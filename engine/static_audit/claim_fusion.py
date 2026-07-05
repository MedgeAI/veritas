"""Claim / Impact Fusion (WP8).

Binds numeric signals to paper claims, figures, and source data references.
This is Veritas's core advantage over PaperConan: PaperConan detects patterns
but does not map them to the paper's semantic structure.

The fusion logic attempts to match each signal's evidence locator
(sheet/file) to known claims, figures, and source-data mappings.
When no mapping can be established, ``impact_scope`` is set to
``"unknown"`` — never silently defaulted to ``"peripheral"``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.static_audit.numeric_signal_schema import (
    ImpactScope,
    NumericSignal,
)


@dataclass(frozen=True)
class ClaimMapping:
    """Result of mapping a numeric signal to a paper claim.

    Attributes:
        signal_id: The signal being mapped.
        claim_refs: Paper claim identifiers (e.g. "Claim 3", "main_conclusion").
        figure_refs: Figure panel identifiers (e.g. "Fig.4c", "Fig.S2").
        source_data_refs: Source data file/sheet references.
        impact_scope: How important the data is to the paper's conclusions.
        impact_reason: Explanation of why this impact_scope was assigned.
        needs_author_data: What additional material from authors would resolve
            the uncertainty. Empty string when nothing specific is needed.
        mapping_confidence: Confidence in the mapping (low/medium/high).
    """

    signal_id: str
    claim_refs: list[str] = field(default_factory=list)
    figure_refs: list[str] = field(default_factory=list)
    source_data_refs: list[str] = field(default_factory=list)
    impact_scope: ImpactScope = "unknown"
    impact_reason: str = ""
    needs_author_data: str = ""
    mapping_confidence: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "claim_refs": list(self.claim_refs),
            "figure_refs": list(self.figure_refs),
            "source_data_refs": list(self.source_data_refs),
            "impact_scope": self.impact_scope,
            "impact_reason": self.impact_reason,
            "needs_author_data": self.needs_author_data,
            "mapping_confidence": self.mapping_confidence,
        }


@dataclass
class _ClaimIndex:
    """Internal index of paper claims for fast lookup.

    Attributes:
        claims: list of claim dicts with at least ``claim_id`` and ``text``.
        figures: list of figure dicts with at least ``figure_id`` and
            ``source_data_refs`` (list of sheet/file names).
        source_data_map: mapping from sheet/file name to claim_ids.
    """

    claims: list[dict[str, Any]] = field(default_factory=list)
    figures: list[dict[str, Any]] = field(default_factory=list)
    source_data_map: dict[str, list[str]] = field(default_factory=dict)


def build_claim_index(
    claims: list[dict[str, Any]] | None = None,
    figures: list[dict[str, Any]] | None = None,
    source_data_map: dict[str, list[str]] | None = None,
) -> _ClaimIndex:
    """Build a claim index from paper metadata.

    Args:
        claims: Paper claims, each with ``claim_id`` and optionally ``text``.
        figures: Figure metadata, each with ``figure_id`` and optionally
            ``source_data_refs`` (list of sheet/file names this figure uses).
        source_data_map: Direct mapping from source-data sheet/file name to
            list of claim_ids that depend on that data.

    Returns:
        An opaque index used by ``fuse_signal_to_claims``.
    """
    return _ClaimIndex(
        claims=list(claims or []),
        figures=list(figures or []),
        source_data_map=dict(source_data_map or {}),
    )


def fuse_signal_to_claims(
    signal: NumericSignal,
    claim_index: _ClaimIndex,
) -> ClaimMapping:
    """Attempt to map a numeric signal to paper claims via evidence locator.

    Mapping strategy:
    1. Extract the source file/sheet name from the signal's evidence_locator.
    2. Look up which claims reference that sheet/file in the source_data_map.
    3. Look up which figures reference that sheet/file.
    4. Derive impact_scope from the mapping results.

    If no mapping is found, impact_scope is ``"unknown"`` (not ``"peripheral"``).

    Args:
        signal: The numeric signal to map.
        claim_index: Pre-built claim index from ``build_claim_index``.

    Returns:
        A ClaimMapping with the mapping results.
    """
    source_path = signal.evidence_locator.source_path
    sheet = signal.evidence_locator.sheet

    # Collect candidate claim refs from source_data_map
    claim_refs: list[str] = []
    source_data_refs: list[str] = []

    # Match by source_path (file-level)
    if source_path and source_path in claim_index.source_data_map:
        claim_refs.extend(claim_index.source_data_map[source_path])
        source_data_refs.append(source_path)

    # Match by sheet name
    if sheet and sheet in claim_index.source_data_map:
        claim_refs.extend(claim_index.source_data_map[sheet])
        if sheet not in source_data_refs:
            source_data_refs.append(sheet)

    # Match figures that reference this source data
    figure_refs: list[str] = []
    for fig in claim_index.figures:
        fig_sd_refs = fig.get("source_data_refs", [])
        if source_path in fig_sd_refs or sheet in fig_sd_refs:
            fig_id = fig.get("figure_id", "")
            if fig_id:
                figure_refs.append(fig_id)

    # Deduplicate
    claim_refs = sorted(set(claim_refs))
    figure_refs = sorted(set(figure_refs))
    source_data_refs = sorted(set(source_data_refs))

    # Determine impact_scope
    impact_scope, impact_reason, confidence = _derive_impact(
        claim_refs=claim_refs,
        figure_refs=figure_refs,
        claims=claim_index.claims,
    )

    return ClaimMapping(
        signal_id=signal.signal_id,
        claim_refs=claim_refs,
        figure_refs=figure_refs,
        source_data_refs=source_data_refs,
        impact_scope=impact_scope,
        impact_reason=impact_reason,
        needs_author_data=_derive_needs_author_data(impact_scope, signal),
        mapping_confidence=confidence,
    )


def fuse_signals_to_claims(
    signals: list[NumericSignal],
    claim_index: _ClaimIndex,
) -> list[ClaimMapping]:
    """Batch-map multiple signals to claims.

    Returns one ClaimMapping per input signal, in the same order.
    """
    return [fuse_signal_to_claims(s, claim_index) for s in signals]


def enrich_signal_with_claim_mapping(
    signal: NumericSignal,
    mapping: ClaimMapping,
) -> NumericSignal:
    """Return a new NumericSignal with WP8 fields populated from a ClaimMapping.

    The original signal is not modified (NumericSignal is frozen).
    """
    return NumericSignal(
        signal_id=signal.signal_id,
        source_tool=signal.source_tool,
        source_tool_version=signal.source_tool_version,
        detector_id=signal.detector_id,
        detector_family=signal.detector_family,
        raw_kind=signal.raw_kind,
        canonical_category=signal.canonical_category,
        rule=signal.rule,
        n=signal.n,
        effect_size=signal.effect_size,
        mechanical_confidence=signal.mechanical_confidence,
        risk_level_raw=signal.risk_level_raw,
        profile=signal.profile,
        profile_action=signal.profile_action,
        prefilter_action=signal.prefilter_action,
        false_positive_context=signal.false_positive_context,
        prefilter_reason=signal.prefilter_reason,
        applicability_premise=signal.applicability_premise,
        evidence_locator=signal.evidence_locator,
        raw_payload_ref=signal.raw_payload_ref,
        claim_refs=mapping.claim_refs,
        figure_refs=mapping.figure_refs,
        source_data_refs=mapping.source_data_refs,
        impact_scope=mapping.impact_scope,
        impact_reason=mapping.impact_reason,
        needs_author_data=mapping.needs_author_data,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _derive_impact(
    claim_refs: list[str],
    figure_refs: list[str],
    claims: list[dict[str, Any]],
) -> tuple[ImpactScope, str, str]:
    """Derive impact_scope from mapping results.

    Returns:
        Tuple of (impact_scope, impact_reason, confidence).
    """
    if not claim_refs and not figure_refs:
        return (
            "unknown",
            "No claim or figure mapping could be established from the evidence locator.",
            "low",
        )

    # Check if any matched claim is a "core" claim (heuristic: claim_id
    # contains "main", "core", "primary", or is the first claim)
    is_core = False
    for ref in claim_refs:
        ref_lower = ref.lower()
        if any(tok in ref_lower for tok in ("main", "core", "primary")):
            is_core = True
            break

    # Also check if the claim is the first one in the list (often the main claim)
    if not is_core and claims and claim_refs:
        first_claim_id = claims[0].get("claim_id", "")
        if first_claim_id and first_claim_id in claim_refs:
            is_core = True

    if is_core:
        return (
            "core",
            "Signal maps to a primary paper claim; data is central to the main conclusion.",
            "medium",
        )

    if figure_refs:
        return (
            "supporting",
            "Signal maps to a figure that supports but is not central to the main claim.",
            "medium",
        )

    if claim_refs:
        return (
            "supporting",
            "Signal maps to a secondary claim referenced by the paper.",
            "low",
        )

    return (
        "unknown",
        "Mapping was attempted but no confident scope assignment could be made.",
        "low",
    )


def _derive_needs_author_data(
    impact_scope: ImpactScope,
    signal: NumericSignal,
) -> str:
    """Suggest what author data would help resolve the signal.

    Returns an empty string for low-priority or unknown signals where
    no specific material can be requested.
    """
    if impact_scope == "unknown":
        return ""

    if signal.applicability_premise.requires_raw_measurement:
        return "Raw (uncorrected) measurement values for the affected data panel."

    if signal.applicability_premise.requires_integer_valued_items:
        return "Confirmation that the reported values represent integer counts of items."

    if impact_scope == "core":
        return "Source data mapping and processing log for the affected panel."

    return ""
