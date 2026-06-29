"""Report section builders — public API re-exports."""

from engine.static_audit.report.sections._shared import (
    ReportData,
    header_section,
    scope_section,
    pipeline_section,
    artifact_manifest_section,
    investigation_section,
    agent_plan_section,
    judge_section,
    claim_mapping_section,
    ledger_section,
    numeric_section,
    profile_section,
    findings_section,
    pair_forensics_section,
    duplicates_section,
    similarity_section,
    bundle_section,
    vlm_section,
    limitations_section,
)
from engine.static_audit.report.sections.material import material_section
from engine.static_audit.report.sections.agent_review import agent_review_section
from engine.static_audit.report.sections.visual_findings import collect_visual_findings
from engine.static_audit.report.sections.grouping import (
    group_similar_findings,
    merge_deterministic_mappings,
)

__all__ = [
    "ReportData",
    "header_section",
    "scope_section",
    "pipeline_section",
    "artifact_manifest_section",
    "material_section",
    "investigation_section",
    "agent_plan_section",
    "judge_section",
    "agent_review_section",
    "claim_mapping_section",
    "ledger_section",
    "numeric_section",
    "profile_section",
    "findings_section",
    "pair_forensics_section",
    "duplicates_section",
    "similarity_section",
    "bundle_section",
    "vlm_section",
    "limitations_section",
    "collect_visual_findings",
    "group_similar_findings",
    "merge_deterministic_mappings",
]
