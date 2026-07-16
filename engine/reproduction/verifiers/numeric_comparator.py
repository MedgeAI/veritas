"""NumericComparator: first typed verifier for claim-provenance consistency auditing.

Compares two numeric values (source vs target) under configurable tolerance,
producing a VerifierOutput verdict. Handles p-values and general numeric
comparisons with absolute/relative error thresholds.
"""

from __future__ import annotations

import math
from typing import Any

from engine.reproduction.verifiers.base import (
    ToleranceConfig,
    VerifierOutput,
    make_verifier_output,
)


def is_numeric(value: Any) -> bool:
    """Check whether *value* can be interpreted as a finite real number."""
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    try:
        f = float(value)
        return math.isfinite(f)
    except (TypeError, ValueError):
        return False


def _severity_for_relative_diff(relative_diff: float) -> str:
    """Map relative difference to a severity level."""
    if relative_diff > 0.50:
        return "critical"
    if relative_diff > 0.20:
        return "high"
    if relative_diff > 0.05:
        return "medium"
    return "low"


def _build_evidence_span(
    verdict: str,
    source_value: float,
    target_value: float,
    abs_diff: float,
    relative_diff: float,
    context: dict[str, Any],
) -> str:
    """Build a stable evidence span identifier for matching with ground truth.

    The evidence span uses a canonical format that identifies which artifact
    pair was compared, enabling exact string matching with GT evidence spans
    for evidence_precision/recall computation.

    Format: ``{relation_type}:{source_artifact_ref}->{target_artifact_ref}``

    The numeric details are included in the VerifierOutput but not in the
    span identifier, because GT and predicted values may differ in formatting
    while still referring to the same artifact pair.
    """
    src_ref = context.get("source_artifact_ref", "unknown")
    tgt_ref = context.get("target_artifact_ref", "unknown")
    relation = context.get("relation_type", "unknown")

    return f"{relation}:{src_ref}->{tgt_ref}"


class NumericComparator:
    """Typed verifier for numeric claim-provenance comparison.

    Implements the TypedVerifier protocol.  Compares *source_value* (from the
    source artifact, e.g. a table cell) against *target_value* (from the
    target artifact, e.g. a paper claim) under configurable tolerance.

    D4 fix: Populates evidence_span with detailed comparison information,
    enabling evidence_precision/recall metrics to verify correct artifact
    identification.
    """

    def __init__(self, tolerance: ToleranceConfig | None = None) -> None:
        self.tolerance = tolerance or ToleranceConfig()

    def verify(
        self,
        source_value: Any,
        target_value: Any,
        context: dict[str, Any] | None = None,
    ) -> VerifierOutput:
        """Compare two numeric values and return a verdict."""
        ctx = context or {}

        # --- Guard: non-numeric inputs ----------------------------------
        if not is_numeric(source_value) or not is_numeric(target_value):
            return make_verifier_output(
                verdict="insufficient",
                confidence=0.0,
                evidence_span=(
                    f"Cannot compare non-numeric values in "
                    f"{ctx.get('relation_type', 'unknown')} relation: "
                    f"source={source_value!r}, target={target_value!r}"
                ),
                abstain_reason="Non-numeric value",
            )

        src = float(source_value)
        tgt = float(target_value)
        tol = self.tolerance

        # --- Optional rounding ------------------------------------------
        if tol.rounding_digits is not None:
            digits = tol.rounding_digits
            src = round(src, digits)
            tgt = round(tgt, digits)

        # --- P-value path -----------------------------------------------
        if ctx.get("value_type") == "p_value":
            abs_diff = abs(src - tgt)
            relative_diff = abs_diff / max(abs(tgt), 1e-300)
            if abs_diff <= tol.p_value_absolute_error:
                return make_verifier_output(
                    verdict="consistent",
                    confidence=1.0,
                    evidence_span=_build_evidence_span(
                        "consistent", src, tgt, abs_diff, relative_diff, ctx
                    ),
                )
            return make_verifier_output(
                verdict="inconsistent",
                confidence=1.0,
                discrepancy_type="p_value_mismatch",
                severity=_severity_for_relative_diff(relative_diff),
                evidence_span=_build_evidence_span(
                    "inconsistent", src, tgt, abs_diff, relative_diff, ctx
                ),
            )

        # --- General numeric path ---------------------------------------
        abs_diff = abs(src - tgt)
        denominator = max(abs(tgt), 1e-300)
        relative_diff = abs_diff / denominator

        if abs_diff <= tol.absolute_error:
            return make_verifier_output(
                verdict="consistent",
                confidence=1.0,
                evidence_span=_build_evidence_span(
                    "consistent", src, tgt, abs_diff, relative_diff, ctx
                ),
            )

        if relative_diff <= tol.relative_error:
            return make_verifier_output(
                verdict="consistent",
                confidence=1.0,
                evidence_span=_build_evidence_span(
                    "consistent", src, tgt, abs_diff, relative_diff, ctx
                ),
            )

        return make_verifier_output(
            verdict="inconsistent",
            confidence=1.0,
            discrepancy_type="numeric_mismatch",
            severity=_severity_for_relative_diff(relative_diff),
            evidence_span=_build_evidence_span(
                "inconsistent", src, tgt, abs_diff, relative_diff, ctx
            ),
        )
