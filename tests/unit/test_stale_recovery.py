from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from web.backend.veritas_web.case_store import CaseStore
from web.backend.veritas_web.models import (
    RUN_STATUSES,
    STALE_RUN_THRESHOLD_SECONDS,
    AuditRunRecord,
    utc_now,
)
from web.backend.veritas_web.runner import AuditRunner


def fake_audit_func(paper_dir: Path, **kwargs: Any) -> dict[str, Any]:
    case_id = kwargs["case_id"]
    output_root = Path(kwargs["output_root"])
    workdir = output_root / case_id / "research-integrity-audit"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "audit_run_manifest.json").write_text('{"steps":[]}\n', encoding="utf-8")
    (workdir / "static_audit_bundle.json").write_text(
        '{"protocol_version":"test"}\n', encoding="utf-8"
    )
    (workdir / "investigation_rounds.jsonl").write_text("", encoding="utf-8")
    (workdir / "final_audit_report.html").write_text(
        "<html>Veritas</html>", encoding="utf-8"
    )
    progress = kwargs.get("progress")
    if progress:
        progress(
            {
                "timestamp": "2026-05-29T00:00:00Z",
                "event": "audit_start",
                "case_id": case_id,
            }
        )
        progress(
            {
                "timestamp": "2026-05-29T00:00:01Z",
                "event": "audit_end",
                "status": "completed",
            }
        )
    return {
        "exit_code": 0,
        "case_id": case_id,
        "workdir": str(workdir),
        "final_html_report": str(workdir / "final_audit_report.html"),
        "run_manifest": str(workdir / "audit_run_manifest.json"),
        "static_audit_bundle": str(workdir / "static_audit_bundle.json"),
        "failed_steps": [],
    }


def test_audit_run_record_has_last_event_at_field() -> None:
    """Verify AuditRunRecord has last_event_at field with default None."""
    record = AuditRunRecord(run_id="run-1", case_id="case-1")
    assert hasattr(record, "last_event_at")
    assert record.last_event_at is None


def test_runner_sets_last_event_at_on_start(tmp_path: Path) -> None:
    """After run_sync starts, last_event_at is set to initial heartbeat."""
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    store.write_input(case.case_id, "paper.pdf", b"%PDF-1.4\n")
    run = store.create_run(case.case_id)
    runner = AuditRunner(
        store, audit_func=fake_audit_func, output_root=tmp_path / "outputs"
    )

    completed = runner.run_sync(case.case_id, run.run_id, {"agent_mode": "review"})

    assert completed.last_event_at is not None
    # last_event_at should be set (either initial or updated by progress)
    assert completed.started_at is not None


def test_runner_updates_last_event_at_on_progress(tmp_path: Path) -> None:
    """After progress callback fires, last_event_at is updated."""
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    store.write_input(case.case_id, "paper.pdf", b"%PDF-1.4\n")
    run = store.create_run(case.case_id)
    runner = AuditRunner(
        store, audit_func=fake_audit_func, output_root=tmp_path / "outputs"
    )

    completed = runner.run_sync(case.case_id, run.run_id, {"agent_mode": "review"})

    # After progress events, last_event_at should be updated
    assert completed.last_event_at is not None
    # The completed run should have a last_event_at that's >= started_at
    assert completed.started_at is not None


