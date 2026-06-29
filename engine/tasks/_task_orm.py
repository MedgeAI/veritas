"""Shared ORM layer for Celery task modules.

Self-contained mirror over the ``runs`` / ``run_events`` tables so that
Celery workers do not import the web backend's SQLAlchemy models (Engine
must not depend on Web).

All task modules (``audit_task``, ``stale_run_watchdog``, etc.) import
their ORM classes and session helpers from here instead of defining
duplicates inline.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, JSON, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from engine.env import get_env


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class _TaskBase(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# ORM mirrors — ``runs`` and ``run_events`` tables
# ---------------------------------------------------------------------------


class _RunRow(_TaskBase):
    """Minimal mirror of the ``runs`` table for Celery workers."""

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


class _RunEventRow(_TaskBase):
    """Minimal mirror of the ``run_events`` table."""

    __tablename__ = "run_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(128), nullable=False)
    event_type = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(String(32), nullable=True)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_session_factory: sessionmaker[Session] | None = None


def _get_session_factory() -> sessionmaker[Session]:
    """Return a cached session factory bound to the database URL.

    Uses ``VERITAS_DATABASE_URL`` (primary) with ``DATABASE_URL`` as a
    legacy fallback.  Raises ``RuntimeError`` when neither is set.
    """
    global _session_factory
    if _session_factory is not None:
        return _session_factory

    db_url = get_env("VERITAS_DATABASE_URL", required=False) or get_env(
        "DATABASE_URL", required=False
    )
    if not db_url:
        raise RuntimeError(
            "VERITAS_DATABASE_URL (or DATABASE_URL) must be set for the "
            "Celery worker to connect to the database."
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
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
