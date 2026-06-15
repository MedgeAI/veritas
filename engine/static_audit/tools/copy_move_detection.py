"""Copy-move detection tool for panel-level forensic analysis.

This module detects copy-move manipulation within and across figures by
matching local feature keypoints between panel pairs. The algorithm:

1. For each panel pair (intra-figure or cross-figure):
   a. Detect keypoints (ORB default, SIFT fallback)
   b. Compute descriptors
   c. BFMatcher initial matching
   d. Lowe's ratio test (ratio=0.75)
   e. If >= min_matches good matches, compute homography (RANSAC)
   f. Compute inlier count
   g. Score = inlier_count / min(keypoints_A, keypoints_B)
   h. If score > min_score, optionally generate overlay image

Outputs image_relationship records for downstream finding pipeline.
"""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path
from typing import Any

from engine.static_audit.visual_constants import COPY_MOVE_DEFAULTS
from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def _try_import_cv2():
    """Try to import cv2; return module or None."""
    try:
        import cv2
        return cv2
    except ImportError:
        return None


def _try_import_numpy():
    """Try to import numpy; return module or None."""
    try:
        import numpy as np
        return np
    except ImportError:
        return None


def _load_image(cv2, path: Path):
    """Load image as grayscale numpy array. Returns None on failure."""
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    return image


def _detect_keypoints_descriptors(cv2, image, method: str):
    """Detect keypoints and compute descriptors.

    Args:
        cv2: OpenCV module
        image: Grayscale image
        method: "orb" or "sift"

    Returns:
        (keypoints, descriptors) or (None, None) on failure
    """
    if method == "sift":
        detector = cv2.SIFT_create()
    else:
        # ORB: free, fast, patent-free
        detector = cv2.ORB_create(nfeatures=5000)

    keypoints, descriptors = detector.detectAndCompute(image, None)
    return keypoints, descriptors


def _match_descriptors(cv2, desc_a, desc_b, method: str, ratio_threshold: float):
    """Match descriptors with BFMatcher + Lowe's ratio test.

    Args:
        cv2: OpenCV module
        desc_a: Descriptors for image A
        desc_b: Descriptors for image B
        method: "orb" or "sift" (determines distance metric)
        ratio_threshold: Lowe's ratio test threshold

    Returns:
        List of (queryIdx, trainIdx) good match pairs
    """
    if desc_a is None or desc_b is None:
        return []
    if len(desc_a) < 2 or len(desc_b) < 2:
        return []

    norm_type = cv2.NORM_HAMMING if method == "orb" else cv2.NORM_L2
    bf = cv2.BFMatcher(norm_type, crossCheck=False)

    raw_matches = bf.knnMatch(desc_a, desc_b, k=2)

    good_matches = []
    for match_pair in raw_matches:
        if len(match_pair) < 2:
            continue
        m, n = match_pair
        if m.distance < ratio_threshold * n.distance:
            good_matches.append((m.queryIdx, m.trainIdx))

    return good_matches


def _compute_homography(cv2, np, kp_a, kp_b, matches, ransac_threshold: float):
    """Compute homography using RANSAC.

    Args:
        cv2: OpenCV module
        np: NumPy module
        kp_a: Keypoints from image A
        kp_b: Keypoints from image B
        matches: List of (queryIdx, trainIdx) pairs
        ransac_threshold: RANSAC reprojection threshold

    Returns:
        (homography_matrix, inlier_mask) or (None, None)
    """
    if len(matches) < 4:
        return None, None

    pts_a = np.float32([kp_a[m[0]].pt for m in matches]).reshape(-1, 1, 2)
    pts_b = np.float32([kp_b[m[1]].pt for m in matches]).reshape(-1, 1, 2)

    matrix, mask = cv2.findHomography(pts_a, pts_b, cv2.RANSAC, ransac_threshold)

    if matrix is None or mask is None:
        return None, None

    return matrix, mask.ravel()


