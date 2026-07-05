"""ReviewDossier: structured review package for a high-priority numeric finding.

A dossier aggregates everything needed for a human or LLM reviewer to
assess a single numeric signal: the signal itself, bounded evidence,
claim/figure mapping, benign explanation checklist, and impact hypothesis.

Per PRD §3.5 "Dossier + Adversarial Refute".
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal


ReviewStatus = Literal[
    "pending",
    "confirmed",
    "rejected",
    "needs_more_material",
    "escalated",
]


@dataclass
class ReviewDossier:
    """Review dossier for a single numeric signal or signal cluster.

    Attributes:
        schema_version: Dossier schema version.
        dossier_id: Unique identifier for this dossier.
        target_signal_ids: Signal IDs this dossier covers.
        signal_summary: Brief description of the signal.
        detector_family: Detector family (e.g., "statistical_impossibility").
        risk_level_raw: Original detector risk level.
        suspicion_tier: 1 (hardest to explain benignly) to 3 (easiest).
        impact_scope: How important the data is to the paper's main claim.
        evidence_locator: Dict representation of the EvidenceLocator.
        claim_refs: Claim IDs related to this signal.
        figure_refs: Figure panel references.
        source_data_refs: Source data file references.
        profile_action: Profile action taken (kept/demoted/hidden).
        prefilter_reason: Reason for prefilter decision.
        false_positive_context: FP context from detector.
        benign_explanation_checklist: Structured benign hypotheses.
        impact_hypothesis: How this signal might affect the paper's conclusion.
        missing_materials: What additional materials would resolve uncertainty.
        scan_errors: Any scan errors associated with this signal.
        review_status: Current review status.
        metadata: Additional metadata.
    """

    schema_version: str = "1.0"
    dossier_id: str = ""
    target_signal_ids: list[str] = field(default_factory=list)
    signal_summary: str = ""
    detector_family: str = ""
    risk_level_raw: str = ""
    suspicion_tier: int = 2
    impact_scope: Literal["core", "supporting", "peripheral", "unknown"] = "unknown"
    evidence_locator: dict[str, Any] = field(default_factory=dict)
    claim_refs: list[str] = field(default_factory=list)
    figure_refs: list[str] = field(default_factory=list)
    source_data_refs: list[str] = field(default_factory=list)
    profile_action: str = ""
    prefilter_reason: str = ""
    false_positive_context: list[str] = field(default_factory=list)
    benign_explanation_checklist: list[dict[str, Any]] = field(default_factory=list)
    impact_hypothesis: str = ""
    missing_materials: list[str] = field(default_factory=list)
    scan_errors: list[str] = field(default_factory=list)
    review_status: ReviewStatus = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewDossier:
        """Deserialize from dictionary."""
        return cls(
            schema_version=data.get("schema_version", "1.0"),
            dossier_id=data.get("dossier_id", ""),
            target_signal_ids=data.get("target_signal_ids", []),
            signal_summary=data.get("signal_summary", ""),
            detector_family=data.get("detector_family", ""),
            risk_level_raw=data.get("risk_level_raw", ""),
            suspicion_tier=data.get("suspicion_tier", 2),
            impact_scope=data.get("impact_scope", "unknown"),
            evidence_locator=data.get("evidence_locator", {}),
            claim_refs=data.get("claim_refs", []),
            figure_refs=data.get("figure_refs", []),
            source_data_refs=data.get("source_data_refs", []),
            profile_action=data.get("profile_action", ""),
            prefilter_reason=data.get("prefilter_reason", ""),
            false_positive_context=data.get("false_positive_context", []),
            benign_explanation_checklist=data.get("benign_explanation_checklist", []),
            impact_hypothesis=data.get("impact_hypothesis", ""),
            missing_materials=data.get("missing_materials", []),
            scan_errors=data.get("scan_errors", []),
            review_status=data.get("review_status", "pending"),
            metadata=data.get("metadata", {}),
        )

    def requires_refute(self) -> bool:
        """Whether this dossier requires red-team refute before escalation.

        Tier 1 and Tier 2 candidates require refute review.
        """
        return self.suspicion_tier <= 2
