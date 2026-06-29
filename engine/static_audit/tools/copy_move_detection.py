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
import logging
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from engine.exceptions import ToolExecutionError
from engine.static_audit.visual_constants import (
    COPY_MOVE_DEFAULTS,
    dhash_rotations_from_path,
    min_hamming_rotations,
)
from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION
from runtime.executors.base import ExecutionRequest
from runtime.executors.subprocess_executor import execute_subprocess

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def _dhash(path: Path, hash_size: int = 8) -> int:
    """Compute perceptual difference hash for an image."""
    from PIL import Image

    with Image.open(path) as image:
        resized = image.convert("L").resize((hash_size + 1, hash_size))
        pixels = list(resized.get_flattened_data())
    value = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            value = (value << 1) | int(left > right)  # type: ignore[assignment,operator]
    return value


def _hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ---------------------------------------------------------------------------
# Public API — dHash pre-filter and parallel SIFT matching
# ---------------------------------------------------------------------------


def compute_dhash(image: Path | str, hash_size: int = 8) -> int:
    """Compute perceptual difference hash (dHash) for an image.

    dHash encodes horizontal gradient direction: each bit represents whether
    the left pixel is brighter than the right pixel in a downscaled grayscale
    image.  Two images with similar visual content will have low Hamming
    distance between their dHashes.

    Args:
        image: Path to an image file, or a PIL Image object.
        hash_size: Grid size for hash computation (default 8 → 64-bit hash).

    Returns:
        Integer hash value.
    """
    return _dhash(Path(image) if not hasattr(image, "rotate") else image, hash_size)


def hamming_distance(hash1: int, hash2: int) -> int:
    """Compute Hamming distance between two integer hashes."""
    return _hamming_distance(hash1, hash2)


def prefilter_with_dhash(
    panels: list[dict[str, Any]],
    max_distance: int = 10,
) -> list[tuple[int, int]]:
    """Use dHash to quickly find candidate panel pairs for expensive matching.

    Computes dHash for every panel image and returns all index pairs whose
    Hamming distance is at most *max_distance*.  This avoids the O(n²)
    full-comparison cost of running SIFT matching on every pair.

    Args:
        panels: List of panel dicts, each with at least ``"crop_path"``
            pointing to an existing image file.
        max_distance: Maximum Hamming distance to consider a pair as a
            candidate.  Default 10 is intentionally permissive to maintain
            high recall; the subsequent SIFT stage filters false positives.

    Returns:
        List of ``(i, j)`` index pairs into *panels* where ``i < j``.
    """
    hashes: list[int | None] = []
    for panel in panels:
        crop = panel.get("crop_path") or ""
        if not crop:
            hashes.append(None)
            continue
        p = Path(crop)
        if not p.is_file():
            hashes.append(None)
            continue
        try:
            hashes.append(compute_dhash(p))
        except OSError:
            hashes.append(None)

    candidates: list[tuple[int, int]] = []
    for i, j in combinations(range(len(panels)), 2):
        h_i, h_j = hashes[i], hashes[j]
        if h_i is None or h_j is None:
            continue
        if hamming_distance(h_i, h_j) <= max_distance:
            candidates.append((i, j))
    return candidates


