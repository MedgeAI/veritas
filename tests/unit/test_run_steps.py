"""Tests for engine.static_audit.run_steps.

Covers:
- build_steps_list: event consumption, status derivation, duration calc
- summarise_steps: aggregate counters
- Edge cases: empty events, missing timestamps, unknown keys
"""

from __future__ import annotations

from datetime import UTC, datetime

from engine.static_audit.run_steps import (
    build_steps_list,
    summarise_run_timing,
    summarise_steps,
)


# ---------------------------------------------------------------------------
# build_steps_list — basic behaviour
# ---------------------------------------------------------------------------


class TestBuildStepsListBasic:
    """Tests for basic step list construction."""

    def test_empty_events_returns_empty_list(self) -> None:
        """An empty events list produces an empty step list."""
        assert build_steps_list([]) == []

    def test_non_step_events_are_ignored(self) -> None:
        """Events that are not step_start/step_result are filtered out."""
        events = [
            {"event": "progress", "key": "some_progress"},
            {"event": "completed", "key": "some_completed"},
            {"event": "heartbeat", "timestamp": "2026-06-26T00:00:00Z"},
        ]
        assert build_steps_list(events) == []

    def test_step_start_only_marks_running(self) -> None:
        """A step with only step_start has status 'running'."""
        events = [
            {
                "event": "step_start",
                "key": "visual_tru_for",
                "title": "TruFor 伪造检测",
                "timestamp": "2026-06-26T00:01:00Z",
            }
        ]
        steps = build_steps_list(events)
        assert len(steps) == 1
        step = steps[0]
        assert step["key"] == "visual_tru_for"
        assert step["title"] == "TruFor 伪造检测"
        assert step["status"] == "running"
        assert step["started_at"] == "2026-06-26T00:01:00Z"
        assert step["duration_seconds"] is None
        assert step["phase"] == "视觉取证"
        assert step["phase_order"] == 5

    def test_step_result_completed_status(self) -> None:
        """step_result with status='ran' maps to 'completed'."""
        events = [
            {
                "event": "step_start",
                "key": "mineru",
                "timestamp": "2026-06-26T00:00:00Z",
            },
            {
                "event": "step_result",
                "key": "mineru",
                "status": "ran",
                "timestamp": "2026-06-26T00:00:45Z",
            },
        ]
        steps = build_steps_list(events)
        assert len(steps) == 1
        step = steps[0]
        assert step["status"] == "completed"
        assert step["duration_seconds"] == 45.0
        assert step["started_at"] == "2026-06-26T00:00:00Z"

    def test_step_result_reused_status(self) -> None:
        """step_result with status='reused' maps to 'completed'."""
        events = [
            {
                "event": "step_start",
                "key": "evidence_ledger",
                "timestamp": "2026-06-26T00:00:00Z",
            },
            {
                "event": "step_result",
                "key": "evidence_ledger",
                "status": "reused",
                "timestamp": "2026-06-26T00:00:05Z",
            },
        ]
        steps = build_steps_list(events)
        assert steps[0]["status"] == "completed"
        assert steps[0]["duration_seconds"] == 5.0

    def test_step_result_failed_status(self) -> None:
        """step_result with status='failed' maps to 'failed'."""
        events = [
            {
                "event": "step_start",
                "key": "visual_provenance_graph",
                "timestamp": "2026-06-26T00:00:00Z",
            },
            {
                "event": "step_result",
                "key": "visual_provenance_graph",
                "status": "failed",
                "timestamp": "2026-06-26T00:10:00Z",
            },
        ]
        steps = build_steps_list(events)
        assert steps[0]["status"] == "failed"
        assert steps[0]["duration_seconds"] == 600.0

    def test_step_result_skipped_status(self) -> None:
        """step_result with status='skipped' maps to 'skipped'."""
        events = [
            {
                "event": "step_start",
                "key": "paperconan_scan",
                "timestamp": "2026-06-26T00:00:00Z",
            },
            {
                "event": "step_result",
                "key": "paperconan_scan",
                "status": "skipped",
                "timestamp": "2026-06-26T00:00:01Z",
            },
        ]
        steps = build_steps_list(events)
        assert steps[0]["status"] == "skipped"

    def test_step_result_warning_status(self) -> None:
        """step_result with status='warning' maps to 'warning'."""
        events = [
            {
                "event": "step_start",
                "key": "agent_review",
                "timestamp": "2026-06-26T00:00:00Z",
            },
            {
                "event": "step_result",
                "key": "agent_review",
                "status": "warning",
                "detail": "schema validation warning",
                "timestamp": "2026-06-26T00:00:30Z",
            },
        ]
        steps = build_steps_list(events)
        assert steps[0]["status"] == "warning"
        assert steps[0]["detail"] == "schema validation warning"

    def test_step_result_without_start_has_no_started_at(self) -> None:
        """A step_result without a preceding step_start has started_at=None."""
        events = [
            {
                "event": "step_result",
                "key": "discover",
                "status": "ran",
                "timestamp": "2026-06-26T00:00:10Z",
            }
        ]
        steps = build_steps_list(events)
        assert len(steps) == 1
        assert steps[0]["started_at"] is None
        assert steps[0]["status"] == "completed"
        assert steps[0]["duration_seconds"] is None


