"""Review queue aggregation view and decision CRUD.

Review items are NOT stored in the database.  They are computed on each
request by reading review suggestions from existing artifacts and merging
with persisted human decisions.

Artifact-reading logic lives in :mod:`engine.reporting.review_queue`.
This module handles DB-backed decision persistence and HTTP-facing
orchestration.

Sources:
- ``visual/findings.json`` — visual finding review suggestions
- ``source_data/pair_forensics.json`` — pair forensics review tasks
- ``agents/review.json`` — agent review manual_review_tasks

Decision state is persisted in the ``review_decisions`` table.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from engine.reporting.review_queue import (
    RISK_ORDER_REVIEW,
    from_agent_review,
    from_pair_forensics,
    from_visual_findings,
)

from .models import ReviewDecisionModel


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_review_items(db: Session, case_id: str, workdir: Path) -> dict[str, Any]:
    """Aggregate review suggestions from artifacts, merge with DB decisions."""
    items: list[dict[str, Any]] = []
    items.extend(from_visual_findings(workdir))
    items.extend(from_pair_forensics(workdir))
    items.extend(from_agent_review(workdir))

    # Merge persisted decisions
    decisions = {
        d.source_ref: d
        for d in db.query(ReviewDecisionModel)
        .filter(ReviewDecisionModel.case_id == case_id)
        .all()
    }
    for item in items:
        dec = decisions.get(item["source_ref"])
        item["decision"] = dec.to_dict() if dec else None

    items.sort(key=lambda x: RISK_ORDER_REVIEW.get(x.get("risk_level", "medium"), 99))
    return {"items": items}


def save_decision(
    db: Session,
    case_id: str,
    source_ref: str,
    *,
    status: str = "open",
    note: str = "",
    user_id: str | None = None,
) -> dict[str, Any]:
    """UPSERT a human review decision.  Returns the saved decision."""
    from .models import utc_now as _utc_now

    existing = (
        db.query(ReviewDecisionModel)
        .filter(
            ReviewDecisionModel.case_id == case_id,
            ReviewDecisionModel.source_ref == source_ref,
        )
        .first()
    )
    if existing:
        existing.status = status
        existing.note = note
        existing.decided_by = user_id
        existing.decided_at = _utc_now()
    else:
        existing = ReviewDecisionModel(
            case_id=case_id,
            source_ref=source_ref,
            status=status,
            note=note,
            decided_by=user_id,
            decided_at=_utc_now(),
        )
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing.to_dict()
