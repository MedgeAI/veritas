"""Image quality anomaly detection.

Lightweight pixel-statistics detector that flags figures with suspicious
uniformity patterns — missing background (uniform border), globally uniform
images, or near-solid-color figures.

Also provides background texture consistency detection: compares Laplacian
variance and edge density across same-type panels (Blots, Microscopy) to
flag figures with abnormally uniform or textureless backgrounds.

Motivation: in PubPeer #10 ground truth a Western blot has no background
unlike other blots.  This tool catches such quality anomalies as a
screening signal for human review.

No ML dependencies — uses Pillow and OpenCV (cv2).
"""

from __future__ import annotations

import logging
import statistics
from pathlib import Path
from typing import Any

from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}


def _border_uniformity(gray: list[list[int]], w: int, h: int) -> float:
    """Fraction of outer-10% border pixels within ±2 gray levels of the mode."""
    border_h = max(1, h // 10)
    border_w = max(1, w // 10)
    total = 0
    counts: dict[int, int] = {}
    for y in range(h):
        for x in range(w):
            if y < border_h or y >= h - border_h or x < border_w or x >= w - border_w:
                v = gray[y][x]
                counts[v] = counts.get(v, 0) + 1
                total += 1
    if total == 0:
        return 0.0
    mode_val = max(counts, key=counts.get)  # type: ignore[arg-type]
    in_range = sum(c for v, c in counts.items() if abs(v - mode_val) <= 2)
    return in_range / total


def _global_uniformity(gray: list[list[int]], w: int, h: int) -> tuple[float, int]:
    """Fraction of all pixels sharing the most common value, and that value."""
    total = w * h
    if total == 0:
        return 0.0, 0
    counts: dict[int, int] = {}
    for row in gray:
        for v in row:
            counts[v] = counts.get(v, 0) + 1
    mode_count = max(counts.values())
    mode_val = max(counts, key=counts.get)  # type: ignore[arg-type]
    return mode_count / total, mode_val


def _analyze_image(image_path: Path) -> list[dict[str, Any]]:
    """Analyze a single image and return anomaly dicts (empty if clean)."""
    from PIL import Image

    anomalies: list[dict[str, Any]] = []

    try:
        img = Image.open(image_path)
    except OSError as e:
        return [{"_error": f"Cannot open image: {e}"}]

    if img.mode not in ("L", "RGB", "RGBA", "P"):
        return []

    gray = img.convert("L")
    w, h = gray.size
    if w == 0 or h == 0:
        return []

    pixels = list(gray.get_flattened_data())
    mean_pixel = sum(pixels) / len(pixels)

    # Build 2-D gray array as plain lists for the helper functions.
    gray_2d: list[list[int]] = [pixels[y * w : (y + 1) * w] for y in range(h)]  # type: ignore[assignment,operator]

    details: dict[str, Any] = {"mean_pixel": round(mean_pixel, 2)}

    # 1. Border uniformity
    border_ratio = _border_uniformity(gray_2d, w, h)
    details["border_uniformity"] = round(border_ratio, 4)
    if border_ratio > 0.95:
        anomalies.append(
            {
                "anomaly_type": "uniform_border",
                "severity": "high",
                "details": dict(details),
            }
        )

    # 2. Global uniformity
    global_ratio, mode_val = _global_uniformity(gray_2d, w, h)
    details["global_uniformity"] = round(global_ratio, 4)
    details["dominant_gray_value"] = mode_val
    if global_ratio > 0.80:
        anomalies.append(
            {
                "anomaly_type": "globally_uniform",
                "severity": "medium",
                "details": dict(details),
            }
        )

    # 3. Near-solid-color (all-white / all-black)
    if mean_pixel > 250 or mean_pixel < 5:
        anomalies.append(
            {
                "anomaly_type": "near_solid_color",
                "severity": "high",
                "details": dict(details),
            }
        )

    return anomalies


def run_image_quality(
    figure_evidence: list[dict[str, Any]],
    *,
    workdir: Path,
) -> dict[str, Any]:
    """Run image quality anomaly detection on all figures.

    Args:
        figure_evidence: List of figure dicts from visual/evidence.json,
            each containing ``figure_id`` and ``source_image_path``.
        workdir: Audit working directory for resolving image paths.

    Returns:
        Canonical result dict with anomalies list.
    """
    errors: list[str] = []
    anomalies: list[dict[str, Any]] = []
    figure_count = 0

    for fig in figure_evidence:
        figure_id = str(fig.get("figure_id") or "")
        source = str(fig.get("source_image_path") or "")
        if not source:
            continue
        fig_path = workdir / source
        if not fig_path.exists():
            errors.append(f"Figure image not found: {source}")
            continue

        suffix = fig_path.suffix.lower()
        if suffix not in _IMAGE_EXTENSIONS:
            continue

        figure_count += 1
        try:
            fig_anomalies = _analyze_image(fig_path)
        except Exception as e:  # Deliberately broad: per-figure failure isolation; image analysis must not abort scan
            # Failure isolation: per-figure analysis must not abort the scan.
            logger.warning("Image quality analysis failed for %s: %s", figure_id, e)
            errors.append(f"Analysis failed for {figure_id}: {e}")
            continue

        for a in fig_anomalies:
            if "_error" in a:
                errors.append(f"{figure_id}: {a['_error']}")
                continue
            anomalies.append(
                {
                    "figure_id": figure_id,
                    "image_path": source,
                    "anomaly_type": a["anomaly_type"],
                    "severity": a["severity"],
                    "details": a["details"],
                }
            )

    status = "ran" if figure_count > 0 else "skipped"

    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/image_quality.py",
        "status": status,
        "figure_count": figure_count,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "errors": errors,
        "limitations": [
            "Image quality checks are heuristic and may produce false positives "
            "for legitimately uniform images like diagrams or schematics.",
        ],
    }


# ---------------------------------------------------------------------------
# Background texture consistency detection
# ---------------------------------------------------------------------------

_COMPARABLE_PANEL_TYPES = {"Blots", "Microscopy"}


def _background_texture_score(image_path: Path) -> tuple[float, float]:
    """Compute background texture features for a single image.

    Returns:
        (laplacian_var, edge_density) where:
        - laplacian_var: variance of Laplacian (higher = more texture)
        - edge_density: fraction of edge pixels from Canny detector
    """
    import cv2
    import numpy as np

    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None or img.size == 0:
        return (0.0, 0.0)

    # Laplacian variance — measures texture richness
    laplacian = cv2.Laplacian(img, cv2.CV_64F)
    laplacian_var = float(laplacian.var())

    # Edge density via Canny
    edges = cv2.Canny(img, 100, 200)
    edge_density = float(np.count_nonzero(edges)) / float(edges.size)

    return (laplacian_var, edge_density)


def _iqr(values: list[float]) -> float:
    """Interquartile range of a sorted-or-unsorted list."""
    if len(values) < 4:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    q1 = sorted_v[n // 4]
    q3 = sorted_v[(3 * n) // 4]
    return q3 - q1


def run_background_comparison(
    figure_evidence: list[dict[str, Any]],
    panel_evidence: list[dict[str, Any]],
    *,
    workdir: Path,
) -> dict[str, Any]:
    """Compare background texture consistency within same-type panel groups.

    Groups panels by panel_type (only Blots and Microscopy), computes
    Laplacian variance and edge density per panel, then flags figures
    whose panels deviate > 2 IQR from the group median.

    Args:
        figure_evidence: List of figure dicts from visual/evidence.json.
        panel_evidence: List of panel dicts from visual/panel_evidence.json.
        workdir: Audit working directory for resolving image paths.

    Returns:
        Result dict compatible with run_image_quality() output format,
        intended to be appended to image_quality.json anomalies.
    """
    errors: list[str] = []
    anomalies: list[dict[str, Any]] = []
    group_stats: dict[str, dict[str, Any]] = {}

    # Build figure_id -> figure source path map
    fig_source_map: dict[str, str] = {}
    for fig in figure_evidence:
        fid = str(fig.get("figure_id") or "")
        src = str(fig.get("source_image_path") or "")
        if fid and src:
            fig_source_map[fid] = src

    # Collect per-panel texture scores grouped by panel_type
    type_scores: dict[str, list[tuple[str, str, float, float]]] = {}
    # Each entry: (panel_id, parent_figure_id, laplacian_var, edge_density)

    for panel in panel_evidence:
        panel_id = str(panel.get("panel_id") or "")
        parent_fid = str(panel.get("parent_figure_id") or "")
        panel_type = str(panel.get("panel_type") or "")
        source = str(panel.get("crop_path") or "")

        if panel_type not in _COMPARABLE_PANEL_TYPES:
            continue
        if not source:
            continue

        panel_path = workdir / source
        if not panel_path.exists():
            errors.append(f"Panel image not found: {source}")
            continue

        try:
            lap_var, edge_dens = _background_texture_score(panel_path)
        except (OSError, ValueError, ImportError) as e:
            logger.warning("Texture score failed for %s: %s", panel_id, e)
            errors.append(f"Texture score failed for {panel_id}: {e}")
            continue

        type_scores.setdefault(panel_type, []).append(
            (panel_id, parent_fid, lap_var, edge_dens)
        )

    # Compute group stats and detect anomalies
    for panel_type, entries in type_scores.items():
        if len(entries) < 3:
            # Too few samples for meaningful comparison
            continue

        lap_values = [e[2] for e in entries]
        edge_values = [e[3] for e in entries]

        lap_median = statistics.median(lap_values)
        edge_median = statistics.median(edge_values)
        lap_iqr = _iqr(lap_values)
        edge_iqr = _iqr(edge_values)

        group_stats[panel_type] = {
            "panel_count": len(entries),
            "laplacian_median": round(lap_median, 2),
            "laplacian_iqr": round(lap_iqr, 2),
            "edge_density_median": round(edge_median, 4),
            "edge_density_iqr": round(edge_iqr, 4),
        }

        # Flag panels deviating > 2 IQR
        flagged_figures: set[str] = set()
        for panel_id, parent_fid, lap_var, edge_dens in entries:
            lap_deviate = lap_iqr > 0 and abs(lap_var - lap_median) > 2 * lap_iqr
            edge_deviate = edge_iqr > 0 and abs(edge_dens - edge_median) > 2 * edge_iqr

            if lap_deviate or edge_deviate:
                if parent_fid in flagged_figures:
                    continue  # One anomaly per figure per panel_type
                flagged_figures.add(parent_fid)

                fig_source = fig_source_map.get(parent_fid, "")
                details: dict[str, Any] = {
                    "panel_type": panel_type,
                    "deviant_panel_id": panel_id,
                    "laplacian_var": round(lap_var, 2),
                    "laplacian_group_median": round(lap_median, 2),
                    "laplacian_group_iqr": round(lap_iqr, 2),
                    "edge_density": round(edge_dens, 4),
                    "edge_density_group_median": round(edge_median, 4),
                    "edge_density_group_iqr": round(edge_iqr, 4),
                    "laplacian_deviation": lap_deviate,
                    "edge_density_deviation": edge_deviate,
                }

                anomalies.append(
                    {
                        "figure_id": parent_fid,
                        "image_path": fig_source,
                        "anomaly_type": "background_texture_anomaly",
                        "severity": "medium",
                        "details": details,
                    }
                )

    status = "ran" if any(len(v) >= 3 for v in type_scores.values()) else "skipped"

    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/image_quality.py",
        "analysis": "background_texture_consistency",
        "status": status,
        "group_stats": group_stats,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "errors": errors,
        "limitations": [
            "Background texture comparison only applies to Blots and Microscopy panels.",
            "Requires at least 3 panels per type for statistical comparison.",
            "Texture deviation does not imply fabrication; some experiments "
            "legitimately produce uniform backgrounds.",
        ],
    }
