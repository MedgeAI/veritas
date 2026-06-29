"""Paired-difference spread detector (within-row)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from engine.static_audit.tools.source_data_findings import (
    SheetVectors,
    col_to_name,
    column_label,
)
from engine.static_audit.tools.source_data_profile import normalized_number

from ._shared import (
    PairForensicsParams,
    is_low_information_numeric_column,
    risk_rank,
)
from .profile_helpers import _is_narrow_value_range, _is_stable_high_correlation


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
