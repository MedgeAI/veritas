"""Tests for web backend modules.

Merged from: test_web_{app,case_store,runner,investigations,visual_endpoints}.
"""

from __future__ import annotations

from pathlib import Path
from tests.helpers.asgi_client import LocalASGITestClient as TestClient
from typing import Any
import base64
import json
import pytest

from engine.static_audit.investigation import read_investigation_records
from engine.static_audit.paths import resolve_artifact_path
from engine.tools.registry import TOOL_ID_SILA_DENSE
from web.backend.veritas_web.app import VeritasWebApp
from web.backend.veritas_web.app import create_app
from web.backend.veritas_web.artifacts import ArtifactService
from web.backend.veritas_web.case_store import CaseStore
from web.backend.veritas_web.database import (
    Base,
    create_db_engine,
    create_session_factory,
)
from web.backend.veritas_web.models import normalize_case_status, normalize_run_status
from web.backend.veritas_web.runner import AuditRunner


# ===========================================================================
# test_web_app.py
# ===========================================================================


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


def test_fastapi_app_runs_web_audit_flow(tmp_path: Path) -> None:
    """Verify the FastAPI app can run an audit end-to-end via TestClient."""
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)

    # Create case and upload input
    resp = client.post(
        "/api/cases", json={"case_id": "demo-case", "paper_title": "Test"}
    )
    assert resp.status_code == 201

    resp = client.post(
        "/api/cases/demo-case/inputs",
        json={
            "filename": "paper.pdf",
            "content_base64": base64.b64encode(b"%PDF-1.4\n").decode("ascii"),
        },
    )
    assert resp.status_code == 200

    # Start a run (uses the real runner with fake audit func — but we can't easily
    # inject the fake here without restructuring.  Instead, test the data flow.)
    deps = app.state.dependencies
    deps.runner = AuditRunner(
        deps.store, audit_func=fake_audit_func, output_root=str(tmp_path / "outputs")
    )

    resp = client.post(
        "/api/audit",
        json={"case_id": "demo-case", "options": {"agent_mode": "review"}},
    )
    assert resp.status_code == 202
    run_data = resp.json()
    run_id = run_data["job_id"]

    # Wait a moment for the background thread to finish
    import time

    for _ in range(50):
        time.sleep(0.1)
        resp = client.get(f"/api/cases/demo-case/runs/{run_id}")
        if resp.json().get("status") in ("completed", "failed"):
            break

    resp = client.get(f"/api/cases/demo-case/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    # Check events
    resp = client.get(f"/api/cases/demo-case/runs/{run_id}/events")
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert [e["event"] for e in events] == ["audit_start", "audit_end"]

    # Check HTML report
    resp = client.get("/api/cases/demo-case/report/html")
    assert resp.status_code == 200
    assert "Veritas 静态审查 Demo" in resp.text


def test_upload_input_accepts_multipart_form_data(tmp_path: Path) -> None:
    """Verify the upload endpoint accepts multipart/form-data (new path)."""
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post("/api/cases", json={"case_id": "mp-case", "paper_title": "MP"})
    assert resp.status_code == 201

    resp = client.post(
        "/api/cases/mp-case/inputs",
        files={"file": ("paper.pdf", b"%PDF-1.4\nmultipart\n", "application/pdf")},
        data={"relative_path": "source-data/batch-1/paper.pdf"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["path"].endswith("source-data/batch-1/paper.pdf")
    assert data["case"]["input_count"] == 1

    # The file on disk matches what we uploaded
    stored = Path(data["path"]).read_bytes()
    assert stored == b"%PDF-1.4\nmultipart\n"


def test_list_cases_honors_limit_and_offset(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)

    for idx in range(5):
        resp = client.post(
            "/api/cases",
            json={"case_id": f"page-case-{idx}", "paper_title": f"Case {idx}"},
        )
        assert resp.status_code == 201

    resp = client.get("/api/cases?limit=2&offset=1")

    assert resp.status_code == 200
    cases = resp.json()["cases"]
    assert len(cases) == 2


def test_upload_input_sanitizes_multipart_relative_path_traversal(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)
    client.post("/api/cases", json={"case_id": "path-case", "paper_title": "Path"})

    resp = client.post(
        "/api/cases/path-case/inputs",
        files={"file": ("paper.pdf", b"%PDF-1.4\nsafe\n", "application/pdf")},
        data={"relative_path": "../../outside/paper.pdf"},
    )

    assert resp.status_code == 200
    stored = Path(resp.json()["path"]).resolve()
    inputs_dir = app.state.dependencies.store.inputs_dir("path-case").resolve()
    assert stored.is_relative_to(inputs_dir)
    assert stored == inputs_dir / "paper.pdf"
    assert not (tmp_path / "outside" / "paper.pdf").exists()
    assert stored.read_bytes() == b"%PDF-1.4\nsafe\n"


def test_upload_input_sanitizes_absolute_multipart_relative_path(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)
    client.post("/api/cases", json={"case_id": "abs-path-case", "paper_title": "Path"})

    resp = client.post(
        "/api/cases/abs-path-case/inputs",
        files={"file": ("absolute.pdf", b"%PDF-1.4\nabsolute\n", "application/pdf")},
        data={"relative_path": "/tmp/absolute.pdf"},
    )

    assert resp.status_code == 200
    stored = Path(resp.json()["path"]).resolve()
    inputs_dir = app.state.dependencies.store.inputs_dir("abs-path-case").resolve()
    assert stored.is_relative_to(inputs_dir)
    assert stored == inputs_dir / "absolute.pdf"
    assert stored.read_bytes() == b"%PDF-1.4\nabsolute\n"


def test_upload_input_still_accepts_json_base64(tmp_path: Path) -> None:
    """Backward-compat: JSON {content_base64} still works."""
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/cases", json={"case_id": "legacy-case", "paper_title": "Legacy"}
    )
    assert resp.status_code == 201

    resp = client.post(
        "/api/cases/legacy-case/inputs",
        json={
            "filename": "paper.pdf",
            "content_base64": base64.b64encode(b"%PDF-1.4\nlegacy\n").decode("ascii"),
        },
    )
    assert resp.status_code == 200
    stored = Path(resp.json()["path"]).read_bytes()
    assert stored == b"%PDF-1.4\nlegacy\n"


def test_materials_endpoint_detects_common_data_and_nested_env_files(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)
    client.post(
        "/api/cases", json={"case_id": "materials-case", "paper_title": "Materials"}
    )
    deps = app.state.dependencies
    deps.store.write_input("materials-case", "counts.RData", b"rdata")
    deps.store.write_input(
        "materials-case",
        "renv.lock",
        b"{}",
        relative_path="analysis/env/renv.lock",
    )

    resp = client.get("/api/cases/materials-case/materials")

    assert resp.status_code == 200
    data = resp.json()
    assert data["source_data"]["status"] == "ok"
    assert data["source_data"]["count"] == 1
    assert data["environment"]["status"] == "provided"
    assert data["environment"]["files"] == ["inputs/analysis/env/renv.lock"]


def test_risk_summary_missing_bundle_is_unavailable(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)
    client.post(
        "/api/cases", json={"case_id": "empty-risk", "paper_title": "Empty Risk"}
    )

    resp = client.get("/api/cases/empty-risk/risk-summary")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unavailable"
    assert data["overall_risk"] == "unknown"
    assert data["total_findings"] == 0


def test_risk_summary_uses_issue_category_priority_for_top_findings(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)
    client.post(
        "/api/cases", json={"case_id": "risk-order", "paper_title": "Risk Order"}
    )
    deps = app.state.dependencies
    run = deps.store.create_run("risk-order")
    workdir = tmp_path / "outputs" / "risk-order" / "research-integrity-audit"
    reports_dir = workdir / "reports"
    reports_dir.mkdir(parents=True)
    bundle = {
        "findings": [
            {
                "finding_id": "COMP-CRIT",
                "issue_category": "completeness",
                "risk_level": "critical",
                "category": "source_data_missing",
                "summary": "Source Data missing",
                "metadata": {"figure_id": "Fig. 2a"},
            },
            {
                "finding_id": "CONS-HIGH",
                "issue_category": "consistency",
                "risk_level": "high",
                "category": "duplicate_numeric_columns",
                "summary": "Duplicate numeric columns",
                "metadata": {
                    "workbook": "source.xlsx",
                    "sheet": "Fig2",
                    "column_labels": ["E", "G"],
                    "equal_rows": 18,
                    "overlap_rows": 18,
                },
            },
        ]
    }
    (reports_dir / "static_audit_bundle.json").write_text(
        json.dumps(bundle), encoding="utf-8"
    )
    run.status = "completed"
    run.workdir = str(workdir)
    deps.store.save_run(run)
    case = deps.store.get_case("risk-order")
    case.latest_run_id = run.run_id
    deps.store.save_case(case)

    resp = client.get("/api/cases/risk-order/risk-summary")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["overall_risk"] == "critical"
    assert data["high_quality_count"] == 2
    assert [item["finding_id"] for item in data["top_findings"]] == [
        "CONS-HIGH",
        "COMP-CRIT",
    ]
    assert "source.xlsx / Fig2" in data["follow_ups"]["CONS-HIGH"][0]


def test_upload_input_rejects_empty_payload(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)
    client.post("/api/cases", json={"case_id": "empty-case", "paper_title": "E"})

    resp = client.post("/api/cases/empty-case/inputs", json={"filename": "x.pdf"})
    assert resp.status_code == 400


def test_run_detail_route_returns_run_data(tmp_path: Path) -> None:
    """Verify GET /api/cases/{id}/runs/{id} returns correct run data."""
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)
    deps = app.state.dependencies
    deps.runner = AuditRunner(
        deps.store, audit_func=fake_audit_func, output_root=str(tmp_path / "outputs")
    )

    resp = client.post(
        "/api/cases", json={"case_id": "paper2_zhanglab", "paper_title": "Test"}
    )
    assert resp.status_code == 201

    resp = client.post(
        "/api/cases/paper2_zhanglab/inputs",
        json={
            "filename": "paper.pdf",
            "content_base64": base64.b64encode(b"%PDF-1.4\n").decode("ascii"),
        },
    )
    assert resp.status_code == 200

    resp = client.post(
        "/api/audit",
        json={"case_id": "paper2_zhanglab", "options": {"agent_mode": "review"}},
    )
    assert resp.status_code == 202
    run_id = resp.json()["job_id"]

    resp = client.get(f"/api/cases/paper2_zhanglab/runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == "paper2_zhanglab"
    assert data["run_id"] == run_id


def test_tool_catalog_uses_app_database_session(tmp_path: Path) -> None:
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
    )
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/tools/catalog")

    assert resp.status_code == 200
    tools = resp.json()["tools"]
    assert tools
    assert all(tool["agent_selectable"] and tool["deterministic"] for tool in tools)


def test_app_dependencies_are_isolated_per_fastapi_app(tmp_path: Path) -> None:
    """Two FastAPI apps get separate AppDependencies (separate data roots)."""
    from web.backend.veritas_web.database import get_database_url

    db_url = get_database_url()
    app1 = create_app(
        data_root=tmp_path / "web_data_1",
        output_root=tmp_path / "outputs_1",
        database_url=db_url,
    )
    app2 = create_app(
        data_root=tmp_path / "web_data_2",
        output_root=tmp_path / "outputs_2",
        database_url=db_url,
    )
    # Each app has its own AppDependencies instance.
    deps1 = app1.state.dependencies
    deps2 = app2.state.dependencies
    assert deps1 is not deps2
    assert deps1.store is not deps2.store


def test_tools_health_reports_probe_results(tmp_path: Path) -> None:
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
    )
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/tools/health")

    assert resp.status_code == 200
    data = resp.json()
    assert "docker_available" in data
    assert "gpu_available" in data
    assert set(data["details"]) == {"docker", "gpu"}


