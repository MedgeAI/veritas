from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any

from engine.static_audit._shared import (
    ProgressCallback,
    StepResult,
    emit_step_start,
    read_json,
    record_step,
    resolve_artifact_path,
    write_json_artifact,
)
from engine.static_audit.tools.panel_extraction import (
    _classify_fallback_panels,
    build_figure_evidence_from_images,
    build_figure_evidence_from_ledger,
    extract_panels_batch,
    whole_figure_panel,
)

logger = logging.getLogger(__name__)


def _resolve_workdir_path(workdir: Path, relative_path: str) -> Path | None:
    if not relative_path:
        return None
    candidate = Path(relative_path)
    if not candidate.is_absolute():
        candidate = workdir / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    try:
        if not resolved.is_relative_to(workdir.resolve()):
            return None
    except OSError:
        return None
    return resolved if resolved.exists() else None


def _visual_status(values: list[str]) -> str:
    if any(value == "ran" for value in values):
        return "ran"
    if any(value == "not_available" for value in values):
        return "not_available"
    if any(value == "failed" for value in values):
        return "failed"
    return "skipped"


def run_visual_panel_extraction(
    *,
    workdir: Path,
    images_dir: Path,
    force: bool,
    progress: ProgressCallback | None = None,
    figure_classification: dict[str, Any] | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Create canonical figure and panel evidence from extracted PDF images.

    Args:
        figure_classification: Optional figure classification data from
            figure_classification.json. If provided, each panel will be
            annotated with 'panel_classification' field.
    """
    steps: list[StepResult] = []
    figure_output = resolve_artifact_path(workdir, "visual_evidence.json")
    panel_output = resolve_artifact_path(workdir, "panel_evidence.json")
    if figure_output.exists() and panel_output.exists() and not force:
        step = StepResult(
            "visual_panel_extraction",
            "图片 Panel 拆分",
            "reused",
            "Existing visual_evidence.json and panel_evidence.json found.",
        )
        record_step(steps, step, progress)
        return steps, {
            "panel_extraction": {
                "status": "reused",
                "figures_output": str(figure_output),
                "panels_output": str(panel_output),
            }
        }

    if not images_dir.is_dir():
        step = StepResult(
            "visual_panel_extraction",
            "图片 Panel 拆分",
            "skipped",
            "images directory missing.",
        )
        record_step(steps, step, progress)
        return steps, {"panel_extraction": {"status": "skipped", "detail": step.detail}}

    emit_step_start(
        progress,
        "visual_panel_extraction",
        "图片 Panel 拆分",
        "Building canonical figure_evidence and panel_evidence artifacts.",
    )

    start_time = time.monotonic()
    evidence_ledger = (
        read_json(resolve_artifact_path(workdir, "evidence_ledger.json")) or {}
    )
    figures = build_figure_evidence_from_ledger(workdir, evidence_ledger)
    if not figures:
        figures = build_figure_evidence_from_images(workdir, images_dir)

    errors: list[str] = []
    limitations: list[str] = []
    panels: list[dict[str, Any]] = []
    extraction_statuses: list[str] = []

    if not figures:
        limitations.append(
            "No extracted figure images were available for panel extraction."
        )

    # Collect (figure_id, absolute_image_path) pairs for figures that exist on disk
    figure_path_pairs: list[tuple[str, Path]] = []
    figure_by_id: dict[str, dict[str, Any]] = {}
    for figure in figures:
        fid = str(figure.get("figure_id") or "")
        figure_by_id[fid] = figure
        source_path = _resolve_workdir_path(
            workdir, str(figure.get("source_image_path") or "")
        )
        if source_path is None:
            errors.append(f"Figure image not found: {figure.get('source_image_path')}")
            extraction_statuses.append("failed")
            continue
        figure_path_pairs.append((fid, source_path))

    # Batch YOLOv5 panel extraction — single subprocess call for all figures
    if figure_path_pairs:
        # Clean stale panel crops from previous runs to prevent orphans
        panels_dir = workdir / "panels"
        if panels_dir.is_dir():
            shutil.rmtree(str(panels_dir), ignore_errors=True)
        batch_panels = extract_panels_batch(figure_path_pairs, output_dir=workdir)
        extraction_statuses.append("ran" if any(batch_panels.values()) else "skipped")
    else:
        batch_panels = {}

    # Pre-compute figure_id → paper_label mapping ONCE (expensive LLM call)
    # Input (full.md + evidence_ledger.json) is fixed for this workdir,
    # so caching avoids 18 redundant LLM calls (~30 min wasted).
    fig_mapping_cache: dict[str, str] | None = None
    if figure_classification:
        from engine.static_audit.figure_classification import (
            build_figure_id_to_paper_label_mapping,
            classify_panel_with_llm_priority,
        )
        cls_dict = figure_classification.get("classifications", {})
        fig_mapping_cache = figure_classification.get("figure_id_to_paper_label")

    # Distribute panels to figures; fallback for figures with zero panels
    fallback_count = 0
    for fid, source_path in figure_path_pairs:
        figure = figure_by_id.get(fid)
        if figure is None:
            continue
        result_panels = batch_panels.get(fid, [])
        if not result_panels:
            logger.debug(
                "Figure %s: 0 panels detected; applying whole-figure fallback", fid
            )
            fallback_panel = whole_figure_panel(
                figure, workdir=workdir, output_dir=workdir
            )
            if fallback_panel:
                result_panels = [fallback_panel]
                fallback_count += 1
                # Post-hoc heuristic typing: infer panel_type from image
                # shape/color so downstream forensics routing can make
                # informed decisions even when YOLOv5 detected nothing.
                _classify_fallback_panels(result_panels, workdir=workdir)
                limitations.append(
                    f"{fid}: YOLOv5 panel extraction did not detect panels; whole-figure fallback panel was created."
                )

        # Annotate panels with LLM classification (if available)
        if figure_classification and cls_dict:
            # Lazily compute mapping on first use (cached for all figures)
            if fig_mapping_cache is None:
                fig_mapping_cache = build_figure_id_to_paper_label_mapping(workdir)

            for panel in result_panels:
                panel["panel_classification"] = classify_panel_with_llm_priority(
                    panel, cls_dict, fig_mapping_cache
                )

        panels.extend(result_panels)
        figure["panel_count"] = len(result_panels)
        metadata = (
            figure.get("metadata") if isinstance(figure.get("metadata"), dict) else {}
        )
        figure["metadata"] = {
            **metadata,
            "panel_extraction_status": "ran" if result_panels else "skipped",
        }

    status = "ran" if figures else "skipped"
    if figures and not panels:
        status = _visual_status(extraction_statuses)
        if status == "ran":
            status = "warning"

    elapsed_s = time.monotonic() - start_time
    logger.info(
        "Panel extraction summary: figures=%d panels=%d fallbacks=%d failures=%d elapsed=%.1fs",
        len(figures),
        len(panels),
        fallback_count,
        len(errors),
        elapsed_s,
    )

    visual_evidence = {
        "schema_version": "1.0",
        "created_by": "engine/static_audit/orchestrator.py",
        "status": status,
        "figure_count": len(figures),
        "panel_count": len(panels),
        "figures": figures,
        "errors": errors,
        "limitations": limitations,
    }
    panel_evidence = {
        "schema_version": "1.0",
        "created_by": "engine/static_audit/orchestrator.py",
        "status": status,
        "figure_count": len(figures),
        "panel_count": len(panels),
        "panels": panels,
        "errors": errors,
        "limitations": limitations,
    }
    write_json_artifact(figure_output, visual_evidence)
    write_json_artifact(panel_output, panel_evidence)

    detail = f"figures={len(figures)} panels={len(panels)}"
    if limitations:
        detail += f" limitations={len(limitations)}"
    step_status = (
        "ran"
        if status in {"ran", "warning"}
        else "warning"
        if status in {"not_available", "failed"}
        else status
    )
    step = StepResult("visual_panel_extraction", "图片 Panel 拆分", step_status, detail)
    record_step(steps, step, progress)
    return steps, {
        "panel_extraction": {
            "status": status,
            "figures_output": str(figure_output),
            "panels_output": str(panel_output),
            "figure_count": len(figures),
            "panel_count": len(panels),
            "errors": errors,
            "limitations": limitations,
        }
    }
