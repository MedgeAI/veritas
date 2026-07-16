"""Binary arithmetic relation detector (A*B=C, A/B=C, B/A=C)."""

from __future__ import annotations

from collections import Counter
from itertools import combinations, permutations
import math
from typing import Any

from engine.static_audit.tools.source_data_findings import (
    SheetVectors,
    _extract_raw_data_samples,
    col_to_name,
    column_label,
    is_summary_statistic_pair,
)

from ._shared import (
    PairForensicsParams,
    SheetNumericIndex,
    approx_equal,
    bitset_to_rows,
    common_rows as index_common_rows,
    ensure_sheet_numeric_index,
    has_consecutive_run,
    iter_bitset_values,
    quantized_float_bucket,
    risk_rank,
)
from .profile_helpers import _is_semantic_equivalent_pair


MAX_ANCHOR_ROWS_PER_PAIR = 64
MAX_CANDIDATE_COLUMNS_PER_PAIR = 128
MAX_VERIFIED_TRIPLES_PER_SHEET = 250_000


def _column_mask(columns: tuple[int, ...]) -> int:
    mask = 0
    for col in columns:
        mask |= 1 << col
    return mask


def _sample_rows(rows: tuple[int, ...], limit: int = MAX_ANCHOR_ROWS_PER_PAIR) -> list[int]:
    if len(rows) <= limit:
        return list(rows)
    step = (len(rows) - 1) / (limit - 1)
    return [rows[round(index * step)] for index in range(limit)]


def _candidate_columns_for_expected(
    index: SheetNumericIndex,
    row: int,
    expected: float,
    excluded_cols: set[int],
) -> int:
    if not math.isfinite(expected):
        return 0
    bucket = quantized_float_bucket(expected)
    row_index = index.row_value_index.get(row, {})
    mask = 0
    for adjacent_bucket in (bucket - 1, bucket, bucket + 1):
        mask |= row_index.get(adjacent_bucket, 0)
    for col in excluded_cols:
        mask &= ~(1 << col)
    return mask


