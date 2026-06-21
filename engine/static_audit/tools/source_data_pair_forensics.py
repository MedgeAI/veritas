#!/usr/bin/env python3
"""Detect row-offset and paired-cohort patterns in XLSX Source Data."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from engine.static_audit.tools.source_data_findings import (
    SheetVectors,
    col_to_name,
    column_label,
    is_summary_statistic_pair,
    is_time_event_design_pair,
    parse_workbook_vectors,
    zero_inflated_pair_artifact,
)
from engine.static_audit.tools.source_data_profile import normalized_number


RISK_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}

# Semantic equivalence groups for summary-statistic pair detection.
# Two columns whose labels both contain terms from the same group are likely
# a legitimate mean±SD / median±IQR / N/total / pre-post / control-treatment
# relationship, not a suspicious fixed-ratio artifact.
_SEMANTIC_GROUPS: tuple[tuple[str, ...], ...] = (
    ("mean", "avg", "average", "sd", "std", "stderr", "sem"),
    ("median", "iqr", "q1", "q3", "25%", "75%"),
    ("n", "count", "total", "proportion", "percentage", "%"),
    ("pre", "post", "baseline", "followup", "t0", "t1"),
    ("control", "treatment", "case", "case_control"),
)


def _is_semantic_equivalent_pair(left_label: str, right_label: str) -> bool:
    """Return True when both labels belong to the same semantic equivalence group.

    Matches are substring-based on the lowercased labels, consistent with how
    ``column_label`` returns the joined header text.
    """
    left_lower = left_label.lower()
    right_lower = right_label.lower()
    for group in _SEMANTIC_GROUPS:
        left_match = any(term in left_lower for term in group)
        right_match = any(term in right_lower for term in group)
        if left_match and right_match:
            return True
    return False


@dataclass(frozen=True)
class PairForensicsParams:
    min_pairs: int = 8
    min_support: float = 0.95
    ratio_places: int = 4
    max_offset: int = 80
    max_findings_per_category: int = 50
    min_duplicate_row_width: int = 2


def risk_rank(value: str) -> int:
    return RISK_ORDER.get(value, 0)


def decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def ratio_key(numerator: Decimal, denominator: Decimal, places: int) -> str | None:
    if denominator == 0:
        return None
    quant = Decimal(1).scaleb(-places)
    try:
        return str((numerator / denominator).quantize(quant).normalize())
    except (InvalidOperation, ZeroDivisionError):
        return None


def common_offset_pairs(rows: list[int], offset: int) -> list[tuple[int, int]]:
    row_set = set(rows)
    return [(row, row + offset) for row in rows if row + offset in row_set]


def numeric_value_diversity(
    values_by_row: dict[int, Decimal],
) -> tuple[int, int, float]:
    values = [normalized_number(value) for value in values_by_row.values()]
    total = len(values)
    distinct = len(set(values))
    return distinct, total, (distinct / total if total else 0.0)


def is_low_information_numeric_column(
    values_by_row: dict[int, Decimal], params: PairForensicsParams
) -> bool:
    """Treat low-cardinality numeric columns as annotation columns, not measurements."""
    distinct, total, diversity = numeric_value_diversity(values_by_row)
    if total < params.min_pairs:
        return False
    return distinct <= 3 or (total >= 20 and diversity <= 0.1)


def candidate_offsets(rows: list[int], params: PairForensicsParams) -> list[int]:
    if not rows:
        return []
    span = max(rows) - min(rows)
    max_offset = min(params.max_offset, span)
    offsets = []
    for offset in range(1, max_offset + 1):
        if len(common_offset_pairs(rows, offset)) >= params.min_pairs:
            offsets.append(offset)
    return offsets


def row_offset_scalar_findings(
    sheet: SheetVectors, params: PairForensicsParams
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str, str], dict[str, Any]] = {}
    for col, values_by_row in sorted(sheet.numeric_columns.items()):
        if is_low_information_numeric_column(values_by_row, params):
            continue
        rows = sorted(values_by_row)
        for offset in candidate_offsets(rows, params):
            pairs = common_offset_pairs(rows, offset)
            ratios: Counter[str] = Counter()
            ratio_rows: dict[str, list[tuple[int, int]]] = defaultdict(list)
            for left_row, right_row in pairs:
                key = ratio_key(
                    values_by_row[right_row],
                    values_by_row[left_row],
                    params.ratio_places,
                )
                if key is None:
                    continue
                ratios[key] += 1
                ratio_rows[key].append((left_row, right_row))
            if not ratios:
                continue
            value, count = ratios.most_common(1)[0]
            support_rate = count / len(pairs)
            if count < params.min_pairs or support_rate < params.min_support:
                continue
            category = (
                "row_offset_exact_reuse"
                if value == "1"
                else "row_offset_scalar_multiple"
            )
            formula_involved = col in sheet.formulas_by_column
            risk = "high" if count >= 10 and value != "1" else "medium"
            if formula_involved:
                risk = "medium"
            group_key = (offset, value, category)
            group = grouped.setdefault(
                group_key,
                {
                    "finding_id": None,
                    "category": category,
                    "risk_level": risk,
                    "confidence": "high" if support_rate >= 0.98 else "medium",
                    "workbook": sheet.workbook,
                    "sheet": sheet.sheet,
                    "row_offset": offset,
                    "relationship_value": value,
                    "support_rows": 0,
                    "overlap_rows": 0,
                    "support_rate": 0.0,
                    "columns": [],
                    "column_labels": [],
                    "sample_pairs": [],
                    "formula_column_involved": False,
                    "benign_explanations": [
                        "可能是合法批量归一化、单位换算、重复测量整理或设计矩阵编码。",
                        "若行代表独立样本或独立患者，固定行偏移倍数关系需要人工复核。",
                    ],
                    "pressure_test_result": "needs_row_offset_independence_review",
                    "next_steps": [
                        "确认行是否代表独立样本、独立患者或分组后的重复计算结果。",
                        "核对第 N 行和第 N+offset 行是否应具有独立测量来源。",
                        "要求原始仪器导出、图像分析日志或上游计算产物支持独立性。",
                    ],
                },
            )
            group["risk_level"] = max(group["risk_level"], risk, key=risk_rank)
            group["confidence"] = (
                "high"
                if group["confidence"] == "high" or support_rate >= 0.98
                else "medium"
            )
            group["support_rows"] += count
            group["overlap_rows"] += len(pairs)
            group["support_rate"] = round(
                group["support_rows"] / group["overlap_rows"], 4
            )
            group["columns"].append(col_to_name(col))
            label = column_label(sheet, col)
            group["column_labels"].append(label)
            group["formula_column_involved"] = (
                group["formula_column_involved"] or formula_involved
            )
            for left_row, right_row in ratio_rows[value][:5]:
                if len(group["sample_pairs"]) >= 20:
                    break
                group["sample_pairs"].append(
                    {
                        "left_row": left_row,
                        "right_row": right_row,
                        "column": col_to_name(col),
                        "left": normalized_number(values_by_row[left_row]),
                        "right": normalized_number(values_by_row[right_row]),
                        "ratio": value,
                    }
                )
    findings = list(grouped.values())
    return sorted(
        findings,
        key=lambda item: (-risk_rank(item["risk_level"]), -item["support_rows"]),
    )[: params.max_findings_per_category]


def paired_ratio_reuse_findings(
    sheet: SheetVectors, params: PairForensicsParams
) -> list[dict[str, Any]]:
    columns = sorted(sheet.numeric_columns)
    findings = []
    for left_index, left_col in enumerate(columns):
        if is_low_information_numeric_column(sheet.numeric_columns[left_col], params):
            continue
        for right_col in columns[left_index + 1 :]:
            if is_low_information_numeric_column(
                sheet.numeric_columns[right_col], params
            ):
                continue
            common = sorted(
                set(sheet.numeric_columns[left_col]).intersection(
                    sheet.numeric_columns[right_col]
                )
            )
            if len(common) < params.min_pairs * 2:
                continue
            ratios_by_row = {}
            for row in common:
                key = ratio_key(
                    sheet.numeric_columns[right_col][row],
                    sheet.numeric_columns[left_col][row],
                    params.ratio_places,
                )
                if key is not None:
                    ratios_by_row[row] = key
            rows = sorted(ratios_by_row)
            for offset in candidate_offsets(rows, params):
                pairs = common_offset_pairs(rows, offset)
                matched = [
                    (left_row, right_row)
                    for left_row, right_row in pairs
                    if ratios_by_row[left_row] == ratios_by_row[right_row]
                ]
                support_rate = len(matched) / len(pairs) if pairs else 0
                if len(matched) < params.min_pairs or support_rate < params.min_support:
                    continue
                risk = (
                    "high" if len(matched) >= 10 and support_rate >= 0.95 else "medium"
                )
                matched_rows = sorted({row for pair in matched for row in pair})
                summary_pair = is_summary_statistic_pair(
                    sheet, left_col, right_col, matched_rows
                )
                left_lbl = column_label(sheet, left_col)
                right_lbl = column_label(sheet, right_col)
                semantic_pair = _is_semantic_equivalent_pair(left_lbl, right_lbl)
                semantic_only = semantic_pair and not summary_pair
                if summary_pair or semantic_pair:
                    risk = "low"
                findings.append(
                    {
                        "finding_id": None,
                        "category": "paired_ratio_reuse",
                        "risk_level": risk,
                        "confidence": "high" if support_rate >= 0.98 else "medium",
                        "workbook": sheet.workbook,
                        "sheet": sheet.sheet,
                        "row_offset": offset,
                        "column_pair": [col_to_name(left_col), col_to_name(right_col)],
                        "column_labels": [left_lbl, right_lbl],
                        "matched_pairs": len(matched),
                        "overlap_pairs": len(pairs),
                        "support_rate": round(support_rate, 4),
                        "ratio_places": params.ratio_places,
                        "artifact_likelihood": "high"
                        if summary_pair or semantic_pair
                        else "unknown",
                        "artifact_reason": (
                            f"summary-statistic pair: {left_lbl} vs {right_lbl}"
                            if semantic_only
                            else (
                                "Mean/Sum/N summary-statistics relationship"
                                if summary_pair
                                else None
                            )
                        ),
                        "sample_pairs": [
                            {
                                "left_row": left_row,
                                "right_row": right_row,
                                "left_ratio": ratios_by_row[left_row],
                                "right_ratio": ratios_by_row[right_row],
                                "reconstruction": (
                                    f"{col_to_name(right_col)}{right_row} ~= "
                                    f"{col_to_name(left_col)}{right_row} * "
                                    f"{col_to_name(right_col)}{left_row}/{col_to_name(left_col)}{left_row}"
                                ),
                            }
                            for left_row, right_row in matched[:20]
                        ],
                        "benign_explanations": [
                            "可能是重复展示同一配对比值、标准化后派生指标或批次归一化产物。",
                            "若行代表独立配对样本，N 与 N+offset 的比例复用需要人工复核。",
                        ],
                        "pressure_test_result": (
                            "likely_summary_statistic_derivation"
                            if summary_pair or semantic_pair
                            else "needs_pair_ratio_independence_review"
                        ),
                        "next_steps": [
                            "确认两列是否构成 paired ratio，例如 PT/RT、pre/post、control/treatment。",
                            "复算第 N 行与第 N+offset 行的 ratio 是否来自独立原始测量。",
                            "要求原始仪器输出或上游分析日志验证样本独立性。",
                        ],
                    }
                )
    return sorted(
        findings,
        key=lambda item: (-risk_rank(item["risk_level"]), -item["matched_pairs"]),
    )[: params.max_findings_per_category]


def duplicate_row_vector_findings(
    sheet: SheetVectors, params: PairForensicsParams
) -> list[dict[str, Any]]:
    row_vectors: dict[tuple[tuple[int, str], ...], list[int]] = defaultdict(list)
    high_information_columns = {
        col
        for col, values_by_row in sheet.numeric_columns.items()
        if not is_low_information_numeric_column(values_by_row, params)
    }
    for row in sorted(
        {row for values in sheet.numeric_columns.values() for row in values}
    ):
        vector = []
        for col in sorted(sheet.numeric_columns):
            value = sheet.numeric_columns[col].get(row)
            if value is not None:
                vector.append((col, normalized_number(value)))
        if len(vector) >= params.min_duplicate_row_width and any(
            col in high_information_columns for col, _value in vector
        ):
            row_vectors[tuple(vector)].append(row)

    findings = []
    for vector, rows in row_vectors.items():
        if len(rows) < 2:
            continue
        cols = [col for col, _value in vector]
        event_artifact = is_time_event_design_pair(sheet, cols, rows)
        zero_artifact = False
        zero_reasons: list[str] = []
        if len(cols) >= 2:
            for left_index, left_col in enumerate(cols):
                for right_col in cols[left_index + 1 :]:
                    current_zero_artifact, zero_reason = zero_inflated_pair_artifact(
                        sheet, left_col, right_col, rows
                    )
                    if current_zero_artifact:
                        zero_artifact = True
                        if zero_reason:
                            zero_reasons.append(zero_reason)
        risk = "medium" if len(rows) < 4 else "high"
        artifact_likelihood = "unknown"
        artifact_reason = None
        pressure_test = "needs_duplicate_row_semantics_review"
        if event_artifact:
            risk = "low"
            artifact_likelihood = "high"
            artifact_reason = "low-cardinality time/event or grouped endpoint rows"
            pressure_test = "likely_time_event_design_artifact"
        elif zero_artifact:
            risk = "medium"
            artifact_likelihood = "high"
            artifact_reason = (
                "; ".join(zero_reasons[:2]) or "zero-inflated matrix duplicate vector"
            )
            pressure_test = "likely_zero_inflated_matrix_artifact"
        findings.append(
            {
                "finding_id": None,
                "category": "duplicate_row_vector",
                "risk_level": risk,
                "confidence": "high",
                "workbook": sheet.workbook,
                "sheet": sheet.sheet,
                "rows": rows[:30],
                "duplicate_row_count": len(rows),
                "width": len(vector),
                "columns": [col_to_name(col) for col in cols],
                "column_labels": [column_label(sheet, col) for col in cols],
                "values": [value for _col, value in vector],
                "artifact_likelihood": artifact_likelihood,
                "artifact_reason": artifact_reason,
                "benign_explanations": [
                    "可能是合法重复测量、重复展示同一样本、分组模板行或空值填充后结果。",
                    "若行代表不同独立样本，整行数值向量重复需要人工复核。",
                ],
                "pressure_test_result": pressure_test,
                "next_steps": [
                    "核对重复行的样本 ID、分组、图表 panel 和是否为独立测量。",
                    "确认重复行是否影响论文中的 n、统计检验或效应量。",
                ],
            }
        )
    return sorted(
        findings,
        key=lambda item: (
            -risk_rank(item["risk_level"]),
            -item["duplicate_row_count"],
            -item["width"],
        ),
    )[: params.max_findings_per_category]


def long_format_pair_groups(
    sheet: SheetVectors,
    id_col: int,
    value_col: int,
    params: PairForensicsParams,
) -> dict[int, tuple[int, int]]:
    id_values = sheet.numeric_columns[id_col]
    value_values = sheet.numeric_columns[value_col]
    groups: dict[int, list[int]] = defaultdict(list)
    for row, pair_id in id_values.items():
        if row not in value_values:
            continue
        if pair_id != pair_id.to_integral_value():
            continue
        groups[int(pair_id)].append(row)
    if len(groups) < params.min_pairs:
        return {}
    paired = {
        pair_id: tuple(sorted(rows))
        for pair_id, rows in groups.items()
        if len(rows) == 2
    }
    if len(paired) < params.min_pairs:
        return {}
    if len(paired) / len(groups) < 0.75:
        return {}
    return paired


def long_format_pair_ratios(
    value_values: dict[int, Decimal],
    pair_groups: dict[int, tuple[int, int]],
    params: PairForensicsParams,
) -> dict[int, str]:
    ratios = {}
    for pair_id, rows in pair_groups.items():
        first_row, second_row = rows
        key = ratio_key(
            value_values[second_row], value_values[first_row], params.ratio_places
        )
        if key is not None:
            ratios[pair_id] = key
    return ratios


def long_format_paired_ratio_reuse_findings(
    sheet: SheetVectors, params: PairForensicsParams
) -> list[dict[str, Any]]:
    findings = []
    columns = sorted(sheet.numeric_columns)
    for id_col in columns:
        id_values = sheet.numeric_columns[id_col]
        distinct, total, _diversity = numeric_value_diversity(id_values)
        if distinct < params.min_pairs or total < params.min_pairs * 2:
            continue
        for value_col in columns:
            if value_col == id_col:
                continue
            value_values = sheet.numeric_columns[value_col]
            if is_low_information_numeric_column(value_values, params):
                continue
            pair_groups = long_format_pair_groups(sheet, id_col, value_col, params)
            if not pair_groups:
                continue
            ratios_by_pair = long_format_pair_ratios(value_values, pair_groups, params)
            pair_ids = sorted(ratios_by_pair)
            for offset in candidate_offsets(pair_ids, params):
                pairs = common_offset_pairs(pair_ids, offset)
                matched = [
                    (left_id, right_id)
                    for left_id, right_id in pairs
                    if ratios_by_pair.get(left_id) == ratios_by_pair.get(right_id)
                ]
                support_rate = len(matched) / len(pairs) if pairs else 0
                if len(matched) < params.min_pairs or support_rate < params.min_support:
                    continue
                findings.append(
                    {
                        "finding_id": None,
                        "category": "long_format_paired_ratio_reuse",
                        "risk_level": "high" if len(matched) >= 10 else "medium",
                        "confidence": "high" if support_rate >= 0.98 else "medium",
                        "workbook": sheet.workbook,
                        "sheet": sheet.sheet,
                        "pair_id_offset": offset,
                        "columns": [col_to_name(id_col), col_to_name(value_col)],
                        "id_column": col_to_name(id_col),
                        "value_column": col_to_name(value_col),
                        "column_labels": [
                            column_label(sheet, id_col),
                            column_label(sheet, value_col),
                        ],
                        "matched_pair_groups": len(matched),
                        "overlap_pair_groups": len(pairs),
                        "support_rate": round(support_rate, 4),
                        "ratio_places": params.ratio_places,
                        "sample_pairs": [
                            {
                                "left_pair_id": left_id,
                                "right_pair_id": right_id,
                                "left_rows": list(pair_groups[left_id]),
                                "right_rows": list(pair_groups[right_id]),
                                "left_ratio": ratios_by_pair[left_id],
                                "right_ratio": ratios_by_pair[right_id],
                                "reconstruction": (
                                    f"{col_to_name(value_col)}{pair_groups[right_id][1]} ~= "
                                    f"{col_to_name(value_col)}{pair_groups[right_id][0]} * "
                                    f"{col_to_name(value_col)}{pair_groups[left_id][1]}/"
                                    f"{col_to_name(value_col)}{pair_groups[left_id][0]}"
                                ),
                            }
                            for left_id, right_id in matched[:20]
                        ],
                        "benign_explanations": [
                            "可能是合法成对样本的标准化比例复用、批次校正或派生指标。",
                            "若 pair id 代表独立患者或独立样本，pair N 与 N+offset 的比值复用需要人工复核。",
                        ],
                        "pressure_test_result": "needs_long_format_pair_ratio_independence_review",
                        "next_steps": [
                            "确认 id_column 是否为患者、样本或 pair 编号，且每个 pair 是否只有两个条件。",
                            "核对同一 pair 内两行是否代表 PT/RT、pre/post、control/treatment 等成对测量。",
                            "要求原始仪器输出、上游分析日志或代码产物验证后半段 pair 的独立性。",
                        ],
                    }
                )
    return sorted(
        findings,
        key=lambda item: (-risk_rank(item["risk_level"]), -item["matched_pair_groups"]),
    )[: params.max_findings_per_category]


def long_format_within_pair_ratio_enrichment_findings(
    sheet: SheetVectors, params: PairForensicsParams
) -> list[dict[str, Any]]:
    findings = []
    columns = sorted(sheet.numeric_columns)
    for id_col in columns:
        id_values = sheet.numeric_columns[id_col]
        distinct, total, _diversity = numeric_value_diversity(id_values)
        if distinct < params.min_pairs or total < params.min_pairs * 2:
            continue
        for value_col in columns:
            if value_col == id_col:
                continue
            value_values = sheet.numeric_columns[value_col]
            if is_low_information_numeric_column(value_values, params):
                continue
            pair_groups = long_format_pair_groups(sheet, id_col, value_col, params)
            if not pair_groups:
                continue
            ratios_by_pair = long_format_pair_ratios(value_values, pair_groups, params)
            if len(ratios_by_pair) < params.min_pairs:
                continue
            ratio_counts = Counter(ratios_by_pair.values())
            for ratio, count in ratio_counts.most_common(
                params.max_findings_per_category
            ):
                if ratio == "1":
                    continue
                support_rate = count / len(ratios_by_pair)
                # Repeated within-pair ratios are weaker evidence than row-offset
                # reuse; require a minimum absolute count and meaningful prevalence.
                if count < params.min_pairs or support_rate < 0.2:
                    continue
                matched_pair_ids = [
                    pair_id
                    for pair_id, value in ratios_by_pair.items()
                    if value == ratio
                ]
                findings.append(
                    {
                        "finding_id": None,
                        "category": "long_format_within_pair_ratio_enrichment",
                        "risk_level": "medium" if support_rate < 0.5 else "high",
                        "confidence": "medium",
                        "workbook": sheet.workbook,
                        "sheet": sheet.sheet,
                        "columns": [col_to_name(id_col), col_to_name(value_col)],
                        "id_column": col_to_name(id_col),
                        "value_column": col_to_name(value_col),
                        "column_labels": [
                            column_label(sheet, id_col),
                            column_label(sheet, value_col),
                        ],
                        "relationship_value": ratio,
                        "matched_pair_groups": count,
                        "overlap_pair_groups": len(ratios_by_pair),
                        "support_rate": round(support_rate, 4),
                        "ratio_places": params.ratio_places,
                        "sample_pair_ids": matched_pair_ids[:30],
                        "sample_pairs": [
                            {
                                "pair_id": pair_id,
                                "rows": list(pair_groups[pair_id]),
                                "ratio": ratio,
                            }
                            for pair_id in matched_pair_ids[:20]
                        ],
                        "benign_explanations": [
                            "可能是阈值化、归一化、分箱或整数比例编码导致的合法重复比例。",
                            "若该比例跨多个独立患者或样本精确重复，应检查是否来自派生或复制过程。",
                        ],
                        "pressure_test_result": "needs_repeated_within_pair_ratio_review",
                        "next_steps": [
                            "确认重复比例是否由方法学定义、阈值化或归一化流程预期产生。",
                            "如果比例代表独立测量结果，抽查原始数据和生成脚本。",
                        ],
                    }
                )
    return sorted(
        findings,
        key=lambda item: (-risk_rank(item["risk_level"]), -item["matched_pair_groups"]),
    )[: params.max_findings_per_category]


def row_offset_rounding_bias_findings(
    sheet: SheetVectors, params: PairForensicsParams
) -> list[dict[str, Any]]:
    findings = []
    for col, values_by_row in sorted(sheet.numeric_columns.items()):
        if is_low_information_numeric_column(values_by_row, params):
            continue
        rows = sorted(values_by_row)
        for offset in candidate_offsets(rows, params):
            pairs = common_offset_pairs(rows, offset)
            exact = []
            rounded_second = []
            upward_changes = []
            comparable = []
            for left_row, right_row in pairs:
                left = values_by_row[left_row]
                right = values_by_row[right_row]
                comparable.append((left_row, right_row))
                if left == right:
                    exact.append((left_row, right_row))
                if decimal_places(right) <= 2 and decimal_places(left) >= 6:
                    rounded_second.append((left_row, right_row))
                if right > left:
                    upward_changes.append((left_row, right_row))
            if len(comparable) < params.min_pairs:
                continue
            exact_rate = len(exact) / len(comparable)
            rounded_rate = len(rounded_second) / len(comparable)
            upward_rate = len(upward_changes) / max(
                1,
                len(
                    [
                        pair
                        for pair in comparable
                        if values_by_row[pair[0]] != values_by_row[pair[1]]
                    ]
                ),
            )
            # This is intentionally stricter than scalar/ratio reuse. Precision
            # shifts are noisy in spreadsheets; only emit when exact reuse,
            # coarse second-block values, and directional changes co-occur.
            if exact_rate < 0.5 or rounded_rate < 0.3 or upward_rate < 0.75:
                continue
            findings.append(
                {
                    "finding_id": None,
                    "category": "row_offset_partial_copy_rounding_bias",
                    "risk_level": "high",
                    "confidence": "medium",
                    "workbook": sheet.workbook,
                    "sheet": sheet.sheet,
                    "row_offset": offset,
                    "column": col_to_name(col),
                    "column_label": column_label(sheet, col),
                    "overlap_pairs": len(comparable),
                    "exact_reuse_pairs": len(exact),
                    "rounded_second_block_pairs": len(rounded_second),
                    "upward_change_rate": round(upward_rate, 4),
                    "exact_reuse_rate": round(exact_rate, 4),
                    "rounded_second_block_rate": round(rounded_rate, 4),
                    "sample_exact_pairs": [
                        {"left_row": left, "right_row": right}
                        for left, right in exact[:10]
                    ],
                    "sample_rounded_pairs": [
                        {"left_row": left, "right_row": right}
                        for left, right in rounded_second[:10]
                    ],
                    "benign_explanations": [
                        "可能是人工四舍五入、单位换算后展示值或不同精度导出的合法结果。",
                        "若后半区代表新增独立样本，精度骤降和单向修改需要人工复核。",
                    ],
                    "pressure_test_result": "needs_partial_copy_rounding_review",
                    "next_steps": [
                        "比较前后区间的原始导出精度和修改方向。",
                        "确认后半区样本是否具有独立原始记录。",
                    ],
                }
            )
    return sorted(
        findings,
        key=lambda item: (-risk_rank(item["risk_level"]), -item["exact_reuse_pairs"]),
    )[: params.max_findings_per_category]


def _is_narrow_value_range(values: list[float]) -> bool:
    """Return True when IQR < 0.01 × median, indicating a high-precision instrument range."""
    if len(values) < 2:
        return False
    median = statistics.median(values)
    if median <= 0:
        return False
    q1, _, q3 = statistics.quantiles(values, n=4)
    iqr = q3 - q1
    return iqr < 0.01 * median


def _is_stable_high_correlation(
    left: list[float], right: list[float]
) -> bool:
    """Return True when columns are highly correlated (r>0.99) with near-constant difference."""
    if len(left) < 3:
        return False
    try:
        corr = statistics.correlation(left, right)
    except (ValueError, statistics.StatisticsError):
        return False
    diff_std = statistics.stdev([a - b for a, b in zip(left, right)])
    return corr > 0.99 and diff_std < 0.001


def paired_difference_spread_findings(
    sheet: SheetVectors, params: PairForensicsParams
) -> list[dict[str, Any]]:
    """Detect column pairs whose paired differences are anomalously narrow.

    For every pair of numeric columns (A, B) sharing >= min_pairs rows,
    compute d_i = A_i - B_i.  Flag when the spread of |d_i| is tiny
    relative to the magnitude of the underlying data -- a pattern
    inconsistent with independent biological measurements.
    """
    columns = sorted(sheet.numeric_columns)
    findings = []
    for left_index, left_col in enumerate(columns):
        left_values = sheet.numeric_columns[left_col]
        if is_low_information_numeric_column(left_values, params):
            continue
        for right_col in columns[left_index + 1 :]:
            right_values = sheet.numeric_columns[right_col]
            if is_low_information_numeric_column(right_values, params):
                continue
            common_rows = sorted(set(left_values).intersection(right_values))
            if len(common_rows) < params.min_pairs:
                continue
            diffs: list[float] = []
            abs_a_list: list[float] = []
            abs_b_list: list[float] = []
            all_values: list[float] = []
            for row in common_rows:
                a_val = float(left_values[row])
                b_val = float(right_values[row])
                diffs.append(a_val - b_val)
                abs_a_list.append(abs(a_val))
                abs_b_list.append(abs(b_val))
                all_values.extend([abs(a_val), abs(b_val)])
            abs_diffs = [abs(d) for d in diffs]
            mean_magnitude = sum(
                abs_a_list[i] + abs_b_list[i] for i in range(len(abs_a_list))
            ) / (2 * len(abs_a_list))
            max_abs_diff = max(abs_diffs)
            min_abs_diff = min(abs_diffs)
            data_range = max(all_values) - min(all_values) if all_values else 0.0
            diff_spread = max_abs_diff - min_abs_diff
            # Condition 1: max |d_i| < 5% of mean magnitude of the data.
            narrow_vs_magnitude = (
                mean_magnitude > 0 and max_abs_diff < 0.05 * mean_magnitude
            )
            # Condition 2: spread of |d_i| is narrow relative to combined data range
            # AND the absolute differences are themselves small relative to that range.
            # Both sub-conditions are required so that a constant-offset column pair
            # (where diff_spread == 0 but |d_i| is large) does not false-trigger.
            narrow_vs_range = (
                data_range > 0
                and diff_spread < 0.01 * data_range
                and max_abs_diff < 0.01 * data_range
            )
            if not (narrow_vs_magnitude or narrow_vs_range):
                continue
            # High-precision instrument filter: downgrade when column pair
            # exhibits characteristics of plate-reader / spectrophotometer
            # output (narrow value range or stable high correlation).
            left_raw = [float(left_values[row]) for row in common_rows]
            right_raw = [float(right_values[row]) for row in common_rows]
            instrument_artifact = (
                _is_narrow_value_range(left_raw + right_raw)
                or _is_stable_high_correlation(left_raw, right_raw)
            )
            if instrument_artifact:
                risk = "low"
                artifact_likelihood = "high"
                artifact_reason = "high-precision instrument or numerical rounding artifact"
            else:
                risk = "high" if len(common_rows) >= 10 else "medium"
                artifact_likelihood = None
                artifact_reason = None
            sample_pairs = [
                {
                    "row": row,
                    "value_a": normalized_number(left_values[row]),
                    "value_b": normalized_number(right_values[row]),
                    "difference": normalized_number(Decimal(str(diffs[i]))),
                }
                for i, row in enumerate(common_rows[:5])
            ]
            finding: dict[str, Any] = {
                "finding_id": None,
                "category": "paired_difference_too_narrow",
                "risk_level": risk,
                "confidence": "high",
                "workbook": sheet.workbook,
                "sheet": sheet.sheet,
                "column_a": col_to_name(left_col),
                "column_b": col_to_name(right_col),
                "column_labels": [
                    column_label(sheet, left_col),
                    column_label(sheet, right_col),
                ],
                "pair_count": len(common_rows),
                "max_abs_diff": round(max_abs_diff, 8),
                "min_abs_diff": round(min_abs_diff, 8),
                "data_range": round(data_range, 8),
                "sample_pairs": sample_pairs,
                "benign_explanations": [
                    "配对测量可能来自同一仪器的高精度重复读数",
                    "配对差异过窄可能是技术重复而非生物学重复",
                ],
                "pressure_test_result": "needs_paired_difference_independence_review",
                "next_steps": [
                    "确认配对数据是否为独立生物学重复",
                    "要求提供原始仪器输出文件验证测量独立性",
                ],
            }
            if instrument_artifact:
                finding["artifact_likelihood"] = artifact_likelihood
                finding["artifact_reason"] = artifact_reason
            findings.append(finding)
    return sorted(
        findings, key=lambda item: (-risk_rank(item["risk_level"]), -item["pair_count"])
    )[: params.max_findings_per_category]


# ── Cross-block paired difference detector ───────────────────────────


def _find_block_separator_rows(sheet: SheetVectors) -> list[int]:
    """Find rows that act as separators between numeric blocks.

    A separator row has text cells but NO numeric cells in the same row.
    Only rows between numeric data (not leading headers) are considered.

    Strategy:
    1. Collect all rows that have numeric cells (``numeric_rows``).
    2. Collect all rows that have text cells but no numeric cells (``text_only_rows``).
    3. A text-only row is a separator if it falls within the numeric data range
       (between the first and last numeric row) AND spans at least 2 columns
       (single-cell labels like a row number are ignored).
    """
    numeric_rows: set[int] = set()
    for col_rows in sheet.numeric_columns.values():
        numeric_rows.update(col_rows.keys())

    if not numeric_rows:
        return []

    min_num_row = min(numeric_rows)
    max_num_row = max(numeric_rows)

    text_only_rows: dict[int, int] = {}  # row → count of text cells
    for col, text_entries in sheet.text_columns.items():
        for row, _text in text_entries:
            if row <= min_num_row or row >= max_num_row:
                continue
            if row in numeric_rows:
                continue
            text_only_rows[row] = text_only_rows.get(row, 0) + 1

    # A separator must have text in at least 2 columns (skip single-cell labels)
    separators = sorted(row for row, count in text_only_rows.items() if count >= 2)
    return separators


def _group_into_blocks(
    numeric_rows: list[int],
    separators: list[int],
) -> list[list[int]]:
    """Split sorted numeric rows into contiguous blocks separated by separator rows."""
    sep_set = set(separators)
    blocks: list[list[int]] = []
    current: list[int] = []
    for row in numeric_rows:
        # Check if any separator falls between the last row in current block and this row
        if current:
            gap_rows = range(current[-1] + 1, row)
            if any(r in sep_set for r in gap_rows):
                blocks.append(current)
                current = []
        current.append(row)
    if current:
        blocks.append(current)
    return blocks


def cross_block_paired_diff_findings(
    sheet: SheetVectors,
    params: PairForensicsParams,
) -> list[dict[str, Any]]:
    """Detect paired differences that are anomalously narrow across row blocks.

    Scientific data sheets often stack multiple experimental groups (cell lines,
    treatment conditions, patient cohorts) vertically with text separator rows
    between them.  The same-column measurements in different blocks should be
    independent — if all paired differences at corresponding positions are
    suspiciously small (e.g., all within ±0.02 OD), this is inconsistent with
    truly independent experiments.

    This detector:
    1. Identifies text separator rows within the numeric data range.
    2. Groups numeric rows into contiguous blocks.
    3. For each pair of blocks with the same structure (same column set,
       same row count), compares corresponding columns position-by-position.
    4. Applies the same narrow-diff thresholds as the within-row detector.
    """
    separators = _find_block_separator_rows(sheet)
    if not separators:
        return []

    # Collect all numeric rows
    all_numeric_rows: set[int] = set()
    for col_rows in sheet.numeric_columns.values():
        all_numeric_rows.update(col_rows.keys())
    sorted_numeric_rows = sorted(all_numeric_rows)

    blocks = _group_into_blocks(sorted_numeric_rows, separators)
    # Filter: blocks need at least 3 rows for a meaningful paired comparison
    # (lower than min_pairs because cross-block structure already encodes pairing)
    blocks = [b for b in blocks if len(b) >= 3]
    if len(blocks) < 2:
        return []

    findings: list[dict[str, Any]] = []

    for i, block_a in enumerate(blocks):
        for j, block_b in enumerate(blocks):
            if j <= i:
                continue
            # Blocks must have the same number of rows
            if len(block_a) != len(block_b):
                continue

            # Find common numeric columns in both blocks
            cols_a: set[int] = set()
            for col, col_rows in sheet.numeric_columns.items():
                if all(r in col_rows for r in block_a):
                    cols_a.add(col)
            cols_b: set[int] = set()
            for col, col_rows in sheet.numeric_columns.items():
                if all(r in col_rows for r in block_b):
                    cols_b.add(col)

            common_cols = sorted(cols_a & cols_b)
            if len(common_cols) < 2:
                continue

            # Compare corresponding columns position-by-position
            for col in common_cols:
                if is_low_information_numeric_column(
                    {r: sheet.numeric_columns[col][r] for r in block_a},
                    params,
                ):
                    continue

                vals_a = [float(sheet.numeric_columns[col][r]) for r in block_a]
                vals_b = [float(sheet.numeric_columns[col][r]) for r in block_b]

                diffs = [a - b for a, b in zip(vals_a, vals_b)]
                abs_diffs = [abs(d) for d in diffs]
                all_values = [abs(v) for v in vals_a + vals_b]

                n = len(diffs)
                mean_magnitude = sum(
                    abs(a) + abs(b) for a, b in zip(vals_a, vals_b)
                ) / (2 * n)
                max_abs_diff = max(abs_diffs)
                min_abs_diff = min(abs_diffs)
                data_range = max(all_values) - min(all_values) if all_values else 0.0
                diff_spread = max_abs_diff - min_abs_diff

                # Same thresholds as within-row paired_difference_spread
                narrow_vs_magnitude = (
                    mean_magnitude > 0 and max_abs_diff < 0.05 * mean_magnitude
                )
                narrow_vs_range = (
                    data_range > 0
                    and diff_spread < 0.01 * data_range
                    and max_abs_diff < 0.01 * data_range
                )

                if not (narrow_vs_magnitude or narrow_vs_range):
                    continue

                risk = "high" if n >= 10 else "medium"
                col_label = column_label(sheet, col)
                sample_pairs = []
                for k in range(min(5, n)):
                    sample_pairs.append(
                        {
                            "position": k + 1,
                            "block_a_row": block_a[k],
                            "block_b_row": block_b[k],
                            "value_a": vals_a[k],
                            "value_b": vals_b[k],
                            "difference": round(diffs[k], 10),
                        }
                    )

                findings.append(
                    {
                        "category": "cross_block_paired_diff_too_narrow",
                        "risk_level": risk,
                        "confidence": "high",
                        "workbook": sheet.workbook,
                        "sheet": sheet.sheet,
                        "column": col,
                        "column_label": col_label,
                        "block_a_rows": block_a,
                        "block_b_rows": block_b,
                        "pair_count": n,
                        "max_abs_diff": round(max_abs_diff, 10),
                        "min_abs_diff": round(min_abs_diff, 10),
                        "data_range": round(data_range, 10),
                        "mean_magnitude": round(mean_magnitude, 10),
                        "sample_pairs": sample_pairs,
                        "benign_explanations": [
                            "两个 block 可能是同一实验的重复孔/技术重复，并非独立生物学样本",
                            "如果两个 block 的数据来自同一块板的连续孔，小的跨块差异可能是仪器精度限制",
                            "检查 sheet 中是否有文本分隔行表明两个 block 代表不同实验条件/细胞系/处理组",
                        ],
                        "pressure_test_result": "needs_block_semantics_review",
                        "next_steps": [
                            "确认两个 block 分别代表什么实验条件（细胞系、处理组、时间点等）",
                            "如果来自不同条件，跨 block 的配对差异应反映生物学差异而非技术噪声",
                            "核对论文 Methods 中是否描述了跨 block 的数据处理方式",
                        ],
                    }
                )

    return sorted(
        findings, key=lambda item: (-risk_rank(item["risk_level"]), -item["pair_count"])
    )[: params.max_findings_per_category]


def assign_ids(findings: list[dict[str, Any]]) -> None:
    counters: Counter[str] = Counter()
    prefixes = {
        "row_offset_exact_reuse": "ROE",
        "row_offset_scalar_multiple": "ROS",
        "paired_ratio_reuse": "PRR",
        "duplicate_row_vector": "DRV",
        "long_format_paired_ratio_reuse": "LPR",
        "long_format_within_pair_ratio_enrichment": "LPE",
        "row_offset_partial_copy_rounding_bias": "RBR",
        "paired_difference_too_narrow": "PDS",
        "cross_block_paired_diff_too_narrow": "CBD",
    }
    for finding in findings:
        category = finding["category"]
        counters[category] += 1
        finding["finding_id"] = (
            f"{prefixes.get(category, 'PF')}-{counters[category]:04d}"
        )


def _finding_offset(finding: dict[str, Any]) -> Any:
    return finding.get("row_offset") or finding.get("pair_id_offset") or "-"


def _finding_relationship(finding: dict[str, Any]) -> Any:
    return finding.get("relationship_value") or finding.get("ratio_places") or "-"


def _finding_columns_text(finding: dict[str, Any]) -> str:
    columns = (
        finding.get("columns")
        or finding.get("column_pair")
        or finding.get("column")
        or []
    )
    if isinstance(columns, list):
        return ", ".join(str(item) for item in columns)
    return str(columns)


def _finding_support(finding: dict[str, Any]) -> tuple[int, int]:
    support = (
        finding.get("support_rows")
        or finding.get("matched_pairs")
        or finding.get("matched_pair_groups")
        or finding.get("duplicate_row_count")
        or finding.get("pair_count")
        or finding.get("exact_reuse_pairs")
        or 0
    )
    overlap = (
        finding.get("overlap_rows")
        or finding.get("overlap_pairs")
        or finding.get("overlap_pair_groups")
        or finding.get("duplicate_row_count")
        or 0
    )
    try:
        support_int = int(support)
    except (TypeError, ValueError):
        support_int = 0
    try:
        overlap_int = int(overlap)
    except (TypeError, ValueError):
        overlap_int = 0
    return support_int, overlap_int


def _cluster_key(finding: dict[str, Any]) -> tuple[str, str, str, str, str]:
    category = str(finding.get("category") or "-")
    workbook = str(finding.get("workbook") or "-")
    sheet = str(finding.get("sheet") or "-")
    offset = str(_finding_offset(finding))
    if category in {
        "row_offset_scalar_multiple",
        "row_offset_exact_reuse",
        "long_format_within_pair_ratio_enrichment",
        "row_offset_partial_copy_rounding_bias",
    }:
        signature = f"offset={offset};relationship={_finding_relationship(finding)}"
    elif category == "duplicate_row_vector":
        signature = f"width={finding.get('width', '-')}"
    else:
        signature = f"offset={offset}"
    return category, workbook, sheet, offset, signature


def _category_review_question(category: str) -> str:
    questions = {
        "paired_ratio_reuse": "同一 sheet 内多组列对在固定行偏移下复用相同比例，需确认这些行是否为独立样本或合法派生。",
        "long_format_paired_ratio_reuse": "long-format pair 在固定 pair id 偏移下复用相同比例，需确认 pair id 是否代表独立样本/患者。",
        "row_offset_scalar_multiple": "同一列在固定行偏移下呈固定倍数关系，需确认是否来自单位换算、归一化或复制派生。",
        "row_offset_exact_reuse": "同一列在固定行偏移下重复数值，需确认是否为合法重复测量或复制粘贴。",
        "duplicate_row_vector": "多行低宽度数值向量重复，需确认重复行是否代表同一样本、模板行或独立测量。",
        "long_format_within_pair_ratio_enrichment": "多个 long-format pair 出现相同比例富集，需确认是否由阈值化/归一化预期产生。",
        "row_offset_partial_copy_rounding_bias": "固定行偏移同时出现精度变化和部分复用，需确认后半区是否为独立原始记录。",
        "paired_difference_too_narrow": "配对列之间的差异分布异常狭窄，需确认配对测量是否来自独立生物学重复或高精度技术重复。",
        "cross_block_paired_diff_too_narrow": "被文本分隔行分开的两个数据块中，对应位置的列值差异异常狭窄，需确认两个块是否代表独立实验条件。",
    }
    return questions.get(
        category, "该 Source Data pattern 需要结合样本语义和原始记录人工复核。"
    )


def cluster_pair_forensics_findings(
    findings: list[dict[str, Any]],
    *,
    max_representatives: int = 8,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(
        list
    )
    for finding in findings:
        if isinstance(finding, dict):
            grouped[_cluster_key(finding)].append(finding)

    clusters: list[dict[str, Any]] = []
    for index, (key, group) in enumerate(
        sorted(
            grouped.items(),
            key=lambda item: (
                -max(
                    risk_rank(str(finding.get("risk_level", ""))) for finding in item[1]
                ),
                -len(item[1]),
                item[0],
            ),
        ),
        start=1,
    ):
        category, workbook, sheet, offset, signature = key
        representatives = sorted(
            group,
            key=lambda finding: (
                -risk_rank(str(finding.get("risk_level", ""))),
                -_finding_support(finding)[0],
                str(finding.get("finding_id", "")),
            ),
        )[:max_representatives]
        support_total = 0
        overlap_total = 0
        max_support_rate = 0.0
        columns_sample: list[str] = []
        for finding in group:
            support, overlap = _finding_support(finding)
            support_total += support
            overlap_total += overlap
            try:
                max_support_rate = max(
                    max_support_rate, float(finding.get("support_rate") or 0.0)
                )
            except (TypeError, ValueError):
                pass
            columns_text = _finding_columns_text(finding)
            if columns_text and columns_text not in columns_sample:
                columns_sample.append(columns_text)

        risk_level = max(
            (str(finding.get("risk_level", "medium")) for finding in group),
            key=risk_rank,
            default="medium",
        )
        cluster_id = f"PFC-{index:04d}"
        representative_ids = [
            str(finding.get("finding_id"))
            for finding in representatives
            if finding.get("finding_id")
        ]
        first = representatives[0] if representatives else group[0]
        clusters.append(
            {
                "cluster_id": cluster_id,
                "category": category,
                "risk_level": risk_level,
                "confidence": "high"
                if any(finding.get("confidence") == "high" for finding in group)
                else "medium",
                "workbook": workbook,
                "sheet": sheet,
                "pattern_signature": signature,
                "offset": offset,
                "finding_count": len(group),
                "support_total": support_total,
                "overlap_total": overlap_total,
                "max_support_rate": round(max_support_rate, 4),
                "columns_sample": columns_sample[:12],
                "representative_finding_ids": representative_ids,
                "evidence_refs": [
                    f"source_data_pair_forensics.json:{finding_id}"
                    for finding_id in representative_ids
                ],
                "review_question": _category_review_question(category),
                "benign_explanations": (first.get("benign_explanations") or [])[:3],
                "next_steps": (first.get("next_steps") or [])[:4],
            }
        )
    return clusters


def pair_forensics_review_tasks(
    clusters: list[dict[str, Any]], *, max_tasks: int = 20
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for cluster in clusters:
        if isinstance(cluster, dict):
            grouped[
                (
                    str(cluster.get("category") or "-"),
                    str(cluster.get("workbook") or "-"),
                    str(cluster.get("sheet") or "-"),
                )
            ].append(cluster)

    task_groups = sorted(
        grouped.items(),
        key=lambda item: (
            -max(risk_rank(str(cluster.get("risk_level", ""))) for cluster in item[1]),
            -sum(int(cluster.get("finding_count") or 0) for cluster in item[1]),
            item[0],
        ),
    )
    tasks = []
    for index, (key, group) in enumerate(task_groups[:max_tasks], start=1):
        category, workbook, sheet = key
        group = sorted(
            group,
            key=lambda cluster: (
                -risk_rank(str(cluster.get("risk_level", ""))),
                -int(cluster.get("finding_count") or 0),
                str(cluster.get("cluster_id", "")),
            ),
        )
        risk_level = max(
            (str(cluster.get("risk_level", "medium")) for cluster in group),
            key=risk_rank,
            default="medium",
        )
        finding_count = sum(int(cluster.get("finding_count") or 0) for cluster in group)
        cluster_ids = [
            str(cluster.get("cluster_id"))
            for cluster in group
            if cluster.get("cluster_id")
        ]
        representative_ids: list[str] = []
        evidence_refs: list[str] = []
        signatures: list[str] = []
        for cluster in group:
            for finding_id in cluster.get("representative_finding_ids") or []:
                if finding_id not in representative_ids:
                    representative_ids.append(str(finding_id))
            for ref in cluster.get("evidence_refs") or []:
                if ref not in evidence_refs:
                    evidence_refs.append(str(ref))
            signature = str(cluster.get("pattern_signature") or "")
            if signature and signature not in signatures:
                signatures.append(signature)
        tasks.append(
            {
                "task_id": f"PFRT-{index:03d}",
                "priority": risk_level,
                "cluster_id": cluster_ids[0] if cluster_ids else None,
                "cluster_ids": cluster_ids[:12],
                "cluster_count": len(group),
                "category": category,
                "workbook": workbook,
                "sheet": sheet,
                "finding_count": finding_count,
                "pattern_signatures": signatures[:12],
                "question": (
                    f"复核 {workbook} / {sheet} 的 {category} patterns："
                    f"{len(group)} 个 clusters、{finding_count} 条 raw findings。"
                    f"{_category_review_question(category)}"
                ),
                "evidence_refs": evidence_refs[:12],
                "representative_finding_ids": representative_ids[:12],
            }
        )
    return tasks


def analyze_xlsx_root(xlsx_root: Path, params: PairForensicsParams) -> dict[str, Any]:
    errors = []
    scalar_findings = []
    ratio_findings = []
    duplicate_rows = []
    long_ratio_reuse = []
    long_ratio_enrichment = []
    rounding_bias = []
    narrow_diff_spread = []
    cross_block_narrow = []
    workbook_count = 0
    sheet_count = 0
    for workbook_path in sorted(xlsx_root.glob("*.xlsx")):
        workbook_count += 1
        try:
            sheets = parse_workbook_vectors(workbook_path)
        except Exception as exc:
            errors.append(
                {
                    "workbook": workbook_path.name,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        sheet_count += len(sheets)
        for sheet in sheets:
            scalar_findings.extend(row_offset_scalar_findings(sheet, params))
            ratio_findings.extend(paired_ratio_reuse_findings(sheet, params))
            duplicate_rows.extend(duplicate_row_vector_findings(sheet, params))
            long_ratio_reuse.extend(
                long_format_paired_ratio_reuse_findings(sheet, params)
            )
            long_ratio_enrichment.extend(
                long_format_within_pair_ratio_enrichment_findings(sheet, params)
            )
            rounding_bias.extend(row_offset_rounding_bias_findings(sheet, params))
            narrow_diff_spread.extend(paired_difference_spread_findings(sheet, params))
            cross_block_narrow.extend(cross_block_paired_diff_findings(sheet, params))

    findings = [
        *scalar_findings,
        *ratio_findings,
        *duplicate_rows,
        *long_ratio_reuse,
        *long_ratio_enrichment,
        *rounding_bias,
        *narrow_diff_spread,
        *cross_block_narrow,
    ]
    findings = sorted(
        findings,
        key=lambda item: (
            -risk_rank(item["risk_level"]),
            str(item.get("workbook")),
            str(item.get("sheet")),
        ),
    )
    assign_ids(findings)
    priority_findings = [
        finding
        for finding in findings
        if risk_rank(finding.get("risk_level", "")) >= 2
        and finding.get("artifact_likelihood") != "high"
    ]
    finding_clusters = cluster_pair_forensics_findings(priority_findings)
    review_tasks = pair_forensics_review_tasks(finding_clusters)
    by_category = Counter(finding["category"] for finding in findings)
    return {
        "schema_version": "1.0",
        "created_by": "engine/static_audit/tools/source_data_pair_forensics.py",
        "inputs": {"xlsx_root": str(xlsx_root)},
        "parameters": {
            "min_pairs": params.min_pairs,
            "min_support": params.min_support,
            "ratio_places": params.ratio_places,
            "max_offset": params.max_offset,
            "max_findings_per_category": params.max_findings_per_category,
            "min_duplicate_row_width": params.min_duplicate_row_width,
        },
        "summary": {
            "workbook_count": workbook_count,
            "sheet_count": sheet_count,
            "findings": len(findings),
            "priority_findings": len(priority_findings),
            "finding_clusters": len(finding_clusters),
            "review_tasks": len(review_tasks),
            "row_offset_scalar_findings": len(scalar_findings),
            "paired_ratio_reuse_findings": len(ratio_findings),
            "duplicate_row_vector_findings": len(duplicate_rows),
            "long_format_paired_ratio_reuse_findings": len(long_ratio_reuse),
            "long_format_within_pair_ratio_enrichment_findings": len(
                long_ratio_enrichment
            ),
            "rounding_bias_findings": len(rounding_bias),
            "paired_difference_too_narrow_findings": len(narrow_diff_spread),
            "cross_block_paired_diff_too_narrow_findings": len(cross_block_narrow),
            "by_category": dict(by_category),
            "errors": len(errors),
        },
        "findings": findings,
        "priority_findings": priority_findings,
        "finding_clusters": finding_clusters,
        "review_tasks": review_tasks,
        "row_offset_scalar_findings": scalar_findings,
        "paired_ratio_reuse_findings": ratio_findings,
        "duplicate_row_vector_findings": duplicate_rows,
        "long_format_paired_ratio_reuse_findings": long_ratio_reuse,
        "long_format_within_pair_ratio_enrichment_findings": long_ratio_enrichment,
        "rounding_bias_findings": rounding_bias,
        "paired_difference_too_narrow_findings": narrow_diff_spread,
        "cross_block_paired_diff_too_narrow_findings": cross_block_narrow,
        "errors": errors,
        "limitations": [
            "该工具只识别 XLSX 中的通用行偏移、配对比例复用、long-format 成对比例复用和低宽度行重复模式，不判断最终科研诚信。",
            "行是否代表独立样本、患者或技术重复需要结合 sheet 注释、论文方法和原始仪器输出人工确认。",
            "ratio_places 会影响 paired ratio reuse 的敏感度；高精度与展示值四舍五入场景应分开解释。",
            "低信息数值列会被视为分组/类别/编号候选并排除在连续测量列检测之外，可能降低二分类测量场景的敏感度。",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect generic paired-cohort and row-offset patterns in XLSX Source Data."
    )
    parser.add_argument(
        "xlsx_root", help="Directory containing .xlsx source data files."
    )
    parser.add_argument(
        "--output", required=True, help="Output source_data_pair_forensics.json path."
    )
    parser.add_argument("--min-pairs", type=int, default=8)
    parser.add_argument("--min-support", type=float, default=0.95)
    parser.add_argument("--ratio-places", type=int, default=4)
    parser.add_argument("--max-offset", type=int, default=80)
    parser.add_argument("--max-findings-per-category", type=int, default=50)
    parser.add_argument("--min-duplicate-row-width", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    xlsx_root = Path(args.xlsx_root).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    params = PairForensicsParams(
        min_pairs=max(2, args.min_pairs),
        min_support=min(1.0, max(0.0, args.min_support)),
        ratio_places=max(1, args.ratio_places),
        max_offset=max(1, args.max_offset),
        max_findings_per_category=max(1, args.max_findings_per_category),
        min_duplicate_row_width=max(2, args.min_duplicate_row_width),
    )
    result = analyze_xlsx_root(xlsx_root, params)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output": str(output), **result["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
