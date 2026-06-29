"""Visual findings collection helper."""

from __future__ import annotations

from typing import Any

from engine.static_audit.models import Finding
from engine.static_audit.visual_schemas import check_language_compliance
from engine.static_audit.report.claims import dedupe


def collect_visual_findings(
    artifacts: dict[str, Any],
    evidence_by_panel: dict[Any, str],
    evidence_by_artifact: dict[Any, str],
) -> list[Finding]:
    """Build findings from visual_findings artifact."""
    visual_findings = artifacts["visual_findings"]
    findings: list[Finding] = []
    for item in visual_findings.get("findings") or []:
        if not isinstance(item, dict):
            continue
        finding_id = str(item.get("finding_id") or "")
        if not finding_id:
            continue
        summary = str(item.get("summary") or "Visual finding requires manual review.")
        if check_language_compliance(summary):
            summary = "Visual finding summary was hidden because it contained report-forbidden wording; inspect source artifacts manually."
        evidence_refs = [
            evidence_by_panel[panel_id]
            for panel_id in [item.get("source_panel_id"), item.get("target_panel_id")]
            if panel_id in evidence_by_panel
        ]
        category = str(item.get("category") or "visual_finding")
        if category == "forged_region_suspicious":
            tru_for_artifact = evidence_by_artifact.get("forged_region_evidence.json")
            if tru_for_artifact:
                evidence_refs.append(tru_for_artifact)
        else:
            relationship_artifact = evidence_by_artifact.get("image_relationships.json")
            if relationship_artifact:
                evidence_refs.append(relationship_artifact)
        questions = [
            str(value)
            for value in (item.get("manual_review_questions") or [])
            if not check_language_compliance(str(value))
        ]
        findings.append(
            Finding(
                finding_id=finding_id,
                category=category,
                risk_level=str(item.get("risk_level") or "medium"),  # type: ignore[arg-type]
                summary=summary,
                issue_category="consistency",
                evidence_refs=dedupe(evidence_refs),
                benign_explanations=[
                    str(value)
                    for value in (item.get("benign_explanations") or [])
                    if not check_language_compliance(str(value))
                ],
                manual_review_note=questions[0]
                if questions
                else "Visual finding requires manual review against the original figure and raw image.",
                metadata={**item, "source_artifact": "visual_findings.json"},
            )
        )
    return findings
