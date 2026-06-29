"""Duplicate column detection."""

from __future__ import annotations

from engine.static_audit.tools.source_data_profile import normalized_number

from ._shared import (
    SheetVectors,
    _extract_raw_data_samples,
    col_to_name,
    column_label,
    common_rows,
    is_index_like_column,
)
from .summary_statistics import (
    is_time_event_design_pair,
    zero_inflated_pair_artifact,
)


def duplicate_column_findings(
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
    for idx, left_col in enumerate(columns):
        for right_col in columns[idx + 1 :]:
            rows = common_rows(
                sheet.numeric_columns[left_col], sheet.numeric_columns[right_col]
            )
            if len(rows) < min_overlap:
                continue
            equal = [
                row
                for row in rows
                if sheet.numeric_columns[left_col][row]
                == sheet.numeric_columns[right_col][row]
            ]
            support = len(equal) / len(rows)
            if support < min_support:
                continue
            left_label = column_label(sheet, left_col)
            right_label = column_label(sheet, right_col)
            index_like = is_index_like_column(
                sheet.numeric_columns[left_col], equal
            ) and is_index_like_column(sheet.numeric_columns[right_col], equal)
            zero_artifact, zero_reason = zero_inflated_pair_artifact(
                sheet, left_col, right_col, rows
            )
            event_artifact = is_time_event_design_pair(
                sheet, [left_col, right_col], equal
            )
            risk = (
                "low"
                if index_like or zero_artifact or event_artifact
                else (
                    "high"
                    if len(equal) >= 100 and left_label != right_label
                    else "medium"
                )
            )
            artifact_likelihood = (
                "high" if index_like or zero_artifact or event_artifact else "unknown"
            )
            artifact_reason = None
            if index_like:
                artifact_reason = "both columns look like repeated sequential index/subject-id columns"
            elif zero_artifact:
                artifact_reason = zero_reason
            elif event_artifact:
                artifact_reason = (
                    "low-cardinality time/event or grouped endpoint columns"
                )
            raw_samples = _extract_raw_data_samples(sheet, equal)
            findings.append(
                {
                    "finding_id": None,
                    "category": "duplicate_numeric_columns",
                    "risk_level": risk,
                    "confidence": "high" if support == 1 else "medium",
                    "workbook": sheet.workbook,
                    "sheet": sheet.sheet,
                    "column_pair": [col_to_name(left_col), col_to_name(right_col)],
                    "column_labels": [left_label, right_label],
                    "overlap_rows": len(rows),
                    "equal_rows": len(equal),
                    "support_rate": round(support, 4),
                    "artifact_likelihood": artifact_likelihood,
                    "artifact_reason": artifact_reason,
                    "sample_rows": equal[:20],
                    "sample_pairs": [
                        {
                            "row": row,
                            "left": normalized_number(
                                sheet.numeric_columns[left_col][row]
                            ),
                            "right": normalized_number(
                                sheet.numeric_columns[right_col][row]
                            ),
                        }
                        for row in equal[:20]
                    ],
                    "benign_explanations": [
                        "两列可能是重复展示同一指标、技术重复或空值填充结果。",
                        "如果列标签表示不同实验组或不同处理条件，则需要人工复核。",
                    ],
                    "pressure_test_result": (
                        "likely_zero_inflated_matrix_artifact"
                        if zero_artifact
                        else "likely_time_event_design_artifact"
                        if event_artifact
                        else "needs_column_semantics_review"
                    ),
                    "next_steps": [
                        "核对列标题、sheet 注释和对应 figure panel。",
                        "确认是否为合法重复、派生列或数据复制。",
                    ],
                    "raw_data_samples": raw_samples,
                }
            )
    return sorted(findings, key=lambda item: (-item["equal_rows"], item["workbook"]))[
        :limit
    ]
