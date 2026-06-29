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


def run_sila_dense_detection(
    *,
    workdir: Path,
    force: bool,
    allow_env_skip: bool = False,
    panel_extraction_status: str | None = None,
    progress: ProgressCallback | None = None,
    figure_classification: dict[str, Any] | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Run SILA dense copy-move detection via Docker.

    If figure_classification is provided, only wet_lab|mixed panels will be
    processed, reducing computation on code-generated visualizations.
    """
    steps: list[StepResult] = []
    output_path = resolve_artifact_path(workdir, "visual_copy_move_dense.json")
    if output_path.exists() and not force:
        record_step(
            steps,
            StepResult(
                "visual_copy_move_dense",
                "SILA Dense Copy-Move",
                "reused",
                "Existing visual_copy_move_dense.json found.",
            ),
            progress,
        )
        return steps, {"sila_dense": {"status": "reused", "output": str(output_path)}}

    emit_step_start(
        progress,
        "visual_copy_move_dense",
        "SILA Dense Copy-Move",
        "Running SILA dense copy-move detection via Docker.",
    )

    panel_evidence_path = resolve_artifact_path(workdir, "panel_evidence.json")
    if not panel_evidence_path.exists():
        if panel_extraction_status in ("skipped", "ran"):
            record_step(
                steps,
                StepResult(
                    "visual_copy_move_dense",
                    "SILA Dense Copy-Move",
                    "skipped",
                    "No panel evidence from upstream.",
                ),
                progress,
            )
            return steps, {
                "sila_dense": {"status": "skipped", "detail": "no panel evidence"}
            }
        record_step(
            steps,
            StepResult(
                "visual_copy_move_dense",
                "SILA Dense Copy-Move",
                "failed",
                "panel_evidence.json not found (upstream dependency).",
            ),
            progress,
        )
        return steps, {
            "sila_dense": {
                "status": "failed",
                "failure_category": "dependency",
                "detail": "missing panel_evidence.json",
            }
        }

    panel_evidence = read_json(panel_evidence_path) or {}
    panels = panel_evidence.get("panels", [])

    # Filter panels to only wet_lab panels (if classification available)
    if figure_classification and panels:
        from engine.static_audit._shared import WET_LAB_TYPES

        original_count = len(panels)
        panels = [
            p
            for p in panels
            if isinstance(p, dict)
            and (
                p.get("panel_classification") in WET_LAB_TYPES
                or p.get("panel_classification") == "unknown"
            )
        ]
        filtered_count = original_count - len(panels)
        if filtered_count > 0:
            logger.info(
                "SILA dense: filtered %d panels (keeping %d wet_lab panels)",
                filtered_count,
                len(panels),
            )

    visual_evidence_path = resolve_artifact_path(workdir, "visual_evidence.json")
    visual_evidence = (
        read_json(visual_evidence_path) or {} if visual_evidence_path.exists() else {}
    )
    figures = visual_evidence.get("figures", [])

    if not panels:
        # Legitimate scenario: no panels extracted (paper has no figures or extraction found none).
        record_step(
            steps,
            StepResult(
                "visual_copy_move_dense",
                "SILA Dense Copy-Move",
                "skipped",
                "No panels to process.",
            ),
            progress,
        )
        return steps, {"sila_dense": {"status": "skipped", "detail": "no panels"}}

    try:
        from engine.static_audit.tools.sila_dense import detect_sila_dense

        result = detect_sila_dense(panels, figures, workdir=workdir)
    except Exception as e:  # Deliberately broad: tool wrapper safety net; detect_sila_dense handles its own errors
        result = {
            "status": "failed",
            "failure_category": "runtime",
            "relationships": [],
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
            StepResult(
                "visual_copy_move_dense", "SILA Dense Copy-Move", "failed", detail
            ),
            progress,
        )
        return steps, {
            "sila_dense": {
                "status": "failed",
                "failure_category": failure_category,
                "output": str(output_path),
                **result,
            }
        }

    detail = f"panels={result.get('panel_count', 0)} relationships={result.get('relationship_count', 0)}"
    if result.get("limitations"):
        detail += f" limitations={len(result['limitations'])}"
    step_status = "ran" if status == "ran" else "failed"
    if status == "failed" and failure_category == "environment" and allow_env_skip:
        detail = f"SKIPPED (environment): {'; '.join(result.get('errors', []))}"
        step_status = "skipped_with_opt_in"
    record_step(
        steps,
        StepResult(
            "visual_copy_move_dense", "SILA Dense Copy-Move", step_status, detail
        ),
        progress,
    )
    return steps, {
        "sila_dense": {"status": status, "output": str(output_path), **result}
    }
