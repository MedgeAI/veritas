"""Red-team refute: adversarial review of high-priority numeric signals.

The red-team reviewer's default stance is "this finding may be a false
positive." It walks through the refute checklist, attempting to find
a benign explanation for each signal. The output is a structured JSON
artifact that records what was checked and what remains uncertain.

Per PRD §3.5 and WP7.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Literal

from engine.static_audit.dossiers.refute_checklist import (
    REFUTE_CHECKLIST,
    RefuteStatus,
    validate_mechanism,
)
from engine.static_audit.dossiers.review_dossier import ReviewDossier


ReviewStatus = Literal[
    "confirmed",          # Signal is real, no benign explanation fits
    "rejected",           # Benign explanation confirmed
    "needs_more_material",  # Cannot conclude without additional data
]


@dataclass
class RefuteAttempt:
    """A single refute attempt for one mechanism.

    Attributes:
        mechanism: The checklist mechanism identifier.
        status: Outcome of checking this mechanism.
        evidence_ref: Reference to evidence supporting this assessment.
        note: Human-readable note explaining the assessment.
    """

    mechanism: str
    status: RefuteStatus
    evidence_ref: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RefuteAttempt:
        return cls(
            mechanism=data["mechanism"],
            status=data["status"],
            evidence_ref=data.get("evidence_ref", ""),
            note=data.get("note", ""),
        )

    def validate(self) -> list[str]:
        """Validate this refute attempt. Returns list of error messages."""
        errors: list[str] = []
        if not validate_mechanism(self.mechanism):
            errors.append(
                f"Unknown mechanism {self.mechanism!r}. "
                f"Must be one of the 10 refute checklist items."
            )
        valid_statuses = {
            "checked_no_fit",
            "plausible_unconfirmed",
            "confirmed",
            "not_applicable",
            "not_checked",
        }
        if self.status not in valid_statuses:
            errors.append(
                f"Invalid status {self.status!r}. "
                f"Must be one of {sorted(valid_statuses)}"
            )
        return errors


@dataclass
class RedTeamRefute:
    """Output of the red-team refute review.

    Attributes:
        schema_version: Schema version for forward compatibility.
        review_id: Unique identifier for this review.
        target_signal_ids: Signal IDs reviewed.
        review_status: Final review status.
        reviewer_role: Always "red_team".
        refute_attempts: List of refute attempts for each mechanism.
        strongest_benign_explanation: The most plausible benign explanation.
        remaining_uncertainty: What remains uncertain after review.
        recommended_final_status: Recommended status for the finding.
        needs_author_data: What author-provided data would resolve uncertainty.
    """

    schema_version: str = "1.0"
    review_id: str = ""
    target_signal_ids: list[str] = field(default_factory=list)
    review_status: ReviewStatus = "needs_more_material"
    reviewer_role: str = "red_team"
    refute_attempts: list[RefuteAttempt] = field(default_factory=list)
    strongest_benign_explanation: str = ""
    remaining_uncertainty: str = ""
    recommended_final_status: str = "needs_more_material"
    needs_author_data: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "review_id": self.review_id,
            "target_signal_ids": self.target_signal_ids,
            "review_status": self.review_status,
            "reviewer_role": self.reviewer_role,
            "refute_attempts": [a.to_dict() for a in self.refute_attempts],
            "strongest_benign_explanation": self.strongest_benign_explanation,
            "remaining_uncertainty": self.remaining_uncertainty,
            "recommended_final_status": self.recommended_final_status,
            "needs_author_data": self.needs_author_data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RedTeamRefute:
        return cls(
            schema_version=data.get("schema_version", "1.0"),
            review_id=data.get("review_id", ""),
            target_signal_ids=data.get("target_signal_ids", []),
            review_status=data.get("review_status", "needs_more_material"),
            reviewer_role=data.get("reviewer_role", "red_team"),
            refute_attempts=[
                RefuteAttempt.from_dict(a) for a in data.get("refute_attempts", [])
            ],
            strongest_benign_explanation=data.get("strongest_benign_explanation", ""),
            remaining_uncertainty=data.get("remaining_uncertainty", ""),
            recommended_final_status=data.get("recommended_final_status", "needs_more_material"),
            needs_author_data=data.get("needs_author_data", ""),
        )

    def validate(self) -> list[str]:
        """Validate the refute output schema. Returns list of error messages."""
        errors: list[str] = []
        if not self.review_id:
            errors.append("review_id is required")
        if not self.target_signal_ids:
            errors.append("target_signal_ids must not be empty")
        valid_statuses = {"confirmed", "rejected", "needs_more_material"}
        if self.review_status not in valid_statuses:
            errors.append(
                f"Invalid review_status {self.review_status!r}. "
                f"Must be one of {sorted(valid_statuses)}"
            )
        if self.reviewer_role != "red_team":
            errors.append(f"reviewer_role must be 'red_team', got {self.reviewer_role!r}")
        for attempt in self.refute_attempts:
            errors.extend(attempt.validate())
        return errors

    def save(self, path: Path) -> None:
        """Save refute output to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


def run_red_team_refute(
    dossier: ReviewDossier,
    refute_attempts: list[RefuteAttempt],
    review_id: str = "",
    strongest_benign_explanation: str = "",
    remaining_uncertainty: str = "",
    recommended_final_status: str = "needs_more_material",
    needs_author_data: str = "",
) -> RedTeamRefute:
    """Run red-team refute review on a dossier.

    This is the deterministic runner: it takes structured refute attempts
    (produced by an LLM or human reviewer) and packages them into a
    validated RedTeamRefute artifact.

    Args:
        dossier: The review dossier being refuted.
        refute_attempts: List of refute attempts (one per mechanism checked).
        review_id: Unique review identifier. Auto-generated if empty.
        strongest_benign_explanation: The most plausible benign explanation.
        remaining_uncertainty: What remains uncertain after review.
        recommended_final_status: Recommended final status.
        needs_author_data: What author data would resolve uncertainty.

    Returns:
        Validated RedTeamRefute artifact.

    Raises:
        ValueError: If the refute output fails schema validation.
    """
    # Determine review_status from refute attempts
    has_confirmed_benign = any(
        a.status == "confirmed" for a in refute_attempts
    )
    has_plausible_unconfirmed = any(
        a.status == "plausible_unconfirmed" for a in refute_attempts
    )

    if has_confirmed_benign:
        review_status: ReviewStatus = "rejected"
    elif has_plausible_unconfirmed:
        review_status = "needs_more_material"
    else:
        review_status = "confirmed"

    # Auto-generate review_id if not provided
    if not review_id:
        signal_ids = "-".join(dossier.target_signal_ids[:2])
        review_id = f"REFUTE-{signal_ids}" if signal_ids else "REFUTE-UNKNOWN"

    refute = RedTeamRefute(
        schema_version="1.0",
        review_id=review_id,
        target_signal_ids=list(dossier.target_signal_ids),
        review_status=review_status,
        reviewer_role="red_team",
        refute_attempts=list(refute_attempts),
        strongest_benign_explanation=strongest_benign_explanation,
        remaining_uncertainty=remaining_uncertainty,
        recommended_final_status=recommended_final_status,
        needs_author_data=needs_author_data,
    )

    errors = refute.validate()
    if errors:
        raise ValueError(
            f"Red-team refute output failed validation: {'; '.join(errors)}"
        )

    return refute
