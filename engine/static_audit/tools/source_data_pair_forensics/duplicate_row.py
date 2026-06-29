"""Duplicate row vector detector."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from engine.static_audit.tools.source_data_findings import (
    SheetVectors,
    _extract_raw_data_samples,
    col_to_name,
    column_label,
    is_time_event_design_pair,
    zero_inflated_pair_artifact,
)
from engine.static_audit.tools.source_data_profile import normalized_number

from ._shared import (
    PairForensicsParams,
    is_low_information_numeric_column,
    risk_rank,
)


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
                "raw_data_samples": _extract_raw_data_samples(sheet, rows),
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
