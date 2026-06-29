from __future__ import annotations

from typing import Any

from engine.investigation.context_pack._shared import (
    _risk_rank,
    _compact_claim_for_judge,
    _compact_mapping_for_judge,
    _compact_finding_review_for_judge,
    _compact_manual_task_for_judge,
    _compact_str_list,
    _extend_unique_strings,
)


def _build_role_outputs_section(
    claim_output: Any,
    source_output: Any,
    limitations: list[str],
) -> dict[str, Any]:
    """Build the role_outputs section of judge context summary."""
    # Extract claims
    claims = claim_output.get("claims") if isinstance(claim_output, dict) else []
    if not isinstance(claims, list):
        claims = []

    # Extract mappings, finding_reviews, manual_tasks
    mappings = (
        source_output.get("claim_to_source_data")
        if isinstance(source_output, dict)
        else []
    )
    if not isinstance(mappings, list):
        mappings = []
    finding_reviews = (
        source_output.get("finding_reviews") if isinstance(source_output, dict) else []
    )
    if not isinstance(finding_reviews, list):
        finding_reviews = []
    manual_tasks = (
        source_output.get("manual_review_tasks")
        if isinstance(source_output, dict)
        else []
    )
    if not isinstance(manual_tasks, list):
        manual_tasks = []

    # Sort reviews and tasks by risk
    top_reviews = sorted(
        [item for item in finding_reviews if isinstance(item, dict)],
        key=lambda item: _risk_rank(item.get("residual_risk")),
    )[:12]
    top_tasks = sorted(
        [item for item in manual_tasks if isinstance(item, dict)],
        key=lambda item: _risk_rank(item.get("priority")),
    )[:12]

    # Collect limitations from both outputs
    if isinstance(claim_output, dict):
        _extend_unique_strings(limitations, claim_output.get("limitations"))
    if isinstance(source_output, dict):
        _extend_unique_strings(limitations, source_output.get("limitations"))

    return {
        "claim_extractor": {
            "status": claim_output.get("status")
            if isinstance(claim_output, dict)
            else "missing",
            "claim_count": len(claims),
            "sample_claims": [
                _compact_claim_for_judge(item)
                for item in claims[:12]
                if isinstance(item, dict)
            ],
            "limitations": _compact_str_list(
                claim_output.get("limitations")
                if isinstance(claim_output, dict)
                else []
            ),
        },
        "source_data_auditor": {
            "status": source_output.get("status")
            if isinstance(source_output, dict)
            else "missing",
            "claim_mapping_count": len(mappings),
            "finding_review_count": len(finding_reviews),
            "manual_review_task_count": len(manual_tasks),
            "sample_claim_mappings": [
                _compact_mapping_for_judge(item)
                for item in mappings[:12]
                if isinstance(item, dict)
            ],
            "top_finding_reviews": [
                _compact_finding_review_for_judge(item) for item in top_reviews
            ],
            "top_manual_review_tasks": [
                _compact_manual_task_for_judge(item) for item in top_tasks
            ],
            "limitations": _compact_str_list(
                source_output.get("limitations")
                if isinstance(source_output, dict)
                else []
            ),
        },
    }
