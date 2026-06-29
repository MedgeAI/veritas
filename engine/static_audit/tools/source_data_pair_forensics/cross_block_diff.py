"""Cross-block paired difference detector."""

from __future__ import annotations

from typing import Any

from engine.static_audit.tools.source_data_findings import (
    SheetVectors,
    _extract_raw_data_samples,
    column_label,
)

from ._shared import (
    PairForensicsParams,
    is_low_information_numeric_column,
    risk_rank,
)


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

    text_only_rows: dict[int, int] = {}  # row -> count of text cells
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
    independent -- if all paired differences at corresponding positions are
    suspiciously small (e.g., all within +-0.02 OD), this is inconsistent with
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
                        "raw_data_samples": _extract_raw_data_samples(
                            sheet, block_a[:25] + block_b[:25]
                        ),
                    }
                )

    return sorted(
        findings, key=lambda item: (-risk_rank(item["risk_level"]), -item["pair_count"])
    )[: params.max_findings_per_category]