# ---------------------------------------------------------------------------
# build_steps_list — ordering and grouping
# ---------------------------------------------------------------------------


class TestBuildStepsListOrdering:
    """Tests for step ordering and phase grouping."""

    def test_steps_preserve_discovery_order(self) -> None:
        """Steps appear in the order their first event was seen."""
        events = [
            {"event": "step_start", "key": "discover", "timestamp": "2026-06-26T00:00:00Z"},
            {"event": "step_start", "key": "mineru", "timestamp": "2026-06-26T00:00:10Z"},
            {"event": "step_start", "key": "agent_plan", "timestamp": "2026-06-26T00:00:20Z"},
        ]
        steps = build_steps_list(events)
        assert [s["key"] for s in steps] == ["discover", "mineru", "agent_plan"]

    def test_phase_labels_from_step_labels(self) -> None:
        """Phase and phase_order come from step_labels mapping."""
        events = [
            {"event": "step_start", "key": "discover", "timestamp": "2026-06-26T00:00:00Z"},
            {"event": "step_start", "key": "visual_tru_for", "timestamp": "2026-06-26T00:01:00Z"},
            {"event": "step_start", "key": "agent_review", "timestamp": "2026-06-26T00:02:00Z"},
        ]
        steps = build_steps_list(events)
        assert steps[0]["phase"] == "准备"
        assert steps[0]["phase_order"] == 1
        assert steps[1]["phase"] == "视觉取证"
        assert steps[1]["phase_order"] == 5
        assert steps[2]["phase"] == "Agent 审查"
        assert steps[2]["phase_order"] == 6


# ---------------------------------------------------------------------------
# build_steps_list — unknown keys and fallback
# ---------------------------------------------------------------------------


class TestBuildStepsListFallback:
    """Tests for unknown step key fallback."""

    def test_unknown_key_uses_fallback_label(self) -> None:
        """Unknown step keys get a generated title from the key."""
        events = [
            {
                "event": "step_start",
                "key": "some_new_step",
                "timestamp": "2026-06-26T00:00:00Z",
            }
        ]
        steps = build_steps_list(events)
        assert steps[0]["title"] == "Some New Step"
        assert steps[0]["phase"] == "Unknown"
        assert steps[0]["phase_order"] == 99

    def test_custom_step_labels_override(self) -> None:
        """Providing step_labels overrides the default mapping."""
        custom_labels = {
            "my_step": {"title": "自定义步骤", "phase": "自定义阶段", "phase_order": 42}
        }
        events = [
            {"event": "step_start", "key": "my_step", "timestamp": "2026-06-26T00:00:00Z"}
        ]
        steps = build_steps_list(events, step_labels=custom_labels)
        assert steps[0]["title"] == "自定义步骤"
        assert steps[0]["phase"] == "自定义阶段"
        assert steps[0]["phase_order"] == 42


# ---------------------------------------------------------------------------
# build_steps_list — title handling
# ---------------------------------------------------------------------------


class TestBuildStepsListTitle:
    """Tests for title resolution."""

    def test_title_from_step_start_is_used(self) -> None:
        """The title from step_start is preferred over the label mapping."""
        events = [
            {
                "event": "step_start",
                "key": "mineru",
                "title": "自定义 PDF 解析标题",
                "timestamp": "2026-06-26T00:00:00Z",
            },
            {
                "event": "step_result",
                "key": "mineru",
                "status": "ran",
                "timestamp": "2026-06-26T00:00:30Z",
            },
        ]
        steps = build_steps_list(events)
        assert steps[0]["title"] == "自定义 PDF 解析标题"

    def test_title_from_step_result_overrides_start(self) -> None:
        """The title from step_result overrides step_start."""
        events = [
            {
                "event": "step_start",
                "key": "mineru",
                "title": "开始标题",
                "timestamp": "2026-06-26T00:00:00Z",
            },
            {
                "event": "step_result",
                "key": "mineru",
                "status": "ran",
                "title": "结果标题",
                "timestamp": "2026-06-26T00:00:30Z",
            },
        ]
        steps = build_steps_list(events)
        assert steps[0]["title"] == "结果标题"


