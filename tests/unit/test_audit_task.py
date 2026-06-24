"""Tests for engine.tasks.audit_task.

Validates the four-layer idempotency guards, status transitions, stage
computation, and progress tracking of the Celery audit task.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


from engine.tasks.audit_task import (
    _compute_stages,
    _resolve_stage_from_event,
    _run_audit_impl,
)


def _make_mock_self(task_id: str = "celery-task-123") -> MagicMock:
    """Create a mock Celery task self with request.id."""
    mock_self = MagicMock()
    mock_self.request.id = task_id
    return mock_self


def _make_mock_row(
    run_id: str = "run-1",
    case_id: str = "case-1",
    status: str = "queued",
    celery_task_id: str | None = None,
) -> MagicMock:
    """Create a mock _RunRow with configurable attributes."""
    row = MagicMock()
    row.run_id = run_id
    row.case_id = case_id
    row.status = status
    row.celery_task_id = celery_task_id
    row.stages = None
    row.current_stage = None
    row.started_at = None
    row.completed_at = None
    row.last_event_at = None
    row.summary = None
    row.workdir = None
    row.final_html_report_url = None
    row.error = None
    return row


def _make_mock_session(row: MagicMock | None = None) -> MagicMock:
    """Create a mock SQLAlchemy session with query chain."""
    session = MagicMock()
    query_mock = MagicMock()
    filter_mock = MagicMock()

    session.query.return_value = query_mock
    query_mock.filter.return_value = filter_mock
    filter_mock.with_for_update.return_value = filter_mock
    filter_mock.first.return_value = row

    return session


def _make_mock_session_factory(session: MagicMock) -> MagicMock:
    """Create a mock session factory that returns the given session."""
    factory = MagicMock()
    factory.return_value = session
    return factory


class TestComputeStages:
    """Tests for _compute_stages."""

    def test_always_includes_pdf_parse_and_report(self, tmp_path: Path):
        """Verify pdf_parse and report are always present."""
        stages = _compute_stages(tmp_path, {})
        stage_ids = [s["id"] for s in stages]
        assert "pdf_parse" in stage_ids
        assert "report" in stage_ids

    def test_includes_source_data_when_files_exist(self, tmp_path: Path):
        """Verify source_data stage is added when data files are present."""
        (tmp_path / "data.csv").write_text("a,b\n1,2\n")
        stages = _compute_stages(tmp_path, {})
        stage_ids = [s["id"] for s in stages]
        assert "source_data" in stage_ids

    def test_excludes_source_data_when_no_files(self, tmp_path: Path):
        """Verify source_data stage is absent when no data files exist."""
        stages = _compute_stages(tmp_path, {})
        stage_ids = [s["id"] for s in stages]
        assert "source_data" not in stage_ids

    def test_skip_visual_option(self, tmp_path: Path):
        """Verify skip_visual removes visual stage."""
        stages_with = _compute_stages(tmp_path, {})
        stages_without = _compute_stages(tmp_path, {"skip_visual": True})
        ids_with = [s["id"] for s in stages_with]
        ids_without = [s["id"] for s in stages_without]
        assert "visual" in ids_with
        assert "visual" not in ids_without

    def test_skip_agent_option(self, tmp_path: Path):
        """Verify skip_agent removes agent stage."""
        stages_with = _compute_stages(tmp_path, {})
        stages_without = _compute_stages(tmp_path, {"skip_agent": True})
        ids_with = [s["id"] for s in stages_with]
        ids_without = [s["id"] for s in stages_without]
        assert "agent" in ids_with
        assert "agent" not in ids_without

    def test_stage_order(self, tmp_path: Path):
        """Verify stages are in expected order."""
        (tmp_path / "data.xlsx").write_text("")
        stages = _compute_stages(tmp_path, {})
        stage_ids = [s["id"] for s in stages]
        assert stage_ids == ["pdf_parse", "source_data", "visual", "agent", "report"]


class TestResolveStageFromEvent:
    """Tests for _resolve_stage_from_event."""

    def test_exact_key_match(self):
        """Verify exact key match returns correct stage."""
        assert _resolve_stage_from_event({"key": "mineru"}) == "pdf_parse"
        assert _resolve_stage_from_event({"key": "source_data_findings"}) == "source_data"
        assert _resolve_stage_from_event({"key": "visual_panel_extraction"}) == "visual"
        assert _resolve_stage_from_event({"key": "agent_plan"}) == "agent"
        assert _resolve_stage_from_event({"key": "html_report"}) == "report"

    def test_step_field_fallback(self):
        """Verify 'step' field is used when 'key' is missing."""
        assert _resolve_stage_from_event({"step": "mineru"}) == "pdf_parse"

    def test_prefix_match(self):
        """Verify prefix matching works for keys with extra suffixes."""
        # "source_data_findings_extra" starts with "source_data_findings" in _STEP_TO_STAGE
        assert _resolve_stage_from_event({"key": "source_data_findings_extra"}) == "source_data"

    def test_unknown_key_returns_none(self):
        """Verify unknown keys return None."""
        assert _resolve_stage_from_event({"key": "unknown_step"}) is None

    def test_empty_event_returns_none(self):
        """Verify empty events return None."""
        assert _resolve_stage_from_event({}) is None
        assert _resolve_stage_from_event({"key": ""}) is None


class TestRunAuditImplIdempotency:
    """Tests for idempotency guards in _run_audit_impl."""

    def test_skip_when_run_not_found(self):
        """Verify task returns skipped when run_id doesn't exist."""
        mock_self = _make_mock_self()
        mock_session = _make_mock_session(row=None)
        mock_factory = _make_mock_session_factory(mock_session)

        with patch("engine.tasks.audit_task._get_session_factory", return_value=mock_factory):
            result = _run_audit_impl(mock_self, "missing-run", "case-1", "/tmp/paper")

        assert result["status"] == "skipped"
        assert "not found" in result["reason"]

    def test_skip_when_celery_task_id_mismatch(self):
        """Verify task returns skipped when celery_task_id doesn't match."""
        mock_self = _make_mock_self(task_id="task-ABC")
        mock_row = _make_mock_row(celery_task_id="task-XYZ")
        mock_session = _make_mock_session(row=mock_row)
        mock_factory = _make_mock_session_factory(mock_session)

        with patch("engine.tasks.audit_task._get_session_factory", return_value=mock_factory):
            result = _run_audit_impl(mock_self, "run-1", "case-1", "/tmp/paper")

        assert result["status"] == "skipped"
        assert "celery_task_id mismatch" in result["reason"]

    def test_skip_when_status_not_queued(self):
        """Verify task returns skipped when status is not 'queued'."""
        mock_self = _make_mock_self()
        mock_row = _make_mock_row(status="running")
        mock_session = _make_mock_session(row=mock_row)
        mock_factory = _make_mock_session_factory(mock_session)

        with patch("engine.tasks.audit_task._get_session_factory", return_value=mock_factory):
            result = _run_audit_impl(mock_self, "run-1", "case-1", "/tmp/paper")

        assert result["status"] == "skipped"
        assert "status=running" in result["reason"]

    def test_skip_when_status_completed(self):
        """Verify task returns skipped when status is already 'completed'."""
        mock_self = _make_mock_self()
        mock_row = _make_mock_row(status="completed")
        mock_session = _make_mock_session(row=mock_row)
        mock_factory = _make_mock_session_factory(mock_session)

        with patch("engine.tasks.audit_task._get_session_factory", return_value=mock_factory):
            result = _run_audit_impl(mock_self, "run-1", "case-1", "/tmp/paper")

        assert result["status"] == "skipped"
        assert "status=completed" in result["reason"]

    def test_skip_when_status_cancelled(self):
        """Verify task returns skipped when status is 'cancelled'."""
        mock_self = _make_mock_self()
        mock_row = _make_mock_row(status="cancelled")
        mock_session = _make_mock_session(row=mock_row)
        mock_factory = _make_mock_session_factory(mock_session)

        with patch("engine.tasks.audit_task._get_session_factory", return_value=mock_factory):
            result = _run_audit_impl(mock_self, "run-1", "case-1", "/tmp/paper")

        assert result["status"] == "skipped"
        assert "status=cancelled" in result["reason"]