def test_review_decision_rejects_invalid_status(tmp_path: Path) -> None:
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
    )
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/cases", json={"case_id": "review-case", "paper_title": "Test"}
    )
    assert resp.status_code == 201

    resp = client.post(
        "/api/cases/review-case/review-items/finding-1/decision",
        json={"status": "made_up_status", "note": "invalid"},
    )

    assert resp.status_code == 422


def test_review_items_missing_workdir_returns_404(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/cases", json={"case_id": "review-empty", "paper_title": "Test"}
    )
    assert resp.status_code == 201

    resp = client.get("/api/cases/review-empty/review-items")

    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "audit_workdir_missing"


def test_review_items_return_503_without_database_session(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/cases", json={"case_id": "review-db", "paper_title": "Test"}
    )
    assert resp.status_code == 201
    deps = app.state.dependencies
    run = deps.store.create_run("review-db")
    workdir = tmp_path / "outputs" / "review-db" / "research-integrity-audit"
    workdir.mkdir(parents=True)
    run.status = "completed"
    run.workdir = str(workdir)
    deps.store.save_run(run)
    deps._session_factory = None

    resp = client.get("/api/cases/review-db/review-items")

    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "database_unavailable"


def test_web_app_marks_stale_runs_failed_on_startup(tmp_path: Path) -> None:
    """Verify stale runs are recovered on app startup."""
    # First app: create a run and mark it as running.
    app1 = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
    )
    client1 = TestClient(app1, raise_server_exceptions=False)

    resp = client1.post(
        "/api/cases", json={"case_id": "demo-case", "paper_title": "Test"}
    )
    assert resp.status_code == 201

    deps = app1.state.dependencies
    run = deps.store.create_run("demo-case")
    run.status = "running"
    deps.store.save_run(run)

    # Second app: should recover the stale run (shares the same DB).
    app2 = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
    )
    client2 = TestClient(app2, raise_server_exceptions=False)

    resp = client2.get(f"/api/cases/demo-case/runs/{run.run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"
    assert resp.json()["error"] == "interrupted_by_backend_restart"


# ===========================================================================
# test_web_case_store.py
# ===========================================================================


def test_case_store_creates_case_and_input(tmp_path) -> None:
    store = CaseStore(tmp_path / "web_data")

    case = store.create_case(
        paper_title="Demo paper", user_id="operator", case_id="demo-case"
    )
    input_path = store.write_input(case.case_id, "paper.pdf", b"%PDF-1.4\n")
    loaded = store.get_case(case.case_id)

    assert case.case_id == "demo-case"
    assert input_path.name == "paper.pdf"
    assert loaded.status == "Uploaded"
    assert loaded.input_count == 1


def test_case_store_records_run_events(tmp_path) -> None:
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    run = store.create_run(case.case_id)

    store.append_event(
        case.case_id, run.run_id, {"event": "audit_start", "case_id": case.case_id}
    )
    store.append_event(
        case.case_id, run.run_id, {"event": "audit_end", "status": "completed"}
    )

    assert [
        event["event"] for event in store.list_events(case.case_id, run.run_id)
    ] == ["audit_start", "audit_end"]


def test_case_store_lists_runs(tmp_path) -> None:
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    first = store.create_run(case.case_id)
    second = store.create_run(case.case_id)

    assert {run.run_id for run in store.list_runs(case.case_id)} == {
        first.run_id,
        second.run_id,
    }
    assert {run.run_id for run in store.list_all_runs()} == {
        first.run_id,
        second.run_id,
    }


def test_status_normalizers_reject_invalid_values() -> None:
    assert normalize_case_status("Draft") == "Draft"
    assert normalize_run_status("queued") == "queued"

    with pytest.raises(ValueError, match="invalid case status"):
        normalize_case_status("completed_typo")

    with pytest.raises(ValueError, match="invalid run status"):
        normalize_run_status("running_typo")


# ===========================================================================
# test_web_runner.py
# ===========================================================================


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


# ===========================================================================
# test_web_investigations.py
# ===========================================================================


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def setup_case_workdir(app: VeritasWebApp, case_id: str) -> Path:
    case = app.store.create_case(case_id=case_id)
    run = app.store.create_run(case.case_id)
    workdir = Path(app.runner.output_root) / case_id / "research-integrity-audit"
    run.workdir = str(workdir)
    app.store.save_run(run)
    write_json(
        resolve_artifact_path(workdir, "panel_evidence.json"),
        {
            "schema_version": "1.0",
            "panels": [
                {
                    "panel_id": "P1",
                    "parent_figure_id": "F1",
                    "crop_path": "visual/panels/F1/a.png",
                },
                {
                    "panel_id": "P2",
                    "parent_figure_id": "F1",
                    "crop_path": "visual/panels/F1/b.png",
                },
            ],
        },
    )
    write_json(
        resolve_artifact_path(workdir, "visual_evidence.json"),
        {
            "schema_version": "1.0",
            "figures": [
                {"figure_id": "F1", "source_image_path": "visual/images/F1.png"}
            ],
        },
    )
    return workdir


def test_web_investigation_runs_dense_on_selected_panels(tmp_path, monkeypatch) -> None:
    app = VeritasWebApp(
        data_root=tmp_path / "web_data", output_root=tmp_path / "outputs"
    )
    workdir = setup_case_workdir(app, "case-investigation")
    captured: dict[str, Any] = {}

    def fake_detect(panel_evidence, figure_evidence, **kwargs):
        captured["panel_ids"] = [panel["panel_id"] for panel in panel_evidence]
        captured["output_base"] = kwargs["output_base"]
        return {
            "schema_version": "1.0",
            "created_by": "fake",
            "status": "ran",
            "failure_category": None,
            "panel_count": len(panel_evidence),
            "relationship_count": 1,
            "relationships": [
                {
                    "relationship_id": "IR-SILA-0001",
                    "source_type": "copy_move_single",
                    "source_panel_id": "P1",
                    "target_panel_id": "P1",
                    "score": 0.8,
                    "match_method": "sila_dense_single",
                    "inlier_count": 0,
                    "metadata": {
                        "mask_path": "investigation/web/action/sila_dense/P1/a_mask.png"
                    },
                }
            ],
            "errors": [],
            "limitations": [],
        }

    monkeypatch.setattr(
        "web.backend.veritas_web.investigations.detect_sila_dense", fake_detect
    )

    result = app.investigations.run_investigation(
        "case-investigation",
        {
            "tool_id": TOOL_ID_SILA_DENSE,
            "panel_ids": ["P1", "P2"],
            "params": {"max_panels": 1, "max_relationships": 10},
        },
    )

    assert captured["panel_ids"] == ["P1"]
    assert "/investigation/web/" in str(captured["output_base"])
    assert result["result"]["metadata"]["selected_panel_ids"] == ["P1"]
    assert Path(workdir / result["artifact"]).exists()
    records = read_investigation_records(workdir)
    assert records[-1]["tool_id"] == TOOL_ID_SILA_DENSE
    assert records[-1]["metadata"]["trigger"] == "web_manual"


def test_web_investigation_rejects_unknown_panel(tmp_path) -> None:
    app = VeritasWebApp(
        data_root=tmp_path / "web_data", output_root=tmp_path / "outputs"
    )
    setup_case_workdir(app, "case-missing-panel")

    with pytest.raises(ValueError, match="unknown panel_id"):
        app.investigations.run_investigation(
            "case-missing-panel",
            {"tool_id": TOOL_ID_SILA_DENSE, "panel_ids": ["P404"]},
        )


def test_web_investigation_list_loads_result_payload(tmp_path, monkeypatch) -> None:
    app = VeritasWebApp(
        data_root=tmp_path / "web_data", output_root=tmp_path / "outputs"
    )
    setup_case_workdir(app, "case-list-investigation")

    monkeypatch.setattr(
        "web.backend.veritas_web.investigations.detect_sila_dense",
        lambda panel_evidence, figure_evidence, **kwargs: {
            "schema_version": "1.0",
            "created_by": "fake",
            "status": "ran",
            "failure_category": None,
            "panel_count": len(panel_evidence),
            "relationship_count": 0,
            "relationships": [],
            "errors": [],
            "limitations": ["none"],
        },
    )
    app.investigations.run_investigation(
        "case-list-investigation", {"panel_ids": ["P1"]}
    )

    listing = app.investigations.list_investigations("case-list-investigation")

    assert len(listing["records"]) == 1
    assert len(listing["results"]) == 1
    assert listing["artifact_errors"] == []
    assert listing["results"][0]["result"]["status"] == "ran"


def test_web_investigation_db_write_failure_returns_partial_success(
    tmp_path, monkeypatch
) -> None:
    app = VeritasWebApp(
        data_root=tmp_path / "web_data", output_root=tmp_path / "outputs"
    )
    workdir = setup_case_workdir(app, "case-db-failure")

    monkeypatch.setattr(
        "web.backend.veritas_web.investigations.detect_sila_dense",
        lambda panel_evidence, figure_evidence, **kwargs: {
            "schema_version": "1.0",
            "created_by": "fake",
            "status": "ran",
            "failure_category": None,
            "panel_count": len(panel_evidence),
            "relationship_count": 0,
            "relationships": [],
            "errors": [],
            "limitations": [],
        },
    )

    class BrokenSession:
        def add(self, _model) -> None:
            pass

        def commit(self) -> None:
            raise RuntimeError("db commit failed")

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(app.store, "_session", lambda: BrokenSession())
    monkeypatch.setattr(
        app.investigations, "_require_workdir", lambda _case_id: workdir
    )

    result = app.investigations.run_investigation(
        "case-db-failure", {"panel_ids": ["P1"]}
    )

    assert result["result"]["status"] == "ran"
    assert "failed to persist investigation record" in result["db_sync_error"]
    records = read_investigation_records(workdir)
    assert len(records) == 1


def test_web_investigation_list_reports_missing_result_artifact(
    tmp_path, monkeypatch
) -> None:
    app = VeritasWebApp(
        data_root=tmp_path / "web_data", output_root=tmp_path / "outputs"
    )
    workdir = setup_case_workdir(app, "case-missing-artifact")

    monkeypatch.setattr(
        "web.backend.veritas_web.investigations.detect_sila_dense",
        lambda panel_evidence, figure_evidence, **kwargs: {
            "schema_version": "1.0",
            "created_by": "fake",
            "status": "ran",
            "failure_category": None,
            "panel_count": len(panel_evidence),
            "relationship_count": 0,
            "relationships": [],
            "errors": [],
            "limitations": [],
        },
    )
    result = app.investigations.run_investigation(
        "case-missing-artifact", {"panel_ids": ["P1"]}
    )
    (workdir / result["artifact"]).unlink()

    listing = app.investigations.list_investigations("case-missing-artifact")

    assert len(listing["records"]) == 1
    assert listing["results"] == []
    assert listing["artifact_errors"][0]["error"] == "artifact_missing"
    assert listing["records"][0]["artifact_errors"][0]["artifact"] == result["artifact"]


def test_web_investigation_list_reports_invalid_json_artifact(
    tmp_path, monkeypatch
) -> None:
    app = VeritasWebApp(
        data_root=tmp_path / "web_data", output_root=tmp_path / "outputs"
    )
    workdir = setup_case_workdir(app, "case-invalid-artifact")

    monkeypatch.setattr(
        "web.backend.veritas_web.investigations.detect_sila_dense",
        lambda panel_evidence, figure_evidence, **kwargs: {
            "schema_version": "1.0",
            "created_by": "fake",
            "status": "ran",
            "failure_category": None,
            "panel_count": len(panel_evidence),
            "relationship_count": 0,
            "relationships": [],
            "errors": [],
            "limitations": [],
        },
    )
    result = app.investigations.run_investigation(
        "case-invalid-artifact", {"panel_ids": ["P1"]}
    )
    (workdir / result["artifact"]).write_text("{bad json", encoding="utf-8")

    listing = app.investigations.list_investigations("case-invalid-artifact")

    assert listing["results"] == []
    assert listing["artifact_errors"][0]["error"] == "artifact_invalid_json"


# ===========================================================================
# test_web_visual_endpoints.py
# ===========================================================================


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def setup_case_with_visual_artifacts(
    tmp_path: Path, case_id: str
) -> tuple[TestClient, Path]:
    """Create a case with visual artifacts and return (client, workdir)."""
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)

    # Create case and run
    resp = client.post("/api/cases", json={"case_id": case_id, "paper_title": "Test"})
    assert resp.status_code == 201

    deps = app.state.dependencies
    run = deps.store.create_run(case_id)
    workdir = Path(deps.runner.output_root) / case_id / "research-integrity-audit"
    run.workdir = str(workdir)
    deps.store.save_run(run)
    workdir.mkdir(parents=True, exist_ok=True)

    # Write visual artifacts
    write_json(
        workdir / "visual_evidence.json",
        {
            "version": "1.0",
            "figures": [
                {
                    "figure_id": "FE-0001",
                    "source_image_path": "images/Figure1.png",
                    "label": "Figure 1",
                    "caption": "Test figure",
                    "page_number": 1,
                    "bbox": None,
                    "width": 100,
                    "height": 100,
                    "panel_count": 2,
                }
            ],
        },
    )
    write_json(
        workdir / "panel_evidence.json",
        {
            "version": "1.0",
            "panels": [
                {
                    "panel_id": "PE-0001-01",
                    "parent_figure_id": "FE-0001",
                    "label": "a",
                    "bbox": [0, 0, 50, 100],
                    "crop_path": "panels/PE-0001-01.png",
                    "width": 50,
                    "height": 100,
                    "extraction_confidence": 0.85,
                    "extraction_method": "contour_edge_detection",
                }
            ],
        },
    )
    write_json(
        workdir / "image_relationships.json",
        {
            "version": "1.0",
            "relationships": [
                {
                    "relationship_id": "IR-0001",
                    "source_type": "copy_move_single",
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-02",
                    "score": 0.85,
                    "match_method": "orb_ransac",
                    "inlier_count": 42,
                }
            ],
        },
    )
    write_json(
        workdir / "visual_findings.json",
        {
            "version": "1.0",
            "findings": [
                {
                    "finding_id": "VF-0001",
                    "category": "copy_move_single",
                    "risk_level": "high",
                    "summary": "Test visual finding",
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-02",
                    "relationship_id": "IR-0001",
                    "score": 0.85,
                }
            ],
        },
    )
    return client, workdir


