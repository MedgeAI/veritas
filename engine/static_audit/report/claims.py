"""Claim mapping collection and normalization for Veritas static audit report.

Handles agent-refined claims, deterministic fallback claims, status
normalization, and the row-format helpers used by report sections.
"""

from __future__ import annotations

from typing import Any

from engine.static_audit.models import Claim, ClaimMapping, Status


# ---------------------------------------------------------------------------
# Status normalization
# ---------------------------------------------------------------------------


def normalize_claim_status(value: Any) -> Status:
    """Return *value* if it is a recognised ``Status`` literal, else ``pending``."""
    allowed = {
        "pending",
        "ran",
        "reused",
        "skipped",
        "warning",
        "failed",
        "not_run",
        "not_provided",
        "missing_material",
    }
    status = str(value or "pending")
    return status if status in allowed else "pending"  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Agent-refined claim mappings
# ---------------------------------------------------------------------------


def collect_agent_refined_claim_mappings(
    *,
    agent_claims: dict[str, Any],
    agent_source: dict[str, Any],
    deterministic_mappings: list[dict[str, Any]],
) -> tuple[list[Claim], list[ClaimMapping]]:
    """Build claims and mappings from Agent *claim_extractor* and *source_data_auditor*.

    Falls back to an empty list when neither artifact produced usable output.
    """
    claim_items = [
        item for item in (agent_claims.get("claims") or []) if isinstance(item, dict)
    ]
    source_items = [
        item
        for item in (agent_source.get("claim_to_source_data") or [])
        if isinstance(item, dict)
    ]
    if not claim_items and not source_items:
        return [], []

    deterministic_by_id = {
        str(item.get("mapping_id")): item
        for item in deterministic_mappings
        if isinstance(item, dict) and item.get("mapping_id")
    }

    claims: list[Claim] = []
    claims_by_id: dict[str, Claim] = {}
    for index, item in enumerate(claim_items[:200], start=1):
        claim_text = item.get("claim_text") or item.get("text")
        if not claim_text:
            continue
        claim_id = str(item.get("claim_id") or f"AC-{index:03d}")
        claim = Claim(
            claim_id=claim_id,
            text=str(claim_text),
            claim_type=str(item.get("claim_type", "figure_trace")),
            source=str(item.get("paper_location", "")),
            evidence_refs=[str(ref) for ref in (item.get("evidence_refs") or [])],
            status=normalize_claim_status(item.get("status")),
            metadata={
                "source_role": "claim_extractor",
                "canonical_source": "agent_refined",
                "agent_status": item.get("status"),
                "claim_decisiveness": str(
                    item.get("claim_decisiveness") or "medium"
                ),
                "figure_refs": [
                    str(ref) for ref in (item.get("figure_refs") or [])
                ],
                "expected_source_data": [
                    str(ref) for ref in (item.get("expected_source_data") or [])
                ],
                "raw": item,
            },
        )
        claims.append(claim)
        claims_by_id[claim_id] = claim

    mappings: list[ClaimMapping] = []
    for index, item in enumerate(source_items[:200], start=1):
        claim_id = str(item.get("claim_id") or f"ACM-{index:03d}")
        if claim_id not in claims_by_id:
            claim = Claim(
                claim_id=claim_id,
                text="Agent SourceDataAuditor 生成了映射，但 ClaimExtractor 未提供对应 claim 文本。",
                claim_type="figure_trace",
                source="agent_source_data_auditor",
                evidence_refs=[
                    str(ref) for ref in (item.get("source_data_refs") or [])
                ],
                status="warning",
                metadata={
                    "source_role": "source_data_auditor",
                    "canonical_source": "agent_refined_placeholder",
                    "raw": item,
                },
            )
            claims.append(claim)
            claims_by_id[claim_id] = claim
        deterministic_mapping_id = item.get("mapping_id")
        deterministic_mapping = (
            deterministic_by_id.get(str(deterministic_mapping_id))
            if deterministic_mapping_id
            else None
        )
        mappings.append(
            ClaimMapping(
                mapping_id=str(item.get("mapping_id") or f"ACM-{index:03d}"),
                claim_id=claim_id,
                evidence_refs=[
                    str(ref) for ref in (item.get("source_data_refs") or [])
                ],
                confidence=str(item.get("confidence", "medium")),
                status="agent_refined_mapping",
                rationale="SourceDataAuditor refined deterministic Source Data scaffolding into a review-oriented claim mapping.",
                metadata={
                    "source_role": "source_data_auditor",
                    "canonical_source": "agent_refined",
                    "needs_human_review": bool(item.get("needs_human_review", True)),
                    "source_data_refs": [
                        str(ref) for ref in (item.get("source_data_refs") or [])
                    ],
                    "deterministic_mapping": deterministic_mapping,
                    "raw": item,
                },
            )
        )
    return claims, mappings