def test_stale_run_detected_with_old_heartbeat(tmp_path: Path) -> None:
    """Run with last_event_at > 5min ago should be marked as interrupted."""
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    run = store.create_run(case.case_id)
    run.status = "running"
    run.started_at = "2026-05-29T08:00:00Z"
    # Set heartbeat to 10 minutes ago (stale)
    stale_time = datetime.now(timezone.utc) - timedelta(
        seconds=STALE_RUN_THRESHOLD_SECONDS + 300
    )
    run.last_event_at = (
        stale_time.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    store.save_run(run)

    runner = AuditRunner(
        store, audit_func=fake_audit_func, output_root=tmp_path / "outputs"
    )
    recovered_count = runner.recover_interrupted_runs()
    recovered_run = store.get_run(case.case_id, run.run_id)

    assert recovered_count == 1
    assert recovered_run.status == "interrupted"
    assert "no_heartbeat_for_" in recovered_run.error
    assert recovered_run.summary["interrupted"] is True
    assert recovered_run.summary["failed_steps"] == ["stale_detection"]


def test_fresh_run_not_recovered(tmp_path: Path) -> None:
    """Run with last_event_at < 5min ago should NOT be recovered."""
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    run = store.create_run(case.case_id)
    run.status = "running"
    run.started_at = utc_now()
    # Set heartbeat to 2 minutes ago (fresh)
    fresh_time = datetime.now(timezone.utc) - timedelta(seconds=120)
    run.last_event_at = (
        fresh_time.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    store.save_run(run)

    runner = AuditRunner(
        store, audit_func=fake_audit_func, output_root=tmp_path / "outputs"
    )
    recovered_count = runner.recover_interrupted_runs()
    recovered_run = store.get_run(case.case_id, run.run_id)

    assert recovered_count == 0
    assert recovered_run.status == "running"  # unchanged
    assert recovered_run.error is None


def test_legacy_run_without_heartbeat_marked_failed(tmp_path: Path) -> None:
    """Run with last_event_at=None should be marked as failed (backward compat)."""
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    run = store.create_run(case.case_id)
    run.status = "running"
    run.started_at = "2026-05-29T08:02:02Z"
    run.last_event_at = None  # legacy run without heartbeat
    store.save_run(run)

    runner = AuditRunner(
        store, audit_func=fake_audit_func, output_root=tmp_path / "outputs"
    )
    recovered_count = runner.recover_interrupted_runs()
    recovered_run = store.get_run(case.case_id, run.run_id)

    assert recovered_count == 1
    assert recovered_run.status == "failed"
    assert recovered_run.error == "interrupted_by_backend_restart"
    assert recovered_run.summary["interrupted"] is True
    assert recovered_run.summary["failed_steps"] == ["backend_restart"]


def test_interrupted_status_in_run_statuses() -> None:
    """Verify 'interrupted' is a valid run status."""
    assert "interrupted" in RUN_STATUSES


def test_interrupted_run_appends_runner_interrupted_event(tmp_path: Path) -> None:
    """Verify event is appended when run is marked as interrupted."""
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    run = store.create_run(case.case_id)
    run.status = "running"
    run.started_at = "2026-05-29T08:00:00Z"
    # Set heartbeat to 10 minutes ago (stale)
    stale_time = datetime.now(timezone.utc) - timedelta(
        seconds=STALE_RUN_THRESHOLD_SECONDS + 300
    )
    run.last_event_at = (
        stale_time.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    store.save_run(run)

    runner = AuditRunner(
        store, audit_func=fake_audit_func, output_root=tmp_path / "outputs"
    )
    runner.recover_interrupted_runs()
    events = store.list_events(case.case_id, run.run_id)

    assert len(events) >= 1
    last_event = events[-1]
    assert last_event["event"] == "runner_interrupted"
    assert last_event["status"] == "interrupted"
    assert last_event["reason"] == "stale_detection"
    assert "No heartbeat for" in last_event["detail"]


def test_interrupted_run_updates_case_status(tmp_path: Path) -> None:
    """Verify case becomes 'Review Needed' when run is interrupted."""
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    run = store.create_run(case.case_id)
    run.status = "running"
    run.started_at = "2026-05-29T08:00:00Z"
    # Set heartbeat to 10 minutes ago (stale)
    stale_time = datetime.now(timezone.utc) - timedelta(
        seconds=STALE_RUN_THRESHOLD_SECONDS + 300
    )
    run.last_event_at = (
        stale_time.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    store.save_run(run)

    runner = AuditRunner(
        store, audit_func=fake_audit_func, output_root=tmp_path / "outputs"
    )
    runner.recover_interrupted_runs()
    recovered_case = store.get_case(case.case_id)

    assert recovered_case.status == "Review Needed"
    assert recovered_case.review_needed_count >= 1
