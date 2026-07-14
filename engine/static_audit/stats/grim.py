"""GRIM/GRIMMER-style arithmetic consistency helpers."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def _to_decimal(value: str | int | float | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def infer_decimals(value: str | int | float | Decimal) -> int:
    text = str(value)
    if "e" in text.lower():
        value = _to_decimal(value)
        return max(0, -value.as_tuple().exponent)
    if "." not in text:
        return 0
    return len(text.rstrip("0").split(".", 1)[1])


def rounded_decimal(value: Decimal, decimals: int) -> Decimal:
    quantum = Decimal(1).scaleb(-decimals)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def grim_mean_is_possible(
    mean: str | int | float | Decimal,
    *,
    n: int,
    decimals: int | None = None,
) -> bool:
    """Check whether a rounded mean could arise from n integer-valued items."""
    if n <= 0:
        raise ValueError("n must be positive")
    reported = _to_decimal(mean)
    places = infer_decimals(mean) if decimals is None else decimals
    lower = reported - (Decimal("0.5") * Decimal(1).scaleb(-places))
    upper = reported + (Decimal("0.5") * Decimal(1).scaleb(-places))
    min_total = int((lower * n).to_integral_value(rounding="ROUND_CEILING"))
    max_total = int((upper * n).to_integral_value(rounding="ROUND_FLOOR"))
    for total in range(min_total, max_total + 1):
        if rounded_decimal(Decimal(total) / n, places) == reported:
            return True
    return False


def grim_findings(
    rows: list[dict],
    *,
    mean_column: str,
    n: int,
    decimals: int | None = None,
) -> list[dict]:
    findings = []
    for index, row in enumerate(rows, start=1):
        value = row.get(mean_column)
        if value is None:
            continue
        try:
            possible = grim_mean_is_possible(value, n=n, decimals=decimals)
        except (InvalidOperation, ValueError):
            continue
        if not possible:
            findings.append(
                {
                    "category": "grim_violation",
                    "row": row.get("row", index),
                    "mean": value,
                    "n": n,
                    "decimals": infer_decimals(value) if decimals is None else decimals,
                }
            )
    return findings
