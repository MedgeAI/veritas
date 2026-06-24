"""Async audit job management endpoints.

Provides the HTTP API for submitting, querying, cancelling and streaming
audit jobs.  When ``VERITAS_USE_CELERY`` is truthy the heavy pipeline
runs in a Celery worker; otherwise the existing ``AuditRunner``
thread-pool path is used transparently.

Endpoints
---------
POST   /api/audit              Submit a new audit job.
GET    /api/audit/{job_id}     Query job status.
DELETE /api/audit/{job_id}     Cancel a queued or running job.
GET    /api/audit/{job_id}/stream   SSE progress stream.
GET    /api/audit/queue        Queue depth summary.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..auth import AuthContext
from ..dependencies import (
    AppDependencies,
    get_app_dependencies,
    get_auth_context,
)
from ..runner import AuditRunner
from ..sse import sse_event_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["audit-jobs"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class AuditSubmitRequest(BaseModel):
    case_id: str
    options: dict[str, Any] = Field(default_factory=dict)


class AuditJobResponse(BaseModel):
    job_id: str
    case_id: str
    status: str
    celery_task_id: str | None = None
    stages: list[dict[str, Any]] | None = None
    current_stage: str | None = None
    message: str = ""


class QueueStatusResponse(BaseModel):
    queued: int
    running: int
    max_concurrent: int
    max_queue_size: int


# ---------------------------------------------------------------------------
# SSE auth dependency — accepts token via query param (EventSource cannot
# set custom HTTP headers).
# ---------------------------------------------------------------------------


async def get_auth_context_sse(
    token: str | None = Query(None),
    authorization: str | None = Query(None, alias="authorization"),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> AuthContext:
    """Authenticate SSE requests.

    The ``EventSource`` browser API cannot set custom headers, so the
    JWT is accepted via the ``token`` query parameter.  The standard
    ``Authorization`` header path is preserved for non-browser clients.
    """
    provider = deps.auth_provider

    from ..auth import NoAuthProvider

    if isinstance(provider, NoAuthProvider):
        return AuthContext(user_id="operator", roles=frozenset({"admin"}))

    # Try query-param token first (SSE / EventSource).
    bearer_token = token or authorization
    if bearer_token:
        from ..auth import BearerTokenProvider

        if isinstance(provider, BearerTokenProvider):
            try:
                payload = pyjwt.decode(
                    bearer_token,
                    provider.shared_secret,
                    algorithms=["HS256"],
                    issuer=provider.issuer,
                    options={"require": ["exp", "iss", "userId"]},
                )
            except pyjwt.InvalidTokenError:
                raise HTTPException(status_code=401, detail="invalid token")
            user_id = payload.get("userId")
            if not isinstance(user_id, str) or not user_id.strip():
                raise HTTPException(status_code=401, detail="invalid token payload")
            return AuthContext(
                user_id=user_id.strip(),
                roles=frozenset({"operator"}),
            )

    raise HTTPException(status_code=401, detail="authentication required")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _use_celery() -> bool:
    return os.environ.get("VERITAS_USE_CELERY", "").lower() in ("1", "true", "yes")


def _get_runner(deps: AppDependencies) -> AuditRunner:
    runner = getattr(deps, "runner", None)
    if runner is None:
        raise HTTPException(status_code=503, detail="audit runner not available")
    return runner  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# POST /api/audit — submit
# ---------------------------------------------------------------------------


@router.post("", status_code=202)
async def submit_audit(
    payload: AuditSubmitRequest,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Submit a new audit job for *case_id*.

    * Validates that the case has at least one input file (PDF).
    * Rejects with 409 if there is already an active run for the case.
    * Rejects with 429 if the global concurrent-audit limit is reached.
    * Returns 202 with the newly created job record.
    """
    case_id = payload.case_id
    store = deps.store
    runner = _get_runner(deps)

    # Verify case exists and is owned by the caller.
    try:
        store.get_case(case_id, user_id=auth.user_id)
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"not the owner of case {case_id}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"case not found: {case_id}")

    # Validate PDF exists in inputs.
    inputs_dir = store.inputs_dir(case_id)
    pdfs = list(inputs_dir.glob("*.pdf"))
    if not pdfs:
        raise HTTPException(
            status_code=400,
            detail=f"no PDF found in inputs for case {case_id}",
        )

    # Idempotency: no duplicate active run for the same case.
    active_runs = store.get_active_runs_by_case(case_id)
    if active_runs:
        raise HTTPException(
            status_code=409,
            detail=(
                f"case {case_id} already has an active run: "
                f"{active_runs[0].run_id} ({active_runs[0].status})"
            ),
        )

    # Global concurrency limit — worker slots (running tasks).
    running_count = store.count_running_runs()
    max_concurrent = runner._max_concurrent
    if running_count >= max_concurrent:
        raise HTTPException(
            status_code=429,
            detail=f"too many running audits (max={max_concurrent})",
        )

    # Queue capacity limit — waiting tasks (queued).
    max_queue_size = int(os.environ.get("AUDIT_MAX_QUEUE_SIZE", "10"))
    queued_count = store.count_queued_runs()
    if queued_count >= max_queue_size:
        raise HTTPException(
            status_code=429,
            detail=f"audit queue full (max={max_queue_size})",
        )

    # Create the run row.
    run = store.create_run(
        case_id,
        agent_mode=str(payload.options.get("agent_mode", "review")),
    )

    if _use_celery():
        run = runner._dispatch_celery_task(run, case_id, payload.options)
    else:
        # Thread-pool path: create_run already inserted the row;
        # submit the work to the executor (start() would create a
        # second row, so we call _executor directly).
        runner._executor.submit(
            runner.run_sync,
            case_id,
            run.run_id,
            payload.options,
        )

    return _run_to_job_dict(run, store)


