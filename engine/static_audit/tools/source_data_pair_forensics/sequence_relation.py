"""Internal sequence relation detector for source data pair forensics.

Detects arithmetic and geometric sequences within single numeric columns.
A sequence requires a contiguous run of >= 4 rows with sufficient high-precision
cells (>= 3 cells with decimal_places >= 3) and either constant deltas or constant
ratios across the run.
"""

from __future__ import annotations

from typing import Any

from engine.static_audit.tools.source_data_findings import (
    SheetVectors,
    _extract_raw_data_samples,
    col_to_name,
    column_label,
)

from ._shared import (
    PairForensicsParams,
    SheetNumericIndex,
    decimal_places,
    ensure_sheet_numeric_index,
    risk_rank,
)


def _approx_equal(a: float, b: float, tol: float) -> bool:
    """Return True when *a* and *b* are within *tol* of each other."""
    return abs(a - b) <= tol


def _contiguous_runs(rows: list[int], min_run: int = 4) -> list[list[int]]:
    """Find maximal consecutive subsequences of length >= *min_run*.

    *rows* must be sorted in ascending order.  A consecutive subsequence is a
    maximal run where each element equals the previous element plus one.
    """
    if len(rows) < min_run:
        return []
    runs: list[list[int]] = []
    start = 0
    for i in range(1, len(rows)):
        if rows[i] != rows[i - 1] + 1:
            length = i - start
            if length >= min_run:
                runs.append(rows[start:i])
            start = i
    length = len(rows) - start
    if length >= min_run:
        runs.append(rows[start:])
    return runs


def internal_sequence_relation_findings(
    source: SheetVectors | SheetNumericIndex, params: PairForensicsParams
) -> list[dict[str, Any]]:
    """Detect arithmetic and geometric sequences in single numeric columns.

    For each numeric column, contiguous runs of >= 4 rows are examined.  Runs
    must contain at least 3 high-precision cells (decimal_places >= 3) to
    qualify.  Qualifying runs are checked for constant-delta (arithmetic) or
    constant-ratio (geometric) patterns.
    """
    index = ensure_sheet_numeric_index(source, params)
    sheet = index.sheet
    findings: list[dict[str, Any]] = []

    for col in index.valid_columns:
        values_by_row = index.values_by_col[col]
        sorted_rows = sorted(values_by_row)
        runs = _contiguous_runs(sorted_rows)

        for run_rows in runs:
            run_values = [values_by_row[r] for r in run_rows]
            length = len(run_values)

            # High-precision gate: at least 3 cells with >= 3 decimal places.
            high_precision_count = sum(
                1 for v in run_values if decimal_places(v) >= 3
            )
            if high_precision_count < 3:
                continue

            # --- Arithmetic sequence check ---
            deltas = [
                float(run_values[i + 1]) - float(run_values[i])
                for i in range(length - 1)
            ]
            is_arithmetic = all(
                _approx_equal(d, deltas[0], 1e-6) for d in deltas
            ) and abs(deltas[0]) > 1e-12

            # --- Geometric sequence check ---
            has_zero = any(float(v) == 0.0 for v in run_values)
            is_geometric = False
            ratios: list[float] = []
            if not has_zero:
                ratios = [
                    float(run_values[i + 1]) / float(run_values[i])
                    for i in range(length - 1)
                ]
                is_geometric = all(
                    _approx_equal(r, ratios[0], 1e-6) for r in ratios
                ) and abs(ratios[0] - 1.0) > 1e-12

            if not is_arithmetic and not is_geometric:
                continue

            seq_type = "arithmetic" if is_arithmetic else "geometric"

            risk = "high" if length >= 10 else "medium"
            confidence = "high" if length >= 6 else "medium"

            # Artifact degradation for formula-derived columns.
            artifact_likelihood: str = "unknown"
            artifact_reason: str | None = None
            if col in sheet.formulas_by_column:
                risk = "low"
                artifact_likelihood = "high"
                artifact_reason = "formula-derived column"

            finding: dict[str, Any] = {
                "finding_id": None,
                "category": "internal_sequence_relation",
                "risk_level": risk,
                "confidence": confidence,
                "workbook": sheet.workbook,
                "sheet": sheet.sheet,
                "support_rows": length,
                "overlap_rows": length,
                "support_rate": 1.0,
                "columns": [col_to_name(col)],
                "column_labels": [column_label(sheet, col)],
                "sequence_type": seq_type,
                "delta": str(run_values[1] - run_values[0])
                if is_arithmetic
                else None,
                "ratio": str(run_values[1] / run_values[0])
                if is_geometric
                else None,
                "sequence_length": length,
                "sample_pairs": [
                    float(v) for v in run_values[:20]
                ],
                "benign_explanations": [
                    "可能是实验设计中的等间距采样（如时间序列、剂量梯度）。",
                    "可能是仪器的固定步长输出或归一化处理的结果。",
                ],
                "pressure_test_result": "needs_sequence_independence_review",
                "next_steps": [
                    "确认该列是否为实验设计中的固定步长/剂量变量。",
                    "核对数据是否来自仪器自动输出还是人工填入。",
                    "检查相邻列是否存在对应的响应数据。",
                ],
                "raw_data_samples": _extract_raw_data_samples(sheet, run_rows),
                "artifact_likelihood": artifact_likelihood,
                "artifact_reason": artifact_reason,
            }
            findings.append(finding)

    return sorted(
        findings,
        key=lambda item: (-risk_rank(item["risk_level"]), -item["sequence_length"]),
    )[: params.max_findings_per_category]
