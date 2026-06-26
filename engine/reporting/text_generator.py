"""LLM-powered text enrichment for HTML report findings.

Generates data-grounded review questions, benign explanations, and relation
descriptions for the top-N findings in a StaticAuditBundle.

Design:
    1. Select top findings by risk priority (critical > high > medium > low).
    2. For each finding, build a context dict from bundle + workdir artifacts.
    3. Call LLM with structured prompt + JSON output schema.
    4. Store results in finding.metadata["llm_text"].
    5. On failure, store {"error": "..."} for graceful fallback.

After enrichment the bundle is re-serialized to disk.  The HTML renderer reads
``finding["llm_text"]`` (metadata is flattened into the finding dict by
``normalize_bundle_finding``) and falls back to "LLM 解释失败" messages when
the field is absent or contains an error.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.static_audit.models import StaticAuditBundle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk priority (higher = more urgent)
# ---------------------------------------------------------------------------
_RISK_PRIORITY: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "info": 0,
}

# ---------------------------------------------------------------------------
# LLM output schema
# ---------------------------------------------------------------------------
LLM_TEXT_FIELDS = ("review_question", "benign_explanations", "relation_text", "evidence_cited")

# ---------------------------------------------------------------------------
# Context dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FindingLLMContext:
    """Compact context passed to the LLM for one finding."""

    finding_id: str
    category: str
    risk_level: str
    summary: str
    issue_category: str
    # Structured data from finding.metadata
    sheet: str | None = None
    workbook: str | None = None
    columns: list[str] = field(default_factory=list)
    row_offset: int | None = None
    relationship_value: Any = None
    support_rate: float | None = None
    pattern_strength: str | None = None
    sample_pairs: list[dict[str, Any]] = field(default_factory=list)
    # Related data
    related_claims: list[dict[str, str]] = field(default_factory=list)
    evidence_items: list[dict[str, str]] = field(default_factory=list)
    agent_source_review: dict[str, Any] | None = None
    agent_judge_risk: dict[str, Any] | None = None
    sibling_count: int = 0

    def to_prompt_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for JSON embedding in a prompt."""
        d: dict[str, Any] = {
            "finding_id": self.finding_id,
            "category": self.category,
            "risk_level": self.risk_level,
            "summary": self.summary,
            "issue_category": self.issue_category,
        }
        # Only include non-empty fields to save tokens
        meta: dict[str, Any] = {}
        if self.sheet:
            meta["sheet"] = self.sheet
        if self.workbook:
            meta["workbook"] = self.workbook
        if self.columns:
            meta["columns"] = self.columns
        if self.row_offset is not None:
            meta["row_offset"] = self.row_offset
        if self.relationship_value is not None:
            meta["relationship_value"] = self.relationship_value
        if self.support_rate is not None:
            meta["support_rate"] = self.support_rate
        if self.pattern_strength:
            meta["pattern_strength"] = self.pattern_strength
        if self.sample_pairs:
            meta["sample_pairs"] = self.sample_pairs
        if meta:
            d["metadata"] = meta
        if self.related_claims:
            d["related_claims"] = self.related_claims
        if self.evidence_items:
            d["evidence_items"] = self.evidence_items
        if self.agent_source_review:
            d["agent_source_review"] = self.agent_source_review
        if self.agent_judge_risk:
            d["agent_judge_risk"] = self.agent_judge_risk
        if self.sibling_count:
            d["sibling_count"] = self.sibling_count
        return d


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _read_json_artifact(workdir: Path, name: str) -> dict[str, Any]:
    """Read a JSON artifact from workdir, returning {} on any failure."""
    from engine.static_audit._shared import resolve_artifact_path, read_json
    path = resolve_artifact_path(workdir, name)
    return read_json(path) or {}


