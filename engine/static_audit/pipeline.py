#!/usr/bin/env python3
"""Core static audit pipeline orchestration.

Owns the end-to-end flow: material planning, deterministic tool execution,
Agent investigation rounds, visual forensics baseline, report generation.

The heavy lifting is delegated to domain-specific stage modules under
``engine.static_audit.stages``.  This file keeps:

* The public API (``run_static_audit``).
* The private orchestrator (``_run_static_audit_from_args``).
* Audit-profile constants and resolution.
* Backward-compatible re-exports of helpers that were physically moved to
  ``stages/planning.py``.
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
    ProgressCallback,
    StepResult,
    record_step,
    resolve_artifact_path,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit profiles — three preset configurations controlling pipeline depth.
#
# fast:     Web default. Minimal agent rounds, short ELIS timeout, no LLM
#           enrichment. Suitable for quick triage.
# standard: Balanced. Moderate agent rounds and timeouts.
# full:     CLI default. Maximum agent rounds, long timeouts, full LLM
#           enrichment. Suitable for thorough pre-submission review.
# ---------------------------------------------------------------------------

AUDIT_PROFILES: dict[str, dict[str, Any]] = {
    "fast": {
        "agent_timeout_seconds": 120,
        "agent_max_retries": 0,
        "agent_max_rounds": 2,
        "agent_max_actions_per_round": 5,
        "elis_timeout_seconds": 60,
        "llm_enrichment": False,
        "investigation_rounds": 1,
    },
    "standard": {
        "agent_timeout_seconds": 300,
        "agent_max_retries": 1,
        "agent_max_rounds": 5,
        "agent_max_actions_per_round": 10,
        "elis_timeout_seconds": 180,
        "llm_enrichment": True,
        "investigation_rounds": 3,
    },
    "full": {
        "agent_timeout_seconds": 600,
        "agent_max_retries": 2,
        "agent_max_rounds": 10,
        "agent_max_actions_per_round": 20,
        "elis_timeout_seconds": 300,
        "llm_enrichment": True,
        "investigation_rounds": 5,
    },
}


def resolve_audit_profile(
    profile_name: str | None,
) -> dict[str, Any]:
    """Return the profile dict for *profile_name*, defaulting to 'fast'.

    Unknown names raise ValueError with the valid choices listed.
    """
    if not profile_name:
        profile_name = "fast"
    if profile_name not in AUDIT_PROFILES:
        valid = ", ".join(sorted(AUDIT_PROFILES))
        raise ValueError(f"Unknown audit profile {profile_name!r}. Valid: {valid}")
    return dict(AUDIT_PROFILES[profile_name])


# ---------------------------------------------------------------------------
# Backward-compatible re-exports — helpers moved to stages/planning.py.
# ---------------------------------------------------------------------------

from engine.static_audit.stages.planning import (  # noqa: E402
    material_plan_from_inventory,
    optional_lanes_from_material_plan,
    resolve_selected_source_root,
    selected_xlsx_source_lane,
    source_finding_params_from_lane,
)

__all__ = [
    "run_static_audit",
    "resolve_audit_profile",
    "AUDIT_PROFILES",
    # Backward-compat re-exports
    "material_plan_from_inventory",
    "optional_lanes_from_material_plan",
    "resolve_selected_source_root",
    "selected_xlsx_source_lane",
    "source_finding_params_from_lane",
]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _run_static_audit_from_args(
    args: argparse.Namespace,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Execute the full static-audit pipeline."""
    from engine.static_audit.stages import (
        discovery,
        investigation,
        mineru,
        planning,
        report,
        roles,
        source_data,
        visual,
    )

    # --- Phase 1: Discovery -----------------------------------------------
    d = discovery.run(args, progress)
    steps: list[StepResult] = list(d.steps)

    # --- Phase 2: Planning ------------------------------------------------
    p = planning.run(
        args,
        workdir=d.workdir,
        paper_dir=d.paper_dir,
        paper_pdf=d.paper_pdf,
        material_inventory=d.material_inventory,
        mi_path=d.mi_path,
        env=d.env,
        progress=progress,
    )
    steps.extend(p.steps)

    # --- Phase 3: MinerU + forensics --------------------------------------
    m = mineru.run(
        args,
        workdir=d.workdir,
        paper_pdf=d.paper_pdf,
        env=d.env,
        progress=progress,
    )
    steps.extend(m.steps)

    if not m.mineru_ok:
        # Early termination: MinerU is the foundation of the audit pipeline.
        # Without full.md, every downstream step either fails silently or
        # produces high-false-positive noise.  Fail fast.
        _MINERU_FAIL_REASON = (
            "MinerU PDF 解析失败（full.md 未生成）。"
            "无论文全文上下文，后续步骤终止——"
            "请检查 MINERU_API_TOKEN 是否配置、PDF 是否损坏，或重试。"
        )
        for key, title in [
            ("source_data_profile", "Source Data profile"),
            ("source_data_findings", "Source Data findings"),
            ("source_data_pair_forensics", "Source Data pair forensics"),
            ("source_data_cross_sheet", "Source Data cross-sheet duplicates"),
            ("source_data_verdict", "Source Data LLM 语义裁决"),
            ("exact_image_duplicates", "图片字节级重复检查"),
            ("image_similarity_candidates", "图片近似相似候选检查"),
            ("panel_extraction", "Panel 提取 (YOLOv5)"),
            ("visual_copy_move", "Copy-Move 检测 (RootSIFT)"),
            ("visual_copy_move_dense", "密集 Copy-Move 检测 (SILA)"),
            ("visual_trufor", "TruFor 伪造检测"),
            ("visual_overlap_reuse", "图像复用检测"),
            ("investigation", "Agent 调查轮次"),
            ("investigation_fallback", "调查 fallback 工具"),
            ("agent_review", "Agent 结构化复核"),
            ("agent_roles", "Agent 角色层 (Claim/SourceData/Judge)"),
            ("bundle", "产物打包与报告生成"),
        ]:
            record_step(
                steps, StepResult(key, title, "failed", _MINERU_FAIL_REASON), progress
            )
        # Jump to bundle + report so the user gets a visible failure record.
        return report.run(
            args,
            workdir=d.workdir,
            paper_dir=d.paper_dir,
            paper_pdf=d.paper_pdf,
            source_data_dir=p.source_data_dir,
            case_id=d.case_id,
            steps=steps,
            agent_manifest=p.agent_manifest,
            mi_path=d.mi_path,
            optional_lanes=p.optional_lanes,
            progress=progress,
        )

    # --- Phase 4: Source data ---------------------------------------------
    sd = source_data.run(
        args,
        workdir=d.workdir,
        source_lane=p.source_lane,
        source_data_dir=p.source_data_dir,
        sfp=p.sfp,
        env=d.env,
        progress=progress,
    )
    steps.extend(sd.steps)

    # --- Phase 5: Visual --------------------------------------------------
    images_dir = resolve_artifact_path(d.workdir, "images")
    v = visual.run(
        args,
        workdir=d.workdir,
        images_dir=images_dir,
        env=d.env,
        agent_manifest=p.agent_manifest,
        progress=progress,
    )
    steps.extend(v.steps)

    # --- Phase 6: Investigation -------------------------------------------
    inv = investigation.run(
        args,
        workdir=d.workdir,
        case_id=d.case_id,
        source_data_dir=p.source_data_dir,
        images_dir=images_dir,
        env=d.env,
        agent_manifest=p.agent_manifest,
        fc_manifest_data=v.figure_classification,
        progress=progress,
    )
    steps.extend(inv.steps)

    # --- Phase 7: Roles ---------------------------------------------------
    r = roles.run(
        args,
        workdir=d.workdir,
        case_id=d.case_id,
        env=d.env,
        agent_manifest=p.agent_manifest,
        progress=progress,
    )
    steps.extend(r.steps)

    # --- Phase 8: Report --------------------------------------------------
    return report.run(
        args,
        workdir=d.workdir,
        paper_dir=d.paper_dir,
        paper_pdf=d.paper_pdf,
        source_data_dir=p.source_data_dir,
        case_id=d.case_id,
        steps=steps,
        agent_manifest=p.agent_manifest,
        mi_path=d.mi_path,
        optional_lanes=p.optional_lanes,
        progress=progress,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
    reproducibility_tier: str = "full",
    skip_unavailable_tools: bool = False,
    audit_profile: str = "fast",
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    profile = resolve_audit_profile(audit_profile)
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
        reproducibility_tier=reproducibility_tier,
        skip_unavailable_tools=skip_unavailable_tools,
        audit_profile=audit_profile,
        profile=profile,
    )
    return _run_static_audit_from_args(args, progress=progress)
