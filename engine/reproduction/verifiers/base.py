"""Base protocol and configuration for typed verifiers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from engine.reproduction.models import VerifierOutput


@dataclass(frozen=True)
class ToleranceConfig:
    """Numerical tolerance configuration for verifier comparisons.

    Frozen dataclass — immutable once created.
    """

    p_value_absolute_error: float = 0.001
    relative_error: float = 0.01
    absolute_error: float = 0.001
    rounding_digits: int | None = None


class TypedVerifier(Protocol):
    """Protocol for typed verifiers.

    Each verifier runs on an evidence graph edge and produces a VerifierOutput.
    """

    def verify(
        self,
        source_value: Any,
        target_value: Any,
        context: dict[str, Any] | None = None,
    ) -> VerifierOutput: ...


def make_verifier_output(
    verdict: str,
    confidence: float,
    evidence_span: str | None = None,
    discrepancy_type: str | None = None,
    severity: str | None = None,
    abstain_reason: str | None = None,
) -> VerifierOutput:
    """Construct a VerifierOutput with sensible defaults."""
    return VerifierOutput(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence,
        evidence_span=evidence_span,
        discrepancy_type=discrepancy_type,
        severity=severity,  # type: ignore[arg-type]
        abstain_reason=abstain_reason,
    )
