#!/usr/bin/env python3
"""Build a compact grounding index (~5KB) from MinerU output artifacts.

The index provides figure_ids, table_ids, source_data_sheets, sections,
and figure_legend_lines extracted from full.md and evidence_ledger.json.
All file access is graceful: missing or unreadable inputs produce empty
structures and a warning log rather than exceptions.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_FIGURE_REF_RE = re.compile(
    r"(?:Extended\s+Data\s+Fig(?:ure)?\.?\s*\d+[a-z]?"
    r"|Fig(?:ure)?\.?\s*\d+[a-z]?)"
)

_TABLE_REF_RE = re.compile(r"Table\s*\d+[a-z]?")

_SECTION_RE = re.compile(r"^(#{1,6})\s+(.*)$")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_figure_label(label: str) -> str | None:
    """Normalize a figure label to 'Fig. N' or 'Extended Data Fig. N' form.

    Returns None if the label does not match expected patterns.
    """
    label = label.strip()
    if not label:
        return None
    m = re.search(
        r"(Extended\s+Data\s+Fig(?:ure)?\.?\s*\d+[a-z]?|Fig(?:ure)?\.?\s*\d+[a-z]?)",
        label,
    )
    if not m:
        return None
    raw = m.group(1)
    # Collapse to canonical "Fig. N" or "Extended Data Fig. N" form
    if raw.lower().startswith("extended"):
        canon = re.sub(r"\s+", " ", raw).strip()
        return re.sub(r"(Data)\s+", r"\1 ", canon, count=1)
    # Simple "Fig. N" form
    num_m = re.search(r"(\d+[a-z]?)", raw)
    if num_m:
        return f"Fig. {num_m.group(1)}"
    return None


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        logger.warning("evidence_ledger not found: %s", path)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("failed to read evidence_ledger %s: %s", path, exc)
        return None


def _read_lines(path: Path) -> list[str] | None:
    if not path.is_file():
        logger.warning("full.md not found: %s", path)
        return None
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("failed to read full.md %s: %s", path, exc)
        return None


def _extract_figure_ids_from_ledger(ledger: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    figures = ledger.get("figures", [])
    if isinstance(figures, list):
        for fig in figures:
            if not isinstance(fig, dict):
                continue
            label = fig.get("label") or fig.get("label_key")
            if label:
                norm = _normalize_figure_label(label)
                if norm:
                    ids.add(norm)
    indexes = ledger.get("indexes", {})
    by_label = indexes.get("by_figure_label", {}) if isinstance(indexes, dict) else {}
    if isinstance(by_label, dict):
        for label in by_label:
            norm = _normalize_figure_label(label)
            if norm:
                ids.add(norm)
    return ids


def _extract_figure_ids_from_md(lines: list[str]) -> set[str]:
    ids: set[str] = set()
    for line in lines:
        for m in _FIGURE_REF_RE.finditer(line):
            norm = _normalize_figure_label(m.group(0))
            if norm:
                ids.add(norm)
    return ids


def _normalize_table_label(label: str) -> str:
    """Normalize whitespace in a table label (e.g. non-breaking spaces)."""
    return re.sub(r"\s+", " ", label.strip())


def _extract_table_ids_from_md(lines: list[str]) -> set[str]:
    ids: set[str] = set()
    for line in lines:
        for m in _TABLE_REF_RE.finditer(line):
            ids.add(_normalize_table_label(m.group(0)))
    return ids


def _extract_table_ids_from_ledger(ledger: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    tables = ledger.get("tables", [])
    if not isinstance(tables, list):
        return ids
    for tbl in tables:
        if not isinstance(tbl, dict):
            continue
        label = tbl.get("label") or tbl.get("label_key")
        if label:
            ids.add(_normalize_table_label(label))
    indexes = ledger.get("indexes", {})
    by_label = indexes.get("by_table_label", {}) if isinstance(indexes, dict) else {}
    if isinstance(by_label, dict):
        for label in by_label:
            ids.add(_normalize_table_label(label))
    return ids


def _extract_source_data_sheets(source_data_dir: Path) -> dict[str, list[str]]:
    if not source_data_dir or not source_data_dir.is_dir():
        return {}
    try:
        import openpyxl  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("openpyxl not installed; skipping source_data sheet extraction")
        return {}
    sheets: dict[str, list[str]] = {}
    for xlsx_path in sorted(source_data_dir.glob("*.xlsx")):
        try:
            wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
            sheets[xlsx_path.name] = list(wb.sheetnames)
            wb.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to read xlsx %s: %s", xlsx_path, exc)
    return sheets


def _extract_sections(lines: list[str]) -> dict[str, str]:
    """Map 'startLine-endLine' -> section_name for each heading line."""
    sections: dict[str, str] = {}
    heading_lines: list[int] = []
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m:
            heading_lines.append(i)
            sections[f"{i + 1}-{i + 1}"] = m.group(2).strip()
    # Extend each section's end to the next heading (or EOF)
    extended: dict[str, str] = {}
    for idx, start in enumerate(heading_lines):
        if idx + 1 < len(heading_lines):
            end = heading_lines[idx + 1] - 1
        else:
            end = len(lines) - 1
        name = sections.get(f"{start + 1}-{start + 1}", "")
        extended[f"{start + 1}-{end + 1}"] = name
    return extended


def _extract_figure_legend_lines(
    lines: list[str],
    figure_ids: set[str],
) -> dict[str, dict[str, int | None]]:
    """For each figure_id, record first and last line numbers (1-based)."""
    legend: dict[str, dict[str, int | None]] = {}
    for fig_id in sorted(figure_ids):
        # Extract the numeric part for matching (e.g. "Fig. 2a" -> "2a")
        num_m = re.search(r"(\d+[a-z]?)", fig_id)
        if not num_m:
            continue
        target_num = num_m.group(1)
        is_extended = "Extended" in fig_id or "extended" in fig_id
        first: int | None = None
        last: int | None = None
        for i, line in enumerate(lines):
            if is_extended and not re.search(r"Extended\s+Data", line):
                continue
            # Look for references like "Fig. 2a" or "Fig. 2"
            if re.search(rf"Fig(?:ure)?\.?\s*{re.escape(target_num)}\b", line):
                if first is None:
                    first = i + 1
                last = i + 1
        if first is not None:
            legend[fig_id] = {"first_line": first, "last_line": last}
    return legend


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_grounding_index(
    full_md_path: Path,
    evidence_ledger_path: Path | None = None,
    source_data_dir: Path | None = None,
) -> dict[str, Any]:
    """Build compact grounding index from MinerU output.

    Returns dict with keys:
      - figure_ids: sorted list of normalized figure references
      - table_ids: sorted list of table references
      - source_data_sheets: mapping of xlsx filename -> list of sheet names
      - sections: mapping of "startLine-endLine" -> section heading
      - figure_legend_lines: mapping of figure_id -> {first_line, last_line}

    Handles missing files gracefully (returns empty structure, no exceptions).
    """
    full_md_path = Path(full_md_path)
    lines = _read_lines(full_md_path)
    if lines is None:
        lines = []

    ledger: dict[str, Any] | None = None
    if evidence_ledger_path is not None:
        ledger = _read_json(Path(evidence_ledger_path))

    # Figure IDs: union of ledger + markdown, deduplicated, sorted
    fig_ids: set[str] = set()
    if ledger is not None:
        fig_ids |= _extract_figure_ids_from_ledger(ledger)
    fig_ids |= _extract_figure_ids_from_md(lines)
    sorted_fig_ids = sorted(fig_ids)

    # Table IDs
    tbl_ids: set[str] = set()
    if ledger is not None:
        tbl_ids |= _extract_table_ids_from_ledger(ledger)
    tbl_ids |= _extract_table_ids_from_md(lines)
    sorted_tbl_ids = sorted(tbl_ids)

    # Source data sheets
    source_data_sheets = _extract_source_data_sheets(
        Path(source_data_dir) if source_data_dir else Path()
    )

    # Sections
    sections = _extract_sections(lines)

    # Figure legend lines
    figure_legend_lines = _extract_figure_legend_lines(lines, set(sorted_fig_ids))

    return {
        "figure_ids": sorted_fig_ids,
        "table_ids": sorted_tbl_ids,
        "source_data_sheets": source_data_sheets,
        "sections": sections,
        "figure_legend_lines": figure_legend_lines,
    }


def save_grounding_index(index: dict[str, Any], output_path: Path) -> None:
    """Write grounding index to JSON file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
