"""Shared constants for Veritas audit engine.

This module contains constants used across engine.static_audit and
engine.investigation modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root (must be on sys.path before engine.* imports).
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AUDITOR_ROOT = PROJECT_ROOT / "third_party" / "research-integrity-auditor"
MAX_INVESTIGATION_ROUNDS = 3

# Output directory structure: layer artifacts by responsibility for Agent and human readability.
# See outputs/<case_id>/research-integrity-audit/README.md for full documentation.
OUTPUT_DIRS = {
    "mineru": "mineru",  # MinerU PDF parsing intermediate artifacts
    "materials": "materials",  # Material inventory and plans
    "source_data": "source_data",  # Source Data tool outputs
    "visual": "visual",  # Visual forensics tool outputs (images, panels, findings)
    "numeric": "numeric",  # Numeric forensics tool outputs
    "agents": "agents",  # Agent outputs, traces, context packs, logs
    "reports": "reports",  # Final deliverables (HTML/MD reports, bundle, manifest)
}


# Artifact path mapping: maps legacy flat filenames to their new subdirectory paths.
# This allows gradual migration without breaking all path references at once.
ARTIFACT_PATH_MAP = {
    # MinerU intermediate artifacts
    "full.md": "mineru/full.md",
    "mineru_manifest.json": "mineru/mineru_manifest.json",
    "evidence_ledger.json": "mineru/evidence_ledger.json",
    "layout.json": "mineru/layout.json",
    "images": "visual/images",
    # Material inventory and plans
    "material_inventory.json": "materials/material_inventory.json",
    "agent_material_plan.json": "materials/agent_material_plan.json",
    # Source Data tool outputs
    "source_data_profile.json": "source_data/profile.json",
    "source_data_findings.json": "source_data/findings.json",
    "source_data_pair_forensics.json": "source_data/pair_forensics.json",
    "source_data_cross_sheet.json": "source_data/cross_sheet.json",
    "source_data_findings_verdict.json": "source_data/findings_verdict.json",
    # Numeric forensics outputs
    "numeric_forensics.json": "numeric/forensics.json",
    "paperfraud_rule_matches.json": "numeric/paperfraud_rules.json",
    "paperconan_scan.json": "numeric/paperconan_scan.json",
    # Visual forensics outputs
    "visual_evidence.json": "visual/evidence.json",
    "panel_evidence.json": "visual/panel_evidence.json",
    "visual_findings.json": "visual/findings.json",
    "image_relationships.json": "visual/relationships.json",
    "visual_copy_move.json": "visual/copy_move.json",
    "exact_image_duplicates.json": "visual/exact_duplicates.json",
    "image_similarity_candidates.json": "visual/similarity_candidates.json",
    "forged_region_evidence.json": "visual/forged_region_evidence.json",
    "provenance_graph.json": "visual/provenance_graph.json",
    "visual_copy_move_dense.json": "visual/copy_move_dense.json",
    "image_quality.json": "visual/image_quality.json",
    "overlap_reuse.json": "visual/overlap_reuse.json",
    "overlap": "visual/overlap",
    "tru_for": "visual/tru_for",
    "provenance": "visual/provenance",
    "sila_dense": "visual/sila_dense",
    "panels": "visual/panels",
    "yolov5_batch": "visual/yolov5_batch",
    # Agent outputs
    "agent_audit_plan.json": "agents/audit_plan.json",
    "agent_plan.json": "agents/plan.json",
    "agent_review.json": "agents/review.json",
    "agent_claim_extractor.json": "agents/claim_extractor.json",
    "agent_source_data_auditor.json": "agents/source_data_auditor.json",
    "agent_judge.json": "agents/judge.json",
    "agent_defense.json": "agents/defense.json",
    "agent_digit_pattern.json": "agents/digit_pattern.json",
    "agent_math_consistency.json": "agents/math_consistency.json",
    "agent_domain_sanity.json": "agents/domain_sanity.json",
    "agent_traces": "agents/traces",
    "context_pack_material_plan.json": "agents/context_pack_material_plan.json",
    "context_pack_claim_extractor.json": "agents/context_pack_claim_extractor.json",
    "context_pack_source_data_auditor.json": "agents/context_pack_source_data_auditor.json",
    "context_pack_review.json": "agents/context_pack_review.json",
    "context_pack_judge.json": "agents/context_pack_judge.json",
    "context_pack_investigation_plan_round_1.json": "agents/context_pack_investigation_plan_round_1.json",
    "agent_investigation_plan_round_01.json": "agents/investigation_plan_round_01.json",
    "logs": "agents/logs",
    # Final deliverables
    "static_audit_bundle.json": "reports/static_audit_bundle.json",
    "final_audit_report.md": "reports/final_audit_report.md",
    "final_audit_report.html": "reports/final_audit_report.html",
    "audit_run_manifest.json": "reports/audit_run_manifest.json",
    # Investigation rounds (kept at root for backward compatibility)
    "investigation": "investigation",
    "investigation_rounds.jsonl": "investigation/investigation_rounds.jsonl",
}


# Step tool IDs mapping
# Import tool IDs from registry to avoid circular imports
from engine.tools.registry import (
    PAPERFRAUD_RULE_MATCH_TOOL_ID,
    SOURCE_DATA_VERDICT_TOOL_ID,
    TOOL_ID_COPY_MOVE,
    TOOL_ID_FINDING_PIPELINE,
    TOOL_ID_IMAGE_QUALITY,
    TOOL_ID_PANEL_EXTRACTION,
    TOOL_ID_PROVENANCE_GRAPH,
    TOOL_ID_SILA_DENSE,
    TOOL_ID_TRU_FOR,
)

STEP_TOOL_IDS = {
    "mineru": "mineru.parse_pdf",
    "evidence_ledger": "paper.evidence_ledger",
    "numeric_forensics": "paper.numeric_forensics",
    "paperfraud_rule_match": PAPERFRAUD_RULE_MATCH_TOOL_ID,
    "material_inventory": "material.inventory",
    "agent_material_plan": "agent.material_plan",
    "figure_classification": "llm.figure_classification",
    "source_data_profile": "source_data.profile",
    "source_data_findings": "source_data.findings",
    "source_data_pair_forensics": "source_data.pair_forensics",
    "source_data_cross_sheet": "source_data.cross_sheet",
    "source_data_verdict": SOURCE_DATA_VERDICT_TOOL_ID,
    "exact_image_duplicates": "image.exact_duplicates",
    "image_similarity_candidates": "image.similarity_candidates",
    "visual_panel_extraction": TOOL_ID_PANEL_EXTRACTION,
    "visual_copy_move": TOOL_ID_COPY_MOVE,
    "visual_finding_pipeline": TOOL_ID_FINDING_PIPELINE,
    "visual_tru_for": TOOL_ID_TRU_FOR,
    "visual_provenance_graph": TOOL_ID_PROVENANCE_GRAPH,
    "visual_copy_move_dense": TOOL_ID_SILA_DENSE,
    "visual_image_quality": TOOL_ID_IMAGE_QUALITY,
    "agent_plan": "agent.plan",
    "agent_review": "agent.review",
    "agent_role_claim_extractor": "agent.role.claim_extractor",
    "agent_role_source_data_auditor": "agent.role.source_data_auditor",
    "agent_role_judge": "agent.role.judge",
    "static_audit_bundle": "static_audit.bundle",
    "report": "report.render_markdown",
    "html_report": "report.render_static_html",
}
