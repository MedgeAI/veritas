"""Integration tests for SSE streaming.

Exercises the real ``SSEEventBuffer`` -> ``_matches_level`` -> ``_format_sse``
path used by the ``GET /api/audit/{job_id}/stream`` endpoint.

Only the database boundary is avoided: the in-process buffer and the SSE
formatting pipeline are the real code paths that the endpoint uses.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from web.backend.veritas_web.sse import (
    _format_buffered_sse,
    _format_sse,
    _matches_level,
)
from web.backend.veritas_web.sse_buffer import SSEEventBuffer


# ---------------------------------------------------------------------------
# Buffer -> level filtering -> SSE formatting pipeline
# ---------------------------------------------------------------------------


class TestBufferToSSEPipeline:
    """End-to-end: producer pushes events; consumer filters and formats."""

    def test_lifecycle_filter_hides_agent_and_log_events(self):
        """Produce a mix of events; lifecycle filter drops agent/log."""
        buf = SSEEventBuffer()
        buf.push("run-1", "step.start", {"key": "mineru"})
        buf.push("run-1", "step.complete", {"key": "mineru"})
        buf.push("run-1", "agent.thinking", {"content": "hmm"})
        buf.push("run-1", "agent.tool_call", {"tool": "grep"})
        buf.push("run-1", "log", {"line": "debug info"})
        buf.push("run-1", "completed", {"source": "status_poll"})

        all_events = buf.get_since("run-1", "0")
        assert len(all_events) == 6

        # Filter at lifecycle level
        lifecycle_frames: list[str] = []
        for ev in all_events:
            if not _matches_level(ev["type"], "lifecycle"):
                continue
            lifecycle_frames.append(_format_buffered_sse(ev))

        # step.start, step.complete, completed = 3 events
        assert len(lifecycle_frames) == 3
        for frame in lifecycle_frames:
            assert frame.startswith("id: ")
            assert "event: " in frame
            assert "data: " in frame
            # Every frame ends with the double-CRLF
            assert frame.endswith("\n\n")
            # Payload is JSON-serialisable
            data_line = [ln for ln in frame.splitlines() if ln.startswith("data: ")][0]
            json.loads(data_line[len("data: "):])

    def test_agent_level_includes_agent_events(self):
        """Agent level includes step + agent events but not log."""
        buf = SSEEventBuffer()
        buf.push("run-1", "step.start", {"key": "discover"})
        buf.push("run-1", "agent.thinking", {"content": "hmm"})
        buf.push("run-1", "log", {"line": "debug info"})

        agent_frames = [
            _format_buffered_sse(ev)
            for ev in buf.get_since("run-1", "0")
            if _matches_level(ev["type"], "agent")
        ]
        # step.start + agent.thinking = 2; log is excluded
        assert len(agent_frames) == 2
        event_types = []
        for frame in agent_frames:
            for line in frame.splitlines():
                if line.startswith("event: "):
                    event_types.append(line[len("event: "):])
        assert "step.start" in event_types
        assert "agent.thinking" in event_types

    def test_debug_level_includes_everything(self):
        """Debug level includes all event types."""
        buf = SSEEventBuffer()
        buf.push("run-1", "step.start", {})
        buf.push("run-1", "agent.thinking", {})
        buf.push("run-1", "log", {"line": "x"})

        debug_frames = [
            _format_buffered_sse(ev)
            for ev in buf.get_since("run-1", "0")
            if _matches_level(ev["type"], "debug")
        ]
        assert len(debug_frames) == 3


# ---------------------------------------------------------------------------
# Reconnection via Last-Event-ID
# ---------------------------------------------------------------------------


class TestReconnection:
    """SSE clients reconnect with Last-Event-ID; buffer replays missed events."""

    def test_replay_after_disconnect(self):
        """Simulate: client reads 2 events, disconnects, more events pushed,
        client reconnects with Last-Event-ID=2."""
        buf = SSEEventBuffer()
        # Initial burst — client reads 2 events.
        buf.push("run-1", "step.start", {"key": "discover"})
        buf.push("run-1", "step.complete", {"key": "discover"})
        initial = buf.get_since("run-1", "0")
        assert len(initial) == 2
        last_seen_id = initial[-1]["id"]  # "2"

        # Disconnect, more events happen.
        buf.push("run-1", "step.start", {"key": "mineru"})
        buf.push("run-1", "step.complete", {"key": "mineru"})
        buf.push("run-1", "completed", {})

        # Reconnection: ask for events after last_seen_id.
        replay = buf.get_since("run-1", last_seen_id)
        assert len(replay) == 3
        assert replay[0]["type"] == "step.start"
        assert replay[1]["type"] == "step.complete"
        assert replay[2]["type"] == "completed"

    def test_evicted_events_cause_clean_replay(self):
        """When events have been evicted, reconnection gets the remaining
        buffered events without errors."""
        buf = SSEEventBuffer(max_size=3)
        buf.push("run-1", "a", {})
        buf.push("run-1", "b", {})
        buf.push("run-1", "c", {})
        buf.push("run-1", "d", {})  # evicts "a"

        # Client reconnects with Last-Event-ID=1 (pointing to evicted "a").
        result = buf.get_since("run-1", "1")
        # Returns events with id > 1 that are still buffered: b, c, d
        assert len(result) == 3
        assert [e["type"] for e in result] == ["b", "c", "d"]


# ---------------------------------------------------------------------------
# Run isolation
# ---------------------------------------------------------------------------


class TestRunIsolation:
    """Events from different runs must not leak."""

    def test_concurrent_runs_filtered(self):
        """Events pushed for run-A do not appear when reading run-B."""
        buf = SSEEventBuffer()
        buf.push("run-a", "step.start", {"key": "a"})
        buf.push("run-b", "step.start", {"key": "b"})
        buf.push("run-a", "step.complete", {"key": "a"})

        a_events = buf.get_since("run-a", "0")
        b_events = buf.get_since("run-b", "0")

        assert len(a_events) == 2
        assert all(e["run_id"] == "run-a" for e in a_events)
        assert len(b_events) == 1
        assert b_events[0]["run_id"] == "run-b"


# ---------------------------------------------------------------------------
# SSE frame format compliance
# ---------------------------------------------------------------------------


class TestSSEFrameFormat:
    """Verify the SSE frames emitted match the spec."""

    def test_format_sse_basic_structure(self):
        """Basic _format_sse produces 'event: ...' + 'data: ...' + double LF."""
        frame = _format_sse("step.start", {"key": "discover"})
        assert frame.startswith("event: step.start\n")
        assert "data: " in frame
        data_line = [ln for ln in frame.splitlines() if ln.startswith("data: ")][0]
        data = json.loads(data_line[len("data: "):])
        assert data == {"key": "discover"}
        assert frame.endswith("\n\n")

    def test_format_sse_with_id(self):
        """id line appears before event line."""
        frame = _format_sse("progress", {"pct": 50}, event_id=42)
        lines = frame.splitlines()
        assert lines[0] == "id: 42"
        assert lines[1] == "event: progress"

    def test_format_buffered_sse_merges_timestamp_into_data(self):
        """Buffered events without timestamp in data get it merged in."""
        event = {
            "id": "7",
            "type": "step.start",
            "timestamp": "2026-06-26T10:00:00Z",
            "data": {"key": "discover"},
        }
        frame = _format_buffered_sse(event)
        data_line = [ln for ln in frame.splitlines() if ln.startswith("data: ")][0]
        data = json.loads(data_line[len("data: "):])
        assert data["timestamp"] == "2026-06-26T10:00:00Z"
        assert data["key"] == "discover"

    def test_format_buffered_sse_does_not_overwrite_existing_timestamp(self):
        """If data already has 'timestamp', it is preserved (not overwritten)."""
        event = {
            "id": "7",
            "type": "step.start",
            "timestamp": "2026-06-26T10:00:00Z",
            "data": {"key": "discover", "timestamp": "2026-06-26T09:59:00Z"},
        }
        frame = _format_buffered_sse(event)
        data_line = [ln for ln in frame.splitlines() if ln.startswith("data: ")][0]
        data = json.loads(data_line[len("data: "):])
        assert data["timestamp"] == "2026-06-26T09:59:00Z"


# ---------------------------------------------------------------------------
# Terminal status handling
# ---------------------------------------------------------------------------


class TestTerminalStatus:
    """Terminal events (completed, failed, cancelled) end the stream."""

    def test_terminal_event_produces_frame(self):
        """A terminal event pushed to the buffer produces a parseable frame."""
        buf = SSEEventBuffer()
        buf.push("run-1", "completed", {"source": "status_poll"})

        events = buf.get_since("run-1", "0")
        assert len(events) == 1
        frame = _format_buffered_sse(events[0])
        assert "event: completed" in frame

    def test_multiple_runs_terminal_independent(self):
        """Terminal event in run-A does not affect run-B's stream."""
        buf = SSEEventBuffer()
        buf.push("run-a", "completed", {})
        buf.push("run-b", "step.start", {"key": "a"})

        a_events = buf.get_since("run-a", "0")
        b_events = buf.get_since("run-b", "0")
        assert len(a_events) == 1
        assert a_events[0]["type"] == "completed"
        assert len(b_events) == 1
        assert b_events[0]["type"] == "step.start"


# ---------------------------------------------------------------------------
# Waiter notification (asyncio bridge)
# ---------------------------------------------------------------------------


class TestWaiterNotification:
    """Sync producer wakes async consumer via asyncio.Event."""

    def test_push_then_notify_wakes_waiter(self):
        """Pushing an event + notify_waiters sets the asyncio.Event."""
        buf = SSEEventBuffer()
        waiter = buf.pop_wait_event("run-1")
        assert not waiter.is_set()

        buf.push("run-1", "step.start", {"key": "mineru"})
        buf.notify_waiters("run-1")

        assert waiter.is_set()

    def test_notify_without_matching_run_does_nothing(self):
        """notify_waiters for an unrelated run_id leaves the waiter unset."""
        buf = SSEEventBuffer()
        waiter = buf.pop_wait_event("run-1")
        buf.notify_waiters("run-2")
        assert not waiter.is_set()
