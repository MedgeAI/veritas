"""Shared constants, dataclass, and utility functions for pair forensics."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

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
