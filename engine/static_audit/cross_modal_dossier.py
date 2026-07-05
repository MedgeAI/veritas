"""Cross-Modal Dossier (WP9).

Aggregates numeric, image, and code evidence by paper claim, forming
a unified review dossier that spans modalities.  This is Veritas's
structural advantage over single-modality tools.

A ``CrossModalDossier`` collects all signals/findings related to one
claim and provides a unified view for red-team refute and review.

The red-team refute checklist is extensible by modality: each modality
can register its own set of refute mechanisms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Modality = Literal["numeric", "image", "code"]


@dataclass(frozen=True)
class ModalityEvidence:
    """A single piece of evidence tagged with its modality.

    Attributes:
        evidence_id: Unique identifier for this evidence item.
        modality: One of "numeric", "image", "code".
        signal_id: For numeric signals, the NumericSignal.signal_id.
            For image/code, the finding_id or equivalent.
        source_tool: Tool that produced this evidence.
        risk_level: Risk/severity level.
        summary: Human-readable description.
        metadata: Modality-specific extra data.
    """

    evidence_id: str
    modality: Modality
    signal_id: str = ""
    source_tool: str = ""
    risk_level: str = "info"
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "modality": self.modality,
            "signal_id": self.signal_id,
            "source_tool": self.source_tool,
            "risk_level": self.risk_level,
            "summary": self.summary,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RefuteAttempt:
    """A single red-team refute attempt for a dossier.

    Attributes:
        mechanism: The benign explanation mechanism being tested
            (e.g. "shared_control_or_replot", "unit_conversion_or_formula").
        status: One of "checked_no_fit", "plausible_unconfirmed",
            "confirmed_benign", "not_applicable".
        note: Free-text explanation of the assessment.
        modality: Which modality this refute attempt targets.
    """

    mechanism: str
    status: str = "plausible_unconfirmed"
    note: str = ""
    modality: Modality = "numeric"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mechanism": self.mechanism,
            "status": self.status,
            "note": self.note,
            "modality": self.modality,
        }


# Default refute checklist mechanisms per modality.
# These can be extended via ``register_refute_mechanism``.
_DEFAULT_REFUTE_MECHANISMS: dict[Modality, list[str]] = {
    "numeric": [
        "shared_control_or_replot",
        "unit_conversion_or_formula",
        "fixed_denominator",
        "axis_dose_time_rank_coordinate",
        "technical_replicate",
        "boundary_censoring_missing_fill",
        "model_output_or_statistical_summary",
        "methods_legend_allowing_reuse",
        "missing_provenance_or_independence_premise",
    ],
    "image": [
        "same_panel_replot_different_channel",
        "figure_composite_legitimate_crop",
        "provider_stock_image",
        "published_in_prior_work_with_permission",
    ],
    "code": [
        "different_input_data",
        "different_random_seed",
        "known_library_version_difference",
        "hardware_float_precision_difference",
    ],
}

# Mutable copy for runtime registration
_refute_mechanisms: dict[Modality, list[str]] = {
    k: list(v) for k, v in _DEFAULT_REFUTE_MECHANISMS.items()
}


def register_refute_mechanism(modality: Modality, mechanism: str) -> None:
    """Register a new refute mechanism for a modality.

    This allows extending the red-team checklist without modifying
    the default set.
    """
    if modality not in _refute_mechanisms:
        _refute_mechanisms[modality] = []
    if mechanism not in _refute_mechanisms[modality]:
        _refute_mechanisms[modality].append(mechanism)


def get_refute_mechanisms(modality: Modality) -> list[str]:
    """Return the current refute mechanism checklist for a modality."""
    return list(_refute_mechanisms.get(modality, []))


def get_all_refute_mechanisms() -> dict[str, list[str]]:
    """Return all refute mechanisms grouped by modality."""
    return {k: list(v) for k, v in _refute_mechanisms.items()}


@dataclass(frozen=True)
class CrossModalDossier:
    """Unified review dossier for a single claim across modalities.

    Aggregates numeric signals, image findings, and code findings
    that all relate to the same paper claim.

    Attributes:
        dossier_id: Unique identifier for this dossier.
        claim_id: The paper claim this dossier covers.
        claim_text: Human-readable claim description.
        evidence: All evidence items grouped under this claim.
        refute_attempts: Red-team refute attempts so far.
        review_status: Current review status.
        strongest_benign_explanation: Best benign explanation found.
        remaining_uncertainty: What is still unknown.
        recommended_final_status: Recommended action.
        needs_author_data: What author material is needed.
    """

    dossier_id: str
    claim_id: str = ""
    claim_text: str = ""
    evidence: list[ModalityEvidence] = field(default_factory=list)
    refute_attempts: list[RefuteAttempt] = field(default_factory=list)
    review_status: str = "pending"
    strongest_benign_explanation: str = ""
    remaining_uncertainty: str = ""
    recommended_final_status: str = "needs_more_material"
    needs_author_data: str = ""

    def evidence_by_modality(self, modality: Modality) -> list[ModalityEvidence]:
        """Return all evidence items for a specific modality."""
        return [e for e in self.evidence if e.modality == modality]

    def modalities_present(self) -> list[Modality]:
        """Return which modalities have evidence in this dossier."""
        seen: set[Modality] = set()
        for e in self.evidence:
            seen.add(e.modality)
        return sorted(seen)

    def highest_risk_level(self) -> str:
        """Return the highest risk level across all evidence.

        Order: critical > high > medium > low > info.
        """
        order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
        best = "info"
        for e in self.evidence:
            if order.get(e.risk_level, 0) > order.get(best, 0):
                best = e.risk_level
        return best

    def to_dict(self) -> dict[str, Any]:
        return {
            "dossier_id": self.dossier_id,
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "evidence": [e.to_dict() for e in self.evidence],
            "refute_attempts": [r.to_dict() for r in self.refute_attempts],
            "review_status": self.review_status,
            "strongest_benign_explanation": self.strongest_benign_explanation,
            "remaining_uncertainty": self.remaining_uncertainty,
            "recommended_final_status": self.recommended_final_status,
            "needs_author_data": self.needs_author_data,
            "modalities_present": self.modalities_present(),
            "highest_risk_level": self.highest_risk_level(),
        }


def build_cross_modal_dossier(
    dossier_id: str,
    claim_id: str,
    claim_text: str,
    numeric_signals: list[Any] | None = None,
    image_findings: list[dict[str, Any]] | None = None,
    code_findings: list[dict[str, Any]] | None = None,
) -> CrossModalDossier:
    """Build a CrossModalDossier from multi-modal findings.

    Args:
        dossier_id: Unique dossier identifier.
        claim_id: Paper claim this dossier covers.
        claim_text: Human-readable claim text.
        numeric_signals: NumericSignal instances with claim_refs containing
            this claim_id.
        image_findings: Visual finding dicts with ``finding_id``,
            ``risk_level``, ``summary``.
        code_findings: Code finding dicts with ``finding_id``,
            ``risk_level``, ``summary``.

    Returns:
        A CrossModalDossier aggregating all evidence.
    """
    evidence: list[ModalityEvidence] = []

    # Numeric evidence
    for sig in (numeric_signals or []):
        evidence.append(
            ModalityEvidence(
                evidence_id=f"NUM-{sig.signal_id}",
                modality="numeric",
                signal_id=sig.signal_id,
                source_tool=getattr(sig, "source_tool", "unknown"),
                risk_level=getattr(sig, "risk_level_raw", "info"),
                summary=getattr(sig, "rule", ""),
                metadata={
                    "canonical_category": getattr(sig, "canonical_category", ""),
                    "impact_scope": getattr(sig, "impact_scope", "unknown"),
                },
            )
        )

    # Image evidence
    for f in (image_findings or []):
        evidence.append(
            ModalityEvidence(
                evidence_id=f"IMG-{f.get('finding_id', '')}",
                modality="image",
                signal_id=f.get("finding_id", ""),
                source_tool=f.get("source_tool", "visual_forensics"),
                risk_level=f.get("risk_level", "info"),
                summary=f.get("summary", ""),
                metadata={k: v for k, v in f.items() if k not in (
                    "finding_id", "risk_level", "summary", "source_tool"
                )},
            )
        )

    # Code evidence
    for f in (code_findings or []):
        evidence.append(
            ModalityEvidence(
                evidence_id=f"CODE-{f.get('finding_id', '')}",
                modality="code",
                signal_id=f.get("finding_id", ""),
                source_tool=f.get("source_tool", "code_audit"),
                risk_level=f.get("risk_level", "info"),
                summary=f.get("summary", ""),
                metadata={k: v for k, v in f.items() if k not in (
                    "finding_id", "risk_level", "summary", "source_tool"
                )},
            )
        )

    return CrossModalDossier(
        dossier_id=dossier_id,
        claim_id=claim_id,
        claim_text=claim_text,
        evidence=evidence,
    )


def build_dossiers_for_claims(
    claims: list[dict[str, Any]],
    numeric_signals: list[Any] | None = None,
    image_findings: list[dict[str, Any]] | None = None,
    code_findings: list[dict[str, Any]] | None = None,
) -> list[CrossModalDossier]:
    """Build one dossier per claim, distributing evidence by claim_refs.

    Each numeric signal is assigned to the dossier of the first claim
    in its claim_refs.  Image/code findings are assigned by their
    ``claim_refs`` field if present.

    Returns:
        List of CrossModalDossier instances, one per claim that has
        at least one piece of evidence.
    """
    all_numeric = numeric_signals or []
    all_image = image_findings or []
    all_code = code_findings or []

    # Build claim_id -> index mapping
    claim_ids = [c.get("claim_id", "") for c in claims]
    claim_map = {c.get("claim_id", ""): c for c in claims}

    dossiers: list[CrossModalDossier] = []

    for cid in claim_ids:
        if not cid:
            continue

        # Filter numeric signals whose claim_refs contain this claim_id
        sigs = [s for s in all_numeric if cid in getattr(s, "claim_refs", [])]

        # Filter image findings whose claim_refs contain this claim_id
        imgs = [f for f in all_image if cid in f.get("claim_refs", [])]

        # Filter code findings
        codes = [f for f in all_code if cid in f.get("claim_refs", [])]

        if not sigs and not imgs and not codes:
            continue

        claim_text = claim_map.get(cid, {}).get("text", "")
        dossier = build_cross_modal_dossier(
            dossier_id=f"DOSSIER-{cid}",
            claim_id=cid,
            claim_text=claim_text,
            numeric_signals=sigs,
            image_findings=imgs,
            code_findings=codes,
        )
        dossiers.append(dossier)

    return dossiers
