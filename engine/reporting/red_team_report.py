"""Red-Team Review Status Report (WP10).

Reports on the red-team refute review status for high-priority findings.
This module aggregates refute review artifacts and produces a summary
of the review status across all dossiers.

The red-team review is a quality gate: Tier 1/2 candidates should have
a refute review before entering the high-priority conclusion area.

This module does NOT read raw detector output.  It consumes structured
refute review artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RedTeamRefuteStatus:
    """Red-team review status for a single dossier/signal.

    Attributes:
        review_id: Unique review identifier.
        target_signal_ids: Signal IDs under review.
        review_status: One of "confirmed", "rejected",
            "needs_more_material", "pending".
        reviewer_role: Typically "red_team".
        refute_count: Number of refute attempts made.
        strongest_benign_explanation: Best benign explanation found.
        remaining_uncertainty: What remains unknown.
        recommended_final_status: Recommended action.
        needs_author_data: What author material is needed.
    """

    review_id: str
    target_signal_ids: list[str] = field(default_factory=list)
    review_status: str = "pending"
    reviewer_role: str = "red_team"
    refute_count: int = 0
    strongest_benign_explanation: str = ""
    remaining_uncertainty: str = ""
    recommended_final_status: str = "needs_more_material"
    needs_author_data: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "target_signal_ids": list(self.target_signal_ids),
            "review_status": self.review_status,
            "reviewer_role": self.reviewer_role,
            "refute_count": self.refute_count,
            "strongest_benign_explanation": self.strongest_benign_explanation,
            "remaining_uncertainty": self.remaining_uncertainty,
            "recommended_final_status": self.recommended_final_status,
            "needs_author_data": self.needs_author_data,
        }


@dataclass(frozen=True)
class RedTeamReport:
    """Summary of all red-team reviews.

    Attributes:
        total_reviews: Total number of red-team reviews.
        confirmed: Reviews with status "confirmed".
        rejected: Reviews with status "rejected".
        needs_more_material: Reviews with status "needs_more_material".
        pending: Reviews with status "pending".
        reviews: Individual review statuses.
        gate_compliance: Fraction of Tier 1/2 candidates that have
            a completed refute review.
    """

    total_reviews: int = 0
    confirmed: int = 0
    rejected: int = 0
    needs_more_material: int = 0
    pending: int = 0
    reviews: list[RedTeamRefuteStatus] = field(default_factory=list)
    gate_compliance: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_reviews": self.total_reviews,
            "confirmed": self.confirmed,
            "rejected": self.rejected,
            "needs_more_material": self.needs_more_material,
            "pending": self.pending,
            "reviews": [r.to_dict() for r in self.reviews],
            "gate_compliance": self.gate_compliance,
        }


def build_red_team_report(
    refute_reviews: list[dict[str, Any]] | None = None,
    tier1_tier2_candidates: int = 0,
) -> RedTeamReport:
    """Build a RedTeamReport from refute review artifacts.

    Args:
        refute_reviews: List of refute review dicts, each with at least
            ``review_id`` and ``review_status``.
        tier1_tier2_candidates: Total number of Tier 1/2 candidates
            that should have a refute review (for gate compliance).

    Returns:
        A RedTeamReport summarizing the red-team review status.
    """
    raw = refute_reviews or []
    if not raw:
        return RedTeamReport()

    reviews: list[RedTeamRefuteStatus] = []
    confirmed = rejected = needs_more = pending_count = 0

    for data in raw:
        review = RedTeamRefuteStatus(
            review_id=str(data.get("review_id", "")),
            target_signal_ids=list(data.get("target_signal_ids", [])),
            review_status=str(data.get("review_status", "pending")),
            reviewer_role=str(data.get("reviewer_role", "red_team")),
            refute_count=int(data.get("refute_count", len(data.get("refute_attempts", [])))),
            strongest_benign_explanation=str(
                data.get("strongest_benign_explanation", "")
            ),
            remaining_uncertainty=str(data.get("remaining_uncertainty", "")),
            recommended_final_status=str(
                data.get("recommended_final_status", "needs_more_material")
            ),
            needs_author_data=str(data.get("needs_author_data", "")),
        )
        reviews.append(review)

        if review.review_status == "confirmed":
            confirmed += 1
        elif review.review_status == "rejected":
            rejected += 1
        elif review.review_status == "needs_more_material":
            needs_more += 1
        else:
            pending_count += 1

    # Gate compliance: how many Tier 1/2 candidates have a completed review
    completed_reviews = confirmed + rejected
    gate_compliance = (
        completed_reviews / tier1_tier2_candidates
        if tier1_tier2_candidates > 0
        else 1.0
    )

    return RedTeamReport(
        total_reviews=len(reviews),
        confirmed=confirmed,
        rejected=rejected,
        needs_more_material=needs_more,
        pending=pending_count,
        reviews=reviews,
        gate_compliance=round(min(gate_compliance, 1.0), 4),
    )
