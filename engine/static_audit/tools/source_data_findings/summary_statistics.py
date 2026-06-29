"""Summary-statistic pair detection and artifact classification."""

from __future__ import annotations

from decimal import Decimal

from engine.static_audit.tools.source_data_profile import normalized_number

from ._shared import (
    TIME_EVENT_TERMS,
    SheetVectors,
    _decimal_close,
    _has_any,
    _integer_like_ratio,
    _is_mean_label,
    _is_n_label,
    _is_sum_label,
    _label_lower,
    column_label,
    decimal_key,
)


def is_summary_statistic_pair(
    sheet: SheetVectors, left_col: int, right_col: int, rows: list[int]
) -> bool:
    """Return True when a pair looks like Mean/Sum with an N column.

    These are traceability facts, not suspicious fixed relationships: if Sum is
    Mean multiplied by a stable N, row-offset ratio reuse is mathematically
    expected.
    """
    left_label = _label_lower(sheet, left_col)
    right_label = _label_lower(sheet, right_col)
    if _is_mean_label(left_label) and _is_sum_label(right_label):
        mean_col, sum_col = left_col, right_col
    elif _is_sum_label(left_label) and _is_mean_label(right_label):
        mean_col, sum_col = right_col, left_col
    else:
        return False

    usable_rows = [
        row
        for row in rows
        if row in sheet.numeric_columns.get(mean_col, {})
        and row in sheet.numeric_columns.get(sum_col, {})
        and sheet.numeric_columns[mean_col][row] != 0
    ]
    if len(usable_rows) < 3:
        return False

    ratios = [
        sheet.numeric_columns[sum_col][row] / sheet.numeric_columns[mean_col][row]
        for row in usable_rows
    ]
    integer_like = [ratio for ratio in ratios if _integer_like_ratio(ratio)]
    if len(integer_like) / len(ratios) < 0.8:
        return False

    n_columns = [
        col
        for col in sheet.numeric_columns
        if col not in {mean_col, sum_col} and _is_n_label(_label_lower(sheet, col))
    ]
    if not n_columns:
        # The Mean/Sum labels plus a stable integer multiplier are already a
        # strong summary-statistics signal, but keep this fallback conservative.
        distinct_ratios = {decimal_key(ratio, "0.001") for ratio in integer_like}
        return len(distinct_ratios) <= 2

    for n_col in n_columns:
        matched = 0
        compared = 0
        for row, ratio in zip(usable_rows, ratios):
            n_value = sheet.numeric_columns.get(n_col, {}).get(row)
            if n_value is None:
                continue
            compared += 1
            if _decimal_close(ratio, n_value, Decimal("0.001")):
                matched += 1
        if compared and matched / compared >= 0.8:
            return True
    return False


def zero_inflated_pair_artifact(
    sheet: SheetVectors,
    left_col: int,
    right_col: int,
    rows: list[int],
) -> tuple[bool, str | None]:
    if len(rows) < 20:
        return False, None
    left_values = sheet.numeric_columns[left_col]
    right_values = sheet.numeric_columns[right_col]
    both_zero = 0
    non_zero_rows = 0
    equal_non_zero = 0
    for row in rows:
        left = left_values.get(row)
        right = right_values.get(row)
        if left is None or right is None:
            continue
        if left == 0 and right == 0:
            both_zero += 1
        else:
            non_zero_rows += 1
            if left == right:
                equal_non_zero += 1
    zero_rate = both_zero / len(rows)
    non_zero_support = equal_non_zero / non_zero_rows if non_zero_rows else 0.0
    if zero_rate >= 0.7 and (non_zero_rows < 5 or non_zero_support < 0.98):
        return (
            True,
            f"zero-inflated matrix candidate: {both_zero}/{len(rows)} shared zero rows",
        )
    return False, None


def is_time_event_design_pair(
    sheet: SheetVectors, columns: list[int], rows: list[int]
) -> bool:
    labels = " / ".join(_label_lower(sheet, col) for col in columns)
    if not _has_any(labels, TIME_EVENT_TERMS):
        return False
    low_cardinality = 0
    for col in columns:
        values = [sheet.numeric_columns.get(col, {}).get(row) for row in rows]
        values = [value for value in values if value is not None]
        if not values:
            continue
        distinct = {normalized_number(value) for value in values}
        if len(distinct) <= 3 or len(distinct) / len(values) <= 0.2:
            low_cardinality += 1
    return low_cardinality >= max(1, len(columns) - 1)
