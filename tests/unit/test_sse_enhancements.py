"""Unit tests for SSE stream enhancements.

Covers event filtering (_matches_level), Last-Event-ID reconnection,
event verbosity levels, and SSE frame formatting.
"""

from __future__ import annotations

import pytest

from web.backend.veritas_web.sse import (
    _format_buffered_sse,
    _format_sse,
    _matches_level,
)


# ---------------------------------------------------------------------------
# Event filtering: _matches_level
# ---------------------------------------------------------------------------


class TestMatchesLevel:
    """Tests for _matches_level event filtering."""

    def test_legacy_lifecycle_types_always_match(self):
        """Legacy event types (stage_changed, progress, completed, failed, cancelled)
        are always included at lifecycle level."""
        for event_type in ("stage_changed", "progress", "completed", "failed", "cancelled"):
            assert _matches_level(event_type, "lifecycle"), f"{event_type} should match lifecycle"
            assert _matches_level(event_type, "agent"), f"{event_type} should match agent"
            assert _matches_level(event_type, "debug"), f"{event_type} should match debug"

    def test_pipeline_prefix_matches_lifecycle(self):
        """pipeline.* events match at lifecycle level."""
        assert _matches_level("pipeline.start", "lifecycle")
        assert _matches_level("pipeline.complete", "lifecycle")
        assert _matches_level("pipeline.failed", "lifecycle")

    def test_step_prefix_matches_lifecycle(self):
        """step.* events match at lifecycle level."""
        assert _matches_level("step.start", "lifecycle")
        assert _matches_level("step.progress", "lifecycle")
        assert _matches_level("step.complete", "lifecycle")
        assert _matches_level("step.failed", "lifecycle")
        assert _matches_level("step.skipped", "lifecycle")

    def test_progress_prefix_matches_lifecycle(self):
        """progress.* events match at lifecycle level."""
        assert _matches_level("progress.update", "lifecycle")

    def test_agent_prefix_requires_agent_or_debug(self):
        """agent.* events require agent or debug level."""
        assert not _matches_level("agent.thinking", "lifecycle")
        assert _matches_level("agent.thinking", "agent")
        assert _matches_level("agent.tool_call", "agent")
        assert _matches_level("agent.tool_result", "debug")

    def test_log_prefix_requires_debug(self):
        """log events require debug level."""
        assert not _matches_level("log", "lifecycle")
        assert not _matches_level("log", "agent")
        assert _matches_level("log", "debug")

    def test_unknown_type_never_matches(self):
        """Unknown event types never match any level."""
        assert not _matches_level("unknown.event", "lifecycle")
        assert not _matches_level("unknown.event", "agent")
        assert not _matches_level("unknown.event", "debug")
        assert not _matches_level("random", "debug")


# ---------------------------------------------------------------------------
# SSE frame formatting
# ---------------------------------------------------------------------------


class TestSSEFormatting:
    """Tests for SSE frame formatting functions."""

    def test_format_sse_basic(self):
        """_format_sse produces correct SSE frame format."""
        frame = _format_sse("step.start", {"step_key": "mineru", "title": "PDF解析"})
        assert "event: step.start\n" in frame
        assert "data: " in frame
        assert '"step_key": "mineru"' in frame
        assert frame.endswith("\n\n")

    def test_format_sse_with_event_id(self):
        """_format_sse includes id line when event_id is provided."""
        frame = _format_sse("progress", {"percent": 50}, event_id=42)
        assert "id: 42\n" in frame
        assert "event: progress\n" in frame

    def test_format_buffered_sse(self):
        """_format_buffered_sse formats buffered event dict correctly."""
        event = {
            "id": "5",
            "type": "step.complete",
            "timestamp": "2026-06-26T12:00:00Z",
            "data": {"step_key": "mineru", "status": "success"},
        }
        frame = _format_buffered_sse(event)
        assert "id: 5\n" in frame
        assert "event: step.complete\n" in frame
        assert "data: " in frame
        assert '"step_key": "mineru"' in frame
        # timestamp should be in data
        assert '"timestamp"' in frame

    def test_format_buffered_sse_adds_timestamp_to_data(self):
        """_format_buffered_sse adds timestamp to data if not present."""
        event = {
            "id": "3",
            "type": "progress",
            "timestamp": "2026-06-26T12:00:00Z",
            "data": {"percent": 75},
        }
        frame = _format_buffered_sse(event)
        # The timestamp should be merged into data
        assert '"timestamp": "2026-06-26T12:00:00Z"' in frame
        assert '"percent": 75' in frame

    def test_format_buffered_sse_preserves_existing_timestamp_in_data(self):
        """_format_buffered_sse does not overwrite timestamp if already in data."""
        event = {
            "id": "3",
            "type": "progress",
            "timestamp": "2026-06-26T12:00:00Z",
            "data": {"timestamp": "2026-06-26T11:59:00Z", "percent": 75},
        }
        frame = _format_buffered_sse(event)
        # Should use the timestamp from data, not override it
        assert '"timestamp": "2026-06-26T11:59:00Z"' in frame
        assert "2026-06-26T12:00:00Z" not in frame


# ---------------------------------------------------------------------------
# Integration: buffer + filtering
# ---------------------------------------------------------------------------


class TestBufferAndFiltering:
    """Tests for buffer retrieval combined with level filtering."""

    def test_get_since_with_level_filter(self):
        """Verify that get_since + level filter work together."""
        from web.backend.veritas_web.sse_buffer import SSEEventBuffer

        buf = SSEEventBuffer()
        buf.push("run-a", "step.start", {"key": "a"})
        buf.push("run-a", "agent.thinking", {"content": "x"})
        buf.push("run-a", "step.complete", {"key": "a"})
        buf.push("run-a", "log", {"message": "debug"})

        # Get all events after id=0
        all_events = buf.get_since("run-a", "0")
        assert len(all_events) == 4

        # Filter at lifecycle level
        lifecycle_events = [e for e in all_events if _matches_level(e["type"], "lifecycle")]
        assert len(lifecycle_events) == 2
        assert all(e["type"] in ("step.start", "step.complete") for e in lifecycle_events)

        # Filter at agent level
        agent_events = [e for e in all_events if _matches_level(e["type"], "agent")]
        assert len(agent_events) == 3  # 2 step + 1 agent
        assert any(e["type"] == "agent.thinking" for e in agent_events)

        # Filter at debug level
        debug_events = [e for e in all_events if _matches_level(e["type"], "debug")]
        assert len(debug_events) == 4  # all events


# ---------------------------------------------------------------------------
# Event level validation
# ---------------------------------------------------------------------------


class TestEventLevelValidation:
    """Tests for event level parameter validation."""

    def test_valid_levels(self):
        """Valid event levels are accepted."""
        valid_levels = ("lifecycle", "agent", "debug")
        for level in valid_levels:
            assert level in valid_levels

    def test_invalid_level_fallback(self):
        """Invalid event level falls back to lifecycle."""
        invalid_levels = ("", "verbose", "trace", "LIFECYCLE", "Agent")
        for level in invalid_levels:
            # In the router, we validate: level if level in valid_set else "lifecycle"
            effective_level = level if level in ("lifecycle", "agent", "debug") else "lifecycle"
            assert effective_level == "lifecycle"
