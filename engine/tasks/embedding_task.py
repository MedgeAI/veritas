"""Celery task for SSCD embedding indexing.

Follows the same self-contained pattern as ``audit_task.py``: a lightweight
ORM layer mirrors the ``embedding_index_jobs`` table so the Celery worker
process does not import FastAPI or web backend modules.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight ORM — mirrors the embedding_index_jobs table.
# ---------------------------------------------------------------------------


class _JobBase(DeclarativeBase):
    pass


class _EmbeddingJobRow(_JobBase):
    __tablename__ = "embedding_index_jobs"

    case_id = Column(String(128), primary_key=True)
    status = Column(String(32), default="queued")
    indexed_count = Column(Integer, default=0)
    expected_count = Column(Integer, nullable=True)
    detail = Column(Text, default="")
    started_at = Column(String(32), nullable=True)
    completed_at = Column(String(32), nullable=True)
    updated_at = Column(String(32), nullable=True)


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

_session_factory: sessionmaker[Session] | None = None


def _get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is not None:
        return _session_factory

    db_url = os.environ.get("VERITAS_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "VERITAS_DATABASE_URL (or DATABASE_URL) must be set for the "
            "Celery worker to connect to the embedding_index_jobs table."
        )

    engine = create_engine(db_url, pool_pre_ping=True, pool_size=2, max_overflow=3)
    _session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return _session_factory


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Task implementation
# ---------------------------------------------------------------------------


def _index_embeddings_impl(
    case_id: str,
    workdir: str,
) -> dict[str, Any]:
    """Run SSCD embedding extraction for all panels in *case_id*."""
    from engine.embeddings.sscd import SSCDEncoder  # type: ignore[import-untyped]

    session_factory = _get_session_factory()
    now = _utc_now()

    # Mark job as running.
    session = session_factory()
    try:
        job = session.get(_EmbeddingJobRow, case_id)
        if job is not None:
            job.status = "running"
            job.detail = "SSCD embedding extraction running"
            job.updated_at = now
            session.commit()
    except Exception:
        session.rollback()
        logger.debug("Failed to mark embedding job as running: case_id=%s", case_id, exc_info=True)
    finally:
        session.close()

    result: dict[str, Any] = {"status": "completed", "case_id": case_id}

    try:
        encoder = SSCDEncoder()
        if not encoder.available:
            result["status"] = "failed"
            result["error"] = f"SSCD model not found at {encoder._model_path}"
        else:
            from web.backend.veritas_web.embeddings import index_panels  # type: ignore[import-untyped]

            session = session_factory()
            try:
                result = index_panels(session, case_id, Path(workdir), encoder)
                session.close()
            except Exception:
                session.rollback()
                session.close()
                logger.debug("index_panels failed, rolling back: case_id=%s", case_id, exc_info=True)
                raise
    except Exception as exc:
        logger.exception("index_embeddings failed: case_id=%s", case_id)
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"

    # Finalise job row.
    session = session_factory()
    try:
        job = session.get(_EmbeddingJobRow, case_id)
        if job is not None:
            now = _utc_now()
            job.status = result.get("status", "completed")
            job.indexed_count = int(result.get("indexed_count", 0))
            job.expected_count = result.get("expected_count")
            job.detail = str(result.get("detail") or result.get("error") or "")
            job.updated_at = now
            job.completed_at = now
            session.commit()
    except Exception:
        session.rollback()
        logger.exception("failed to finalise embedding job: case_id=%s", case_id)
    finally:
        session.close()

    return result


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def _register_task() -> None:
    from engine.tasks.celery_app import celery_app

    celery_app.task(
        name="index_embeddings",
        max_retries=0,
        acks_late=True,
    )(_index_embeddings_impl)


try:
    _register_task()
except Exception:
    logger.debug("Could not auto-register index_embeddings task", exc_info=True)
