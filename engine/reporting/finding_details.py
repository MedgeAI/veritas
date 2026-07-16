"""Finding detail extraction — pure domain transformations.

Builds per-finding detail dicts from raw artifact data.  These functions
contain no I/O, no DB access, and no orchestration — they transform one
finding dict into a structured detail dict.

Moved from web/backend/veritas_web/client_report_service.py to enforce the
UI -> Engine -> Config layering rule.
"""

from __future__ import annotations

from typing import Any


def extract_location(metadata: dict | None) -> str:
    """Extract human-readable location from finding metadata (PRD S7.3).

    Priority: sheet_name + cell_ref > file_name > pattern description.
    """
    if not metadata or not isinstance(metadata, dict):
        return ""
    sheet = metadata.get("sheet_name", "")
    cell = metadata.get("cell_ref", "")
    if sheet and cell:
        return f"{sheet}!{cell}"
    if sheet:
        return sheet
    file_name = metadata.get("file_name", "")
    if file_name:
        return file_name
    pattern = metadata.get("pattern", "")
    if pattern:
        return pattern
    return ""


def source_data_detail(finding: dict[str, Any]) -> dict[str, Any]:
    columns = (
        finding.get("columns")
        or finding.get("column_pair")
        or finding.get("column")
        or []
    )
    if isinstance(columns, str):
        columns = [columns]
    support_rows = (
        finding.get("support_rows")
        or finding.get("matched_pairs")
        or finding.get("sample_rows")
        or finding.get("equal_rows")
        or []
    )
    samples = (
        finding.get("sample_pairs")
        or finding.get("sample_exact_pairs")
        or finding.get("raw_data_samples")
        or []
    )
    return {
        "type": "source_data",
        "category": finding.get("category"),
        "workbook": finding.get("workbook"),
        "sheet": finding.get("sheet"),
        "columns": columns,
        "support_rows": support_rows,
        "sample_values": samples[:8] if isinstance(samples, list) else [],
        "pattern_description": finding.get("summary")
        or finding.get("description")
        or finding.get("pattern_signature"),
        "benign_explanations": finding.get("benign_explanations")
        or [
            "rounding or truncation",
            "unit conversion or normalization",
            "shared control/reference value",
        ],
        "related_finding_ids": finding.get("related_finding_ids") or [],
    }


def visual_relationship_detail(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "visual_relationship",
        "source_figure": finding.get("source_figure"),
        "target_figure": finding.get("target_figure"),
        "score": finding.get("score"),
        "relationship_type": finding.get("relationship_type"),
        "overlay_path": finding.get("overlay_path"),
        "benign_explanations": finding.get("benign_explanations") or [],
    }


def visual_copy_move_detail(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "visual_copy_move",
        "source_panel": finding.get("source_panel_id"),
        "target_panel": finding.get("target_panel_id"),
        "overlap_ratio": finding.get("overlap_ratio"),
        "score": finding.get("score"),
        "overlay_path": finding.get("overlay_path"),
        "benign_explanations": finding.get("benign_explanations") or [],
    }
