"""Image quality anomaly detection.

Lightweight pixel-statistics detector that flags figures with suspicious
uniformity patterns — missing background (uniform border), globally uniform
images, or near-solid-color figures.

Motivation: in PubPeer #10 ground truth a Western blot has no background
unlike other blots.  This tool catches such quality anomalies as a
screening signal for human review.

No ML dependencies — uses Pillow only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION

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
    except Exception as e:
        return [{"_error": f"Cannot open image: {e}"}]

    if img.mode not in ("L", "RGB", "RGBA", "P"):
        return []

    gray = img.convert("L")
    w, h = gray.size
    if w == 0 or h == 0:
        return []

    pixels = list(gray.getdata())
    mean_pixel = sum(pixels) / len(pixels)

    # Build 2-D gray array as plain lists for the helper functions.
    gray_2d: list[list[int]] = [
        pixels[y * w:(y + 1) * w] for y in range(h)
    ]

    details: dict[str, Any] = {"mean_pixel": round(mean_pixel, 2)}

    # 1. Border uniformity
    border_ratio = _border_uniformity(gray_2d, w, h)
    details["border_uniformity"] = round(border_ratio, 4)
    if border_ratio > 0.95:
        anomalies.append({
            "anomaly_type": "uniform_border",
            "severity": "high",
            "details": dict(details),
        })

    # 2. Global uniformity
    global_ratio, mode_val = _global_uniformity(gray_2d, w, h)
    details["global_uniformity"] = round(global_ratio, 4)
    details["dominant_gray_value"] = mode_val
    if global_ratio > 0.80:
        anomalies.append({
            "anomaly_type": "globally_uniform",
            "severity": "medium",
            "details": dict(details),
        })

    # 3. Near-solid-color (all-white / all-black)
    if mean_pixel > 250 or mean_pixel < 5:
        anomalies.append({
            "anomaly_type": "near_solid_color",
            "severity": "high",
            "details": dict(details),
        })

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
        except Exception as e:
            errors.append(f"Analysis failed for {figure_id}: {e}")
            continue

        for a in fig_anomalies:
            if "_error" in a:
                errors.append(f"{figure_id}: {a['_error']}")
                continue
            anomalies.append({
                "figure_id": figure_id,
                "image_path": source,
                "anomaly_type": a["anomaly_type"],
                "severity": a["severity"],
                "details": a["details"],
            })

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
