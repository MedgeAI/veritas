from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.investigation.agent_models import TruncationConfig
from engine.shared import filter_judge_input
from engine.investigation.context_pack._shared import (
    _read_json_artifact,
    _collect_limitations,
    _artifact_summary_value,
    _compact_pair_review_task_for_judge,
    _compact_pair_cluster_for_judge,
    _compact_visual_review_task_for_judge,
    _compact_visual_cluster_for_judge,
    head_tail_truncate,
)
from engine.investigation.context_pack.role_outputs import _build_role_outputs_section
from engine.investigation.context_pack.evidence import _extract_top_n_findings


def _load_judge_artifacts(workdir: Path) -> dict[str, Any]:
    """Load all artifacts needed for judge context summary."""
    return {
        "claim_output": _read_json_artifact(workdir, "agent_claim_extractor.json"),
        "source_output": _read_json_artifact(workdir, "agent_source_data_auditor.json"),
        "material_inventory": _read_json_artifact(workdir, "material_inventory.json"),
        "material_plan": _read_json_artifact(workdir, "agent_material_plan.json"),
        "numeric": _read_json_artifact(workdir, "numeric_forensics.json"),
        "source_findings": _read_json_artifact(workdir, "source_data_findings.json"),
        "pair_forensics": _read_json_artifact(
            workdir, "source_data_pair_forensics.json"
        ),
        "visual_findings": _read_json_artifact(workdir, "visual_findings.json"),
        "image_relationships": _read_json_artifact(workdir, "image_relationships.json"),
    }


def _build_deterministic_summaries_section(
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    """Build the deterministic_artifact_summaries section."""
    material_inventory = artifacts["material_inventory"]
    material_plan = artifacts["material_plan"]
    numeric = artifacts["numeric"]
    source_findings = artifacts["source_findings"]
    pair_forensics = artifacts["pair_forensics"]
    visual_findings = artifacts["visual_findings"]
    image_relationships = artifacts["image_relationships"]

    inventory_summary = (
        material_inventory.get("summary")
        if isinstance(material_inventory, dict)
        else {}
    )

    return {
        "material_inventory": {
            "file_count": inventory_summary.get("file_count")
            if isinstance(inventory_summary, dict)
            else None,
            "by_material_type": inventory_summary.get("by_material_type", {})
            if isinstance(inventory_summary, dict)
            else {},
        },
        "material_plan": {
            "selected_optional_lanes": material_plan.get("selected_optional_lanes", [])
            if isinstance(material_plan, dict)
            else [],
            "missing_materials": material_plan.get("missing_materials", [])
            if isinstance(material_plan, dict)
            else [],
            "unsupported_materials": (material_plan.get("unsupported_materials") or [])[
                :8
            ]
            if isinstance(material_plan, dict)
            else [],
        },
        "numeric_forensics": _artifact_summary_value(numeric),
        "source_data_findings": _artifact_summary_value(source_findings),
        "source_data_pair_forensics": _artifact_summary_value(pair_forensics),
        "source_data_pair_forensics_review_tasks": [
            _compact_pair_review_task_for_judge(item)
            for item in (
                (
                    pair_forensics.get("review_tasks")
                    if isinstance(pair_forensics, dict)
                    else []
                )
                or []
            )[:12]
            if isinstance(item, dict)
        ],
        "source_data_pair_forensics_clusters": [
            _compact_pair_cluster_for_judge(item)
            for item in (
                (
                    pair_forensics.get("finding_clusters")
                    if isinstance(pair_forensics, dict)
                    else []
                )
                or []
            )[:12]
            if isinstance(item, dict)
        ],
        "visual_findings": _artifact_summary_value(visual_findings),
        "visual_review_queue": [
            _compact_visual_review_task_for_judge(item)
            for item in (
                (
                    visual_findings.get("review_queue")
                    if isinstance(visual_findings, dict)
                    else []
                )
                or []
            )[:12]
            if isinstance(item, dict)
        ],
        "visual_finding_clusters": [
            _compact_visual_cluster_for_judge(item)
            for item in (
                (
                    visual_findings.get("finding_clusters")
                    if isinstance(visual_findings, dict)
                    else []
                )
                or []
            )[:12]
            if isinstance(item, dict)
        ],
        "image_relationships": _artifact_summary_value(image_relationships),
    }


def _build_judge_context_summary(workdir: Path) -> dict[str, Any]:
    artifacts = _load_judge_artifacts(workdir)
    limitations = _collect_limitations(workdir)

    return {
        "contract": {
            "role_id": "judge",
            "purpose": "Synthesize prior role outputs and compact deterministic summaries into report-ready risk suggestions.",
            "primary_inputs": [
                "agent_claim_extractor.json",
                "agent_source_data_auditor.json",
                "top_n_findings",
                "limitations",
            ],
            "raw_artifacts_excluded": [
                "full.md",
                "evidence_ledger.json",
                "source_data_findings.json",
                "source_data_pair_forensics.json",
                "visual image files",
            ],
            "output_limits": {
                "risk_suggestions": 8,
                "report_notes": 8,
                "limitations": 10,
            },
        },
        "role_outputs": _build_role_outputs_section(
            artifacts["claim_output"],
            artifacts["source_output"],
            limitations,
        ),
        "deterministic_artifact_summaries": _build_deterministic_summaries_section(
            artifacts
        ),
        # PRD2-T6: Filter Judge input to only Layer 1 + Layer 2 findings
        "top_n_findings": filter_judge_input(_extract_top_n_findings(workdir, n=12)),
        "limitations": limitations[:12],
    }


def _json_excerpt(data: dict[str, Any], config: TruncationConfig) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return head_tail_truncate(text, config.max_tokens_per_excerpt)
