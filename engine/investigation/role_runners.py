from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.investigation.context_pack import build_context_pack_for_role
from engine.investigation.validators import _require
from engine.investigation._shared import (
    AgentRunResult,
    _artifact_summary,
    _run_with_context_pack,
)

REAL_STATIC_AUDIT_ROLE_IDS = {
    "claim_extractor",
    "source_data_auditor",
    "judge",
}


def run_agent_role(
    *,
    role_id: str,
    case_id: str,
    workdir: Path,
    project_root: Path,
    env: dict[str, str],
    model: str,
    opencode_bin: str,
    timeout_seconds: int,
    max_retries: int,
) -> AgentRunResult:
    if role_id not in REAL_STATIC_AUDIT_ROLE_IDS:
        raise ValueError(f"unsupported real static-audit role: {role_id}")
    if env.get("VERITAS_FAKE_OPENCODE") == "1":
        return AgentRunResult(
            status="ok",
            data=fake_role_output(role_id=role_id, case_id=case_id, workdir=workdir),
            detail=f"fake opencode role {role_id}",
            command=[],
            runtime_seconds=0.0,
        )
    prompt = build_role_prompt(role_id=role_id, case_id=case_id, workdir=workdir)
    context_pack = build_context_pack_for_role(role_id, workdir, case_id)
    return _run_with_context_pack(
        role=role_id,
        prompt=prompt,
        context_pack=context_pack,
        expected=f"role {role_id}",
        workdir=workdir,
        project_root=project_root,
        env=env,
        model=model,
        opencode_bin=opencode_bin,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        validator=lambda data: validate_role_output(role_id, data),
    )


def build_role_prompt(*, role_id: str, case_id: str, workdir: Path) -> str:
    summary = _artifact_summary(workdir)
    role_specific_rules = ""
    if role_id == "claim_extractor":
        contract = f"""
Return this exact JSON shape:
{{
  "schema_version": "1.0",
  "role_id": "claim_extractor",
  "case_id": "{case_id}",
  "claims": [
    {{
      "claim_id": "AC-001",
      "claim_text": "...",
      "claim_type": "numeric|method|figure_trace|code_execution|material_completeness",
      "paper_location": "...",
      "evidence_refs": ["..."],
      "status": "needs_review",
      "claim_decisiveness": "high|medium|low",
      "figure_refs": ["Fig1", "Fig3a"],
      "expected_source_data": ["Sheet:Fig3, cols B-E"]
    }}
  ],
  "limitations": ["..."]
}}
claim_decisiveness (optional, defaults to "medium"): how decisively this claim supports the paper's main conclusion.
figure_refs (optional, defaults to []): figure/panel IDs referenced by this claim (e.g. ["Fig3a", "Fig3b"]).
expected_source_data (optional, defaults to []): expected source data locations or structures (e.g. ["Sheet:Fig3, cols B-E"]).
""".strip()
        focus = "Extract only technical claims that can be checked against Source Data, figures, code, methods, or material completeness."
    elif role_id == "source_data_auditor":
        contract = f"""
Return this exact JSON shape:
{{
  "schema_version": "1.0",
  "role_id": "source_data_auditor",
  "case_id": "{case_id}",
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
  "limitations": ["..."]
}}
""".strip()
        focus = "Review deterministic Source Data findings, pressure-test benign explanations, and create manual review tasks. Limit claim mappings, finding reviews, and manual tasks to at most 12 items each; prioritize high-risk deterministic findings."
    elif role_id == "judge":
        contract = f"""
Return this exact JSON shape:
{{
  "schema_version": "1.0",
  "role_id": "judge",
  "case_id": "{case_id}",
  "summary": {{
    "claim_count": 0,
    "finding_review_count": 0,
    "manual_review_task_count": 0,
    "technical_risk_summary": "..."
  }},
  "risk_suggestions": [
    {{
      "risk_level": "low|medium|high",
      "reason": "...",
      "evidence_refs": ["..."],
      "requires_human_review": true
    }}
  ],
  "report_notes": ["..."],
  "limitations": ["..."]
}}
""".strip()
        focus = "Synthesize prior role outputs from the compact Judge context pack. Do not re-audit raw deterministic artifacts, do not override deterministic evidence, and do not make a final misconduct judgment."
        role_specific_rules = """
Judge-specific input contract:
- Use `context_pack_judge.json` as the primary input. Its `bounded_excerpts.judge_context_summary.json` field is the compact source of truth for this role.
- Treat `agent_claim_extractor.json` and `agent_source_data_auditor.json` as prior role outputs, but consume them through the compact summary instead of expanding raw artifacts.
- Do not request or infer from full `source_data_findings.json`, `source_data_pair_forensics.json`, `full.md`, image files, or other large raw artifacts.
- Return at most 8 risk_suggestions, 8 report_notes, and 10 limitations.
- Every risk_suggestions item must cite evidence_refs already present in the compact summary or top_n_findings.
- Input findings are pre-filtered: you only receive Layer 1 (high-confidence data issues) and Layer 2 (needs human judgment) findings. Layer 3 informational findings (duplicate row vectors, low-risk signals, methodology checks) are excluded to reduce noise.
""".strip()
    else:
        raise ValueError(f"unsupported role prompt: {role_id}")
    return f"""
You are Veritas Static Audit Role Agent: {role_id}.

Task: {focus}

Rules:
- Do not run tools.
- Do not modify files.
- Do not make final academic-value or misconduct judgments.
- Treat deterministic artifacts as evidence; your output is interpretation and review planning.
- Use Chinese for natural-language fields, including limitations, benign_explanations, manual_review_tasks.question, report_notes, risk_suggestions.reason, and technical_risk_summary. Keep professional terms and provenance evidence unchanged: claim, finding, Source Data, Agent, Tool Registry, workbook/sheet names, file paths, artifact names, figure labels, evidence refs, code identifiers, and quoted paper claims.
- Return ONLY one valid JSON object. The first character must be {{ and the last character must be }}. Do not wrap it in Markdown.

{role_specific_rules}

Case:
- case_id: {case_id}
- workdir: {workdir}

Artifact summary:
{json.dumps(summary, ensure_ascii=False, indent=2)}

{contract}
""".strip()


