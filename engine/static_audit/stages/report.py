"""Report stage — bundle, markdown report, HTML report, manifest.

Corresponds to lines 615-631 of the original pipeline.py ``_run_static_audit_from_args``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from engine.static_audit._pipeline_steps import _run_bundle_and_report
from engine.static_audit._shared import (
    ProgressCallback,
    StepResult,
    resolve_artifact_path,
)


def run(
    args: argparse.Namespace,
    *,
    workdir: Path,
    paper_dir: Path,
    paper_pdf: Path,
    source_data_dir: Path | None,
    case_id: str,
    steps: list[StepResult],
    agent_manifest: dict[str, Any],
    mi_path: Path,
    optional_lanes: list[dict[str, Any]],
    progress: ProgressCallback | None,
) -> dict[str, Any]:
    """Build bundle + reports.  Returns the summary dict (pipeline result)."""
    return _run_bundle_and_report(
        paper_dir=paper_dir,
        paper_pdf=paper_pdf,
        source_data_dir=source_data_dir,
        workdir=workdir,
        case_id=case_id,
        agent_mode=args.agent_mode,
        steps=steps,
        agent_manifest=agent_manifest,
        material_inventory_path=mi_path,
        agent_material_plan_path=resolve_artifact_path(
            workdir, "agent_material_plan.json"
        ),
        optional_lanes=optional_lanes,
        progress=progress,
        reproducibility_tier=getattr(args, "reproducibility_tier", "full"),
    )
