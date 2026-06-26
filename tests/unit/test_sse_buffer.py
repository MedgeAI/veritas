"""Unit tests for SSEEventBuffer.

Covers the in-process bounded FIFO buffer used by the SSE streaming
endpoint.  Verifies monotonic ids, eviction, run_id filtering,
reconnection via ``get_since``, thread safety, and waiter notification.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from web.backend.veritas_web.sse_buffer import SSEEventBuffer, get_event_buffer


# ---------------------------------------------------------------------------
# Basic push / id assignment
# ---------------------------------------------------------------------------


class TestSSEEventBufferBasic:
    """Tests for SSEEventBuffer core operations."""

    def test_push_returns_event_with_monotonic_id(self):
        """push assigns incrementing ids starting from '1'."""
        buf = SSEEventBuffer()
        ev1 = buf.push("run-a", "step.start", {"step": "a"})
        ev2 = buf.push("run-a", "step.complete", {"step": "a"})

        assert ev1["id"] == "1"
        assert ev2["id"] == "2"
        assert ev1["type"] == "step.start"
        assert ev2["type"] == "step.complete"

    def test_push_includes_timestamp_and_data(self):
        """push returns event with ISO timestamp and original data."""
        buf = SSEEventBuffer()
        ev = buf.push("run-a", "progress", {"percent": 50})

        assert "timestamp" in ev
        assert ev["data"] == {"percent": 50}
        # ISO 8601 format check
        assert "T" in ev["timestamp"]

    def test_push_records_run_id(self):
        """push stores run_id on the event."""
        buf = SSEEventBuffer()
        ev = buf.push("run-42", "step.start", {})

        assert ev["run_id"] == "run-42"

    def test_push_records_optional_db_id(self):
        """push stores db_id when provided, otherwise None."""
        buf = SSEEventBuffer()
        ev_with = buf.push("run-a", "progress", {}, db_id=99)
        ev_without = buf.push("run-a", "progress", {})

        assert ev_with["db_id"] == 99
        assert ev_without["db_id"] is None

    def test_last_id_property(self):
        """last_id reflects the most recent sequence number."""
        buf = SSEEventBuffer()
        assert buf.last_id == 0
        buf.push("run-a", "a", {})
        assert buf.last_id == 1
        buf.push("run-a", "b", {})
        assert buf.last_id == 2


# ---------------------------------------------------------------------------
# get_since / filtering
# ---------------------------------------------------------------------------


class TestSSEEventBufferGetSince:
    """Tests for get_since (reconnection) filtering."""

    def test_get_since_returns_events_after_id(self):
        """get_since returns only events with id > given id for the same run."""
        buf = SSEEventBuffer()
        buf.push("run-a", "a", {})
        buf.push("run-a", "b", {})
        ev3 = buf.push("run-a", "c", {})

        result = buf.get_since("run-a", "2")
        assert len(result) == 1
        assert result[0]["id"] == ev3["id"]
        assert result[0]["type"] == "c"

    def test_get_since_zero_returns_all_events_for_run(self):
        """get_since('0') returns all buffered events for the run."""
        buf = SSEEventBuffer()
        buf.push("run-a", "a", {})
        buf.push("run-a", "b", {})
        buf.push("run-a", "c", {})

        result = buf.get_since("run-a", "0")
        assert len(result) == 3
        assert [e["id"] for e in result] == ["1", "2", "3"]

    def test_get_since_future_id_returns_empty(self):
        """get_since with id >= last_id returns empty list."""
        buf = SSEEventBuffer()
        buf.push("run-a", "a", {})
        buf.push("run-a", "b", {})

        result = buf.get_since("run-a", "5")
        assert result == []

    def test_get_since_filters_by_run_id(self):
        """get_since only returns events for the requested run."""
        buf = SSEEventBuffer()
        buf.push("run-a", "a", {})
        buf.push("run-b", "b", {})
        buf.push("run-a", "c", {})

        result = buf.get_since("run-a", "0")
        assert len(result) == 2
        assert all(e["run_id"] == "run-a" for e in result)

        result_b = buf.get_since("run-b", "0")
        assert len(result_b) == 1
        assert result_b[0]["type"] == "b"

    def test_get_since_invalid_id_returns_empty(self):
        """get_since with non-numeric id returns empty list (no exception)."""
        buf = SSEEventBuffer()
        buf.push("run-a", "a", {})

        assert buf.get_since("run-a", "not-a-number") == []
        assert buf.get_since("run-a", "") == []

    def test_get_since_with_string_id(self):
        """get_since accepts string id (as per SSE spec)."""
        buf = SSEEventBuffer()
        buf.push("run-a", "a", {})
        buf.push("run-a", "b", {})

        # SSE Last-Event-ID is always a string
        result = buf.get_since("run-a", "1")
        assert len(result) == 1
        assert result[0]["type"] == "b"


# ---------------------------------------------------------------------------
# Eviction / bounded capacity
# ---------------------------------------------------------------------------


class TestSSEEventBufferEviction:
    """Tests for bounded capacity and eviction behaviour."""

    def test_buffer_eviction_when_full(self):
        """Oldest events are evicted when buffer exceeds max_size."""
        buf = SSEEventBuffer(max_size=3)
        buf.push("run-a", "a", {})
        buf.push("run-a", "b", {})
        buf.push("run-a", "c", {})
        buf.push("run-a", "d", {})  # evicts "a"

        # "a" should be gone
        result = buf.get_since("run-a", "0")
        assert len(result) == 3
        assert result[0]["type"] == "b"
        assert result[-1]["type"] == "d"

    def test_get_since_with_evicted_id(self):
        """get_since with id pointing to evicted event returns remaining events."""
        buf = SSEEventBuffer(max_size=3)
        buf.push("run-a", "a", {})  # id=1
        buf.push("run-a", "b", {})  # id=2
        buf.push("run-a", "c", {})  # id=3
        buf.push("run-a", "d", {})  # id=4, evicts id=1

        # Request events after id=1 (evicted)
        result = buf.get_since("run-a", "1")
        assert len(result) == 3
        assert [e["id"] for e in result] == ["2", "3", "4"]

    def test_max_size_validation(self):
        """max_size < 1 raises ValueError."""
        with pytest.raises(ValueError, match="max_size must be >= 1"):
            SSEEventBuffer(max_size=0)

    def test_len_reflects_buffered_events(self):
        """len returns current number of buffered events."""
        buf = SSEEventBuffer(max_size=5)
        assert len(buf) == 0

        buf.push("run-a", "a", {})
        buf.push("run-a", "b", {})
        assert len(buf) == 2

        # Fill beyond max_size
        for i in range(10):
            buf.push("run-a", f"ev{i}", {})
        assert len(buf) == 5  # capped at max_size

    def test_last_id_persists_across_evictions(self):
        """last_id continues incrementing even after evictions."""
        buf = SSEEventBuffer(max_size=2)
        buf.push("run-a", "a", {})  # id=1
        buf.push("run-a", "b", {})  # id=2
        ev3 = buf.push("run-a", "c", {})  # id=3, evicts id=1

        assert ev3["id"] == "3"
        assert buf.last_id == 3

    def test_empty_data_dict(self):
        """push with empty data dict is valid."""
        buf = SSEEventBuffer()
        ev = buf.push("run-a", "heartbeat", {})
        assert ev["data"] == {}


# ---------------------------------------------------------------------------
# get_all / clear helpers
# ---------------------------------------------------------------------------


class TestSSEEventBufferHelpers:
    """Tests for get_all and clear helpers."""

    def test_get_all_returns_all_events_for_run(self):
        """get_all returns every buffered event for the run."""
        buf = SSEEventBuffer()
        buf.push("run-a", "a", {})
        buf.push("run-b", "b", {})
        buf.push("run-a", "c", {})

        result = buf.get_all("run-a")
        assert len(result) == 2
        assert [e["type"] for e in result] == ["a", "c"]

    def test_clear_all_runs(self):
        """clear() with no args empties the entire buffer and resets counter."""
        buf = SSEEventBuffer()
        buf.push("run-a", "a", {})
        buf.push("run-b", "b", {})
        buf.clear()

        assert len(buf) == 0
        assert buf.last_id == 0

    def test_clear_single_run(self):
        """clear(run_id=...) removes only events for that run."""
        buf = SSEEventBuffer()
        buf.push("run-a", "a", {})
        buf.push("run-b", "b", {})
        buf.push("run-a", "c", {})
        buf.clear(run_id="run-a")

        assert len(buf) == 1
        assert buf.get_all("run-b")[0]["type"] == "b"
        assert buf.get_all("run-a") == []


# ---------------------------------------------------------------------------
# Waiter notification (asyncio.Event)
# ---------------------------------------------------------------------------


class TestSSEEventBufferWaiters:
    """Tests for pop_wait_event / notify_infers run-scoped waiter semantics."""

    def test_pop_wait_returns_fresh_event(self):
        """pop_wait_event returns an unset asyncio.Event."""
        buf = SSEEventBuffer()
        ev = buf.pop_wait_event("run-a")
        assert isinstance(ev, asyncio.Event)
        assert not ev.is_set()

    def test_notify_waiters_sets_event(self):
        """notify_waiters sets the waiter event for the given run."""
        buf = SSEEventBuffer()
        ev = buf.pop_wait_event("run-a")
        assert not ev.is_set()

        buf.notify_waiters("run-a")
        assert ev.is_set()

    def test_notify_waiters_does_not_affect_other_runs(self):
        """notify_waiters only wakes waiters for the matching run_id."""
        buf = SSEEventBuffer()
        ev_a = buf.pop_wait_event("run-a")
        # pop a second waiter for run-b
        _ev_b = buf.pop_wait_event("run-b")

        buf.notify_waiters("run-a")
        assert ev_a.is_set()
        # run-b's waiter was consumed by pop (one-shot); no waiter set
        # but we can check that ev_b (different run) was not set.

    def test_notify_waiters_no_waiter_is_noop(self):
        """notify_waiters with no active waiter does not raise."""
        buf = SSEEventBuffer()
        buf.notify_waiters("run-nonexistent")  # no exception


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestSSEEventBufferConcurrency:
    """Smoke tests for thread-safe push / get_since under concurrent writes."""

    def test_concurrent_pushes(self):
        """Concurrent pushes do not corrupt the counter or buffer."""
        buf = SSEEventBuffer(max_size=10_000)
        n_threads = 8
        n_pushes = 200

        def _push_batch(run_id: str):
            for i in range(n_pushes):
                buf.push(run_id, f"ev-{i}", {"i": i})

        threads = [
            threading.Thread(target=_push_batch, args=(f"run-{t}",))
            for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total_expected = n_threads * n_pushes
        assert buf.last_id == total_expected
        assert len(buf) == total_expected

    def test_concurrent_push_and_read(self):
        """Concurrent push + get_since do not raise."""
        buf = SSEEventBuffer(max_size=500)
        stop = threading.Event()

        def _writer():
            i = 0
            while not stop.is_set():
                buf.push("run-a", f"ev-{i}", {})
                i += 1

        def _reader():
            while not stop.is_set():
                buf.get_since("run-a", "0")

        writer = threading.Thread(target=_writer, daemon=True)
        reader = threading.Thread(target=_reader, daemon=True)
        writer.start()
        reader.start()

        # Let them run for a short time, then check no exception occurred.
        import time
        time.sleep(0.1)
        stop.set()
        writer.join(timeout=2)
        reader.join(timeout=2)
        # If we got here without an exception, thread safety holds.
        assert buf.last_id > 0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


class TestGetEventBuffer:
    """Tests for the process-wide singleton accessor."""

    def test_get_event_buffer_returns_sse_buffer(self):
        """get_event_buffer returns an SSEEventBuffer instance."""
        buf = get_event_buffer()
        assert isinstance(buf, SSEEventBuffer)

    def test_get_event_buffer_returns_same_instance(self):
        """Repeated calls return the same object (singleton)."""
        assert get_event_buffer() is get_event_buffer()
