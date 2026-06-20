"""Tests for Progress Event contract enforcement in orchestrator.

Validates that emit_progress / enforce_event_contract enforce:
- summary <= 200 chars
- long detail written to log artifact with log_ref
- stdout/stderr/traceback/full_output stripped
- backward-compat ``detail`` key alongside ``summary``
"""

from __future__ import annotations

from pathlib import Path

from engine.investigation.agent_models import PROGRESS_EVENT_SUMMARY_MAX_CHARS
from engine.static_audit.orchestrator import (
    StepResult,
    enforce_event_contract,
    emit_step_result,
    _write_long_text_to_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _long_text(length: int = 500) -> str:
    return "x" * length


def _collect_events():
    """Return (callback, events_list) — callback appends to events_list."""
    events: list[dict] = []

    def callback(event: dict) -> None:
        events.append(event)

    return callback, events


# ---------------------------------------------------------------------------
# Tests — enforce_event_contract
# ---------------------------------------------------------------------------


def test_summary_truncated_to_200_chars():
    """Long detail is truncated to PROGRESS_EVENT_SUMMARY_MAX_CHARS."""
    event = {"event": "step_result", "key": "test_step", "detail": _long_text(500)}
    result = enforce_event_contract(event)
    assert len(result["summary"]) == PROGRESS_EVENT_SUMMARY_MAX_CHARS
    assert len(result["detail"]) == PROGRESS_EVENT_SUMMARY_MAX_CHARS
    # Both keys carry the same truncated text.
    assert result["summary"] == result["detail"]


def test_short_detail_unchanged():
    """Short detail passes through without modification."""
    text = "All checks passed."
    event = {"event": "step_result", "key": "test_step", "detail": text}
    result = enforce_event_contract(event)
    assert result["summary"] == text
    assert result["detail"] == text
    assert "log_ref" not in result


def test_failed_event_requires_log_ref(tmp_path: Path):
    """When workdir is provided, a failed event with long detail gets log_ref."""
    event = {
        "event": "step_result",
        "key": "broken_step",
        "status": "failed",
        "detail": _long_text(300),
    }
    result = enforce_event_contract(event, workdir=tmp_path)
    assert result.get("log_ref") is not None
    assert result["log_ref"].startswith("agents/logs/")


def test_long_detail_written_to_log_file(tmp_path: Path):
    """Verify log file is created with full (un-truncated) text."""
    full_text = _long_text(400)
    event = {"event": "step_result", "key": "my_step", "detail": full_text}
    result = enforce_event_contract(event, workdir=tmp_path)

    log_ref = result.get("log_ref")
    assert log_ref is not None
    log_path = tmp_path / log_ref
    assert log_path.is_file()
    assert log_path.read_text(encoding="utf-8") == full_text


def test_event_strips_stdout_stderr():
    """stdout and stderr keys are removed from the event."""
    event = {
        "event": "step_result",
        "key": "cmd",
        "detail": "ok",
        "stdout": "some long stdout output",
        "stderr": "some warning",
    }
    result = enforce_event_contract(event)
    assert "stdout" not in result
    assert "stderr" not in result


def test_event_strips_traceback():
    """traceback key is removed from the event."""
    event = {
        "event": "step_result",
        "key": "failing",
        "status": "failed",
        "detail": "boom",
        "traceback": "Traceback (most recent call last):\n  ...",
    }
    result = enforce_event_contract(event)
    assert "traceback" not in result


def test_event_strips_full_output():
    """full_output key is removed from the event."""
    event = {
        "event": "step_result",
        "key": "step",
        "detail": "ok",
        "full_output": "huge combined output",
    }
    result = enforce_event_contract(event)
    assert "full_output" not in result


def test_log_ref_is_relative_path(tmp_path: Path):
    """log_ref must be a relative path, not absolute."""
    event = {"event": "step_result", "key": "step_x", "detail": _long_text(300)}
    result = enforce_event_contract(event, workdir=tmp_path)
    log_ref = result.get("log_ref")
    assert log_ref is not None
    # Must not start with / — relative to workdir.
    assert not Path(log_ref).is_absolute()
    assert log_ref.startswith("agents/logs/")


def test_enforce_event_contract_without_workdir():
    """Without workdir, truncation still happens but no log file is written."""
    event = {"event": "step_result", "key": "step", "detail": _long_text(500)}
    result = enforce_event_contract(event, workdir=None)
    assert len(result["summary"]) == PROGRESS_EVENT_SUMMARY_MAX_CHARS
    # No log_ref since there is no workdir to write to.
    assert result.get("log_ref") is None


# ---------------------------------------------------------------------------
# Tests — _write_long_text_to_log
# ---------------------------------------------------------------------------


def test_write_long_text_returns_none_for_empty(tmp_path: Path):
    """Empty text returns None, no file created."""
    assert _write_long_text_to_log(tmp_path, "step", "") is None


def test_write_long_text_creates_log(tmp_path: Path):
    """Non-empty text creates a log file and returns relative path."""
    ref = _write_long_text_to_log(tmp_path, "my_step", "hello world")
    assert ref is not None
    assert ref.startswith("agents/logs/my_step_")
    assert ref.endswith(".log")
    assert (tmp_path / ref).read_text(encoding="utf-8") == "hello world"


# ---------------------------------------------------------------------------
# Tests — emit_step_result integration
# ---------------------------------------------------------------------------


def test_emit_step_result_truncates_long_detail():
    """emit_step_result truncates long detail via enforce_event_contract."""
    callback, events = _collect_events()
    step = StepResult(
        key="test",
        title="Test step",
        status="ran",
        detail=_long_text(500),
    )
    emit_step_result(callback, step)
    assert len(events) == 1
    assert len(events[0]["detail"]) == PROGRESS_EVENT_SUMMARY_MAX_CHARS
    assert len(events[0]["summary"]) == PROGRESS_EVENT_SUMMARY_MAX_CHARS


def test_emit_step_result_writes_log_with_workdir(tmp_path: Path):
    """emit_step_result writes log and sets log_ref when workdir provided."""
    callback, events = _collect_events()
    full_detail = _long_text(300)
    step = StepResult(
        key="logged_step",
        title="Logged step",
        status="failed",
        detail=full_detail,
    )
    emit_step_result(callback, step, workdir=tmp_path)
    assert len(events) == 1
    event = events[0]
    assert event.get("log_ref") is not None
    log_path = tmp_path / event["log_ref"]
    assert log_path.is_file()
    assert log_path.read_text(encoding="utf-8") == full_detail
