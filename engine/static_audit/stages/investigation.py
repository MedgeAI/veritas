"""Investigation stage — investigation rounds, fallbacks, agent review.

Corresponds to lines 554-595 of the original pipeline.py ``_run_static_audit_from_args``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.static_audit._pipeline_steps import (
    _run_agent_review_section,
    _run_investigation_fallbacks,
)
from engine.static_audit._shared import (
    PROJECT_ROOT,
    ProgressCallback,
    StepResult,
)


@dataclass(frozen=True, slots=True)
class InvestigationResult:
    """Outputs of the investigation stage."""

    inv_manifest: dict[str, Any]
    steps: list[StepResult] = field(default_factory=list)


def run(
    args: argparse.Namespace,
    *,
    workdir: Path,
    case_id: str,
    source_data_dir: Path | None,
    images_dir: Path,
    env: dict[str, str],
    agent_manifest: dict[str, Any],
    fc_manifest_data: dict[str, Any] | None,
    progress: ProgressCallback | None,
) -> InvestigationResult:
    """Run investigation rounds, fallbacks, and agent review."""
    from engine.static_audit.investigation_dispatch import run_investigation_rounds

    steps: list[StepResult] = []

    # Investigation rounds
    inv_steps, inv_manifest = run_investigation_rounds(
        case_id=case_id,
        workdir=workdir,
        source_data_dir=source_data_dir,
        agent_enabled=args.agent_mode in {"review", "full"},
        agent_mode=args.agent_mode,
        force=args.force,
        project_root=PROJECT_ROOT,
        env=env,
        model=args.agent_model,
        opencode_bin=args.opencode_bin,
        timeout_seconds=args.agent_timeout_seconds,
        max_retries=args.agent_max_retries,
        progress=progress,
    )
    steps.extend(inv_steps)
    agent_manifest["investigation"] = inv_manifest

    # Investigation fallbacks
    steps.extend(
        _run_investigation_fallbacks(
            workdir=workdir,
            images_dir=images_dir,
            investigation_manifest=inv_manifest,
            env=env,
            args=args,
            progress=progress,
            figure_classification=fc_manifest_data,
        )
    )

    # Agent review
    steps.extend(
        _run_agent_review_section(
            args=args,
            workdir=workdir,
            env=env,
            agent_manifest=agent_manifest,
            progress=progress,
        )
    )

    return InvestigationResult(inv_manifest=inv_manifest, steps=steps)
