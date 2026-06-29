"""MinerU stage — PDF parsing, evidence ledger, numeric forensics, PaperFraud rules.

Corresponds to lines 406-410 of the original pipeline.py ``_run_static_audit_from_args``.
Early-termination logic is handled by the caller (the orchestrator in pipeline.py).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

from engine.static_audit._pipeline_steps import _run_mineru_forensics_section
from engine.static_audit._shared import (
    ProgressCallback,
    StepResult,
)


@dataclass(frozen=True, slots=True)
class MinerUResult:
    """Outputs of the MinerU stage."""

    mineru_ok: bool
    steps: list[StepResult] = field(default_factory=list)


def run(
    args: argparse.Namespace,
    *,
    workdir: Path,
    paper_pdf: Path,
    env: dict[str, str],
    progress: ProgressCallback | None,
) -> MinerUResult:
    """Run MinerU + forensics.  Returns whether full.md was produced."""
    mineru_steps, mineru_ok = _run_mineru_forensics_section(
        args=args,
        workdir=workdir,
        paper_pdf=paper_pdf,
        env=env,
        progress=progress,
    )
    return MinerUResult(mineru_ok=mineru_ok, steps=mineru_steps)
