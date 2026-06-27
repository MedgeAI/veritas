"""Idempotent Celery task that runs the full audit pipeline.

The task is the *only* Celery entry point for audit execution.  It implements
four-layer idempotency so that broker redelivery, worker restarts or
accidental double-dispatch never produce duplicate runs:

1. **Partial unique index** — ``run_id`` is the primary key of the ``runs``
   table, so the row can only exist once.
2. **SELECT ... FOR UPDATE** — the task locks the run row in ``queued``
   status; if no row is found or the status is wrong, the task exits early.
3. **celery_task_id binding** — the locked row's ``celery_task_id`` must
   match ``self.request.id``; a mismatch means another task already claimed
   this run.
4. **Status state machine** — only ``queued -> running`` is accepted.  Any
   other source status is treated as already handled.

The static audit pipeline (``run_static_audit``) handles the full execution
flow internally (PDF parse, source data, visual, agent, report).  This task
wraps it with:

* Idempotency guards (the four layers above).
* Dynamic stage computation stored as JSON on the run row.
* A progress callback that maps pipeline step events to coarse stages,
  updating ``current_stage`` on the run row and firing SSE notifications.
* Final state transition (completed / failed) with cleanup on failure.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import Column, JSON, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from engine.env import get_env

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lightweight ORM layer — self-contained for the Celery worker process.
#
# We cannot import web.backend ORM classes (they pull in FastAPI).
# Instead we define a minimal mapping over the same ``runs`` / ``run_events``
# tables.
# ---------------------------------------------------------------------------


class _TaskBase(DeclarativeBase):
    pass


class _RunRow(_TaskBase):
    """Minimal mirror of the ``runs`` table for the Celery worker."""

    __tablename__ = "runs"

    run_id = Column(String(128), primary_key=True)
    case_id = Column(String(128), nullable=False)
    status = Column(String(32), default="queued")
    agent_mode = Column(String(32), nullable=True)
    started_at = Column(String(32), nullable=True)
    completed_at = Column(String(32), nullable=True)
    summary = Column(JSON, nullable=True)
    workdir = Column(Text, nullable=True)
    final_html_report_url = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    last_event_at = Column(String(32), nullable=True)
    created_at = Column(String(32), nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    stages = Column(JSON, nullable=True)
    current_stage = Column(String(50), nullable=True)


# ---------------------------------------------------------------------------
# Session factory — created lazily from DATABASE_URL
# ---------------------------------------------------------------------------

_session_factory: sessionmaker[Session] | None = None


def _get_session_factory() -> sessionmaker[Session]:
    """Return a cached session factory bound to the database URL.

    The Celery worker process must have ``VERITAS_DATABASE_URL`` (or
    ``DATABASE_URL``) set.  We intentionally avoid importing the web
    backend's ``get_database_url`` to keep this module free of FastAPI
    dependencies.
    """
    global _session_factory
    if _session_factory is not None:
        return _session_factory

    db_url = (
        get_env("VERITAS_DATABASE_URL", required=False)
        or get_env("DATABASE_URL", required=False)
    )
    if not db_url:
        raise RuntimeError(
            "VERITAS_DATABASE_URL (or DATABASE_URL) must be set for the "
            "Celery worker to connect to the runs table."
        )

    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=3,
    )
    _session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return _session_factory


def _utc_now() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# SSE progress notification (best-effort, no-op if unavailable)
# ---------------------------------------------------------------------------


def _notify_progress(run_id: str, event: dict[str, Any]) -> None:
    """Push a progress event to SSE subscribers if the module is available.

    The web backend's SSE infrastructure is the primary consumer.  In the
    Celery worker the SSE module may not be importable (different process,
    different classpath).  We attempt a lazy import and log on failure —
    the run row itself is always the source of truth.
    """
    try:
        from web.backend.veritas_web.sse import notify_progress  # type: ignore[import-not-found]

        event_type = event.get("event", "progress")
        notify_progress(run_id, event_type, event)
    except Exception:
        logger.debug(
            "SSE notify_progress failed for run_id=%s event=%s",
            run_id,
            event.get("key") or event.get("event") or "?",
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Stage computation
# ---------------------------------------------------------------------------

_SOURCE_DATA_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".csv"}

# Map pipeline step keys (from STEP_TOOL_IDS) to coarse stage IDs.
_STEP_TO_STAGE: dict[str, str] = {
    # pdf_parse stage
    "mineru": "pdf_parse",
    "mineru.parse_pdf": "pdf_parse",
    "evidence_ledger": "pdf_parse",
    "paper.evidence_ledger": "pdf_parse",
    # source_data stage
    "material_inventory": "source_data",
    "material.inventory": "source_data",
    "agent_material_plan": "source_data",
    "agent.material_plan": "source_data",
    "numeric_forensics": "source_data",
    "paper.numeric_forensics": "source_data",
    "source_data_profile": "source_data",
    "source_data_findings": "source_data",
    "source_data.pair_forensics": "source_data",
    "source_data_cross_sheet": "source_data",
    "source_data.cross_sheet": "source_data",
    "source_data_verdict": "source_data",
    "paperfraud_rule_match": "source_data",
    # visual stage
    "visual_panel_extraction": "visual",
    "visual_copy_move": "visual",
    "visual_finding_pipeline": "visual",
    "visual_tru_for": "visual",
    "visual_provenance_graph": "visual",
    "visual_copy_move_dense": "visual",
    "visual_image_quality": "visual",
    "exact_image_duplicates": "visual",
    "image.exact_duplicates": "visual",
    "image_similarity_candidates": "visual",
    "image.similarity_candidates": "visual",
    # agent stage
    "agent_plan": "agent",
    "agent.plan": "agent",
    "agent_review": "agent",
    "agent.review": "agent",
    "agent_role_claim_extractor": "agent",
    "agent.role.claim_extractor": "agent",
    "agent_role_source_data_auditor": "agent",
    "agent.role.source_data_auditor": "agent",
    "agent_role_judge": "agent",
    "agent.role.judge": "agent",
    # report stage
    "static_audit_bundle": "report",
    "static_audit.bundle": "report",
    "report": "report",
    "report.render_markdown": "report",
    "html_report": "report",
    "report.render_static_html": "report",
}


def _compute_stages(
    paper_dir: str | Path,
    options: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compute the ordered list of stages for this audit run.

    Stages are always-present (``pdf_parse``, ``report``) or conditional on
    the case directory contents and caller options.
    """
    paper_path = Path(paper_dir)

    # Check for source data files
    has_source_data = False
    if paper_path.is_dir():
        for child in paper_path.rglob("*"):
            if child.is_file() and child.suffix.lower() in _SOURCE_DATA_EXTENSIONS:
                has_source_data = True
                break

    stages: list[dict[str, Any]] = [
        {"id": "pdf_parse", "label": "PDF parsing", "required": True},
    ]
    if has_source_data:
        stages.append(
            {"id": "source_data", "label": "Source data analysis", "required": True}
        )
    if not options.get("skip_visual"):
        stages.append(
            {"id": "visual", "label": "Visual forensics", "required": False}
        )
    if not options.get("skip_agent"):
        stages.append(
            {"id": "agent", "label": "Agent investigation", "required": False}
        )
    stages.append({"id": "report", "label": "Report generation", "required": True})
    return stages


