"""Source-data stage — profile, findings, pair forensics, cross-sheet, verdict.

Corresponds to lines 463-489 of the original pipeline.py ``_run_static_audit_from_args``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.static_audit._pipeline_steps import _run_source_data_steps
from engine.static_audit._shared import (
    ProgressCallback,
    StepResult,
    record_step,
)


@dataclass(frozen=True, slots=True)
class SourceDataResult:
    """Outputs of the source-data stage."""

    steps: list[StepResult] = field(default_factory=list)


def run(
    args: argparse.Namespace,
    *,
    workdir: Path,
    source_lane: dict[str, Any] | None,
    source_data_dir: Path | None,
    sfp: dict[str, Any],
    env: dict[str, str],
    progress: ProgressCallback | None,
) -> SourceDataResult:
    """Run source-data pipeline or record skip steps if unavailable."""
    steps: list[StepResult] = []

    if source_lane and source_data_dir and source_data_dir.is_dir():
        steps.extend(
            _run_source_data_steps(
                workdir=workdir,
                source_data_dir=source_data_dir,
                source_finding_params=sfp,
                env=env,
                args=args,
                progress=progress,
            )
        )
    else:
        reason = (
            f"Selected Source Data root is invalid or outside paper_dir: {source_lane.get('root')}"
            if source_lane and source_lane.get("root")
            else (source_lane or {}).get("reason")
            or "No executable XLSX/XLSM Source Data optional lane was selected."
        )
        for k, t in [
            ("source_data_profile", "Source Data profile"),
            ("source_data_findings", "Source Data findings"),
            ("source_data_pair_forensics", "Source Data pair forensics"),
            ("source_data_cross_sheet", "Source Data cross-sheet duplicates"),
            ("source_data_verdict", "Source Data LLM 语义裁决"),
        ]:
            record_step(steps, StepResult(k, t, "skipped", reason), progress)

    return SourceDataResult(steps=steps)
