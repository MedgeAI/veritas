#!/usr/bin/env python3
"""Run the first-party Veritas static paper-audit pipeline."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT_PATH = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))

from engine.env import load_project_env
from engine.static_audit._shared import (
    ARTIFACT_PATH_MAP,
    AUDITOR_ROOT,
    MAX_INVESTIGATION_ROUNDS,
    OUTPUT_DIRS,
    PROJECT_ROOT,
    STEP_TOOL_IDS,
    ProgressCallback,
    StepResult,
    _write_long_text_to_log,
    agent_step_status,
    artifact_exists,
    emit_progress,
    emit_step_result,
    emit_step_start,
    enforce_event_contract,
    ensure_output_subdirs,
    investigation_action_from_dict,
    output_subdir,
    read_json,
    record_step,
    resolve_artifact_path,
    run_command,
    safe_action_dir_name,
    source_finding_params_from_plan,
)

# Re-exports for backward compatibility (tests and external consumers may import from orchestrator).
__all__ = [
    "ARTIFACT_PATH_MAP",
    "AUDITOR_ROOT",
    "MAX_INVESTIGATION_ROUNDS",
    "OUTPUT_DIRS",
    "PROJECT_ROOT",
    "STEP_TOOL_IDS",
    "ProgressCallback",
    "StepResult",
    "_write_long_text_to_log",
    "agent_step_status",
    "artifact_exists",
    "emit_progress",
    "emit_step_result",
    "emit_step_start",
    "enforce_event_contract",
    "ensure_output_subdirs",
    "investigation_action_from_dict",
    "output_subdir",
    "read_json",
    "record_step",
    "resolve_artifact_path",
    "run_command",
    "safe_action_dir_name",
    "source_finding_params_from_plan",
]
from engine.static_audit.html_report import write_static_audit_html
from engine.static_audit.materials import (
    build_material_inventory,
    fallback_optional_lanes,
    write_material_inventory,
)
from engine.static_audit.tools.paperfraud_rules import (
    run_paperfraud_rule_match,
)
from engine.investigation.opencode_agent import (
    DEFAULT_SOURCE_FINDING_PARAMS,
    result_metadata,
    run_agent_material_plan,
    run_agent_plan,
    run_agent_review,
    write_agent_result,
)
from engine.tools.registry import (
    PAPER_STATIC_AUDIT_TOOL_IDS,
    STATIC_AUDIT_V1_TOOL_IDS,
    selected_tool_ids_from_plan,
)

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Veritas paper audit from a local paper directory."
    )
    parser.add_argument("paper_dir", help="Directory containing paper PDF and optional Source Data.")
    parser.add_argument("--case-id", help="Case id used under outputs/<case-id>.")
    parser.add_argument("--output-root", default="outputs", help="Output root directory.")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Remove the case audit workdir before running; guarantees previous MinerU outputs are not reused.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run steps even if expected outputs already exist.",
    )
    parser.add_argument(
        "--no-env-file",
        action="store_true",
        help="Do not load local .env into subprocess environment.",
    )
    parser.add_argument(
        "--agent-mode",
        choices=["off", "plan", "review", "full"],
        default="full",
        help="opencode Agent mode: off disables Agent, plan only tunes deterministic steps, review only interprets artifacts, full does both.",
    )
    parser.add_argument(
        "--agent-model",
        default="dashscope/qwen3.7-plus",
        help="opencode model id used for Agent plan/review.",
    )
    parser.add_argument(
        "--opencode-bin",
        default="opencode",
        help="opencode executable path.",
    )
    parser.add_argument(
        "--agent-timeout-seconds",
        type=int,
        default=300,
        help="Timeout for each opencode Agent call.",
    )
    parser.add_argument(
        "--agent-max-retries",
        type=int,
        default=1,
        help="Retries after invalid Agent JSON output.",
    )
    parser.add_argument(
        "--skip-unavailable-tools",
        action="store_true",
        help="Allow pipeline to continue when tools fail due to missing environment prerequisites (GPU, Docker). "
             "Without this flag, environment failures abort the pipeline.",
    )
    return parser.parse_args()


def safe_remove_workdir(workdir: Path, output_root: Path) -> None:
    if not workdir.exists():
        return
    resolved_workdir = workdir.resolve()
    resolved_output_root = output_root.resolve()
    if resolved_workdir == resolved_output_root:
        raise ValueError(f"Refusing to remove output root: {resolved_workdir}")
    if resolved_workdir.name != "research-integrity-audit":
        raise ValueError(f"Refusing to remove unexpected workdir: {resolved_workdir}")
    if not resolved_workdir.is_relative_to(resolved_output_root):
        raise ValueError(f"Refusing to remove path outside output root: {resolved_workdir}")
    shutil.rmtree(resolved_workdir)


def load_env(include_env_file: bool) -> dict[str, str]:
    return load_project_env(PROJECT_ROOT, include_env_file=include_env_file)


def discover_pdf(paper_dir: Path) -> Path:
    pdfs = sorted(path for path in paper_dir.glob("*.pdf") if path.is_file())
    if not pdfs:
        raise FileNotFoundError(f"No PDF found in {paper_dir}")
    if len(pdfs) > 1:
        # Deterministic choice for the MVP; future manifest should remove ambiguity.
        return pdfs[0]
    return pdfs[0]


def exists_all(paths: list[Path]) -> bool:
    return all(path.exists() for path in paths)


def text_tail(value: str, limit: int = 1000) -> str:
    value = value.strip()
    if not value:
        return ""
    return value[-limit:]


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
        if lane.get("lane_id") == "source_data_xlsx" and lane.get("status") == "selected" and lane.get("root"):
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
    unsupported_material_types = {"structured_table_text", "raw_data", "archive"}
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "status": status,
        "detail": detail,
        "selected_optional_lanes": lanes,
        "missing_materials": [] if any(item.get("status") == "selected" for item in lanes) else ["source_data_xlsx"],
        "unsupported_materials": [
            {
                "path": item.get("relative_path") or item.get("path"),
                "material_type": item.get("material_type"),
                "reason": "Material type is inventoried but has no executable optional lane in static_audit_protocol.v1.",
            }
            for item in (inventory.get("files") or [])[:80]
            if item.get("material_type") in unsupported_material_types
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
        return [item for item in material_plan["selected_optional_lanes"] if isinstance(item, dict)]
    return fallback_optional_lanes(inventory)


def resolve_selected_source_root(lane: dict[str, Any] | None, paper_dir: Path) -> Path | None:
    if not lane or not lane.get("root"):
        return None
    root = Path(str(lane["root"])).expanduser()
    if not root.is_absolute():
        root = paper_dir / root
    resolved = root.resolve()
    paper_root = paper_dir.resolve()
    if not resolved.is_dir():
        return None
    if not resolved.is_relative_to(paper_root):
        return None
    return resolved


# ---------------------------------------------------------------------------
# Lazy re-exports for backward compatibility.
# External consumers import from orchestrator; the actual functions live in
# report.py, visual_pipeline.py, and investigation_dispatch.py.
# We use module-level __getattr__ to avoid circular imports at load time.
# ---------------------------------------------------------------------------
_LAZY_REEXPORTS: dict[str, str] = {
    # report.py
    "generate_report": "engine.static_audit.report",
    "build_static_audit_bundle": "engine.static_audit.report",
    "collect_claims_and_findings": "engine.static_audit.report",
    "collect_evidence_items": "engine.static_audit.report",
    "collect_agent_refined_claim_mappings": "engine.static_audit.report",
    "collect_deterministic_claim_mappings": "engine.static_audit.report",
    "normalize_claim_status": "engine.static_audit.report",
    "brief_list": "engine.static_audit.report",
    "dedupe": "engine.static_audit.report",
    "agent_manual_review_rows": "engine.static_audit.report",
    "agent_finding_review_rows": "engine.static_audit.report",
    "investigation_record_rows": "engine.static_audit.report",
    # visual_pipeline.py
    "run_visual_panel_extraction": "engine.static_audit.visual_pipeline",
    "run_visual_finding_pipeline": "engine.static_audit.visual_pipeline",
    "run_tru_for_detection": "engine.static_audit.visual_pipeline",
    "run_image_quality_detection": "engine.static_audit.visual_pipeline",
    "run_overlap_reuse_detection": "engine.static_audit.visual_pipeline",
    "run_provenance_graph": "engine.static_audit.visual_pipeline",
    "run_sila_dense_detection": "engine.static_audit.visual_pipeline",
    # investigation_dispatch.py
    "run_investigation_rounds": "engine.static_audit.investigation_dispatch",
    "run_investigation_tool_action": "engine.static_audit.investigation_dispatch",
    "run_agent_roles": "engine.static_audit.investigation_dispatch",
    "collect_agent_traces": "engine.static_audit.investigation_dispatch",
    "trace_from_role_result": "engine.static_audit.investigation_dispatch",
    "write_role_agent_result": "engine.static_audit.investigation_dispatch",
    "role_failure_payload": "engine.static_audit.investigation_dispatch",
    "role_output_summary": "engine.static_audit.investigation_dispatch",
    "write_reserved_role_output": "engine.static_audit.investigation_dispatch",
    "write_role_trace": "engine.static_audit.investigation_dispatch",
    "read_agent_trace": "engine.static_audit.investigation_dispatch",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_REEXPORTS:
        import importlib
        module = importlib.import_module(_LAZY_REEXPORTS[name])
        value = getattr(module, name)
        # Cache in module globals so subsequent lookups are fast
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")



def _run_static_audit_from_args(
    args: argparse.Namespace,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    # Local imports to break circular dependency with submodules.
    from engine.static_audit.visual_pipeline import (
        run_visual_panel_extraction,
        run_tru_for_detection,
        run_image_quality_detection,
        run_provenance_graph,
        run_visual_finding_pipeline,
    )
    from engine.static_audit.investigation_dispatch import (
        run_investigation_rounds,
        run_agent_roles,
    )
    from engine.static_audit.report import (
        build_static_audit_bundle,
        generate_report,
    )

    paper_dir = Path(args.paper_dir).expanduser().resolve()
    if not paper_dir.is_dir():
        raise NotADirectoryError(paper_dir)

    case_id = args.case_id or paper_dir.name
    output_root = (PROJECT_ROOT / args.output_root).resolve() if not Path(args.output_root).is_absolute() else Path(args.output_root)
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
        workdir=str(workdir),
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

    material_inventory_path = resolve_artifact_path(workdir, "material_inventory.json")
    if material_inventory_path.exists() and not args.force:
        material_inventory = read_json(material_inventory_path) or {}
        record_step(
            steps,
            StepResult("material_inventory", "材料清单扫描", "reused", "Existing material_inventory.json found."),
            progress,
        )
    else:
        material_inventory = build_material_inventory(paper_dir, paper_pdf)
        write_material_inventory(material_inventory_path, material_inventory)
        record_step(steps, StepResult("material_inventory", "材料清单扫描", "ran", str(material_inventory_path)), progress)

    agent_manifest: dict[str, Any] = {
        "mode": args.agent_mode,
        "model": args.agent_model,
        "opencode_bin": args.opencode_bin,
        "tool_registry": "paper_static_audit.v1",
        "registered_tool_ids": list(STATIC_AUDIT_V1_TOOL_IDS),
        "agent_plan_tool_ids": list(PAPER_STATIC_AUDIT_TOOL_IDS),
        "material_inventory": str(material_inventory_path),
    }

    agent_material_plan_path = resolve_artifact_path(workdir, "agent_material_plan.json")
    if agent_material_plan_path.exists() and not args.force:
        material_plan = read_json(agent_material_plan_path) or material_plan_from_inventory(
            case_id=case_id,
            inventory=material_inventory,
            status="fallback",
            detail="Existing agent_material_plan.json could not be parsed; deterministic fallback used.",
        )
        agent_manifest["material_plan"] = {
            "status": "reused",
            "detail": "Existing agent_material_plan.json found.",
            "runtime_seconds": None,
            "retries": 0,
            "command": [],
            "output": str(agent_material_plan_path),
        }
        record_step(
            steps,
            StepResult(
                "agent_material_plan",
                "opencode Agent 材料计划",
                "reused",
                "Existing agent_material_plan.json found.",
            ),
            progress,
        )
    elif args.agent_mode == "off":
        material_plan = material_plan_from_inventory(
            case_id=case_id,
            inventory=material_inventory,
            status="deterministic_fallback",
            detail="agent_mode=off; optional lanes were selected from deterministic material inventory only.",
        )
        agent_material_plan_path.write_text(json.dumps(material_plan, ensure_ascii=False, indent=2), encoding="utf-8")
        agent_manifest["material_plan"] = {
            "status": "not_run",
            "detail": material_plan["detail"],
            "runtime_seconds": None,
            "retries": 0,
            "command": [],
            "output": str(agent_material_plan_path),
        }
        record_step(
            steps,
            StepResult("agent_material_plan", "opencode Agent 材料计划", "skipped", material_plan["detail"]),
            progress,
        )
    else:
        emit_step_start(
            progress,
            "agent_material_plan",
            "opencode Agent 材料计划",
            "Calling opencode to select optional material lanes.",
        )
        agent_material_plan_result = run_agent_material_plan(
            case_id=case_id,
            workdir=workdir,
            project_root=PROJECT_ROOT,
            env=env,
            model=args.agent_model,
            opencode_bin=args.opencode_bin,
            timeout_seconds=args.agent_timeout_seconds,
            max_retries=args.agent_max_retries,
        )
        if agent_material_plan_result.data:
            material_plan = agent_material_plan_result.data
            write_agent_result(agent_material_plan_path, agent_material_plan_result, "material_plan")
        else:
            material_plan = material_plan_from_inventory(
                case_id=case_id,
                inventory=material_inventory,
                status="fallback",
                detail=f"Agent material plan failed; deterministic fallback used. {agent_material_plan_result.detail}",
            )
            agent_material_plan_path.write_text(json.dumps(material_plan, ensure_ascii=False, indent=2), encoding="utf-8")
        agent_manifest["material_plan"] = result_metadata(agent_material_plan_result, agent_material_plan_path)
        record_step(
            steps,
            StepResult(
                "agent_material_plan",
                "opencode Agent 材料计划",
                agent_step_status(agent_material_plan_result.status),
                agent_material_plan_result.detail,
                agent_material_plan_result.command,
            ),
            progress,
        )

    optional_lanes = optional_lanes_from_material_plan(material_plan, material_inventory)
    source_lane = selected_xlsx_source_lane(optional_lanes)
    source_data_dir = resolve_selected_source_root(source_lane, paper_dir)
    agent_manifest["optional_lanes"] = optional_lanes
    agent_manifest["selected_source_data_dir"] = str(source_data_dir) if source_data_dir else None

    source_finding_params = dict(DEFAULT_SOURCE_FINDING_PARAMS)
    source_finding_params.update(source_finding_params_from_lane(source_lane))
    if args.agent_mode in {"plan", "full"}:
        agent_plan_path = resolve_artifact_path(workdir, "agent_audit_plan.json")
        emit_step_start(
            progress,
            "agent_plan",
            "opencode Agent 审查计划",
            "Calling opencode to fill deterministic tool parameters.",
        )
        agent_plan_result = run_agent_plan(
            case_id=case_id,
            paper_pdf=paper_pdf,
            source_data_dir=source_data_dir,
            workdir=workdir,
            project_root=PROJECT_ROOT,
            env=env,
            model=args.agent_model,
            opencode_bin=args.opencode_bin,
            timeout_seconds=args.agent_timeout_seconds,
            max_retries=args.agent_max_retries,
        )
        write_agent_result(agent_plan_path, agent_plan_result, "audit_plan")
        agent_manifest["plan"] = result_metadata(agent_plan_result, agent_plan_path)
        agent_manifest["selected_tool_ids"] = selected_tool_ids_from_plan(agent_plan_result.data)
        record_step(
            steps,
            StepResult(
                "agent_plan",
                "opencode Agent 审查计划",
                agent_step_status(agent_plan_result.status),
                agent_plan_result.detail,
                agent_plan_result.command,
            ),
            progress,
        )
        if agent_plan_result.data:
            source_finding_params = source_finding_params_from_plan(agent_plan_result.data)
    else:
        agent_manifest["plan"] = None
        agent_manifest["selected_tool_ids"] = list(PAPER_STATIC_AUDIT_TOOL_IDS)

    mineru_outputs = [resolve_artifact_path(workdir, "full.md"), resolve_artifact_path(workdir, "mineru_manifest.json"), resolve_artifact_path(workdir, "images")]
    if exists_all(mineru_outputs) and not args.force:
        record_step(steps, StepResult("mineru", "MinerU PDF 解析", "reused", "Existing MinerU outputs found."), progress)
    elif not env.get("MINERU_API_TOKEN"):
        record_step(
            steps,
            StepResult("mineru", "MinerU PDF 解析", "skipped", "MINERU_API_TOKEN is missing; cannot run MinerU from scratch."),
            progress,
        )
    else:
        # MinerU outputs to root directory, not subdirectories
        # We check root paths here, and relocate to subdirectories after evidence_ledger
        mineru_root_outputs = [workdir / "full.md", workdir / "mineru_manifest.json", workdir / "images"]
        steps.append(
            run_command(
                "mineru",
                "MinerU PDF 解析",
                [sys.executable, "scripts/mineru_convert.py", str(paper_pdf), "--output", str(workdir)],
                mineru_root_outputs,
                cwd=AUDITOR_ROOT,
                env=env,
                force=args.force,
                attempts=3,
                retry_delay_seconds=10,
                progress=progress,
                stream_output=True,
            )
        )
        # Note: Don't relocate MinerU outputs yet. build_evidence_ledger.py needs them in root.
        # Relocation will happen after evidence_ledger step.

    # Check root directory for full.md since MinerU outputs there before relocation
    if (workdir / "full.md").exists():
        steps.append(
            run_command(
                "evidence_ledger",
                "构建 evidence ledger",
                [
                    sys.executable,
                    "scripts/build_evidence_ledger.py",
                    str(workdir),
                    "--output",
                    str(resolve_artifact_path(workdir, "evidence_ledger.json")),
                ],
                [resolve_artifact_path(workdir, "evidence_ledger.json")],
                cwd=AUDITOR_ROOT,
                env=env,
                force=args.force,
                progress=progress,
            )
        )
        # Now relocate MinerU outputs to layered subdirectories
        _relocate_mineru_outputs(workdir)
        steps.append(
            run_command(
                "numeric_forensics",
                "PDF 数字取证",
                [
                    sys.executable,
                    "scripts/numeric_forensics.py",
                    str(workdir),
                    "--output",
                    str(resolve_artifact_path(workdir, "numeric_forensics.json")),
                ],
                [resolve_artifact_path(workdir, "numeric_forensics.json")],
                cwd=AUDITOR_ROOT,
                env=env,
                force=args.force,
                progress=progress,
            )
        )
        # ── PaperFraud rule matching ──────────────────────────────────
        paperfraud_output = resolve_artifact_path(workdir, "paperfraud_rule_matches.json")
        if paperfraud_output.exists() and not args.force:
            record_step(
                steps,
                StepResult(
                    "paperfraud_rule_match",
                    "PaperFraud 规则库匹配",
                    "reused",
                    "Existing paperfraud_rule_matches.json found.",
                ),
                progress,
            )
        else:
            emit_step_start(
                progress,
                "paperfraud_rule_match",
                "PaperFraud 规则库匹配",
                "Matching structured PaperFraud rules against parsed paper text.",
            )
            run_paperfraud_rule_match(resolve_artifact_path(workdir, "full.md"), paperfraud_output)
            record_step(
                steps,
                StepResult("paperfraud_rule_match", "PaperFraud 规则库匹配", "ran", str(paperfraud_output)),
                progress,
            )
    else:
        record_step(steps, StepResult("evidence_ledger", "构建 evidence ledger", "skipped", "full.md missing."), progress)
        record_step(steps, StepResult("numeric_forensics", "PDF 数字取证", "skipped", "full.md missing."), progress)
        record_step(steps, StepResult("paperfraud_rule_match", "PaperFraud 规则库匹配", "skipped", "full.md missing."), progress)

    if source_lane and source_data_dir and source_data_dir.is_dir():
        steps.append(
            run_command(
                "source_data_profile",
                "Source Data profile",
                [
                    sys.executable,
                    "-m",
                    "engine.static_audit.tools.source_data_profile",
                    str(source_data_dir),
                    "--output",
                    str(resolve_artifact_path(workdir, "source_data_profile.json")),
                ],
                [resolve_artifact_path(workdir, "source_data_profile.json")],
                cwd=PROJECT_ROOT,
                env=env,
                force=args.force,
                progress=progress,
            )
        )
        if (resolve_artifact_path(workdir, "source_data_profile.json")).exists():
            command = [
                sys.executable,
                "-m",
                "engine.static_audit.tools.source_data_findings",
                str(source_data_dir),
                "--profile",
                str(resolve_artifact_path(workdir, "source_data_profile.json")),
                "--output",
                str(resolve_artifact_path(workdir, "source_data_findings.json")),
                "--min-overlap",
                str(source_finding_params["min_overlap"]),
                "--min-support",
                str(source_finding_params["min_support"]),
                "--max-findings-per-category",
                str(source_finding_params["max_findings_per_category"]),
            ]
            if (resolve_artifact_path(workdir, "full.md")).exists():
                command.extend(["--full-md", str(resolve_artifact_path(workdir, "full.md"))])
            steps.append(
                run_command(
                    "source_data_findings",
                    "Source Data findings",
                    command,
                    [resolve_artifact_path(workdir, "source_data_findings.json")],
                    cwd=PROJECT_ROOT,
                    env=env,
                    force=args.force,
                    progress=progress,
                )
            )
            steps.append(
                run_command(
                    "source_data_pair_forensics",
                    "Source Data pair forensics",
                    [
                        sys.executable,
                        "-m",
                        "engine.static_audit.tools.source_data_pair_forensics",
                        str(source_data_dir),
                        "--output",
                        str(resolve_artifact_path(workdir, "source_data_pair_forensics.json")),
                    ],
                    [resolve_artifact_path(workdir, "source_data_pair_forensics.json")],
                    cwd=PROJECT_ROOT,
                    env=env,
                    force=args.force,
                    progress=progress,
                )
            )
            steps.append(
                run_command(
                    "source_data_cross_sheet",
                    "Source Data cross-sheet duplicates",
                    [
                        sys.executable,
                        "-m",
                        "engine.static_audit.tools.source_data_cross_sheet",
                        str(source_data_dir),
                        "--output",
                        str(resolve_artifact_path(workdir, "source_data_cross_sheet.json")),
                    ],
                    [resolve_artifact_path(workdir, "source_data_cross_sheet.json")],
                    cwd=PROJECT_ROOT,
                    env=env,
                    force=args.force,
                    progress=progress,
                )
            )
            # ── LLM verdict: adjudicate source data findings per sheet ──
            verdict_key = "source_data_verdict"
            verdict_title = "Source Data LLM 语义裁决"
            emit_step_start(progress, verdict_key, verdict_title)
            try:
                from engine.static_audit.tools.source_data_verdict import (
                    run_source_data_verdict,
                )
                verdict_result = run_source_data_verdict(
                    workdir,
                    source_data_dir=source_data_dir,
                    project_root=PROJECT_ROOT,
                    env=env,
                    model=args.agent_model,
                    opencode_bin=args.opencode_bin,
                    force=args.force,
                    progress=progress,
                )
                v_summary = verdict_result.get("summary", {})
                v_detail = (
                    f"sheets={v_summary.get('total_sheets', 0)} "
                    f"TP={v_summary.get('true_positive', 0)} "
                    f"FP={v_summary.get('false_positive', 0)} "
                    f"uncertain={v_summary.get('uncertain', 0)}"
                )
                v_status = "ran" if v_summary.get("total_sheets", 0) > 0 else "skipped"
                if v_summary.get("failed_sheets", 0) > 0:
                    v_status = "warning"
                    v_detail += f" failed_sheets={v_summary['failed_sheets']}"
            except Exception as e:
                v_status = "warning"
                v_detail = f"verdict step exception: {e}"
                logger.warning("source_data_verdict failed: %s", e)
            record_step(
                steps,
                StepResult(verdict_key, verdict_title, v_status, v_detail),
                progress,
            )
        else:
            record_step(
                steps,
                StepResult("source_data_findings", "Source Data findings", "skipped", "source_data_profile.json missing."),
                progress,
            )
            record_step(
                steps,
                StepResult("source_data_pair_forensics", "Source Data pair forensics", "skipped", "source_data_profile.json missing."),
                progress,
            )
            record_step(
                steps,
                StepResult("source_data_cross_sheet", "Source Data cross-sheet duplicates", "skipped", "source_data_profile.json missing."),
                progress,
            )
            record_step(
                steps,
                StepResult("source_data_verdict", "Source Data LLM 语义裁决", "skipped", "source_data_profile.json missing."),
                progress,
            )
    else:
        if source_lane and source_lane.get("root"):
            source_skip_detail = f"Selected Source Data root is invalid or outside paper_dir: {source_lane.get('root')}"
        else:
            source_skip_detail = (source_lane or {}).get("reason") or "No executable XLSX/XLSM Source Data optional lane was selected."
        record_step(steps, StepResult("source_data_profile", "Source Data profile", "skipped", source_skip_detail), progress)
        record_step(steps, StepResult("source_data_findings", "Source Data findings", "skipped", source_skip_detail), progress)
        record_step(steps, StepResult("source_data_pair_forensics", "Source Data pair forensics", "skipped", source_skip_detail), progress)
        record_step(steps, StepResult("source_data_cross_sheet", "Source Data cross-sheet duplicates", "skipped", source_skip_detail), progress)
        record_step(steps, StepResult("source_data_verdict", "Source Data LLM 语义裁决", "skipped", source_skip_detail), progress)

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
        # image_similarity_candidates is deferred to post-investigation phase.
        # It runs as Agent-selectable or deterministic fallback after investigation rounds.
    else:
        record_step(steps, StepResult("exact_image_duplicates", "图片字节级重复检查", "skipped", "images directory missing."), progress)
        record_step(
            steps,
            StepResult("image_similarity_candidates", "图片近似相似候选检查", "skipped", "images directory missing."),
            progress,
        )

    visual_steps, visual_manifest = run_visual_panel_extraction(
        workdir=workdir,
        images_dir=images_dir,
        force=args.force,
        progress=progress,
    )
    steps.extend(visual_steps)
    agent_manifest["visual_forensics"] = visual_manifest

    # MANDATORY_BASELINE visual tools: run unconditionally in the baseline pipeline.
    # SILA dense remains an Agent investigation tool (AGENT_SELECTABLE) because it
    # is resource-heavy and must run with a bounded panel selection.
    allow_env_skip = getattr(args, "skip_unavailable_tools", False)
    panel_extraction_status = agent_manifest.get("visual_forensics", {}).get("panel_extraction", {}).get("status")
    tru_for_steps, tru_for_manifest = run_tru_for_detection(
        workdir=workdir, force=args.force, allow_env_skip=allow_env_skip,
        panel_extraction_status=panel_extraction_status, progress=progress,
    )
    steps.extend(tru_for_steps)
    agent_manifest.setdefault("visual_forensics", {}).update(tru_for_manifest)

    iq_steps, iq_manifest = run_image_quality_detection(
        workdir=workdir, force=args.force,
        panel_extraction_status=panel_extraction_status, progress=progress,
    )
    steps.extend(iq_steps)
    agent_manifest.setdefault("visual_forensics", {}).update(iq_manifest)

    provenance_steps, provenance_manifest = run_provenance_graph(
        workdir=workdir, force=args.force, allow_env_skip=allow_env_skip,
        panel_extraction_status=panel_extraction_status, progress=progress,
    )
    steps.extend(provenance_steps)
    agent_manifest.setdefault("visual_forensics", {}).update(provenance_manifest)

    investigation_steps, investigation_manifest = run_investigation_rounds(
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
    steps.extend(investigation_steps)
    agent_manifest["investigation"] = investigation_manifest

    # AGENT_SELECTABLE with deterministic fallback:
    # image_similarity and copy_move run via Agent investigation rounds, but
    # fall back to deterministic execution when the Agent planner fails or is
    # disabled.  Fallback output is written to investigation/fallback/ so the
    # finding pipeline picks it up via rglob without overwriting baseline
    # artifacts.
    investigation_dir = resolve_artifact_path(workdir, "investigation")
    agent_similarity_outputs = (
        sorted(investigation_dir.rglob("image_similarity_candidates.json"))
        if investigation_dir.exists() else []
    )
    agent_copy_move_outputs = (
        sorted(investigation_dir.rglob("visual_copy_move.json"))
        if investigation_dir.exists() else []
    )
    agent_planner_failed = (
        not investigation_manifest.get("enabled", True)
        or investigation_manifest.get("stop_reason") == "planner_failed"
    )

    # --- image_similarity_candidates ---
    if agent_similarity_outputs:
        record_step(
            steps,
            StepResult("image_similarity_candidates", "图片近似相似候选检查", "ran",
                       "image.similarity_candidates output was produced by AgentInvestigationPlanner."),
            progress,
        )
    elif agent_planner_failed and images_dir.is_dir():
        fallback_dir = investigation_dir / "fallback"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_output = fallback_dir / "image_similarity_candidates.json"
        similarity_cmd = [
            sys.executable, "-m", "engine.static_audit.tools.image_similarity",
            str(images_dir),
            "--output", str(fallback_output),
            "--max-distance", "8",
            "--max-candidates", "200",
        ]
        panel_evidence_json = resolve_artifact_path(workdir, "panel_evidence.json")
        if panel_evidence_json.exists():
            similarity_cmd.extend(["--panel-evidence", str(panel_evidence_json)])
        steps.append(run_command(
            "image_similarity_candidates",
            "图片近似相似候选检查（确定性回退）",
            similarity_cmd,
            [fallback_output],
            cwd=PROJECT_ROOT, env=env, force=args.force, progress=progress,
        ))
        if steps[-1].status == "ran":
            steps[-1].detail = "Ran as deterministic fallback: Agent investigation planner failed."
    elif not images_dir.is_dir():
        record_step(
            steps,
            StepResult("image_similarity_candidates", "图片近似相似候选检查", "skipped",
                       "images directory missing."),
            progress,
        )
    else:
        record_step(
            steps,
            StepResult("image_similarity_candidates", "图片近似相似候选检查", "skipped",
                       "AgentInvestigationPlanner did not select image.similarity_candidates for this run."),
            progress,
        )

    # --- visual_copy_move ---
    if agent_copy_move_outputs:
        record_step(
            steps,
            StepResult("visual_copy_move", "图片 Copy-Move 检测", "ran",
                       "visual.copy_move output was produced by AgentInvestigationPlanner."),
            progress,
        )
    elif agent_planner_failed and resolve_artifact_path(workdir, "panel_evidence.json").exists():
        fallback_dir = investigation_dir / "fallback"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_output = fallback_dir / "visual_copy_move.json"
        panel_json = resolve_artifact_path(workdir, "panel_evidence.json")
        steps.append(run_command(
            "visual_copy_move",
            "图片 Copy-Move 检测（确定性回退）",
            [
                sys.executable, "-m", "engine.static_audit.tools.copy_move_detection",
                str(panel_json),
                "--figure-json", str(resolve_artifact_path(workdir, "visual_evidence.json")),
                "--output", str(fallback_output),
                "--workdir", str(workdir),
                "--method", "rootsift_magsac",
                "--min-matches", "20",
                "--min-score", "0.05",
                "--max-relationships", "500",
            ],
            [fallback_output],
            cwd=PROJECT_ROOT, env=env, force=args.force, progress=progress,
        ))
        if steps[-1].status == "ran":
            steps[-1].detail = "Ran as deterministic fallback: Agent investigation planner failed."
    elif not resolve_artifact_path(workdir, "panel_evidence.json").exists():
        record_step(
            steps,
            StepResult("visual_copy_move", "图片 Copy-Move 检测", "skipped",
                       "panel_evidence.json missing."),
            progress,
        )
    else:
        record_step(
            steps,
            StepResult("visual_copy_move", "图片 Copy-Move 检测", "skipped",
                       "AgentInvestigationPlanner did not select visual.copy_move for this run."),
            progress,
        )

    # REPORT_ONLY: finding pipeline aggregates existing visual artifacts.
    visual_finding_steps, visual_finding_manifest = run_visual_finding_pipeline(
        workdir=workdir,
        force=args.force,
        progress=progress,
    )
    steps.extend(visual_finding_steps)
    agent_manifest.setdefault("visual_forensics", {}).update(visual_finding_manifest)

    if (resolve_artifact_path(workdir, "vlm_triage_selected.json")).exists():
        record_step(steps, StepResult("vlm_triage", "VLM 抽样初筛", "reused", "Existing VLM triage artifact found."), progress)
    else:
        record_step(
            steps,
            StepResult("vlm_triage", "VLM 抽样初筛", "skipped", "Batch VLM triage is not implemented in this orchestrator."),
            progress,
        )

    if args.agent_mode in {"review", "full"}:
        agent_review_path = resolve_artifact_path(workdir, "agent_review.json")
        if agent_review_path.exists() and not args.force:
            agent_manifest["review"] = {
                "status": "reused",
                "detail": "Existing agent_review.json found.",
                "runtime_seconds": None,
                "retries": 0,
                "command": [],
                "output": str(agent_review_path),
            }
            record_step(
                steps,
                StepResult(
                    "agent_review",
                    "opencode Agent 结构化审阅",
                    "reused",
                    "Existing agent_review.json found.",
                ),
                progress,
            )
        else:
            emit_step_start(
                progress,
                "agent_review",
                "opencode Agent 结构化审阅",
                "Calling opencode to review deterministic audit artifacts.",
            )
            agent_review_result = run_agent_review(
                case_id=case_id,
                workdir=workdir,
                project_root=PROJECT_ROOT,
                env=env,
                model=args.agent_model,
                opencode_bin=args.opencode_bin,
                timeout_seconds=args.agent_timeout_seconds,
                max_retries=args.agent_max_retries,
            )
            write_agent_result(agent_review_path, agent_review_result, "agent_review")
            agent_manifest["review"] = result_metadata(agent_review_result, agent_review_path)
            record_step(
                steps,
                StepResult(
                    "agent_review",
                    "opencode Agent 结构化审阅",
                    agent_step_status(agent_review_result.status),
                    agent_review_result.detail,
                    agent_review_result.command,
                ),
                progress,
            )
    else:
        agent_manifest["review"] = None

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

    bundle = build_static_audit_bundle(
        paper_dir=paper_dir,
        paper_pdf=paper_pdf,
        source_data_dir=source_data_dir,
        workdir=workdir,
        case_id=case_id,
        steps=steps,
        agent_manifest=agent_manifest,
    )
    bundle_path = resolve_artifact_path(workdir, "static_audit_bundle.json")
    bundle.write_json(bundle_path)
    record_step(steps, StepResult("static_audit_bundle", "生成 Static Audit Bundle", "ran", str(bundle_path)), progress)

    report_path = generate_report(
        paper_dir=paper_dir,
        paper_pdf=paper_pdf,
        source_data_dir=source_data_dir,
        workdir=workdir,
        case_id=case_id,
        agent_mode=args.agent_mode,
        steps=steps,
    )
    record_step(steps, StepResult("report", "生成最终 Markdown 报告", "ran", str(report_path)), progress)

    manifest = {
        "schema_version": "1.0",
        "created_by": "engine/static_audit/orchestrator.py",
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "case_id": case_id,
        "paper_dir": str(paper_dir),
        "paper_pdf": str(paper_pdf),
        "source_data_dir": str(source_data_dir) if source_data_dir else None,
        "material_inventory": str(material_inventory_path),
        "agent_material_plan": str(agent_material_plan_path),
        "optional_lanes": optional_lanes,
        "workdir": str(workdir),
        "agent": agent_manifest,
        "steps": [asdict(step) for step in steps],
        "static_audit_bundle": str(bundle_path),
        "final_report": str(report_path),
    }
    manifest_path = resolve_artifact_path(workdir, "audit_run_manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    html_report_path = write_static_audit_html(workdir, case_id)
    record_step(steps, StepResult("html_report", "生成最终 HTML 报告", "ran", str(html_report_path)), progress)
    manifest["steps"] = [asdict(step) for step in steps]
    manifest["final_html_report"] = str(html_report_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "case_id": case_id,
        "workdir": str(workdir),
        "final_report": str(report_path),
        "final_html_report": str(html_report_path),
        "run_manifest": str(manifest_path),
        "static_audit_bundle": str(bundle_path),
        "failed_steps": [step.key for step in steps if step.status == "failed"],
    }
    # exit_code = 0 when final reports were generated, even if some non-critical
    # steps failed.  This lets the web runner mark the run as "completed" so the
    # case status reflects "Review Needed" (partial failure) rather than "failed"
    # (crash).  failed_steps is still populated for downstream review.
    report_exists = report_path.exists() and html_report_path.exists()
    summary["exit_code"] = 0 if report_exists else (
        1 if any(step.status == "failed" for step in steps) else 0
    )
    emit_progress(
        progress,
        "audit_end",
        case_id=case_id,
        status="failed" if summary["exit_code"] else "completed",
        failed_steps=summary["failed_steps"],
        final_report=str(report_path),
        final_html_report=str(html_report_path),
    )
    return summary


def _relocate_mineru_outputs(workdir: Path) -> None:
    """Move MinerU outputs from root to layered subdirectories.

    MinerU script outputs to workdir root, but ARTIFACT_PATH_MAP expects:
    - full.md, layout.json, *_manifest.json → mineru/
    - images/ → visual/images/
    """
    mineru_dir = workdir / "mineru"
    mineru_dir.mkdir(parents=True, exist_ok=True)

    # Move MinerU intermediate artifacts to mineru/
    mineru_files = ["full.md", "layout.json", "mineru_manifest.json", "mineru_submission.json", "mineru_result.zip"]
    for filename in mineru_files:
        src = workdir / filename
        dst = mineru_dir / filename
        if src.exists():
            if dst.exists():
                dst.unlink()
            src.rename(dst)

    # Move middle JSON files (if any)
    for middle_json in workdir.glob("*_middle.json"):
        dst = mineru_dir / middle_json.name
        if dst.exists():
            dst.unlink()
        middle_json.rename(dst)

    # Move MinerU hash-prefixed files (content_list, model, origin.pdf)
    for pattern in ("*_content_list.json", "*_content_list_v2.json", "*_model.json", "*_origin.pdf"):
        for src in workdir.glob(pattern):
            dst = mineru_dir / src.name
            if dst.exists():
                dst.unlink()
            src.rename(dst)

    # Move images/ to visual/images/
    images_src = workdir / "images"
    if images_src.exists():
        visual_dir = workdir / "visual"
        visual_dir.mkdir(parents=True, exist_ok=True)
        images_dst = visual_dir / "images"
        if images_dst.exists():
            shutil.rmtree(images_dst)
        images_src.rename(images_dst)

    # Update evidence_ledger.json to use new image paths
    ledger_path = resolve_artifact_path(workdir, "evidence_ledger.json")
    if ledger_path.exists():
        try:
            import json
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            _update_ledger_image_paths(ledger, "images/", "visual/images/")
            ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass  # If update fails, continue without updating


def _update_ledger_image_paths(obj: Any, old_prefix: str, new_prefix: str) -> None:
    """Recursively update image paths in evidence ledger."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ("source_image_path", "relative_path", "path") and isinstance(value, str):
                if value.startswith(old_prefix):
                    obj[key] = new_prefix + value[len(old_prefix):]
            elif isinstance(value, (dict, list)):
                _update_ledger_image_paths(value, old_prefix, new_prefix)
    elif isinstance(obj, list):
        for item in obj:
            _update_ledger_image_paths(item, old_prefix, new_prefix)


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


def main() -> int:
    summary = _run_static_audit_from_args(parse_args())
    exit_code = int(summary.pop("exit_code"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
