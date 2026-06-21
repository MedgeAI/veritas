"""Visual overlap/reuse detection tool.

Detects cross-panel local image region reuse via tile-level retrieval and
geometric verification.  The pipeline:

1. Load panel_evidence; filter out whole-figure fallbacks and undersized panels.
2. Generate overlapping tiles per panel (tile_size × tile_size, tile_stride).
3. Compute dHash per tile for cheap candidate retrieval.
4. Find candidate tile pairs across different panels (Hamming distance threshold).
5. Merge tile candidates into panel-level pairs.
6. Verify panel pairs via RootSIFT + MAGSAC++ (ELIS keypoint subprocess).
7. Estimate homography + overlap polygon from inlier matches.
8. Generate overlay / keypoints / warped / mask evidence images.
9. Emit ``visual/overlap_reuse.json``.

Failure isolation: any exception is caught and recorded as a limitation;
the tool never blocks the audit pipeline.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from engine.static_audit.visual_constants import (
    dhash_rotations_from_image,
    min_hamming_rotations,
)
from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
MIN_PANEL_SIZE = 64

# dHash Hamming distance threshold for tile candidate retrieval.
# Tiles from the same physical region at similar scale should have distance < 20.
_TILE_DHASH_THRESHOLD = 24


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dhash_image(img: Image.Image, hash_size: int = 8) -> tuple[int, int, int, int]:
    """Compute rotation-invariant dHash tuple for a PIL image (0°, 90°, 180°, 270°)."""
    return dhash_rotations_from_image(img, hash_size)


def _hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _resolve_panel_image_path(panel: dict, workdir: Path) -> Path | None:
    crop = str(panel.get("crop_path") or "")
    if not crop:
        return None
    candidate = workdir / crop
    if candidate.exists():
        return candidate
    return None


def _is_valid_panel(panel: dict) -> bool:
    """Skip whole-figure fallback panels and panels with missing metadata."""
    method = panel.get("extraction_method") or ""
    if method == "whole_figure_fallback":
        return False
    meta = panel.get("metadata") or {}
    if meta.get("extraction_method") == "whole_figure_fallback":
        return False
    return True


# ---------------------------------------------------------------------------
# Tile generation
# ---------------------------------------------------------------------------


def _generate_tiles(
    panel_id: str,
    image_path: Path,
    tile_size: int,
    tile_stride: int,
) -> list[dict[str, Any]]:
    """Generate overlapping tiles from a panel image.

    Each tile record contains its bounding box in panel coordinates,
    its dHash, and its PIL Image (for later warping/overlay).
    """
    try:
        img = Image.open(image_path)
    except OSError:
        return []

    w, h = img.size
    if w < MIN_PANEL_SIZE or h < MIN_PANEL_SIZE:
        return []

    tiles: list[dict[str, Any]] = []
    tile_idx = 0
    for y in range(0, max(1, h - tile_size + 1), tile_stride):
        for x in range(0, max(1, w - tile_size + 1), tile_stride):
            box = (x, y, min(x + tile_size, w), min(y + tile_size, h))
            crop = img.crop(box)
            if crop.size[0] < 32 or crop.size[1] < 32:
                continue
            tiles.append(
                {
                    "tile_id": f"{panel_id}_tile_{tile_idx}",
                    "panel_id": panel_id,
                    "bbox": list(box),
                    "dhash": _dhash_image(crop),
                    "image": crop,
                }
            )
            tile_idx += 1

    return tiles


# ---------------------------------------------------------------------------
# Candidate retrieval
# ---------------------------------------------------------------------------


def _retrieve_tile_candidates(
    all_tiles: list[dict[str, Any]],
    max_candidate_pairs: int,
) -> list[dict[str, Any]]:
    """Find tile pairs from DIFFERENT panels with low rotation-invariant Hamming distance.

    Uses 4-rotation dHash comparison (Plan C) so that 90° rotated reuse is not
    missed by the pre-filter.  Returns list of {tile_a, tile_b, distance,
    best_rotation_angle} sorted by distance ascending.
    """
    candidates: list[dict[str, Any]] = []
    n = len(all_tiles)
    if n < 2:
        return candidates

    for i in range(n):
        tile_a = all_tiles[i]
        for j in range(i + 1, n):
            tile_b = all_tiles[j]
            if tile_a["panel_id"] == tile_b["panel_id"]:
                continue
            dist, best_angle = min_hamming_rotations(tile_a["dhash"], tile_b["dhash"])
            if dist <= _TILE_DHASH_THRESHOLD:
                candidates.append(
                    {
                        "tile_a": tile_a,
                        "tile_b": tile_b,
                        "distance": dist,
                        "best_rotation_angle": best_angle,
                    }
                )

    candidates.sort(key=lambda c: c["distance"])
    return candidates[:max_candidate_pairs]


def _merge_to_panel_pairs(
    tile_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group tile candidates by (source_panel, target_panel).

    For each panel pair, keep the best tile candidates and count.
    """
    from collections import defaultdict

    panel_pair_map: dict[frozenset, list[dict[str, Any]]] = defaultdict(list)
    for cand in tile_candidates:
        key = frozenset({cand["tile_a"]["panel_id"], cand["tile_b"]["panel_id"]})
        panel_pair_map[key].append(cand)

    result: list[dict[str, Any]] = []
    for _key, tile_cands in panel_pair_map.items():
        panel_ids = sorted(
            {c["tile_a"]["panel_id"] for c in tile_cands}
            | {c["tile_b"]["panel_id"] for c in tile_cands}
        )
        if len(panel_ids) != 2:
            continue
        best_dist = min(c["distance"] for c in tile_cands)
        # Pick the rotation angle of the best (lowest-distance) tile candidate
        best_angle = next(
            c.get("best_rotation_angle", 0)
            for c in sorted(tile_cands, key=lambda c: c["distance"])
        )
        result.append(
            {
                "source_panel_id": panel_ids[0],
                "target_panel_id": panel_ids[1],
                "tile_candidate_count": len(tile_cands),
                "best_tile_distance": best_dist,
                "best_rotation_angle": best_angle,
                "tile_candidates": tile_cands,
            }
        )

    result.sort(key=lambda p: (p["best_tile_distance"], -p["tile_candidate_count"]))
    return result


