"""Column profile helpers: semantic equivalence, instrument artifact detection."""

from __future__ import annotations

import statistics
from decimal import Decimal

# Semantic equivalence groups for summary-statistic pair detection.
# Two columns whose labels both contain terms from the same group are likely
# a legitimate mean+-SD / median+-IQR / N/total / pre-post / control-treatment
# relationship, not a suspicious fixed-ratio artifact.
_SEMANTIC_GROUPS: tuple[tuple[str, ...], ...] = (
    ("mean", "avg", "average", "sd", "std", "stderr", "sem"),
    ("median", "iqr", "q1", "q3", "25%", "75%"),
    ("n", "count", "total", "proportion", "percentage", "%"),
    ("pre", "post", "baseline", "followup", "t0", "t1"),
    ("control", "treatment", "case", "case_control"),
)


def _is_semantic_equivalent_pair(left_label: str, right_label: str) -> bool:
    """Return True when both labels belong to the same semantic equivalence group.

    Matches are substring-based on the lowercased labels, consistent with how
    ``column_label`` returns the joined header text.
    """
    left_lower = left_label.lower()
    right_lower = right_label.lower()
    for group in _SEMANTIC_GROUPS:
        left_match = any(term in left_lower for term in group)
        right_match = any(term in right_lower for term in group)
        if left_match and right_match:
            return True
    return False


def _is_narrow_value_range(values: list[float]) -> bool:
    """Return True when IQR < 0.01 x median, indicating a high-precision instrument range."""
    if len(values) < 2:
        return False
    median = statistics.median(values)
    if median <= 0:
        return False
    q1, _, q3 = statistics.quantiles(values, n=4)
    iqr = q3 - q1
    return iqr < 0.01 * median


def _is_stable_high_correlation(
    left: list[float], right: list[float]
) -> bool:
    """Return True when columns are highly correlated (r>0.99) with near-constant difference."""
    if len(left) < 3:
        return False
    try:
        corr = statistics.correlation(left, right)
    except (ValueError, statistics.StatisticsError):
        return False
    diff_std = statistics.stdev([a - b for a, b in zip(left, right)])
    return corr > 0.99 and diff_std < 0.001
