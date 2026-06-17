from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.investigation.context_pack import (
    build_material_inventory_context_pack,
    build_review_context_pack,
)
from engine.investigation.validators import (
    _coerce_material_source_params,
    _require,
)
from engine.investigation._shared import (
    AgentRunResult,
    _artifact_summary,
    _claims_from_mappings,
    _read_json,
    _review_mappings,
    _run_with_context_pack,
)


def fake_review(
    *,
    case_id: str,
    workdir: Path,
) -> dict[str, Any]:
    findings = _read_json(workdir / "source_data_findings.json") or {}
    priority = findings.get("priority_findings") or []
    mappings = findings.get("claim_to_source_data") or []
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "candidate_claims": _claims_from_mappings(mappings),
        "claim_to_source_data": _review_mappings(mappings),
        "finding_reviews": [
            {
                "finding_id": item.get("finding_id"),
                "assessment": "manual_review_required",
                "benign_explanations": item.get("benign_explanations", []),
                "residual_risk": item.get("risk_level", "medium"),
                "evidence_refs": {
                    "workbook": item.get("workbook"),
                    "sheet": item.get("sheet"),
                    "columns": item.get("column_pair"),
                },
            }
            for item in priority
        ],
        "manual_review_tasks": [
            {
                "task_id": f"MR-{idx:03d}",
                "priority": "high",
                "question": f"核对 {item.get('finding_id')} 的列语义、panel 对应关系和良性解释。",
                "evidence_refs": [item.get("workbook"), item.get("sheet")],
            }
            for idx, item in enumerate(priority, start=1)
        ],
        "report_notes": [
            "Agent review is a structured interpretation layer; deterministic artifacts remain the evidence source.",
            "Do not treat source-data candidates as misconduct conclusions.",
        ],
        "limitations": [
            "Fake Agent mode was used; no model reasoning was performed.",
        ],
    }


def fake_material_plan(*, case_id: str, workdir: Path) -> dict[str, Any]:
    inventory = _read_json(workdir / "material_inventory.json") or {}
    lanes = inventory.get("supported_optional_lanes") or []
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "selected_optional_lanes": lanes,
        "missing_materials": [] if any(item.get("status") == "selected" for item in lanes) else ["source_data_xlsx"],
        "unsupported_materials": [
            item
            for item in (inventory.get("files") or [])[:50]
            if item.get("material_type") in {"structured_table_text", "raw_data", "archive"}
        ],
        "agent_rationale": [
            "Use material_inventory.json to decide optional evidence lanes.",
            "Execute only Tool Registry validated lanes; do not run arbitrary commands.",
        ],
    }


def run_agent_material_plan(
    *,
    case_id: str,
    workdir: Path,
    project_root: Path,
    env: dict[str, str],
    model: str,
    opencode_bin: str,
    timeout_seconds: int,
    max_retries: int,
) -> AgentRunResult:
    if env.get("VERITAS_FAKE_OPENCODE") == "1":
        return AgentRunResult(
            status="ok",
            data=fake_material_plan(case_id=case_id, workdir=workdir),
            detail="fake opencode material plan",
            command=[],
            runtime_seconds=0.0,
        )
    prompt = build_material_plan_prompt(case_id=case_id, workdir=workdir)
    context_pack = build_material_inventory_context_pack(workdir, case_id)
    return _run_with_context_pack(
        role="material_plan",
        prompt=prompt,
        context_pack=context_pack,
        expected="material plan",
        workdir=workdir,
        project_root=project_root,
        env=env,
        model=model,
        opencode_bin=opencode_bin,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        validator=validate_material_plan,
    )


def run_agent_review(
    *,
    case_id: str,
    workdir: Path,
    project_root: Path,
    env: dict[str, str],
    model: str,
    opencode_bin: str,
    timeout_seconds: int,
    max_retries: int,
) -> AgentRunResult:
    if env.get("VERITAS_FAKE_OPENCODE") == "1":
        return AgentRunResult(
            status="ok",
            data=fake_review(case_id=case_id, workdir=workdir),
            detail="fake opencode review",
            command=[],
            runtime_seconds=0.0,
        )
    prompt = build_review_prompt(case_id=case_id, workdir=workdir)
    context_pack = build_review_context_pack(workdir, case_id)
    return _run_with_context_pack(
        role="review",
        prompt=prompt,
        context_pack=context_pack,
        expected="review",
        workdir=workdir,
        project_root=project_root,
        env=env,
        model=model,
        opencode_bin=opencode_bin,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        validator=validate_review,
    )