# ---------------------------------------------------------------------------
# build_steps_list — duration calculation
# ---------------------------------------------------------------------------


class TestBuildStepsListDuration:
    """Tests for duration calculation."""

    def test_duration_in_seconds(self) -> None:
        """Duration is computed as end - start in seconds."""
        events = [
            {
                "event": "step_start",
                "key": "visual_copy_move",
                "timestamp": "2026-06-26T10:00:00Z",
            },
            {
                "event": "step_result",
                "key": "visual_copy_move",
                "status": "ran",
                "timestamp": "2026-06-26T10:02:30Z",
            },
        ]
        steps = build_steps_list(events)
        assert steps[0]["duration_seconds"] == 150.0

    def test_duration_with_milliseconds(self) -> None:
        """Duration handles sub-second precision."""
        events = [
            {
                "event": "step_start",
                "key": "discover",
                "timestamp": "2026-06-26T00:00:00.123Z",
            },
            {
                "event": "step_result",
                "key": "discover",
                "status": "ran",
                "timestamp": "2026-06-26T00:00:01.456Z",
            },
        ]
        steps = build_steps_list(events)
        assert abs(steps[0]["duration_seconds"] - 1.333) < 0.01

    def test_negative_duration_clamped_to_none(self) -> None:
        """If end_ts < start_ts (clock skew), duration is None."""
        events = [
            {
                "event": "step_start",
                "key": "mineru",
                "timestamp": "2026-06-26T00:01:00Z",
            },
            {
                "event": "step_result",
                "key": "mineru",
                "status": "ran",
                "timestamp": "2026-06-26T00:00:00Z",
            },
        ]
        steps = build_steps_list(events)
        assert steps[0]["duration_seconds"] is None


# ---------------------------------------------------------------------------
# build_steps_list — edge cases
# ---------------------------------------------------------------------------


class TestBuildStepsListEdgeCases:
    """Tests for edge cases."""

    def test_events_without_key_are_skipped(self) -> None:
        """Events without a 'key' field are silently ignored."""
        events = [
            {"event": "step_start", "timestamp": "2026-06-26T00:00:00Z"},
            {"event": "step_result", "status": "ran", "timestamp": "2026-06-26T00:00:10Z"},
        ]
        assert build_steps_list(events) == []

    def test_events_with_empty_key_are_skipped(self) -> None:
        """Events with an empty 'key' are ignored."""
        events = [
            {"event": "step_start", "key": "", "timestamp": "2026-06-26T00:00:00Z"}
        ]
        assert build_steps_list(events) == []

    def test_events_with_invalid_timestamp_are_handled(self) -> None:
        """Invalid timestamp strings don't crash the function."""
        events = [
            {
                "event": "step_start",
                "key": "discover",
                "timestamp": "not-a-timestamp",
            },
            {
                "event": "step_result",
                "key": "discover",
                "status": "ran",
                "timestamp": "also-not-a-timestamp",
            },
        ]
        steps = build_steps_list(events)
        assert len(steps) == 1
        assert steps[0]["status"] == "completed"
        assert steps[0]["started_at"] is None
        assert steps[0]["duration_seconds"] is None

    def test_multiple_steps_mixed_statuses(self) -> None:
        """A realistic mix of steps with various statuses."""
        events = [
            # completed
            {"event": "step_start", "key": "discover", "timestamp": "2026-06-26T00:00:00Z"},
            {"event": "step_result", "key": "discover", "status": "ran", "timestamp": "2026-06-26T00:00:05Z"},
            # running
            {"event": "step_start", "key": "mineru", "timestamp": "2026-06-26T00:00:10Z"},
            # failed
            {"event": "step_start", "key": "visual_tru_for", "timestamp": "2026-06-26T00:01:00Z"},
            {"event": "step_result", "key": "visual_tru_for", "status": "failed", "timestamp": "2026-06-26T00:05:00Z"},
            # skipped
            {"event": "step_start", "key": "paperconan_scan", "timestamp": "2026-06-26T00:00:20Z"},
            {"event": "step_result", "key": "paperconan_scan", "status": "skipped", "timestamp": "2026-06-26T00:00:21Z"},
        ]
        steps = build_steps_list(events)
        statuses = {s["key"]: s["status"] for s in steps}
        assert statuses["discover"] == "completed"
        assert statuses["mineru"] == "running"
        assert statuses["visual_tru_for"] == "failed"
        assert statuses["paperconan_scan"] == "skipped"
        assert len(steps) == 4

    def test_duplicate_step_start_uses_first_timestamp(self) -> None:
        """If a step_start is repeated, the first timestamp is used for duration."""
        events = [
            {
                "event": "step_start",
                "key": "mineru",
                "timestamp": "2026-06-26T00:00:00Z",
            },
            {
                "event": "step_start",
                "key": "mineru",
                "timestamp": "2026-06-26T00:00:30Z",
            },
            {
                "event": "step_result",
                "key": "mineru",
                "status": "ran",
                "timestamp": "2026-06-26T00:01:00Z",
            },
        ]
        steps = build_steps_list(events)
        assert len(steps) == 1
        # duration should be from the first start (00:00:00) to end (00:01:00) = 60s
        assert steps[0]["duration_seconds"] == 60.0
        assert steps[0]["started_at"] == "2026-06-26T00:00:00Z"

    def test_orphan_started_step_stays_running_while_run_active(self) -> None:
        """A start without result is still running while the run is active."""
        events = [
            {
                "event": "step_start",
                "key": "source_data_verdict",
                "timestamp": "2026-06-26T00:00:00Z",
            }
        ]

        steps = build_steps_list(events, run_status="running")

        assert steps[0]["status"] == "running"

    def test_orphan_started_step_warns_after_run_completed(self) -> None:
        """A terminal run should not display orphan starts as still running."""
        events = [
            {
                "event": "step_start",
                "key": "source_data_verdict",
                "timestamp": "2026-06-26T00:00:00Z",
            }
        ]

        steps = build_steps_list(events, run_status="completed")

        assert steps[0]["status"] == "warning"
        assert "terminal status" in steps[0]["detail"]


