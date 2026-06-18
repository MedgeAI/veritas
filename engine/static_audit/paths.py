"""Artifact path resolution utilities for Veritas static audit.

This module provides helpers for mapping legacy flat artifact filenames to their
new layered directory structure. It's separated from orchestrator.py to avoid
circular imports with html_report and other modules.
"""
from __future__ import annotations

from pathlib import Path


# Output directory structure: layer artifacts by responsibility for Agent and human readability.
# See outputs/<case_id>/research-integrity-audit/README.md for full documentation.
OUTPUT_DIRS = {
    "mineru": "mineru",           # MinerU PDF parsing intermediate artifacts
    "materials": "materials",     # Material inventory and plans
    "source_data": "source_data", # Source Data tool outputs
    "visual": "visual",           # Visual forensics tool outputs (images, panels, findings)
    "numeric": "numeric",         # Numeric forensics tool outputs
    "agents": "agents",           # Agent outputs, traces, context packs, logs
    "reports": "reports",         # Final deliverables (HTML/MD reports, bundle, manifest)
}


def output_subdir(workdir: Path, category: str) -> Path:
    """Return the subdirectory path for a given artifact category.

    Args:
        workdir: The root audit output directory.
        category: One of the keys in OUTPUT_DIRS.

    Returns:
        Path to the subdirectory (does not create it).
    """
    if category not in OUTPUT_DIRS:
        raise ValueError(f"Unknown output category: {category}. Must be one of {list(OUTPUT_DIRS.keys())}")
    return workdir / OUTPUT_DIRS[category]


def ensure_output_subdirs(workdir: Path) -> None:
    """Create all output subdirectories under workdir."""
    for subdir in OUTPUT_DIRS.values():
        (workdir / subdir).mkdir(parents=True, exist_ok=True)


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
    "agent_visual_triage.json": "agents/visual_triage.json",
    "agent_traces": "agents/traces",
    "context_pack_material_plan.json": "agents/context_pack_material_plan.json",
    "context_pack_claim_extractor.json": "agents/context_pack_claim_extractor.json",
    "context_pack_source_data_auditor.json": "agents/context_pack_source_data_auditor.json",
    "context_pack_review.json": "agents/context_pack_review.json",
    "context_pack_judge.json": "agents/context_pack_judge.json",
    "context_pack_investigation_plan_round_1.json": "agents/context_pack_investigation_plan_round_1.json",
    "agent_investigation_plan_round_01.json": "agents/investigation_plan_round_01.json",
    "vlm_triage_selected.json": "agents/vlm_triage_selected.json",
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


def resolve_artifact_path(workdir: Path, artifact_name: str) -> Path:
    """Resolve an artifact name to its full path, using the ARTIFACT_PATH_MAP.

    If the artifact name is in the map, returns the mapped subdirectory path.
    Otherwise, returns the legacy flat path (for backward compatibility).

    Args:
        workdir: The root audit output directory.
        artifact_name: The artifact filename (e.g., "full.md" or "mineru/full.md").

    Returns:
        Full Path to the artifact.
    """
    if artifact_name in ARTIFACT_PATH_MAP:
        return workdir / ARTIFACT_PATH_MAP[artifact_name]
    return workdir / artifact_name
