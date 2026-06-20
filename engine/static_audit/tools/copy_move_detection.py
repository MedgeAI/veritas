"""Copy-move detection tool using ELIS RootSIFT+MAGSAC++ keypoint matching.

This module replaces the previous ORB/BFMatcher/RANSAC implementation with
ELIS's RootSIFT+MAGSAC++ pipeline via a subprocess wrapper.

Two detection modes (following ELIS architecture):

Phase 2a -- Single-image copy-move per panel:
    For each panel, detect regions copied within the same panel.
    Catches within-panel forgery (e.g. a blot band duplicated).

Phase 2b -- Cross-figure copy-move with dhash pre-filter:
    Compute dhash for all figure images, select similar pairs (hamming < threshold),
    then verify with RootSIFT+MAGSAC++ cross-image detection.
    Catches cross-figure content reuse.

Both modes call ``_elis_copy_move_runner`` via subprocess for isolation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

from engine.static_audit.visual_constants import COPY_MOVE_DEFAULTS
from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def _dhash(path: Path, hash_size: int = 8) -> int:
    """Compute perceptual difference hash for an image."""
    from PIL import Image

    with Image.open(path) as image:
        resized = image.convert("L").resize((hash_size + 1, hash_size))
        pixels = list(resized.getdata())
    value = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            value = (value << 1) | int(left > right)
    return value


def _hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _resolve_panel_image_path(panel: dict, workdir: Path) -> Path | None:
    """Resolve a panel's crop_path to an absolute path within workdir."""
    crop = str(panel.get("crop_path") or "")
    if not crop:
        return None
    candidate = workdir / crop
    if candidate.exists():
        return candidate
    return None


def _remap_overlay_to_unique(
    relationships: list[dict[str, Any]],
    workdir: Path,
) -> None:
    """Rename overlay files in-place so each relationship has a unique path.

    The ELIS detector derives overlay filenames from input image stems, which
    can collide when different panels share the same crop filename (e.g.
    fallback panels).  This function renames each overlay to a
    relationship-indexed path and updates ``overlay_path`` accordingly.

    When multiple relationships share the same source overlay path, the first
    relationship renames the file; subsequent relationships copy from the
    already-renamed file to their own unique path.
    """
    # Track source paths that have already been moved: original -> current location
    moved_srcs: dict[str, Path] = {}

    for idx, rel in enumerate(relationships):
        raw = rel.get("overlay_path") or ""
        if not raw:
            continue
        src = workdir / raw
        suffix = src.suffix or ".png"
        unique_name = f"rel_{idx:04d}_overlay{suffix}"
        dst = src.parent / unique_name
        if src == dst:
            continue

        if src.exists():
            # Source still at original location — rename it.
            try:
                src.rename(dst)
                rel["overlay_path"] = (
                    str(dst.relative_to(workdir))
                    if dst.is_relative_to(workdir)
                    else str(dst)
                )
                moved_srcs[raw] = dst
            except OSError:
                continue
        elif raw in moved_srcs:
            # Source was already moved by an earlier relationship — copy.
            prev = moved_srcs[raw]
            if prev.exists():
                try:
                    shutil.copy2(prev, dst)
                    rel["overlay_path"] = (
                        str(dst.relative_to(workdir))
                        if dst.is_relative_to(workdir)
                        else str(dst)
                    )
                except OSError:
                    continue


def _empty_result(
    status: str,
    method: str,
    panel_count: int = 0,
    errors: list[str] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/copy_move_detection.py",
        "status": status,
        "method": method,
        "panel_count": panel_count,
        "pair_count_examined": 0,
        "relationship_count": 0,
        "relationships": [],
        "errors": errors or [],
        "limitations": limitations or [],
    }


