"""Small-n publication-pattern detectors for source-data workbooks."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import Any

from engine.static_audit.tools.source_data_findings import (
    SheetVectors,
    _extract_raw_data_samples,
    col_to_name,
    column_label,
)
from engine.static_audit.tools.source_data_findings.summary_statistics import (
    is_summary_statistic_pair,
)

from ._shared import (
    PairForensicsParams,
    SheetNumericIndex,
    common_rows as index_common_rows,
    ensure_sheet_numeric_index,
    has_consecutive_run,
    risk_rank,
)
from .profile_helpers import _is_semantic_equivalent_pair


DISPLAY_PLACES = 6
TAIL_DIGITS = 5
MIN_TAIL_RUN = 4
MIN_REPEAT_DECIMAL_PLACES = 4
MIN_FIXED_RELATION_PAIRS = 3


def _cell_ref(col: int, row: int) -> str:
    return f"{col_to_name(col)}{row}"


def _quantized(value: Decimal, places: int = DISPLAY_PLACES) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    try:
        return value.quantize(quantum)
    except InvalidOperation:
        return value.normalize()


def _display_value(value: Decimal, places: int = DISPLAY_PLACES) -> str:
    quantized = _quantized(value, places)
    if quantized == quantized.to_integral_value():
        return str(quantized.to_integral_value())
    return f"{quantized:.{places}f}".rstrip("0").rstrip(".")


def _fraction_digits(value: Decimal, places: int = DISPLAY_PLACES) -> str:
    text = f"{_quantized(value, places):.{places}f}"
    if "." not in text:
        return ""
    return text.split(".", 1)[1]


def _meaningful_decimal_places(value: Decimal) -> int:
    fraction = _fraction_digits(value)
    return len(fraction.rstrip("0"))


def _fractional_tail(value: Decimal, tail_digits: int = TAIL_DIGITS) -> str | None:
    fraction = _fraction_digits(value)
    if len(fraction) < tail_digits:
        return None
    if len(fraction.rstrip("0")) < tail_digits:
        return None
    tail = fraction[-tail_digits:]
    if not tail.strip("0"):
        return None
    return tail


def _row_label(sheet: SheetVectors, row: int) -> str:
    labels = []
    for entries in sheet.text_columns.values():
        for text_row, value in entries:
            if text_row == row and value not in labels:
                labels.append(value)
    return " / ".join(labels) or f"row {row}"


def _row_cells(sheet: SheetVectors, row: int) -> list[dict[str, Any]]:
    cells = []
    for col, values_by_row in sorted(sheet.numeric_columns.items()):
        value = values_by_row.get(row)
        if value is None:
            continue
        tail = _fractional_tail(value)
        cells.append(
            {
                "row": row,
                "col": col,
                "cell": _cell_ref(col, row),
                "value": value,
                "display_value": _display_value(value),
                "tail": tail,
                "column_label": column_label(sheet, col),
            }
        )
    return cells


def _numeric_cells(sheet: SheetVectors) -> list[dict[str, Any]]:
    cells = []
    for col, values_by_row in sorted(sheet.numeric_columns.items()):
        for row, value in sorted(values_by_row.items()):
            cells.append(
                {
                    "row": row,
                    "col": col,
                    "cell": _cell_ref(col, row),
                    "value": value,
                    "display_value": _display_value(value),
                    "row_label": _row_label(sheet, row),
                    "column_label": column_label(sheet, col),
                    "tail": _fractional_tail(value),
                    "decimal_places": _meaningful_decimal_places(value),
                }
            )
    return cells


def repeated_measurement_value_findings(
    sheet: SheetVectors, params: PairForensicsParams
) -> list[dict[str, Any]]:
    """Detect repeated displayed measurement values in small source-data tables."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cell in _numeric_cells(sheet):
        value = _quantized(cell["value"])
        if value in {Decimal("0"), Decimal("1"), Decimal("-1")}:
            continue
        grouped[cell["display_value"]].append(cell)

    findings: list[dict[str, Any]] = []
    for display_value, cells in grouped.items():
        count = len(cells)
        if count < 2:
            continue
        max_places = max(int(cell["decimal_places"]) for cell in cells)
        if max_places < 3:
            continue
        if count == 2 and max_places < MIN_REPEAT_DECIMAL_PLACES:
            continue
        rows = sorted({int(cell["row"]) for cell in cells})
        cols = sorted({int(cell["col"]) for cell in cells})
        row_labels = sorted({str(cell["row_label"]) for cell in cells})
        same_row = len(rows) == 1
        risk = "high" if count >= 3 and max_places >= 5 else "medium"
        if count == 2 and not same_row:
            risk = "low" if max_places < 5 else "medium"
        findings.append(
            {
                "finding_id": None,
                "category": "repeated_measurement_value",
                "risk_level": risk,
                "confidence": "high" if count >= 3 else "medium",
                "workbook": sheet.workbook,
                "sheet": sheet.sheet,
                "relationship_value": display_value,
                "support_rows": count,
                "overlap_rows": count,
                "repeated_value": display_value,
                "repeated_count": count,
                "cells": [cell["cell"] for cell in cells[:30]],
                "rows": rows[:30],
                "columns": [col_to_name(col) for col in cols],
                "row_labels": row_labels[:8],
                "sample_pairs": [
                    {
                        "cell": cell["cell"],
                        "row": cell["row"],
                        "column": col_to_name(int(cell["col"])),
                        "value": cell["display_value"],
                        "row_label": cell["row_label"],
                        "column_label": cell["column_label"],
                    }
                    for cell in cells[:20]
                ],
                "benign_explanations": [
                    "可能是合法重复测量、离散化计数比例或展示值四舍五入后重复。",
                    "若这些 cell 代表独立样本或独立实验，精确重复值需要回到原始记录复核。",
                ],
                "pressure_test_result": "needs_repeated_value_independence_review",
                "next_steps": [
                    "确认重复 cell 是否属于同一样本、技术重复、阈值化百分比或独立生物学重复。",
                    "核对原始仪器导出和统计脚本，确认展示值重复是否由四舍五入解释。",
                ],
                "raw_data_samples": _extract_raw_data_samples(sheet, rows),
            }
        )
    return sorted(
        findings,
        key=lambda item: (
            -risk_rank(item["risk_level"]),
            -int(item["repeated_count"]),
            str(item["sheet"]),
            str(item["repeated_value"]),
        ),
    )[: params.max_findings_per_category]