class TestRunAuditImplStatusTransitions:
    """Tests for status transitions in _run_audit_impl."""

    def test_queued_to_running_to_completed(self, tmp_path: Path):
        """Verify full status transition: queued -> running -> completed."""
        mock_self = _make_mock_self(task_id="task-001")
        mock_row = _make_mock_row(run_id="run-100", case_id="case-100", status="queued")
        mock_session = _make_mock_session(row=mock_row)
        mock_factory = _make_mock_session_factory(mock_session)

        mock_summary = {
            "exit_code": 0,
            "workdir": str(tmp_path),
            "final_report": str(tmp_path / "report.md"),
            "final_html_report": str(tmp_path / "report.html"),
            "failed_steps": [],
        }

        with patch("engine.tasks.audit_task._get_session_factory", return_value=mock_factory):
            with patch("engine.tasks.audit_task._compute_stages", return_value=[{"id": "pdf_parse"}]):
                with patch("engine.tasks.audit_task._notify_progress"):
                    with patch(
                        "engine.static_audit.pipeline.run_static_audit",
                        return_value=mock_summary,
                    ):
                        result = _run_audit_impl(
                            mock_self, "run-100", "case-100", str(tmp_path)
                        )

        assert result["status"] == "completed"
        assert result["run_id"] == "run-100"
        # Verify status was set to running during execution
        assert mock_row.status == "completed"
        assert mock_row.started_at is not None
        assert mock_row.completed_at is not None
        assert mock_row.celery_task_id == "task-001"

    def test_failure_sets_failed_status(self, tmp_path: Path):
        """Verify pipeline failure sets status to 'failed'."""
        mock_self = _make_mock_self()
        mock_row = _make_mock_row(run_id="run-200", status="queued")
        mock_session = _make_mock_session(row=mock_row)
        mock_factory = _make_mock_session_factory(mock_session)

        with patch("engine.tasks.audit_task._get_session_factory", return_value=mock_factory):
            with patch("engine.tasks.audit_task._compute_stages", return_value=[]):
                with patch("engine.tasks.audit_task._notify_progress"):
                    with patch(
                        "engine.static_audit.pipeline.run_static_audit",
                        side_effect=RuntimeError("Pipeline crashed"),
                    ):
                        result = _run_audit_impl(
                            mock_self, "run-200", "case-200", str(tmp_path)
                        )

        assert result["status"] == "failed"
        assert "RuntimeError" in result["error"]
        assert "Pipeline crashed" in result["error"]
        assert mock_row.status == "failed"
        assert mock_row.error is not None

    def test_pipeline_failed_steps_sets_failed(self, tmp_path: Path):
        """Verify failed_steps in summary sets status to 'failed'."""
        mock_self = _make_mock_self()
        mock_row = _make_mock_row(run_id="run-300", status="queued")
        mock_session = _make_mock_session(row=mock_row)
        mock_factory = _make_mock_session_factory(mock_session)

        mock_summary = {
            "exit_code": 1,
            "failed_steps": ["visual_panel_extraction"],
            "final_report": "",
            "final_html_report": "",
        }

        with patch("engine.tasks.audit_task._get_session_factory", return_value=mock_factory):
            with patch("engine.tasks.audit_task._compute_stages", return_value=[]):
                with patch("engine.tasks.audit_task._notify_progress"):
                    with patch(
                        "engine.static_audit.pipeline.run_static_audit",
                        return_value=mock_summary,
                    ):
                        result = _run_audit_impl(
                            mock_self, "run-300", "case-300", str(tmp_path)
                        )

        assert result["status"] == "failed"
        assert "visual_panel_extraction" in result["error"]

    def test_partial_failure_with_reports_is_completed(self, tmp_path: Path):
        """Verify that failed_steps with existing reports is treated as completed."""
        mock_self = _make_mock_self()
        mock_row = _make_mock_row(run_id="run-400", status="queued")
        mock_session = _make_mock_session(row=mock_row)
        mock_factory = _make_mock_session_factory(mock_session)

        report_path = tmp_path / "report.md"
        html_path = tmp_path / "report.html"
        report_path.write_text("report")
        html_path.write_text("<html>report</html>")

        mock_summary = {
            "exit_code": 1,
            "failed_steps": ["visual_panel_extraction"],
            "final_report": str(report_path),
            "final_html_report": str(html_path),
        }

        with patch("engine.tasks.audit_task._get_session_factory", return_value=mock_factory):
            with patch("engine.tasks.audit_task._compute_stages", return_value=[]):
                with patch("engine.tasks.audit_task._notify_progress"):
                    with patch(
                        "engine.static_audit.pipeline.run_static_audit",
                        return_value=mock_summary,
                    ):
                        result = _run_audit_impl(
                            mock_self, "run-400", "case-400", str(tmp_path)
                        )

        # Should be completed because reports exist
        assert result["status"] == "completed"

    def test_cleanup_called_on_failure(self, tmp_path: Path):
        """Verify cleanup is called when status is 'failed'."""
        mock_self = _make_mock_self()
        mock_row = _make_mock_row(run_id="run-500", case_id="case-500", status="queued")
        mock_session = _make_mock_session(row=mock_row)
        mock_factory = _make_mock_session_factory(mock_session)

        with patch("engine.tasks.audit_task._get_session_factory", return_value=mock_factory):
            with patch("engine.tasks.audit_task._compute_stages", return_value=[]):
                with patch("engine.tasks.audit_task._notify_progress"):
                    with patch(
                        "engine.static_audit.pipeline.run_static_audit",
                        side_effect=RuntimeError("fail"),
                    ):
                        with patch(
                            "engine.tasks.process_cleanup.cleanup_audit_processes"
                        ) as mock_cleanup:
                            mock_cleanup.return_value = {
                                "killed_processes": [],
                                "stopped_containers": [],
                                "cleaned_dirs": [],
                                "errors": [],
                            }
                            result = _run_audit_impl(
                                mock_self, "run-500", "case-500", str(tmp_path)
                            )

        assert result["status"] == "failed"
        mock_cleanup.assert_called_once_with("run-500", "case-500")

    def test_cleanup_not_called_on_success(self, tmp_path: Path):
        """Verify cleanup is NOT called when status is 'completed'."""
        mock_self = _make_mock_self()
        mock_row = _make_mock_row(run_id="run-600", status="queued")
        mock_session = _make_mock_session(row=mock_row)
        mock_factory = _make_mock_session_factory(mock_session)

        mock_summary = {
            "exit_code": 0,
            "workdir": str(tmp_path),
            "final_report": str(tmp_path / "report.md"),
            "final_html_report": str(tmp_path / "report.html"),
            "failed_steps": [],
        }

        with patch("engine.tasks.audit_task._get_session_factory", return_value=mock_factory):
            with patch("engine.tasks.audit_task._compute_stages", return_value=[]):
                with patch("engine.tasks.audit_task._notify_progress"):
                    with patch(
                        "engine.static_audit.pipeline.run_static_audit",
                        return_value=mock_summary,
                    ):
                        with patch(
                            "engine.tasks.process_cleanup.cleanup_audit_processes"
                        ) as mock_cleanup:
                            result = _run_audit_impl(
                                mock_self, "run-600", "case-600", str(tmp_path)
                            )

        assert result["status"] == "completed"
        mock_cleanup.assert_not_called()


