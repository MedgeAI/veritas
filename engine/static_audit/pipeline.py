#!/usr/bin/env python3
"""Core static audit pipeline orchestration.

Owns the end-to-end flow: material planning, deterministic tool execution,
Agent investigation rounds, visual forensics baseline, report generation.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT_PATH = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))

from engine.static_audit._shared import (
    PROJECT_ROOT,
    ProgressCallback,
    StepResult,
    emit_progress,
    ensure_output_subdirs,
    read_json,
    record_step,
    resolve_artifact_path,
    run_command,
)
from engine.static_audit.cli_driver import (
    discover_pdf,
    load_env,
    safe_remove_workdir,
)
from engine.static_audit.materials import (
    build_material_inventory,
    fallback_optional_lanes,
    write_material_inventory,
)
from engine.investigation.opencode_agent import DEFAULT_SOURCE_FINDING_PARAMS
from engine.tools.registry import (
    PAPER_STATIC_AUDIT_TOOL_IDS,
    STATIC_AUDIT_V1_TOOL_IDS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Material planning helpers
# ---------------------------------------------------------------------------


def source_finding_params_from_lane(lane: dict[str, Any] | None) -> dict[str, Any]:
    params = dict(DEFAULT_SOURCE_FINDING_PARAMS)
    if not lane:
        return params
    lane_params = lane.get("params")
    if not isinstance(lane_params, dict):
        return params
    source_params = lane_params.get("source_data_findings")
    if isinstance(source_params, dict):
        for key in params:
            if key in source_params:
                params[key] = source_params[key]
    return params


def selected_xlsx_source_lane(lanes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for lane in lanes:
        if (
            lane.get("lane_id") == "source_data_xlsx"
            and lane.get("status") == "selected"
            and lane.get("root")
        ):
            return lane
    return None


def material_plan_from_inventory(
    *,
    case_id: str,
    inventory: dict[str, Any],
    status: str,
    detail: str,
) -> dict[str, Any]:
    lanes = fallback_optional_lanes(inventory)
    unsupported = {"structured_table_text", "raw_data", "archive"}
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "status": status,
        "detail": detail,
        "selected_optional_lanes": lanes,
        "missing_materials": []
        if any(i.get("status") == "selected" for i in lanes)
        else ["source_data_xlsx"],
        "unsupported_materials": [
            {
                "path": i.get("relative_path") or i.get("path"),
                "material_type": i.get("material_type"),
                "reason": "Material type is inventoried but has no executable optional lane in static_audit_protocol.v1.",
            }
            for i in (inventory.get("files") or [])[:80]
            if i.get("material_type") in unsupported
        ],
        "agent_rationale": [
            "Deterministic fallback used material_inventory.json because Agent material planning was not available.",
            "Only registry-supported XLSX/XLSM Source Data lanes are executable in this MVP.",
        ],
    }


def optional_lanes_from_material_plan(
    material_plan: dict[str, Any] | None,
    inventory: dict[str, Any],
) -> list[dict[str, Any]]:
    if material_plan and isinstance(material_plan.get("selected_optional_lanes"), list):
        return [
            i for i in material_plan["selected_optional_lanes"] if isinstance(i, dict)
        ]
    return fallback_optional_lanes(inventory)


def resolve_selected_source_root(
    lane: dict[str, Any] | None, paper_dir: Path
) -> Path | None:
    if not lane or not lane.get("root"):
        return None
    root = Path(str(lane["root"])).expanduser()
    if not root.is_absolute():
        root = paper_dir / root
    resolved = root.resolve()
    if not resolved.is_dir() or not resolved.is_relative_to(paper_dir.resolve()):
        return None
    return resolved


# ---------------------------------------------------------------------------
# Section helpers — imported from _pipeline_steps to keep this file < 500 lines.
# ---------------------------------------------------------------------------

from engine.static_audit._pipeline_steps import (
    _run_agent_plan_section,
    _run_agent_review_section,
    _run_bundle_and_report,
    _run_investigation_fallbacks,
    _run_material_plan_section,
    _run_mineru_forensics_section,
    _run_source_data_steps,
)


def _run_visual_baseline(
    *,
    workdir: Path,
    images_dir: Path,
    args: argparse.Namespace,
    progress: ProgressCallback | None,
) -> tuple[list[StepResult], dict[str, Any]]:
    from engine.static_audit.visual_pipeline import (
        run_visual_panel_extraction,
        run_tru_for_detection,
        run_image_quality_detection,
        run_provenance_graph,
        run_visual_finding_pipeline,
    )

    steps: list[StepResult] = []
    manifest: dict[str, Any] = {}
    vs, vm = run_visual_panel_extraction(
        workdir=workdir, images_dir=images_dir, force=args.force, progress=progress
    )
    steps.extend(vs)
    manifest["visual_forensics"] = vm
    allow_env_skip = getattr(args, "skip_unavailable_tools", False)
    pe_status = (
        manifest.get("visual_forensics", {}).get("panel_extraction", {}).get("status")
    )
    for runner in (
        run_tru_for_detection,
        run_image_quality_detection,
        run_provenance_graph,
    ):
        kw: dict[str, Any] = {
            "workdir": workdir,
            "force": args.force,
            "progress": progress,
        }
        if runner is not run_image_quality_detection:
            kw["allow_env_skip"] = allow_env_skip
        kw["panel_extraction_status"] = pe_status
        s, m = runner(**kw)
        steps.extend(s)
        manifest.setdefault("visual_forensics", {}).update(m)
    fs, fm = run_visual_finding_pipeline(
        workdir=workdir, force=args.force, progress=progress
    )
    steps.extend(fs)
    manifest.setdefault("visual_forensics", {}).update(fm)
    return steps, manifest


def _run_static_audit_from_args(
    args: argparse.Namespace,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    from engine.static_audit.investigation_dispatch import (
        run_investigation_rounds,
        run_agent_roles,
    )

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

    # Material inventory
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

    agent_manifest: dict[str, Any] = {
        "mode": args.agent_mode,
        "model": args.agent_model,
        "opencode_bin": args.opencode_bin,
        "tool_registry": "paper_static_audit.v1",
        "registered_tool_ids": list(STATIC_AUDIT_V1_TOOL_IDS),
        "agent_plan_tool_ids": list(PAPER_STATIC_AUDIT_TOOL_IDS),
        "material_inventory": str(mi_path),
    }

    # Agent material plan
    mp_steps, material_plan = _run_material_plan_section(
        args=args,
        workdir=workdir,
        paper_dir=paper_dir,
        paper_pdf=paper_pdf,
        material_inventory=material_inventory,
        env=env,
        agent_manifest=agent_manifest,
        progress=progress,
    )
    steps.extend(mp_steps)

    optional_lanes = optional_lanes_from_material_plan(
        material_plan, material_inventory
    )
    source_lane = selected_xlsx_source_lane(optional_lanes)
    source_data_dir = resolve_selected_source_root(source_lane, paper_dir)
    agent_manifest["optional_lanes"] = optional_lanes
    agent_manifest["selected_source_data_dir"] = (
        str(source_data_dir) if source_data_dir else None
    )
    sfp = dict(DEFAULT_SOURCE_FINDING_PARAMS)
    sfp.update(source_finding_params_from_lane(source_lane))

    # Agent plan
    ap_steps, sfp = _run_agent_plan_section(
        args=args,
        workdir=workdir,
        paper_pdf=paper_pdf,
        source_data_dir=source_data_dir,
        source_finding_params=sfp,
        env=env,
        agent_manifest=agent_manifest,
        progress=progress,
    )
    steps.extend(ap_steps)

    # MinerU + forensics
    steps.extend(
        _run_mineru_forensics_section(
            args=args, workdir=workdir, paper_pdf=paper_pdf, env=env, progress=progress
        )
    )

    # Source data
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

    # Image duplicates
    images_dir = resolve_artifact_path(workdir, "images")
    if images_dir.is_dir():
        steps.append(
            run_command(
                "exact_image_duplicates",
                "图片字节级重复检查",
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "exact_image_duplicates.py"),
                    str(images_dir),
                    "--output",
                    str(resolve_artifact_path(workdir, "exact_image_duplicates.json")),
                ],
                [resolve_artifact_path(workdir, "exact_image_duplicates.json")],
                cwd=PROJECT_ROOT,
                env=env,
                force=args.force,
                progress=progress,
            )
        )
    else:
        for k, t in [
            ("exact_image_duplicates", "图片字节级重复检查"),
            ("image_similarity_candidates", "图片近似相似候选检查"),
        ]:
            record_step(
                steps,
                StepResult(k, t, "skipped", "images directory missing."),
                progress,
            )

    # Visual baseline
    vb_steps, vb_manifest = _run_visual_baseline(
        workdir=workdir, images_dir=images_dir, args=args, progress=progress
    )
    steps.extend(vb_steps)
    agent_manifest.setdefault("visual_forensics", {}).update(
        {
            k: v
            for k, v in vb_manifest.get("visual_forensics", {}).items()
            if k not in (agent_manifest.get("visual_forensics") or {})
        }
    )

    # Investigation rounds
    inv_steps, inv_manifest = run_investigation_rounds(
        case_id=case_id,
        workdir=workdir,
        source_data_dir=source_data_dir,
        agent_enabled=args.agent_mode != "off",
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
        )
    )

    # VLM triage
    if (resolve_artifact_path(workdir, "vlm_triage_selected.json")).exists():
        record_step(
            steps,
            StepResult(
                "vlm_triage",
                "VLM 抽样初筛",
                "reused",
                "Existing VLM triage artifact found.",
            ),
            progress,
        )
    else:
        record_step(
            steps,
            StepResult(
                "vlm_triage",
                "VLM 抽样初筛",
                "skipped",
                "Batch VLM triage is not implemented in this orchestrator.",
            ),
            progress,
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

    # Agent roles
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

    # Bundle + report
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
    )


def run_static_audit(
    paper_dir: str | Path,
    *,
    case_id: str | None = None,
    output_root: str = "outputs",
    fresh: bool = False,
    force: bool = False,
    no_env_file: bool = False,
    agent_mode: str = "full",
    agent_model: str = "dashscope/qwen3.7-plus",
    opencode_bin: str = "opencode",
    agent_timeout_seconds: int = 600,
    agent_max_retries: int = 1,
    skip_unavailable_tools: bool = False,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    args = argparse.Namespace(
        paper_dir=str(paper_dir),
        case_id=case_id,
        output_root=output_root,
        fresh=fresh,
        force=force,
        no_env_file=no_env_file,
        agent_mode=agent_mode,
        agent_model=agent_model,
        opencode_bin=opencode_bin,
        agent_timeout_seconds=agent_timeout_seconds,
        agent_max_retries=agent_max_retries,
        skip_unavailable_tools=skip_unavailable_tools,
    )
    return _run_static_audit_from_args(args, progress=progress)
