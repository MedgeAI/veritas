"""Fixed-relationship detection and relationship record construction."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

from engine.static_audit.tools.source_data_profile import normalized_number

from ._shared import (
    SheetVectors,
    _extract_raw_data_samples,
    col_to_name,
    column_label,
    common_rows,
    decimal_key,
    is_index_like_column,
)
from .summary_statistics import (
    is_summary_statistic_pair,
    is_time_event_design_pair,
)


def relationship_record(
    sheet: SheetVectors,
    relationship: str,
    left_col: int,
    right_col: int,
    value: str,
    support_rows: int,
    overlap_rows: int,
    rows: list[int],
    formula_cols: set[int],
) -> dict:
    formula_involved = left_col in formula_cols or right_col in formula_cols
    index_like = is_index_like_column(
        sheet.numeric_columns[left_col], rows
    ) and is_index_like_column(sheet.numeric_columns[right_col], rows)
    summary_pair = is_summary_statistic_pair(sheet, left_col, right_col, rows)
    event_artifact = is_time_event_design_pair(sheet, [left_col, right_col], rows)
    risk = (
        "low"
        if formula_involved or summary_pair
        else ("high" if support_rows >= 100 else "medium")
    )
    if index_like or event_artifact:
        risk = "low"

    # Calculate pattern_strength: mechanical regularity coverage, not造假概率
    support_rate = support_rows / overlap_rows if overlap_rows > 0 else 0
    if support_rate >= 0.99:
        pattern_strength = "complete"
    elif support_rate >= 0.8:
        pattern_strength = "strong"
    elif support_rate >= 0.5:
        pattern_strength = "moderate"
    else:
        pattern_strength = "weak"

    pattern_strength_reason = (
        f"{relationship}={value} covers {support_rows}/{overlap_rows} overlapping rows"
    )

    return {
        "finding_id": None,
        "category": relationship,
        "risk_level": risk,
        "confidence": "high",
        "workbook": sheet.workbook,
        "sheet": sheet.sheet,
        "column_pair": [col_to_name(left_col), col_to_name(right_col)],
        "column_labels": [
            column_label(sheet, left_col),
            column_label(sheet, right_col),
        ],
        "relationship_value": value,
        "overlap_rows": overlap_rows,
        "support_rows": support_rows,
        "support_rate": round(support_rate, 4),
        "pattern_strength": pattern_strength,
        "pattern_strength_reason": pattern_strength_reason,
        "artifact_likelihood": (
            "high"
            if index_like or summary_pair or event_artifact
            else ("medium" if formula_involved else "unknown")
        ),
        "artifact_reason": (
            "both columns look like sequential index/subject-id columns with a constant offset"
            if index_like
            else "Mean/Sum/N summary-statistics relationship"
            if summary_pair
            else "low-cardinality time/event or grouped endpoint columns"
            if event_artifact
            else ("formula column involved" if formula_involved else None)
        ),
        "sample_rows": rows[:20],
        "sample_pairs": [
            {
                "row": row,
                "left": normalized_number(sheet.numeric_columns[left_col][row]),
                "right": normalized_number(sheet.numeric_columns[right_col][row]),
            }
            for row in rows[:20]
        ],
        "formula_column_involved": formula_involved,
        "benign_explanations": [
            "可能是公式派生列、单位换算、归一化、体积/面积计算或设计矩阵编码。",
            "若列代表独立实验组或原始测量值，则机械固定关系需要人工复核。",
        ],
        "pressure_test_result": (
            "likely_index_or_design_artifact"
            if index_like
            else "likely_summary_statistic_derivation"
            if summary_pair
            else "likely_time_event_design_artifact"
            if event_artifact
            else "likely_formula_or_transform_if_column_semantics_confirmed"
            if formula_involved
            else "needs_semantics_and_formula_review"
        ),
        "next_steps": [
            "检查该列是否有公式或是否为派生指标。",
            "核对列标题和对应论文 figure panel。",
            "确认固定关系是否覆盖原始测量值而非派生列。",
        ],
        "raw_data_samples": _extract_raw_data_samples(sheet, rows),
    }


def fixed_relationship_findings(
    sheet: SheetVectors,
    min_overlap: int,
    min_support: float,
    limit: int,
) -> list[dict]:
    columns = sorted(
        col
        for col, values in sheet.numeric_columns.items()
        if len(values) >= min_overlap
    )
    findings = []
    formula_cols = set(sheet.formulas_by_column)
    for idx, left_col in enumerate(columns):
        for right_col in columns[idx + 1 :]:
            rows = common_rows(
                sheet.numeric_columns[left_col], sheet.numeric_columns[right_col]
            )
            if len(rows) < min_overlap:
                continue
            differences = Counter()
            ratios = Counter()
            ratio_rows: dict[str, list[int]] = defaultdict(list)
            diff_rows: dict[str, list[int]] = defaultdict(list)
            for row in rows:
                left = sheet.numeric_columns[left_col][row]
                right = sheet.numeric_columns[right_col][row]
                diff_key = decimal_key(left - right)
                differences[diff_key] += 1
                diff_rows[diff_key].append(row)
                if right != 0:
                    ratio_key = decimal_key(left / right)
                    ratios[ratio_key] += 1
                    ratio_rows[ratio_key].append(row)

            diff_value, diff_count = differences.most_common(1)[0]
            if diff_value != "0" and diff_count / len(rows) >= min_support:
                findings.append(
                    relationship_record(
                        sheet,
                        "fixed_difference",
                        left_col,
                        right_col,
                        diff_value,
                        diff_count,
                        len(rows),
                        diff_rows[diff_value],
                        formula_cols,
                    )
                )

            if ratios:
                ratio_value, ratio_count = ratios.most_common(1)[0]
                if (
                    ratio_value not in {"0", "1"}
                    and ratio_count / len(rows) >= min_support
                ):
                    findings.append(
                        relationship_record(
                            sheet,
                            "fixed_ratio",
                            left_col,
                            right_col,
                            ratio_value,
                            ratio_count,
                            len(rows),
                            ratio_rows[ratio_value],
                            formula_cols,
                        )
                    )
    return sorted(findings, key=lambda item: (-item["support_rows"], item["workbook"]))[
        :limit
    ]