def build_review_prompt(*, case_id: str, workdir: Path) -> str:
    summary = _artifact_summary(workdir)
    return f"""
You are Veritas Runtime Review Agent.

Task: review deterministic audit artifacts and produce structured claim/finding review. Do not run tools. Do not modify files. Do not make final misconduct judgments. Return ONLY one valid JSON object. The first character must be {{ and the last character must be }}. Do not wrap it in Markdown.

Case:
- case_id: {case_id}
- workdir: {workdir}

Artifact summary:
{json.dumps(summary, ensure_ascii=False, indent=2)}

Focus:
- extract candidate claims from figure/source-data mappings
- review source-data priority findings
- pressure-test benign explanations
- create manual review tasks

Language:
- Use Chinese for all natural-language explanations, report_notes, limitations, review questions, benign explanations, and manual-review instructions.
- Keep professional terms and provenance evidence unchanged: claim, finding, Source Data, Agent, Tool Registry, workbook/sheet names, file paths, tool_id, artifact names, figure labels, evidence refs, code identifiers, and quoted paper claims.

Return this exact JSON shape:
{{
  "schema_version": "1.0",
  "case_id": "{case_id}",
  "candidate_claims": [
    {{
      "claim_id": "AC-001",
      "claim_text": "...",
      "claim_type": "numeric|method|figure_trace|code_execution|material_completeness",
      "paper_location": "...",
      "evidence_refs": ["..."],
      "status": "needs_review"
    }}
  ],
  "claim_to_source_data": [
    {{
      "claim_id": "AC-001",
      "mapping_id": "...",
      "source_data_refs": ["..."],
      "confidence": "low|medium|high",
      "needs_human_review": true
    }}
  ],
  "finding_reviews": [
    {{
      "finding_id": "...",
      "assessment": "manual_review_required|likely_artifact|needs_more_evidence",
      "benign_explanations": ["..."],
      "residual_risk": "low|medium|high",
      "evidence_refs": {{}}
    }}
  ],
  "manual_review_tasks": [
    {{
      "task_id": "MR-001",
      "priority": "low|medium|high",
      "question": "...",
      "evidence_refs": ["..."]
    }}
  ],
  "report_notes": ["..."],
  "limitations": ["..."]
}}
""".strip()


def build_material_plan_prompt(*, case_id: str, workdir: Path) -> str:
    inventory = _read_json(workdir / "material_inventory.json") or {}
    compact_inventory = {
        "summary": inventory.get("summary", {}),
        "candidate_source_roots": inventory.get("candidate_source_roots", [])[:12],
        "supported_optional_lanes": inventory.get("supported_optional_lanes", [])[:8],
        "limitations": inventory.get("limitations", []),
    }
    return f"""
You are Veritas Material Planner.

Task: inspect material_inventory.json and choose optional evidence lanes. PDF analysis is mandatory and already handled by deterministic code. Your job is only optional data/material lanes.

Rules:
- Do not run tools.
- Do not invent files.
- Select only Tool Registry lanes that are supported by the inventory.
- Current MVP can execute XLSX/XLSM Source Data with tool_ids source_data.profile, source_data.findings, and source_data.pair_forensics.
- CSV/TSV/raw/archive materials should be reported as unsupported_materials unless an executable lane exists.
- Use Chinese for natural-language fields such as reason, unsupported_materials.reason, and agent_rationale. Keep professional terms, tool_id, lane_id, file paths, artifact names, workbook/sheet names, and evidence refs unchanged.
- Return ONLY one valid JSON object. The first character must be {{ and the last character must be }}.

Case:
- case_id: {case_id}
- workdir: {workdir}

Compact inventory:
{json.dumps(compact_inventory, ensure_ascii=False, indent=2)}

Return this exact JSON shape:
{{
  "schema_version": "1.0",
  "case_id": "{case_id}",
  "selected_optional_lanes": [
    {{
      "lane_id": "source_data_xlsx",
      "status": "selected|missing_material|unsupported",
      "tool_ids": ["source_data.profile", "source_data.findings", "source_data.pair_forensics"],
      "root": "... or null",
      "reason": "...",
      "params": {{
        "source_data_findings": {{
          "min_overlap": 12,
          "min_support": 0.98,
          "max_findings_per_category": 200
        }}
      }}
    }}
  ],
  "missing_materials": ["..."],
  "unsupported_materials": [
    {{
      "path": "...",
      "material_type": "...",
      "reason": "..."
    }}
  ],
  "agent_rationale": ["..."]
}}
""".strip()


def validate_review(data: dict[str, Any]) -> dict[str, Any]:
    _require(data, "schema_version", str)
    _require(data, "case_id", str)
    for key in [
        "candidate_claims",
        "claim_to_source_data",
        "finding_reviews",
        "manual_review_tasks",
        "report_notes",
        "limitations",
    ]:
        _require(data, key, list)
    return data


def validate_material_plan(data: dict[str, Any]) -> dict[str, Any]:
    _require(data, "schema_version", str)
    _require(data, "case_id", str)
    lanes = _require(data, "selected_optional_lanes", list)
    normalized = []
    for lane in lanes:
        if not isinstance(lane, dict):
            raise ValueError("selected_optional_lanes items must be objects")
        lane_id = str(lane.get("lane_id", ""))
        if lane_id != "source_data_xlsx":
            raise ValueError(f"unsupported optional lane_id: {lane_id}")
        status = str(lane.get("status", "missing_material"))
        if status not in {"selected", "missing_material", "unsupported"}:
            raise ValueError(f"unsupported optional lane status: {status}")
        tool_ids = lane.get("tool_ids") or []
        if status == "selected":
            required_tool_ids = ["source_data.profile", "source_data.findings", "source_data.pair_forensics"]
            if tool_ids != required_tool_ids:
                raise ValueError("source_data_xlsx selected lane must use source_data.profile, source_data.findings, and source_data.pair_forensics")
            if not lane.get("root"):
                raise ValueError("source_data_xlsx selected lane requires root")
        params = lane.get("params") if isinstance(lane.get("params"), dict) else {}
        source_params = params.get("source_data_findings") if isinstance(params.get("source_data_findings"), dict) else {}
        normalized.append(
            {
                "lane_id": lane_id,
                "status": status,
                "tool_ids": tool_ids if status == "selected" else [],
                "root": lane.get("root") if status == "selected" else None,
                "reason": str(lane.get("reason", ""))[:500],
                "params": {
                    "source_data_findings": _coerce_material_source_params(source_params),
                },
            }
        )
    data["selected_optional_lanes"] = normalized
    data.setdefault("missing_materials", [])
    data.setdefault("unsupported_materials", [])
    data.setdefault("agent_rationale", [])
    return data
