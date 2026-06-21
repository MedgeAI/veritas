from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from web.backend.veritas_web.artifacts import ArtifactService
from web.backend.veritas_web.case_store import CaseStore
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
        "<html>Veritas 静态审查 Demo</html>", encoding="utf-8"
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


def test_runner_calls_audit_function_and_indexes_report(tmp_path) -> None:
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    store.write_input(case.case_id, "paper.pdf", b"%PDF-1.4\n")
    run = store.create_run(case.case_id)
    runner = AuditRunner(
        store, audit_func=fake_audit_func, output_root=tmp_path / "outputs"
    )

    completed = runner.run_sync(case.case_id, run.run_id, {"agent_mode": "review"})
    artifacts = ArtifactService(store).list_artifacts(case.case_id)
    html_ref = next(ref for ref in artifacts if ref.artifact_id == "final_html_report")

    assert completed.status == "completed"
    assert store.get_case(case.case_id).status == "Report Ready"
    assert [
        event["event"] for event in store.list_events(case.case_id, run.run_id)
    ] == ["audit_start", "audit_end"]
    assert html_ref.exists is True
    assert html_ref.size_bytes == len(
        "<html>Veritas 静态审查 Demo</html>".encode("utf-8")
    )
    assert html_ref.updated_at


def test_runner_updates_case_risk_from_static_audit_bundle(tmp_path) -> None:
    def audit_with_findings(paper_dir: Path, **kwargs: Any) -> dict[str, Any]:
        case_id = kwargs["case_id"]
        output_root = Path(kwargs["output_root"])
        workdir = output_root / case_id / "research-integrity-audit"
        reports_dir = workdir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "audit_run_manifest.json").write_text(
            '{"steps":[]}\n', encoding="utf-8"
        )
        bundle = {
            "protocol_version": "test",
            "findings": [
                {
                    "finding_id": "CONS-1",
                    "issue_category": "consistency",
                    "risk_level": "high",
                    "category": "duplicate_numeric_columns",
                    "summary": "duplicate columns",
                },
                {
                    "finding_id": "COMP-1",
                    "issue_category": "completeness",
                    "risk_level": "critical",
                    "category": "source_data_missing",
                    "summary": "source data missing",
                },
                {
                    "finding_id": "LOW-1",
                    "issue_category": "matching",
                    "risk_level": "low",
                    "category": "claim_mismatch",
                    "summary": "weak signal",
                },
            ],
        }
        (reports_dir / "static_audit_bundle.json").write_text(
            json.dumps(bundle), encoding="utf-8"
        )
        (reports_dir / "final_audit_report.html").write_text(
            "<html>report</html>", encoding="utf-8"
        )
        return {
            "exit_code": 0,
            "case_id": case_id,
            "workdir": str(workdir),
            "final_html_report": str(reports_dir / "final_audit_report.html"),
            "run_manifest": str(reports_dir / "audit_run_manifest.json"),
            "static_audit_bundle": str(reports_dir / "static_audit_bundle.json"),
            "failed_steps": [],
        }

    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="risk-case")
    store.write_input(case.case_id, "paper.pdf", b"%PDF-1.4\n")
    run = store.create_run(case.case_id)
    runner = AuditRunner(
        store, audit_func=audit_with_findings, output_root=tmp_path / "outputs"
    )

    completed = runner.run_sync(case.case_id, run.run_id, {"agent_mode": "review"})
    updated_case = store.get_case(case.case_id)

    assert completed.status == "completed"
    assert updated_case.status == "Review Needed"
    assert updated_case.technical_risk == "critical"
    assert updated_case.review_needed_count == 2


def test_runner_recovers_interrupted_thread_runs_on_backend_startup(tmp_path) -> None:
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    run = store.create_run(case.case_id)
    run.status = "running"
    run.started_at = "2026-05-29T08:02:02Z"
    store.save_run(run)
    workdir = tmp_path / "outputs" / case.case_id / "research-integrity-audit"
    workdir.mkdir(parents=True)

    recovered_count = AuditRunner(
        store, audit_func=fake_audit_func, output_root=tmp_path / "outputs"
    ).recover_interrupted_runs()
    recovered_run = store.get_run(case.case_id, run.run_id)
    recovered_case = store.get_case(case.case_id)
    events = store.list_events(case.case_id, run.run_id)

    assert recovered_count == 1
    assert recovered_run.status == "failed"
    assert recovered_run.error == "interrupted_by_backend_restart"
    assert recovered_run.summary["interrupted"] is True
    assert recovered_run.workdir == str(workdir)
    assert recovered_case.status == "Review Needed"
    assert events[-1]["event"] == "runner_interrupted"