def parallel_sift_match(
    candidates: list[tuple[int, int]],
    panels: list[dict[str, Any]],
    max_workers: int = 8,
) -> list[dict[str, Any]]:
    """Run SIFT-based copy-move matching on candidate pairs in parallel.

    Each candidate pair ``(i, j)`` is matched by spawning the ELIS keypoint
    copy-move runner in cross-image mode.  Up to *max_workers* subprocesses
    run concurrently via :class:`ThreadPoolExecutor`.

    Args:
        candidates: Index pairs from :func:`prefilter_with_dhash`.
        panels: Panel dicts (must contain ``"panel_id"`` and ``"crop_path"``).
        max_workers: Maximum number of concurrent subprocess workers.

    Returns:
        List of match result dicts.  Each dict contains ``pair_id``,
        ``source_panel_id``, ``target_panel_id``, ``success``,
        ``matched_keypoints``, and other fields from the ELIS runner.
    """
    if not candidates:
        return []

    # Build per-pair input data
    pair_inputs: list[dict[str, Any]] = []
    for i, j in candidates:
        panel_i = panels[i]
        panel_j = panels[j]
        path_i = panel_i.get("crop_path", "")
        path_j = panel_j.get("crop_path", "")
        pair_inputs.append(
            {
                "pair_id": f"{panel_i.get('panel_id', i)}__{panel_j.get('panel_id', j)}",
                "source": str(path_i),
                "target": str(path_j),
                "source_panel_id": str(panel_i.get("panel_id", i)),
                "target_panel_id": str(panel_j.get("panel_id", j)),
            }
        )

    # Determine output directory from first panel path's parent
    workdir = Path(panels[0].get("crop_path", ".")).parent
    output_dir = workdir / "copy_move_elis" / "parallel_sift"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run ELIS subprocess — single batched call for all pairs is more
    # efficient than splitting, because subprocess startup overhead
    # dominates for small pair counts.  For large pair counts, we chunk.
    chunk_size = max(1, len(pair_inputs) // max_workers)
    chunks = [
        pair_inputs[k : k + chunk_size] for k in range(0, len(pair_inputs), chunk_size)
    ]

    all_results: list[dict[str, Any]] = []

    def _run_chunk(chunk: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = _run_elis_runner(
            {
                "mode": "cross",
                "pairs": chunk,
                "output_dir": str(output_dir),
                "min_keypoints": 20,
                "min_area": 0.01,
                "check_flip": True,
            },
            timeout=max(600, len(chunk) * 5),
        )
        if result is None:
            return []
        return result.get("results", [])

    if len(chunks) <= 1:
        all_results = _run_chunk(pair_inputs)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_run_chunk, c): c for c in chunks}
            for future in as_completed(futures):
                try:
                    all_results.extend(future.result())
                except (OSError, RuntimeError):
                    pass

    return all_results


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
        result = execute_subprocess(
            ExecutionRequest(
                command=[
                    sys.executable,
                    "-m",
                    "engine.static_audit.tools._elis_copy_move_runner",
                ],
                workdir=Path.cwd(),
                timeout_seconds=timeout,
                stdin_data=json.dumps(input_data),
            )
        )
        return json.loads(result.stdout)
    except (ToolExecutionError, json.JSONDecodeError, OSError):
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


