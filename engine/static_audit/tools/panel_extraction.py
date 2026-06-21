"""Panel extraction tool using YOLOv5 object detection.

This module extracts individual panels from composite scientific figure images
by calling the ELIS panel-extractor (YOLOv5) via subprocess.  It replaces the
previous OpenCV contour-based approach with learned panel detection and
semantic classification (Blots, Graphs, Microscopy, Body Imaging, Flow Cytometry).

Architecture:
  Veritas orchestrator
    → extract_panels_batch() — single subprocess call with all images
    → ELIS panel-extractor (YOLOv5) — model loads once, processes all images
    → PANELS.csv — one row per detected panel
    → _parse_yolov5_csv() — convert to PanelEvidence schema
    → visual_evidence.json + panel_evidence.json

When YOLOv5 detects zero panels for a figure, the orchestrator falls back to
whole_figure_panel() which creates a single panel covering the entire image.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from engine.static_audit.visual_schemas import (
    FigureEvidence,
    PanelEvidence,
    VISUAL_SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ELIS_PANEL_EXTRACTOR = (
    _REPO_ROOT / "third_party" / "elis" / "system_modules" / "panel-extractor"
)
DEFAULT_WEIGHTS = _REPO_ROOT / "models" / "panel_extraction" / "model_5_class.pt"

EXTRACTION_METHOD_YOLOV5 = "yolov5_panel_extractor"
EXTRACTION_METHOD_FALLBACK = "whole_figure_fallback"

# Panel types that require visual forensics analysis (copy-move, overlap, etc.).
# Code-generated deterministic visualizations (Graphs, etc.) are excluded because
# their geometric repetition is normal and visual forensic tools produce high
# false-positive rates on these modalities. They are verified via code/data
# forensics instead.
#
# Flow Cytometry is INCLUDED because:
#   - FACS dot plots / contour plots can be image-level duplicated (same point
#     cloud relabelled as different treatment/timepoint/cell line) — BioFors
#     dataset includes FACS as a dedicated forensics category
#   - Visual similarity across panels is a genuine reuse signal, not a normal
#     geometric artifact as with Graphs
VISUAL_FORENSICS_PANEL_TYPES = {"Blots", "Microscopy", "Body Imaging", "Flow Cytometry"}

# Maximum panels per figure.  YOLOv5 over-segments grid images (spatial
# transcriptomics, blot montages) — e.g. a 4×10 cell grid yields 40 detections.
# Real multi-panel figures in biomedical papers rarely exceed 9 panels.
# Distribution on paper2: 1-9 panels = normal, 12+ = over-segmentation (no
# values in 10-11 range).  When exceeded, the orchestrator falls back to a
# single whole-figure panel.
MAX_PANELS_PER_FIGURE = 16


# ---------------------------------------------------------------------------
# Batch YOLOv5 extraction
# ---------------------------------------------------------------------------


def extract_panels_batch(
    figure_paths: list[tuple[str, Path]],
    *,
    output_dir: Path,
    weights_path: Path = DEFAULT_WEIGHTS,
    device: str = "0",
    conf_thres: float = 0.4,
    iou_thres: float = 0.4,
    imgsz: int = 640,
    figure_labels: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Run YOLOv5 panel extraction on all figures in a single subprocess.

    Args:
        figure_paths: List of (figure_id, absolute_image_path) tuples.
        output_dir: Working directory for panel output.
        weights_path: Path to YOLOv5 model weights.
        device: CUDA device ('0') or 'cpu'.
        conf_thres: Confidence threshold.
        iou_thres: NMS IoU threshold.
        imgsz: Inference image size.
        figure_labels: Optional mapping of figure_id → paper_figure_label
            (e.g. from evidence ledger caption). Used for crop filenames and
            panel evidence metadata.

    Returns:
        Dict mapping figure_id → list of PanelEvidence dicts.
    """
    if not figure_paths:
        return {}

    # Check prerequisites
    extract_script = ELIS_PANEL_EXTRACTOR / "extract.py"
    if not extract_script.is_file():
        logger.warning(
            "ELIS panel-extractor not found at %s. "
            "Panel extraction skipped; falling back to whole-figure panels.",
            extract_script,
        )
        return {fid: [] for fid, _ in figure_paths}
    if not weights_path.is_file():
        logger.warning(
            "Model weights not found at %s. "
            "Run `make download-models` to download YOLOv5 weights. "
            "Panel extraction skipped; falling back to whole-figure panels.",
            weights_path,
        )
        return {fid: [] for fid, _ in figure_paths}

    # Create batch output directory
    batch_output = output_dir / "yolov5_batch"
    batch_output.mkdir(parents=True, exist_ok=True)

    # Build command: pass all image paths to a single YOLOv5 invocation
    input_paths = [str(path) for _, path in figure_paths]
    cmd = [
        sys.executable,
        str(extract_script),
        "--input-path",
        *input_paths,
        "--output-path",
        str(batch_output),
        "--weights",
        str(weights_path),
        "--device",
        device,
        "--conf-thres",
        str(conf_thres),
        "--iou-thres",
        str(iou_thres),
        "--imgsz",
        str(imgsz),
        "--save_img",
        "True",
    ]

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(300, len(figure_paths) * 5),
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {fid: [] for fid, _ in figure_paths}

    # Parse PANELS.csv and distribute to figures
    csv_path = batch_output / "PANELS.csv"
    return _distribute_panels_from_csv(
        csv_path,
        figure_paths,
        batch_output,
        output_dir,
        figure_labels=figure_labels,
    )


