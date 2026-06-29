"""Agent review section builder."""

from __future__ import annotations

from engine.static_audit._shared import markdown_table, fmt_int
from engine.static_audit.report.sections._shared import ReportData
from engine.static_audit.report.claims import agent_manual_review_rows, agent_finding_review_rows


def agent_review_section(data: ReportData) -> list[str]:
    source_auditor_data = data.agent_source_data_auditor
    legacy_review_data = data.agent_review

    if not source_auditor_data and not legacy_review_data:
        return []

    lines: list[str] = []
    lines.append("## Agent Review")
    lines.append("")

    if source_auditor_data:
        candidate_claims = (
            source_auditor_data.get("claims")
            or source_auditor_data.get("candidate_claims")
            or []
        )
        mapping_reviews = (
            source_auditor_data.get("claim_mappings")
            or source_auditor_data.get("claim_to_source_data")
            or []
        )
        finding_reviews = source_auditor_data.get("finding_reviews") or []
        manual_tasks = source_auditor_data.get("manual_review_tasks") or []
        status = source_auditor_data.get("status", "ok")
    elif legacy_review_data:
        candidate_claims = legacy_review_data.get("candidate_claims") or []
        mapping_reviews = legacy_review_data.get("claim_to_source_data") or []
        finding_reviews = legacy_review_data.get("finding_reviews") or []
        manual_tasks = legacy_review_data.get("manual_review_tasks") or []
        status = legacy_review_data.get("status", "ok")
    else:
        return []

    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                ["status", status],
                ["candidate_claims", fmt_int(len(candidate_claims))],
                ["claim_to_source_data_reviews", fmt_int(len(mapping_reviews))],
                ["finding_reviews", fmt_int(len(finding_reviews))],
                ["manual_review_tasks", fmt_int(len(manual_tasks))],
            ],
        )
    )
    if manual_tasks:
        lines.append("")
        lines.append("### Agent Manual Review Tasks")
        lines.append("")
        lines.append(
            markdown_table(
                ["Task", "Priority", "Question", "Evidence Refs"],
                agent_manual_review_rows(manual_tasks),
            )
        )
    if finding_reviews:
        lines.append("")
        lines.append("### Agent Finding Reviews")
        lines.append("")
        lines.append(
            markdown_table(
                ["Finding", "Assessment", "Residual Risk", "Benign Explanations"],
                agent_finding_review_rows(finding_reviews),
            )
        )

    notes = []
    if source_auditor_data:
        notes = source_auditor_data.get("report_notes") or []
    elif legacy_review_data:
        notes = legacy_review_data.get("report_notes") or []

    if notes:
        lines.append("")
        lines.append("Agent report notes:")
        for item in notes[:8]:
            lines.append(f"- {item}")
    lines.append("")
    return lines
