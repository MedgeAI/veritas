"""Shared constants for visual forensics subsystem.

This module defines tool IDs, score thresholds, and risk level mappings
used across visual forensics tools and pipeline.
"""

from __future__ import annotations

# Tool IDs for visual forensics tools
TOOL_ID_PANEL_EXTRACTION = "visual.panel_extraction"
TOOL_ID_COPY_MOVE = "visual.copy_move"
TOOL_ID_FINDING_PIPELINE = "visual.finding_pipeline"

# Score thresholds for risk level mapping
SCORE_THRESHOLD_CRITICAL = 0.7
SCORE_THRESHOLD_HIGH = 0.4
SCORE_THRESHOLD_MEDIUM = 0.25

# Default parameters for panel extraction
PANEL_EXTRACTION_DEFAULTS = {
    "min_area_ratio": 0.05,  # Minimum panel area as fraction of image area
    "max_area_ratio": 0.95,  # Maximum panel area as fraction of image area
    "min_extent": 0.6,  # Minimum extent (contour area / bounding rect area)
    "min_panel_count": 1,
    "max_panel_count": 30,
}

# Default parameters for copy-move detection
COPY_MOVE_DEFAULTS = {
    "method": "orb",  # "orb" (faster, free) or "sift" (better accuracy)
    "min_matches": 10,  # Minimum number of good matches to consider
    "ratio_threshold": 0.75,  # Lowe's ratio test threshold
    "ransac_threshold": 3.0,  # RANSAC reprojection threshold
    "min_score": 0.15,  # Minimum score to emit a relationship
    "max_relationships": 500,  # Maximum number of relationships to emit
    "generate_overlays": True,  # Whether to generate overlay images
}

# Default parameters for visual finding pipeline
FINDING_PIPELINE_DEFAULTS = {
    "high_score_threshold": SCORE_THRESHOLD_HIGH,
    "critical_score_threshold": SCORE_THRESHOLD_CRITICAL,
}


def score_to_risk_level(score: float) -> str:
    """Map a score to a risk level.

    Args:
        score: Confidence score in [0.0, 1.0]

    Returns:
        Risk level: "critical", "high", "medium", or "low"
    """
    if score >= SCORE_THRESHOLD_CRITICAL:
        return "critical"
    if score >= SCORE_THRESHOLD_HIGH:
        return "high"
    if score >= SCORE_THRESHOLD_MEDIUM:
        return "medium"
    return "low"


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
}
