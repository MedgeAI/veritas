"""Paired-ratio and row-offset reuse detectors."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from itertools import combinations
from typing import Any

from engine.static_audit.tools.source_data_findings import (
    SheetVectors,
    _extract_raw_data_samples,
    col_to_name,
    column_label,
    is_summary_statistic_pair,
)
from engine.static_audit.tools.source_data_profile import normalized_number

from ._shared import (
    PairForensicsParams,
    SheetNumericIndex,
    bitset_to_rows,
    candidate_offsets,
    common_rows as index_common_rows,
    common_offset_pairs,
    decimal_places,
    ensure_sheet_numeric_index,
    has_consecutive_run,
    is_low_information_numeric_column,
    numeric_value_diversity,
    ratio_key,
    risk_rank,
    same_fraction_integer_delta,
)
from .profile_helpers import _is_semantic_equivalent_pair


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
                    "_matched_rows": set(),
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
                group["_matched_rows"].update([left_row, right_row])
    findings = list(grouped.values())
    for finding in findings:
        matched_rows = sorted(finding.pop("_matched_rows"))
        finding["raw_data_samples"] = _extract_raw_data_samples(sheet, matched_rows)
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
                        "raw_data_samples": _extract_raw_data_samples(
                            sheet, sorted(matched_rows)
                        ),
                    }
                )
    return sorted(
        findings,
        key=lambda item: (-risk_rank(item["risk_level"]), -item["matched_pairs"]),
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
    return paired  # type: ignore[assignment,operator]


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


def copy_paste_modify_findings(
    source: SheetVectors | SheetNumericIndex,
    params: PairForensicsParams,
    *,
    performance: dict[str, Any] | None = None,
    detector_skips: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Detect column pairs where values share the same fractional part but differ by a constant integer.

    This is the P2 detector: when a column is copy-pasted and only the integer
    part is modified (e.g., 3.14 -> 7.14), the fractional part is preserved and
    the integer delta is constant across matched rows.
    """
    del detector_skips
    index = ensure_sheet_numeric_index(source, params)
    sheet = index.sheet
    findings = []
    for left_col, right_col in combinations(index.valid_columns, 2):
        left_values = index.values_by_col[left_col]
        right_values = index.values_by_col[right_col]
        common = index_common_rows(index, left_col, right_col)
        if len(common) < 3:
            continue
        if performance is not None:
            performance["copy_paste_modify_column_pairs"] = (
                int(performance.get("copy_paste_modify_column_pairs", 0)) + 1
            )
        delta_groups: dict[int, list[int]] = defaultdict(list)
        shared_fraction_keys = (
            set(index.frac_rows_by_col.get(left_col, {}))
            & set(index.frac_rows_by_col.get(right_col, {}))
        )
        for fraction_key in shared_fraction_keys:
            # A decimal fraction of exactly zero is extremely common in exported
            # spreadsheets and tends to represent formatting, not pasted mantissas.
            if fraction_key == "0":
                continue
            candidate_bits = (
                index.frac_rows_by_col[left_col][fraction_key]
                & index.frac_rows_by_col[right_col][fraction_key]
            )
            for row in bitset_to_rows(candidate_bits):
                delta = same_fraction_integer_delta(
                    left_values[row], right_values[row]
                )
                if delta is not None:
                    delta_groups[delta].append(row)
        common_positions = {row: i for i, row in enumerate(common)}
        for delta, matched_rows in delta_groups.items():
            count = len(matched_rows)
            comparable = len(common)
            rate = count / comparable if comparable else 0.0
            positions = [common_positions[r] for r in matched_rows]
            if not (
                has_consecutive_run(positions, min_run=3)
                or (count >= 5 and rate >= 0.6)
            ):
                continue
            risk = "high" if (count >= 10 and rate >= 0.95) else "medium"
            confidence = "high" if rate >= 0.95 else "medium"
            formula_involved = (
                left_col in sheet.formulas_by_column
                or right_col in sheet.formulas_by_column
            )
            if formula_involved:
                risk = "low"
            matched_row_set = sorted(matched_rows)
            summary_pair = is_summary_statistic_pair(
                sheet, left_col, right_col, matched_row_set
            )
            left_lbl = column_label(sheet, left_col)
            right_lbl = column_label(sheet, right_col)
            semantic_pair = _is_semantic_equivalent_pair(left_lbl, right_lbl)
            if summary_pair or semantic_pair:
                artifact_likelihood = "high"
                if summary_pair:
                    artifact_reason = (
                        f"summary-statistic pair: {left_lbl} vs {right_lbl}"
                    )
                else:
                    artifact_reason = (
                        f"semantic-equivalent pair: {left_lbl} vs {right_lbl}"
                    )
            else:
                artifact_likelihood = "unknown"
                artifact_reason = None
            findings.append(
                {
                    "finding_id": None,
                    "category": "copy_paste_modify",
                    "risk_level": risk,
                    "confidence": confidence,
                    "workbook": sheet.workbook,
                    "sheet": sheet.sheet,
                    "support_rows": count,
                    "overlap_rows": comparable,
                    "support_rate": round(rate, 4),
                    "columns": [col_to_name(left_col), col_to_name(right_col)],
                    "column_labels": [left_lbl, right_lbl],
                    "relationship_value": str(delta),
                    "sample_pairs": [
                        {
                            "row": row,
                            "left": normalized_number(left_values[row]),
                            "right": normalized_number(right_values[row]),
                            "delta": delta,
                        }
                        for row in matched_rows[:20]
                    ],
                    "benign_explanations": [
                        "可能是合法的单位换算（如 kg→g，整数部分改变但小数部分保留）。",
                        "可能是数据归一化或基线校正的结果。",
                    ],
                    "pressure_test_result": "needs_copy_paste_modify_review",
                    "next_steps": [
                        "确认两列是否代表不同的测量条件或单位。",
                        "核对整数差值是否有物理解释。",
                        "要求学生解释两列数据的来源关系。",
                    ],
                    "raw_data_samples": _extract_raw_data_samples(
                        sheet, matched_row_set
                    ),
                    "artifact_likelihood": artifact_likelihood,
                    "artifact_reason": artifact_reason,
                }
            )
    return sorted(
        findings,
        key=lambda item: (-risk_rank(item["risk_level"]), -item["support_rows"]),
    )[: params.max_findings_per_category]


