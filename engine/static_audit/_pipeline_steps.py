#!/usr/bin/env python3
"""Step helpers for the static audit pipeline sections.

These are extracted from pipeline.py to keep the main orchestrator under 500 lines.
Each function mutates agent_manifest in-place (where applicable) and returns steps.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT_PATH = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))

from engine.static_audit._shared import (
    AUDITOR_ROOT,
    PROJECT_ROOT,
    ProgressCallback,
    StepResult,
    emit_progress,
    emit_step_start,
    existing_artifact_path,
    read_json,
    record_step,
    resolve_artifact_path,
    run_command,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MinerU output relocation (used by _run_mineru_forensics_section)
# ---------------------------------------------------------------------------


def _relocate_mineru_outputs(workdir: Path) -> None:
    mineru_dir = workdir / "mineru"
    mineru_dir.mkdir(parents=True, exist_ok=True)
    for f in (
        "full.md",
        "layout.json",
        "mineru_manifest.json",
        "mineru_submission.json",
        "mineru_result.zip",
    ):
        src, dst = workdir / f, mineru_dir / f
        if src.exists():
            if dst.exists():
                dst.unlink()
            src.rename(dst)
    for mj in workdir.glob("*_middle.json"):
        dst = mineru_dir / mj.name
        if dst.exists():
            dst.unlink()
        mj.rename(dst)
    for pat in (
        "*_content_list.json",
        "*_content_list_v2.json",
        "*_model.json",
        "*_origin.pdf",
    ):
        for src in workdir.glob(pat):
            dst = mineru_dir / src.name
            if dst.exists():
                dst.unlink()
            src.rename(dst)
    images_src = workdir / "images"
    if images_src.exists():
        visual_dir = workdir / "visual"
        visual_dir.mkdir(parents=True, exist_ok=True)
        images_dst = visual_dir / "images"
        if images_dst.exists():
            shutil.rmtree(images_dst)
        images_src.rename(images_dst)
    ledger_path = resolve_artifact_path(workdir, "evidence_ledger.json")
    if ledger_path.exists():
        try:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            _update_ledger_image_paths(ledger, "images/", "visual/images/")
            ledger_path.write_text(
                json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.warning("Ledger image path update failed (non-critical)", exc_info=True)


def _update_ledger_image_paths(obj: Any, old: str, new: str) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if (
                k in ("source_image_path", "relative_path", "path")
                and isinstance(v, str)
                and v.startswith(old)
            ):
                obj[k] = new + v[len(old) :]
            elif isinstance(v, (dict, list)):
                _update_ledger_image_paths(v, old, new)
    elif isinstance(obj, list):
        for item in obj:
            _update_ledger_image_paths(item, old, new)


# ---------------------------------------------------------------------------
# Source data tool steps
# ---------------------------------------------------------------------------


def _run_source_data_steps(
    *,
    workdir: Path,
    source_data_dir: Path,
    source_finding_params: dict[str, Any],
    env: dict[str, str],
    args: argparse.Namespace,
    progress: ProgressCallback | None,
) -> list[StepResult]:
    """Run source_data_profile, findings, pair_forensics, cross_sheet, paperconan, verdict."""
    steps: list[StepResult] = []
    profile_out = resolve_artifact_path(workdir, "source_data_profile.json")
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
                str(profile_out),
            ],
            [profile_out],
            cwd=PROJECT_ROOT,
            env=env,
            force=args.force,
            progress=progress,
        )
    )
    if not profile_out.exists():
        for k, t in [
            ("source_data_findings", "Source Data findings"),
            ("source_data_pair_forensics", "Source Data pair forensics"),
            ("source_data_cross_sheet", "Source Data cross-sheet duplicates"),
            ("source_data_verdict", "Source Data LLM 语义裁决"),
        ]:
            steps.append(
                StepResult(k, t, "skipped", "source_data_profile.json missing.")
            )
        return steps

    # source_data_findings
    cmd = [
        sys.executable,
        "-m",
        "engine.static_audit.tools.source_data_findings",
        str(source_data_dir),
        "--profile",
        str(profile_out),
        "--output",
        str(resolve_artifact_path(workdir, "source_data_findings.json")),
        "--min-overlap",
        str(source_finding_params["min_overlap"]),
        "--min-support",
        str(source_finding_params["min_support"]),
        "--max-findings-per-category",
        str(source_finding_params["max_findings_per_category"]),
    ]
    full_md = existing_artifact_path(workdir, "full.md")
    if full_md is not None:
        cmd.extend(["--full-md", str(full_md)])
    steps.append(
        run_command(
            "source_data_findings",
            "Source Data findings",
            cmd,
            [resolve_artifact_path(workdir, "source_data_findings.json")],
            cwd=PROJECT_ROOT,
            env=env,
            force=args.force,
            progress=progress,
        )
    )
    # pair forensics
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
    # cross-sheet
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
    # Cross-sheet LLM filter (metadata column removal)
    cross_sheet_path = resolve_artifact_path(workdir, "source_data_cross_sheet.json")
    if cross_sheet_path.exists():
        emit_step_start(progress, "cross_sheet_filter", "Cross-sheet LLM metadata filter")
        try:
            from engine.llm.client import VeritasLLMClient
            from engine.static_audit._shared import run_cross_sheet_filter

            cross_sheet_data = json.loads(cross_sheet_path.read_text(encoding="utf-8"))
            findings = cross_sheet_data.get("findings", cross_sheet_data.get("cross_sheet_findings", []))

            if findings:
                llm_client = VeritasLLMClient()
                filtered_findings = run_cross_sheet_filter(workdir, findings, llm_client)

                # Write filtered findings back
                cross_sheet_data["findings"] = filtered_findings
                cross_sheet_data["filter_metadata"] = {
                    "original_count": len(findings),
                    "filtered_count": len(filtered_findings),
                    "filter_applied": True,
                }
                cross_sheet_path.write_text(
                    json.dumps(cross_sheet_data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                filter_status = "ran"
                filter_detail = f"filtered={len(findings) - len(filtered_findings)}"
            else:
                filter_status = "skipped"
                filter_detail = "no findings to filter"
        except Exception as e:
            logger.warning("cross_sheet_filter failed: %s", e)
            filter_status = "warning"
            filter_detail = f"filter failed: {e}"
        steps.append(StepResult("cross_sheet_filter", "Cross-sheet LLM metadata filter", filter_status, filter_detail))
    else:
        steps.append(StepResult("cross_sheet_filter", "Cross-sheet LLM metadata filter", "skipped", "cross_sheet.json missing"))
    # paperconan GRIM/GRIMMER scan
    num_dir = resolve_artifact_path(workdir, "numeric")
    steps.append(
        run_command(
            "paperconan_scan",
            "Paperconan GRIM/GRIMMER scan",
            [
                sys.executable,
                "-c",
                f"import json\n"
                f"from pathlib import Path\n"
                f"from engine.static_audit.adapters.paperconan_adapter import run_paperconan_scan\n"
                f"r = run_paperconan_scan(source_data_dir=Path({str(source_data_dir)!r}), "
                f"output_dir=Path({str(num_dir)!r}), profile='review')\n"
                f"print(json.dumps({{'status': r['status'], 'findings': r['findings_summary']}}))",
            ],
            [resolve_artifact_path(workdir, "numeric/paperconan_scan.json")],
            cwd=PROJECT_ROOT,
            env=env,
            force=args.force,
            progress=progress,
        )
    )
    # Sheet briefings — compact structural intelligence for Agent context
    emit_step_start(progress, "source_data_briefings", "Source Data sheet briefings")
    try:
        from engine.static_audit.tools.source_data_sheet_briefing import (
            build_all_briefings,
        )

        sd_findings = resolve_artifact_path(workdir, "source_data_findings.json")
        sd_pf = resolve_artifact_path(workdir, "source_data_pair_forensics.json")
        findings_data = (
            json.loads(sd_findings.read_text(encoding="utf-8"))
            if sd_findings.exists()
            else None
        )
        pf_data = (
            json.loads(sd_pf.read_text(encoding="utf-8")) if sd_pf.exists() else None
        )
        briefings = build_all_briefings(findings_data, pf_data, source_data_dir)
        briefings_path = resolve_artifact_path(
            workdir, "source_data_sheet_briefings.json"
        )
        briefings_path.parent.mkdir(parents=True, exist_ok=True)
        briefings_path.write_text(
            json.dumps(briefings, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        bs = briefings.get("sheet_count", 0)
        bst, bsd = "ran", f"sheets={bs}"
    except Exception as e:
        bst, bsd = "warning", f"briefings step exception: {e}"
        logger.warning("source_data_briefings failed: %s", e)
    steps.append(
        StepResult("source_data_briefings", "Source Data sheet briefings", bst, bsd)
    )
    # LLM verdict
    emit_step_start(progress, "source_data_verdict", "Source Data LLM 语义裁决")
    try:
        from engine.static_audit.tools.source_data_verdict import (
            run_source_data_verdict,
        )

        vr = run_source_data_verdict(
            workdir,
            source_data_dir=source_data_dir,
            project_root=PROJECT_ROOT,
            env=env,
            model=args.agent_model,
            opencode_bin=args.opencode_bin,
            force=args.force,
            progress=progress,
        )
        vs = vr.get("summary", {})
        vd = (
            f"sheets={vs.get('total_sheets', 0)} TP={vs.get('true_positive', 0)} "
            f"FP={vs.get('false_positive', 0)} uncertain={vs.get('uncertain', 0)}"
        )
        vst = "ran" if vs.get("total_sheets", 0) > 0 else "skipped"
        if vs.get("failed_sheets", 0) > 0:
            vst, vd = "warning", vd + f" failed_sheets={vs['failed_sheets']}"
    except Exception as e:
        vst, vd = "warning", f"verdict step exception: {e}"
        logger.warning("source_data_verdict failed: %s", e)
    steps.append(StepResult("source_data_verdict", "Source Data LLM 语义裁决", vst, vd))
    return steps


# ---------------------------------------------------------------------------
# Investigation deterministic fallbacks
# ---------------------------------------------------------------------------


def _run_investigation_fallbacks(
    *,
    workdir: Path,
    images_dir: Path,
    investigation_manifest: dict[str, Any],
    env: dict[str, str],
    args: argparse.Namespace,
    progress: ProgressCallback | None,
    figure_classification: dict[str, Any] | None = None,
) -> list[StepResult]:
    """Run deterministic fallback for Agent-selectable investigation tools.

    If figure_classification is provided, copy_move fallback will only process
    wet_lab panels, reducing computation on code-generated visualizations.
    """
    steps: list[StepResult] = []
    inv_dir = resolve_artifact_path(workdir, "investigation")
    sim_outs = (
        sorted(inv_dir.rglob("image_similarity_candidates.json"))
        if inv_dir.exists()
        else []
    )
    cm_outs = sorted(inv_dir.rglob("visual_copy_move.json")) if inv_dir.exists() else []
    planner_failed = (
        not investigation_manifest.get("enabled", True)
        or investigation_manifest.get("stop_reason") == "planner_failed"
    )
    pe_path = resolve_artifact_path(workdir, "panel_evidence.json")
    fb = inv_dir / "fallback"

    # image_similarity_candidates
    if sim_outs:
        steps.append(
            StepResult(
                "image_similarity_candidates",
                "图片近似相似候选检查",
                "ran",
                "image.similarity_candidates output was produced by AgentInvestigationPlanner.",
            )
        )
    elif planner_failed and images_dir.is_dir():
        fb.mkdir(parents=True, exist_ok=True)
        out = fb / "image_similarity_candidates.json"
        cmd = [
            sys.executable,
            "-m",
            "engine.static_audit.tools.image_similarity",
            str(images_dir),
            "--output",
            str(out),
            "--max-distance",
            "8",
            "--max-candidates",
            "200",
        ]
        if pe_path.exists():
            cmd.extend(["--panel-evidence", str(pe_path)])
        steps.append(
            run_command(
                "image_similarity_candidates",
                "图片近似相似候选检查（确定性回退）",
                cmd,
                [out],
                cwd=PROJECT_ROOT,
                env=env,
                force=args.force,
                progress=progress,
            )
        )
        if steps[-1].status == "ran":
            steps[
                -1
            ].detail = (
                "Ran as deterministic fallback: Agent investigation planner failed."
            )
    elif not images_dir.is_dir():
        steps.append(
            StepResult(
                "image_similarity_candidates",
                "图片近似相似候选检查",
                "skipped",
                "images directory missing.",
            )
        )
    else:
        steps.append(
            StepResult(
                "image_similarity_candidates",
                "图片近似相似候选检查",
                "skipped",
                "AgentInvestigationPlanner did not select image.similarity_candidates for this run.",
            )
        )

    # visual_copy_move
    if cm_outs:
        steps.append(
            StepResult(
                "visual_copy_move",
                "图片 Copy-Move 检测",
                "ran",
                "visual.copy_move output was produced by AgentInvestigationPlanner.",
            )
        )
    elif planner_failed and pe_path.exists():
        fb.mkdir(parents=True, exist_ok=True)
        out = fb / "visual_copy_move.json"

        # If figure_classification is available, filter panels to wet_lab only
        filtered_pe_path = pe_path
        if figure_classification:
            from engine.static_audit._shared import WET_LAB_TYPES, read_json
            import json

            panel_data = read_json(pe_path) or {}
            all_panels = panel_data.get("panels", [])
            filtered_panels = [
                p for p in all_panels
                if isinstance(p, dict) and (
                    p.get("panel_classification") in WET_LAB_TYPES
                    or p.get("panel_classification") == "unknown"
                )
            ]
            if len(filtered_panels) < len(all_panels):
                filtered_panel_data = {**panel_data, "panels": filtered_panels}
                filtered_pe_path = fb / "panel_evidence_wetlab.json"
                filtered_pe_path.write_text(
                    json.dumps(filtered_panel_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(
                    "Copy-move fallback: filtered %d panels -> %d wet_lab panels",
                    len(all_panels),
                    len(filtered_panels),
                )

        steps.append(
            run_command(
                "visual_copy_move",
                "图片 Copy-Move 检测（确定性回退）",
                [
                    sys.executable,
                    "-m",
                    "engine.static_audit.tools.copy_move_detection",
                    str(filtered_pe_path),
                    "--figure-json",
                    str(resolve_artifact_path(workdir, "visual_evidence.json")),
                    "--output",
                    str(out),
                    "--workdir",
                    str(workdir),
                    "--method",
                    "rootsift_magsac",
                    "--min-matches",
                    "20",
                    "--min-score",
                    "0.05",
                    "--max-relationships",
                    "500",
                ],
                [out],
                cwd=PROJECT_ROOT,
                env=env,
                force=args.force,
                progress=progress,
            )
        )
        if steps[-1].status == "ran":
            steps[
                -1
            ].detail = (
                "Ran as deterministic fallback: Agent investigation planner failed."
            )
    elif not pe_path.exists():
        steps.append(
            StepResult(
                "visual_copy_move",
                "图片 Copy-Move 检测",
                "skipped",
                "panel_evidence.json missing.",
            )
        )
    else:
        steps.append(
            StepResult(
                "visual_copy_move",
                "图片 Copy-Move 检测",
                "skipped",
                "AgentInvestigationPlanner did not select visual.copy_move for this run.",
            )
        )
    return steps


# ---------------------------------------------------------------------------
# Phase helpers (extracted from pipeline.py to keep it < 500 lines)
# ---------------------------------------------------------------------------


def _run_material_plan_section(
    *,
    args: argparse.Namespace,
    workdir: Path,
    paper_dir: Path,
    paper_pdf: Path,
    material_inventory: dict[str, Any],
    env: dict[str, str],
    agent_manifest: dict[str, Any],
    progress: ProgressCallback | None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Run agent material plan step. Returns (steps, material_plan)."""
    from engine.investigation.opencode_agent import (
        result_metadata,
        run_agent_material_plan,
        write_agent_result,
    )
    from engine.static_audit._shared import agent_step_status
    from engine.static_audit.pipeline import material_plan_from_inventory

    steps: list[StepResult] = []
    amp_path = resolve_artifact_path(workdir, "agent_material_plan.json")
    case_id = args.case_id or paper_dir.name
    if amp_path.exists() and not args.force:
        material_plan = read_json(amp_path) or material_plan_from_inventory(
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
            "output": str(amp_path),
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
    else:
        emit_step_start(
            progress,
            "agent_material_plan",
            "opencode Agent 材料计划",
            "Calling opencode to select optional material lanes.",
        )
        result = run_agent_material_plan(
            case_id=case_id,
            workdir=workdir,
            project_root=PROJECT_ROOT,
            env=env,
            model=args.agent_model,
            opencode_bin=args.opencode_bin,
            timeout_seconds=args.agent_timeout_seconds,
            max_retries=args.agent_max_retries,
        )
        if result.data:
            material_plan = result.data
            write_agent_result(amp_path, result, "material_plan")
        else:
            material_plan = material_plan_from_inventory(
                case_id=case_id,
                inventory=material_inventory,
                status="fallback",
                detail=f"Agent material plan failed; deterministic fallback used. {result.detail}",
            )
            amp_path.write_text(
                json.dumps(material_plan, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        agent_manifest["material_plan"] = result_metadata(result, amp_path)
        record_step(
            steps,
            StepResult(
                "agent_material_plan",
                "opencode Agent 材料计划",
                agent_step_status(result.status),
                result.detail,
                result.command,
            ),
            progress,
        )
    return steps, material_plan


def _run_agent_plan_section(
    *,
    args: argparse.Namespace,
    workdir: Path,
    paper_pdf: Path,
    source_data_dir: Path | None,
    source_finding_params: dict[str, Any],
    env: dict[str, str],
    agent_manifest: dict[str, Any],
    progress: ProgressCallback | None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Run agent audit plan step. Returns (steps, updated_source_finding_params)."""
    from engine.investigation.opencode_agent import (
        result_metadata,
        run_agent_plan,
        write_agent_result,
    )
    from engine.static_audit._shared import (
        agent_step_status,
        source_finding_params_from_plan,
    )
    from engine.tools.registry import (
        PAPER_STATIC_AUDIT_TOOL_IDS,
        selected_tool_ids_from_plan,
    )

    steps: list[StepResult] = []
    if args.agent_mode in {"plan", "full"}:
        ap_path = resolve_artifact_path(workdir, "agent_audit_plan.json")
        emit_step_start(
            progress,
            "agent_plan",
            "opencode Agent 审查计划",
            "Calling opencode to fill deterministic tool parameters.",
        )
        result = run_agent_plan(
            case_id=args.case_id or Path(args.paper_dir).name,
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
        write_agent_result(ap_path, result, "audit_plan")
        agent_manifest["plan"] = result_metadata(result, ap_path)
        agent_manifest["selected_tool_ids"] = selected_tool_ids_from_plan(result.data)
        record_step(
            steps,
            StepResult(
                "agent_plan",
                "opencode Agent 审查计划",
                agent_step_status(result.status),
                result.detail,
                result.command,
            ),
            progress,
        )
        if result.data:
            source_finding_params = source_finding_params_from_plan(result.data)
    else:
        agent_manifest["plan"] = None
        agent_manifest["selected_tool_ids"] = list(PAPER_STATIC_AUDIT_TOOL_IDS)
    return steps, source_finding_params


def _run_mineru_forensics_section(
    *,
    args: argparse.Namespace,
    workdir: Path,
    paper_pdf: Path,
    env: dict[str, str],
    progress: ProgressCallback | None,
) -> tuple[list[StepResult], bool]:
    """Run MinerU, evidence ledger, numeric forensics, and PaperFraud rule matching."""
    from engine.static_audit.tools.paperfraud_rules import run_paperfraud_rule_match

    steps: list[StepResult] = []
    mineru_outputs = [
        existing_artifact_path(workdir, k)
        for k in ("full.md", "mineru_manifest.json", "images")
    ]
    if all(mineru_outputs) and not args.force:
        record_step(
            steps,
            StepResult(
                "mineru", "MinerU PDF 解析", "reused", "Existing MinerU outputs found."
            ),
            progress,
        )
    elif not env.get("MINERU_API_TOKEN"):
        record_step(
            steps,
            StepResult(
                "mineru",
                "MinerU PDF 解析",
                "skipped",
                "MINERU_API_TOKEN is missing; cannot run MinerU from scratch.",
            ),
            progress,
        )
    else:
        mineru_root = [
            workdir / "full.md",
            workdir / "mineru_manifest.json",
            workdir / "images",
        ]
        steps.append(
            run_command(
                "mineru",
                "MinerU PDF 解析",
                [
                    sys.executable,
                    "scripts/mineru_convert.py",
                    str(paper_pdf),
                    "--output",
                    str(workdir),
                ],
                mineru_root,
                cwd=AUDITOR_ROOT,
                env=env,
                force=args.force,
                attempts=3,
                retry_delay_seconds=10,
                progress=progress,
                stream_output=True,
            )
        )
    full_md = existing_artifact_path(workdir, "full.md")
    if full_md is not None:
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
        _relocate_mineru_outputs(workdir)
        full_md = existing_artifact_path(workdir, "full.md")
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
        pf_out = resolve_artifact_path(workdir, "paperfraud_rule_matches.json")
        if pf_out.exists() and not args.force:
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
            run_paperfraud_rule_match(
                full_md or resolve_artifact_path(workdir, "full.md"), pf_out
            )
            record_step(
                steps,
                StepResult(
                    "paperfraud_rule_match", "PaperFraud 规则库匹配", "ran", str(pf_out)
                ),
                progress,
            )
    else:
        for key, title in [
            ("evidence_ledger", "构建 evidence ledger"),
            ("numeric_forensics", "PDF 数字取证"),
            ("paperfraud_rule_match", "PaperFraud 规则库匹配"),
        ]:
            record_step(
                steps, StepResult(key, title, "skipped", "full.md missing."), progress
            )
    return steps, existing_artifact_path(workdir, "full.md") is not None


def _run_agent_review_section(
    *,
    args: argparse.Namespace,
    workdir: Path,
    env: dict[str, str],
    agent_manifest: dict[str, Any],
    progress: ProgressCallback | None,
) -> list[StepResult]:
    from engine.investigation.opencode_agent import (
        result_metadata,
        run_agent_review,
        write_agent_result,
    )
    from engine.static_audit._shared import agent_step_status

    steps: list[StepResult] = []
    if args.agent_mode in {"review", "full"}:
        p = resolve_artifact_path(workdir, "agent_review.json")
        if p.exists() and not args.force:
            agent_manifest["review"] = {
                "status": "reused",
                "detail": "Existing agent_review.json found.",
                "runtime_seconds": None,
                "retries": 0,
                "command": [],
                "output": str(p),
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
            result = run_agent_review(
                case_id=args.case_id or Path(args.paper_dir).name,
                workdir=workdir,
                project_root=PROJECT_ROOT,
                env=env,
                model=args.agent_model,
                opencode_bin=args.opencode_bin,
                timeout_seconds=args.agent_timeout_seconds,
                max_retries=args.agent_max_retries,
            )
            write_agent_result(p, result, "agent_review")
            agent_manifest["review"] = result_metadata(result, p)
            record_step(
                steps,
                StepResult(
                    "agent_review",
                    "opencode Agent 结构化审阅",
                    agent_step_status(result.status),
                    result.detail,
                    result.command,
                ),
                progress,
            )
    else:
        agent_manifest["review"] = None
    return steps


def _run_bundle_and_report(
    *,
    paper_dir: Path,
    paper_pdf: Path,
    source_data_dir: Path | None,
    workdir: Path,
    case_id: str,
    agent_mode: str,
    steps: list[StepResult],
    agent_manifest: dict[str, Any],
    material_inventory_path: Path,
    agent_material_plan_path: Path,
    optional_lanes: list[dict[str, Any]],
    progress: ProgressCallback | None,
) -> dict[str, Any]:
    """Build bundle, markdown report, HTML report, manifest. Returns summary dict."""
    from dataclasses import asdict
    from datetime import UTC, datetime
    from engine.static_audit.html_report import write_static_audit_html
    from engine.static_audit.report import build_static_audit_bundle, generate_report

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
    record_step(
        steps,
        StepResult(
            "static_audit_bundle", "生成 Static Audit Bundle", "ran", str(bundle_path)
        ),
        progress,
    )

    # LLM text enrichment: generate data-grounded review text for top findings
    try:
        from engine.llm.client import VeritasLLMClient
        from engine.reporting.text_generator import enrich_bundle_with_llm_text

        llm_client = VeritasLLMClient()
        bundle = enrich_bundle_with_llm_text(bundle, workdir, llm_client, max_findings=10)
        bundle.write_json(bundle_path)  # re-write with enriched text
        logger.info("LLM text enrichment completed for bundle %s", case_id)
    except Exception as e:
        logger.warning("LLM text enrichment skipped: %s", e)

    # Certification grade (after bundle, before reports)
    emit_step_start(progress, "certification_grade", "认证评级计算")
    grade_data = None
    try:
        from engine.static_audit.grade_engine import compute_grade

        grade = compute_grade(bundle)
        grade_data = asdict(grade)
        grade_path = resolve_artifact_path(workdir, "certification_grade.json")
        grade_path.parent.mkdir(parents=True, exist_ok=True)
        grade_path.write_text(
            json.dumps(grade_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        record_step(
            steps,
            StepResult(
                "certification_grade",
                "认证评级计算",
                "ran",
                f"grade={grade_data.get('grade', '?')}",
            ),
            progress,
        )
    except Exception as e:
        logger.warning("certification_grade failed: %s", e)
        record_step(
            steps,
            StepResult(
                "certification_grade",
                "认证评级计算",
                "warning",
                f"grade computation failed: {e}",
            ),
            progress,
        )

    # Certainty layer enrichment (fact/inference/suggestion per finding)
    emit_step_start(progress, "certainty_enrichment", "确定性分层")
    try:
        from engine.static_audit.certainty_enrichment import save_certainty_data

        certainty_path = save_certainty_data(bundle, workdir)
        record_step(
            steps,
            StepResult(
                "certainty_enrichment",
                "确定性分层",
                "ran",
                f"enriched {len(bundle.findings)} findings → {certainty_path.name}",
            ),
            progress,
        )
    except Exception as e:
        logger.warning("certainty_enrichment failed: %s", e)
        record_step(
            steps,
            StepResult(
                "certainty_enrichment",
                "确定性分层",
                "warning",
                f"enrichment failed: {e}",
            ),
            progress,
        )

    report_path = generate_report(
        paper_dir=paper_dir,
        paper_pdf=paper_pdf,
        source_data_dir=source_data_dir,
        workdir=workdir,
        case_id=case_id,
        agent_mode=agent_mode,
        steps=steps,
    )
    record_step(
        steps,
        StepResult("report", "生成最终 Markdown 报告", "ran", str(report_path)),
        progress,
    )

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
        "steps": [asdict(s) for s in steps],
        "static_audit_bundle": str(bundle_path),
        "final_report": str(report_path),
    }
    manifest_path = resolve_artifact_path(workdir, "audit_run_manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Generate report_id before HTML rendering so it can be embedded in the hero
    report_id = None
    if grade_data:
        try:
            from engine.static_audit.report_id import generate_report_id

            report_id = generate_report_id()
        except Exception as e:
            logger.warning("Report ID generation failed: %s", e)

    html_path = write_static_audit_html(
        workdir,
        case_id,
        grade=grade_data,
        dimensions=grade_data.get("dimensions") if grade_data else None,
        report_id=report_id,
    )
    record_step(
        steps,
        StepResult("html_report", "生成最终 HTML 报告", "ran", str(html_path)),
        progress,
    )
    manifest["steps"] = [asdict(s) for s in steps]
    manifest["final_html_report"] = str(html_path)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Public verification: save verification summary
    if report_id and grade_data:
        try:
            from engine.static_audit.verify_store import save_verification_summary

            save_verification_summary(
                case_id=case_id,
                report_id=report_id,
                paper_title=case_id,  # Use case_id as title for now
                grade_data=grade_data,
            )
            logger.info("Public verification enabled: %s", report_id)
        except Exception as e:
            logger.warning("Verification summary save failed: %s", e)

    failed = [s.key for s in steps if s.status == "failed"]
    exit_code = (
        0
        if (report_path.exists() and html_path.exists())
        else (1 if any(s.status == "failed" for s in steps) else 0)
    )
    emit_progress(
        progress,
        "audit_end",
        case_id=case_id,
        status="failed" if exit_code else "completed",
        failed_steps=failed,
        final_report=str(report_path),
        final_html_report=str(html_path),
    )
    return {
        "case_id": case_id,
        "workdir": str(workdir),
        "final_report": str(report_path),
        "final_html_report": str(html_path),
        "run_manifest": str(manifest_path),
        "static_audit_bundle": str(bundle_path),
        "failed_steps": failed,
        "exit_code": exit_code,
        "report_id": report_id,
    }
