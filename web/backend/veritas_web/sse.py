"""Server-Sent Events backend for real-time audit progress streaming.

Two entry points:

* :func:`notify_progress` — **sync**, called from Celery workers.
  Persists an event row and fires ``pg_notify('audit_progress', …)``.

* :func:`sse_event_stream` — **async** generator consumed by FastAPI
  ``StreamingResponse``.  Polls ``run_events`` every 2 s, yields SSE-formatted
  frames, and stops when the run reaches a terminal status.

Event filtering
---------------
The stream supports three verbosity levels via the ``events`` parameter:

* ``lifecycle`` (default): pipeline/step/progress events + legacy status events
* ``agent``: lifecycle + agent reasoning events (agent.thinking, agent.tool_call)
* ``debug``: all events including log streams

Legacy event types (stage_changed, progress, completed, failed, cancelled) are
always included at the lifecycle level for backward compatibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Literal

from sqlalchemy import text

from .database import create_db_engine, create_session_factory, get_database_url
from .models import utc_now
from .sse_buffer import SSEEventBuffer, get_event_buffer

logger = logging.getLogger(__name__)

# Terminal run statuses that end the SSE stream.
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

# Poll interval for the SSE fallback (seconds).
_POLL_INTERVAL = 2

# Heartbeat interval (seconds) — keep-alive so proxies do not close the connection.
_HEARTBEAT_INTERVAL = 15

# Event verbosity levels.
EventLevel = Literal["lifecycle", "agent", "debug"]

# Event type prefixes for filtering.
_LIFECYCLE_PREFIXES = ("pipeline.", "step.", "progress.")
_AGENT_PREFIXES = ("agent.",)
_DEBUG_PREFIXES = ("log",)

# Legacy event types always included at lifecycle level.
_LEGACY_LIFECYCLE_TYPES = frozenset(
    {"stage_changed", "progress", "completed", "failed", "cancelled"}
)


# ---------------------------------------------------------------------------
# Sync: called from Celery worker process
# ---------------------------------------------------------------------------


def notify_progress(
    run_id: str,
    event_type: str,
    data: dict[str, Any] | None = None,
    *,
    database_url: str | None = None,
    engine: Any | None = None,
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
    engine:
        SQLAlchemy engine to reuse.  If ``None``, a new engine is created
        and disposed when the function completes.
    """
    data = data or {}
    own_engine = engine is None
    eng = engine if engine is not None else create_db_engine(database_url or get_database_url())
    session_factory = create_session_factory(eng)
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
        # Push to in-process buffer for fast same-process notification.
        # This wakes up SSE consumers immediately without waiting for
        # the next DB poll cycle.  Cross-process consumers still rely
        # on pg_notify (not implemented in this module).
        try:
            buffer = get_event_buffer()
            buffer.push(run_id, event_type, data)
            buffer.notify_waiters(run_id)
        except Exception:
            logger.debug("buffer push/notify failed for run %s", run_id, exc_info=True)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        if own_engine:
            eng.dispose()


# ---------------------------------------------------------------------------
# Event filtering
# ---------------------------------------------------------------------------


def _matches_level(event_type: str, level: EventLevel) -> bool:
    """Return True if *event_type* should be emitted at the given *level*."""
    # Legacy lifecycle types always pass at lifecycle level.
    if event_type in _LEGACY_LIFECYCLE_TYPES:
        return True

    # Check prefixes for new event types.
    if event_type.startswith(_LIFECYCLE_PREFIXES):
        return True
    if level in ("agent", "debug") and event_type.startswith(_AGENT_PREFIXES):
        return True
    if level == "debug" and event_type.startswith(_DEBUG_PREFIXES):
        return True
    return False


# ---------------------------------------------------------------------------
# SSE frame formatting
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


def _format_buffered_sse(event: dict[str, Any]) -> str:
    """Format a buffered event dict as an SSE frame."""
    event_id = event.get("id")
    event_type = event.get("type", "progress")
    data = event.get("data", {})
    # Add timestamp to data if not present.
    if "timestamp" not in data:
        data = {"timestamp": event.get("timestamp"), **data}
    return _format_sse(event_type, data, event_id=event_id)


# ---------------------------------------------------------------------------
# Async: consumed by FastAPI StreamingResponse
# ---------------------------------------------------------------------------


async def sse_event_stream(
    run_id: str,
    db_engine: Any = None,
    *,
    level: EventLevel = "lifecycle",
    last_event_id: str | None = None,
    buffer: SSEEventBuffer | None = None,
) -> AsyncIterator[str]:
    """Async generator that yields SSE frames for *run_id*.

    Polls ``run_events`` every :data:`_POLL_INTERVAL` seconds for new rows
    with ``id > last_id``.  Falls back to polling because async PG LISTEN
    requires ``asyncpg`` which is not in the dependency tree.

    When *buffer* is provided and the notification happens in the same
    process, events are delivered immediately via :class:`asyncio.Event`
    without waiting for the next DB poll cycle.

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
    level:
        Event verbosity: ``lifecycle`` (default), ``agent``, or ``debug``.
    last_event_id:
        Resume streaming from this event id (for reconnection).  Events
        with id ≤ *last_event_id* are skipped.
    buffer:
        In-process event buffer for fast notification.  If ``None``, the
        global buffer is used.
    """
    own_engine = db_engine is None
    engine = db_engine or create_db_engine()
    session_factory = create_session_factory(engine)
    last_id: int = int(last_event_id) if last_event_id else 0
    last_heartbeat: float = 0.0
    loop = asyncio.get_running_loop()
    event_buffer = buffer or get_event_buffer()

    try:
        # Fast path: replay buffered events that the client missed.
        buffered_events = event_buffer.get_since(run_id, str(last_id))
        for ev in buffered_events:
            if _matches_level(ev.get("type", "progress"), level):
                last_id = int(ev["id"])
                yield _format_buffered_sse(ev)
                if ev.get("type") in _TERMINAL_STATUSES:
                    return

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
                event_type = ev["event_type"]
                # Filter events by level.
                if not _matches_level(event_type, level):
                    continue
                frame_data: dict[str, Any] = {
                    "timestamp": ev["timestamp"],
                    **ev["payload"],
                }
                yield _format_sse(event_type, frame_data, event_id=ev["id"])
                # Update heartbeat timestamp whenever we send data.
                last_heartbeat = now

                # Terminal event → stop after yielding.
                if event_type in _TERMINAL_STATUSES:
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

            # Wait for either a buffer notification or a timeout.
            wait_event = event_buffer.pop_wait_event(run_id)
            try:
                await asyncio.wait_for(
                    wait_event.wait(), timeout=_POLL_INTERVAL
                )
            except asyncio.TimeoutError:
                pass  # Poll the DB on timeout.
    finally:
        if own_engine:
            engine.dispose()