def test_visual_figures_endpoint(tmp_path: Path) -> None:
    client, _ = setup_case_with_visual_artifacts(tmp_path, "visual-case-1")
    resp = client.get("/api/cases/visual-case-1/visual/figures")
    assert resp.status_code == 200
    data = resp.json()
    assert "figures" in data
    assert len(data["figures"]) == 1
    assert data["figures"][0]["figure_id"] == "FE-0001"


def test_visual_panels_endpoint(tmp_path: Path) -> None:
    client, _ = setup_case_with_visual_artifacts(tmp_path, "visual-case-2")
    resp = client.get("/api/cases/visual-case-2/visual/panels")
    assert resp.status_code == 200
    data = resp.json()
    assert "panels" in data
    assert len(data["panels"]) == 1
    assert data["panels"][0]["panel_id"] == "PE-0001-01"


def test_visual_relationships_endpoint(tmp_path: Path) -> None:
    client, _ = setup_case_with_visual_artifacts(tmp_path, "visual-case-3")
    resp = client.get("/api/cases/visual-case-3/visual/relationships")
    assert resp.status_code == 200
    data = resp.json()
    assert "relationships" in data
    assert len(data["relationships"]) == 1
    assert data["relationships"][0]["relationship_id"] == "IR-0001"


def test_visual_findings_endpoint(tmp_path: Path) -> None:
    client, _ = setup_case_with_visual_artifacts(tmp_path, "visual-case-4")
    resp = client.get("/api/cases/visual-case-4/visual/findings")
    assert resp.status_code == 200
    data = resp.json()
    assert "findings" in data
    assert len(data["findings"]) == 1
    assert data["findings"][0]["finding_id"] == "VF-0001"