# ---------------------------------------------------------------------------
# Deterministic fallback claim mappings
# ---------------------------------------------------------------------------


def collect_deterministic_claim_mappings(
    *,
    source_findings: dict[str, Any],
    evidence_by_finding: dict[Any, str],
) -> tuple[list[Claim], list[ClaimMapping]]:
    """Build claims and mappings from the deterministic ``claim_to_source_data`` scaffold.

    Used as a fallback when no agent-refined output is available.
    """
    claims: list[Claim] = []
    mappings: list[ClaimMapping] = []
    for index, mapping in enumerate(
        (source_findings.get("claim_to_source_data") or [])[:200], start=1
    ):
        claim_items = mapping.get("candidate_claims") or []
        claim_text = (
            claim_items[0].get("text")
            if claim_items and isinstance(claim_items[0], dict)
            else ""
        )
        if not claim_text:
            continue
        claim_id = f"CL-{index:04d}"
        linked = [
            item.get("finding_id")
            for item in (mapping.get("linked_priority_findings") or [])
            if isinstance(item, dict) and item.get("finding_id")
        ]
        refs = [
            evidence_by_finding[item] for item in linked if item in evidence_by_finding
        ]
        claims.append(
            Claim(
                claim_id=claim_id,
                text=claim_text,
                claim_type="figure_trace",
                source=str(mapping.get("source_figure_id", "")),
                evidence_refs=refs,
                status="pending",
                metadata={
                    "mapping_id": mapping.get("mapping_id"),
                    "canonical_source": "deterministic_scaffolding_fallback",
                },
            )
        )
        mappings.append(
            ClaimMapping(
                mapping_id=str(mapping.get("mapping_id") or f"CM-{index:04d}"),
                claim_id=claim_id,
                evidence_refs=refs,
                confidence=str(mapping.get("mapping_confidence", "medium")),
                finding_refs=linked,
                rationale=str(mapping.get("manual_review_note", "")),
                metadata={
                    "canonical_source": "deterministic_scaffolding_fallback",
                    "source_figure_id": mapping.get("source_figure_id"),
                    "workbook": mapping.get("workbook"),
                    "sheet": mapping.get("sheet"),
                    "review_priority": mapping.get("review_priority"),
                    "raw": mapping,
                },
            )
        )
    return claims, mappings


# ---------------------------------------------------------------------------
# Row-format helpers (used by report sections)
# ---------------------------------------------------------------------------


def dedupe(items: list[str]) -> list[str]:
    """Return *items* with duplicates removed, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def brief_list(items: Any, limit: int = 8) -> str:
    """Render *items* as a comma-separated string, capped at *limit* entries."""
    if not isinstance(items, list) or not items:
        return "-"
    return ", ".join(str(item) for item in items[:limit])


def agent_manual_review_rows(
    tasks: list[dict[str, Any]], limit: int = 12
) -> list[list[str]]:
    """Format agent manual-review tasks as markdown table rows."""
    rows = []
    for task in tasks[:limit]:
        refs = task.get("evidence_refs") or []
        rows.append(
            [
                task.get("task_id", "-"),
                task.get("priority", "-"),
                str(task.get("question", "-"))[:220],
                ", ".join(str(item) for item in refs if item) or "-",
            ]
        )
    return rows


def agent_finding_review_rows(
    reviews: list[dict[str, Any]], limit: int = 12
) -> list[list[str]]:
    """Format agent finding reviews as markdown table rows."""
    rows = []
    for review in reviews[:limit]:
        rows.append(
            [
                review.get("finding_id", "-"),
                review.get("assessment", "-"),
                review.get("residual_risk", "-"),
                brief_list(review.get("benign_explanations"), 3),
            ]
        )
    return rows


def investigation_record_rows(
    records: list[dict[str, Any]], limit: int = 20
) -> list[list[str]]:
    """Format investigation records as markdown table rows."""
    rows = []
    for record in records[:limit]:
        artifacts = record.get("output_artifacts") or []
        rows.append(
            [
                record.get("round_id", "-"),
                record.get("action_id", "-"),
                record.get("tool_id", "-"),
                record.get("status", "-"),
                str(record.get("hypothesis") or record.get("detail") or "-")[:180],
                brief_list(artifacts, 3),
            ]
        )
    return rows
