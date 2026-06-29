"""Planning stage — agent manifest, material plan, agent plan, source lane resolution.

Corresponds to lines 356-404 of the original pipeline.py ``_run_static_audit_from_args``.
Also contains the material-planning helpers previously defined in pipeline.py.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.investigation.opencode_agent import DEFAULT_SOURCE_FINDING_PARAMS
from engine.static_audit._pipeline_steps import (
    _run_agent_plan_section,
    _run_material_plan_section,
)
from engine.static_audit._shared import (
    ProgressCallback,
    StepResult,
)
from engine.static_audit.materials import fallback_optional_lanes
from engine.tools.registry import (
    PAPER_STATIC_AUDIT_TOOL_IDS,
    STATIC_AUDIT_V1_TOOL_IDS,
)


# ---------------------------------------------------------------------------
# Material planning helpers (moved from pipeline.py)
# ---------------------------------------------------------------------------


def source_finding_params_from_lane(
    lane: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return source-finding params merged from *lane* overrides."""
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


def selected_xlsx_source_lane(
    lanes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the selected XLSX source-data lane, or ``None``."""
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
    """Build a deterministic fallback material plan from *inventory*."""
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
    """Extract optional lanes from *material_plan*, falling back to *inventory*."""
    if material_plan and isinstance(material_plan.get("selected_optional_lanes"), list):
        return [
            i for i in material_plan["selected_optional_lanes"] if isinstance(i, dict)
        ]
    return fallback_optional_lanes(inventory)


def resolve_selected_source_root(
    lane: dict[str, Any] | None, paper_dir: Path
) -> Path | None:
    """Resolve the source-data root from *lane*, constrained to *paper_dir*."""
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
# Stage result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanningResult:
    """Outputs of the planning stage."""

    optional_lanes: list[dict[str, Any]]
    source_lane: dict[str, Any] | None
    source_data_dir: Path | None
    sfp: dict[str, Any]
    agent_manifest: dict[str, Any]
    steps: list[StepResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------


def run(
    args: argparse.Namespace,
    *,
    workdir: Path,
    paper_dir: Path,
    paper_pdf: Path,
    material_inventory: dict[str, Any],
    mi_path: Path,
    env: dict[str, str],
    progress: ProgressCallback | None,
) -> PlanningResult:
    """Build agent manifest, material plan, and agent plan."""
    steps: list[StepResult] = []

    agent_manifest: dict[str, Any] = {
        "mode": args.agent_mode,
        "model": args.agent_model,
        "opencode_bin": args.opencode_bin,
        "tool_registry": "paper_static_audit.v1",
        "registered_tool_ids": list(STATIC_AUDIT_V1_TOOL_IDS),
        "agent_plan_tool_ids": list(PAPER_STATIC_AUDIT_TOOL_IDS),
        "material_inventory": str(mi_path),
        "audit_profile": getattr(args, "audit_profile", "fast"),
        "profile_config": getattr(args, "profile", {}),
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

    return PlanningResult(
        optional_lanes=optional_lanes,
        source_lane=source_lane,
        source_data_dir=source_data_dir,
        sfp=sfp,
        agent_manifest=agent_manifest,
        steps=steps,
    )