def within_sheet_fractional_tail_reuse_findings(
    sheet: SheetVectors, params: PairForensicsParams
) -> list[dict[str, Any]]:
    """Detect repeated decimal tails across distinct displayed values in one sheet."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cell in _numeric_cells(sheet):
        tail = cell.get("tail")
        if tail is None:
            continue
        if int(cell["decimal_places"]) < TAIL_DIGITS:
            continue
        grouped[str(tail)].append(cell)

    findings: list[dict[str, Any]] = []
    for tail, cells in grouped.items():
        display_values = sorted({str(cell["display_value"]) for cell in cells})
        if len(display_values) < 2:
            continue
        count = len(cells)
        if count < 3:
            continue
        rows = sorted({int(cell["row"]) for cell in cells})
        cols = sorted({int(cell["col"]) for cell in cells})
        row_labels = sorted({str(cell["row_label"]) for cell in cells})
        findings.append(
            {
                "finding_id": None,
                "category": "fractional_tail_reuse",
                "risk_level": "high" if count >= 5 else "medium",
                "confidence": "medium",
                "workbook": sheet.workbook,
                "sheet": sheet.sheet,
                "relationship_value": tail,
                "support_rows": count,
                "overlap_rows": count,
                "tail_digits": TAIL_DIGITS,
                "reused_tail": tail,
                "matched_cells": count,
                "distinct_values": display_values[:20],
                "cells": [cell["cell"] for cell in cells[:30]],
                "rows": rows[:30],
                "columns": [col_to_name(col) for col in cols],
                "row_labels": row_labels[:8],
                "sample_pairs": [
                    {
                        "cell": cell["cell"],
                        "row": cell["row"],
                        "column": col_to_name(int(cell["col"])),
                        "value": cell["display_value"],
                        "tail": tail,
                        "row_label": cell["row_label"],
                        "column_label": cell["column_label"],
                    }
                    for cell in cells[:20]
                ],
                "benign_explanations": [
                    "可能是百分比由相同分母计数换算、展示值四舍五入或合法归一化导致尾数重复。",
                    "若这些值来自不同独立样本或不同实验条件，小数尾部复用需要追溯原始计数和计算脚本。",
                ],
                "pressure_test_result": "needs_fractional_tail_origin_review",
                "next_steps": [
                    "确认这些值是否由相同整数计数分母换算为百分比。",
                    "核对原始计数、归一化公式和展示值四舍五入规则。",
                ],
                "raw_data_samples": _extract_raw_data_samples(sheet, rows),
            }
        )
    return sorted(
        findings,
        key=lambda item: (
            -risk_rank(item["risk_level"]),
            -int(item["matched_cells"]),
            str(item["sheet"]),
            str(item["reused_tail"]),
        ),
    )[: params.max_findings_per_category]


def small_n_fixed_relationship_findings(
    sheet: SheetVectors, params: PairForensicsParams
) -> list[dict[str, Any]]:
    """Detect exact fixed difference/ratio in short column vectors."""
    findings: list[dict[str, Any]] = []
    columns = sorted(sheet.numeric_columns)
    for left_col, right_col in combinations(columns, 2):
        left_values = sheet.numeric_columns[left_col]
        right_values = sheet.numeric_columns[right_col]
        common_rows = sorted(set(left_values).intersection(right_values))
        if len(common_rows) < MIN_FIXED_RELATION_PAIRS:
            continue
        diffs = [right_values[row] - left_values[row] for row in common_rows]
        ratios = [
            right_values[row] / left_values[row]
            for row in common_rows
            if left_values[row] != 0
        ]
        relationships: list[tuple[str, Decimal]] = []
        rounded_diffs = {_display_value(diff, DISPLAY_PLACES) for diff in diffs}
        if len(rounded_diffs) == 1 and _quantized(diffs[0]) != 0:
            relationships.append(("small_n_fixed_difference", _quantized(diffs[0])))
        rounded_ratios = {_display_value(ratio, DISPLAY_PLACES) for ratio in ratios}
        if (
            len(ratios) == len(common_rows)
            and len(rounded_ratios) == 1
            and _quantized(ratios[0]) not in {Decimal("0"), Decimal("1")}
        ):
            relationships.append(("small_n_fixed_ratio", _quantized(ratios[0])))
        for category, relationship_value in relationships:
            rows = common_rows[:]
            findings.append(
                {
                    "finding_id": None,
                    "category": category,
                    "risk_level": "medium",
                    "confidence": "high",
                    "workbook": sheet.workbook,
                    "sheet": sheet.sheet,
                    "relationship_value": _display_value(relationship_value),
                    "support_rows": len(common_rows),
                    "overlap_rows": len(common_rows),
                    "columns": [col_to_name(left_col), col_to_name(right_col)],
                    "column_labels": [
                        column_label(sheet, left_col),
                        column_label(sheet, right_col),
                    ],
                    "rows": rows,
                    "sample_pairs": [
                        {
                            "row": row,
                            "left_cell": _cell_ref(left_col, row),
                            "right_cell": _cell_ref(right_col, row),
                            "left": _display_value(left_values[row]),
                            "right": _display_value(right_values[row]),
                            "relationship": _display_value(relationship_value),
                        }
                        for row in common_rows[:20]
                    ],
                    "benign_explanations": [
                        "可能是合法单位换算、归一化、同一原始量的派生列或展示层公式。",
                        "若两列代表独立实验条件，短向量中的精确固定关系需要人工复核。",
                    ],
                    "pressure_test_result": "needs_small_n_fixed_relationship_review",
                    "next_steps": [
                        "确认两列是否应为派生关系、单位换算或同一原始数据的不同表示。",
                        "若列代表独立条件，要求提供原始表格和计算脚本。",
                    ],
                    "raw_data_samples": _extract_raw_data_samples(sheet, rows),
                }
            )
    return sorted(
        findings,
        key=lambda item: (
            -risk_rank(item["risk_level"]),
            -int(item["support_rows"]),
            str(item["sheet"]),
            str(item["columns"]),
        ),
    )[: params.max_findings_per_category]


def cross_sheet_fractional_tail_reuse_findings(
    sheets: list[SheetVectors], params: PairForensicsParams
) -> list[dict[str, Any]]:
    """Detect aligned decimal-tail reuse across rows in different sheets."""
    findings: list[dict[str, Any]] = []
    row_vectors: list[tuple[SheetVectors, int, str, list[dict[str, Any]]]] = []
    for sheet in sheets:
        rows = sorted({row for values in sheet.numeric_columns.values() for row in values})
        for row in rows:
            cells = [cell for cell in _row_cells(sheet, row) if cell.get("tail")]
            if len(cells) >= MIN_TAIL_RUN:
                row_vectors.append((sheet, row, _row_label(sheet, row), cells))

    for left_index, (left_sheet, left_row, left_label, left_cells) in enumerate(
        row_vectors
    ):
        for right_sheet, right_row, right_label, right_cells in row_vectors[
            left_index + 1 :
        ]:
            if left_sheet.workbook != right_sheet.workbook:
                continue
            if left_sheet.sheet == right_sheet.sheet and left_row == right_row:
                continue
            best: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for left_start in range(len(left_cells)):
                for right_start in range(len(right_cells)):
                    current = []
                    left_pos = left_start
                    right_pos = right_start
                    while (
                        left_pos < len(left_cells)
                        and right_pos < len(right_cells)
                        and left_cells[left_pos]["tail"] == right_cells[right_pos]["tail"]
                        and left_cells[left_pos]["display_value"]
                        != right_cells[right_pos]["display_value"]
                    ):
                        current.append((left_cells[left_pos], right_cells[right_pos]))
                        left_pos += 1
                        right_pos += 1
                    if len(current) > len(best):
                        best = current
            if len(best) < MIN_TAIL_RUN:
                continue
            same_label = left_label.lower() == right_label.lower()
            rows = sorted({left_row, right_row})
            findings.append(
                {
                    "finding_id": None,
                    "category": "cross_sheet_fractional_tail_reuse",
                    "risk_level": "high" if same_label and len(best) >= 5 else "medium",
                    "confidence": "high" if len(best) >= 5 else "medium",
                    "workbook": left_sheet.workbook,
                    "sheet": f"{left_sheet.sheet} <-> {right_sheet.sheet}",
                    "relationship_value": f"last_{TAIL_DIGITS}_digits",
                    "support_rows": len(best),
                    "overlap_rows": min(len(left_cells), len(right_cells)),
                    "tail_digits": TAIL_DIGITS,
                    "sheet_pair": [left_sheet.sheet, right_sheet.sheet],
                    "row_pair": [left_row, right_row],
                    "row_labels": [left_label, right_label],
                    "matched_pairs": len(best),
                    "columns": [
                        f"{pair[0]['cell']}<->{pair[1]['cell']}" for pair in best[:20]
                    ],
                    "sample_pairs": [
                        {
                            "left_sheet": left_sheet.sheet,
                            "right_sheet": right_sheet.sheet,
                            "left_cell": left_cell["cell"],
                            "right_cell": right_cell["cell"],
                            "left_value": left_cell["display_value"],
                            "right_value": right_cell["display_value"],
                            "tail": left_cell["tail"],
                        }
                        for left_cell, right_cell in best[:20]
                    ],
                    "benign_explanations": [
                        "可能是展示值四舍五入、同一上游模板或相同计算过程造成的小数尾部一致。",
                        "若两个 sheet 对应独立 cohort 或独立实验，小数尾部连续复用需要追溯原始值和生成脚本。",
                    ],
                    "pressure_test_result": "needs_cross_sheet_decimal_tail_review",
                    "next_steps": [
                        "确认两个 sheet/figure 是否为独立实验、独立 cohort 或同一数据的合法派生。",
                        "核对原始未四舍五入数值，确认小数尾部一致是否由展示规则解释。",
                    ],
                    "raw_data_samples": _extract_raw_data_samples(
                        left_sheet, [left_row]
                    )
                    + _extract_raw_data_samples(right_sheet, [right_row]),
                }
            )
    return sorted(
        findings,
        key=lambda item: (
            -risk_rank(item["risk_level"]),
            -int(item["matched_pairs"]),
            str(item["sheet"]),
        ),
    )[: params.max_findings_per_category]


def _matching_tail_offsets(
    windows_a: tuple[tuple[int, str], ...],
    windows_b: tuple[tuple[int, str], ...],
    token: str,
    shift: int,
) -> tuple[int | None, int | None]:
    for offset_a, token_a in windows_a:
        if token_a != token:
            continue
        for offset_b, token_b in windows_b:
            if token_b == token and offset_b - offset_a == shift:
                return offset_a, offset_b
    return None, None


def decimal_tail_match_shifted_findings(
    source: SheetVectors | SheetNumericIndex,
    params: PairForensicsParams,
    *,
    performance: dict[str, Any] | None = None,
    detector_skips: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Detect column pairs with matching 5-digit decimal tails, allowing ±1 position shift."""
    index = ensure_sheet_numeric_index(source, params)
    sheet = index.sheet
    findings: list[dict[str, Any]] = []
    columns = index.valid_columns
    numeric_cell_count = sum(len(values) for values in index.values_by_col.values())
    high_frequency_limit = max(20, int(numeric_cell_count * 0.05))
    skipped_high_frequency_tokens = 0
    for col_a, col_b in combinations(columns, 2):
        values_a = index.values_by_col[col_a]
        values_b = index.values_by_col[col_b]
        common = index_common_rows(index, col_a, col_b)
        if len(common) < 3:
            continue
        if performance is not None:
            performance["decimal_tail_shifted_column_pairs"] = (
                int(performance.get("decimal_tail_shifted_column_pairs", 0)) + 1
            )
        # Group matches by (shift, tail_token).
        groups: dict[tuple[int, str], set[int]] = defaultdict(set)
        for row in common:
            windows_a = index.tail_windows_by_cell.get((col_a, row), ())
            windows_b = index.tail_windows_by_cell.get((col_b, row), ())
            if not windows_a or not windows_b:
                continue
            offsets_by_token_b: dict[str, list[int]] = defaultdict(list)
            for offset_b, token_b in windows_b:
                if index.tail_token_frequency.get(token_b, 0) > high_frequency_limit:
                    skipped_high_frequency_tokens += 1
                    continue
                offsets_by_token_b[token_b].append(offset_b)
            row_matches: set[tuple[int, str]] = set()
            for offset_a, token_a in windows_a:
                if index.tail_token_frequency.get(token_a, 0) > high_frequency_limit:
                    skipped_high_frequency_tokens += 1
                    continue
                for offset_b in offsets_by_token_b.get(token_a, []):
                    shift = offset_b - offset_a
                    if shift in {-1, 0, 1}:
                        row_matches.add((shift, token_a))
            for match_key in row_matches:
                groups[match_key].add(row)
        common_positions = {row: idx for idx, row in enumerate(common)}
        for (shift, tail_token), matched_row_set in groups.items():
            matched_rows = sorted(matched_row_set)
            indices = [common_positions[row] for row in matched_rows]
            count = len(matched_rows)
            comparable = len(common)
            rate = count / comparable if comparable else 0.0
            if not (
                has_consecutive_run(indices, 3)
                or (count >= 3 and rate >= 0.6)
            ):
                continue
            risk = "high" if count >= 5 else "medium"
            confidence = "high" if rate >= 0.8 else "medium"
            # Artifact degradation: formula-derived column.
            artifact_likelihood: str = "unknown"
            artifact_reason: str | None = None
            formula_cols = {col_a, col_b} & set(sheet.formulas_by_column)
            if formula_cols:
                risk = "low"
                artifact_likelihood = "high"
                artifact_reason = "formula-derived column"
            # Artifact degradation: summary / semantic pair.
            summary_pair = is_summary_statistic_pair(
                sheet, col_a, col_b, matched_rows
            )
            lbl_a = column_label(sheet, col_a)
            lbl_b = column_label(sheet, col_b)
            semantic_pair = _is_semantic_equivalent_pair(lbl_a, lbl_b)
            if summary_pair or semantic_pair:
                risk = "low"
                artifact_likelihood = "high"
                if summary_pair:
                    artifact_reason = (
                        "Mean/Sum/N summary-statistics relationship"
                    )
                elif artifact_reason is None:
                    artifact_reason = (
                        f"semantic-equivalent pair: {lbl_a} vs {lbl_b}"
                    )
            sample_pairs = []
            for row in matched_rows[:20]:
                left_offset, right_offset = _matching_tail_offsets(
                    index.tail_windows_by_cell.get((col_a, row), ()),
                    index.tail_windows_by_cell.get((col_b, row), ()),
                    tail_token,
                    shift,
                )
                sample_pairs.append(
                    {
                        "row": row,
                        "left_cell": _cell_ref(col_a, row),
                        "right_cell": _cell_ref(col_b, row),
                        "left": _display_value(values_a[row]),
                        "right": _display_value(values_b[row]),
                        "left_offset": left_offset,
                        "right_offset": right_offset,
                        "tail_token": tail_token,
                        "shift": shift,
                    }
                )
            findings.append(
                {
                    "finding_id": None,
                    "category": "decimal_tail_match_shifted",
                    "risk_level": risk,
                    "confidence": confidence,
                    "workbook": sheet.workbook,
                    "sheet": sheet.sheet,
                    "support_rows": count,
                    "overlap_rows": comparable,
                    "support_rate": round(rate, 4),
                    "columns": [col_to_name(col_a), col_to_name(col_b)],
                    "column_labels": [lbl_a, lbl_b],
                    "shift": shift,
                    "tail_token": tail_token,
                    "sample_pairs": sample_pairs,
                    "benign_explanations": [
                        "可能是单位换算导致的小数点位移（如 mg→g）。",
                        "可能是相同的归一化分母导致的尾数重用。",
                        "可能是计算过程中的中间值共享。",
                    ],
                    "pressure_test_result": "needs_decimal_tail_shift_review",
                    "next_steps": [
                        "确认两列是否存在单位换算关系（10倍、100倍等）。",
                        "核对尾数匹配是否由共同分母产生。",
                        "检查位移方向是否与已知的单位换算一致。",
                    ],
                    "raw_data_samples": _extract_raw_data_samples(
                        sheet, sorted(matched_rows)
                    ),
                    "artifact_likelihood": artifact_likelihood,
                    "artifact_reason": artifact_reason,
                }
            )
    if skipped_high_frequency_tokens and detector_skips is not None:
        detector_skips.append(
            {
                "detector": "decimal_tail_match_shifted",
                "workbook": sheet.workbook,
                "sheet": sheet.sheet,
                "reason": "high_frequency_tail_tokens_skipped",
                "skipped_token_observations": skipped_high_frequency_tokens,
                "frequency_limit": high_frequency_limit,
            }
        )
    return sorted(
        findings,
        key=lambda item: (
            -risk_rank(item["risk_level"]),
            -int(item["support_rows"]),
            str(item["sheet"]),
            str(item["columns"]),
        ),
    )[: params.max_findings_per_category]