# ---------------------------------------------------------------------------
# Geometric verification via ELIS keypoint runner
# ---------------------------------------------------------------------------


def _run_elis_cross_verification(
    panel_pairs: list[dict[str, Any]],
    panel_path_map: dict[str, Path],
    workdir: Path,
    min_inliers: int,
) -> list[dict[str, Any]]:
    """Verify panel pairs via ELIS RootSIFT+MAGSAC++ cross-image detection."""
    pairs_for_elis = []
    for idx, pp in enumerate(panel_pairs):
        src_path = panel_path_map.get(pp["source_panel_id"])
        tgt_path = panel_path_map.get(pp["target_panel_id"])
        if src_path is None or tgt_path is None:
            continue
        pairs_for_elis.append(
            {
                "pair_id": f"overlap_{idx:04d}",
                "source": str(src_path),
                "target": str(tgt_path),
                "source_panel_id": pp["source_panel_id"],
                "target_panel_id": pp["target_panel_id"],
            }
        )

    if not pairs_for_elis:
        return []

    output_dir = workdir / "visual" / "overlap"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "engine.static_audit.tools._elis_copy_move_runner"],
            input=json.dumps(
                {
                    "mode": "cross",
                    "pairs": pairs_for_elis,
                    "output_dir": str(output_dir),
                    "min_keypoints": min_inliers,
                    "min_area": 0.0,
                    "check_flip": True,
                }
            ),
            capture_output=True,
            text=True,
            timeout=max(600, len(pairs_for_elis) * 10),
            check=False,
        )
        if proc.returncode != 0:
            return []
        result = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return []

    return result.get("results", [])


# ---------------------------------------------------------------------------
# Overlap polygon computation
# ---------------------------------------------------------------------------