def shifted_paste_findings(
    source: SheetVectors | SheetNumericIndex,
    params: PairForensicsParams,
    *,
    performance: dict[str, Any] | None = None,
    detector_skips: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Detect column pairs with copy-paste-modify at a positional lag offset.

    This is the P1 detector: when a column is copy-pasted into another column
    but shifted by a fixed number of rows (e.g., pasted starting at row 5
    instead of row 2), the fractional parts still match but values are compared
    at a row offset rather than at the same row.
    """
    del detector_skips
    index = ensure_sheet_numeric_index(source, params)
    sheet = index.sheet
    findings = []
    for left_col, right_col in combinations(index.valid_columns, 2):
        left_values = index.values_by_col[left_col]
        right_values = index.values_by_col[right_col]
        for lag in (-3, -2, -1, 1, 2, 3):
            right_aligned_bits = (
                index.row_bitset_by_col[right_col] >> lag
                if lag > 0
                else index.row_bitset_by_col[right_col] << (-lag)
            )
            comparable_bits = index.row_bitset_by_col[left_col] & right_aligned_bits
            comparable_rows = bitset_to_rows(comparable_bits)
            if len(comparable_rows) < 3:
                continue
            if performance is not None:
                performance["shifted_paste_column_lags"] = (
                    int(performance.get("shifted_paste_column_lags", 0)) + 1
                )
            # Group matched rows by (lag, delta).
            delta_groups: dict[int, list[int]] = defaultdict(list)
            shared_fraction_keys = (
                set(index.frac_rows_by_col.get(left_col, {}))
                & set(index.frac_rows_by_col.get(right_col, {}))
            )
            for fraction_key in shared_fraction_keys:
                if fraction_key == "0":
                    continue
                right_fraction_bits = index.frac_rows_by_col[right_col][fraction_key]
                right_fraction_aligned = (
                    right_fraction_bits >> lag
                    if lag > 0
                    else right_fraction_bits << (-lag)
                )
                candidate_bits = (
                    index.frac_rows_by_col[left_col][fraction_key]
                    & right_fraction_aligned
                    & comparable_bits
                )
                for row in bitset_to_rows(candidate_bits):
                    delta = same_fraction_integer_delta(
                        left_values[row], right_values[row + lag]
                    )
                    if delta is not None:
                        delta_groups[delta].append(row)
            # Build position index for consecutive-run check.
            comparable_positions = {
                row: i for i, row in enumerate(comparable_rows)
            }
            for delta, matched_rows in delta_groups.items():
                count = len(matched_rows)
                comparable = len(comparable_rows)
                rate = count / comparable if comparable else 0.0
                positions = [comparable_positions[r] for r in matched_rows]
                if not (
                    has_consecutive_run(positions, min_run=4)
                    or (count >= 5 and rate >= 0.6)
                ):
                    continue
                risk = "high" if (count >= 10 and rate >= 0.95) else "medium"
                confidence = "high" if rate >= 0.95 else "medium"
                formula_involved = (
                    left_col in sheet.formulas_by_column
                    or right_col in sheet.formulas_by_column
                )
                if formula_involved:
                    risk = "low"
                matched_row_set = sorted(matched_rows)
                summary_pair = is_summary_statistic_pair(
                    sheet, left_col, right_col, matched_row_set
                )
                left_lbl = column_label(sheet, left_col)
                right_lbl = column_label(sheet, right_col)
                semantic_pair = _is_semantic_equivalent_pair(left_lbl, right_lbl)
                if summary_pair or semantic_pair:
                    artifact_likelihood = "high"
                    if summary_pair:
                        artifact_reason = (
                            f"summary-statistic pair: {left_lbl} vs {right_lbl}"
                        )
                    else:
                        artifact_reason = (
                            f"semantic-equivalent pair: {left_lbl} vs {right_lbl}"
                        )
                else:
                    artifact_likelihood = "unknown"
                    artifact_reason = None
                findings.append(
                    {
                        "finding_id": None,
                        "category": "shifted_paste",
                        "risk_level": risk,
                        "confidence": confidence,
                        "workbook": sheet.workbook,
                        "sheet": sheet.sheet,
                        "row_offset": lag,
                        "support_rows": count,
                        "overlap_rows": comparable,
                        "support_rate": round(rate, 4),
                        "columns": [
                            col_to_name(left_col),
                            col_to_name(right_col),
                        ],
                        "column_labels": [left_lbl, right_lbl],
                        "relationship_value": str(delta),
                        "sample_pairs": [
                            {
                                "left_row": row,
                                "right_row": row + lag,
                                "left": normalized_number(left_values[row]),
                                "right": normalized_number(
                                    right_values[row + lag]
                                ),
                                "delta": delta,
                            }
                            for row in matched_rows[:20]
                        ],
                        "benign_explanations": [
                            "可能是复制粘贴时的行错位（如从第5行粘贴到第8行）。",
                            "可能是数据整理过程中的移位操作。",
                        ],
                        "pressure_test_result": "needs_shifted_paste_review",
                        "next_steps": [
                            "确认两列数据的粘贴来源和起始行。",
                            "核对位移量是否与已知的数据操作一致。",
                            "要求学生解释两列数据的对应关系。",
                        ],
                        "raw_data_samples": _extract_raw_data_samples(
                            sheet, sorted(matched_rows)
                        ),
                        "artifact_likelihood": artifact_likelihood,
                        "artifact_reason": artifact_reason,
                    }
                )
    return sorted(
        findings,
        key=lambda item: (-risk_rank(item["risk_level"]), -item["support_rows"]),
    )[: params.max_findings_per_category]


def _sample_common_rows(rows: tuple[int, ...], limit: int = 7) -> list[int]:
    if len(rows) <= limit:
        return list(rows)
    step = (len(rows) - 1) / (limit - 1)
    return [rows[round(index * step)] for index in range(limit)]


def strict_linear_relation_findings(
    source: SheetVectors | SheetNumericIndex,
    params: PairForensicsParams,
    *,
    performance: dict[str, Any] | None = None,
    detector_skips: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Detect column pairs with strict linear relationship y = ax + b (R^2 >= 0.999999)."""
    del detector_skips
    index = ensure_sheet_numeric_index(source, params)
    sheet = index.sheet
    findings: list[dict[str, Any]] = []
    for x_col, y_col in combinations(index.valid_columns, 2):
        values_x = index.floats_by_col[x_col]
        values_y = index.floats_by_col[y_col]
        common_rows = index_common_rows(index, x_col, y_col)
        if len(common_rows) < 3:
            continue
        if performance is not None:
            performance["strict_linear_sampled_pairs"] = (
                int(performance.get("strict_linear_sampled_pairs", 0)) + 1
            )
        distinct_x = len({values_x[r] for r in common_rows})
        if distinct_x < 2:
            continue

        sample_rows = _sample_common_rows(common_rows)
        sample_pair: tuple[int, int] | None = None
        for left_index, left_row in enumerate(sample_rows):
            for right_row in sample_rows[left_index + 1 :]:
                if abs(values_x[right_row] - values_x[left_row]) > 1e-12:
                    sample_pair = (left_row, right_row)
                    break
            if sample_pair is not None:
                break
        if sample_pair is None:
            continue

        left_row, right_row = sample_pair
        sample_factor = (values_y[right_row] - values_y[left_row]) / (
            values_x[right_row] - values_x[left_row]
        )
        sample_intercept = values_y[left_row] - sample_factor * values_x[left_row]
        sample_limit = 1e-6 * max(
            1.0, max(abs(values_y[row]) for row in sample_rows)
        )
        if any(
            abs(values_y[row] - (sample_factor * values_x[row] + sample_intercept))
            > sample_limit
            for row in sample_rows
        ):
            continue

        if performance is not None:
            performance["strict_linear_verified_pairs"] = (
                int(performance.get("strict_linear_verified_pairs", 0)) + 1
            )

        # Least-squares linear fit: y = factor * x + intercept
        n = len(common_rows)
        sum_x = sum(values_x[r] for r in common_rows)
        sum_y = sum(values_y[r] for r in common_rows)
        sum_xy = sum(values_x[r] * values_y[r] for r in common_rows)
        sum_x2 = sum(values_x[r] ** 2 for r in common_rows)
        denom = n * sum_x2 - sum_x ** 2
        if abs(denom) < 1e-15:
            continue
        factor = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - factor * sum_x) / n

        # R-squared and max residual
        y_mean = sum_y / n
        ss_tot = sum((values_y[r] - y_mean) ** 2 for r in common_rows)
        ss_res = sum(
            (values_y[r] - (factor * values_x[r] + intercept)) ** 2
            for r in common_rows
        )
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-15 else 0.0
        max_abs_residual = max(
            abs(values_y[r] - (factor * values_x[r] + intercept))
            for r in common_rows
        )

        # Threshold check
        max_abs_y = max(abs(v) for v in values_y.values())
        residual_limit = 1e-6 * max(1.0, max_abs_y)
        if not (r2 >= 0.999999 and max_abs_residual <= residual_limit):
            continue
        if abs(intercept) <= residual_limit or abs(factor - 1.0) <= 1e-6:
            continue

        # Risk and confidence
        risk = "high" if (n >= 10 and r2 >= 0.9999999) else "medium"
        confidence = "high" if r2 >= 0.9999999 else "medium"

        # Artifact degradation: formula column
        formula_involved = (
            x_col in sheet.formulas_by_column
            or y_col in sheet.formulas_by_column
        )
        if formula_involved:
            risk = "low"

        # Artifact classification: summary pair / semantic pair
        common_row_set = sorted(common_rows)
        summary_pair = is_summary_statistic_pair(
            sheet, x_col, y_col, common_row_set
        )
        x_lbl = column_label(sheet, x_col)
        y_lbl = column_label(sheet, y_col)
        semantic_pair = _is_semantic_equivalent_pair(x_lbl, y_lbl)

        if summary_pair or semantic_pair:
            artifact_likelihood = "high"
            if summary_pair:
                artifact_reason = f"summary-statistic pair: {x_lbl} vs {y_lbl}"
            else:
                artifact_reason = f"semantic-equivalent pair: {x_lbl} vs {y_lbl}"
        else:
            artifact_likelihood = "unknown"
            artifact_reason = None

        # Build sample pairs (up to 20)
        sample_pairs = [
            {
                "row": row,
                "x": values_x[row],
                "y": values_y[row],
                "predicted": factor * values_x[row] + intercept,
                "residual": values_y[row] - (factor * values_x[row] + intercept),
            }
            for row in common_rows[:20]
        ]

        findings.append(
            {
                "finding_id": None,
                "category": "strict_linear_relation",
                "risk_level": risk,
                "confidence": confidence,
                "workbook": sheet.workbook,
                "sheet": sheet.sheet,
                "support_rows": n,
                "overlap_rows": n,
                "support_rate": 1.0,
                "columns": [col_to_name(x_col), col_to_name(y_col)],
                "column_labels": [x_lbl, y_lbl],
                "factor": str(factor),
                "intercept": str(intercept),
                "r_squared": round(r2, 10),
                "max_abs_residual": str(max_abs_residual),
                "sample_pairs": sample_pairs,
                "benign_explanations": [
                    "可能是合法的校准曲线或标准曲线关系。",
                    "可能是仪器的线性响应特性。",
                    "可能是已知的物理/化学线性关系（如 Beer-Lambert 定律）。",
                ],
                "pressure_test_result": "needs_strict_linear_independence_review",
                "next_steps": [
                    "确认 y 列是否为 x 列的线性派生（如校准、归一化）。",
                    "核对截距是否有物理意义（非零截距可能暗示系统误差）。",
                    "要求学生说明两列数据的独立测量过程。",
                ],
                "raw_data_samples": _extract_raw_data_samples(sheet, common_row_set),
                "artifact_likelihood": artifact_likelihood,
                "artifact_reason": artifact_reason,
            }
        )

    return sorted(
        findings,
        key=lambda item: (-risk_rank(item["risk_level"]), -item["support_rows"]),
    )[: params.max_findings_per_category]
