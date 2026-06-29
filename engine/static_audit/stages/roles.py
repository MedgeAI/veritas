"""Roles stage — agent role assignment (Claim / SourceData / Judge).

Corresponds to lines 597-613 of the original pipeline.py ``_run_static_audit_from_args``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.static_audit._shared import (
    PROJECT_ROOT,
    ProgressCallback,
    StepResult,
)


@dataclass(frozen=True, slots=True)
class RolesResult:
    """Outputs of the roles stage."""

    role_manifest: dict[str, Any]
    steps: list[StepResult] = field(default_factory=list)


def run(
    args: argparse.Namespace,
    *,
    workdir: Path,
    case_id: str,
    env: dict[str, str],
    agent_manifest: dict[str, Any],
    progress: ProgressCallback | None,
) -> RolesResult:
    """Run agent roles and update *agent_manifest* in place."""
    from engine.static_audit.investigation_dispatch import run_agent_roles

    steps: list[StepResult] = []

    role_steps, role_manifest = run_agent_roles(
        case_id=case_id,
        workdir=workdir,
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
    steps.extend(role_steps)
    agent_manifest["roles"] = role_manifest

    return RolesResult(role_manifest=role_manifest, steps=steps)
