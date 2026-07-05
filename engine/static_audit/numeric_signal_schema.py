"""Canonical Numeric Signal Schema for Veritas numeric forensics.

This module defines the unified signal representation that both PaperConan
translations and native Veritas detectors must produce before entering the
report finding layer.

Design rationale (from PRD WP1):
- PaperConan and native Veritas detectors produce different raw shapes.
- Mixing them directly into report findings causes category collisions,
  inconsistent provenance, and loss of profile/prefilter context.
- The NumericSignal is the single canonical intermediate representation.
- Every signal carries enough provenance to trace back to the original
  tool output (raw_payload_ref) and source file (evidence_locator).

Key constraints:
- mechanical_confidence is NOT a suspicion score; it is not used for ranking.
- risk_level_raw is the detector priority, NOT the final Veritas risk.
- applicability_premise MUST be explicit for GRIM/GRIMMER/last-digit/within-col.
- raw_payload_ref MUST trace back to the original paperconan_scan.json path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

# Valid source tools that can produce NumericSignals
ValidSourceTool = Literal["paperconan", "veritas_native"]

# Valid profile actions from the profile/prefilter layer
ValidProfileAction = Literal["kept", "demoted", "hidden"]

# Valid prefilter actions
ValidPrefilterAction = Literal["keep", "downweight", "drop"]

# Valid risk levels from detectors
ValidRiskLevel = Literal["critical", "high", "medium", "low", "info"]

# Valid detector families matching the coverage matrix
ValidDetectorFamily = Literal[
    "column_relations",
    "copy_tweak_fingerprints",
    "within_column",
    "cross_sheet",
    "matrix_vector_reuse",
    "statistical_impossibility",
    "digit_statistics",
    "progressions",
    "scan_errors",
    "native_source_data",
    "native_pair_forensics",
    "unknown",
]

_SCHEMA_VERSION = "1.0"

_SIGNAL_ID_PATTERN = re.compile(r"^NUM-SIG-\d{4,}$")

# Required provenance fields that must be present on every signal
_REQUIRED_PROVENANCE_FIELDS = frozenset({
    "signal_id",
    "source_tool",
    "detector_id",
    "detector_family",
    "raw_kind",
    "canonical_category",
    "raw_payload_ref",
})

# Required evidence locator fields when evidence_locator is present
_REQUIRED_EVIDENCE_LOCATOR_FIELDS = frozenset({
    "source_path",
})


@dataclass(frozen=True)
class ApplicabilityPremise:
    """Records the data-type assumptions a detector requires to be valid.

    These premises gate whether a signal should enter review or be flagged
    as potentially inapplicable. For example, GRIM requires integer-valued
    items; applying it to continuous measurements produces structural FPs.
    """

    requires_integer_valued_items: bool = False
    requires_independent_rows: bool = False
    requires_raw_measurement: bool = False
    additional_premises: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "requires_integer_valued_items": self.requires_integer_valued_items,
            "requires_independent_rows": self.requires_independent_rows,
            "requires_raw_measurement": self.requires_raw_measurement,
        }
        if self.additional_premises:
            result["additional_premises"] = dict(self.additional_premises)
        return result


@dataclass(frozen=True)
class EvidenceLocator:
    """Bounded evidence window locator.

    Points to the exact location in the source file where the signal was
    detected, without storing bulky evidence blobs. The source file hash
    ensures reproducibility.
    """

    source_path: str
    source_sha256: str = ""
    sheet: str = ""
    rows: str = ""
    cols: str = ""
    highlight_rows: list[int] = field(default_factory=list)
    highlight_cols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"source_path": self.source_path}
        if self.source_sha256:
            result["source_sha256"] = self.source_sha256
        if self.sheet:
            result["sheet"] = self.sheet
        if self.rows:
            result["rows"] = self.rows
        if self.cols:
            result["cols"] = self.cols
        if self.highlight_rows:
            result["highlight_rows"] = list(self.highlight_rows)
        if self.highlight_cols:
            result["highlight_cols"] = list(self.highlight_cols)
        return result


@dataclass(frozen=True)
class NumericSignal:
    """Canonical numeric forensics signal.

    This is the unified intermediate representation between detector output
    and report finding. Both PaperConan translations and native Veritas
    detectors produce NumericSignal instances.

    Fields follow the PRD WP1 schema specification.
    """

    # --- Identity ---
    signal_id: str
    source_tool: ValidSourceTool
    detector_id: str
    detector_family: ValidDetectorFamily
    raw_kind: str
    canonical_category: str

    # --- Detector output ---
    rule: str = ""
    n: int | None = None
    effect_size: float | None = None
    mechanical_confidence: float | None = None
    risk_level_raw: ValidRiskLevel = "low"

    # --- Profile / Prefilter ---
    profile: str = "review"
    profile_action: ValidProfileAction = "kept"
    prefilter_action: ValidPrefilterAction = "keep"
    false_positive_context: list[str] = field(default_factory=list)
    prefilter_reason: str = ""

    # --- Applicability ---
    applicability_premise: ApplicabilityPremise | None = None

    # --- Evidence ---
    evidence_locator: EvidenceLocator | None = None

    # --- Provenance ---
    raw_payload_ref: str = ""

    # --- Extra detector-specific metadata ---
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        result: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "signal_id": self.signal_id,
            "source_tool": self.source_tool,
            "detector_id": self.detector_id,
            "detector_family": self.detector_family,
            "raw_kind": self.raw_kind,
            "canonical_category": self.canonical_category,
            "rule": self.rule,
            "n": self.n,
            "effect_size": self.effect_size,
            "mechanical_confidence": self.mechanical_confidence,
            "risk_level_raw": self.risk_level_raw,
            "profile": self.profile,
            "profile_action": self.profile_action,
            "prefilter_action": self.prefilter_action,
            "false_positive_context": list(self.false_positive_context),
            "prefilter_reason": self.prefilter_reason,
            "raw_payload_ref": self.raw_payload_ref,
        }
        if self.applicability_premise is not None:
            result["applicability_premise"] = self.applicability_premise.to_dict()
        if self.evidence_locator is not None:
            result["evidence_locator"] = self.evidence_locator.to_dict()
        if self.extra:
            result["extra"] = dict(self.extra)
        return result


class NumericSignalValidationError(ValueError):
    """Raised when a NumericSignal fails validation."""


def validate_numeric_signal(signal: NumericSignal) -> list[str]:
    """Validate a NumericSignal and return a list of error messages.

    Returns an empty list if the signal is valid.

    Checks:
    - Required provenance fields are non-empty
    - signal_id matches the NUM-SIG-NNNN pattern
    - evidence_locator has required fields when present
    - mechanical_confidence is in [0, 1] when present
    - n is non-negative when present
    """
    errors: list[str] = []

    # signal_id format
    if not _SIGNAL_ID_PATTERN.match(signal.signal_id):
        errors.append(
            f"signal_id {signal.signal_id!r} does not match NUM-SIG-NNNN pattern"
        )

    # Required provenance fields
    if not signal.source_tool:
        errors.append("source_tool is required")
    if signal.source_tool not in ("paperconan", "veritas_native"):
        errors.append(f"source_tool {signal.source_tool!r} is not valid")
    if not signal.detector_id:
        errors.append("detector_id is required")
    if not signal.detector_family:
        errors.append("detector_family is required")
    if not signal.raw_kind:
        errors.append("raw_kind is required")
    if not signal.canonical_category:
        errors.append("canonical_category is required")
    if not signal.raw_payload_ref:
        errors.append("raw_payload_ref is required")

    # mechanical_confidence range
    if signal.mechanical_confidence is not None:
        if not (0.0 <= signal.mechanical_confidence <= 1.0):
            errors.append(
                f"mechanical_confidence {signal.mechanical_confidence} "
                f"out of range [0, 1]"
            )

    # n non-negative
    if signal.n is not None and signal.n < 0:
        errors.append(f"n {signal.n} must be non-negative")

    # evidence_locator required fields
    if signal.evidence_locator is not None:
        if not signal.evidence_locator.source_path:
            errors.append("evidence_locator.source_path is required")

    return errors


class NumericSignalSet:
    """Ordered collection of NumericSignals with serialization support.

    Provides:
    - Signal counting by family/category/severity
    - JSON serialization for artifact output
    - Deduplication by signal_id
    """

    def __init__(self, signals: list[NumericSignal] | None = None) -> None:
        self._signals: list[NumericSignal] = list(signals) if signals else []
        self._id_index: dict[str, int] = {
            s.signal_id: i for i, s in enumerate(self._signals)
        }

    def add(self, signal: NumericSignal) -> None:
        """Add a signal. Raises if signal_id already exists."""
        if signal.signal_id in self._id_index:
            raise ValueError(
                f"Duplicate signal_id: {signal.signal_id!r}"
            )
        self._id_index[signal.signal_id] = len(self._signals)
        self._signals.append(signal)

    def __len__(self) -> int:
        return len(self._signals)

    def __iter__(self):
        return iter(self._signals)

    def __getitem__(self, index: int) -> NumericSignal:
        return self._signals[index]

    @property
    def signals(self) -> list[NumericSignal]:
        return list(self._signals)

    def count_by_family(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self._signals:
            counts[s.detector_family] = counts.get(s.detector_family, 0) + 1
        return counts

    def count_by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self._signals:
            counts[s.canonical_category] = counts.get(s.canonical_category, 0) + 1
        return counts

    def count_by_risk(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self._signals:
            counts[s.risk_level_raw] = counts.get(s.risk_level_raw, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire signal set to a JSON-compatible dict."""
        return {
            "schema_version": _SCHEMA_VERSION,
            "total_signals": len(self._signals),
            "counts_by_family": self.count_by_family(),
            "counts_by_category": self.count_by_category(),
            "counts_by_risk": self.count_by_risk(),
            "signals": [s.to_dict() for s in self._signals],
        }

    def to_json_bytes(self) -> bytes:
        """Serialize to JSON bytes for artifact writing."""
        import json
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")


def generate_signal_id(counter: int) -> str:
    """Generate a deterministic signal ID from a counter.

    Format: NUM-SIG-NNNN (zero-padded to at least 4 digits).
    """
    return f"NUM-SIG-{counter:04d}"