def _compute_overlap_polygon(
    src_w: int,
    src_h: int,
    tgt_w: int,
    tgt_h: int,
    homography: list[list[float]] | None,
) -> tuple[float, float] | None:
    """Compute overlap area ratios from homography.

    Returns (overlap_area_ratio_source, overlap_area_ratio_target) or None
    if homography is invalid.
    """
    if not homography or len(homography) != 3:
        return None

    try:
        h_mat = []
        for row in homography:
            h_mat.append([float(v) for v in row])
        if len(h_mat) != 3 or any(len(r) != 3 for r in h_mat):
            return None
    except (TypeError, ValueError):
        return None

    src_corners = [(0, 0), (src_w, 0), (src_w, src_h), (0, src_h)]
    tgt_corners = [(0, 0), (tgt_w, 0), (tgt_w, tgt_h), (0, tgt_h)]

    transformed: list[tuple[float, float]] = []
    for x, y in src_corners:
        w_ = h_mat[2][0] * x + h_mat[2][1] * y + h_mat[2][2]
        if abs(w_) < 1e-10:
            return None
        tx = (h_mat[0][0] * x + h_mat[0][1] * y + h_mat[0][2]) / w_
        ty = (h_mat[1][0] * x + h_mat[1][1] * y + h_mat[1][2]) / w_
        transformed.append((tx, ty))

    overlap_area = _polygon_intersection_area(transformed, tgt_corners)
    if overlap_area <= 0:
        return None

    src_area = src_w * src_h
    tgt_area = tgt_w * tgt_h
    if src_area <= 0 or tgt_area <= 0:
        return None

    return (
        round(min(1.0, overlap_area / src_area), 4),
        round(min(1.0, overlap_area / tgt_area), 4),
    )


def _polygon_intersection_area(
    poly_a: list[tuple[float, float]],
    poly_b: list[tuple[float, float]],
) -> float:
    """Approximate intersection area via Sutherland-Hodgman clipping.

    For simplicity we compute the overlap of two convex polygons.
    Falls back to bounding-box overlap if clipping fails.
    """
    try:
        clipped = list(poly_a)
        for i in range(len(poly_b)):
            if not clipped:
                return 0.0
            edge_start = poly_b[i]
            edge_end = poly_b[(i + 1) % len(poly_b)]
            clipped = _clip_polygon_by_edge(clipped, edge_start, edge_end)
        return _polygon_area(clipped)
    except Exception:
        # Sutherland-Hodgman clipping can fail on degenerate polygons;
        # fall back to bbox overlap rather than crashing the pipeline.
        return _bbox_overlap_area(poly_a, poly_b)


def _clip_polygon_by_edge(
    polygon: list[tuple[float, float]],
    edge_start: tuple[float, float],
    edge_end: tuple[float, float],
) -> list[tuple[float, float]]:
    """Sutherland-Hodgman: clip polygon by one edge of the clipping polygon."""
    if not polygon:
        return []

    def _inside(p: tuple[float, float]) -> bool:
        return (
            (edge_end[0] - edge_start[0]) * (p[1] - edge_start[1])
            - (edge_end[1] - edge_start[1]) * (p[0] - edge_start[0])
        ) >= 0

    def _intersection(
        p1: tuple[float, float], p2: tuple[float, float]
    ) -> tuple[float, float]:
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = edge_start
        x4, y4 = edge_end
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-12:
            return p1
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    result: list[tuple[float, float]] = []
    for i in range(len(polygon)):
        current = polygon[i]
        next_pt = polygon[(i + 1) % len(polygon)]
        if _inside(current):
            if not _inside(next_pt):
                result.append(_intersection(current, next_pt))
            else:
                result.append(next_pt)
        elif _inside(next_pt):
            result.append(_intersection(current, next_pt))
            result.append(next_pt)
    return result


def _polygon_area(poly: list[tuple[float, float]]) -> float:
    """Shoelace formula for polygon area."""
    n = len(poly)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += poly[i][0] * poly[j][1]
        area -= poly[j][0] * poly[i][1]
    return abs(area) / 2.0


def _bbox_overlap_area(
    poly_a: list[tuple[float, float]],
    poly_b: list[tuple[float, float]],
) -> float:
    """Fallback: bounding box overlap area."""
    if not poly_a or not poly_b:
        return 0.0
    min_ax, min_ay = min(p[0] for p in poly_a), min(p[1] for p in poly_a)
    max_ax, max_ay = max(p[0] for p in poly_a), max(p[1] for p in poly_a)
    min_bx, min_by = min(p[0] for p in poly_b), min(p[1] for p in poly_b)
    max_bx, max_by = max(p[0] for p in poly_b), max(p[1] for p in poly_b)
    overlap_w = max(0, min(max_ax, max_bx) - max(min_ax, min_bx))
    overlap_h = max(0, min(max_ay, max_by) - max(min_ay, min_by))
    return overlap_w * overlap_h


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _empty_result(
    status: str = "skipped",
    errors: list[str] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "tool_id": "visual.overlap_reuse",
        "status": status,
        "panel_count": 0,
        "tile_count": 0,
        "candidate_pair_count": 0,
        "relationship_count": 0,
        "relationships": [],
        "errors": errors or [],
        "limitations": limitations or [],
    }


