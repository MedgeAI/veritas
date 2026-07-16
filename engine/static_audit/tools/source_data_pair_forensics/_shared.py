"""Shared constants, dataclass, and utility functions for pair forensics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from engine.static_audit.tools.source_data_findings._shared import SheetVectors
from engine.static_audit.tools.source_data_profile import normalized_number


RISK_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


@dataclass(frozen=True)
class PairForensicsParams:
    min_pairs: int = 8
    min_support: float = 0.95
    ratio_places: int = 4
    max_offset: int = 80
    max_findings_per_category: int = 50
    min_duplicate_row_width: int = 2


@dataclass(frozen=True)
class SheetNumericIndex:
    sheet: SheetVectors
    valid_columns: tuple[int, ...]
    values_by_col: dict[int, dict[int, Decimal]]
    floats_by_col: dict[int, dict[int, float]]
    rows_by_col: dict[int, frozenset[int]]
    row_bitset_by_col: dict[int, int]
    common_rows_cache: dict[tuple[int, int], tuple[int, ...]]
    fraction_key_by_cell: dict[tuple[int, int], str | None]
    frac_rows_by_col: dict[int, dict[str, int]]
    decimal_digits_by_cell: dict[tuple[int, int], str]
    tail_windows_by_cell: dict[tuple[int, int], tuple[tuple[int, str], ...]]
    row_value_index: dict[int, dict[int, int]]
    tail_token_frequency: dict[str, int]


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


def rows_to_bitset(rows: list[int] | tuple[int, ...] | frozenset[int]) -> int:
    bitset = 0
    for row in rows:
        if row >= 0:
            bitset |= 1 << row
    return bitset


def bitset_to_rows(bitset: int, limit: int | None = None) -> list[int]:
    rows: list[int] = []
    current = bitset
    while current:
        lsb = current & -current
        row = lsb.bit_length() - 1
        rows.append(row)
        if limit is not None and len(rows) >= limit:
            break
        current ^= lsb
    return rows


def iter_bitset_values(bitset: int) -> list[int]:
    values: list[int] = []
    current = bitset
    while current:
        lsb = current & -current
        values.append(lsb.bit_length() - 1)
        current ^= lsb
    return values


def quantized_float_bucket(value: float, epsilon: float = 1e-6) -> int:
    if not math.isfinite(value):
        return 0
    return round(value / epsilon)


def _decimal_fraction(value: Decimal) -> Decimal:
    absolute = abs(value)
    return absolute - int(absolute)


def decimal_fraction_key(value: Decimal) -> str | None:
    if decimal_places(value) <= 0:
        return None
    fraction = _decimal_fraction(value)
    return str(fraction.normalize())


def decimal_digits(value: Decimal) -> str:
    if decimal_places(value) <= 0:
        return ""
    text = format(abs(value), "f")
    if "." not in text:
        return ""
    return text.split(".", 1)[1]


def tail_windows(value: Decimal, tail_digits: int = 5) -> tuple[tuple[int, str], ...]:
    digits = decimal_digits(value)
    if len(digits) < tail_digits or len(digits.rstrip("0")) < tail_digits:
        return ()
    windows: list[tuple[int, str]] = []
    for offset in range(len(digits) - tail_digits + 1):
        token = digits[offset : offset + tail_digits]
        if token.strip("0"):
            windows.append((offset, token))
    return tuple(windows)


def build_sheet_numeric_index(
    sheet: SheetVectors,
    params: PairForensicsParams,
    *,
    min_values: int = 3,
) -> SheetNumericIndex:
    values_by_col = sheet.numeric_columns
    valid_columns = tuple(
        col
        for col, values_by_row in sorted(values_by_col.items())
        if len(values_by_row) >= min_values
        and not is_low_information_numeric_column(values_by_row, params)
    )
    valid_set = set(valid_columns)
    floats_by_col = {
        col: {row: float(value) for row, value in values_by_row.items()}
        for col, values_by_row in values_by_col.items()
        if col in valid_set
    }
    rows_by_col = {col: frozenset(values_by_col[col]) for col in valid_columns}
    row_bitset_by_col = {col: rows_to_bitset(rows) for col, rows in rows_by_col.items()}
    common_rows_cache: dict[tuple[int, int], tuple[int, ...]] = {}
    for index, left_col in enumerate(valid_columns):
        for right_col in valid_columns[index + 1 :]:
            common_bitset = row_bitset_by_col[left_col] & row_bitset_by_col[right_col]
            common_rows_cache[(left_col, right_col)] = tuple(
                bitset_to_rows(common_bitset)
            )

    fraction_key_by_cell: dict[tuple[int, int], str | None] = {}
    frac_rows_by_col: dict[int, dict[str, int]] = {}
    decimal_digits_by_cell: dict[tuple[int, int], str] = {}
    tail_windows_by_cell: dict[tuple[int, int], tuple[tuple[int, str], ...]] = {}
    row_value_index: dict[int, dict[int, int]] = {}
    tail_token_frequency: dict[str, int] = {}

    for col in valid_columns:
        frac_rows_by_col[col] = {}
        for row, value in values_by_col[col].items():
            cell_key = (col, row)
            frac_key = decimal_fraction_key(value)
            fraction_key_by_cell[cell_key] = frac_key
            if frac_key is not None:
                frac_rows_by_col[col][frac_key] = (
                    frac_rows_by_col[col].get(frac_key, 0) | (1 << row)
                )
            decimal_digits_by_cell[cell_key] = decimal_digits(value)
            windows = tail_windows(value)
            tail_windows_by_cell[cell_key] = windows
            for _offset, token in windows:
                tail_token_frequency[token] = tail_token_frequency.get(token, 0) + 1

            float_value = floats_by_col[col][row]
            bucket = quantized_float_bucket(float_value)
            row_bucket_index = row_value_index.setdefault(row, {})
            row_bucket_index[bucket] = row_bucket_index.get(bucket, 0) | (1 << col)

    return SheetNumericIndex(
        sheet=sheet,
        valid_columns=valid_columns,
        values_by_col=values_by_col,
        floats_by_col=floats_by_col,
        rows_by_col=rows_by_col,
        row_bitset_by_col=row_bitset_by_col,
        common_rows_cache=common_rows_cache,
        fraction_key_by_cell=fraction_key_by_cell,
        frac_rows_by_col=frac_rows_by_col,
        decimal_digits_by_cell=decimal_digits_by_cell,
        tail_windows_by_cell=tail_windows_by_cell,
        row_value_index=row_value_index,
        tail_token_frequency=tail_token_frequency,
    )


def ensure_sheet_numeric_index(
    source: SheetVectors | SheetNumericIndex,
    params: PairForensicsParams,
) -> SheetNumericIndex:
    if isinstance(source, SheetNumericIndex):
        return source
    return build_sheet_numeric_index(source, params)


def common_rows(
    index: SheetNumericIndex, left_col: int, right_col: int
) -> tuple[int, ...]:
    if left_col == right_col:
        return tuple(sorted(index.rows_by_col.get(left_col, ())))
    key = (left_col, right_col) if left_col < right_col else (right_col, left_col)
    cached = index.common_rows_cache.get(key)
    if cached is not None:
        return cached
    bitset = index.row_bitset_by_col.get(left_col, 0) & index.row_bitset_by_col.get(
        right_col, 0
    )
    return tuple(bitset_to_rows(bitset))


def approx_equal(a: float, b: float, epsilon: float = 1e-6) -> bool:
    """Relative-error approximate equality with magnitude floor protection.

    When |a| and |b| are both < 1, threshold degrades to absolute epsilon (1e-6),
    preventing relative error amplification for small values.
    """
    return abs(a - b) <= epsilon * max(1.0, abs(a), abs(b))


def has_consecutive_run(positions: list[int], min_run: int) -> bool:
    """Check if sorted positions contain a consecutive run of length >= min_run."""
    if not positions or min_run <= 0:
        return False
    sorted_pos = sorted(set(positions))
    current = 1
    for i in range(1, len(sorted_pos)):
        if sorted_pos[i] == sorted_pos[i - 1] + 1:
            current += 1
            if current >= min_run:
                return True
        else:
            current = 1
    return current >= min_run


def same_fraction_integer_delta(a: Decimal, b: Decimal, epsilon: float = 1e-6) -> int | None:
    """If two Decimal values share the same fractional part, return the integer delta.

    Returns int(b) - int(a) if fractional parts match within epsilon, else None.
    Uses float conversion for fractional comparison to avoid Decimal precision issues.
    """
    if decimal_places(a) <= 0 or decimal_places(b) <= 0:
        return None
    tolerance = Decimal(str(epsilon))
    frac_a = _decimal_fraction(a)
    frac_b = _decimal_fraction(b)
    if abs(frac_a - frac_b) > tolerance:
        return None
    delta = b - a
    nearest = int(delta.to_integral_value())
    if abs(delta - Decimal(nearest)) > tolerance:
        return None
    return nearest