def _run_elis_runner(
    input_data: dict[str, Any], timeout: int = 3600
) -> dict[str, Any] | None:
    """Call the ELIS copy-move runner subprocess and parse its JSON output."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "engine.static_audit.tools._elis_copy_move_runner"],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


def _run_single_image_detection(
    panels: list[dict[str, Any]],
    workdir: Path,
    min_keypoints: int,
    min_area: float,
) -> list[dict[str, Any]]:
    """Phase 2a: Run single-image copy-move on each panel independently."""
    # Build panel list with absolute paths
    panel_items = []
    for panel in panels:
        crop_path = _resolve_panel_image_path(panel, workdir)
        if crop_path is None:
            continue
        panel_items.append(
            {
                "panel_id": str(panel.get("panel_id") or ""),
                "path": str(crop_path),
            }
        )

    if not panel_items:
        return []

    output_dir = workdir / "copy_move_elis" / "single"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = _run_elis_runner(
        {
            "mode": "single",
            "panels": panel_items,
            "output_dir": str(output_dir),
            "min_keypoints": min_keypoints,
            "min_area": min_area,
        }
    )

    if result is None:
        return []

    return result.get("results", [])


def _run_cross_figure_detection(
    figure_evidence: list[dict[str, Any]],
    workdir: Path,
    min_keypoints: int,
    min_area: float,
    dhash_threshold: int = 20,
    max_pairs: int = 500,
) -> list[dict[str, Any]]:
    """Phase 2b: Cross-figure detection with dhash pre-filter."""
    # Collect figure images
    figures_with_paths = []
    for fig in figure_evidence:
        source = str(fig.get("source_image_path") or "")
        if not source:
            continue
        fig_path = workdir / source
        if fig_path.exists():
            figures_with_paths.append(
                {
                    "figure_id": str(fig.get("figure_id") or ""),
                    "path": fig_path,
                }
            )

    if len(figures_with_paths) < 2:
        return []

    # Compute dhash for all figures
    hashes: list[tuple[str, Path, int]] = []
    for fig in figures_with_paths:
        try:
            h = _dhash(fig["path"])
            hashes.append((fig["figure_id"], fig["path"], h))
        except OSError:
            continue

    if len(hashes) < 2:
        return []

    # Pre-filter pairs by dhash distance
    candidate_pairs = []
    for (fid_a, path_a, hash_a), (fid_b, path_b, hash_b) in combinations(hashes, 2):
        dist = _hamming_distance(hash_a, hash_b)
        if dist <= dhash_threshold:
            candidate_pairs.append(
                {
                    "pair_id": f"{fid_a}__{fid_b}",
                    "source": str(path_a),
                    "target": str(path_b),
                    "source_figure_id": fid_a,
                    "target_figure_id": fid_b,
                    "dhash_distance": dist,
                }
            )

    if not candidate_pairs:
        return []

    # Sort by dhash distance (most similar first), cap
    candidate_pairs.sort(key=lambda p: p["dhash_distance"])
    candidate_pairs = candidate_pairs[:max_pairs]

    output_dir = workdir / "copy_move_elis" / "cross"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = _run_elis_runner(
        {
            "mode": "cross",
            "pairs": candidate_pairs,
            "output_dir": str(output_dir),
            "min_keypoints": min_keypoints,
            "min_area": min_area,
            "check_flip": True,
        },
        timeout=max(600, len(candidate_pairs) * 5),
    )

    if result is None:
        return []

    return result.get("results", [])


def detect_copy_move(
    panel_evidence: list[dict],
    figure_evidence: list[dict],
    *,
    workdir: Path,
    method: str = "rootsift_magsac",
    min_matches: int = COPY_MOVE_DEFAULTS["min_matches"],
    min_score: float = COPY_MOVE_DEFAULTS["min_score"],
    max_relationships: int = COPY_MOVE_DEFAULTS["max_relationships"],
) -> dict[str, Any]:
    """Detect copy-move manipulation within and across panels.

    Phase 2a: single-image copy-move per panel (within-panel forgery).
    Phase 2b: cross-figure with dhash pre-filter (cross-figure reuse).
    """
    panels_with_crops = [
        p for p in panel_evidence if _resolve_panel_image_path(p, workdir)
    ]
    if not panels_with_crops and not figure_evidence:
        return _empty_result(
            "skipped", method, limitations=["No panels or figures available."]
        )

    relationships: list[dict[str, Any]] = []
    errors: list[str] = []
    limitations: list[str] = []

    # --- Phase 2a: Single-image copy-move per panel ---
    single_results = _run_single_image_detection(
        panels_with_crops,
        workdir,
        min_keypoints=min_matches,
        min_area=0.01,
    )
    for r in single_results:
        if not r.get("success"):
            if r.get("error"):
                errors.append(f"Single-image {r.get('panel_id')}: {r['error']}")
            continue
        if not r.get("found_forgery"):
            continue
        kp_count = r.get("matched_keypoints", 0)
        if kp_count < min_matches:
            continue

        panel_id = r.get("panel_id", "")
        # Score: normalize keypoint count (cap at 200 for score=1.0)
        score = min(1.0, kp_count / 200.0)
        if score < min_score:
            continue

        # Make overlay path relative to workdir
        # Use matches_path (with red lines) instead of mask_path (grayscale mask)
        overlay = r.get("matches_path", "") or r.get("mask_path", "")
        if overlay:
            try:
                overlay = str(Path(overlay).relative_to(workdir))
            except ValueError:
                pass

        relationships.append(
            {
                "relationship_id": f"IR-{len(relationships) + 1:04d}",
                "source_type": "copy_move_single",
                "source_panel_id": panel_id,
                "target_panel_id": panel_id,
                "score": round(score, 4),
                "match_method": "rootsift_magsac_single",
                "inlier_count": kp_count,
                "homography": None,
                "overlay_path": overlay or None,
                "flip_detected": False,
                "metadata": {
                    "num_clusters": r.get("num_clusters", 0),
                    "detection_mode": "single_image",
                },
            }
        )

    # --- Phase 2b: Cross-figure with dhash pre-filter ---
    cross_results = _run_cross_figure_detection(
        figure_evidence,
        workdir,
        min_keypoints=min_matches,
        min_area=0.01,
    )
    for r in cross_results:
        if not r.get("success"):
            if r.get("error"):
                errors.append(f"Cross-image {r.get('pair_id')}: {r['error']}")
            continue
        if not r.get("found_forgery"):
            continue
        kp_count = r.get("matched_keypoints", 0)
        if kp_count < min_matches:
            continue

        shared_src = r.get("shared_area_source", 0.0)
        shared_tgt = r.get("shared_area_target", 0.0)
        score = min(shared_src, shared_tgt)
        if score < min_score:
            continue

        overlay = r.get("matches_path", "")
        if overlay:
            try:
                overlay = str(Path(overlay).relative_to(workdir))
            except ValueError:
                pass

        relationships.append(
            {
                "relationship_id": f"IR-{len(relationships) + 1:04d}",
                "source_type": "copy_move_cross",
                "source_panel_id": r.get("source_figure_id", ""),
                "target_panel_id": r.get("target_figure_id", ""),
                "score": round(score, 4),
                "match_method": "rootsift_magsac_cross",
                "inlier_count": kp_count,
                "homography": None,
                "overlay_path": overlay or None,
                "flip_detected": r.get("is_flipped", False),
                "metadata": {
                    "shared_area_source": round(shared_src, 4),
                    "shared_area_target": round(shared_tgt, 4),
                    "num_clusters_source": r.get("num_clusters_source", 0),
                    "num_clusters_target": r.get("num_clusters_target", 0),
                    "detection_mode": "cross_image",
                },
            }
        )

    # Sort by score descending, cap at max_relationships
    relationships.sort(key=lambda r: r["score"], reverse=True)
    relationships = relationships[:max_relationships]

    # Re-number relationship IDs after sorting
    for i, rel in enumerate(relationships, start=1):
        rel["relationship_id"] = f"IR-{i:04d}"

    # Ensure every relationship has a unique overlay file path.
    # The ELIS detector derives overlay names from input image stems, which
    # can collide when different panels share the same crop filename.
    _remap_overlay_to_unique(relationships, workdir)

    total_examined = len(panels_with_crops) + len(figure_evidence)
    status = "ran" if relationships else "skipped"
    if not relationships and (panels_with_crops or figure_evidence):
        limitations.append(
            "No copy-move relationships detected above thresholds. "
            "This does not confirm absence of manipulation."
        )

    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/copy_move_detection.py",
        "status": status,
        "method": method,
        "panel_count": len(panels_with_crops),
        "pair_count_examined": total_examined,
        "relationship_count": len(relationships),
        "relationships": relationships,
        "errors": errors,
        "limitations": limitations,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy-move detection using RootSIFT+MAGSAC++."
    )
    parser.add_argument("panel_json", help="Path to panel_evidence.json")
    parser.add_argument(
        "--figure-json", default=None, help="Path to visual_evidence.json"
    )
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument(
        "--workdir", required=True, help="Working directory for image resolution"
    )
    parser.add_argument(
        "--method", default="rootsift_magsac", choices=["rootsift_magsac"]
    )
    parser.add_argument(
        "--min-matches", type=int, default=COPY_MOVE_DEFAULTS["min_matches"]
    )
    parser.add_argument(
        "--min-score", type=float, default=COPY_MOVE_DEFAULTS["min_score"]
    )
    parser.add_argument(
        "--max-relationships", type=int, default=COPY_MOVE_DEFAULTS["max_relationships"]
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workdir = Path(args.workdir).expanduser().resolve()

    panel_json_path = Path(args.panel_json).expanduser().resolve()
    panel_data = (
        json.loads(panel_json_path.read_text(encoding="utf-8"))
        if panel_json_path.exists()
        else {}
    )
    panels = panel_data.get("panels", []) if isinstance(panel_data, dict) else []

    figures = []
    if args.figure_json:
        figure_json_path = Path(args.figure_json).expanduser().resolve()
        if figure_json_path.exists():
            figure_data = json.loads(figure_json_path.read_text(encoding="utf-8"))
            figures = (
                figure_data.get("figures", []) if isinstance(figure_data, dict) else []
            )

    result = detect_copy_move(
        panels,
        figures,
        workdir=workdir,
        method=args.method,
        min_matches=args.min_matches,
        min_score=args.min_score,
        max_relationships=args.max_relationships,
    )

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "output": str(output),
                "status": result["status"],
                "relationship_count": result["relationship_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