def detect_overlap_reuse(
    panel_evidence: list[dict],
    figure_evidence: list[dict],
    *,
    workdir: Path,
    tile_size: int = 128,
    tile_stride: int = 64,
    candidate_method: str = "dhash_tile",
    max_candidate_pairs: int = 500,
    min_inliers: int = 10,
    min_overlap_area: float = 0.01,
    max_relationships: int = 500,
) -> dict[str, Any]:
    """Detect cross-panel overlap/reuse via tile-level retrieval + verification.

    Parameters
    ----------
    panel_evidence : list[dict]
        Panel evidence list (from ``visual/panel_evidence.json``).
    figure_evidence : list[dict]
        Figure evidence list (from ``visual/evidence.json``).
    workdir : Path
        Audit output root directory.
    tile_size : int
        Tile window size in pixels.
    tile_stride : int
        Tile stride in pixels.
    candidate_method : str
        Tile candidate retrieval method (``"dhash_tile"`` supported).
    max_candidate_pairs : int
        Maximum tile-level candidate pairs to retain.
    min_inliers : int
        Minimum inlier keypoints for geometric verification.
    min_overlap_area : float
        Minimum overlap area ratio (0-1) to emit a relationship.
    max_relationships : int
        Maximum relationships to emit.

    Returns
    -------
    dict
        Overlap reuse artifact (``visual/overlap_reuse.json``).
    """
    limitations: list[str] = []
    errors: list[str] = []

    # 1. Filter panels
    valid_panels = [p for p in panel_evidence if _is_valid_panel(p)]
    panel_path_map: dict[str, Path] = {}
    for panel in valid_panels:
        path = _resolve_panel_image_path(panel, workdir)
        if path is not None:
            panel_path_map[str(panel.get("panel_id") or "")] = path

    if len(panel_path_map) < 2:
        return _empty_result(
            status="skipped",
            limitations=[
                "Fewer than 2 valid panels with crop images; overlap detection skipped."
            ],
        )

    # 2. Generate tiles
    all_tiles: list[dict[str, Any]] = []
    for panel_id, path in panel_path_map.items():
        tiles = _generate_tiles(panel_id, path, tile_size, tile_stride)
        all_tiles.extend(tiles)

    if not all_tiles:
        return {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "tool_id": "visual.overlap_reuse",
            "status": "skipped",
            "panel_count": len(panel_path_map),
            "tile_count": 0,
            "candidate_pair_count": 0,
            "relationship_count": 0,
            "relationships": [],
            "errors": errors,
            "limitations": [
                "No tiles generated from any panel; overlap detection skipped."
            ],
        }

    # 3. Retrieve tile candidates
    tile_candidates = _retrieve_tile_candidates(all_tiles, max_candidate_pairs)

    if not tile_candidates:
        return {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "tool_id": "visual.overlap_reuse",
            "status": "ran",
            "panel_count": len(panel_path_map),
            "tile_count": len(all_tiles),
            "candidate_pair_count": 0,
            "relationship_count": 0,
            "relationships": [],
            "errors": errors,
            "limitations": [
                "No tile-level candidates found; possible lack of overlap."
            ],
        }

    # 4. Merge to panel pairs
    panel_pairs = _merge_to_panel_pairs(tile_candidates)

    # 5. Geometric verification via ELIS keypoint runner
    verified = _run_elis_cross_verification(
        panel_pairs,
        panel_path_map,
        workdir,
        min_inliers,
    )

    if not verified:
        limitations.append(
            "Tile candidates found but geometric verification produced no matches. "
            "Possible causes: insufficient keypoints, low-texture panels, or ELIS runner failure."
        )
        return {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "tool_id": "visual.overlap_reuse",
            "status": "ran",
            "panel_count": len(panel_path_map),
            "tile_count": len(all_tiles),
            "candidate_pair_count": len(tile_candidates),
            "relationship_count": 0,
            "relationships": [],
            "errors": errors,
            "limitations": limitations,
        }

    # 6. Build relationships with overlap polygon
    relationships: list[dict[str, Any]] = []
    panel_size_map: dict[str, tuple[int, int]] = {}
    for panel_id, path in panel_path_map.items():
        try:
            with Image.open(path) as img:
                panel_size_map[panel_id] = img.size
        except OSError:
            continue

    # Build a lookup from (src, tgt) panel pair -> best_rotation_angle
    rotation_angle_map: dict[tuple[str, str], int] = {}
    for pp in panel_pairs:
        key = (pp["source_panel_id"], pp["target_panel_id"])
        rotation_angle_map[key] = pp.get("best_rotation_angle", 0)

    rel_idx = 0
    for v in verified:
        src_id = str(v.get("source_panel_id") or "")
        tgt_id = str(v.get("target_panel_id") or "")
        inlier_count = int(v.get("inlier_count") or 0)
        if inlier_count < min_inliers:
            continue

        src_size = panel_size_map.get(src_id, (1, 1))
        tgt_size = panel_size_map.get(tgt_id, (1, 1))
        homography = v.get("homography")

        if homography is not None:
            overlap_ratios = _compute_overlap_polygon(
                src_size[0],
                src_size[1],
                tgt_size[0],
                tgt_size[1],
                homography,
            )
            if overlap_ratios is None:
                overlap_src_ratio = 0.0
                overlap_tgt_ratio = 0.0
            else:
                overlap_src_ratio, overlap_tgt_ratio = overlap_ratios
        else:
            overlap_src_ratio = float(v.get("shared_area_source") or 0.0)
            overlap_tgt_ratio = float(v.get("shared_area_target") or 0.0)

        if (
            overlap_src_ratio < min_overlap_area
            and overlap_tgt_ratio < min_overlap_area
        ):
            continue

        score = min(1.0, inlier_count / 200.0)
        overlay_path = v.get("overlay_path")
        transform_type = "homography" if homography is not None else "shared_area"

        ovl_id = f"OVL-{rel_idx:04d}"
        relationships.append(
            {
                "relationship_id": ovl_id,
                "source_type": "overlap_reuse_cross_panel",
                "source_panel_id": src_id,
                "target_panel_id": tgt_id,
                "candidate_method": candidate_method,
                "verification_method": "rootsift_magsac",
                "transform_type": transform_type,
                "inlier_count": inlier_count,
                "inlier_ratio": round(
                    inlier_count / max(1, int(v.get("keypoint_count") or inlier_count)),
                    4,
                ),
                "overlap_area_ratio_source": overlap_src_ratio,
                "overlap_area_ratio_target": overlap_tgt_ratio,
                "score": round(score, 4),
                "overlay_path": overlay_path,
                "flip_detected": bool(v.get("flip_detected", False)),
                "homography": homography,
                "best_rotation_angle": rotation_angle_map.get((src_id, tgt_id), 0),
            }
        )
        rel_idx += 1

        if len(relationships) >= max_relationships:
            break

    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "tool_id": "visual.overlap_reuse",
        "status": "ran",
        "panel_count": len(panel_path_map),
        "tile_count": len(all_tiles),
        "candidate_pair_count": len(tile_candidates),
        "relationship_count": len(relationships),
        "relationships": relationships,
        "errors": errors,
        "limitations": limitations,
    }


