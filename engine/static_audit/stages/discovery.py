"""Discovery stage — profile resolution, input validation, PDF discovery, material inventory.

Corresponds to lines 277-354 of the original pipeline.py ``_run_static_audit_from_args``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.static_audit._shared import (
    PROJECT_ROOT,
    ProgressCallback,
    StepResult,
    emit_progress,
    ensure_output_subdirs,
    read_json,
    record_step,
    resolve_artifact_path,
)
from engine.static_audit.cli_driver import (
    discover_pdf,
    load_env,
    safe_remove_workdir,
)
from engine.static_audit.materials import (
    build_material_inventory,
    write_material_inventory,
)


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Outputs of the discovery stage."""

    paper_dir: Path
    paper_pdf: Path
    workdir: Path
    case_id: str
    env: dict[str, str]
    material_inventory: dict[str, Any]
    mi_path: Path
    steps: list[StepResult]


def run(
    args: argparse.Namespace,
    progress: ProgressCallback | None,
) -> DiscoveryResult:
    """Resolve profile, set up workdir, discover PDF, build material inventory.

    Mutates *args* in place to apply audit-profile overrides.
    """
    from engine.static_audit.pipeline import resolve_audit_profile

    # --- Profile resolution (must stay here; mutates args) ----------------
    if isinstance(getattr(args, "profile", None), str):
        args.audit_profile = args.profile
        args.profile = resolve_audit_profile(args.profile)
    elif not hasattr(args, "profile") or not isinstance(args.profile, dict):
        args.audit_profile = getattr(args, "audit_profile", "fast")
        args.profile = resolve_audit_profile(args.audit_profile)

    profile = args.profile
    args.agent_timeout_seconds = profile.get(
        "agent_timeout_seconds", args.agent_timeout_seconds
    )
    args.agent_max_retries = profile.get("agent_max_retries", args.agent_max_retries)

    # --- Workdir setup ----------------------------------------------------
    paper_dir = Path(args.paper_dir).expanduser().resolve()
    if not paper_dir.is_dir():
        raise NotADirectoryError(paper_dir)

    case_id = args.case_id or paper_dir.name
    output_root = (
        (PROJECT_ROOT / args.output_root).resolve()
        if not Path(args.output_root).is_absolute()
        else Path(args.output_root)
    )
    workdir = output_root / case_id / "research-integrity-audit"
    if args.fresh:
        safe_remove_workdir(workdir, output_root)
    workdir.mkdir(parents=True, exist_ok=True)
    ensure_output_subdirs(workdir)

    # --- PDF discovery + env ----------------------------------------------
    paper_pdf = discover_pdf(paper_dir)
    env = load_env(not args.no_env_file)
    steps: list[StepResult] = []

    emit_progress(
        progress,
        "audit_start",
        case_id=case_id,
        paper_dir=str(paper_dir),
        workdir=workdir,
        agent_mode=args.agent_mode,
        audit_profile=getattr(args, "audit_profile", "fast"),
    )
    record_step(
        steps,
        StepResult(
            "discover",
            "发现输入材料",
            "ran",
            f"PDF={paper_pdf}; optional data lanes will be selected from material_inventory.json",
        ),
        progress,
    )

    # --- Material inventory -----------------------------------------------
    mi_path = resolve_artifact_path(workdir, "material_inventory.json")
    if mi_path.exists() and not args.force:
        material_inventory = read_json(mi_path) or {}
        record_step(
            steps,
            StepResult(
                "material_inventory",
                "材料清单扫描",
                "reused",
                "Existing material_inventory.json found.",
            ),
            progress,
        )
    else:
        material_inventory = build_material_inventory(paper_dir, paper_pdf)
        write_material_inventory(mi_path, material_inventory)
        record_step(
            steps,
            StepResult("material_inventory", "材料清单扫描", "ran", str(mi_path)),
            progress,
        )

    return DiscoveryResult(
        paper_dir=paper_dir,
        paper_pdf=paper_pdf,
        workdir=workdir,
        case_id=case_id,
        env=env,
        material_inventory=material_inventory,
        mi_path=mi_path,
        steps=steps,
    )