def _add_candidates_for_ordered_pair(
    *,
    index: SheetNumericIndex,
    col_a: int,
    col_b: int,
    op: str,
    candidate_triples: set[tuple[int, int, int]],
    detector_skips: list[dict[str, Any]] | None,
    performance: dict[str, Any] | None,
    all_column_mask: int,
) -> bool:
    rows = index_common_rows(index, col_a, col_b)
    if len(rows) < 3:
        return True

    values_a = index.floats_by_col[col_a]
    values_b = index.floats_by_col[col_b]
    sampled_rows = _sample_rows(rows)
    candidate_counts: Counter[int] = Counter()
    broad_anchor_rows = 0

    for row in sampled_rows:
        if row not in values_a or row not in values_b:
            continue
        left = values_a[row]
        right = values_b[row]
        if op == "mul":
            expected = left * right
        else:
            if abs(right) <= 1e-12:
                continue
            expected = left / right
        mask = _candidate_columns_for_expected(
            index, row, expected, excluded_cols={col_a, col_b}
        )
        mask &= all_column_mask
        if mask.bit_count() > MAX_CANDIDATE_COLUMNS_PER_PAIR:
            broad_anchor_rows += 1
            continue
        for candidate_col in iter_bitset_values(mask):
            candidate_counts[candidate_col] += 1

    if performance is not None:
        performance["binary_arithmetic_candidate_pairs"] = (
            int(performance.get("binary_arithmetic_candidate_pairs", 0)) + 1
        )
        performance["binary_arithmetic_broad_anchor_rows"] = (
            int(performance.get("binary_arithmetic_broad_anchor_rows", 0))
            + broad_anchor_rows
        )

    if broad_anchor_rows and not candidate_counts and detector_skips is not None:
        detector_skips.append(
            {
                "detector": "binary_arithmetic_relation",
                "workbook": index.sheet.workbook,
                "sheet": index.sheet.sheet,
                "reason": "candidate_value_too_broad",
                "columns": [col_to_name(col_a), col_to_name(col_b)],
                "operation": op,
                "sampled_rows": len(sampled_rows),
                "broad_anchor_rows": broad_anchor_rows,
            }
        )
        return True

    min_hits = 1 if len(sampled_rows) <= 4 else min(3, max(1, len(sampled_rows) // 8))
    for candidate_col, hits in candidate_counts.items():
        if hits < min_hits:
            continue
        candidate_triples.add(tuple(sorted((col_a, col_b, candidate_col))))
        if len(candidate_triples) > MAX_VERIFIED_TRIPLES_PER_SHEET:
            if detector_skips is not None:
                detector_skips.append(
                    {
                        "detector": "binary_arithmetic_relation",
                        "workbook": index.sheet.workbook,
                        "sheet": index.sheet.sheet,
                        "reason": "candidate_triple_budget_exceeded",
                        "candidate_triples": len(candidate_triples),
                        "budget": MAX_VERIFIED_TRIPLES_PER_SHEET,
                    }
                )
            return False
    return True


def _triple_common_rows(index: SheetNumericIndex, cols: tuple[int, int, int]) -> list[int]:
    bitset = (
        index.row_bitset_by_col.get(cols[0], 0)
        & index.row_bitset_by_col.get(cols[1], 0)
        & index.row_bitset_by_col.get(cols[2], 0)
    )
    return bitset_to_rows(bitset)


def _matched_rows_for_relation(
    index: SheetNumericIndex,
    col_a: int,
    col_b: int,
    col_c: int,
    op: str,
) -> tuple[list[int], int]:
    rows = _triple_common_rows(index, tuple(sorted((col_a, col_b, col_c))))
    if len(rows) < 3:
        return [], len(rows)

    vals_a = index.floats_by_col[col_a]
    vals_b = index.floats_by_col[col_b]
    vals_c = index.floats_by_col[col_c]
    matched: list[int] = []
    for row in rows:
        af = vals_a[row]
        bf = vals_b[row]
        cf = vals_c[row]
        if op == "A*B=C":
            if approx_equal(af * bf, cf, 1e-6):
                matched.append(row)
        elif abs(bf) > 1e-12 and approx_equal(af / bf, cf, 1e-6):
            matched.append(row)
    return matched, len(rows)


def _candidate_relations_for_triple(
    cols: tuple[int, int, int],
) -> list[tuple[int, int, int, str]]:
    relations: list[tuple[int, int, int, str]] = []
    for result_col in sorted(cols, reverse=True):
        operands = [col for col in cols if col != result_col]
        left, right = sorted(operands)
        relations.append((left, right, result_col, "A*B=C"))
        relations.append((left, right, result_col, "A/B=C"))
        relations.append((right, left, result_col, "A/B=C"))
    return relations


def _passes_relation_gate(matched_rows: list[int], comparable: int) -> bool:
    if len(matched_rows) < 3 or comparable < 3:
        return False
    return has_consecutive_run(matched_rows, 3) or (
        len(matched_rows) / comparable >= 0.5
    )


def binary_arithmetic_relation_findings(
    source: SheetVectors | SheetNumericIndex,
    params: PairForensicsParams,
    *,
    performance: dict[str, Any] | None = None,
    detector_skips: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Detect column triples where one column is a binary function of two others.

    Candidate triples are generated from row-level value indexes instead of
    scanning every column permutation.  Algebraically equivalent forms are
    verified once per unordered triple, so A*B=C and C/B=A do not produce
    duplicate findings.
    """
    index = ensure_sheet_numeric_index(source, params)
    sheet = index.sheet
    valid_columns = index.valid_columns
    col_count = len(valid_columns)
    row_count = max((len(rows) for rows in index.rows_by_col.values()), default=0)
    naive_budget = row_count * col_count * max(0, col_count - 1) * max(0, col_count - 2)
    if performance is not None:
        performance["binary_arithmetic_naive_triples"] = (
            int(performance.get("binary_arithmetic_naive_triples", 0)) + naive_budget
        )

    if col_count < 3:
        return []

    all_column_mask = _column_mask(valid_columns)
    candidate_triples: set[tuple[int, int, int]] = set()
    keep_collecting = True

    for col_a, col_b in combinations(valid_columns, 2):
        keep_collecting = _add_candidates_for_ordered_pair(
            index=index,
            col_a=col_a,
            col_b=col_b,
            op="mul",
            candidate_triples=candidate_triples,
            detector_skips=detector_skips,
            performance=performance,
            all_column_mask=all_column_mask,
        )
        if not keep_collecting:
            break

    if keep_collecting:
        for col_a, col_b in permutations(valid_columns, 2):
            keep_collecting = _add_candidates_for_ordered_pair(
                index=index,
                col_a=col_a,
                col_b=col_b,
                op="div",
                candidate_triples=candidate_triples,
                detector_skips=detector_skips,
                performance=performance,
                all_column_mask=all_column_mask,
            )
            if not keep_collecting:
                break

    if performance is not None:
        performance["binary_arithmetic_candidate_triples"] = (
            int(performance.get("binary_arithmetic_candidate_triples", 0))
            + len(candidate_triples)
        )

    findings: list[dict[str, Any]] = []

    for triple in sorted(candidate_triples):
        if len(findings) >= params.max_findings_per_category:
            break
        if performance is not None:
            performance["binary_arithmetic_verified_triples"] = (
                int(performance.get("binary_arithmetic_verified_triples", 0)) + 1
            )

        relation_matches = []
        for col_a, col_b, col_c, op in _candidate_relations_for_triple(triple):
            matched_rows, comparable = _matched_rows_for_relation(
                index, col_a, col_b, col_c, op
            )
            if not _passes_relation_gate(matched_rows, comparable):
                continue
            relation_matches.append(
                (len(matched_rows), comparable, col_c, col_a, col_b, op, matched_rows)
            )

        if not relation_matches:
            continue

        support, comparable, col_c, col_a, col_b, op, matched_rows = max(
            relation_matches,
            key=lambda item: (item[0], item[0] / item[1], item[2], item[5] == "A*B=C"),
        )

        rate = support / comparable
        risk = "high" if support >= 10 and rate >= 0.95 else "medium"

        # -- artifact degradation --
        artifact = False
        reason: str | None = None

        formula_cols = {col_a, col_b, col_c} & set(sheet.formulas_by_column)
        if formula_cols:
            risk = "low"
            artifact = True
            reason = "formula column involved"

        sorted_matched = sorted(matched_rows)
        for pair in [(col_a, col_b), (col_a, col_c), (col_b, col_c)]:
            if is_summary_statistic_pair(sheet, pair[0], pair[1], sorted_matched):
                artifact = True
                if reason is None:
                    reason = (
                        f"summary-statistic pair: "
                        f"{column_label(sheet, pair[0])} vs "
                        f"{column_label(sheet, pair[1])}"
                    )
                break

        lbl_a = column_label(sheet, col_a)
        lbl_b = column_label(sheet, col_b)
        lbl_c = column_label(sheet, col_c)
        if not artifact:
            for pair_lbl in [(lbl_a, lbl_b), (lbl_a, lbl_c), (lbl_b, lbl_c)]:
                if _is_semantic_equivalent_pair(pair_lbl[0], pair_lbl[1]):
                    artifact = True
                    if reason is None:
                        reason = (
                            f"semantic-equivalent pair: "
                            f"{pair_lbl[0]} vs {pair_lbl[1]}"
                        )
                    break

        vals_a = index.floats_by_col[col_a]
        vals_b = index.floats_by_col[col_b]
        vals_c = index.floats_by_col[col_c]
        findings.append(
            {
                "finding_id": None,
                "category": "binary_arithmetic_relation",
                "risk_level": risk,
                "confidence": "high" if rate >= 0.95 else "medium",
                "workbook": sheet.workbook,
                "sheet": sheet.sheet,
                "support_rows": support,
                "overlap_rows": comparable,
                "support_rate": round(rate, 4),
                "columns": [
                    col_to_name(col_a),
                    col_to_name(col_b),
                    col_to_name(col_c),
                ],
                "column_labels": [lbl_a, lbl_b, lbl_c],
                "operation": op,
                "sample_pairs": [
                    {
                        "row": row,
                        "a": vals_a[row],
                        "b": vals_b[row],
                        "c": vals_c[row],
                        "a_cell": f"{col_to_name(col_a)}{row}",
                        "b_cell": f"{col_to_name(col_b)}{row}",
                        "c_cell": f"{col_to_name(col_c)}{row}",
                    }
                    for row in sorted_matched[:20]
                ],
                "benign_explanations": [
                    "可能是合法的单位换算、密度×体积=质量、浓度×体积=摩尔数等物理/化学关系。",
                    "若三列代表独立测量，精确乘除关系需要追溯原始计算过程。",
                ],
                "pressure_test_result": "needs_binary_arithmetic_independence_review",
                "next_steps": [
                    "确认第三列是否为前两列的派生计算列（如公式列）。",
                    "核对三列是否分别来自独立测量还是存在数学定义关系。",
                    "要求提供原始仪器输出和计算脚本。",
                ],
                "raw_data_samples": _extract_raw_data_samples(sheet, sorted_matched),
                "artifact_likelihood": "high" if artifact else "unknown",
                "artifact_reason": reason,
            }
        )

    return sorted(
        findings,
        key=lambda item: (-risk_rank(item["risk_level"]), -item["support_rows"]),
    )[: params.max_findings_per_category]
