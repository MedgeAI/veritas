"""Independent p-value recomputation for reported test statistics."""

from __future__ import annotations

from math import isfinite, log10
from typing import Any, Iterable, Mapping

from scipy import stats


def two_sided_t_p_value(t_stat: float, df: float) -> float:
    """Recompute two-sided p from a t statistic and degrees of freedom."""
    if df <= 0:
        raise ValueError("df must be positive")
    return float(2.0 * stats.t.sf(abs(float(t_stat)), float(df)))


def two_sided_z_p_value(z_stat: float) -> float:
    """Recompute two-sided p from a z statistic."""
    return float(2.0 * stats.norm.sf(abs(float(z_stat))))


def log10_p_delta(reported_p: float, recomputed_p: float) -> float:
    """Absolute log10 distance between two positive p values."""
    if reported_p <= 0 or recomputed_p <= 0:
        return float("inf")
    return abs(log10(float(reported_p)) - log10(float(recomputed_p)))


def audit_t_test_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    t_column: str = "t",
    df_column: str = "df",
    p_column: str = "P",
    tolerance_log10: float = 0.5,
) -> list[dict[str, Any]]:
    """Return rows whose reported p value disagrees with t+df recomputation."""
    findings: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        try:
            t_stat = float(row[t_column])
            df = float(row[df_column])
            reported = float(row[p_column])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(isfinite(value) for value in (t_stat, df, reported)):
            continue
        recomputed = two_sided_t_p_value(t_stat, df)
        delta = log10_p_delta(reported, recomputed)
        if delta > tolerance_log10:
            findings.append(
                {
                    "category": "p_value_inconsistency",
                    "row": row.get("row", index),
                    "stat": t_stat,
                    "df": df,
                    "reported_p": reported,
                    "recomputed_p": recomputed,
                    "log10_delta": delta,
                    "threshold": tolerance_log10,
                }
            )
    return findings


def audit_z_test_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    z_column: str = "z",
    p_column: str = "P",
    tolerance_log10: float = 0.5,
) -> list[dict[str, Any]]:
    """Return rows whose reported p value disagrees with z recomputation."""
    findings: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        try:
            z_stat = float(row[z_column])
            reported = float(row[p_column])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(isfinite(value) for value in (z_stat, reported)):
            continue
        recomputed = two_sided_z_p_value(z_stat)
        delta = log10_p_delta(reported, recomputed)
        if delta > tolerance_log10:
            findings.append(
                {
                    "category": "p_value_inconsistency",
                    "row": row.get("row", index),
                    "stat": z_stat,
                    "reported_p": reported,
                    "recomputed_p": recomputed,
                    "log10_delta": delta,
                    "threshold": tolerance_log10,
                }
            )
    return findings
