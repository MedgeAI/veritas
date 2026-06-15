"""Panel extraction tool using traditional CV (OpenCV).

This module implements panel extraction from figure images using contour-based
edge detection. It detects multi-panel figures and extracts individual panels
with bounding boxes, labels, and crop paths.

Algorithm:
1. Grayscale conversion
2. Gaussian blur to reduce noise
3. Canny edge detection (adaptive thresholds)
4. Morphological close to connect broken edges
5. Contour detection (RETR_EXTERNAL)
6. Contour filtering (area, aspect ratio, extent)
7. Panel labeling (top-to-bottom, left-to-right)
8. Crop extraction and saving
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised through not_available paths when absent
    import cv2
    import numpy as np
    from PIL import Image
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]

from engine.static_audit.visual_constants import PANEL_EXTRACTION_DEFAULTS
from engine.static_audit.visual_schemas import FigureEvidence, PanelEvidence, VISUAL_SCHEMA_VERSION


def detect_edges(image: np.ndarray) -> np.ndarray:
    """Detect edges using Canny with adaptive thresholds.

    Args:
        image: Input image (BGR or grayscale)

    Returns:
        Edge map
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    # Apply Gaussian blur to reduce noise
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Compute adaptive thresholds based on median gradient
    median = np.median(blurred)
    lower = int(max(0, (1.0 - 0.33) * median))
    upper = int(min(255, (1.0 + 0.33) * median))

    # Fallback to fixed thresholds if median is too low or too high
    if lower < 10 or upper > 245:
        lower, upper = 50, 150

    # Apply Canny edge detection
    edges = cv2.Canny(blurred, lower, upper)

    return edges