# ---------------------------------------------------------------------------
# summarise_steps
# ---------------------------------------------------------------------------


class TestSummariseSteps:
    """Tests for the summarise_steps helper."""

    def test_empty_list(self) -> None:
        """Empty step list gives all zeros."""
        summary = summarise_steps([])
        assert summary == {
            "total": 0,
            "completed": 0,
            "running": 0,
            "failed": 0,
            "skipped": 0,
            "warnings": 0,
            "progress_pct": 0,
        }

    def test_all_completed(self) -> None:
        """All completed steps gives 100% progress."""
        steps = [
            {"key": "a", "status": "completed"},
            {"key": "b", "status": "completed"},
            {"key": "c", "status": "completed"},
        ]
        summary = summarise_steps(steps)
        assert summary["total"] == 3
        assert summary["completed"] == 3
        assert summary["progress_pct"] == 100

    def test_mixed_statuses(self) -> None:
        """Mixed statuses are counted correctly."""
        steps = [
            {"key": "a", "status": "completed"},
            {"key": "b", "status": "completed"},
            {"key": "c", "status": "running"},
            {"key": "d", "status": "failed"},
            {"key": "e", "status": "skipped"},
            {"key": "f", "status": "pending"},
            {"key": "g", "status": "warning"},
        ]
        summary = summarise_steps(steps)
        assert summary["total"] == 7
        assert summary["completed"] == 2
        assert summary["running"] == 1
        assert summary["failed"] == 1
        assert summary["skipped"] == 1
        assert summary["warnings"] == 1
        # 2/7 = 28%
        assert summary["progress_pct"] == 28

    def test_progress_pct_integer_truncation(self) -> None:
        """progress_pct is truncated to an integer."""
        steps = [
            {"key": "a", "status": "completed"},
            {"key": "b", "status": "running"},
            {"key": "c", "status": "running"},
        ]
        summary = summarise_steps(steps)
        # 1/3 = 33.33... -> truncated to 33
        assert summary["progress_pct"] == 33


# ---------------------------------------------------------------------------
# summarise_run_timing
# ---------------------------------------------------------------------------