def _build_finding_context(
    finding: Any,
    bundle: StaticAuditBundle,
    workdir: Path,
) -> FindingLLMContext:
    """Build LLM context for a single Finding dataclass instance."""
    meta = finding.metadata or {}
    fid = finding.finding_id

    # Related claims via claim_mappings
    related_claims: list[dict[str, str]] = []
    claim_by_id = {c.claim_id: c for c in bundle.claims}
    for mapping in bundle.claim_mappings:
        if fid in (mapping.finding_refs or []):
            claim = claim_by_id.get(mapping.claim_id)
            if claim:
                related_claims.append({
                    "claim_id": claim.claim_id,
                    "text": (claim.text or "")[:300],
                })
            if len(related_claims) >= 3:
                break

    # Also check claim_refs on the finding itself
    if not related_claims and finding.claim_refs:
        for cid in finding.claim_refs[:3]:
            claim = claim_by_id.get(cid)
            if claim:
                related_claims.append({
                    "claim_id": claim.claim_id,
                    "text": (claim.text or "")[:300],
                })

    # Related evidence items
    evidence_items: list[dict[str, str]] = []
    evidence_ref_set = set(finding.evidence_refs or [])
    for ev in bundle.evidence_items:
        if ev.evidence_id in evidence_ref_set:
            evidence_items.append({
                "evidence_id": ev.evidence_id,
                "kind": ev.kind,
                "summary": (ev.summary or "")[:200],
            })
        if len(evidence_items) >= 5:
            break

    # Agent source review (from workdir artifact)
    source_auditor = _read_json_artifact(workdir, "agent_source_data_auditor.json")
    agent_source_review = None
    for review in (source_auditor.get("finding_reviews") or []):
        if review.get("finding_id") == fid:
            agent_source_review = {
                "benign_explanations": (review.get("benign_explanations") or [])[:3],
                "next_steps": (review.get("next_steps") or [])[:3],
            }
            break

    # Agent judge risk
    agent_judge = _read_json_artifact(workdir, "agent_judge.json")
    agent_judge_risk = None
    for risk in (agent_judge.get("risk_suggestions") or []):
        risk_fids = risk.get("finding_ids") or []
        if fid in risk_fids or risk.get("finding_id") == fid:
            agent_judge_risk = {
                "reason": (risk.get("reason") or "")[:300],
                "risk_level": risk.get("risk_level"),
                "requires_human_review": risk.get("requires_human_review", False),
            }
            break

    # Sibling count (same category)
    sibling_count = sum(
        1 for f in bundle.findings
        if f.category == finding.category and f.finding_id != fid
    )

    # Sample pairs (truncate to 3)
    sample_pairs = (meta.get("sample_pairs") or [])[:3]

    return FindingLLMContext(
        finding_id=fid,
        category=finding.category,
        risk_level=finding.risk_level,
        summary=finding.summary,
        issue_category=finding.issue_category,
        sheet=meta.get("sheet"),
        workbook=meta.get("workbook"),
        columns=meta.get("column_pair") or meta.get("columns") or [],
        row_offset=meta.get("row_offset"),
        relationship_value=meta.get("relationship_value"),
        support_rate=meta.get("support_rate"),
        pattern_strength=meta.get("pattern_strength"),
        sample_pairs=sample_pairs,
        related_claims=related_claims,
        evidence_items=evidence_items,
        agent_source_review=agent_source_review,
        agent_judge_risk=agent_judge_risk,
        sibling_count=sibling_count,
    )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_llm_prompt(context: FindingLLMContext) -> str:
    """Build the LLM prompt with constraints and serialized context."""
    context_json = json.dumps(context.to_prompt_dict(), ensure_ascii=False, indent=2)

    return f"""\
你是论文数据审计助手。根据以下 finding 的结构化数据，生成三段文本。

## 约束（违反任何一条则输出无效）
1. 每句话必须引用输入数据中的具体值（sheet 名、列名、行号、数值、claim ID）
2. 如果无法引用具体数据，对应字段返回 null
3. 不预判学术不端——只描述数据模式，不给结论
4. 不使用"请解释"、"请确认"等泛化措辞——改为"请核对 X 中 Y 列的 Z 值"
5. benign_explanations 最多 3 条，每条引用不同数据角度
6. evidence_cited 只能包含输入中的 evidence_id 和 claim_id

## Finding 数据
{context_json}

## 输出格式
严格返回 JSON，不包含其他文字：
{{
    "review_question": "具体的审查问题（引用数据），或 null",
    "benign_explanations": ["良性解释1（引用数据）", "良性解释2"],
    "relation_text": "一句话描述数据模式（引用具体列名、数值），或 null",
    "evidence_cited": ["引用的 evidence_id 或 claim_id"]
}}
"""