def _adaptive_kernel_size(image_shape: tuple[int, int]) -> int:
    """Compute morphological kernel size from image dimensions.

    The kernel must be smaller than the expected gap between panels so that
    morphological closing connects broken edges within a panel without merging
    adjacent panels.  Using 1/50 of the shorter side, clamped to [5, 15],
    gives a reasonable default for typical figure layouts.

    Args:
        image_shape: Image shape (height, width).

    Returns:
        Odd kernel size in pixels.
    """
    shorter = min(image_shape)
    k = max(5, min(15, shorter // 50))
    # Ensure odd size for symmetric morphology
    return k if k % 2 == 1 else k + 1


def connect_edges(edges: np.ndarray, kernel_size: int = 0) -> np.ndarray:
    """Connect broken edges using morphological closing.

    Args:
        edges: Edge map from Canny.
        kernel_size: Size of morphological kernel.  When 0 (default) the size
            is chosen adaptively from the image dimensions; pass an explicit
            value to override.

    Returns:
        Connected edge map.
    """
    if kernel_size <= 0:
        kernel_size = _adaptive_kernel_size(edges.shape)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    return closed


def find_contours(connected_edges: np.ndarray) -> list[np.ndarray]:
    """Find contours in the connected edge map.

    Args:
        connected_edges: Connected edge map

    Returns:
        List of contours
    """
    contours, _ = cv2.findContours(connected_edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return contours


def filter_contours(
    contours: list[np.ndarray],
    image_shape: tuple[int, int],
    min_area_ratio: float = 0.05,
    max_area_ratio: float = 0.95,
    min_extent: float = 0.6,
    min_aspect_ratio: float = 0.2,
    max_aspect_ratio: float = 5.0,
) -> list[np.ndarray]:
    """Filter contours based on area, aspect ratio, and extent.

    Args:
        contours: List of contours
        image_shape: Image shape (height, width)
        min_area_ratio: Minimum panel area as fraction of image area
        max_area_ratio: Maximum panel area as fraction of image area
        min_extent: Minimum extent (contour area / bounding rect area)
        min_aspect_ratio: Minimum aspect ratio (width / height)
        max_aspect_ratio: Maximum aspect ratio (width / height)

    Returns:
        Filtered list of contours
    """
    image_area = image_shape[0] * image_shape[1]
    filtered = []

    for contour in contours:
        # Compute bounding rect
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        aspect_ratio = w / h if h > 0 else 0

        # Compute extent
        contour_area = cv2.contourArea(contour)
        extent = contour_area / area if area > 0 else 0

        # Filter criteria
        area_ratio = area / image_area
        if min_area_ratio <= area_ratio <= max_area_ratio:
            if extent >= min_extent:
                if min_aspect_ratio <= aspect_ratio <= max_aspect_ratio:
                    filtered.append(contour)

    return filtered


def _has_dominant_contour(
    contours: list[np.ndarray],
    image_shape: tuple[int, int],
    threshold: float = 0.40,
) -> bool:
    """Return True when a single contour covers a dominant fraction of the image.

    This is the hallmark signature of panels being merged by an oversized
    morphological kernel: instead of N similarly-sized panel contours we get
    one giant contour that swallows most of the image area.

    Args:
        contours: Filtered contours.
        image_shape: Image shape (height, width).
        threshold: Area ratio above which the largest contour is considered
            dominant.

    Returns:
        True when the largest contour exceeds the threshold.
    """
    if not contours:
        return False
    image_area = image_shape[0] * image_shape[1]
    largest = max(cv2.boundingRect(c)[2] * cv2.boundingRect(c)[3] for c in contours)
    return (largest / image_area) > threshold


def sort_contours_by_position(contours: list[np.ndarray]) -> list[np.ndarray]:
    """Sort contours by position (top-to-bottom, left-to-right).

    Args:
        contours: List of contours

    Returns:
        Sorted list of contours
    """
    # Get bounding rects
    rects = [cv2.boundingRect(c) for c in contours]

    # Sort by y coordinate first, then x coordinate
    sorted_contours = [c for _, c in sorted(zip(rects, contours), key=lambda x: (x[0][1], x[0][0]))]

    return sorted_contours


def assign_panel_labels(count: int) -> list[str]:
    """Assign panel labels (a, b, c, ...).

    Args:
        count: Number of panels

    Returns:
        List of labels
    """
    labels = []
    for i in range(count):
        if i < 26:
            labels.append(chr(ord("a") + i))
        else:
            # For more than 26 panels, use aa, ab, ac, ...
            labels.append(chr(ord("a") + (i // 26) - 1) + chr(ord("a") + (i % 26)))
    return labels


def extract_panels(
    figure_path: Path,
    *,
    figure_id: str,
    output_dir: Path,
    min_area_ratio: float = PANEL_EXTRACTION_DEFAULTS["min_area_ratio"],
    max_area_ratio: float = PANEL_EXTRACTION_DEFAULTS["max_area_ratio"],
    min_extent: float = PANEL_EXTRACTION_DEFAULTS["min_extent"],
    min_panel_count: int = PANEL_EXTRACTION_DEFAULTS["min_panel_count"],
    max_panel_count: int = PANEL_EXTRACTION_DEFAULTS["max_panel_count"],
) -> dict[str, Any]:
    """Extract panels from a figure image.

    Args:
        figure_path: Path to figure image
        figure_id: Figure identifier
        output_dir: Output directory for panels
        min_area_ratio: Minimum panel area as fraction of image area
        max_area_ratio: Maximum panel area as fraction of image area
        min_extent: Minimum extent (contour area / bounding rect area)
        min_panel_count: Minimum number of panels to detect
        max_panel_count: Maximum number of panels to detect

    Returns:
        Dictionary with figure_evidence and panel_evidence
    """
    if cv2 is None or np is None or Image is None:
        return {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "created_by": "engine/static_audit/tools/panel_extraction.py",
            "status": "not_available",
            "figure_id": figure_id,
            "source_image_path": str(figure_path),
            "panel_count": 0,
            "panels": [],
            "errors": ["OpenCV, NumPy, or Pillow is not installed; panel extraction was not computed."],
            "limitations": ["Install opencv-python-headless, numpy, and Pillow to enable panel extraction."],
        }

    # Check if image exists
    if not figure_path.exists():
        return {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "created_by": "engine/static_audit/tools/panel_extraction.py",
            "status": "failed",
            "figure_id": figure_id,
            "source_image_path": str(figure_path),
            "panel_count": 0,
            "panels": [],
            "errors": [f"Figure image not found: {figure_path}"],
            "limitations": [],
        }

    # Load image
    image = cv2.imread(str(figure_path))
    if image is None:
        return {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "created_by": "engine/static_audit/tools/panel_extraction.py",
            "status": "failed",
            "figure_id": figure_id,
            "source_image_path": str(figure_path),
            "panel_count": 0,
            "panels": [],
            "errors": [f"Failed to load image: {figure_path}"],
            "limitations": [],
        }

    height, width = image.shape[:2]

    # Get image dimensions from PIL for consistency
    with Image.open(figure_path) as img:
        pil_width, pil_height = img.size

    # Detect edges
    edges = detect_edges(image)

    # Connect edges with adaptive kernel; fall back to a smaller kernel when
    # the first pass merges distinct panels into one dominant contour.
    connected = connect_edges(edges)
    contours = find_contours(connected)
    filtered_contours = filter_contours(
        contours,
        image.shape,
        min_area_ratio=min_area_ratio,
        max_area_ratio=max_area_ratio,
        min_extent=min_extent,
    )

    current_kernel = _adaptive_kernel_size(image.shape)
    if len(filtered_contours) < min_panel_count and _has_dominant_contour(contours, image.shape):
        smaller_kernel = max(3, current_kernel // 2)
        # Ensure odd
        if smaller_kernel % 2 == 0:
            smaller_kernel += 1
        if smaller_kernel < current_kernel:
            connected = connect_edges(edges, kernel_size=smaller_kernel)
            contours = find_contours(connected)
            filtered_contours = filter_contours(
                contours,
                image.shape,
                min_area_ratio=min_area_ratio,
                max_area_ratio=max_area_ratio,
                min_extent=min_extent,
            )
            current_kernel = smaller_kernel

    # Check if we found any panels
    if len(filtered_contours) < min_panel_count:
        return {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "created_by": "engine/static_audit/tools/panel_extraction.py",
            "status": "skipped",
            "figure_id": figure_id,
            "source_image_path": str(figure_path),
            "panel_count": 0,
            "panels": [],
            "errors": [],
            "limitations": [
                f"Could not detect at least {min_panel_count} panel(s). "
                f"Found {len(filtered_contours)} contour(s). "
                "This may be a single-panel figure or a complex layout."
            ],
        }

    # Limit to max_panel_count
    if len(filtered_contours) > max_panel_count:
        filtered_contours = filtered_contours[:max_panel_count]

    # Sort contours by position
    sorted_contours = sort_contours_by_position(filtered_contours)

    # Assign labels
    labels = assign_panel_labels(len(sorted_contours))

    # Extract panels
    panels = []
    panels_dir = output_dir / "panels" / figure_id
    panels_dir.mkdir(parents=True, exist_ok=True)

    for i, (contour, label) in enumerate(zip(sorted_contours, labels)):
        x, y, w, h = cv2.boundingRect(contour)

        # Compute extraction confidence based on extent and contour regularity
        contour_area = cv2.contourArea(contour)
        bbox_area = w * h
        extent = contour_area / bbox_area if bbox_area > 0 else 0
        confidence = min(1.0, extent * 1.2)  # Scale up slightly

        # Crop panel
        panel_crop = image[y : y + h, x : x + w]

        # Save panel crop
        panel_filename = f"{label}.png"
        panel_path = panels_dir / panel_filename
        cv2.imwrite(str(panel_path), panel_crop)

        # Create panel evidence
        panel_id = f"{figure_id}-{i + 1:02d}"
        panel_evidence = PanelEvidence(
            panel_id=panel_id,
            parent_figure_id=figure_id,
            label=label,
            bbox=[x, y, w, h],
            crop_path=f"panels/{figure_id}/{panel_filename}",
            width=w,
            height=h,
            extraction_confidence=round(confidence, 3),
            extraction_method="contour_edge_detection",
            metadata={
                "contour_area": float(contour_area),
                "extent": round(extent, 3),
            },
        )
        panels.append(panel_evidence.to_dict())

    # Create figure evidence
    # Try to compute relative path, fallback to absolute path
    try:
        relative_image_path = str(figure_path.relative_to(output_dir))
    except ValueError:
        # If figure_path is not under output_dir, use a relative path from workdir
        # This happens when figure_path is in a fixture directory
        relative_image_path = str(figure_path)
        # Try to extract just the filename or a sensible relative path
        if "images" in str(figure_path):
            # Extract path starting from "images/"
            parts = str(figure_path).split("images/")
            if len(parts) > 1:
                relative_image_path = "images/" + parts[-1]

    figure_evidence = FigureEvidence(
        figure_id=figure_id,
        source_image_path=relative_image_path,
        label="",  # Will be filled by figure canonicalizer
        caption="",  # Will be filled by figure canonicalizer
        page_number=None,  # Will be filled by figure canonicalizer
        bbox=None,  # Will be filled by figure canonicalizer
        width=pil_width,
        height=pil_height,
        panel_count=len(panels),
        metadata={"extraction_status": "ran"},
    )

    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/panel_extraction.py",
        "status": "ran",
        "figure_id": figure_id,
        "source_image_path": relative_image_path,
        "figure_evidence": figure_evidence.to_dict(),
        "panel_count": len(panels),
        "panels": panels,
        "errors": [],
        "limitations": [],
    }


def build_figure_evidence_from_ledger(
    workdir: Path,
    evidence_ledger: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build figure evidence from evidence ledger.

    Args:
        workdir: Working directory
        evidence_ledger: Evidence ledger from build_evidence_ledger.py

    Returns:
        List of figure_evidence dicts
    """
    figures = []

    # Extract figures from the current first-party ledger shape and tolerate
    # older/fixture shapes used while the evidence-ledger contract was forming.
    raw_figures = evidence_ledger.get("figures")
    if not isinstance(raw_figures, list):
        raw_figures = evidence_ledger.get("items", [])
    if not isinstance(raw_figures, list):
        raw_figures = []

    for index, item in enumerate(raw_figures, start=1):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "figure":
            figure_id = str(item.get("id") or item.get("figure_id") or f"FE-{index:04d}")
            image_ref = _image_ref_to_relative_path(item.get("image_ref"))
            if not image_ref:
                image_ref = str(item.get("source_image_path") or "")
            if not image_ref:
                continue
            label = item.get("label", "")
            caption_text = item.get("caption_text", "")
            page = item.get("page")
            bbox = item.get("bbox")

            # Get image dimensions
            image_path = workdir / image_ref
            if image_path.exists():
                with Image.open(image_path) as img:
                    width, height = img.size
            else:
                width, height = 0, 0

            figure_evidence = FigureEvidence(
                figure_id=figure_id,
                source_image_path=image_ref,
                label=label,
                caption=caption_text,
                page_number=page,
                bbox=bbox,
                width=width,
                height=height,
                panel_count=0,  # Will be updated by panel extraction
                metadata={"source": "evidence_ledger"},
            )
            figures.append(figure_evidence.to_dict())

    return figures


def _image_ref_to_relative_path(image_ref: Any) -> str:
    if isinstance(image_ref, dict):
        return str(image_ref.get("relative_path") or image_ref.get("path") or image_ref.get("raw") or "")
    if isinstance(image_ref, str):
        return image_ref
    return ""


def build_figure_evidence_from_images(workdir: Path, images_dir: Path) -> list[dict[str, Any]]:
    """Build canonical figure evidence directly from extracted image files."""
    figures: list[dict[str, Any]] = []
    if Image is None:
        return figures
    image_paths = [
        path
        for path in sorted(images_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
    ]
    for index, image_path in enumerate(image_paths, start=1):
        try:
            with Image.open(image_path) as img:
                width, height = img.size
        except Exception:
            width, height = 0, 0
        try:
            relative = str(image_path.relative_to(workdir))
        except ValueError:
            relative = str(image_path)
        figures.append(
            FigureEvidence(
                figure_id=f"FE-{index:04d}",
                source_image_path=relative,
                label=image_path.stem,
                caption="",
                page_number=None,
                bbox=None,
                width=width,
                height=height,
                panel_count=0,
                metadata={"source": "images_dir_fallback"},
            ).to_dict()
        )
    return figures


def whole_figure_panel(figure: dict[str, Any], *, workdir: Path, output_dir: Path) -> dict[str, Any] | None:
    """Create one panel covering the full figure when contour splitting fails."""
    source_rel = str(figure.get("source_image_path") or "")
    if not source_rel:
        return None
    source_path = workdir / source_rel
    if not source_path.exists() or not source_path.is_file():
        return None
    figure_id = str(figure.get("figure_id") or "FE-UNKNOWN")
    panel_dir = output_dir / "panels" / figure_id
    panel_dir.mkdir(parents=True, exist_ok=True)
    crop_path = panel_dir / "a.png"
    if not crop_path.exists():
        shutil.copyfile(source_path, crop_path)
    try:
        with Image.open(source_path) as img:
            width, height = img.size
    except Exception:
        width = int(figure.get("width") or 0)
        height = int(figure.get("height") or 0)
    rel_crop = str(crop_path.relative_to(output_dir))
    return PanelEvidence(
        panel_id=f"{figure_id}-01",
        parent_figure_id=figure_id,
        label="a",
        bbox=[0, 0, width, height],
        crop_path=rel_crop,
        width=width,
        height=height,
        extraction_confidence=0.5,
        extraction_method="whole_figure_fallback",
        metadata={"source_image_path": source_rel, "fallback_reason": "no_contour_panels_detected"},
    ).to_dict()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Extract panels from figure images.")
    parser.add_argument("figure_path", help="Path to figure image")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--output-dir", required=True, help="Output directory for panels")
    parser.add_argument("--figure-id", required=True, help="Figure identifier")
    parser.add_argument(
        "--min-area-ratio",
        type=float,
        default=PANEL_EXTRACTION_DEFAULTS["min_area_ratio"],
        help="Minimum panel area as fraction of image area",
    )
    parser.add_argument(
        "--max-area-ratio",
        type=float,
        default=PANEL_EXTRACTION_DEFAULTS["max_area_ratio"],
        help="Maximum panel area as fraction of image area",
    )
    parser.add_argument(
        "--min-extent",
        type=float,
        default=PANEL_EXTRACTION_DEFAULTS["min_extent"],
        help="Minimum extent (contour area / bounding rect area)",
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()
    figure_path = Path(args.figure_path).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    result = extract_panels(
        figure_path,
        figure_id=args.figure_id,
        output_dir=output_dir,
        min_area_ratio=args.min_area_ratio,
        max_area_ratio=args.max_area_ratio,
        min_extent=args.min_extent,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "output": str(output),
                "status": result["status"],
                "panel_count": result["panel_count"],
            },
            ensure_ascii=False,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