def _distribute_panels_from_csv(
    csv_path: Path,
    figure_paths: list[tuple[str, Path]],
    batch_output: Path,
    output_dir: Path,
    figure_labels: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Parse PANELS.csv and map panels to their parent figures.

    The CSV FIGNAME column contains the image file stem.  We match stems back
    to figure_ids via the figure_paths list.

    Args:
        figure_labels: Optional mapping of figure_id → paper_figure_label
            from the evidence ledger. Used for crop filenames and panel
            evidence metadata.
    """
    # Build stem → figure_id mapping
    stem_to_fid: dict[str, str] = {}
    for fid, path in figure_paths:
        stem_to_fid[path.stem] = fid

    # Initialize result for all figures
    result: dict[str, list[dict[str, Any]]] = {fid: [] for fid, _ in figure_paths}

    if not csv_path.is_file():
        return result

    # Parse CSV — ELIS uses ", " (comma-space) as separator
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="") as f:
        content = f.read()
    # ELIS writes rows with ", " separator; normalise to standard CSV
    content = content.replace(", ", ",")
    reader = csv.DictReader(content.splitlines())
    for row in reader:
        rows.append(row)

    # Group rows by FIGNAME
    from collections import defaultdict

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        figname = row.get("FIGNAME", "")
        if figname:
            grouped[figname].append(row)

    # Convert to PanelEvidence dicts
    for figname, fig_rows in grouped.items():
        fid = stem_to_fid.get(figname)
        if fid is None:
            continue
        paper_label = (figure_labels or {}).get(fid)
        panels = _convert_csv_rows_to_panels(
            fid, fig_rows, batch_output, output_dir, paper_figure_label=paper_label
        )
        result[fid] = panels

    return result


def _convert_csv_rows_to_panels(
    figure_id: str,
    rows: list[dict[str, str]],
    batch_output: Path,
    output_dir: Path,
    paper_figure_label: str | None = None,
) -> list[dict[str, Any]]:
    """Convert PANELS.csv rows for one figure into PanelEvidence dicts."""
    if len(rows) > MAX_PANELS_PER_FIGURE:
        logger.warning(
            "Figure %s: YOLOv5 produced %d panels (max=%d). "
            "Likely over-segmentation of a grid/montage image. "
            "Falling back to whole-figure panel.",
            figure_id,
            len(rows),
            MAX_PANELS_PER_FIGURE,
        )
        return []

    panels: list[dict[str, Any]] = []
    panels_dir = output_dir / "panels" / figure_id
    panels_dir.mkdir(parents=True, exist_ok=True)

    skipped_count = 0
    for idx, row in enumerate(rows):
        try:
            x0 = int(float(row.get("X0", "0")))
            y0 = int(float(row.get("Y0", "0")))
            x1 = int(float(row.get("X1", "0")))
            y1 = int(float(row.get("Y1", "0")))
        except (ValueError, TypeError):
            continue

        w = x1 - x0
        h = y1 - y0
        if w <= 0 or h <= 0:
            continue

        panel_type_raw = row.get("LABEL", "")
        # Normalise panel type to schema-allowed values
        panel_type = _normalise_panel_type(panel_type_raw)

        # Filter: only extract panels that require visual forensics.
        # Code-generated panels (Graphs, etc.) are skipped because visual
        # forensics tools produce high false-positive rates on these modalities.
        # They are verified via code/data forensics instead.
        # Flow Cytometry is kept — FACS plot reuse is a genuine image-level
        # forensics signal (BioFors dataset includes FACS as a category).
        if panel_type not in VISUAL_FORENSICS_PANEL_TYPES:
            skipped_count += 1
            logger.debug(
                "Skipping panel %s-%02d (type=%s): code-generated visualization, "
                "verified via code/data forensics",
                figure_id,
                idx + 1,
                panel_type,
            )
            continue

        label = _index_to_label(idx)

        # Move crop from batch output to canonical location
        crop_src = _find_crop_file(
            batch_output, row.get("FIGNAME", ""), idx, panel_type_raw
        )
        crop_filename = _build_crop_filename(
            paper_figure_label, figure_id, idx + 1, panel_type_raw
        )
        crop_dst = panels_dir / crop_filename
        if crop_src and crop_src.is_file():
            shutil.move(str(crop_src), str(crop_dst))
        elif not crop_dst.is_file():
            # Crop file not found; skip this panel
            continue

        rel_crop = str(crop_dst.relative_to(output_dir))
        panel_id = f"{figure_id}-{idx + 1:02d}"

        panel = PanelEvidence(
            panel_id=panel_id,
            parent_figure_id=figure_id,
            label=label,
            bbox=[x0, y0, w, h],
            crop_path=rel_crop,
            width=w,
            height=h,
            extraction_confidence=0.8,
            extraction_method=EXTRACTION_METHOD_YOLOV5,
            panel_type=panel_type,
            paper_figure_label=paper_figure_label,
            metadata={
                "yolov5_label": panel_type_raw,
                "yolov5_id": row.get("ID", ""),
            },
        )
        panels.append(panel.to_dict())

    if skipped_count > 0:
        logger.info(
            "Figure %s: extracted %d panels for visual forensics, "
            "skipped %d code-generated panels (Graphs/etc.)",
            figure_id,
            len(panels),
            skipped_count,
        )

    return panels


def _find_crop_file(
    batch_output: Path,
    figname: str,
    panel_index: int,
    class_name: str,
) -> Path | None:
    """Locate the crop file written by YOLOv5 for a given panel.

    ELIS saves crops as: {batch_output}/{figname}_{1-based-index}_{ClassName}.png
    """
    # ELIS uses 1-based crop index in filename
    crop_idx = panel_index + 1
    # Try exact class name first
    candidate = batch_output / f"{figname}_{crop_idx}_{class_name}.png"
    if candidate.is_file():
        return candidate
    # Try common variations (singular/plural)
    for alt in _class_name_variations(class_name):
        candidate = batch_output / f"{figname}_{crop_idx}_{alt}.png"
        if candidate.is_file():
            return candidate
    # Glob fallback: any file matching {figname}_{crop_idx}_*.png
    matches = list(batch_output.glob(f"{figname}_{crop_idx}_*.png"))
    return matches[0] if matches else None


def _class_name_variations(name: str) -> list[str]:
    """Return singular/plural variations of a YOLOv5 class name."""
    if not name:
        return []
    variations = [name]
    if name.endswith("s"):
        variations.append(name[:-1])  # Blots → Blot
    else:
        variations.append(name + "s")  # Blot → Blots
    return variations


def _normalise_panel_type(raw: str) -> str | None:
    """Map a YOLOv5 class name to a PanelEvidence.PANEL_TYPES value."""
    if not raw:
        return None
    # Direct match
    if raw in PanelEvidence.PANEL_TYPES:
        return raw
    # Case-insensitive match
    lower = raw.lower()
    for pt in PanelEvidence.PANEL_TYPES:
        if pt.lower() == lower:
            return pt
    # Singular/plural match
    for pt in PanelEvidence.PANEL_TYPES:
        if pt.lower().startswith(lower) or lower.startswith(pt.lower()):
            return pt
    return raw  # Keep original if no match; schema validation is lenient


def _index_to_label(index: int) -> str:
    """Convert a 0-based panel index to an alphabetic label (a, b, c, ...)."""
    if index < 26:
        return chr(ord("a") + index)
    return chr(ord("a") + (index // 26) - 1) + chr(ord("a") + (index % 26))


def _sanitize_for_filename(name: str) -> str:
    """Sanitize a string for use in a filename (replace spaces, strip unsafe chars)."""
    return name.replace(" ", "_").replace("/", "_")


def _build_crop_filename(
    paper_figure_label: str | None,
    figure_id: str,
    panel_index: int,
    modality: str,
) -> str:
    """Build a human-readable crop filename for a panel.

    Format: {paper_figure_label or figure_id}_panel{idx:02d}_{modality}.png
    Example: Fig3b_panel01_Blots.png (with label)
    Example: figure-0003_panel01_Graphs.png (fallback)
    """
    label_part = (
        _sanitize_for_filename(paper_figure_label)
        if paper_figure_label
        else _sanitize_for_filename(figure_id)
    )
    modality_part = _sanitize_for_filename(modality) if modality else "unknown"
    return f"{label_part}_panel{panel_index:02d}_{modality_part}.png"


# ---------------------------------------------------------------------------
# Figure evidence builders (unchanged from previous version)
# ---------------------------------------------------------------------------


def _deduplicate_ledger_figures(
    raw_figures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge figure entries pointing to the same image file.

    The upstream evidence ledger builder concatenates figure entries from
    multiple sources (markdown refs, content blocks, middle blocks) without
    deduplication.  When the same image is referenced in both markdown and
    structured blocks, this produces duplicate entries.

    Dedup key: resolved image relative path.  When duplicates are found,
    prefer the entry with richer structural data (content/middle sources
    have page/bbox; markdown sources have alt_text).  All metadata is merged.
    """
    seen: dict[str, dict[str, Any]] = {}

    for fig in raw_figures:
        if not isinstance(fig, dict):
            continue
        image_ref = fig.get("image_ref")
        rel_path = None
        if isinstance(image_ref, dict):
            rel_path = image_ref.get("relative_path") or image_ref.get("path")
        if not rel_path:
            rel_path = fig.get("source_image_path")
        if not rel_path:
            seen[f"__no_path_{id(fig)}"] = fig
            continue

        if rel_path in seen:
            existing = seen[rel_path]
            if fig.get("page") and not existing.get("page"):
                fig.setdefault("metadata", {})
                fig["metadata"]["_merged_from"] = existing.get("id")
                seen[rel_path] = fig
            elif not fig.get("page") and existing.get("page"):
                existing.setdefault("metadata", {})
                existing["metadata"]["_merged_from"] = fig.get("id")
        else:
            seen[rel_path] = fig

    return list(seen.values())


def build_figure_evidence_from_ledger(
    workdir: Path,
    evidence_ledger: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build figure evidence from evidence ledger."""
    figures = []

    raw_figures = evidence_ledger.get("figures")
    if not isinstance(raw_figures, list):
        raw_figures = evidence_ledger.get("items", [])
    if not isinstance(raw_figures, list):
        raw_figures = []

    raw_figures = _deduplicate_ledger_figures(raw_figures)

    for index, item in enumerate(raw_figures, start=1):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "figure":
            figure_id = str(
                item.get("id") or item.get("figure_id") or f"FE-{index:04d}"
            )
            image_ref = _image_ref_to_relative_path(item.get("image_ref"))
            if not image_ref:
                image_ref = str(item.get("source_image_path") or "")
            if not image_ref:
                continue
            label = item.get("label", "")
            caption_text = item.get("caption_text", "")
            page = item.get("page")
            bbox = item.get("bbox")

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
                panel_count=0,
                metadata={"source": "evidence_ledger"},
            )
            figures.append(figure_evidence.to_dict())

    return figures


def _image_ref_to_relative_path(image_ref: Any) -> str:
    if isinstance(image_ref, dict):
        return str(
            image_ref.get("relative_path")
            or image_ref.get("path")
            or image_ref.get("raw")
            or ""
        )
    if isinstance(image_ref, str):
        return image_ref
    return ""


def build_figure_evidence_from_images(
    workdir: Path, images_dir: Path
) -> list[dict[str, Any]]:
    """Build canonical figure evidence directly from extracted image files."""
    figures: list[dict[str, Any]] = []
    image_paths = [
        path
        for path in sorted(images_dir.rglob("*"))
        if path.is_file()
        and path.suffix.lower()
        in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
    ]
    for index, image_path in enumerate(image_paths, start=1):
        try:
            with Image.open(image_path) as img:
                width, height = img.size
        except OSError:
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


def whole_figure_panel(
    figure: dict[str, Any], *, workdir: Path, output_dir: Path
) -> dict[str, Any] | None:
    """Create one panel covering the full figure when panel detection fails."""
    source_rel = str(figure.get("source_image_path") or "")
    if not source_rel:
        return None
    source_path = workdir / source_rel
    if not source_path.exists() or not source_path.is_file():
        return None
    figure_id = str(figure.get("figure_id") or "FE-UNKNOWN")
    paper_figure_label = figure.get("label") or None
    panel_dir = output_dir / "panels" / figure_id
    panel_dir.mkdir(parents=True, exist_ok=True)
    crop_filename = _build_crop_filename(
        paper_figure_label, figure_id, 1, "whole_figure"
    )
    crop_path = panel_dir / crop_filename
    if not crop_path.exists():
        shutil.copyfile(source_path, crop_path)
    try:
        with Image.open(source_path) as img:
            width, height = img.size
    except OSError:
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
        extraction_method=EXTRACTION_METHOD_FALLBACK,
        paper_figure_label=paper_figure_label,
        metadata={
            "source_image_path": source_rel,
            "fallback_reason": "yolov5_detected_no_panels",
        },
    ).to_dict()


# ---------------------------------------------------------------------------
# Fallback panel classification (post-hoc heuristic typing)
# ---------------------------------------------------------------------------


def _classify_fallback_panels(panels: list[dict[str, Any]], *, workdir: Path) -> None:
    """Classify fallback panels in-place using image-size and color heuristics.

    Only panels whose ``extraction_method`` equals
    :data:`EXTRACTION_METHOD_FALLBACK` **and** whose ``panel_type`` is unset or
    falsy are touched. YOLOv5-classified panels are never modified.

    The heuristics are intentionally weak because they run on the whole figure
    after YOLOv5 has already failed to detect any sub-panels. They record a
    best-effort guess so that downstream forensics routing
    (see :data:`VISUAL_FORENSICS_PANEL_TYPES`) can make informed decisions, and
    annotate each decision via ``_fallback_panel_type_source`` in metadata so
    consumers can tell "observed by model" from "inferred by heuristic".

    Heuristic rules (evaluated in order; first match wins):
      1. aspect_ratio (h/w or w/h) > 3:1 → ``Graph`` (strip/ribbon layout).
      2. Blue or purple pixel mass > 25 % → ``Microscopy`` (H&E / fluorescence).
      3. ≥ 60 % gray pixels (40–200 luminance) **and** any RGB channel
         variance in (500, 4000) → ``Blots`` (uniform PVDF background +
         localized dark bands).
      4. Otherwise → ``Body Imaging`` (catch-all for real photographic content
         that is not microscopy).

    Args:
        panels: List of panel dicts. Modified in-place.
        workdir: Working directory used to resolve relative ``crop_path`` values.
    """
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        if panel.get("extraction_method") != EXTRACTION_METHOD_FALLBACK:
            continue
        if panel.get("panel_type"):
            continue  # already typed — don't override

        crop_rel = str(panel.get("crop_path") or "")
        if not crop_rel:
            continue
        try:
            image_path = (workdir / crop_rel).resolve()
            if not image_path.is_file():
                continue
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                width, height = img.size
                if width <= 0 or height <= 0:
                    continue
                panel_type = _heuristic_panel_type(img, width, height)
        except OSError:
            continue

        if panel_type:
            panel["panel_type"] = panel_type
            metadata = (
                panel.get("metadata") if isinstance(panel.get("metadata"), dict) else {}
            )
            metadata["_fallback_panel_type_source"] = (
                "heuristic_aspect_ratio"
                if panel_type == "Graph"
                else "heuristic_dominant_color"
                if panel_type == "Microscopy"
                else "heuristic_gray_background_variance"
                if panel_type == "Blots"
                else "heuristic_default_photographic"
            )
            panel["metadata"] = metadata


def _heuristic_panel_type(img: "Image.Image", width: int, height: int) -> str:
    """Return a best-effort panel type for a whole-figure fallback image.

    Pure function of image content. Returns one of the schema
    :data:`PanelEvidence.PANEL_TYPES` values or ``""`` when no rule matches
    confidently (caller falls through to no-op).
    """
    # Rule 1 — strip / ribbon aspect ratio.
    # Use max(h/w, w/h) so both tall vertical strips and wide horizontal strips
    # are caught with the same threshold.
    aspect_ratio = max(height / width, width / height)
    if aspect_ratio > 3.0:
        return "Graph"

    # Rule 2 — microscopy: dominant blue or purple stain (H&E, DAPI, ...).
    # Use pixel access by coordinate (deprecated-free) and sample every 4th
    # pixel to keep cost bounded on large images.
    pixels = img.load()
    cols, rows = img.size
    sample_coords: list[tuple[int, int]] = [
        (i % cols, i // cols)
        for i in range(0, cols * rows, max(1, cols * rows // 5000))
    ]
    sampled = [pixels[x, y] for x, y in sample_coords]
    n = len(sampled)
    if n == 0:
        return ""

    blue_count = sum(
        1 for r, g, b in sampled if b > 100 and b > r * 1.3 and b > g * 1.3
    )
    purple_count = sum(
        1 for r, g, b in sampled if r > 80 and b > 80 and r > g * 1.2 and b > g * 1.2
    )
    if (blue_count + purple_count) / n > 0.25:
        return "Microscopy"

    # Rule 3 — blots: uniform gray PVDF background + localized dark bands.
    # "Gray" = within ±25 of neutral; "small target" = ≥ 60 % of pixels are
    # background-gray yet at least one color channel has measurable variance
    # (bands contribute variance). Variance window (500, 4000) separates
    # "flat blank membrane" from "membrane with bands" from "complex photo".
    gray = img.convert("L")
    gray_px = gray.load()
    gray_samples = [gray_px[x, y] for x, y in sample_coords]
    n_gray = len(gray_samples)
    gray_bg_count = sum(1 for p in gray_samples if 40 <= p <= 200)
    gray_ratio = gray_bg_count / n_gray if n_gray else 0
    if gray_ratio < 0.6:
        return ""
    r_ch, g_ch, b_ch = img.split()
    for channel in (r_ch, g_ch, b_ch):
        ch_px = channel.load()
        ch_samples = [ch_px[x, y] for x, y in sample_coords]
        mean_val = sum(ch_samples) / len(ch_samples)
        variance = sum((p - mean_val) ** 2 for p in ch_samples) / len(ch_samples)
        if 500 < variance < 4000:
            return "Blots"

    return ""


# ---------------------------------------------------------------------------
# CLI entry point (kept for standalone usage / testing)
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract panels from figure images using YOLOv5."
    )
    parser.add_argument("figure_paths", nargs="+", help="Path(s) to figure image(s)")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument(
        "--output-dir", required=True, help="Output directory for panels"
    )
    parser.add_argument(
        "--weights", default=str(DEFAULT_WEIGHTS), help="Path to YOLOv5 weights"
    )
    parser.add_argument("--device", default="0", help="CUDA device or 'cpu'")
    parser.add_argument("--conf-thres", type=float, default=0.4)
    parser.add_argument("--iou-thres", type=float, default=0.4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()

    figure_paths = [
        (Path(p).stem, Path(p).expanduser().resolve()) for p in args.figure_paths
    ]
    batch_result = extract_panels_batch(
        [(stem, path) for stem, path in figure_paths],
        output_dir=output_dir,
        weights_path=Path(args.weights),
        device=args.device,
        conf_thres=args.conf_thres,
        iou_thres=args.iou_thres,
    )

    total_panels = sum(len(v) for v in batch_result.values())
    result = {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "status": "ran" if total_panels > 0 else "skipped",
        "figure_count": len(figure_paths),
        "panel_count": total_panels,
        "panels_by_figure": {fid: panels for fid, panels in batch_result.items()},
    }

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
                "panel_count": total_panels,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
