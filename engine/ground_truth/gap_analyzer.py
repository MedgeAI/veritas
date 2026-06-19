"""Phase 2 — Gap analysis for undetected ground-truth claims.

Classifies each claim where ``detected=False`` into one of four gap types:
  - NEW_DETECTOR: requires a new detection capability
  - CALIBRATION: existing tool parameters/thresholds need adjustment
  - INTEGRATION: data-flow break — output exists but is not consumed
  - COVERAGE: required input material is missing
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from engine.ground_truth.mapper import MappedClaim

GapType = Literal["NEW_DETECTOR", "CALIBRATION", "INTEGRATION", "COVERAGE"]


@dataclass
class GapRecord:
    """A single detection gap."""

    gap_type: GapType
    capability_id: str
    claim_description: str
    claim_target: str
    recommended_action: str
    severity: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_GAP_TYPE_KEYWORDS: dict[GapType, list[str]] = {
    "COVERAGE": ["missing", "not provided", "no source data", "not submitted", "未提供"],
    "INTEGRATION": ["produced", "output", "artifact", "generated", "not consumed", "not merged"],
    "CALIBRATION": [
        "threshold", "parameter", "sensitivity", "false positive",
        "false negative", "missed", "calibration", "tuning",
    ],
    "NEW_DETECTOR": [],
}


def analyze_gaps(
    mapped_claims: list[MappedClaim],
    known_capabilities: set[str] | None = None,
) -> list[GapRecord]:
    """Find claims where ``detected=False`` and classify the gap.

    Parameters
    ----------
    mapped_claims : list[MappedClaim]
        Output from ``mapper.map_claims_to_capabilities``.
    known_capabilities : set[str], optional
        Set of capability_ids already registered in the system.
        Used to distinguish NEW_DETECTOR from CALIBRATION.

    Returns
    -------
    list[GapRecord]
        Gap records for undetected claims.
    """
    known = known_capabilities or set()
    gaps: list[GapRecord] = []

    for mc in mapped_claims:
        if mc.detected:
            continue

        gap_type = _classify_gap(mc, known)
        action = _recommended_action(gap_type, mc)
        severity = _estimate_severity(mc)

        gaps.append(GapRecord(
            gap_type=gap_type,
            capability_id=mc.capability_id,
            claim_description=mc.claim.description,
            claim_target=mc.claim.target,
            recommended_action=action,
            severity=severity,
        ))

    return gaps


def _classify_gap(mc: MappedClaim, known: set[str]) -> GapType:
    """Classify the gap type based on claim metadata and known capabilities."""
    desc_lower = mc.claim.description.lower()

    for gap_type, keywords in _GAP_TYPE_KEYWORDS.items():
        if any(kw in desc_lower for kw in keywords):
            if gap_type == "CALIBRATION" and mc.capability_id not in known:
                return "NEW_DETECTOR"
            return gap_type

    if mc.capability_id in known:
        return "CALIBRATION"

    return "NEW_DETECTOR"


def _recommended_action(gap_type: GapType, mc: MappedClaim) -> str:
    """Generate a recommended action string for a gap."""
    actions = {
        "NEW_DETECTOR": (
            f"Design and implement a new detection capability for "
            f"'{mc.capability_id}'. Requires design spec (Phase 3) and "
            f"cross-paper validation (Phase 5)."
        ),
        "CALIBRATION": (
            f"Adjust parameters/thresholds for existing capability "
            f"'{mc.capability_id}'. Review distribution analysis before changing."
        ),
        "INTEGRATION": (
            f"Fix data-flow break: '{mc.capability_id}' produces output "
            f"that is not consumed by downstream pipeline. Check finding_pipeline integration."
        ),
        "COVERAGE": (
            f"Input material missing for '{mc.capability_id}' at target "
            f"'{mc.claim.target}'. Request from author or flag as completeness issue."
        ),
    }
    return actions.get(gap_type, f"Investigate gap for capability '{mc.capability_id}'.")


def _estimate_severity(mc: MappedClaim) -> str:
    """Estimate gap severity based on evidence type."""
    type_severity = {
        "image": "high",
        "source_data": "high",
        "numeric": "medium",
        "completeness": "low",
    }
    return type_severity.get(mc.claim.evidence_type, "medium")
