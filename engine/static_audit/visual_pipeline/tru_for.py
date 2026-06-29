from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


def run_tru_for_detection(
    *,
    workdir: Path,
    force: bool,
    allow_env_skip: bool = False,
    panel_extraction_status: str | None = None,
    progress: ProgressCallback | None = None,
    figure_classification: dict[str, Any] | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Run TruFor forgery detection on all figures.

    If figure_classification is provided, only figures with wet_lab|mixed panels
    will be processed, reducing computation on code-generated visualizations.
    """
    steps: list[StepResult] = []
    output_path = resolve_artifact_path(workdir, "forged_region_evidence.json")
    if output_path.exists() and not force:
        record_step(
            steps,
            StepResult(
                "visual_tru_for",
                "TruFor 深度学习伪造检测",
                "reused",
                "Existing forged_region_evidence.json found.",
            ),
            progress,
        )
        return steps, {"tru_for": {"status": "reused", "output": str(output_path)}}

    emit_step_start(
        progress,
        "visual_tru_for",
        "TruFor 深度学习伪造检测",
        "Running TruFor forgery detection on all figures.",
    )

    visual_evidence_path = resolve_artifact_path(workdir, "visual_evidence.json")
    if not visual_evidence_path.exists():
        # If panel_extraction was skipped or ran with no figures, this is a legitimate skip.
        if panel_extraction_status in ("skipped", "ran"):
            record_step(
                steps,
                StepResult(
                    "visual_tru_for",
                    "TruFor 深度学习伪造检测",
                    "skipped",
                    "No visual evidence from upstream.",
                ),
                progress,
            )
            return steps, {
                "tru_for": {"status": "skipped", "detail": "no visual evidence"}
            }
        # Otherwise, it's a dependency failure.
        record_step(
            steps,
            StepResult(
                "visual_tru_for",
                "TruFor 深度学习伪造检测",
                "failed",
                "visual_evidence.json not found (upstream dependency).",
            ),
            progress,
        )
        return steps, {
            "tru_for": {
                "status": "failed",
                "failure_category": "dependency",
                "detail": "missing visual_evidence.json",
            }
        }

    visual_evidence = read_json(visual_evidence_path) or {}
    figures = visual_evidence.get("figures", [])

    # Filter figures to only those with wet_lab panels (if classification available)
    if figure_classification and figures:
        from engine.static_audit._shared import WET_LAB_TYPES

        # Load panel evidence to check panel classifications
        panel_evidence_path = resolve_artifact_path(workdir, "panel_evidence.json")
        panel_evidence = read_json(panel_evidence_path) or {}
        panels = panel_evidence.get("panels", [])

        # Find figure_ids that have wet_lab panels
        wet_lab_figure_ids: set[str] = set()
        for panel in panels:
            if not isinstance(panel, dict):
                continue
            panel_cls = panel.get("panel_classification", "unknown")
            if panel_cls in WET_LAB_TYPES or panel_cls == "unknown":
                parent_id = panel.get("parent_figure_id")
                if parent_id:
                    wet_lab_figure_ids.add(parent_id)

        # Filter figures
        original_count = len(figures)
        figures = [f for f in figures if f.get("figure_id") in wet_lab_figure_ids]
        filtered_count = original_count - len(figures)
        if filtered_count > 0:
            logger.info(
                "TruFor: filtered %d figures (keeping %d with wet_lab panels)",
                filtered_count,
                len(figures),
            )

    if not figures:
        # Legitimate scenario: paper has no figures. Skip without failure.
        record_step(
            steps,
            StepResult(
                "visual_tru_for",
                "TruFor 深度学习伪造检测",
                "skipped",
                "Paper has no figures.",
            ),
            progress,
        )
        return steps, {
            "tru_for": {"status": "skipped", "detail": "no figures in paper"}
        }

    try:
        from engine.static_audit.tools.tru_for import run_tru_for

        result = run_tru_for(figures, workdir=workdir)
    except Exception as e:  # Deliberately broad: tool wrapper safety net; run_tru_for catches ToolExecutionError internally
        result = {
            "status": "failed",
            "failure_category": "runtime",
            "forged_region_evidence": [],
            "errors": [str(e)],
            "limitations": [],
        }

    write_json_artifact(output_path, result)
    status = result.get("status", "failed")
    failure_category = result.get("failure_category")

    # Environment failures are only skippable with explicit opt-in
    if status == "failed" and failure_category == "environment" and not allow_env_skip:
        detail = f"FAILED (environment): {'; '.join(result.get('errors', []))}"
        record_step(
            steps,
            StepResult("visual_tru_for", "TruFor 深度学习伪造检测", "failed", detail),
            progress,
        )
        return steps, {
            "tru_for": {
                "status": "failed",
                "failure_category": failure_category,
                "output": str(output_path),
                **result,
            }
        }

    detail = f"figures={result.get('figure_count', 0)} forged_regions={result.get('forged_region_count', 0)} suspicious={result.get('suspicious_count', 0)}"
    if result.get("limitations"):
        detail += f" limitations={len(result['limitations'])}"
    step_status = "ran" if status == "ran" else "failed"
    if status == "failed" and failure_category == "environment" and allow_env_skip:
        detail = f"SKIPPED (environment): {'; '.join(result.get('errors', []))}"
        step_status = "skipped_with_opt_in"
    record_step(
        steps,
        StepResult("visual_tru_for", "TruFor 深度学习伪造检测", step_status, detail),
        progress,
    )
    return steps, {"tru_for": {"status": status, "output": str(output_path), **result}}
