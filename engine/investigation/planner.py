from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.investigation.context_pack import (
    build_material_inventory_context_pack,
    build_review_context_pack,
)
from engine.investigation.validators import (
    DEFAULT_SOURCE_FINDING_PARAMS,
    _require,
)
from engine.investigation._shared import (
    AgentRunResult,
    _artifact_summary,
    _run_with_context_pack,
)
from engine.tools.registry import (
    PAPER_STATIC_AUDIT_TOOL_IDS,
    tool_catalog_for_agent,
    tool_catalog_for_investigation,
    validate_investigation_tool_action,
    validate_plan_tools,
)


def fake_plan(
    *,
    case_id: str,
    paper_pdf: Path,
    source_data_dir: Path | None,
    workdir: Path,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "material_inventory": {
            "paper_pdf": str(paper_pdf),
            "source_data_dir": str(source_data_dir) if source_data_dir else None,
            "workdir": str(workdir),
            "code_repo_dir": None,
        },
        "selected_steps": [
            "mineru",
            "evidence_ledger",
            "numeric_forensics",
            "source_data_profile",
            "source_data_findings",
            "visual_panel_extraction",
            "exact_image_duplicates",
            "visual_finding_pipeline",
            "agent_review",
            "report",
        ],
        "selected_tools": [
            {
                "tool_id": tool_id,
                "params": (
                    DEFAULT_SOURCE_FINDING_PARAMS
                    if tool_id == "source_data.findings"
                    else {}
                ),
                "reason": "default paper static audit flow",
            }
            for tool_id in PAPER_STATIC_AUDIT_TOOL_IDS
        ],
        "script_parameters": {
            "source_data_findings": DEFAULT_SOURCE_FINDING_PARAMS,
        },
        "missing_materials": [] if source_data_dir else ["source_data_dir"],
        "agent_rationale": [
            "Use deterministic scripts for extraction and statistics.",
            "Use Agent review after source_data_findings for claim mapping and pressure testing.",
        ],
    }


def fake_investigation_plan(
    *, case_id: str, workdir: Path, round_id: int
) -> dict[str, Any]:
    images_dir = workdir / "images"
    similarity_output = workdir / "image_similarity_candidates.json"
    actions = []
    if round_id == 1 and images_dir.is_dir() and not similarity_output.exists():
        actions.append(
            {
                "action_id": f"IR-{round_id:02d}-A001",
                "tool_id": "image.similarity_candidates",
                "params": {"max_distance": 8, "max_candidates": 200},
                "hypothesis": "MinerU 已抽取图片，近似重复图片候选可补充视觉人工复核线索。",
                "depends_on_artifacts": ["images/", "exact_image_duplicates.json"],
                "expected_evidence_type": "image_similarity",
                "stop_if_no_new_evidence": True,
            }
        )
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "round_id": round_id,
        "actions": actions,
        "stop_reason": "no_more_tools" if not actions else "",
        "agent_rationale": [
            "Fake planner only selects safe optional deterministic tools when required artifacts exist.",
        ],
    }


def run_agent_plan(
    *,
    case_id: str,
    paper_pdf: Path,
    source_data_dir: Path | None,
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
            data=fake_plan(
                case_id=case_id,
                paper_pdf=paper_pdf,
                source_data_dir=source_data_dir,
                workdir=workdir,
            ),
            detail="fake opencode plan",
            command=[],
            runtime_seconds=0.0,
        )
    prompt = build_plan_prompt(
        case_id=case_id,
        paper_pdf=paper_pdf,
        source_data_dir=source_data_dir,
        workdir=workdir,
    )
    context_pack = build_material_inventory_context_pack(workdir, case_id)
    return _run_with_context_pack(
        role="plan",
        prompt=prompt,
        context_pack=context_pack,
        expected="plan",
        workdir=workdir,
        project_root=project_root,
        env=env,
        model=model,
        opencode_bin=opencode_bin,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        validator=validate_plan,
    )


def run_agent_investigation_plan(
    *,
    case_id: str,
    workdir: Path,
    round_id: int,
    previous_records: list[dict[str, Any]],
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
            data=fake_investigation_plan(
                case_id=case_id, workdir=workdir, round_id=round_id
            ),
            detail=f"fake opencode investigation plan round {round_id}",
            command=[],
            runtime_seconds=0.0,
        )
    prompt = build_investigation_plan_prompt(
        case_id=case_id,
        workdir=workdir,
        round_id=round_id,
        previous_records=previous_records,
    )
    context_pack = build_review_context_pack(workdir, case_id)
    return _run_with_context_pack(
        role=f"investigation_plan_round_{round_id}",
        prompt=prompt,
        context_pack=context_pack,
        expected=f"investigation plan round {round_id}",
        workdir=workdir,
        project_root=project_root,
        env=env,
        model=model,
        opencode_bin=opencode_bin,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        validator=lambda data: validate_investigation_plan(data, round_id=round_id),
    )