class TestSummariseRunTiming:
    """Tests for factual timing metadata without ETA estimation."""

    def test_active_run_reports_current_step_and_elapsed_time(self) -> None:
        now = datetime(2026, 6, 26, 0, 10, tzinfo=UTC)
        steps = [
            {"key": "discover", "title": "发现输入", "phase": "准备", "status": "completed"},
            {
                "key": "agent_review",
                "title": "Agent 审查",
                "phase": "Agent 审查",
                "status": "running",
                "started_at": "2026-06-26T00:09:00Z",
            },
        ]

        summary = summarise_run_timing(
            steps,
            run_status="running",
            started_at="2026-06-26T00:00:00Z",
            completed_at=None,
            last_event_at="2026-06-26T00:09:00Z",
            stale_after_seconds=300,
            now=now,
        )

        assert summary["timing_status"] == "active"
        assert summary["current_step"]["key"] == "agent_review"
        assert summary["latest_step"]["key"] == "agent_review"
        assert summary["elapsed_seconds"] == 600
        assert summary["seconds_since_last_event"] == 60
        assert summary["is_stale"] is False
        assert summary["eta"] is None

    def test_stale_active_run_reports_waiting_for_new_event(self) -> None:
        now = datetime(2026, 6, 26, 0, 10, tzinfo=UTC)
        steps = [
            {
                "key": "mineru",
                "title": "PDF 解析",
                "phase": "文档解析",
                "status": "running",
                "started_at": "2026-06-26T00:00:00Z",
            }
        ]

        summary = summarise_run_timing(
            steps,
            run_status="running",
            started_at="2026-06-26T00:00:00Z",
            completed_at=None,
            last_event_at="2026-06-26T00:00:30Z",
            stale_after_seconds=300,
            now=now,
        )

        assert summary["timing_status"] == "stale"
        assert summary["current_step"]["key"] == "mineru"
        assert summary["seconds_since_last_event"] == 570
        assert summary["is_stale"] is True
        assert summary["eta"] is None

    def test_completed_run_uses_completed_at_for_elapsed_time(self) -> None:
        now = datetime(2026, 6, 26, 1, 0, tzinfo=UTC)
        steps = [
            {
                "key": "report",
                "title": "报告生成",
                "phase": "报告",
                "status": "completed",
            }
        ]

        summary = summarise_run_timing(
            steps,
            run_status="completed",
            started_at="2026-06-26T00:00:00Z",
            completed_at="2026-06-26T00:12:00Z",
            last_event_at="2026-06-26T00:12:00Z",
            stale_after_seconds=300,
            now=now,
        )

        assert summary["timing_status"] == "complete"
        assert summary["current_step"] is None
        assert summary["latest_step"]["key"] == "report"
        assert summary["elapsed_seconds"] == 720
        assert summary["is_stale"] is False
        assert summary["eta"] is None


# ---------------------------------------------------------------------------
# Integration: events -> steps list -> summary
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end tests combining build_steps_list and summarise_steps."""

    def test_realistic_pipeline_scenario(self) -> None:
        """A realistic sequence of events produces the expected summary."""
        events = [
            # Phase 1: 准备 — all completed
            {"event": "step_start", "key": "discover", "timestamp": "2026-06-26T00:00:00Z"},
            {"event": "step_result", "key": "discover", "status": "ran", "timestamp": "2026-06-26T00:00:05Z"},
            {"event": "step_start", "key": "agent_plan", "timestamp": "2026-06-26T00:00:10Z"},
            {"event": "step_result", "key": "agent_plan", "status": "ran", "timestamp": "2026-06-26T00:00:30Z"},
            # Phase 2: 文档解析 — one completed, one running
            {"event": "step_start", "key": "mineru", "timestamp": "2026-06-26T00:01:00Z"},
            {"event": "step_result", "key": "mineru", "status": "ran", "timestamp": "2026-06-26T00:03:00Z"},
            {"event": "step_start", "key": "evidence_ledger", "timestamp": "2026-06-26T00:03:05Z"},
            # Phase 3: 数值取证 — one failed
            {"event": "step_start", "key": "numeric_forensics", "timestamp": "2026-06-26T00:05:00Z"},
            {"event": "step_result", "key": "numeric_forensics", "status": "failed", "timestamp": "2026-06-26T00:06:00Z"},
        ]

        steps = build_steps_list(events)
        assert len(steps) == 5

        summary = summarise_steps(steps)
        assert summary["total"] == 5
        assert summary["completed"] == 3  # discover, agent_plan, mineru
        assert summary["running"] == 1    # evidence_ledger
        assert summary["failed"] == 1     # numeric_forensics
        assert summary["progress_pct"] == 60  # 3/5 = 60%

        # Verify phase ordering is preserved
        phases = [(s["phase"], s["phase_order"]) for s in steps]
        assert phases[0] == ("准备", 1)
        assert phases[1] == ("准备", 1)
        assert phases[2] == ("文档解析", 2)
        assert phases[3] == ("文档解析", 2)
        assert phases[4] == ("数值取证", 3)
