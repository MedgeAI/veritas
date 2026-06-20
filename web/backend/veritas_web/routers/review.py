"""Review queue endpoints — aggregation view + decision CRUD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import AppDependencies, get_app_dependencies, require_case_access
from ..models import CaseRecord, ReviewDecisionCreate

router = APIRouter(tags=["review"])


@router.get("/cases/{case_id}/review-items")
async def list_review_items(
    case_id: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Aggregate review suggestions from artifacts, merge with DB decisions."""
    workdir = deps.artifacts.latest_workdir(case_id)
    if not workdir:
        raise HTTPException(
            status_code=404,
            detail={"error": "audit_workdir_missing", "detail": "case has no completed audit workdir"},
        )

    from ..review_queue import list_review_items as _list

    if deps._session_factory is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "detail": "database not configured for review queue"},
        )

    session = deps._session_factory()
    try:
        return _list(session, case_id, workdir)
    finally:
        session.close()


@router.post("/cases/{case_id}/review-items/{source_ref}/decision")
async def save_decision(
    case_id: str,
    source_ref: str,
    payload: ReviewDecisionCreate,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Write or update a human review decision."""
    if deps._session_factory is None:
        raise HTTPException(status_code=501, detail="database not configured for review decisions")

    from ..review_queue import save_decision as _save

    session = deps._session_factory()
    try:
        result = _save(
            session,
            case_id,
            source_ref,
            status=payload.status,
            note=payload.note,
            user_id=case.owner,
        )
        return result
    finally:
        session.close()