def _generate_overlay_image(cv2, np, img_a_path: Path, img_b_path: Path,
                            homography, overlay_path: Path) -> bool:
    """Generate overlay visualization of matched panels.

    Args:
        cv2: OpenCV module
        np: NumPy module
        img_a_path: Path to source panel image
        img_b_path: Path to target panel image
        homography: 3x3 homography matrix
        overlay_path: Output path for overlay image

    Returns:
        True if overlay was generated successfully
    """
    try:
        img_a = cv2.imread(str(img_a_path), cv2.IMREAD_COLOR)
        img_b = cv2.imread(str(img_b_path), cv2.IMREAD_COLOR)
        if img_a is None or img_b is None:
            return False

        h_b, w_b = img_b.shape[:2]

        # Warp image A into B's coordinate frame
        warped = cv2.warpPerspective(img_a, homography, (w_b, h_b))

        # Convert warped to grayscale for blending
        warped_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        img_b_gray = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)

        # Create overlay: red channel shows warped A, green shows B
        overlay = np.zeros((h_b, w_b, 3), dtype=np.uint8)
        overlay[:, :, 0] = warped_gray  # Red = source
        overlay[:, :, 1] = img_b_gray   # Green = target

        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(overlay_path), overlay)
        return True
    except Exception:
        return False


def _matrix_to_list(matrix) -> list[list[float]]:
    """Convert numpy 3x3 matrix to nested Python list."""
    return [[round(float(matrix[i][j]), 6) for j in range(3)] for i in range(3)]


def _resolve_panel_image_path(panel: dict, workdir: Path) -> Path | None:
    """Resolve the absolute path to a panel crop image.

    Looks for crop_path first, then source_image_path in figure_evidence.
    """
    crop_path = panel.get("crop_path", "")
    if crop_path:
        candidate = workdir / crop_path
        if candidate.exists():
            return candidate

    # Fallback: try parent figure source_image_path (for single-panel figures)
    return None


def _determine_source_type(panel_a: dict, panel_b: dict) -> str:
    """Determine whether the relationship is intra-figure or cross-figure.

    Returns:
        "copy_move_single" if same parent figure, "copy_move_cross" otherwise
    """
    fig_a = panel_a.get("parent_figure_id", "")
    fig_b = panel_b.get("parent_figure_id", "")
    if fig_a and fig_b and fig_a == fig_b:
        return "copy_move_single"
    return "copy_move_cross"


