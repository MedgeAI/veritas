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

import asyncio
import logging
from typing import Any

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from engine.env import get_env

from ..auth import AuthContext
from ..dependencies import (
    AppDependencies,
    get_app_dependencies,
    get_auth_context,
)
from ..models import REPRODUCIBILITY_TIERS
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
    # Backward compatibility for older clients that sent the tier at the top
    # level instead of inside options.
    reproducibility_tier: str | None = None


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
# SSE auth dependency — unified provider path.
#
# Cloudflare tunnel injects ``Cf-Access-Jwt-Assertion`` into every
# origin-bound request (including SSE), so same-origin EventSource calls
# are authenticated without a query-param token.
#
# For the legacy ``bearer`` mode (non-Cloudflare), the token is still
# accepted via query param because ``EventSource`` cannot set custom headers.
# ---------------------------------------------------------------------------


async def get_auth_context_sse(
    request: Request,
    token: str | None = Query(None),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> AuthContext:
    """Authenticate SSE requests via the same auth provider.

    Cloudflare tunnel injects ``Cf-Access-Jwt-Assertion`` into every
    request, so same-origin EventSource calls work without a query param.

    For ``bearer`` mode (legacy), the HS256 token is accepted via the
    ``token`` query parameter since ``EventSource`` cannot set headers.
    """
    provider = deps.auth_provider

    from ..auth import BearerTokenProvider, NoAuthProvider

    if isinstance(provider, NoAuthProvider):
        return AuthContext(user_id="operator", roles=frozenset({"admin"}))

    # For bearer mode: accept token via query param (EventSource limitation)
    if isinstance(provider, BearerTokenProvider) and token:
        try:
            payload = pyjwt.decode(
                token,
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

    # For cloudflare (and bearer without query param): use request headers
    headers = dict(request.headers)
    ctx = provider.authenticate(headers)
    if ctx is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return ctx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _use_celery() -> bool:
    return get_env("VERITAS_USE_CELERY", required=False, default="").lower() in (
        "1", "true", "yes"
    )


def _get_runner(deps: AppDependencies) -> AuditRunner:
    runner = getattr(deps, "runner", None)
    if runner is None:
        raise HTTPException(status_code=503, detail="audit runner not available")
    return runner  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# POST /api/audit — submit
# ---------------------------------------------------------------------------


def _submit_audit_sync(
    case_id: str,
    uid: str | None,
    store: Any,
    runner: AuditRunner,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Synchronous business logic for submit_audit (runs in executor)."""
    # Verify case exists and is owned by the caller (admin bypasses check).
    try:
        case_record = store.get_case(case_id, user_id=uid)
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"not the owner of case {case_id}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"case not found: {case_id}")

    # Validate PDF exists in inputs (search recursively — uploads may
    # be organised into subdirectories via relative_path).
    inputs_dir = store.inputs_dir(case_id)
    if next(inputs_dir.rglob("*.pdf"), None) is None:
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
    max_queue_size = int(get_env("AUDIT_MAX_QUEUE_SIZE", required=False, default="10"))
    queued_count = store.count_queued_runs()
    if queued_count >= max_queue_size:
        raise HTTPException(
            status_code=429,
            detail=f"audit queue full (max={max_queue_size})",
        )

    # Save reproducibility_tier on case if provided
    tier = options.get("reproducibility_tier") or getattr(
        case_record, "reproducibility_tier", "full"
    )
    if not isinstance(tier, str) or tier not in REPRODUCIBILITY_TIERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid reproducibility_tier: {tier}. "
                f"Must be one of: {', '.join(REPRODUCIBILITY_TIERS.keys())}"
            ),
        )
    options["reproducibility_tier"] = tier
    if tier != getattr(case_record, "reproducibility_tier", "full"):
        store.update_case(case_id, {"reproducibility_tier": tier}, user_id=uid)

    # Create the run row.
    run = store.create_run(
        case_id,
        agent_mode=str(options.get("agent_mode", "review")),
    )

    # Version tracking: if this case has previous runs, increment version
    # and link to the previous report.
    all_runs = store.list_runs(case_id)
    completed_runs = [r for r in all_runs if r.status == "completed" and r.run_id != run.run_id]
    if completed_runs:
        current_case = store.get_case(case_id, user_id=uid)
        new_version = (current_case.report_version or 1) + 1
        # Use the latest completed run's run_id as the parent report reference
        latest_completed = max(
            completed_runs,
            key=lambda r: r.completed_at or "",
        )
        store.update_case(
            case_id,
            {
                "report_version": new_version,
                "parent_report_id": latest_completed.run_id,
            },
            user_id=uid,
        )

    if _use_celery():
        run = runner._dispatch_celery_task(run, case_id, options)
    else:
        # Thread-pool path: create_run already inserted the row;
        # submit the work to the executor (start() would create a
        # second row, so we call _executor directly).
        runner._executor.submit(
            runner.run_sync,
            case_id,
            run.run_id,
            options,
        )

    return _run_to_job_dict(run, store)


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
    uid = None if auth.is_admin() else auth.user_id
    store = deps.store
    runner = _get_runner(deps)
    options = dict(payload.options)
    if payload.reproducibility_tier:
        options.setdefault("reproducibility_tier", payload.reproducibility_tier)

    return await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _submit_audit_sync(payload.case_id, uid, store, runner, options),
    )


# ---------------------------------------------------------------------------
# GET /api/audit/queue — queue status
#
# IMPORTANT: Must be defined BEFORE the parameterized /{job_id} routes
# below, otherwise FastAPI matches ``/api/audit/queue`` as job_id="queue".
# ---------------------------------------------------------------------------


@router.get("/queue")
async def queue_status(
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Return the number of queued/running jobs and the concurrency limits."""
    store = deps.store
    runner = _get_runner(deps)

    loop = asyncio.get_event_loop()
    queued = await loop.run_in_executor(None, store.count_queued_runs)
    running = await loop.run_in_executor(None, store.count_running_runs)
    max_queue_size = int(get_env("AUDIT_MAX_QUEUE_SIZE", required=False, default="10"))

    return {
        "queued": queued,
        "running": running,
        "max_concurrent": runner._max_concurrent,
        "max_queue_size": max_queue_size,
    }


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
    loop = asyncio.get_event_loop()

    def _get_status_sync():
        run_model = _get_run_model(store, job_id)
        _verify_case_ownership(store, run_model.case_id, auth.user_id, is_admin=auth.is_admin())
        return _run_model_to_dict(run_model)

    return await loop.run_in_executor(None, _get_status_sync)


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
    loop = asyncio.get_event_loop()

    def _cancel_sync():
        run_model = _get_run_model(store, job_id)
        _verify_case_ownership(store, run_model.case_id, auth.user_id, is_admin=auth.is_admin())

        if run_model.status not in ("queued", "running"):
            raise HTTPException(
                status_code=409,
                detail=f"job {job_id} is not active (status={run_model.status})",
            )

        run = runner.cancel_run(job_id, run_model.case_id)
        return _run_to_job_dict(run, store)

    return await loop.run_in_executor(None, _cancel_sync)


# ---------------------------------------------------------------------------
# GET /api/audit/{job_id}/stream — SSE
# ---------------------------------------------------------------------------


@router.get("/{job_id}/stream")
async def stream_audit_progress(
    job_id: str,
    request: Request,
    events: str = Query(
        "lifecycle",
        description="Event verbosity: lifecycle (default), agent, or debug",
    ),
    auth: AuthContext = Depends(get_auth_context_sse),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> StreamingResponse:
    """Stream real-time audit progress via Server-Sent Events.

    Authentication is via the ``token`` query parameter because the
    browser ``EventSource`` API cannot set custom headers.

    Parameters
    ----------
    events:
        Event verbosity level:
        - ``lifecycle`` (default): pipeline/step/progress events
        - ``agent``: lifecycle + agent reasoning events
        - ``debug``: all events including log streams
    Last-Event-ID:
        HTTP header for reconnection.  When present, the stream resumes
        from the event with id strictly greater than the supplied value.
    """
    store = deps.store
    loop = asyncio.get_event_loop()

    def _validate_and_get_run():
        run_model = _get_run_model(store, job_id)
        _verify_case_ownership(store, run_model.case_id, auth.user_id, is_admin=auth.is_admin())
        return run_model

    await loop.run_in_executor(None, _validate_and_get_run)

    # Validate events parameter.
    level = events if events in ("lifecycle", "agent", "debug") else "lifecycle"

    # Extract Last-Event-ID header for reconnection support.
    last_event_id = request.headers.get("Last-Event-ID")

    engine = getattr(deps, "_engine", None)
    return StreamingResponse(
        sse_event_stream(
            job_id,
            db_engine=engine,
            level=level,
            last_event_id=last_event_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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


def _verify_case_ownership(
    store: Any, case_id: str, user_id: str, *, is_admin: bool = False
) -> None:
    """Raise 403 if *user_id* does not own *case_id*.  Admin bypasses check."""
    uid = None if is_admin else user_id
    try:
        store.get_case(case_id, user_id=uid)
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