def _build_figure_panel_type_map(
    panel_evidence: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """Map each parent_figure_id to the set of known panel_types it contains.

    Panels with ``panel_type`` of ``None`` or empty string are ignored.
    Figures with no classified panels will be absent from the map.
    """
    mapping: dict[str, set[str]] = {}
    for panel in panel_evidence:
        if not isinstance(panel, dict):
            continue
        figure_id = str(panel.get("parent_figure_id") or "")
        panel_type = panel.get("panel_type")
        if not figure_id or not panel_type:
            continue
        mapping.setdefault(figure_id, set()).add(panel_type)
    return mapping


def _run_cross_figure_detection(
    figure_evidence: list[dict[str, Any]],
    workdir: Path,
    min_keypoints: int,
    min_area: float,
    dhash_threshold: int = 20,
    max_pairs: int = 500,
    figure_panel_types: dict[str, set[str]] | None = None,
    full_scan: bool = False,
) -> list[dict[str, Any]]:
    """Phase 2b: Cross-figure detection with dhash pre-filter.

    When *figure_panel_types* is provided, only figure pairs whose panel-type
    sets intersect are compared.  Pairs where either side has no classified
    panels (null/unknown panel_type) are skipped to avoid false matches between
    unrelated panel categories (e.g. Blots vs Graphs).
    """
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

    # Compute dhash for all figures (rotation-invariant via 4-rotation pre-filter)
    hashes: list[tuple[str, Path, tuple[int, int, int, int]]] = []
    for fig in figures_with_paths:
        try:
            h_tuple = dhash_rotations_from_path(fig["path"])
            hashes.append((fig["figure_id"], fig["path"], h_tuple))
        except OSError:
            continue

    if len(hashes) < 2:
        return []

    # Pre-filter pairs by rotation-invariant dhash distance (Plan C)
    # Additionally filter by panel_type consistency when available.
    # When full_scan=True, skip the dhash distance check and compare all pairs.
    candidate_pairs = []
    for (fid_a, path_a, hash_a), (fid_b, path_b, hash_b) in combinations(hashes, 2):
        if full_scan:
            dist, best_angle = 0, 0
        else:
            dist, best_angle = min_hamming_rotations(hash_a, hash_b)
            if dist > dhash_threshold:
                continue

        # panel_type consistency check: both sides must have at least one
        # classified panel, and their type sets must intersect.
        if figure_panel_types:
            types_a = figure_panel_types.get(fid_a)
            types_b = figure_panel_types.get(fid_b)
            if not types_a or not types_b:
                # One or both figures have no classified panels -- skip.
                continue
            if not (types_a & types_b):
                # No overlapping panel type -- skip.
                continue

        candidate_pairs.append(
            {
                "pair_id": f"{fid_a}__{fid_b}",
                "source": str(path_a),
                "target": str(path_b),
                "source_figure_id": fid_a,
                "target_figure_id": fid_b,
                "dhash_distance": dist,
                "best_rotation_angle": best_angle,
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


def _is_wet_lab_figure(
    figure_id: str,
    figure_panel_types: dict[str, set[str]] | None,
    figure_classification: dict[str, Any] | None,
) -> bool:
    """Check if a figure should run rotation detection (wet_lab only).

    Rotation detection is restricted to wet_lab panels to avoid false positives
    on code-generated images. A figure is eligible if:
    1. figure_classification indicates it has wet_lab/mixed panels, OR
    2. figure_panel_types includes wet_lab-like YOLO types (Blots, Microscopy, etc.)

    Args:
        figure_id: The figure identifier
        figure_panel_types: Map of figure_id -> set of YOLO panel types
        figure_classification: Figure classification data from figure_classification.json

    Returns:
        True if rotation detection should run on this figure
    """
    # Check figure_classification first (LLM-based)
    if figure_classification:
        classifications = figure_classification.get("classifications", [])
        for cls_item in classifications:
            if isinstance(cls_item, dict):
                fid = cls_item.get("figure_id", "")
                cls = cls_item.get("classification", "")
                if fid == figure_id and cls in {"wet_lab", "mixed"}:
                    return True

    # Fall back to YOLO panel types
    if figure_panel_types:
        types = figure_panel_types.get(figure_id, set())
        wet_lab_yolo_types = {"Blots", "Microscopy", "Body Imaging", "Flow Cytometry"}
        if types & wet_lab_yolo_types:
            return True

    return False


def _run_rotation_detection(
    figure_evidence: list[dict[str, Any]],
    workdir: Path,
    min_matches: int,
    min_score: float,
    figure_panel_types: dict[str, set[str]] | None = None,
    figure_classification: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Phase 2c: Detect copy-move with rotation/flip/scale on wet_lab figures.

    Only runs on figures classified as wet_lab or mixed to avoid false positives
    on code-generated images (UMAP, heatmaps, etc.).

    Args:
        figure_evidence: List of figure dicts
        workdir: Working directory
        min_matches: Minimum inlier matches for RANSAC
        min_score: Minimum score to emit relationship
        figure_panel_types: Map of figure_id -> set of YOLO panel types
        figure_classification: Figure classification data from figure_classification.json

    Returns:
        List of rotation detection results (same format as cross-figure results)
    """
    try:
        import cv2
    except ImportError:
        logger.warning("cv2 not available; skipping rotation detection")
        return []

    from engine.static_audit.tools._copy_move_rotation import (
        detect_copy_move_rotation,
    )

    # Collect figures with valid paths
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

    # Filter to wet_lab figures only
    wet_lab_figures = []
    for fig in figures_with_paths:
        fid = fig["figure_id"]
        if _is_wet_lab_figure(fid, figure_panel_types, figure_classification):
            wet_lab_figures.append(fig)

    if len(wet_lab_figures) < 2:
        logger.debug(
            f"Rotation detection: {len(wet_lab_figures)} wet_lab figures (need >= 2)"
        )
        return []

    # Compare all wet_lab pairs (capped to avoid O(n^2) blowup)
    results = []
    max_pairs = 500
    pair_count = 0

    for i, fig_a in enumerate(wet_lab_figures):
        for fig_b in wet_lab_figures[i + 1 :]:
            if pair_count >= max_pairs:
                logger.warning(f"Rotation detection: capped at {max_pairs} pairs")
                break

            pair_count += 1
            pair_id = f"{fig_a['figure_id']}__{fig_b['figure_id']}"

            try:
                img_a = cv2.imread(str(fig_a["path"]))
                img_b = cv2.imread(str(fig_b["path"]))

                if img_a is None or img_b is None:
                    logger.warning(f"Failed to load images for rotation pair {pair_id}")
                    continue

                result = detect_copy_move_rotation(
                    img_a, img_b, min_matches=min_matches
                )

                if result is None:
                    continue

                inlier_count = result["inlier_count"]
                angle = result["angle"]
                scale = result["scale"]
                is_flipped = result["is_flipped"]

                # Score based on inlier count
                score = min(1.0, inlier_count / 200.0)

                if score < min_score:
                    continue

                results.append(
                    {
                        "pair_id": pair_id,
                        "source_figure_id": fig_a["figure_id"],
                        "target_figure_id": fig_b["figure_id"],
                        "success": True,
                        "found_forgery": True,
                        "matched_keypoints": inlier_count,
                        "inlier_count": inlier_count,
                        "score": round(score, 4),
                        "is_flipped": is_flipped,
                        "rotation_angle": round(angle, 2),
                        "scale_factor": round(scale, 4),
                        "transform_matrix": result["transform_matrix"],
                    }
                )

            except Exception as e:  # Deliberately broad: rotation detection uses cv2 + custom algorithms that may raise various errors
                logger.warning(f"Rotation detection failed for pair {pair_id}: {e}")
                results.append(
                    {
                        "pair_id": pair_id,
                        "source_figure_id": fig_a["figure_id"],
                        "target_figure_id": fig_b["figure_id"],
                        "success": False,
                        "found_forgery": False,
                        "error": str(e),
                    }
                )

    return results


def _process_single_image_results(
    single_results: list[dict[str, Any]],
    workdir: Path,
    min_matches: int,
    min_score: float,
    relationships: list[dict[str, Any]],
    errors: list[str],
) -> None:
    """Process Phase 2a single-image detection results into relationships."""
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


def _process_cross_figure_result(
    r: dict[str, Any],
    workdir: Path,
    min_matches: int,
    min_score: float,
    figure_panel_types: dict[str, set[str]],
    relationships: list[dict[str, Any]],
    errors: list[str],
) -> None:
    """Process a single Phase 2b cross-figure detection result."""
    if not r.get("success"):
        if r.get("error"):
            errors.append(f"Cross-image {r.get('pair_id')}: {r['error']}")
        return
    if not r.get("found_forgery"):
        return
    kp_count = r.get("matched_keypoints", 0)
    if kp_count < min_matches:
        return

    shared_src = r.get("shared_area_source", 0.0)
    shared_tgt = r.get("shared_area_target", 0.0)
    score = min(shared_src, shared_tgt)
    if score < min_score:
        return

    overlay = r.get("matches_path", "")
    if overlay:
        try:
            overlay = str(Path(overlay).relative_to(workdir))
        except ValueError:
            pass

    # Resolve panel types for the matched figure pair.
    src_fid = r.get("source_figure_id", "")
    tgt_fid = r.get("target_figure_id", "")
    src_types = sorted(figure_panel_types.get(src_fid) or set())
    tgt_types = sorted(figure_panel_types.get(tgt_fid) or set())
    # The matched panel type(s): intersection of both sides.
    matched_types = sorted(set(src_types) & set(tgt_types))
    src_panel_type = ",".join(src_types) if src_types else "unknown"
    tgt_panel_type = ",".join(tgt_types) if tgt_types else "unknown"

    relationships.append(
        {
            "relationship_id": f"IR-{len(relationships) + 1:04d}",
            "source_type": "copy_move_cross",
            "source_panel_id": src_fid,
            "target_panel_id": tgt_fid,
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
                "source_panel_type": src_panel_type,
                "target_panel_type": tgt_panel_type,
                "matched_panel_types": ",".join(matched_types)
                if matched_types
                else "unknown",
            },
        }
    )


def _process_cross_figure_results(
    cross_results: list[dict[str, Any]],
    workdir: Path,
    min_matches: int,
    min_score: float,
    figure_panel_types: dict[str, set[str]],
    relationships: list[dict[str, Any]],
    errors: list[str],
) -> None:
    """Process all Phase 2b cross-figure detection results."""
    for r in cross_results:
        _process_cross_figure_result(
            r,
            workdir,
            min_matches,
            min_score,
            figure_panel_types,
            relationships,
            errors,
        )


def _process_rotation_result(
    r: dict[str, Any],
    min_matches: int,
    min_score: float,
    figure_panel_types: dict[str, set[str]],
    relationships: list[dict[str, Any]],
    errors: list[str],
) -> None:
    """Process a single Phase 2c rotation detection result."""
    if not r.get("success"):
        if r.get("error"):
            errors.append(f"Rotation {r.get('pair_id')}: {r['error']}")
        return
    if not r.get("found_forgery"):
        return

    inlier_count = r.get("inlier_count", 0)
    if inlier_count < min_matches:
        return

    score = r.get("score", 0.0)
    if score < min_score:
        return

    src_fid = r.get("source_figure_id", "")
    tgt_fid = r.get("target_figure_id", "")

    # Resolve panel types
    src_types = sorted(figure_panel_types.get(src_fid) or set())
    tgt_types = sorted(figure_panel_types.get(tgt_fid) or set())
    matched_types = sorted(set(src_types) & set(tgt_types))
    src_panel_type = ",".join(src_types) if src_types else "unknown"
    tgt_panel_type = ",".join(tgt_types) if tgt_types else "unknown"

    relationships.append(
        {
            "relationship_id": f"IR-{len(relationships) + 1:04d}",
            "source_type": "copy_move_rotation",
            "source_panel_id": src_fid,
            "target_panel_id": tgt_fid,
            "score": round(score, 4),
            "match_method": "sift_ransac_affine",
            "inlier_count": inlier_count,
            "homography": r.get("transform_matrix"),
            "overlay_path": None,  # Rotation detection doesn't generate overlay
            "flip_detected": r.get("is_flipped", False),
            "metadata": {
                "detection_mode": "rotation_affine",
                "rotation_angle": r.get("rotation_angle", 0.0),
                "scale_factor": r.get("scale_factor", 1.0),
                "is_flipped": r.get("is_flipped", False),
                "source_panel_type": src_panel_type,
                "target_panel_type": tgt_panel_type,
                "matched_panel_types": ",".join(matched_types)
                if matched_types
                else "unknown",
            },
        }
    )


def _process_rotation_results(
    rotation_results: list[dict[str, Any]],
    min_matches: int,
    min_score: float,
    figure_panel_types: dict[str, set[str]],
    relationships: list[dict[str, Any]],
    errors: list[str],
) -> None:
    """Process all Phase 2c rotation detection results."""
    for r in rotation_results:
        _process_rotation_result(
            r, min_matches, min_score, figure_panel_types, relationships, errors
        )


def detect_copy_move(
    panel_evidence: list[dict],
    figure_evidence: list[dict],
    *,
    workdir: Path,
    method: str = "rootsift_magsac",
    min_matches: int = COPY_MOVE_DEFAULTS["min_matches"],
    min_score: float = COPY_MOVE_DEFAULTS["min_score"],
    max_relationships: int = COPY_MOVE_DEFAULTS["max_relationships"],
    figure_classification: dict[str, Any] | None = None,
    full_scan: bool = False,
) -> dict[str, Any]:
    """Detect copy-move manipulation within and across panels.

    Phase 2a: single-image copy-move per panel (within-panel forgery).
    Phase 2b: cross-figure with dhash pre-filter (cross-figure reuse).
    Phase 2c: rotation/flip/scale detection using SIFT + affine transform (wet_lab only).

    Args:
        full_scan: When True, skip dHash pre-filtering and compare all figure
            pairs.  Use as fallback when dHash pre-filter may miss matches.
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
    _process_single_image_results(
        single_results, workdir, min_matches, min_score, relationships, errors
    )

    # --- Phase 2b: Cross-figure with dhash pre-filter ---
    figure_panel_types = _build_figure_panel_type_map(panel_evidence)
    cross_results = _run_cross_figure_detection(
        figure_evidence,
        workdir,
        min_keypoints=min_matches,
        min_area=0.01,
        figure_panel_types=figure_panel_types,
        full_scan=full_scan,
    )
    _process_cross_figure_results(
        cross_results,
        workdir,
        min_matches,
        min_score,
        figure_panel_types,
        relationships,
        errors,
    )

    # --- Phase 2c: Rotation/flip/scale detection (wet_lab only) ---
    rotation_results = _run_rotation_detection(
        figure_evidence,
        workdir,
        min_matches=max(min_matches, 10),  # Rotation needs at least 10 matches
        min_score=min_score,
        figure_panel_types=figure_panel_types,
        figure_classification=figure_classification,
    )
    _process_rotation_results(
        rotation_results,
        min_matches,
        min_score,
        figure_panel_types,
        relationships,
        errors,
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
    parser.add_argument(
        "--figure-classification",
        default=None,
        help="Path to figure_classification.json (for wet_lab filtering)",
    )
    parser.add_argument(
        "--full-scan",
        action="store_true",
        default=False,
        help="Skip dHash pre-filter and compare all figure pairs (slower but higher recall)",
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

    figure_classification = None
    if args.figure_classification:
        fc_path = Path(args.figure_classification).expanduser().resolve()
        if fc_path.exists():
            figure_classification = json.loads(fc_path.read_text(encoding="utf-8"))

    result = detect_copy_move(
        panels,
        figures,
        workdir=workdir,
        method=args.method,
        min_matches=args.min_matches,
        min_score=args.min_score,
        max_relationships=args.max_relationships,
        figure_classification=figure_classification,
        full_scan=args.full_scan,
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