def fake_role_output(*, role_id: str, case_id: str, workdir: Path) -> dict[str, Any]:
    from engine.investigation.review_material import fake_review

    review = fake_review(case_id=case_id, workdir=workdir)
    if role_id == "claim_extractor":
        claims = review["candidate_claims"]
        for claim in claims:
            claim.setdefault("claim_decisiveness", "medium")
            claim.setdefault("figure_refs", [])
            claim.setdefault("expected_source_data", [])
        return {
            "schema_version": "1.0",
            "role_id": role_id,
            "case_id": case_id,
            "claims": claims,
            "limitations": review["limitations"],
        }
    if role_id == "source_data_auditor":
        return {
            "schema_version": "1.0",
            "role_id": role_id,
            "case_id": case_id,
            "claim_to_source_data": review["claim_to_source_data"],
            "finding_reviews": review["finding_reviews"],
            "manual_review_tasks": review["manual_review_tasks"],
            "limitations": review["limitations"],
        }
    if role_id == "judge":
        return {
            "schema_version": "1.0",
            "role_id": role_id,
            "case_id": case_id,
            "summary": {
                "claim_count": len(review["candidate_claims"]),
                "finding_review_count": len(review["finding_reviews"]),
                "manual_review_task_count": len(review["manual_review_tasks"]),
                "technical_risk_summary": "Structured static-audit review requires human verification before escalation.",
            },
            "risk_suggestions": [],
            "report_notes": review["report_notes"],
            "limitations": review["limitations"],
        }
    raise ValueError(f"unsupported fake role: {role_id}")


def validate_role_output(role_id: str, data: dict[str, Any]) -> dict[str, Any]:
    _require(data, "schema_version", str)
    actual_role_id = _require(data, "role_id", str)
    if actual_role_id != role_id:
        raise ValueError(f"role_id must be {role_id}")
    _require(data, "case_id", str)
    if role_id == "claim_extractor":
        _require(data, "claims", list)
        data.setdefault("limitations", [])
        _require(data, "limitations", list)
        valid_decisiveness = {"high", "medium", "low"}
        for claim in data["claims"]:
            if not isinstance(claim, dict):
                continue
            if "claim_decisiveness" in claim:
                if claim["claim_decisiveness"] not in valid_decisiveness:
                    claim["claim_decisiveness"] = "medium"
            else:
                claim.setdefault("claim_decisiveness", "medium")
            if "figure_refs" not in claim:
                claim["figure_refs"] = []
            if "expected_source_data" not in claim:
                claim["expected_source_data"] = []
    elif role_id == "source_data_auditor":
        for key in [
            "claim_to_source_data",
            "finding_reviews",
            "manual_review_tasks",
            "limitations",
        ]:
            _require(data, key, list)
        data["claim_to_source_data"] = data["claim_to_source_data"][:12]
        data["finding_reviews"] = data["finding_reviews"][:12]
        data["manual_review_tasks"] = data["manual_review_tasks"][:12]
        data["limitations"] = data["limitations"][:10]
    elif role_id == "judge":
        summary = _require(data, "summary", dict)
        for key in ["risk_suggestions", "report_notes", "limitations"]:
            _require(data, key, list)
        data["risk_suggestions"] = data["risk_suggestions"][:8]
        data["report_notes"] = data["report_notes"][:8]
        data["limitations"] = data["limitations"][:10]
        if isinstance(summary.get("technical_risk_summary"), str):
            summary["technical_risk_summary"] = summary["technical_risk_summary"][:1200]
    else:
        raise ValueError(f"unsupported role validator: {role_id}")
    return data
