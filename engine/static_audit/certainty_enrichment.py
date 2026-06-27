"""Certainty layer enrichment for audit findings.

Generates fact/inference/suggestion triplets from Finding data to support
the Three-Layer Certainty UI design. Each finding gets:
- FACT: Objective statements from evidence (verifiable)
- INFERENCE: AI analysis with disclaimer (needs human confirmation)
- SUGGESTION: Actionable fixes (recommended actions)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.static_audit.models import Finding, StaticAuditBundle
from engine.static_audit.paths import resolve_artifact_path


def _generate_fact(finding: Finding) -> str:
    """Generate FACT layer: objective statement from evidence.

    Synthesizes finding.summary + evidence_refs into a clear factual statement.
    """
    summary = finding.summary or "发现异常模式"

    # Build evidence locator
    evidence_parts = []
    if finding.evidence_refs:
        evidence_parts.append(f"证据引用: {', '.join(finding.evidence_refs[:3])}")
    if finding.claim_refs:
        evidence_parts.append(f"关联表述: {', '.join(finding.claim_refs[:2])}")

    if evidence_parts:
        return f"{summary}。{'；'.join(evidence_parts)}。"
    return f"{summary}。"


def _generate_inference(finding: Finding) -> str:
    """Generate INFERENCE layer: AI analysis with disclaimer.

    Uses finding.benign_explanations + metadata to generate possible explanations.
    Always includes disclaimer that this is inference, not certification.
    """
    explanations = finding.benign_explanations or []
    metadata = finding.metadata or {}

    # Build inference from benign explanations
    if explanations:
        inference_text = "可能原因: " + "；".join(explanations[:2])
    elif metadata.get("pattern"):
        inference_text = f"模式匹配: {metadata['pattern']}"
    else:
        inference_text = "未发现明确的良性解释，需要人工判断"

    return f"{inference_text}。此为推断，不构成认证结论。"


def _generate_suggestion(finding: Finding) -> str:
    """Generate SUGGESTION layer: actionable fix recommendation.

    Based on finding.category + metadata to provide concrete actions.
    """
    category = finding.category
    metadata = finding.metadata or {}
    risk = finding.risk_level

    # High-risk findings get priority suggestions regardless of category
    if risk in ("critical", "high"):
        if "duplicate" in category.lower():
            return "高风险发现，建议优先核查重复列/行是否为数据录入错误，并记录核查过程。"
        if "offset" in category.lower() or "fixed" in category.lower():
            return "高风险发现，建议优先核查固定差值/偏移是否为公式错误，并记录核查过程。"
        if "mismatch" in category.lower() or "inconsisten" in category.lower():
            return "高风险发现，建议优先对比原始数据与报告表述，修正不一致之处并同步调整相关百分比/统计量。"
        return "高风险发现，建议优先人工复核并记录核查过程。"

    # Category-specific suggestions for medium/low risk
    if "duplicate" in category.lower():
        return "建议核查重复列/行是否为数据录入错误，如确认无误请标注说明。"
    if "offset" in category.lower() or "fixed" in category.lower():
        return "建议核查固定差值/偏移是否为公式错误，如为设计意图请补充说明。"
    if "mismatch" in category.lower() or "inconsisten" in category.lower():
        return "建议对比原始数据与报告表述，修正不一致之处并同步调整相关百分比/统计量。"
    if "missing" in category.lower() or "completeness" in category.lower():
        return "建议补充缺失的数据源或说明数据缺失原因。"

    # Generic suggestion based on risk level
    if risk == "medium":
        return "建议人工复核，确认数据一致性。"

    # Fallback
    if metadata.get("action"):
        return f"建议: {metadata['action']}"
    return "建议人工复核此发现，确认数据准确性。"


def enrich_certainty_layers(bundle: StaticAuditBundle) -> list[dict[str, Any]]:
    """Generate certainty layer data for all findings in the bundle.

    Args:
        bundle: StaticAuditBundle containing findings to enrich

    Returns:
        List of dicts with keys: finding_id, fact, inference, suggestion
    """
    result = []
    for finding in bundle.findings:
        if not isinstance(finding, Finding):
            continue

        result.append({
            "finding_id": finding.finding_id,
            "fact": _generate_fact(finding),
            "inference": _generate_inference(finding),
            "suggestion": _generate_suggestion(finding),
        })

    return result


def save_certainty_data(
    bundle: StaticAuditBundle, workdir: Path
) -> Path:
    """Enrich certainty layers and save as JSON artifact.

    Args:
        bundle: StaticAuditBundle containing findings
        workdir: Working directory for artifact output

    Returns:
        Path to saved certainty_data.json
    """
    import json

    certainty_data = enrich_certainty_layers(bundle)
    path = resolve_artifact_path(workdir, "certainty_data.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(certainty_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
