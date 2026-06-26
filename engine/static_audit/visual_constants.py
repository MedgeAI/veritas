"""Shared constants for visual forensics subsystem.

This module defines tool IDs, score thresholds, and risk level mappings
used across visual forensics tools and pipeline.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# dHash rotation helpers (rotation-invariant pre-filter)
#
# dHash encodes horizontal column gradients (mean(col_i) > mean(col_{i+1})).
# When an image is rotated 90°, horizontal gradients become vertical gradients,
# so the original dHash carries NO information about what the rotated dHash
# would be.  Therefore we CANNOT predict rotated hashes via bit permutation.
#
# Correct approach: actually rotate the image, then recompute dHash.
# Callers must use `dhash_rotations_from_image(img)` or `dhash_rotations_from_path(path)`
# to obtain a tuple of 4 hashes (0°, 90°, 180°, 270°), then pass both tuples
# to `min_hamming_rotations(h1_tuple, h2_tuple)` for comparison.
# ---------------------------------------------------------------------------


def _dhash_single(img, hash_size: int = 8) -> int:
    """Compute dHash for a single PIL Image (or path). Internal helper."""
    from PIL import Image

    if isinstance(img, (str,)):
        img = Image.open(img)
        close_after = True
    elif not hasattr(img, "rotate"):
        from pathlib import Path

        img = Image.open(Path(img))
        close_after = True
    else:
        close_after = False

    try:
        resized = img.convert("L").resize((hash_size + 1, hash_size))
        pixels = list(resized.get_flattened_data())
    finally:
        if close_after:
            img.close()

    value = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            value = (value << 1) | int(left > right)  # type: ignore[assignment,operator]
    return value


def dhash_rotations_from_image(img, hash_size: int = 8) -> tuple[int, int, int, int]:
    """Compute dHash for an image at 0°, 90°, 180°, 270° by actual rotation.

    Uses PIL.Image.rotate() for 90/180/270 (transpose-based, exact & fast).
    Returns (h0, h90, h180, h270).
    """
    from PIL import Image

    if isinstance(img, (str,)):
        from pathlib import Path

        img = Image.open(Path(img))
    elif not hasattr(img, "rotate"):
        from pathlib import Path

        img = Image.open(Path(img))

    h0 = _dhash_single(img, hash_size)
    h90 = _dhash_single(img.rotate(90, expand=True), hash_size)
    h180 = _dhash_single(img.rotate(180), hash_size)
    h270 = _dhash_single(img.rotate(270, expand=True), hash_size)
    return (h0, h90, h180, h270)


dhash_rotations_from_path = dhash_rotations_from_image  # alias: accepts path or image


def min_hamming_rotations(
    h1_tuple: tuple[int, int, int, int],
    h2_tuple: tuple[int, int, int, int],
) -> tuple[int, int]:
    """Return (min_distance, best_angle) over all 16 pairwise comparisons.

    Each input is a tuple of 4 hashes (0°, 90°, 180°, 270°) computed by
    actually rotating the image.  We try all 16 pairs (4 rotations of h1
    × 4 rotations of h2) and report the minimum Hamming distance and the
    relative rotation angle that produced it.

    The angle semantics: if h1_tuple[i] and h2_tuple[j] give the best match,
    then h1's i-th rotation view equals h2's j-th rotation view.  This means
    h2 was obtained by rotating h1 by (A_i - A_j) mod 360 degrees.
    """
    angles = (0, 90, 180, 270)
    best_dist = 65
    best_angle = 0
    for a1, rot1 in zip(angles, h1_tuple):
        for a2, rot2 in zip(angles, h2_tuple):
            dist = bin(rot1 ^ rot2).count("1")
            if dist < best_dist:
                best_dist = dist
                best_angle = (a1 - a2) % 360
    return best_dist, best_angle


# Tool IDs for visual forensics tools
TOOL_ID_PANEL_EXTRACTION = "visual.panel_extraction"
TOOL_ID_COPY_MOVE = "visual.copy_move"
TOOL_ID_FINDING_PIPELINE = "visual.finding_pipeline"

# Score thresholds for risk level mapping
SCORE_THRESHOLD_CRITICAL = 0.7
SCORE_THRESHOLD_HIGH = 0.4
SCORE_THRESHOLD_MEDIUM = 0.25

# Default parameters for copy-move detection
COPY_MOVE_DEFAULTS = {
    "method": "orb",  # "orb" (faster, free) or "sift" (better accuracy)
    "min_matches": 10,  # Minimum number of good matches to consider
    "ratio_threshold": 0.75,  # Lowe's ratio test threshold
    "ransac_threshold": 3.0,  # RANSAC reprojection threshold
    "min_score": 0.50,  # Minimum score to emit a relationship
    "max_relationships": 500,  # Maximum number of relationships to emit
}

# Panel types that are code-generated and should skip copy_move/overlap_reuse/trufor detection
# Only exact_duplicate (SHA-256) is retained for these modalities.
# Flow Cytometry is NOT skipped — FACS plot reuse is a genuine image-level
# forensics signal (BioFors dataset includes FACS as a dedicated category).
VISUAL_SKIP_PANEL_TYPES = {"Graphs"}
VISUAL_SKIP_CONFIDENCE_THRESHOLD = 0.5  # Only skip if YOLOv5 confidence >= this


# Modality weights for dual-dimension risk scoring.
# Higher weight = higher forensic relevance for the modality.
MODALITY_WEIGHT: dict[str, float] = {
    "Blots": 1.0,
    "Microscopy": 0.9,
    "Body Imaging": 0.6,
    "Flow Cytometry": 0.2,
    "Graphs": 0.2,
}
_DEFAULT_MODALITY_WEIGHT = 0.5


def compute_risk_level(score: float, modality: str | None = None) -> str:
    """Map a score to a risk level, adjusted by modality weight.

    The final score is ``score * weight`` where *weight* is:

    * **1.0** when *modality* is ``None`` (backward-compatible — no
      modality adjustment).
    * :data:`MODALITY_WEIGHT` value when *modality* is a recognised key.
    * **0.5** when *modality* is a string not present in
      :data:`MODALITY_WEIGHT` (unknown modality).

    Existing thresholds (0.7 / 0.4 / 0.25) are then applied to the
    weighted score.

    Args:
        score: Confidence score in [0.0, 1.0].
        modality: Panel type string (e.g. "Blots", "Graphs").
            ``None`` disables modality weighting entirely.

    Returns:
        Risk level: "critical", "high", "medium", or "low".
    """
    if modality is None:
        weight = 1.0
    else:
        weight = MODALITY_WEIGHT.get(modality, _DEFAULT_MODALITY_WEIGHT)
    final_score = score * weight
    if final_score >= SCORE_THRESHOLD_CRITICAL:
        return "critical"
    if final_score >= SCORE_THRESHOLD_HIGH:
        return "high"
    if final_score >= SCORE_THRESHOLD_MEDIUM:
        return "medium"
    return "low"


def score_to_risk_level(score: float) -> str:
    """Backward-compatible wrapper — calls compute_risk_level(score, None)."""
    return compute_risk_level(score, None)


# Benign explanations for different finding categories
BENIGN_EXPLANATIONS = {
    "copy_move_single": [
        "合法的实验对照（如 loading control）",
        "重复的模板结构（如 gel lane layout）",
        "图像处理的 artifacts（如 background subtraction）",
        "相同的生物学主体或对照样本出现在多个 panel 中",
    ],
    "copy_move_cross": [
        "同一细胞系或组织切片在不同时间点或条件下的成像",
        "跨实验共享的阳性/阴性对照是标准做法",
        "图像在图片组装时被合法重复作为占位符，应该被替换",
    ],
    "exact_duplicate": [
        "字节级相同的文件可能来自导出流程的重复，而非操控",
        "同一原始图像文件在出版系统中被多个 figure panel 引用",
    ],
    "dhash_similar": [
        "dHash 候选只是分类线索，需要人工复核",
        "相似的图像可能来自相似的实验条件或样本",
    ],
    "forged_region_suspicious": [
        "TruFor 神经网络检测的伪造区域是筛查信号，需要人工复核原始图像",
        "高 integrity_score 可能由图像拼接、过度后处理或非伪造的图像编辑引起",
        "部分检测可能源于正常的图像裁剪、标注或格式转换",
    ],
    "overlap_reuse_cross_panel": [
        "可能是同一原始视野的不同通道、合法 shared control 或重复展示的 reference panel。",
        "某些标准化实验流程中，同一对照图像在不同 figure 中重复展示是常见做法。",
        "图像可能在出版组装过程中被意外复用为占位符。",
    ],
}

# Manual review questions for different finding categories
MANUAL_REVIEW_QUESTIONS = {
    "copy_move_single": [
        "验证匹配的 panel 是否描绘同一实验主体或独立重复",
        "检查图注和方法部分是否有合法的对照重用",
        "比较 panel 标签（a, b, c）与图注以确认它们代表不同条件",
    ],
    "copy_move_cross": [
        "检查跨图匹配的 panel 是否共享生物学来源",
        "验证图注是否描述了不同实验或同一实验",
        "审查方法部分是否有共享对照或参考样本",
    ],
    "exact_duplicate": [
        "验证字节级相同的文件是否来自合法的数据导出流程",
        "检查是否有多个 figure 引用了同一原始图像",
    ],
    "dhash_similar": [
        "人工复核 dHash 候选，确认是否为合法的相似性",
        "检查相似的图像是否来自相似的实验条件",
    ],
    "forged_region_suspicious": [
        "在原始图像上复核 TruFor 标记的可疑区域，判断是否为独立实验证据",
        "检查 localization heatmap 是否与图像拼接、裁剪边界或正常后处理区域吻合",
        "结合图注和实验设计判断该区域是否可能来自合理的图像操作",
    ],
    "overlap_reuse_cross_panel": [
        "两个 panel 是否声称代表不同实验条件、样本、时间点或处理组？",
        "图注或方法是否声明 shared control / same field of view？",
        "作者能否提供原始显微图、仪器导出文件或未裁剪图？",
        "两个 panel 的 figure label 是否暗示它们来自不同的实验？",
    ],
}


def trufor_integrity_risk_level(integrity_score: float) -> str:
    """Map TruFor integrity_score to risk level.

    - score >= 0.9 -> "high"
    - score >= 0.7 -> "medium"
    - score >= 0.5 -> "low"
    """
    if integrity_score >= 0.9:
        return "high"
    if integrity_score >= 0.7:
        return "medium"
    return "low"
