"""In-process SSE event buffer for reconnection and fast notification.

Stores the most recent events per run (default 1000) so that:

1. Clients reconnecting after a network interruption can replay missed
   events via the ``Last-Event-ID`` header.
2. SSE consumers in the same process as ``notify_progress`` can be
   woken up immediately via :class:`asyncio.Event`, avoiding the
   multi-second DB-poll latency.

Design contract
---------------
* Each buffered entry carries ``run_id``, ``id`` (monotonic sequence),
  ``type``, ``timestamp``, ``data``, and ``db_id``.
* ``get_since`` filters by ``run_id`` and returns entries with
  sequence strictly greater than the supplied id.
* When the buffer is full, the oldest events are silently evicted
  (``deque(maxlen=…)``).  A client whose ``Last-Event-ID`` points to
  an evicted event receives only the remaining events; anything older
  falls back to DB polling.
* Thread-safe: ``notify_progress`` is sync (called from Celery workers
  or sync runner threads), SSE consumers are async.  All shared state
  is guarded by locks.
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from typing import Any

from .models import utc_now


class SSEEventBuffer:
    """Bounded FIFO buffer of SSE events with monotonic ids and waiter notification.

    Parameters
    ----------
    max_size:
        Maximum number of events retained across all runs.  Oldest
        events are evicted when the limit is exceeded.  Must be ≥ 1.
    """

    def __init__(self, max_size: int = 1000) -> None:
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._max_size = max_size
        self._lock = threading.Lock()
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_size)
        self._counter: int = 0
        # Waiter notification (separate lock to minimise hold time)
        self._waiter_lock = threading.Lock()
        self._waiters: dict[str, asyncio.Event] = {}

    @property
    def last_id(self) -> int:
        """The most recently assigned sequence number."""
        return self._counter

    # ------------------------------------------------------------------
    # Producer API
    # ------------------------------------------------------------------

    def push(
        self,
        run_id: str,
        event_type: str,
        data: dict[str, Any],
        *,
        db_id: int | None = None,
    ) -> dict[str, Any]:
        """Append an event and return it.

        The returned dict has keys ``id`` (string sequence), ``type``,
        ``timestamp`` (ISO-8601 UTC), ``data``, ``run_id``, and ``db_id``.
        """
        with self._lock:
            self._counter += 1
            event: dict[str, Any] = {
                "id": str(self._counter),
                "type": event_type,
                "timestamp": utc_now(),
                "data": data,
                "run_id": run_id,
                "db_id": db_id,
            }
            self._buffer.append(event)
        return event

    # ------------------------------------------------------------------
    # Consumer API
    # ------------------------------------------------------------------

    def get_since(self, run_id: str, event_id: str) -> list[dict[str, Any]]:
        """Return buffered events for *run_id* with id > *event_id*."""
        try:
            id_int = int(event_id)
        except (ValueError, TypeError):
            return []
        with self._lock:
            return [
                e
                for e in self._buffer
                if e.get("run_id") == run_id and int(e["id"]) > id_int
            ]

    def get_all(self, run_id: str) -> list[dict[str, Any]]:
        """Return all currently buffered events for *run_id*."""
        with self._lock:
            return [e for e in self._buffer if e.get("run_id") == run_id]

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)

    # ------------------------------------------------------------------
    # Waiter notification (asyncio.Event, thread-safe)
    # ------------------------------------------------------------------

    def pop_wait_event(self, run_id: str) -> asyncio.Event:
        """Return a *fresh* :class:`asyncio.Event` to await.

        The event is set by :meth:`notify_waiters` on the next push.
        Callers should request a new event after each wake-up.
        """
        with self._waiter_lock:
            event = asyncio.Event()
            self._waiters[run_id] = event
            return event

    def notify_waiters(self, run_id: str) -> None:
        """Set the current waiter event for *run_id* (if any).

        Safe to call from a sync thread (uses no await); the waiting
        async task will be woken on the next event-loop iteration.
        """
        with self._waiter_lock:
            event = self._waiters.pop(run_id, None)
        if event is not None:
            event.set()

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def clear(self, run_id: str | None = None) -> None:
        """Clear buffered events for *run_id*, or all runs if ``None``."""
        with self._lock:
            if run_id is None:
                self._buffer.clear()
                self._counter = 0
            else:
                # deque doesn't support filtered removal — rebuild
                self._buffer = deque(
                    (e for e in self._buffer if e.get("run_id") != run_id),
                    maxlen=self._max_size,
                )
        with self._waiter_lock:
            self._waiters.pop(run_id, None)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_global_buffer = SSEEventBuffer()


def get_event_buffer() -> SSEEventBuffer:
    """Return the process-wide :class:`SSEEventBuffer` singleton."""
    return _global_buffer
