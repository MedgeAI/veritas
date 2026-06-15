from __future__ import annotations

import io
import json

from cli.commands.audit_paper import format_plain_progress, make_progress_reporter


def test_plain_progress_formats_step_without_full_command() -> None:
    line = format_plain_progress(
        {
            "event": "step_start",
            "timestamp": "2026-05-27T00:00:00Z",
            "key": "agent_review",
            "title": "opencode Agent 结构化审阅",
            "detail": "Calling opencode.",
            "command_preview": "opencode run --format json --model dashscope/qwen3.7-plus ...",
        }
    )

    assert "START agent_review" in line
    assert "opencode Agent 结构化审阅" in line
    assert "dashscope/qwen3.7-plus" in line


def test_jsonl_progress_reporter_writes_one_event_per_line() -> None:
    stream = io.StringIO()
    reporter = make_progress_reporter("jsonl", stream=stream)

    assert reporter is not None
    reporter({"event": "step_result", "key": "report", "status": "ran"})

    assert json.loads(stream.getvalue()) == {"event": "step_result", "key": "report", "status": "ran"}


def test_plain_progress_formats_command_output() -> None:
    line = format_plain_progress(
        {
            "event": "command_output",
            "timestamp": "2026-05-27T00:00:00Z",
            "key": "mineru",
            "line": "state=running pages=12/30",
        }
    )

    assert line.endswith("OUT   mineru | state=running pages=12/30")


def test_auto_progress_is_quiet_for_non_tty_stream() -> None:
    stream = io.StringIO()

    assert make_progress_reporter("auto", stream=stream) is None
