from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from web.backend.veritas_web.app import VeritasRequestHandler, VeritasWebApp
from web.backend.veritas_web.auth import AuthContext
from web.backend.veritas_web.runner import AuditRunner


def fake_audit_func(paper_dir: Path, **kwargs: Any) -> dict[str, Any]:
    case_id = kwargs["case_id"]
    output_root = Path(kwargs["output_root"])
    workdir = output_root / case_id / "research-integrity-audit"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "audit_run_manifest.json").write_text('{"steps":[]}\n', encoding="utf-8")
    (workdir / "static_audit_bundle.json").write_text('{"protocol_version":"test"}\n', encoding="utf-8")
    (workdir / "investigation_rounds.jsonl").write_text("", encoding="utf-8")
    (workdir / "final_audit_report.html").write_text("<html>Veritas 静态审查 Demo</html>", encoding="utf-8")
    progress = kwargs.get("progress")
    if progress:
        progress({"timestamp": "2026-05-29T00:00:00Z", "event": "audit_start", "case_id": case_id})
        progress({"timestamp": "2026-05-29T00:00:01Z", "event": "audit_end", "status": "completed"})
    return {
        "exit_code": 0,
        "case_id": case_id,
        "workdir": str(workdir),
        "final_html_report": str(workdir / "final_audit_report.html"),
        "run_manifest": str(workdir / "audit_run_manifest.json"),
        "static_audit_bundle": str(workdir / "static_audit_bundle.json"),
        "failed_steps": [],
    }


def test_stdlib_app_wiring_runs_web_audit_flow_without_socket(tmp_path) -> None:
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    app.runner = AuditRunner(app.store, audit_func=fake_audit_func, output_root=tmp_path / "outputs")
    case = app.store.create_case(case_id="demo-case")
    app.store.write_input_base64(case.case_id, "paper.pdf", base64.b64encode(b"%PDF-1.4\n").decode("ascii"))
    run = app.store.create_run(case.case_id)

    completed = app.runner.run_sync(case.case_id, run.run_id, {"agent_mode": "review"})
    html_path = app.artifacts.report_html_path(case.case_id)

    assert completed.status == "completed"
    assert [event["event"] for event in app.store.list_events(case.case_id, run.run_id)] == ["audit_start", "audit_end"]
    assert html_path is not None
    assert "Veritas 静态审查 Demo" in html_path.read_text(encoding="utf-8")


def test_run_detail_route_uses_five_path_segments(tmp_path) -> None:
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    case = app.store.create_case(case_id="paper2_zhanglab")
    run = app.store.create_run(case.case_id)
    captured: list[dict[str, Any]] = []

    handler = VeritasRequestHandler.__new__(VeritasRequestHandler)
    handler.app = app
    handler.auth_context = AuthContext(user_id="operator", roles=frozenset({"admin"}))
    handler.path = f"/api/cases/{case.case_id}/runs/{run.run_id}"
    handler._send_json = lambda payload, status=None: captured.append(payload)

    handler._route_get()

    assert captured[0]["case_id"] == case.case_id
    assert captured[0]["run_id"] == run.run_id


def test_web_app_marks_stale_runs_interrupted_on_startup(tmp_path) -> None:
    initial_app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    case = initial_app.store.create_case(case_id="demo-case")
    run = initial_app.store.create_run(case.case_id)
    run.status = "running"
    initial_app.store.save_run(run)

    restarted_app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    recovered_run = restarted_app.store.get_run(case.case_id, run.run_id)

    assert restarted_app.recovered_interrupted_runs == 1
    assert recovered_run.status == "failed"
    assert recovered_run.error == "interrupted_by_backend_restart"