# ---------------------------------------------------------------------------
# GET /api/audit/{job_id} — status
# ---------------------------------------------------------------------------


@router.get("/{job_id}")
async def get_audit_status(
    job_id: str,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Return the current status of job *job_id*, including stage progress."""
    store = deps.store
    run_model = _get_run_model(store, job_id)
    _verify_case_ownership(store, run_model.case_id, auth.user_id)
    return _run_model_to_dict(run_model)


# ---------------------------------------------------------------------------
# DELETE /api/audit/{job_id} — cancel
# ---------------------------------------------------------------------------


@router.delete("/{job_id}")
async def cancel_audit(
    job_id: str,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Cancel a queued or running audit job.

    * If the job was dispatched to Celery, the task is revoked.
    * If the job was running in the thread pool, subprocess cleanup is
      attempted via :func:`cleanup_audit_processes`.
    """
    store = deps.store
    runner = _get_runner(deps)
    run_model = _get_run_model(store, job_id)
    _verify_case_ownership(store, run_model.case_id, auth.user_id)

    if run_model.status not in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"job {job_id} is not active (status={run_model.status})",
        )

    run = runner.cancel_run(job_id, run_model.case_id)
    return _run_to_job_dict(run, store)


# ---------------------------------------------------------------------------
# GET /api/audit/{job_id}/stream — SSE
# ---------------------------------------------------------------------------


@router.get("/{job_id}/stream")
async def stream_audit_progress(
    job_id: str,
    auth: AuthContext = Depends(get_auth_context_sse),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> StreamingResponse:
    """Stream real-time audit progress via Server-Sent Events.

    Authentication is via the ``token`` query parameter because the
    browser ``EventSource`` API cannot set custom headers.
    """
    store = deps.store
    run_model = _get_run_model(store, job_id)
    _verify_case_ownership(store, run_model.case_id, auth.user_id)

    engine = getattr(deps, "_engine", None)
    return StreamingResponse(
        sse_event_stream(job_id, db_engine=engine),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/audit/queue — queue status
# ---------------------------------------------------------------------------


@router.get("/queue")
async def queue_status(
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Return the number of queued/running jobs and the concurrency limits."""
    store = deps.store
    runner = _get_runner(deps)

    queued = store.count_queued_runs()
    running = store.count_running_runs()
    max_queue_size = int(os.environ.get("AUDIT_MAX_QUEUE_SIZE", "10"))

    return {
        "queued": queued,
        "running": running,
        "max_concurrent": runner._max_concurrent,
        "max_queue_size": max_queue_size,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_run_model(store: Any, run_id: str) -> Any:
    """Fetch the ORM ``RunModel`` row for *run_id*, or 404."""
    from ..models import RunModel

    session = store._session()
    try:
        model = session.get(RunModel, run_id)
        if model is None:
            raise HTTPException(status_code=404, detail=f"job not found: {run_id}")
        # Detach by reading all needed attributes before session closes.
        return _RunSnapshot(model)
    finally:
        session.close()


class _RunSnapshot:
    """Lightweight immutable copy of a ``RunModel`` row.

    Avoids lazy-loading issues after the session is closed.
    """

    __slots__ = (
        "run_id",
        "case_id",
        "status",
        "agent_mode",
        "started_at",
        "completed_at",
        "summary",
        "workdir",
        "final_html_report_url",
        "error",
        "last_event_at",
        "celery_task_id",
        "stages",
        "current_stage",
    )

    def __init__(self, model: Any) -> None:
        for attr in self.__slots__:
            setattr(self, attr, getattr(model, attr, None))


def _verify_case_ownership(store: Any, case_id: str, user_id: str) -> None:
    """Raise 403 if *user_id* does not own *case_id*."""
    try:
        store.get_case(case_id, user_id=user_id)
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"not the owner of case {case_id}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"case not found: {case_id}")


def _run_model_to_dict(model: Any) -> dict[str, Any]:
    """Serialise a ``_RunSnapshot`` (or ORM ``RunModel``) to a JSON-safe dict."""
    return {
        "job_id": model.run_id,
        "case_id": model.case_id,
        "status": model.status,
        "celery_task_id": model.celery_task_id,
        "stages": model.stages,
        "current_stage": model.current_stage,
        "started_at": model.started_at,
        "completed_at": model.completed_at,
        "error": model.error,
        "summary": model.summary,
        "workdir": model.workdir,
        "final_html_report_url": model.final_html_report_url,
    }


def _run_to_job_dict(run: Any, store: Any) -> dict[str, Any]:
    """Build an ``AuditJobResponse``-shaped dict from an ``AuditRunRecord``.

    The ``celery_task_id``, ``stages`` and ``current_stage`` fields are not
    part of ``AuditRunRecord`` so they are fetched from the DB directly.
    """
    celery_task_id = store.get_run_celery_task_id(run.run_id)

    # Fetch stages / current_stage from the ORM row.
    from ..models import RunModel

    session = store._session()
    try:
        orm_run = session.get(RunModel, run.run_id)
        stages = orm_run.stages if orm_run else None
        current_stage = orm_run.current_stage if orm_run else None
    finally:
        session.close()

    return {
        "job_id": run.run_id,
        "case_id": run.case_id,
        "status": run.status,
        "celery_task_id": celery_task_id,
        "stages": stages,
        "current_stage": current_stage,
        "message": "dispatched to Celery worker"
        if celery_task_id
        else "submitted to thread pool",
    }
