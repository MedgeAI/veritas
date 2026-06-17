"""Review queue aggregation view and decision CRUD.

Review items are NOT stored in the database.  They are computed on each
request by reading review suggestions from existing artifacts and merging
with persisted human decisions.

Sources:
- ``visual/findings.json`` — visual finding review suggestions
- ``source_data/pair_forensics.json`` — pair forensics review tasks
- ``agents/review.json`` — agent review manual_review_tasks

Decision state is persisted in the ``review_decisions`` table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .models import ReviewDecisionModel
from engine.static_audit.paths import resolve_artifact_path

RISK_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_review_items(db: Session, case_id: str, workdir: Path) -> dict[str, Any]:
    """Aggregate review suggestions from artifacts, merge with DB decisions."""
    items: list[dict[str, Any]] = []
    items.extend(_from_visual_findings(workdir))
    items.extend(_from_pair_forensics(workdir))
    items.extend(_from_agent_review(workdir))

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

    items.sort(key=lambda x: RISK_ORDER.get(x.get("risk_level", "medium"), 99))
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


# ---------------------------------------------------------------------------
# Artifact readers
# ---------------------------------------------------------------------------


def _read_json(workdir: Path, artifact_name: str) -> dict[str, Any] | None:
    """Read a JSON artifact, trying the mapped path then the legacy flat path."""
    mapped = resolve_artifact_path(workdir, artifact_name)
    if mapped.exists():
        return json.loads(mapped.read_text(encoding="utf-8"))
    legacy = workdir / artifact_name
    if legacy.exists():
        return json.loads(legacy.read_text(encoding="utf-8"))
    return None


def _from_visual_findings(workdir: Path) -> list[dict[str, Any]]:
    """Extract review items from ``visual/findings.json``."""
    data = _read_json(workdir, "visual_findings.json")
    if not data:
        # Also try under the visual/ prefix
        data = _read_json(workdir, "visual/findings.json")
    if not data:
        return []

    items: list[dict[str, Any]] = []
    findings = data.get("findings") or []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        finding_id = finding.get("finding_id") or finding.get("id") or "unknown"
        risk = finding.get("risk_level", "medium")
        category = finding.get("issue_category", "consistency")
        items.append({
            "source_ref": f"visual_findings:{finding_id}",
            "title": finding.get("title", f"Visual finding {finding_id}"),
            "risk_level": risk,
            "issue_category": category,
            "source": "visual_findings",
            "evidence_refs": finding.get("evidence_refs", []),
            "recommended_action": finding.get("recommended_action", ""),
            "benign_explanation": finding.get("benign_explanation", ""),
        })
    return items


def _from_pair_forensics(workdir: Path) -> list[dict[str, Any]]:
    """Extract review items from ``source_data/pair_forensics.json``."""
    data = _read_json(workdir, "source_data/pair_forensics.json")
    if not data:
        data = _read_json(workdir, "source_data_pair_forensics.json")
    if not data:
        return []

    items: list[dict[str, Any]] = []
    review_tasks = data.get("pair_forensics_review_tasks") or []
    for task in review_tasks:
        if not isinstance(task, dict):
            continue
        task_id = task.get("task_id") or task.get("id") or "unknown"
        items.append({
            "source_ref": f"pair_forensics:{task_id}",
            "title": task.get("title", f"Pair forensics review: {task_id}"),
            "risk_level": task.get("risk_level", "medium"),
            "issue_category": task.get("issue_category", "consistency"),
            "source": "pair_forensics",
            "evidence_refs": task.get("evidence_refs", []),
            "recommended_action": task.get("recommended_action", ""),
            "benign_explanation": task.get("benign_explanation", ""),
        })
    return items


def _from_agent_review(workdir: Path) -> list[dict[str, Any]]:
    """Extract review items from ``agents/review.json``."""
    data = _read_json(workdir, "agents/review.json")
    if not data:
        data = _read_json(workdir, "agent_review.json")
    if not data:
        return []

    items: list[dict[str, Any]] = []
    review_tasks = data.get("manual_review_tasks") or []
    for task in review_tasks:
        if not isinstance(task, dict):
            continue
        task_id = task.get("task_id") or task.get("id") or "unknown"
        items.append({
            "source_ref": f"agent_review:{task_id}",
            "title": task.get("title", f"Agent review task: {task_id}"),
            "risk_level": task.get("risk_level", "medium"),
            "issue_category": task.get("issue_category", "matching"),
            "source": "agent_review",
            "evidence_refs": task.get("evidence_refs", []),
            "recommended_action": task.get("recommended_action", ""),
            "benign_explanation": task.get("benign_explanation", ""),
        })
    return items
