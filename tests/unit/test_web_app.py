from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from tests.helpers.asgi_client import LocalASGITestClient as TestClient
from web.backend.veritas_web.app import create_app
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

    resp = client.post("/api/cases/demo-case/runs", json={"agent_mode": "review"})
    assert resp.status_code == 202
    run_data = resp.json()
    run_id = run_data["run_id"]

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

    resp = client.post("/api/cases/paper2_zhanglab/runs", json={"agent_mode": "review"})
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    resp = client.get(f"/api/cases/paper2_zhanglab/runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == "paper2_zhanglab"
    assert data["run_id"] == run_id


def test_tool_catalog_uses_app_database_session(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url=db_url,
    )
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/tools/catalog")

    assert resp.status_code == 200
    tools = resp.json()["tools"]
    assert tools
    assert all(tool["agent_selectable"] and tool["deterministic"] for tool in tools)


def test_app_dependencies_are_isolated_per_fastapi_app(tmp_path: Path) -> None:
    app1 = create_app(
        data_root=tmp_path / "web_data_1", output_root=tmp_path / "outputs_1"
    )
    app2 = create_app(
        data_root=tmp_path / "web_data_2", output_root=tmp_path / "outputs_2"
    )
    client1 = TestClient(app1, raise_server_exceptions=False)
    client2 = TestClient(app2, raise_server_exceptions=False)

    resp = client1.post(
        "/api/cases", json={"case_id": "case-one", "paper_title": "One"}
    )
    assert resp.status_code == 201
    resp = client2.post(
        "/api/cases", json={"case_id": "case-two", "paper_title": "Two"}
    )
    assert resp.status_code == 201

    resp = client1.get("/api/cases")

    assert resp.status_code == 200
    assert [case["case_id"] for case in resp.json()["cases"]] == ["case-one"]


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
    assert "sscd_model_available" in data
    assert set(data["details"]) == {"docker", "gpu", "sscd_model_path"}


def test_review_decision_rejects_invalid_status(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url=db_url,
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


def test_embedding_endpoints_return_503_without_database_session(
    tmp_path: Path,
) -> None:
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/cases", json={"case_id": "embedding-case", "paper_title": "Test"}
    )
    assert resp.status_code == 201
    app.state.dependencies._session_factory = None

    for path in (
        "/api/cases/embedding-case/embeddings/status",
        "/api/cases/embedding-case/similarity?panel_id=P1",
        "/api/cases/embedding-case/similarity/pairs",
    ):
        resp = client.get(path)
        assert resp.status_code == 503
        assert resp.json()["detail"]["error"] == "database_unavailable"


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
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"

    # First app: create a run and mark it as running
    app1 = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url=db_url,
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

    # Second app: should recover the stale run (shares same DB file)
    app2 = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url=db_url,
    )
    client2 = TestClient(app2, raise_server_exceptions=False)

    resp = client2.get(f"/api/cases/demo-case/runs/{run.run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"
    assert resp.json()["error"] == "interrupted_by_backend_restart"
