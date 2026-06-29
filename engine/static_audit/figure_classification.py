"""Figure classification via LLM legend analysis.

Parses figure legends from MinerU's full.md and uses LLM to classify each
figure's panels into: wet_lab | bioinformatics | mixed | other.

This enables downstream visual forensics (TruFor, Copy-Move) to focus on
wet-lab panels only, reducing false positives and computation time.

Architecture:
    full.md (MinerU output)
        -> parse_figure_legends()  — extract legend text per figure
        -> classify_figure()       — LLM call per figure
        -> figure_classification.json

Downstream:
    visual_pipeline.py reads figure_classification.json to annotate panels
    with panel_classification field, then filters wet_lab|mixed panels for
    TruFor/Copy-Move analysis.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from engine.static_audit._shared import (
    ProgressCallback,
    StepResult,
    emit_step_start,
    existing_artifact_path,
    record_step,
    resolve_artifact_path,
    write_json_artifact,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Legend parsing
# ---------------------------------------------------------------------------

# Matches figure headings in full.md:
#   "# Fig. 1 | Title"
#   "# Extended Data Fig. 1 | Title"
#   "## Fig. 10 | Title"
_FIGURE_HEADING_RE = re.compile(
    r"^#+\s*((?:Extended\s+Data\s+)?Fig(?:ure)?\.?\s*\d+[a-z]?)\s*\|?\s*(.*)",
    re.IGNORECASE | re.MULTILINE,
)

# Matches inline figure legends (no heading marker):
#   "Fig. 2 | Title. a, Description..."
#   "Extended Data Fig. 1 | Title. a, Description..."
_INLINE_LEGEND_RE = re.compile(
    r"^((?:Extended\s+Data\s+)?Fig(?:ure)?\.?\s*\d+[a-z]?)\s*\|\s*(.*)",
    re.IGNORECASE | re.MULTILINE,
)


def parse_figure_legends(full_md_text: str) -> dict[str, str]:
    """Extract figure legends from full.md text.

    Returns:
        {figure_label: legend_text}
        e.g. {"Fig. 1": "ScRNA-seq and spatial profiling...",
              "Extended Data Fig. 1": "..."}

    Handles both heading-based legends (# Fig. 1 | ...) and inline legends
    (Fig. 2 | ...).
    """
    legends: dict[str, str] = {}

    # Split by markdown headings to get sections
    lines = full_md_text.split("\n")
    current_figure: str | None = None
    current_legend_lines: list[str] = []

    for line in lines:
        # Check if this line is a figure heading
        heading_match = _FIGURE_HEADING_RE.match(line)
        if heading_match:
            # Save previous figure's legend
            if current_figure and current_legend_lines:
                legends[current_figure] = "\n".join(current_legend_lines).strip()

            current_figure = _normalize_figure_label(heading_match.group(1))
            # Start collecting legend from the title part
            title_part = heading_match.group(2).strip()
            current_legend_lines = [title_part] if title_part else []
            continue

        # Check if this is a new heading (non-figure) — stop collecting
        if line.startswith("#"):
            if current_figure and current_legend_lines:
                legends[current_figure] = "\n".join(current_legend_lines).strip()
                current_figure = None
                current_legend_lines = []
            continue

        # If we're collecting a figure legend, add this line
        if current_figure is not None:
            current_legend_lines.append(line)

    # Save last figure if file doesn't end with a heading
    if current_figure and current_legend_lines:
        legends[current_figure] = "\n".join(current_legend_lines).strip()

    # Also scan for inline legends (not under headings)
    for match in _INLINE_LEGEND_RE.finditer(full_md_text):
        label = _normalize_figure_label(match.group(1))
        if label not in legends:
            # Collect text until next blank line or figure reference
            end = match.end()
            # Find the end of this paragraph (double newline or next figure)
            remaining = full_md_text[end:]
            para_end = re.search(r"\n\n|\n(?=(?:Extended\s+Data\s+)?Fig)", remaining)
            if para_end:
                legend_text = match.group(2) + remaining[: para_end.start()]
            else:
                legend_text = match.group(2) + remaining[:500]  # limit
            legends[label] = legend_text.strip()

    return legends


def _normalize_figure_label(label: str) -> str:
    """Normalize figure label to canonical form: 'Fig. N' or 'Extended Data Fig. N'."""
    # Remove extra whitespace
    label = re.sub(r"\s+", " ", label.strip())
    # Ensure consistent format
    label = re.sub(r"Figure\.?", "Fig.", label, flags=re.IGNORECASE)
    label = re.sub(r"Fig\.?\s*", "Fig. ", label, flags=re.IGNORECASE)
    label = re.sub(r"^extended data\s+", "Extended Data ", label, flags=re.IGNORECASE)
    label = re.sub(r"^fig\. ", "Fig. ", label, flags=re.IGNORECASE)
    return label


# ---------------------------------------------------------------------------
# LLM classification
# ---------------------------------------------------------------------------

_CLASSIFICATION_PROMPT_TEMPLATE = """You are analyzing a scientific paper's figure legend to classify each panel.

Figure: {figure_label}
Legend:
{legend_text}

Classify each panel based on its description:

Classification rules:
- wet_lab: Real photographic images (blot, microscopy, IHC/IF, gel, flow cytometry scatter plots, tissue/animal photos, histology)
- bioinformatics: Code-generated visualizations (UMAP/t-SNE, heatmap, volcano plot, survival curve, bar/line/scatter chart, pseudotime graph, bubble chart)
- mixed: Figure contains both wet_lab and bioinformatics panels
- other: Schematic diagrams, flowcharts, 3D renders, cartoons, illustrations

Return JSON with panel descriptions and classifications:
{{
  "a": {{"description": "Brief description from legend", "classification": "wet_lab|bioinformatics|mixed|other"}},
  "b": {{"description": "...", "classification": "..."}},
  ...
}}

If the figure has no panel structure (single image), use "figure" as the key.
If the legend is unclear or malformed, return empty {{}}.
Return ONLY valid JSON, no explanations."""


def classify_figure(
    figure_label: str,
    legend_text: str,
    llm_client: Any,
) -> dict[str, dict[str, str]]:
    """Call LLM to classify panels in a single figure.

    Args:
        figure_label: e.g. "Fig. 1", "Extended Data Fig. 2"
        legend_text: The full legend text for this figure
        llm_client: VeritasLLMClient instance

    Returns:
        {panel_label: {"description": str, "classification": str}}
        e.g. {"a": {"description": "UMAP plot...", "classification": "bioinformatics"},
              "b": {"description": "Western blot...", "classification": "wet_lab"}}
        Returns empty dict if LLM fails or legend is unparseable.
    """
    if not legend_text.strip():
        logger.warning("Empty legend for %s, skipping classification", figure_label)
        return {}

    prompt = _CLASSIFICATION_PROMPT_TEMPLATE.format(
        figure_label=figure_label,
        legend_text=legend_text[:3000],  # Limit to avoid token overflow
    )

    try:
        result = llm_client.chat_json(prompt)
        if not isinstance(result, dict):
            logger.warning(
                "LLM returned non-dict for %s: %r", figure_label, type(result)
            )
            return {}
        return result
    except Exception as e:  # Deliberately broad: LLM client can raise VeritasLLMParseError, network errors, etc.
        logger.warning("LLM classification failed for %s: %s", figure_label, e)
        return {}


def classify_all_figures(
    legends: dict[str, str],
    llm_client: Any,
) -> dict[str, dict[str, dict[str, str]]]:
    """Classify all figures in the paper.

    Attempts batch classification (1 LLM call) first.  If the batch call
    fails for any reason, falls back to per-figure calls automatically.

    Args:
        legends: {figure_label: legend_text} from parse_figure_legends()
        llm_client: VeritasLLMClient instance

    Returns:
        {figure_label: {panel_label: {"description": str, "classification": str}}}
    """
    if len(legends) > 1:
        try:
            return classify_all_figures_batch(legends, llm_client)
        except Exception as e:  # Deliberately broad: batch LLM call may raise VeritasLLMParseError, network errors, etc.
            logger.warning(
                "Batch classification failed, falling back to per-figure: %s", e
            )

    # Fallback: per-figure calls (original path)
    results: dict[str, dict[str, dict[str, str]]] = {}
    for label, legend in legends.items():
        results[label] = classify_figure(label, legend, llm_client)
    return results


# ---------------------------------------------------------------------------
# Batch classification (18 calls → 1 call)
# ---------------------------------------------------------------------------

_BATCH_PROMPT_TEMPLATE = """You are analyzing a scientific paper's figure legends to classify each panel in every figure.

Below are {figure_count} figures with their legends.

{legend_block}

Classification rules (apply to each panel):
- wet_lab: Real photographic images (blot, microscopy, IHC/IF, gel, flow cytometry scatter plots, tissue/animal photos, histology)
- bioinformatics: Code-generated visualizations (UMAP/t-SNE, heatmap, volcano plot, survival curve, bar/line/scatter chart, pseudotime graph, bubble chart)
- mixed: Figure contains both wet_lab and bioinformatics panels
- other: Schematic diagrams, flowcharts, 3D renders, cartoons, illustrations

Return ONLY valid JSON in this exact structure (one key per figure, nested panel keys):
{{
  "{first_fig_id}": {{
    "a": {{"description": "Brief description from legend", "classification": "wet_lab|bioinformatics|mixed|other"}},
    "b": {{"description": "...", "classification": "..."}}
  }},
  "{second_fig_id}": {{
    ...
  }}
}}

Rules:
1. Every figure listed above MUST appear as a top-level key.
2. If a figure has no panel structure (single image), use "figure" as the panel key.
3. If a legend is unclear, return empty {{}} for that figure.
4. Return ONLY valid JSON, no explanations."""


def build_batch_classification_prompt(legends: dict[str, str]) -> str:
    """Build a single prompt that classifies all figures at once.

    Each figure's legend is truncated to 1500 chars (vs 3000 for single calls)
    to keep the combined prompt within reasonable token limits.
    """
    legend_parts: list[str] = []
    for fig_id, legend in legends.items():
        legend_parts.append(f"[{fig_id}]\n{legend[:1500]}")

    legend_block = "\n\n".join(legend_parts)
    fig_ids = list(legends.keys())

    return _BATCH_PROMPT_TEMPLATE.format(
        figure_count=len(legends),
        legend_block=legend_block,
        first_fig_id=fig_ids[0] if fig_ids else "Fig. 1",
        second_fig_id=fig_ids[1] if len(fig_ids) > 1 else "Fig. 2",
    )


def parse_batch_response(
    response: dict,
    legends: dict[str, str],
) -> dict[str, dict[str, dict[str, str]]]:
    """Parse batch LLM response into per-figure classification dicts.

    Validates that every expected figure label is present.  Missing figures
    are returned as empty dicts (consistent with single-call behavior on
    failure).
    """
    if not isinstance(response, dict):
        logger.warning("Batch response is not a dict: %r", type(response))
        return {label: {} for label in legends}

    results: dict[str, dict[str, dict[str, str]]] = {}
    for fig_id in legends:
        fig_data = response.get(fig_id)
        if isinstance(fig_data, dict):
            results[fig_id] = fig_data
        else:
            logger.warning("Missing or invalid batch result for %s", fig_id)
            results[fig_id] = {}

    return results


def classify_all_figures_batch(
    legends: dict[str, str],
    llm_client: Any,
) -> dict[str, dict[str, dict[str, str]]]:
    """Classify all figures in a single LLM call.

    Raises on any failure so the caller (classify_all_figures) can fall back
    to per-figure calls.

    Args:
        legends: {figure_label: legend_text}
        llm_client: VeritasLLMClient instance

    Returns:
        {figure_label: {panel_label: {"description": str, "classification": str}}}
    """
    if not legends:
        return {}

    prompt = build_batch_classification_prompt(legends)

    # Single call with larger token budget
    response = llm_client.chat_json(
        prompt,
        model="qwen-plus",
        max_tokens=8192,
    )

    results = parse_batch_response(response, legends)

    # Validate: if ALL figures came back empty, treat as failure
    if all(not v for v in results.values()):
        raise RuntimeError(
            "Batch classification returned empty results for all figures"
        )

    return results


# ---------------------------------------------------------------------------
# Image → Paper label mapping via LLM
# ---------------------------------------------------------------------------

_IMAGE_LABEL_PROMPT_TEMPLATE = """You are analyzing a scientific paper's markdown text to determine which figure each image belongs to.

The text below is from full.md — a MinerU extraction of a scientific paper. It contains:
- Inline image references: ![](images/HASH.jpg)
- Figure legends: "Fig. N | Title. a, Description..." or "# Fig. N | Title"

Your task: For each image reference, determine which figure label (Fig. 1, Fig. 2, Extended Data Fig. 1, etc.) it belongs to.

Use these clues:
1. Images usually appear near their figure legend (before or after)
2. Panel labels (a, b, c...) may appear between images, matching the legend's panel descriptions
3. Images between two figure legends typically belong to the closer one

Images to classify:
{image_list}

Full text context (abbreviated):
{text_context}

Return ONLY valid JSON — a mapping from image filename to figure label:
{{
  "0b668c7706a9...b6.jpg": "Fig. 2",
  "2392aed99ffb...80.jpg": "Fig. 2",
  ...
}}

Rules:
1. Use ONLY the filename (e.g. "0b668c...b6.jpg"), NOT the full path.
2. Use canonical labels: "Fig. 1", "Fig. 2", "Extended Data Fig. 1", etc.
3. If an image clearly doesn't belong to any numbered figure (e.g. graphical abstract, TOC), use "other".
4. Return ONLY valid JSON, no explanations."""


def build_image_to_paper_label_mapping(
    full_md_text: str,
    llm_client: Any,
) -> dict[str, str]:
    """Use LLM to map image filenames to paper labels from full.md context.

    Parses all image references and figure legends from full.md, then asks
    the LLM to determine which figure each image belongs to based on
    spatial proximity and panel label context.

    Args:
        full_md_text: The full text of full.md
        llm_client: VeritasLLMClient instance

    Returns:
        {image_filename: paper_label}
        e.g. {"0b668c...b6.jpg": "Fig. 2", "acfaff...1f.jpg": "Fig. 3"}
    """
    # Extract all image references from full.md
    image_refs: list[str] = []
    for match in re.finditer(r"!\[.*?\]\(images/([^)]+)\)", full_md_text):
        filename = match.group(1)
        if filename not in image_refs:
            image_refs.append(filename)

    if not image_refs:
        return {}

    # Extract all figure labels from full.md for context
    figure_labels: list[str] = []
    for match in _FIGURE_HEADING_RE.finditer(full_md_text):
        label = _normalize_figure_label(match.group(1))
        if label not in figure_labels:
            figure_labels.append(label)
    for match in _INLINE_LEGEND_RE.finditer(full_md_text):
        label = _normalize_figure_label(match.group(1))
        if label not in figure_labels:
            figure_labels.append(label)

    if not figure_labels:
        return {}

    # Build the prompt
    image_list = "\n".join(f"- {fn}" for fn in image_refs[:100])  # cap at 100
    # Abbreviate text context: keep figure legends and nearby image refs
    text_context = _abbreviate_md_for_mapping(full_md_text, max_chars=8000)

    prompt = _IMAGE_LABEL_PROMPT_TEMPLATE.format(
        image_list=image_list,
        text_context=text_context,
    )

    try:
        result = llm_client.chat_json(prompt)
        if not isinstance(result, dict):
            logger.warning(
                "LLM image→label mapping returned non-dict: %r", type(result)
            )
            return {}

        # Validate: only keep mappings with known figure labels
        valid_labels = set(figure_labels) | {"other"}
        validated: dict[str, str] = {}
        for filename, label in result.items():
            canonical_label = _normalize_mapping_label(label, valid_labels)
            if canonical_label:
                validated[str(filename)] = canonical_label

        return validated

    except Exception as e:
        logger.warning("LLM image→label mapping failed: %s", e)
        return {}


def _normalize_mapping_label(label: Any, valid_labels: set[str]) -> str | None:
    if not isinstance(label, str):
        return None
    if label.strip().lower() == "other":
        return "other" if "other" in valid_labels else None

    canonical = _normalize_figure_label(label)
    if canonical in valid_labels:
        return canonical
    return None


def _abbreviate_md_for_mapping(text: str, max_chars: int = 8000) -> str:
    """Abbreviate full.md text to keep only figure-relevant content.

    Keeps: figure headings, inline legends, image references, panel labels.
    Removes: long body paragraphs that don't contain figure references.
    """
    lines = text.split("\n")
    kept: list[str] = []
    total = 0

    for line in lines:
        stripped = line.strip()
        # Keep figure headings, image refs, short lines (panel labels),
        # and lines mentioning "Fig."
        is_relevant = (
            not stripped
            or re.match(r"^#+", stripped)
            or re.match(r"^!\[", stripped)
            or re.match(r"^[a-z]\s*$", stripped, re.IGNORECASE)
            or "Fig." in stripped
            or "Extended Data Fig" in stripped
        )
        if is_relevant:
            kept.append(line)
            total += len(line)
            if total >= max_chars:
                break

    return "\n".join(kept)


def _image_ref_to_filename(image_ref: Any) -> str:
    """Extract image filename from evidence-ledger image_ref shapes."""
    if isinstance(image_ref, dict):
        image_path = str(
            image_ref.get("relative_path")
            or image_ref.get("path")
            or image_ref.get("raw")
            or ""
        )
    elif image_ref is None:
        image_path = ""
    else:
        image_path = str(image_ref)

    image_path = image_path.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return image_path.rsplit("/", 1)[-1] if image_path else ""


def _figure_item_image_filename(item: dict[str, Any]) -> str:
    filename = _image_ref_to_filename(item.get("image_ref"))
    if not filename:
        filename = _image_ref_to_filename(item.get("source_image_path"))
    return filename


def _map_figure_ids_from_image_labels(
    ledger: dict[str, Any],
    image_to_label: dict[str, str],
) -> dict[str, str]:
    raw_figures = ledger.get("figures")
    if not isinstance(raw_figures, list):
        raw_figures = ledger.get("items", [])
    if not isinstance(raw_figures, list):
        return {}

    mapping: dict[str, str] = {}
    for item in raw_figures:
        if not isinstance(item, dict) or item.get("type") != "figure":
            continue
        fid = str(item.get("id") or item.get("figure_id") or "")
        if not fid:
            continue
        filename = _figure_item_image_filename(item)
        label = image_to_label.get(filename)
        if label and label != "other":
            mapping[fid] = label
    return mapping


def build_figure_id_to_paper_label_mapping(
    workdir: Path,
    llm_client: Any | None = None,
) -> dict[str, str]:
    """Build a mapping from figure IDs to paper labels.

    Uses LLM to map image filenames → paper labels from full.md context,
    then maps figure IDs → image paths (from evidence_ledger) → paper labels.

    Args:
        workdir: Audit working directory
        llm_client: VeritasLLMClient instance (if None, tries to create one)

    Returns:
        {figure_id: paper_label}
        e.g. {"figure-md-0001": "Fig. 2", "figure-md-0002": "Fig. 3"}
    """
    full_md = existing_artifact_path(workdir, "full.md")
    if full_md is None:
        return {}

    full_md_text = full_md.read_text(encoding="utf-8")

    # Initialize LLM client if needed
    if llm_client is None:
        try:
            from engine.llm.client import VeritasLLMClient

            llm_client = VeritasLLMClient()
        except Exception as e:
            logger.warning("Failed to initialize LLM client for fig mapping: %s", e)
            return {}

    # Step 1: LLM maps image filenames → paper labels
    image_to_label = build_image_to_paper_label_mapping(full_md_text, llm_client)
    if not image_to_label:
        return {}

    # Step 2: Map figure_id → image_path → image_filename → paper_label
    mapping: dict[str, str] = {}
    evidence_ledger_path = existing_artifact_path(workdir, "evidence_ledger.json")
    if evidence_ledger_path and evidence_ledger_path.exists():
        try:
            ledger = json.loads(evidence_ledger_path.read_text(encoding="utf-8"))
            mapping = _map_figure_ids_from_image_labels(ledger, image_to_label)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read evidence_ledger for fig mapping: %s", e)

    return mapping


# ---------------------------------------------------------------------------
# Panel classification (combines YOLO + LLM)
# ---------------------------------------------------------------------------

# YOLO panel types that are definitely wet-lab
_YOLO_WET_LAB_TYPES = {"Microscopy", "Blots", "Body Imaging", "Flow Cytometry"}
# YOLO panel types that are definitely bioinformatics
_YOLO_BIOINFO_TYPES = {"Graph", "Graphs"}


def classify_panel_with_llm_priority(
    panel: dict[str, Any],
    cls_dict: dict[str, dict[str, dict[str, str]]],
    fig_mapping: dict[str, str],
) -> str:
    """Classify a single panel using figure-aware LLM lookup with YOLO fallback.

    Priority:
        1. Use fig_mapping to get paper label from panel's parent figure ID
        2. Look up panel label in cls_dict[paper_label] for LLM classification
        3. If LLM fails, fall back to YOLO panel_type
        4. If both fail, return 'unknown'

    Args:
        panel: Panel dict with 'panel_type', 'label', 'parent_figure_id'
        cls_dict: {paper_label: {panel_label: {"classification": str}}}
                  e.g. {"Fig. 1": {"a": {"classification": "wet_lab"}}}
        fig_mapping: {figure_id: paper_label}
                     e.g. {"figure-md-0001": "Fig. 1"}

    Returns:
        Classification string: 'wet_lab', 'bioinformatics', 'mixed', 'other', 'unknown'
    """
    # Priority 1: Figure-aware LLM lookup
    parent_fid = panel.get("parent_figure_id") or ""
    paper_label = fig_mapping.get(parent_fid)

    if paper_label and paper_label in cls_dict:
        panel_label = panel.get("label") or ""
        if panel_label:
            panels_for_fig = cls_dict[paper_label]
            if isinstance(panels_for_fig, dict):
                panel_info = panels_for_fig.get(panel_label) or panels_for_fig.get(
                    "figure"
                )
                if isinstance(panel_info, dict):
                    classification = panel_info.get("classification")
                    if classification in {
                        "wet_lab",
                        "bioinformatics",
                        "mixed",
                        "other",
                    }:
                        return classification

    # Priority 2: YOLO fallback
    yolo_type = panel.get("panel_type") or ""
    if yolo_type in _YOLO_WET_LAB_TYPES:
        return "wet_lab"
    if yolo_type in _YOLO_BIOINFO_TYPES:
        return "bioinformatics"

    # Priority 3: Unknown (conservative)
    return "unknown"


def classify_panel_with_yolo_priority(
    panel: dict[str, Any],
    llm_classifications: dict[str, dict[str, str]],
) -> str:
    """Classify a single panel using YOLO panel_type with LLM fallback.

    Priority:
        1. YOLO panel_type is recognized -> map directly
        2. YOLO unknown/missing -> use LLM classification for this panel label
        3. Both fail -> return 'unknown'

    Args:
        panel: Panel dict with 'panel_type', 'label', 'parent_figure_id'
        llm_classifications: {figure_label: {panel_label: {"classification": str}}}

    Returns:
        Classification string: 'wet_lab', 'bioinformatics', 'mixed', 'other', 'unknown'
    """
    # Priority 1: YOLO already classified
    yolo_type = panel.get("panel_type") or ""
    if yolo_type in _YOLO_WET_LAB_TYPES:
        return "wet_lab"
    if yolo_type in _YOLO_BIOINFO_TYPES:
        return "bioinformatics"

    # Priority 2: LLM fallback
    # Need to map parent_figure_id -> figure_label, but panel_evidence doesn't
    # have figure_label directly. We'll use the figure_id to look up in
    # classifications by matching the panel's figure context.
    # For now, we look up by panel label across all figures.
    panel_label = panel.get("label") or ""
    if panel_label:
        for fig_label, panels in llm_classifications.items():
            if isinstance(panels, dict) and panel_label in panels:
                panel_info = panels[panel_label]
                if isinstance(panel_info, dict):
                    classification = panel_info.get("classification")
                    if classification in {
                        "wet_lab",
                        "bioinformatics",
                        "mixed",
                        "other",
                    }:
                        return classification

    # Priority 3: Unknown (conservative)
    return "unknown"


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


def run_figure_classification_step(
    *,
    workdir: Path,
    force: bool = False,
    llm_client: Any = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Run figure classification pipeline step.

    Args:
        workdir: Audit working directory
        force: Re-run even if artifact exists
        llm_client: VeritasLLMClient instance (if None, will try to create one)
        progress: Progress callback

    Returns:
        (steps, manifest) where manifest contains classification results
    """
    steps: list[StepResult] = []
    output_path = resolve_artifact_path(workdir, "figure_classification.json")

    # Check if artifact already exists
    if output_path.exists() and not force:
        record_step(
            steps,
            StepResult(
                "figure_classification",
                "LLM 图注分类",
                "reused",
                "Existing figure_classification.json found.",
            ),
            progress,
        )
        classification_data = json.loads(output_path.read_text(encoding="utf-8"))
        return steps, {"figure_classification": classification_data}

    # Check for full.md
    full_md = existing_artifact_path(workdir, "full.md")
    if full_md is None:
        record_step(
            steps,
            StepResult(
                "figure_classification",
                "LLM 图注分类",
                "skipped",
                "full.md missing (MinerU output required).",
            ),
            progress,
        )
        return steps, {
            "figure_classification": {
                "status": "skipped",
                "detail": "full.md missing",
            }
        }

    emit_step_start(
        progress,
        "figure_classification",
        "LLM 图注分类",
        "Classifying figure panels from legends using LLM.",
    )

    # Initialize LLM client if not provided
    if llm_client is None:
        try:
            from engine.llm.client import VeritasLLMClient

            llm_client = VeritasLLMClient()
        except Exception as e:  # Deliberately broad: LLM client initialization may fail due to missing config, env vars, etc.
            logger.warning("Failed to initialize LLM client: %s", e)
            record_step(
                steps,
                StepResult(
                    "figure_classification",
                    "LLM 图注分类",
                    "failed",
                    f"LLM client initialization failed: {e}",
                ),
                progress,
            )
            return steps, {
                "figure_classification": {
                    "status": "failed",
                    "detail": f"LLM client init failed: {e}",
                }
            }

    # Parse legends from full.md
    full_md_text = full_md.read_text(encoding="utf-8")
    legends = parse_figure_legends(full_md_text)

    if not legends:
        record_step(
            steps,
            StepResult(
                "figure_classification",
                "LLM 图注分类",
                "skipped",
                "No figure legends found in full.md.",
            ),
            progress,
        )
        return steps, {
            "figure_classification": {
                "status": "skipped",
                "detail": "no figure legends found",
            }
        }

    # Classify all figures
    classifications = classify_all_figures(legends, llm_client)

    # Count classifications by type
    type_counts: dict[str, int] = {}
    for fig_label, panels in classifications.items():
        for panel_label, panel_info in panels.items():
            if isinstance(panel_info, dict):
                cls = panel_info.get("classification", "unknown")
                type_counts[cls] = type_counts.get(cls, 0) + 1

    # Build figure_id → paper_label mapping using LLM
    # This mapping is persisted in the artifact so visual_pipeline can use it
    # without needing to call LLM again.
    figure_id_to_paper_label: dict[str, str] = {}
    try:
        figure_id_to_paper_label = build_figure_id_to_paper_label_mapping(
            workdir,
            llm_client,
        )
    except Exception as e:
        logger.warning("Failed to build figure_id→paper_label mapping: %s", e)

    # Build output artifact
    artifact = {
        "schema_version": "1.0",
        "status": "ran",
        "figure_count": len(legends),
        "classified_panel_count": sum(type_counts.values()),
        "type_counts": type_counts,
        "legends_extracted": list(legends.keys()),
        "classifications": classifications,
        "figure_id_to_paper_label": figure_id_to_paper_label,
        "errors": [],
    }

    write_json_artifact(output_path, artifact)

    detail = (
        f"figures={len(legends)} panels={sum(type_counts.values())} types={type_counts}"
    )
    record_step(
        steps,
        StepResult("figure_classification", "LLM 图注分类", "ran", detail),
        progress,
    )

    return steps, {"figure_classification": artifact}
