"""Report generation for Veritas static audit.

Backward-compat shim: re-exports every public symbol so that
``from engine.static_audit.report import <name>`` keeps working after the
former monolithic ``report.py`` was split into ``report/`` sub-modules.
"""

from __future__ import annotations

from engine.static_audit.report.evidence import (
    collect_evidence_items,
)
from engine.static_audit.report.claims import (
    agent_finding_review_rows,
    agent_manual_review_rows,
    brief_list,
    collect_agent_refined_claim_mappings,
    collect_deterministic_claim_mappings,
    dedupe,
    investigation_record_rows,
    normalize_claim_status,
)
from engine.static_audit.report.findings import (
    find_missing_source_data_findings,
)
from engine.static_audit.report.generator import (
    build_static_audit_bundle,
    collect_claims_and_findings,
    generate_report,
)
from engine.static_audit.report.sections import (
    collect_visual_findings,
    group_similar_findings,
    merge_deterministic_mappings,
)

__all__ = [
    # evidence.py
    "collect_evidence_items",
    # claims.py
    "agent_finding_review_rows",
    "agent_manual_review_rows",
    "brief_list",
    "collect_agent_refined_claim_mappings",
    "collect_deterministic_claim_mappings",
    "dedupe",
    "investigation_record_rows",
    "normalize_claim_status",
    # findings.py
    "find_missing_source_data_findings",
    # generator.py
    "build_static_audit_bundle",
    "collect_claims_and_findings",
    "generate_report",
    # sections.py
    "collect_visual_findings",
    "group_similar_findings",
    "merge_deterministic_mappings",
]
