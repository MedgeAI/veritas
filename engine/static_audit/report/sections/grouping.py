"""Finding grouping and deterministic mapping merge helpers."""

from __future__ import annotations

from typing import Any

from engine.static_audit.models import Finding
from engine.static_audit.report.claims import dedupe


def group_similar_findings(findings: list[Finding]) -> list[Finding]:
    """Group similar findings into summary findings to reduce noise.

    Groups paired_ratio_reuse by workbook+sheet and copy_move by figure pair.
    Creates summary findings and marks original findings as suppressed.
    """
    # Group paired_ratio_reuse by workbook+sheet
    paired_groups: dict[tuple[str, str], list[Finding]] = {}
    for finding in findings:
        if finding.category == "long_format_paired_ratio_reuse":
            metadata = finding.metadata or {}
            key = (
                str(metadata.get("workbook") or ""),
                str(metadata.get("sheet") or ""),
            )
            paired_groups.setdefault(key, []).append(finding)

    # Group copy_move by figure pair
    copy_move_groups: dict[tuple[str, str], list[Finding]] = {}
    for finding in findings:
        if finding.category in ("copy_move_single", "copy_move_cross"):
            metadata = finding.metadata or {}
            src = str(
                metadata.get("source_parent_figure_id")
                or metadata.get("source_panel_id")
                or ""
            )
            tgt = str(
                metadata.get("target_parent_figure_id")
                or metadata.get("target_panel_id")
                or ""
            )
            key = (src, tgt)
            copy_move_groups.setdefault(key, []).append(finding)

    # Create summary findings for paired_ratio_reuse groups
    for (workbook, sheet), group in paired_groups.items():
        if len(group) < 2:
            continue
        summary_id = f"GRP-PRR-{workbook}-{sheet}".replace(".", "_").replace(" ", "_")
        summary = Finding(
            finding_id=summary_id,
            category="long_format_paired_ratio_reuse",
            risk_level=group[0].risk_level,
            summary=f"Paired ratio reuse group: {len(group)} findings in {workbook}/{sheet}",
            issue_category=group[0].issue_category,
            evidence_refs=dedupe([ref for f in group for ref in f.evidence_refs]),
            benign_explanations=group[0].benign_explanations,
            manual_review_note=f"{len(group)} paired ratio reuse patterns detected in workbook '{workbook}', sheet '{sheet}'. Review column semantics and data generation process.",
            metadata={
                "group_type": "paired_ratio_reuse",
                "workbook": workbook,
                "sheet": sheet,
                "member_count": len(group),
                "member_ids": [f.finding_id for f in group],
            },
        )
        findings.append(summary)
        for f in group:
            f.suppressed_by = summary_id

    # Create summary findings for copy_move groups
    for (src, tgt), group in copy_move_groups.items():
        if len(group) < 2:
            continue
        summary_id = f"GRP-CM-{src}-{tgt}".replace(".", "_").replace(" ", "_")
        summary = Finding(
            finding_id=summary_id,
            category=group[0].category,
            risk_level=group[0].risk_level,
            summary=f"Copy-move group: {len(group)} findings for figure pair {src} -> {tgt}",
            issue_category=group[0].issue_category,
            evidence_refs=dedupe([ref for f in group for ref in f.evidence_refs]),
            benign_explanations=group[0].benign_explanations,
            manual_review_note=f"{len(group)} copy-move patterns detected between figures '{src}' and '{tgt}'. Review image processing pipeline and raw data.",
            metadata={
                "group_type": "copy_move",
                "source_figure": src,
                "target_figure": tgt,
                "member_count": len(group),
                "member_ids": [f.finding_id for f in group],
            },
        )
        findings.append(summary)
        for f in group:
            f.suppressed_by = summary_id

    return findings


def merge_deterministic_mappings(
    *,
    agent_claims: list,
    agent_mappings: list,
    source_findings: dict[str, Any],
    evidence_by_finding: dict[Any, str],
) -> tuple[list, list]:
    """Supplement agent-refined claim mappings with uncovered deterministic ones."""
    from engine.static_audit.models import Claim, ClaimMapping

    covered_ids: set[str] = {str(m.mapping_id) for m in agent_mappings}

    extra_claims: list[Claim] = []
    extra_mappings: list[ClaimMapping] = []
    counter = len(agent_claims) + 1

    for mapping in (source_findings.get("claim_to_source_data") or [])[:200]:
        mapping_id = str(mapping.get("mapping_id", ""))
        if not mapping_id or mapping_id in covered_ids:
            continue

        claim_items = mapping.get("candidate_claims") or []
        claim_text = ""
        if claim_items and isinstance(claim_items[0], dict):
            claim_text = claim_items[0].get("text", "")
        if not claim_text:
            paper_refs = mapping.get("matched_paper_references") or []
            if paper_refs and isinstance(paper_refs[0], dict):
                claim_text = paper_refs[0].get("text", "")

        if not claim_text:
            continue

        claim_id = f"CL-{counter:04d}"
        counter += 1

        linked = [
            item.get("finding_id")
            for item in (mapping.get("linked_priority_findings") or [])
            if isinstance(item, dict) and item.get("finding_id")
        ]
        refs = [
            evidence_by_finding[item] for item in linked if item in evidence_by_finding
        ]

        extra_claims.append(
            Claim(
                claim_id=claim_id,
                text=claim_text,
                claim_type="figure_trace",
                source=str(mapping.get("source_figure_id", "")),
                evidence_refs=refs,
                status="pending",
                metadata={
                    "mapping_id": mapping_id,
                    "canonical_source": "deterministic_supplement",
                },
            )
        )
        extra_mappings.append(
            ClaimMapping(
                mapping_id=mapping_id,
                claim_id=claim_id,
                evidence_refs=refs,
                confidence=str(mapping.get("mapping_confidence", "medium")),
                finding_refs=linked,
                rationale=str(mapping.get("manual_review_note", "")),
                metadata={
                    "canonical_source": "deterministic_supplement",
                    "source_figure_id": mapping.get("source_figure_id"),
                    "workbook": mapping.get("workbook"),
                    "sheet": mapping.get("sheet"),
                    "review_priority": mapping.get("review_priority"),
                    "raw": mapping,
                },
            )
        )
    return extra_claims, extra_mappings