def _resolve_stage_from_event(event: dict[str, Any]) -> str | None:
    """Map a pipeline progress event to a coarse stage ID.

    The pipeline emits events with ``key`` or ``step`` fields.  We look up
    the stage from the ``_STEP_TO_STAGE`` mapping.
    """
    step_key = event.get("key") or event.get("step") or ""
    if not step_key:
        return None
    # Try exact match first, then prefix match
    stage = _STEP_TO_STAGE.get(step_key)
    if stage:
        return stage
    # Try prefix matching (e.g., "source_data.findings" -> "source_data")
    for prefix, stage_id in _STEP_TO_STAGE.items():
        if step_key.startswith(prefix):
            return stage_id
    return None


# ---------------------------------------------------------------------------
# The Celery task
# ---------------------------------------------------------------------------


def _register_task() -> None:
    """Register ``run_audit`` with the Celery app.

    This is called at module import time (by ``celery_app.py`` via the
    ``include`` list) so that workers discover the task without an explicit
    ``@shared_task`` decorator that would require a default Celery app.
    """
    from engine.tasks.celery_app import celery_app

    celery_app.task(
        bind=True,
        name="run_audit",
        max_retries=0,
        acks_late=True,
    )(_run_audit_impl)


def _run_audit_impl(
    self: Any,
    run_id: str,
    case_id: str,
    paper_dir: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute the full audit pipeline for *run_id*.

    Args:
        run_id: Primary key in the ``runs`` table.
        case_id: Foreign key to the ``cases`` table.
        paper_dir: Absolute path to the paper input directory.
        options: Caller-supplied options (``skip_visual``, ``skip_agent``,
            ``agent_mode``, ``output_root``, etc.).

    Returns:
        A summary dict with ``status``, ``run_id``, ``stages`` and
        ``error`` (if any).
    """
    options = options or {}
    celery_task_id = self.request.id
    session_factory = _get_session_factory()

    logger.info(
        "run_audit started: run_id=%s case_id=%s celery_task_id=%s",
        run_id,
        case_id,
        celery_task_id,
    )

    # ------------------------------------------------------------------
    # Layer 1+2: SELECT ... FOR UPDATE — claim the run row
    # ------------------------------------------------------------------
    session: Session = session_factory()
    try:
        row = (
            session.query(_RunRow)
            .filter(_RunRow.run_id == run_id)
            .with_for_update()
            .first()
        )

        if row is None:
            logger.warning("run_audit: run_id=%s not found — skipping", run_id)
            session.close()
            return {"status": "skipped", "reason": "run_id not found"}

        # Layer 2: celery_task_id must match
        if row.celery_task_id and row.celery_task_id != celery_task_id:
            logger.warning(
                "run_audit: run_id=%s already bound to celery_task_id=%s "
                "(this task is %s) — skipping",
                run_id,
                row.celery_task_id,
                celery_task_id,
            )
            session.close()
            return {"status": "skipped", "reason": "celery_task_id mismatch"}

        # Layer 4: status state machine — only queued->running
        if row.status != "queued":
            logger.warning(
                "run_audit: run_id=%s status=%s (expected 'queued') — skipping",
                run_id,
                row.status,
            )
            session.close()
            return {"status": "skipped", "reason": f"status={row.status}"}

        # ------------------------------------------------------------------
        # Layer 3: Atomically bind celery_task_id and transition to running
        # ------------------------------------------------------------------
        now = _utc_now()
        row.status = "running"
        row.started_at = now
        row.last_event_at = now
        row.celery_task_id = celery_task_id

        # Compute dynamic stages
        stages = _compute_stages(paper_dir, options)
        row.stages = stages

        session.commit()
    except Exception:
        session.rollback()
        session.close()
        raise

    # ------------------------------------------------------------------
    # Progress callback — tracks coarse stage transitions and fires SSE
    # ------------------------------------------------------------------
    _current_stage_ref: list[str] = [""]  # mutable cell for closure

    def _progress(event: dict[str, Any]) -> None:
        # Track coarse stage transitions
        stage = _resolve_stage_from_event(event)
        if stage and stage != _current_stage_ref[0]:
            _current_stage_ref[0] = stage
            try:
                s = session_factory()
                try:
                    r = s.query(_RunRow).filter(_RunRow.run_id == run_id).first()
                    if r is not None:
                        r.current_stage = stage
                        r.last_event_at = _utc_now()
                        s.commit()
                except Exception:
                    s.rollback()
                    logger.debug(
                        "stage commit failed for run_id=%s stage=%s",
                        run_id, stage, exc_info=True,
                    )
                finally:
                    s.close()
            except Exception:
                logger.debug("stage update skipped", exc_info=True)

        # Update heartbeat on every progress event
        try:
            s = session_factory()
            try:
                r = s.query(_RunRow).filter(_RunRow.run_id == run_id).first()
                if r is not None:
                    r.last_event_at = _utc_now()
                    s.commit()
            except Exception:
                s.rollback()
                logger.debug(
                    "heartbeat commit failed for run_id=%s",
                    run_id, exc_info=True,
                )
            finally:
                s.close()
        except Exception:
            logger.debug("heartbeat update skipped", exc_info=True)

        # Forward event to SSE subscribers
        _notify_progress(run_id, event)

    # ------------------------------------------------------------------
    # Execute the pipeline (single call — it handles all internal stages)
    # ------------------------------------------------------------------
    result: dict[str, Any] = {
        "status": "completed",
        "run_id": run_id,
        "case_id": case_id,
        "stages": stages,
    }
    failed_steps: list[str] = []

    try:
        from engine.static_audit.pipeline import run_static_audit

        summary = run_static_audit(
            paper_dir,
            case_id=case_id,
            output_root=options.get("output_root", "outputs"),
            fresh=options.get("fresh", True),
            force=options.get("force", True),
            no_env_file=options.get("no_env_file", False),
            agent_mode=options.get("agent_mode", "review"),
            agent_model=options.get("agent_model", "dashscope/qwen3.7-plus"),
            opencode_bin=options.get("opencode_bin")
            or get_env("OPENCODE_BIN", required=False, default="opencode"),
            agent_timeout_seconds=int(options.get("agent_timeout_seconds", 300)),
            agent_max_retries=int(options.get("agent_max_retries", 1)),
            reproducibility_tier=options.get("reproducibility_tier", "full"),
            progress=_progress,
        )
        result["summary"] = summary
        result["workdir"] = summary.get("workdir")
        result["final_html_report_url"] = f"/api/cases/{case_id}/report/html"

        # If the pipeline reported failed steps, determine final status
        pipeline_failed = summary.get("failed_steps") or []
        if pipeline_failed:
            failed_steps = list(pipeline_failed)
            exit_code = int(summary.get("exit_code", 1))
            # Safety net: if reports exist despite non-zero exit, treat as
            # completed with partial failure (same logic as runner.py).
            if exit_code != 0:
                report_path = summary.get("final_report", "")
                html_path = summary.get("final_html_report", "")
                if report_path and html_path:
                    if Path(report_path).exists() and Path(html_path).exists():
                        failed_steps = []  # partial success

        if failed_steps:
            result["status"] = "failed"
            result["error"] = f"failed_steps={failed_steps}"

    except Exception as exc:
        logger.exception(
            "run_audit: pipeline failed for run_id=%s: %s",
            run_id,
            exc,
        )
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------
    # Finalise run record
    # ------------------------------------------------------------------
    try:
        final_row = (
            session.query(_RunRow).filter(_RunRow.run_id == run_id).first()
        )
        if final_row is not None:
            # Guard: if the run was cancelled while the pipeline was
            # executing, do NOT overwrite the cancelled status.
            if final_row.status == "cancelled":
                logger.info(
                    "run_audit: run_id=%s was cancelled during execution — "
                    "preserving cancelled status",
                    run_id,
                )
            else:
                now = _utc_now()
                final_row.completed_at = now
                final_row.last_event_at = now
                final_row.current_stage = None  # clear — run is done
                if result["status"] == "completed":
                    final_row.status = "completed"
                    final_row.summary = result.get("summary")
                    final_row.workdir = result.get("workdir")
                    final_row.final_html_report_url = result.get(
                        "final_html_report_url"
                    )
                    if failed_steps:
                        final_row.error = f"partial: {failed_steps}"
                elif result["status"] == "cancelled":
                    final_row.status = "cancelled"
                else:
                    final_row.status = "failed"
                    final_row.error = result.get("error", "unknown error")
            session.commit()
    except Exception:
        session.rollback()
        logger.exception("run_audit: failed to finalise run_id=%s", run_id)

    # ------------------------------------------------------------------
    # Cleanup on failure / cancel
    # ------------------------------------------------------------------
    if result["status"] in ("failed", "cancelled"):
        try:
            from engine.tasks.process_cleanup import cleanup_audit_processes

            cleanup_result = cleanup_audit_processes(run_id, case_id)
            result["cleanup"] = cleanup_result
            logger.info(
                "run_audit: cleanup for run_id=%s: %s",
                run_id,
                cleanup_result,
            )
        except Exception:
            logger.exception(
                "run_audit: cleanup failed for run_id=%s", run_id
            )

    session.close()

    logger.info(
        "run_audit finished: run_id=%s status=%s",
        run_id,
        result["status"],
    )
    return result


# ---------------------------------------------------------------------------
# Auto-register with the Celery app when this module is imported.
# ---------------------------------------------------------------------------
try:
    _register_task()
except Exception:
    # During testing or if the celery app is not yet configured, the
    # registration may fail.  The task function is still importable.
    logger.debug("Could not auto-register run_audit task", exc_info=True)
