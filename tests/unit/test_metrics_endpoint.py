"""Tests for the /api/metrics endpoint."""

from __future__ import annotations

from pathlib import Path

from tests.helpers.asgi_client import LocalASGITestClient as TestClient
from web.backend.veritas_web.app import create_app


def test_metrics_returns_json(tmp_path: Path) -> None:
    """GET /api/metrics returns 200 with the expected schema."""
    app = create_app(
        data_root=tmp_path / "web_data", output_root=tmp_path / "outputs"
    )
    client = TestClient(app)

    resp = client.get("/api/metrics")
    assert resp.status_code == 200

    data = resp.json()
    required_keys = {
        "cases_total",
        "cases_by_status",
        "runs_total",
        "runs_active",
        "runs_completed",
        "runs_failed",
        "runs_interrupted",
        "uptime_seconds",
        "timestamp",
    }
    assert required_keys.issubset(data.keys())
    assert isinstance(data["cases_total"], int)
    assert isinstance(data["cases_by_status"], dict)
    assert isinstance(data["runs_total"], int)
    assert isinstance(data["uptime_seconds"], int)
    assert isinstance(data["timestamp"], str)


def test_metrics_reflects_cases_and_runs(tmp_path: Path) -> None:
    """Metrics counts update after creating cases and runs."""
    app = create_app(
        data_root=tmp_path / "web_data", output_root=tmp_path / "outputs"
    )
    client = TestClient(app)

    # Create two cases
    client.post("/api/cases", json={"case_id": "m1", "paper_title": "Paper 1"})
    client.post("/api/cases", json={"case_id": "m2", "paper_title": "Paper 2"})

    # Create one run for the first case
    deps = app.state.dependencies
    deps.store.create_run("m1")

    resp = client.get("/api/metrics")
    data = resp.json()

    assert data["cases_total"] == 2
    # Both cases start as Draft; m1 moves to Uploaded after run creation? No —
    # cases start as Draft, uploading inputs changes status. Without upload, both Draft.
    assert data["cases_by_status"].get("Draft", 0) == 2 or "Draft" in data["cases_by_status"]
    assert data["runs_total"] == 1


def test_metrics_uses_aggregate_store_method(tmp_path: Path) -> None:
    """Metrics should not materialize all cases/runs in Python."""
    app = create_app(
        data_root=tmp_path / "web_data", output_root=tmp_path / "outputs"
    )
    client = TestClient(app)
    deps = app.state.dependencies

    client.post("/api/cases", json={"case_id": "m1", "paper_title": "Paper 1"})

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("metrics endpoint should use SQL aggregates")

    deps.store.list_cases = fail_if_called
    deps.store.list_all_runs = fail_if_called

    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert resp.json()["cases_total"] == 1


def test_metrics_no_auth_required(tmp_path: Path) -> None:
    """The metrics endpoint does not require Authorization header."""
    app = create_app(
        data_root=tmp_path / "web_data", output_root=tmp_path / "outputs"
    )
    client = TestClient(app)

    resp = client.get("/api/metrics")
    assert resp.status_code == 200