def _empty_result(
    status: str,
    panel_count: int = 0,
    errors: list[str] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Build an empty result dict with the canonical schema."""
    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/copy_move_detection.py",
        "status": status,
        "method": COPY_MOVE_DEFAULTS["method"],
        "panel_count": panel_count,
        "pair_count_examined": 0,
        "relationship_count": 0,
        "relationships": [],
        "errors": errors or [],
        "limitations": limitations or [],
    }


def detect_copy_move(
    panel_evidence: list[dict],
    figure_evidence: list[dict],
    *,
    workdir: Path,
    method: str = "orb",
    min_matches: int = COPY_MOVE_DEFAULTS["min_matches"],
    ratio_threshold: float = COPY_MOVE_DEFAULTS["ratio_threshold"],
    ransac_threshold: float = COPY_MOVE_DEFAULTS["ransac_threshold"],
    min_score: float = COPY_MOVE_DEFAULTS["min_score"],
    max_relationships: int = COPY_MOVE_DEFAULTS["max_relationships"],
    generate_overlays: bool = COPY_MOVE_DEFAULTS["generate_overlays"],
) -> dict[str, Any]:
    """Detect copy-move manipulation between panel pairs.

    Args:
        panel_evidence: List of PanelEvidence dicts from panel extraction.
        figure_evidence: List of FigureEvidence dicts (used for context).
        workdir: Working directory for resolving image paths and writing overlays.
        method: Feature detection method ("orb" or "sift").
        min_matches: Minimum good matches to attempt homography.
        ratio_threshold: Lowe's ratio test threshold.
        ransac_threshold: RANSAC reprojection threshold in pixels.
        min_score: Minimum score to emit a relationship.
        max_relationships: Maximum relationships to emit.
        generate_overlays: Whether to generate overlay images.

    Returns:
        Canonical result dict with schema_version, status, relationships, etc.
    """
    cv2 = _try_import_cv2()
    if cv2 is None:
        return _empty_result(
            "not_available",
            panel_count=len(panel_evidence),
            errors=["OpenCV is not installed; copy-move detection was not computed."],
            limitations=["Install opencv-python-headless to enable copy-move detection."],
        )

    np = _try_import_numpy()
    if np is None:
        return _empty_result(
            "not_available",
            panel_count=len(panel_evidence),
            errors=["NumPy is not installed; copy-move detection was not computed."],
            limitations=["Install numpy to enable copy-move detection."],
        )

    if method not in ("orb", "sift"):
        return _empty_result(
            "failed",
            panel_count=len(panel_evidence),
            errors=[f"Unsupported method: {method!r}. Use 'orb' or 'sift'."],
        )

    workdir = Path(workdir)

    # Build panel id -> resolved image path map
    panel_paths: dict[str, Path] = {}
    for panel in panel_evidence:
        pid = panel.get("panel_id", "")
        if not pid:
            continue
        resolved = _resolve_panel_image_path(panel, workdir)
        if resolved is not None:
            panel_paths[pid] = resolved

    loadable_panels = [p for p in panel_evidence if p.get("panel_id") in panel_paths]

    if len(loadable_panels) < 2:
        return _empty_result(
            "skipped",
            panel_count=len(panel_evidence),
            errors=[],
            limitations=[
                f"Need at least 2 panels with loadable images, got {len(loadable_panels)}."
            ],
        )

    # Load images and compute keypoints/descriptors once per panel
    panel_cache: dict[str, dict] = {}
    for panel in loadable_panels:
        pid = panel["panel_id"]
        img_path = panel_paths[pid]
        gray = _load_image(cv2, img_path)
        if gray is None:
            continue
        kps, descs = _detect_keypoints_descriptors(cv2, gray, method)
        if kps is None or descs is None or len(kps) < 2:
            continue
        panel_cache[pid] = {
            "image_path": img_path,
            "gray": gray,
            "keypoints": kps,
            "descriptors": descs,
            "panel": panel,
        }

    usable_ids = list(panel_cache.keys())
    if len(usable_ids) < 2:
        return _empty_result(
            "skipped",
            panel_count=len(panel_evidence),
            errors=[],
            limitations=[
                f"Need at least 2 panels with detectable keypoints, got {len(usable_ids)}."
            ],
        )

    # Pairwise comparison
    relationships: list[dict] = []
    pair_count = 0
    overlay_dir = workdir / "visual" / "overlays"

    rel_counter = 0

    for pid_a, pid_b in combinations(usable_ids, 2):
        pair_count += 1

        cache_a = panel_cache[pid_a]
        cache_b = panel_cache[pid_b]

        matches = _match_descriptors(
            cv2,
            cache_a["descriptors"],
            cache_b["descriptors"],
            method,
            ratio_threshold,
        )

        if len(matches) < min_matches:
            continue

        homography, inlier_mask = _compute_homography(
            cv2, np,
            cache_a["keypoints"],
            cache_b["keypoints"],
            matches,
            ransac_threshold,
        )

        if homography is None or inlier_mask is None:
            continue

        inlier_count = int(inlier_mask.sum())
        denominator = min(len(cache_a["keypoints"]), len(cache_b["keypoints"]))
        score = inlier_count / denominator if denominator > 0 else 0.0

        if score < min_score:
            continue

        rel_counter += 1
        relationship_id = f"IR-{rel_counter:04d}"
        source_type = _determine_source_type(cache_a["panel"], cache_b["panel"])
        match_method = f"{method}_ransac"

        overlay_rel_path: str | None = None
        if generate_overlays:
            overlay_filename = f"{relationship_id}.png"
            overlay_full_path = overlay_dir / overlay_filename
            ok = _generate_overlay_image(
                cv2, np,
                cache_a["image_path"],
                cache_b["image_path"],
                homography,
                overlay_full_path,
            )
            if ok:
                overlay_rel_path = f"visual/overlays/{overlay_filename}"

        relationships.append({
            "relationship_id": relationship_id,
            "source_type": source_type,
            "source_panel_id": pid_a,
            "target_panel_id": pid_b,
            "score": round(score, 6),
            "match_method": match_method,
            "inlier_count": inlier_count,
            "homography": _matrix_to_list(homography),
            "overlay_path": overlay_rel_path,
        })

        if len(relationships) >= max_relationships:
            break

    limitations: list[str] = []
    if len(relationships) >= max_relationships:
        limitations.append(
            f"Reached max_relationships limit ({max_relationships}); "
            "additional pairs were not emitted."
        )

    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/copy_move_detection.py",
        "status": "ran",
        "method": method,
        "panel_count": len(panel_evidence),
        "pair_count_examined": pair_count,
        "relationship_count": len(relationships),
        "relationships": relationships,
        "errors": [],
        "limitations": limitations,
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Detect copy-move manipulation between panel pairs."
    )
    parser.add_argument(
        "panel_json",
        help="Path to JSON file containing panel_evidence list.",
    )
    parser.add_argument(
        "--figure-json",
        default=None,
        help="Path to JSON file containing figure_evidence list (optional).",
    )
    parser.add_argument("--output", required=True, help="Output JSON path.")
    parser.add_argument(
        "--workdir",
        required=True,
        help="Working directory for resolving panel image paths and writing overlays.",
    )
    parser.add_argument(
        "--method",
        choices=["orb", "sift"],
        default=COPY_MOVE_DEFAULTS["method"],
        help="Feature detection method.",
    )
    parser.add_argument(
        "--min-matches",
        type=int,
        default=COPY_MOVE_DEFAULTS["min_matches"],
        help="Minimum good matches to attempt homography.",
    )
    parser.add_argument(
        "--ratio-threshold",
        type=float,
        default=COPY_MOVE_DEFAULTS["ratio_threshold"],
        help="Lowe's ratio test threshold.",
    )
    parser.add_argument(
        "--ransac-threshold",
        type=float,
        default=COPY_MOVE_DEFAULTS["ransac_threshold"],
        help="RANSAC reprojection threshold in pixels.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=COPY_MOVE_DEFAULTS["min_score"],
        help="Minimum score to emit a relationship.",
    )
    parser.add_argument(
        "--max-relationships",
        type=int,
        default=COPY_MOVE_DEFAULTS["max_relationships"],
        help="Maximum relationships to emit.",
    )
    parser.add_argument(
        "--no-overlays",
        action="store_true",
        help="Skip overlay image generation.",
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    panel_json_path = Path(args.panel_json).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    workdir = Path(args.workdir).expanduser().resolve()

    if not panel_json_path.exists():
        result = _empty_result(
            "failed",
            errors=[f"Panel JSON not found: {panel_json_path}"],
        )
    else:
        panel_data = json.loads(panel_json_path.read_text(encoding="utf-8"))

        # Accept either a list of panels or a dict with "panels" key
        if isinstance(panel_data, list):
            panel_evidence = panel_data
        elif isinstance(panel_data, dict):
            panel_evidence = panel_data.get("panels", [])
        else:
            panel_evidence = []

        # Load figure evidence if provided
        figure_evidence: list[dict] = []
        if args.figure_json:
            figure_json_path = Path(args.figure_json).expanduser().resolve()
            if figure_json_path.exists():
                fig_data = json.loads(figure_json_path.read_text(encoding="utf-8"))
                if isinstance(fig_data, list):
                    figure_evidence = fig_data
                elif isinstance(fig_data, dict):
                    # Accept both list of figures or a dict with figure_evidence key
                    fe = fig_data.get("figure_evidence")
                    if isinstance(fe, list):
                        figure_evidence = fe
                    elif isinstance(fig_data.get("figure_evidence"), dict):
                        figure_evidence = [fig_data["figure_evidence"]]

        result = detect_copy_move(
            panel_evidence,
            figure_evidence,
            workdir=workdir,
            method=args.method,
            min_matches=args.min_matches,
            ratio_threshold=args.ratio_threshold,
            ransac_threshold=args.ransac_threshold,
            min_score=args.min_score,
            max_relationships=args.max_relationships,
            generate_overlays=not args.no_overlays,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps({
        "output": str(output_path),
        "status": result["status"],
        "relationship_count": result["relationship_count"],
    }, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