def build_plan_prompt(
    *,
    case_id: str,
    paper_pdf: Path,
    source_data_dir: Path | None,
    workdir: Path,
) -> str:
    tool_catalog = tool_catalog_for_agent()
    return f"""
You are Veritas Runtime Audit Agent.

Task: create a deterministic audit plan for this paper case. Do not run tools. Do not make misconduct judgments. Return ONLY one valid JSON object. The first character must be {{ and the last character must be }}. Do not wrap it in Markdown.

The research-integrity-auditor toolbox is mandatory context for this task. You are not responsible for invoking the tools directly. Veritas Python orchestrator will validate selected tool_ids against its Tool Registry and execute deterministic tools.

Case:
- case_id: {case_id}
- paper_pdf: {paper_pdf}
- source_data_dir: {source_data_dir or "missing"}
- workdir: {workdir}

Allowed Tool Registry entries:
{json.dumps(tool_catalog, ensure_ascii=False, indent=2)}

Allowed source_data_findings parameters:
- min_overlap: integer 8..50, default 12
- min_support: float 0.90..1.00, default 0.98
- max_findings_per_category: integer 20..500, default 200

Return this exact JSON shape:
{{
  "schema_version": "1.0",
  "case_id": "{case_id}",
  "material_inventory": {{
    "paper_pdf": "...",
    "source_data_dir": "... or null",
    "workdir": "...",
    "code_repo_dir": null
  }},
  "selected_tools": [
    {{
      "tool_id": "mineru.parse_pdf",
      "params": {{}},
      "reason": "..."
    }},
    {{
      "tool_id": "source_data.findings",
      "params": {{
        "min_overlap": 12,
        "min_support": 0.98,
        "max_findings_per_category": 200
      }},
      "reason": "..."
    }}
  ],
  "selected_steps": ["mineru", "evidence_ledger", "numeric_forensics", "source_data_profile", "source_data_findings", "source_data_pair_forensics", "exact_image_duplicates", "visual_panel_extraction", "visual_finding_pipeline", "agent_review", "report"],
  "script_parameters": {{
    "source_data_findings": {{
      "min_overlap": 12,
      "min_support": 0.98,
      "max_findings_per_category": 200
    }}
  }},
  "missing_materials": [],
  "agent_rationale": ["..."]
}}
""".strip()


def build_investigation_plan_prompt(
    *,
    case_id: str,
    workdir: Path,
    round_id: int,
    previous_records: list[dict[str, Any]],
) -> str:
    summary = _artifact_summary(workdir)
    compact_records = previous_records[-30:]
    tool_catalog = tool_catalog_for_investigation()
    return f"""
You are Veritas AgentInvestigationPlanner.

Task: choose deterministic follow-up investigation tools for static paper audit round {round_id}. You do not run tools. Veritas Python orchestrator validates every action against Tool Registry and executes accepted deterministic tools.

Rules:
- Select only tool_id values from Agent-selectable Tool Registry entries.
- Do not select Agent tools such as agent.review or JudgeAgent.
- Mandatory bootstrap tools have already run or have been skipped by deterministic prerequisites; do not request mineru.parse_pdf, paper.evidence_ledger, paper.numeric_forensics, image.exact_duplicates, report tools, or Agent tools.
- Every action must include hypothesis, depends_on_artifacts, and expected_evidence_type.
- Avoid repeating any previous tool_id + params + depends_on_artifacts combination.
- Prefer no actions over noisy actions. If no useful deterministic follow-up is available, return actions=[] and stop_reason="no_more_tools".
- Use Chinese for natural-language fields. Keep tool_id, artifact names, file paths, workbook/sheet names, evidence refs, and professional terms unchanged.
- Return ONLY one valid JSON object. The first character must be {{ and the last character must be }}. Do not wrap it in Markdown.

Case:
- case_id: {case_id}
- workdir: {workdir}
- round_id: {round_id}
- max_rounds: 3

Artifact summary:
{json.dumps(summary, ensure_ascii=False, indent=2)}

Previous investigation records:
{json.dumps(compact_records, ensure_ascii=False, indent=2)}

Agent-selectable Tool Registry entries:
{json.dumps(tool_catalog, ensure_ascii=False, indent=2)}

Return this exact JSON shape:
{{
  "schema_version": "1.0",
  "case_id": "{case_id}",
  "round_id": {round_id},
  "actions": [
    {{
      "action_id": "IR-{round_id:02d}-A001",
      "tool_id": "image.similarity_candidates",
      "params": {{"max_distance": 8, "max_candidates": 200}},
      "hypothesis": "...",
      "depends_on_artifacts": ["images/", "exact_image_duplicates.json"],
      "expected_evidence_type": "image_similarity",
      "stop_if_no_new_evidence": true
    }}
  ],
  "stop_reason": "no_more_tools|budget_exhausted|waiting_for_human|",
  "agent_rationale": ["..."]
}}
""".strip()


def validate_plan(data: dict[str, Any]) -> dict[str, Any]:
    _require(data, "schema_version", str)
    _require(data, "case_id", str)
    _require(data, "material_inventory", dict)
    data = validate_plan_tools(data)
    data.setdefault("missing_materials", [])
    data.setdefault("agent_rationale", [])
    return data


def validate_investigation_plan(
    data: dict[str, Any], *, round_id: int
) -> dict[str, Any]:
    _require(data, "schema_version", str)
    _require(data, "case_id", str)
    actual_round_id = _require(data, "round_id", int)
    if actual_round_id != round_id:
        raise ValueError(f"round_id must be {round_id}")
    actions = _require(data, "actions", list)
    normalized_actions = []
    for index, action in enumerate(actions, start=1):
        normalized = validate_investigation_tool_action(action)
        if not normalized["action_id"]:
            normalized["action_id"] = f"IR-{round_id:02d}-A{index:03d}"
        normalized_actions.append(normalized)
    data["actions"] = normalized_actions
    data["stop_reason"] = str(data.get("stop_reason") or "")
    data.setdefault("agent_rationale", [])
    _require(data, "agent_rationale", list)
    return data
