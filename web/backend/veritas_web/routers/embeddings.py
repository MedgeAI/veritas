"""Embedding indexing and similarity search endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ..dependencies import AppDependencies, get_app_dependencies, require_case_access
from ..embeddings import (
    SSCDEncoder,
    get_index_status,
    index_panels,
    query_all_similar_pairs,
    query_similar,
    update_index_job,
)
from ..models import CaseRecord

router = APIRouter(tags=["embeddings"])
logger = logging.getLogger(__name__)

# Module-level encoder singleton (lazy-loaded)
_encoder: SSCDEncoder | None = None


def _get_encoder() -> SSCDEncoder:
    global _encoder
    if _encoder is None:
        _encoder = SSCDEncoder()
    return _encoder


@router.post("/cases/{case_id}/embeddings/index")
async def trigger_indexing(
    case_id: str,
    background_tasks: BackgroundTasks,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Trigger SSCD embedding extraction for all panels in the case.

    Runs as a background task.  Use GET /embeddings/status to poll progress.
    """
    workdir = deps.artifacts.latest_workdir(case_id)
    if not workdir:
        raise HTTPException(status_code=404, detail="case has no completed audit workdir")

    encoder = _get_encoder()
    if not encoder.available:
        raise HTTPException(
            status_code=503,
            detail=f"SSCD model not available at {encoder._model_path}. "
                   "Download the model first (see README).",
        )

    if deps._session_factory is None:
        raise HTTPException(status_code=503, detail={"error": "database_unavailable", "detail": "database not configured"})

    session = deps._session_factory()
    try:
        update_index_job(session, case_id, "queued", detail="SSCD embedding extraction queued")
    finally:
        session.close()

    def _run_index() -> None:
        session = deps._session_factory()
        try:
            update_index_job(session, case_id, "running", detail="SSCD embedding extraction running")
            result = index_panels(session, case_id, workdir, encoder)
            update_index_job(
                session,
                case_id,
                result.get("status", "completed"),
                indexed_count=int(result.get("indexed_count") or 0),
                expected_count=result.get("expected_count"),
                detail=str(result.get("detail") or result.get("error") or ""),
            )
        except Exception as exc:
            logger.exception("SSCD embedding indexing failed for case %s", case_id)
            try:
                update_index_job(session, case_id, "failed", detail=str(exc))
            except Exception:
                logger.exception("failed to persist SSCD indexing failure for case %s", case_id)
        finally:
            session.close()

    background_tasks.add_task(_run_index)

    return {
        "status": "queued",
        "case_id": case_id,
        "message": "Embedding extraction started. Poll /embeddings/status for progress.",
    }


@router.get("/cases/{case_id}/embeddings/status")
async def embedding_status(
    case_id: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Return the indexing status for a case."""
    if deps._session_factory is None:
        raise HTTPException(status_code=503, detail={"error": "database_unavailable", "detail": "database not configured"})

    session = deps._session_factory()
    try:
        status = get_index_status(session, case_id)
        encoder = _get_encoder()
        status["model_available"] = encoder.available
        return status
    finally:
        session.close()


@router.get("/cases/{case_id}/similarity")
async def get_similar_panels(
    case_id: str,
    panel_id: str,
    top_k: int = 20,
    threshold: float = 0.85,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Find panels similar to the given panel."""
    if deps._session_factory is None:
        raise HTTPException(status_code=503, detail={"error": "database_unavailable", "detail": "database not configured"})

    session = deps._session_factory()
    try:
        results = query_similar(session, case_id, panel_id, top_k=top_k, threshold=threshold)
        return {"query_panel_id": panel_id, "threshold": threshold, "similar_panels": results}
    finally:
        session.close()


@router.get("/cases/{case_id}/similarity/pairs")
async def get_all_similar_pairs(
    case_id: str,
    threshold: float = 0.85,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Find all pairs of similar panels above the threshold."""
    if deps._session_factory is None:
        raise HTTPException(status_code=503, detail={"error": "database_unavailable", "detail": "database not configured"})

    session = deps._session_factory()
    try:
        pairs = query_all_similar_pairs(session, case_id, threshold=threshold)
        return {"threshold": threshold, "pair_count": len(pairs), "pairs": pairs}
    finally:
        session.close()