# ---------------------------------------------------------------------------
# Response validator
# ---------------------------------------------------------------------------

def _validate_response(response: dict[str, Any], context: FindingLLMContext) -> None:
    """Validate LLM response structure and evidence references.

    Raises ValueError if validation fails.
    """
    if not isinstance(response, dict):
        raise ValueError(f"LLM response is not a dict: {type(response)}")

    # Check required fields exist
    for field_name in LLM_TEXT_FIELDS:
        if field_name not in response:
            raise ValueError(f"Missing field: {field_name}")

    # Validate evidence_cited references
    valid_ids: set[str] = set()
    for ev in context.evidence_items:
        valid_ids.add(ev.get("evidence_id", ""))
    for cl in context.related_claims:
        valid_ids.add(cl.get("claim_id", ""))
    valid_ids.discard("")

    cited = response.get("evidence_cited") or []
    if not isinstance(cited, list):
        raise ValueError(f"evidence_cited is not a list: {type(cited)}")
    for ref in cited:
        if isinstance(ref, str) and ref and ref not in valid_ids:
            logger.debug("evidence_cited contains unknown ref: %s (allowed: %s)", ref, valid_ids)

    # Validate benign_explanations is a list
    exp = response.get("benign_explanations")
    if exp is not None and not isinstance(exp, list):
        raise ValueError(f"benign_explanations is not a list: {type(exp)}")


# ---------------------------------------------------------------------------
# Main enrichment function
# ---------------------------------------------------------------------------

def _select_top_findings(
    findings: list[Any],
    max_findings: int,
) -> list[Any]:
    """Select top findings by risk priority."""
    return sorted(
        findings,
        key=lambda f: (-_RISK_PRIORITY.get(f.risk_level, 0), f.finding_id),
    )[:max_findings]


def enrich_bundle_with_llm_text(
    bundle: StaticAuditBundle,
    workdir: Path,
    llm_client: Any,
    max_findings: int = 10,
) -> StaticAuditBundle:
    """Enrich top findings with LLM-generated text.

    For each of the top-N findings (by risk priority):
    1. Build context from bundle + workdir artifacts
    2. Call LLM with structured prompt
    3. Validate response
    4. Store in finding.metadata["llm_text"]

    On failure for a single finding, stores {"error": "..."} and continues.

    Args:
        bundle: The StaticAuditBundle to enrich (mutated in place).
        workdir: Path to the workdir containing JSON artifacts.
        llm_client: VeritasLLMClient instance (must have chat_json method).
        max_findings: Maximum number of findings to enrich (default 10).

    Returns:
        The same bundle instance (for chaining).
    """
    if llm_client is None:
        logger.warning("LLM client is None; skipping text enrichment")
        return bundle

    if not bundle.findings:
        logger.info("No findings in bundle; skipping text enrichment")
        return bundle

    top_findings = _select_top_findings(bundle.findings, max_findings)
    logger.info(
        "LLM text enrichment: targeting %d/%d findings",
        len(top_findings), len(bundle.findings),
    )

    enriched = 0
    failed = 0

    for finding in top_findings:
        try:
            context = _build_finding_context(finding, bundle, workdir)
            prompt = _build_llm_prompt(context)
            response = llm_client.chat_json(prompt, max_tokens=2000)
            _validate_response(response, context)
            finding.metadata["llm_text"] = {
                "review_question": response.get("review_question"),
                "benign_explanations": response.get("benign_explanations") or [],
                "relation_text": response.get("relation_text"),
                "evidence_cited": response.get("evidence_cited") or [],
                "model": "qwen3.7-plus",
                "generated_at": _utc_now(),
            }
            enriched += 1
        except Exception as e:
            logger.warning(
                "LLM enrichment failed for %s: %s",
                finding.finding_id, e,
            )
            finding.metadata["llm_text"] = {"error": str(e)}
            failed += 1

    logger.info(
        "LLM text enrichment complete: %d succeeded, %d failed",
        enriched, failed,
    )
    return bundle


def _utc_now() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
