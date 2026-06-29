"""Shared data structures, constants, and helpers for source_data_findings."""

from __future__ import annotations

import json
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, getcontext
from pathlib import Path

from engine.static_audit.tools.source_data_profile import (
    SHEET_NS,
    normalized_number,
    parse_cell,
    read_xml,
    shared_strings,
    workbook_sheets,
)


getcontext().prec = 28


FORMULA_REF_RE = re.compile(r"\$?([A-Z]+)\$?(\d+)")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")
SUMMARY_MEAN_TERMS = ("mean", "average")
SUMMARY_SUM_TERMS = ("sum", "total")
SUMMARY_N_TERMS = ("n total", "n=", "n ", "count", "number")
TIME_EVENT_TERMS = (
    "day",
    "days",
    "time",
    "week",
    "weeks",
    "control",
    "tumor free",
    "tumour free",
    "survival",
    "event",
)


@dataclass
class SheetVectors:
    workbook: str
    workbook_path: str
    sheet: str
    sheet_path: str
    numeric_columns: dict[int, dict[int, Decimal]]
    text_columns: dict[int, list[tuple[int, str]]]
    formulas_by_column: dict[int, list[dict]]
    cell_count: int
    numeric_cell_count: int


def col_to_name(index: int) -> str:
    name = ""
    value = index
    while value:
        value, rem = divmod(value - 1, 26)
        name = chr(65 + rem) + name
    return name


def col_to_idx(col: str) -> int:
    value = 0
    for ch in col:
        value = value * 26 + ord(ch) - 64
    return value


def decimal_key(value: Decimal, places: str = "0.000001") -> str:
    try:
        return str(value.quantize(Decimal(places)).normalize())
    except InvalidOperation:
        return str(value.normalize())


def risk_rank(value: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}.get(value, 0)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def load_profile(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_workbook_vectors(path: Path) -> list[SheetVectors]:
    vectors = []
    with zipfile.ZipFile(path) as zf:
        shared = shared_strings(zf)
        for sheet in workbook_sheets(zf):
            root = read_xml(zf, sheet["path"])
            numeric_columns: dict[int, dict[int, Decimal]] = defaultdict(dict)
            text_columns: dict[int, list[tuple[int, str]]] = defaultdict(list)
            formulas_by_column: dict[int, list[dict]] = defaultdict(list)
            cell_count = 0
            numeric_cell_count = 0
            for cell in root.findall(".//a:sheetData/a:row/a:c", SHEET_NS):
                cell_count += 1
                parsed = parse_cell(cell, shared)
                row = parsed["row"]
                col = parsed["col"]
                if row is None or col is None:
                    continue
                if parsed["formula"]:
                    formulas_by_column[col].append(
                        {"ref": parsed["ref"], "formula": parsed["formula"]}
                    )
                if parsed["numeric"] is not None:
                    numeric_cell_count += 1
                    numeric_columns[col][row] = parsed["numeric"]
                else:
                    value = clean_text(str(parsed["value"] or ""))
                    if value:
                        text_columns[col].append((row, value))
            vectors.append(
                SheetVectors(
                    workbook=path.name,
                    workbook_path=str(path),
                    sheet=sheet["name"] or "",
                    sheet_path=sheet["path"],
                    numeric_columns=dict(numeric_columns),
                    text_columns=dict(text_columns),
                    formulas_by_column=dict(formulas_by_column),
                    cell_count=cell_count,
                    numeric_cell_count=numeric_cell_count,
                )
            )
    return vectors


def column_label(sheet: SheetVectors, col: int) -> str:
    labels = []
    for row, value in sheet.text_columns.get(col, []):
        if row <= 30 and value not in labels:
            labels.append(value)
        if len(labels) >= 4:
            break
    return " / ".join(labels)


def _extract_raw_data_samples(
    sheet: SheetVectors, rows: list[int], max_samples: int = 50
) -> list[dict]:
    """Extract raw row data from a sheet for the given rows (up to max_samples).

    Each entry contains the 1-based row number and all column values found in
    that row.  Decimal values are converted to float for JSON serialization.
    """
    samples: list[dict] = []
    text_by_row: dict[int, dict[str, str]] = {}
    for col, entries in sheet.text_columns.items():
        label = column_label(sheet, col) or col_to_name(col)
        for row, value in entries:
            text_by_row.setdefault(row, {})[label] = value

    all_cols = sorted(
        set(sheet.numeric_columns) | set(sheet.text_columns)
    )
    for row in rows[:max_samples]:
        column_values: dict[str, object] = {}
        for col in all_cols:
            col_data = sheet.numeric_columns.get(col, {})
            if isinstance(col_data, dict):
                numeric = col_data.get(row)
            else:
                # list-based mock: index is the row
                numeric = col_data[row] if 0 <= row < len(col_data) else None
            if numeric is not None:
                label = column_label(sheet, col) or col_to_name(col)
                column_values[label] = float(numeric)
        for label, value in text_by_row.get(row, {}).items():
            column_values.setdefault(label, value)
        samples.append({"row": row, "column_values": column_values})
    return samples


def _label_lower(sheet: SheetVectors, col: int) -> str:
    return column_label(sheet, col).lower()


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_mean_label(label: str) -> bool:
    return _has_any(label, SUMMARY_MEAN_TERMS)


def _is_sum_label(label: str) -> bool:
    return _has_any(label, SUMMARY_SUM_TERMS)


def _is_n_label(label: str) -> bool:
    return _has_any(label, SUMMARY_N_TERMS)


def _decimal_close(
    left: Decimal, right: Decimal, tolerance: Decimal = Decimal("0.0001")
) -> bool:
    return abs(left - right) <= tolerance


def _integer_like_ratio(value: Decimal) -> bool:
    if value <= 1:
        return False
    return _decimal_close(value, value.to_integral_value(), Decimal("0.000001"))


def is_integer_like(value: Decimal) -> bool:
    return value == value.to_integral_value()


def is_index_like_column(values_by_row: dict[int, Decimal], rows: list[int]) -> bool:
    if len(rows) < 8:
        return False
    values = [values_by_row[row] for row in rows if row in values_by_row]
    if len(values) < 8:
        return False
    if sum(1 for value in values if is_integer_like(value)) / len(values) < 0.95:
        return False
    normalized = [int(value) for value in values]
    diffs = [right - left for left, right in zip(normalized, normalized[1:])]
    if not diffs:
        return False
    one_step_rate = sum(1 for diff in diffs if diff == 1) / len(diffs)
    unique_rate = len(set(normalized)) / len(normalized)
    # Source-data tables often repeat per-group subject IDs as 1..n blocks.
    # Those are index/design columns even when the whole column is not unique.
    repeated_index_blocks = one_step_rate >= 0.7
    mostly_unique_sequence = unique_rate >= 0.9 and one_step_rate >= 0.85
    return repeated_index_blocks or mostly_unique_sequence


def common_rows(left: dict[int, Decimal], right: dict[int, Decimal]) -> list[int]:
    return sorted(set(left).intersection(right))


def assign_ids(findings: list[dict]) -> None:
    counters: dict[str, int] = {}
    prefix = {
        "fixed_difference": "FD",
        "fixed_ratio": "FR",
        "duplicate_numeric_columns": "DC",
        "formula_derived_column": "FM",
    }
    for finding in findings:
        category = finding["category"]
        counters[category] = counters.get(category, 0) + 1
        finding["finding_id"] = f"{prefix.get(category, 'F')}-{counters[category]:04d}"