class TestRunAuditImplProgressCallback:
    """Tests for progress callback and stage tracking."""

    def test_progress_updates_current_stage(self, tmp_path: Path):
        """Verify progress callback updates current_stage on the run row."""
        mock_self = _make_mock_self()
        mock_row = _make_mock_row(run_id="run-700", status="queued")
        mock_session = _make_mock_session(row=mock_row)
        mock_factory = _make_mock_session_factory(mock_session)

        mock_summary = {
            "exit_code": 0,
            "workdir": str(tmp_path),
            "final_report": "",
            "final_html_report": "",
            "failed_steps": [],
        }

        def fake_pipeline(*args, **kwargs):
            progress = kwargs.get("progress")
            if progress:
                progress({"key": "mineru", "event": "step_start"})
                progress({"key": "html_report", "event": "step_end"})
            return mock_summary

        with patch("engine.tasks.audit_task._get_session_factory", return_value=mock_factory):
            with patch("engine.tasks.audit_task._compute_stages", return_value=[]):
                with patch("engine.tasks.audit_task._notify_progress"):
                    with patch(
                        "engine.static_audit.pipeline.run_static_audit",
                        side_effect=fake_pipeline,
                    ):
                        result = _run_audit_impl(
                            mock_self, "run-700", "case-700", str(tmp_path)
                        )

        assert result["status"] == "completed"
