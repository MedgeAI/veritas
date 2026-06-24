"""Server-Sent Events backend for real-time audit progress streaming.

Two entry points:

* :func:`notify_progress` — **sync**, called from Celery workers.
  Persists an event row and fires ``pg_notify('audit_progress', …)``.

* :func:`sse_event_stream` — **async** generator consumed by FastAPI
  ``StreamingResponse``.  Polls ``run_events`` every 2 s, yields SSE-formatted
  frames, and stops when the run reaches a terminal status.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from sqlalchemy import text

from .database import create_db_engine, create_session_factory, get_database_url
from .models import utc_now

logger = logging.getLogger(__name__)

# Terminal run statuses that end the SSE stream.
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

# Poll interval for the SSE fallback (seconds).
_POLL_INTERVAL = 2

# Heartbeat interval (seconds) — keep-alive so proxies do not close the connection.
_HEARTBEAT_INTERVAL = 15


# ---------------------------------------------------------------------------
# Sync: called from Celery worker process
# ---------------------------------------------------------------------------


def notify_progress(
    run_id: str,
    event_type: str,
    data: dict[str, Any] | None = None,
    *,
    database_url: str | None = None,
) -> None:
    """Persist a progress event and notify listeners via ``pg_notify``.

    This is a **synchronous** function — it must be callable from a Celery
    worker that has no async event loop.

    * Creates its own DB session (workers are independent processes).
    * Inserts a row into ``run_events``.
    * Fires ``pg_notify('audit_progress', payload)`` with JSON payload.
    * Updates ``runs.last_event_at`` so stale-detection stays accurate.
    * Commits and closes the session in all paths.

    Parameters
    ----------
    run_id:
        The run this event belongs to.
    event_type:
        One of ``stage_changed``, ``progress``, ``completed``, ``failed``,
        ``cancelled``.
    data:
        Arbitrary JSON-serialisable payload.
    database_url:
        Override for testing.  Defaults to the standard
        ``VERITAS_DATABASE_URL`` resolution.
    """
    data = data or {}
    db_url = database_url or get_database_url()
    engine = create_db_engine(db_url)
    session_factory = create_session_factory(engine)
    session = session_factory()
    ts = utc_now()
    notify_payload = json.dumps(
        {
            "run_id": run_id,
            "event_type": event_type,
            "data": data,
            "timestamp": ts,
        }
    )
    try:
        # Insert the event row so it survives even if no SSE client is connected.
        session.execute(
            text(
                "INSERT INTO run_events (run_id, event_type, payload, created_at) "
                "VALUES (:run_id, :event_type, :payload, :ts)"
            ),
            {
                "run_id": run_id,
                "event_type": event_type,
                "payload": json.dumps(data),
                "ts": ts,
            },
        )
        # Update heartbeat.
        session.execute(
            text("UPDATE runs SET last_event_at = :ts WHERE run_id = :run_id"),
            {"ts": ts, "run_id": run_id},
        )
        # If this is a terminal event, also flip the run status.
        if event_type in _TERMINAL_STATUSES:
            session.execute(
                text(
                    "UPDATE runs SET status = :status, completed_at = :ts "
                    "WHERE run_id = :run_id"
                ),
                {"status": event_type, "ts": ts, "run_id": run_id},
            )
        # Fire the PG NOTIFY.
        session.execute(
            text("SELECT pg_notify('audit_progress', :payload)"),
            {"payload": notify_payload},
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Async: consumed by FastAPI StreamingResponse
# ---------------------------------------------------------------------------


def _format_sse(
    event_type: str, data: dict[str, Any], event_id: int | None = None
) -> str:
    """Format a dict as an SSE frame (``event: …\\ndata: …\\n\\n``)."""
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data)}")
    return "\n".join(lines) + "\n\n"


async def sse_event_stream(
    run_id: str,
    db_engine: Any = None,
) -> AsyncIterator[str]:
    """Async generator that yields SSE frames for *run_id*.

    Polls ``run_events`` every :data:`_POLL_INTERVAL` seconds for new rows
    with ``id > last_id``.  Falls back to polling because async PG LISTEN
    requires ``asyncpg`` which is not in the dependency tree.

    The generator:

    * Yields each pending event as an SSE frame.
    * Sends an ``event: heartbeat`` comment every :data:`_HEARTBEAT_INTERVAL`
      seconds to keep proxies alive.
    * Stops after yielding a ``completed``, ``failed`` or ``cancelled`` event,
      or when the run row itself has reached a terminal status.

    Parameters
    ----------
    run_id:
        The run to stream events for.
    db_engine:
        SQLAlchemy engine to reuse.  If ``None``, a new engine is created
        and disposed when the stream ends.
    """
    own_engine = db_engine is None
    engine = db_engine or create_db_engine()
    session_factory = create_session_factory(engine)
    last_id: int = 0
    last_heartbeat: float = 0.0
    loop = asyncio.get_running_loop()

    try:
        while True:
            events: list[dict[str, Any]] = []
            run_status: str | None = None

            def _poll() -> tuple[list[dict[str, Any]], str | None]:
                """Sync DB work — runs in a thread to avoid blocking the loop."""
                session = session_factory()
                try:
                    # Fetch new events since last_id.
                    rows = session.execute(
                        text(
                            "SELECT id, event_type, payload, created_at "
                            "FROM run_events "
                            "WHERE run_id = :run_id AND id > :last_id "
                            "ORDER BY id"
                        ),
                        {"run_id": run_id, "last_id": last_id},
                    ).fetchall()
                    fetched: list[dict[str, Any]] = []
                    for row in rows:
                        payload = (
                            row[2]
                            if isinstance(row[2], dict)
                            else json.loads(row[2] or "{}")
                        )
                        fetched.append(
                            {
                                "id": row[0],
                                "event_type": row[1],
                                "payload": payload,
                                "timestamp": row[3],
                            }
                        )
                    # Read current run status to detect terminal state.
                    run_row = session.execute(
                        text("SELECT status FROM runs WHERE run_id = :run_id"),
                        {"run_id": run_id},
                    ).fetchone()
                    status = run_row[0] if run_row else None
                    return fetched, status
                finally:
                    session.close()

            events, run_status = await loop.run_in_executor(None, _poll)

            now = loop.time()

            # Yield any new events.
            for ev in events:
                last_id = ev["id"]
                frame_data: dict[str, Any] = {
                    "timestamp": ev["timestamp"],
                    **ev["payload"],
                }
                yield _format_sse(ev["event_type"], frame_data, event_id=ev["id"])
                # Update heartbeat timestamp whenever we send data.
                last_heartbeat = now

                # Terminal event → stop after yielding.
                if ev["event_type"] in _TERMINAL_STATUSES:
                    return

            # If the run reached terminal status via a different code path
            # (e.g. stale detection, direct DB update), emit a synthetic
            # event and stop.
            if run_status in _TERMINAL_STATUSES:
                yield _format_sse(
                    run_status,
                    {"timestamp": utc_now(), "source": "status_poll"},
                )
                return

            # Send heartbeat if enough time has elapsed.
            if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
                # SSE comment lines start with ':' — lightweight keep-alive.
                yield ": heartbeat\n\n"
                last_heartbeat = now

            await asyncio.sleep(_POLL_INTERVAL)
    finally:
        if own_engine:
            engine.dispose()