# ---------------------------------------------------------------------------
# CLI entry point (for direct invocation)
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Visual overlap/reuse detection")
    parser.add_argument("--workdir", required=True, help="Audit output root directory")
    parser.add_argument("--tile-size", type=int, default=128)
    parser.add_argument("--tile-stride", type=int, default=64)
    parser.add_argument("--max-candidate-pairs", type=int, default=500)
    parser.add_argument("--min-inliers", type=int, default=10)
    parser.add_argument("--min-overlap-area", type=float, default=0.01)
    parser.add_argument("--max-relationships", type=int, default=500)
    args = parser.parse_args()

    workdir = Path(args.workdir)
    panel_path = workdir / "visual" / "panel_evidence.json"
    figure_path = workdir / "visual" / "evidence.json"

    if not panel_path.exists():
        result = _empty_result(
            status="skipped", limitations=["No panel_evidence.json found."]
        )
    else:
        panels = json.loads(panel_path.read_text()) if panel_path.exists() else []
        figures = json.loads(figure_path.read_text()) if figure_path.exists() else []
        result = detect_overlap_reuse(
            panels,
            figures,
            workdir=workdir,
            tile_size=args.tile_size,
            tile_stride=args.tile_stride,
            max_candidate_pairs=args.max_candidate_pairs,
            min_inliers=args.min_inliers,
            min_overlap_area=args.min_overlap_area,
            max_relationships=args.max_relationships,
        )

    output_path = workdir / "visual" / "overlap_reuse.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(
        json.dumps(
            {"status": result["status"], "relationships": result["relationship_count"]}
        )
    )


if __name__ == "__main__":
    main()