def test_visual_unknown_type_returns_error(tmp_path: Path) -> None:
    client, _ = setup_case_with_visual_artifacts(tmp_path, "visual-case-5")
    resp = client.get("/api/cases/visual-case-5/visual/unknown")
    assert resp.status_code == 404


def test_visual_image_endpoint(tmp_path: Path) -> None:
    client, workdir = setup_case_with_visual_artifacts(tmp_path, "visual-case-6")
    image_dir = workdir / "panels"
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / "PE-0001-01.png").write_bytes(b"\x89PNG\r\n\x1a\nfake_image_data")

    resp = client.get("/api/cases/visual-case-6/visual/images/panels/PE-0001-01.png")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG\r\n\x1a\nfake_image_data"
    assert "image/png" in resp.headers.get("content-type", "")


def test_visual_image_prevents_path_traversal(tmp_path: Path) -> None:
    """Image endpoint should prevent path traversal attacks.

    Note: httpx (used by TestClient) normalizes URL paths, so ``../``
    sequences are resolved before reaching the server.  We test the
    server-side protection directly via ArtifactService.
    """
    from web.backend.veritas_web.artifacts import ArtifactService
    from web.backend.veritas_web.case_store import CaseStore

    store = CaseStore(tmp_path / "web_data")
    store.create_case(case_id="traversal-case")
    artifacts = ArtifactService(store)

    # Attempt path traversal — should return None
    result = artifacts.visual_image_path("traversal-case", "../../../etc/passwd")
    assert result is None


def test_visual_artifacts_in_known_artifacts() -> None:
    from web.backend.veritas_web.artifacts import KNOWN_ARTIFACTS

    artifact_ids = [a[0] for a in KNOWN_ARTIFACTS]
    assert "visual_evidence" in artifact_ids
    assert "panel_evidence" in artifact_ids
    assert "image_relationships" in artifact_ids
    assert "visual_findings" in artifact_ids
