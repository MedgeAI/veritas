"""Claim-to-source-data mapping based on sheet names and paper figure references."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from ._shared import (
    SENTENCE_SPLIT_RE,
    clean_text,
    risk_rank,
)


def figure_keys_from_sheet_name(sheet_name: str) -> list[dict]:
    text = sheet_name.lower().replace("source data", "").strip()
    keys = []
    ed_match = re.search(r"ed\s*fig\.?\s*(\d+)([a-z]?)", text, re.IGNORECASE)
    fig_match = re.search(r"fig\.?\s*(\d+)([a-z]?)", text, re.IGNORECASE)
    if ed_match:
        figure = ed_match.group(1)
        panel = ed_match.group(2) or None
        keys.append(
            {
                "kind": "extended_data",
                "figure": figure,
                "panel": panel,
                "figure_id": f"Extended Data Fig.{figure}{panel or ''}",
                "display_label": f"Extended Data Fig. {figure}{panel or ''}",
                "patterns": [
                    rf"Extended Data Fig\.?\s*{figure}{panel or ''}\b",
                    rf"Extended Data Fig\.\s*{figure}\b",
                ],
            }
        )
    elif fig_match:
        figure = fig_match.group(1)
        panel = fig_match.group(2) or None
        keys.append(
            {
                "kind": "main_figure",
                "figure": figure,
                "panel": panel,
                "figure_id": f"Fig.{figure}{panel or ''}",
                "display_label": f"Fig. {figure}{panel or ''}",
                "patterns": [
                    rf"(?<!Extended Data )Fig\.?\s*{figure}{panel or ''}\b",
                    rf"(?<!Extended Data )Fig\.\s*{figure}\b",
                ],
            }
        )
    # Handle sheet names like "Fig.3c and 3d".
    for extra_panel in re.findall(r"\band\s*(\d+)([a-z])", text, re.IGNORECASE):
        figure, panel = extra_panel
        keys.append(
            {
                "kind": "main_figure",
                "figure": figure,
                "panel": panel,
                "figure_id": f"Fig.{figure}{panel}",
                "display_label": f"Fig. {figure}{panel}",
                "patterns": [
                    rf"(?<!Extended Data )Fig\.?\s*{figure}{panel}\b",
                    rf"(?<!Extended Data )Fig\.\s*{figure}\b",
                ],
            }
        )
    return keys


def markdown_blocks(full_md: Path) -> list[dict]:
    if not full_md or not full_md.exists():
        return []
    blocks = []
    current = []
    start = 1
    for idx, line in enumerate(
        full_md.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if line.strip():
            if not current:
                start = idx
            current.append(line.strip())
            continue
        if current:
            blocks.append(
                {
                    "line_start": start,
                    "line_end": idx - 1,
                    "text": clean_text(" ".join(current)),
                }
            )
            current = []
    if current:
        blocks.append(
            {
                "line_start": start,
                "line_end": start + len(current) - 1,
                "text": clean_text(" ".join(current)),
            }
        )
    return blocks


def candidate_claims_from_refs(refs: list[dict], max_claims: int = 5) -> list[dict]:
    claims = []
    seen = set()
    for ref in refs:
        text = ref["text"]
        if "|" in text:
            text = text.split("|", 1)[1].strip()
        for sentence in SENTENCE_SPLIT_RE.split(text):
            sentence = clean_text(sentence)
            if len(sentence) < 30:
                continue
            # Keep caption titles and panel-level descriptions; drop pure image markers.
            if sentence.startswith("!") or sentence.startswith("x !"):
                continue
            key = sentence[:180].lower()
            if key in seen:
                continue
            seen.add(key)
            claims.append(
                {
                    "source": "paper_figure_reference",
                    "line_start": ref["line_start"],
                    "line_end": ref["line_end"],
                    "text": sentence[:700],
                }
            )
            if len(claims) >= max_claims:
                return claims
    return claims


def finding_index(findings: list[dict]) -> dict[tuple[str, str], list[dict]]:
    index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for finding in findings:
        index[(finding["workbook"], finding["sheet"])].append(
            {
                "finding_id": finding["finding_id"],
                "category": finding["category"],
                "risk_level": finding["risk_level"],
                "artifact_likelihood": finding.get("artifact_likelihood"),
                "summary": {
                    "column_pair": finding.get("column_pair"),
                    "column_labels": finding.get("column_labels"),
                    "relationship_value": finding.get("relationship_value"),
                    "support_rows": finding.get("support_rows"),
                    "equal_rows": finding.get("equal_rows"),
                    "support_rate": finding.get("support_rate"),
                },
            }
        )
    return index


def claim_mappings(
    profile: dict, full_md: Path, max_refs: int, findings: list[dict]
) -> list[dict]:
    blocks = markdown_blocks(full_md)
    mappings = []
    by_source = finding_index(findings)
    for workbook in profile.get("workbooks", []):
        for sheet in workbook.get("sheets", []):
            keys = figure_keys_from_sheet_name(sheet.get("name", ""))
            refs = []
            seen_refs = set()
            for key in keys:
                compiled = [
                    re.compile(pattern, re.IGNORECASE) for pattern in key["patterns"]
                ]
                for block in blocks:
                    if any(pattern.search(block["text"]) for pattern in compiled):
                        ref_key = (
                            block["line_start"],
                            block["line_end"],
                            block["text"][:200],
                        )
                        if ref_key in seen_refs:
                            continue
                        seen_refs.add(ref_key)
                        refs.append(
                            {
                                "line_start": block["line_start"],
                                "line_end": block["line_end"],
                                "match_label": key["display_label"],
                                "text": block["text"][:900],
                            }
                        )
                    if len(refs) >= max_refs:
                        break
                if refs:
                    # A sheet can intentionally map to multiple panels, for example Fig.3c and 3d.
                    continue
            linked = by_source.get((workbook.get("file_name"), sheet.get("name")), [])
            priority_linked = [
                item
                for item in linked
                if risk_rank(item["risk_level"]) >= 2
                and item.get("artifact_likelihood") != "high"
            ]
            mapping_confidence = (
                "high" if refs and keys else ("medium" if refs else "low")
            )
            mappings.append(
                {
                    "mapping_id": None,
                    "workbook": workbook.get("file_name"),
                    "sheet": sheet.get("name"),
                    "source_figure_id": ", ".join(key["figure_id"] for key in keys)
                    or None,
                    "source_figure_kind": keys[0]["kind"] if keys else None,
                    "source_panels": [key["panel"] for key in keys if key.get("panel")],
                    "figure_keys": keys,
                    "source_data_profile": {
                        "cell_count": sheet.get("cell_count"),
                        "numeric_cell_count": sheet.get("numeric_cell_count"),
                        "formula_count": sheet.get("formula_count"),
                    },
                    "matched_paper_references": refs[:max_refs],
                    "paper_refs": refs[:max_refs],
                    "candidate_claims": candidate_claims_from_refs(refs[:max_refs]),
                    "linked_source_data_findings": linked,
                    "linked_priority_findings": priority_linked,
                    "mapping_confidence": mapping_confidence,
                    "status": "candidate_mapping" if refs else "needs_manual_mapping",
                    "review_priority": (
                        "high"
                        if priority_linked
                        else ("medium" if linked or refs else "low")
                    ),
                    "audit_next_step": (
                        "优先人工确认该 sheet 的列语义，并将 linked_priority_findings 与论文 claim 对账。"
                        if priority_linked
                        else "人工确认 sheet 与 figure/panel 对应关系，再抽取 panel 级 claim。"
                    ),
                    "manual_review_note": (
                        "基于 Source Data sheet 名称和论文 figure 引用的启发式映射，需要人工确认 panel 级对应关系。"
                    ),
                }
            )
    for idx, mapping in enumerate(mappings, start=1):
        mapping["mapping_id"] = f"CM-{idx:04d}"
    return mappings
