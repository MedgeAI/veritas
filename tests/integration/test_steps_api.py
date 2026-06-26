"""Integration tests for the /cases/{case_id}/runs/{run_id}/steps API.

Drives the real FastAPI endpoint through the LocalASGITestClient and the
real ``build_steps_list`` / ``summarise_steps`` functions.  Only the
``CaseStore`` (I/O boundary — DB + filesystem) is replaced with an
in-memory stub so the test exercises the real service logic:

    HTTP endpoint -> CaseStore.list_events -> build_steps_list
                                            -> summarise_steps
                                            -> response
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers.asgi_client import LocalASGITestClient as TestClient
from web.backend.veritas_web.auth import NoAuthProvider
from web.backend.veritas_web.dependencies import AppDependencies, get_app_dependencies
from web.backend.veritas_web.models import CaseRecord
from web.backend.veritas_web.routers import cases as cases_router


# ---------------------------------------------------------------------------
# Stub CaseStore — in-memory, only the methods the endpoint touches.
# ---------------------------------------------------------------------------


class _StubCaseStore:
    """Minimal CaseStore stub that serves events from memory.

    No core logic is mocked: the endpoint runs the real
    ``build_steps_list`` / ``summarise_steps`` on the events returned.
    """

    def __init__(
        self,
        case: CaseRecord,
        events_by_run: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self._case = case
        self._events_by_run = dict(events_by_run or {})

    def get_case(self, case_id: str, user_id: str | None = None) -> CaseRecord:
        if case_id != self._case.case_id:
            raise FileNotFoundError(case_id)
        return self._case

    def list_events(self, case_id: str, run_id: str) -> list[dict[str, Any]]:
        return list(self._events_by_run.get(run_id, []))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_app(store: _StubCaseStore) -> Any:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(cases_router.router, prefix="/api")

    deps = AppDependencies(
        store=store,  # type: ignore[arg-type]
        auth_provider=NoAuthProvider(),
        engine=None,
    )

    async def _override_deps() -> AppDependencies:
        return deps

    app.dependency_overrides[get_app_dependencies] = _override_deps
    return app


def _make_case(case_id: str = "case-1") -> CaseRecord:
    return CaseRecord(
        case_id=case_id,
        paper_title="Test Paper",
        owner="operator",
        status="Uploaded",
        input_count=1,
        technical_risk="unknown",
        review_needed_count=0,
        latest_run_id=None,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetRunSteps:
    """Tests for GET /api/cases/{case_id}/runs/{run_id}/steps."""

    def test_empty_events_returns_zero_summary(self):
        """A run with no events returns an empty step list and zero summary."""
        case = _make_case()
        store = _StubCaseStore(case, events_by_run={"run-1": []})
        app = _build_app(store)
        client = TestClient(app)

        resp = client.get("/api/cases/case-1/runs/run-1/steps")

        assert resp.status_code == 200
        body = resp.json()
        assert body["steps"] == []
        assert body["total"] == 0
        assert body["completed"] == 0
        assert body["running"] == 0
        assert body["failed"] == 0
        assert body["skipped"] == 0
        assert body["progress_pct"] == 0

    def test_completed_pipeline_returns_phases_and_summary(self):
        """A realistic mix of completed/running/failed steps produces the
        expected summary via the REAL ``build_steps_list`` logic."""
        events = [
            # Phase 1: 准备 — completed
            {"event": "step_start", "key": "discover", "timestamp": "2026-06-26T00:00:00Z"},
            {"event": "step_result", "key": "discover", "status": "ran", "timestamp": "2026-06-26T00:00:05Z"},
            {"event": "step_start", "key": "figure_classification", "timestamp": "2026-06-26T00:00:06Z"},
            {"event": "step_result", "key": "figure_classification", "status": "ran", "timestamp": "2026-06-26T00:00:15Z"},
            # Phase 2: 文档解析 — one completed, one running
            {"event": "step_start", "key": "mineru", "timestamp": "2026-06-26T00:01:00Z"},
            {"event": "step_result", "key": "mineru", "status": "ran", "timestamp": "2026-06-26T00:03:00Z"},
            {"event": "step_start", "key": "evidence_ledger", "timestamp": "2026-06-26T00:03:05Z"},
            # Phase 3: 数值取证 — failed
            {"event": "step_start", "key": "numeric_forensics", "timestamp": "2026-06-26T00:05:00Z"},
            {"event": "step_result", "key": "numeric_forensics", "status": "failed", "timestamp": "2026-06-26T00:06:00Z"},
            # Phase 5: 视觉取证 — skipped
            {"event": "step_start", "key": "visual_tru_for", "timestamp": "2026-06-26T00:07:00Z"},
            {"event": "step_result", "key": "visual_tru_for", "status": "skipped", "timestamp": "2026-06-26T00:07:01Z"},
        ]
        case = _make_case()
        store = _StubCaseStore(case, events_by_run={"run-1": events})
        app = _build_app(store)
        client = TestClient(app)

        resp = client.get("/api/cases/case-1/runs/run-1/steps")

        assert resp.status_code == 200
        body = resp.json()

        # Step count
        assert len(body["steps"]) == 6
        assert body["total"] == 6
        assert body["completed"] == 3  # discover, figure_classification, mineru
        assert body["running"] == 1    # evidence_ledger
        assert body["failed"] == 1     # numeric_forensics
        assert body["skipped"] == 1    # visual_tru_for
        assert body["progress_pct"] == 50  # 3/6

        # Phase labels come from the REAL step_labels mapping.
        phases = {s["key"]: (s["phase"], s["phase_order"]) for s in body["steps"]}
        assert phases["discover"] == ("准备", 1)
        assert phases["figure_classification"] == ("准备", 1)
        assert phases["mineru"] == ("文档解析", 2)
        assert phases["evidence_ledger"] == ("文档解析", 2)
        assert phases["numeric_forensics"] == ("数值取证", 3)
        assert phases["visual_tru_for"] == ("视觉取证", 5)

        # Durations computed from real timestamps.
        durations = {s["key"]: s["duration_seconds"] for s in body["steps"]}
        assert durations["discover"] == 5.0
        assert durations["figure_classification"] == 9.0
        assert durations["mineru"] == 120.0
        assert durations["numeric_forensics"] == 60.0
        assert durations["visual_tru_for"] == 1.0
        assert durations["evidence_ledger"] is None  # running

    def test_unknown_step_key_gets_fallback_label(self):
        """An unknown step key falls back through the real ``get_step_label``."""
        events = [
            {"event": "step_start", "key": "future_step_xyz", "timestamp": "2026-06-26T00:00:00Z"},
            {"event": "step_result", "key": "future_step_xyz", "status": "ran", "timestamp": "2026-06-26T00:00:02Z"},
        ]
        case = _make_case()
        store = _StubCaseStore(case, events_by_run={"run-1": events})
        app = _build_app(store)
        client = TestClient(app)

        resp = client.get("/api/cases/case-1/runs/run-1/steps")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["steps"]) == 1
        step = body["steps"][0]
        # Fallback title is generated from the key.
        assert step["title"] == "Future Step Xyz"
        assert step["phase"] == "Unknown"
        assert step["phase_order"] == 99

    def test_run_not_found_returns_empty_steps(self):
        """A run_id with no recorded events returns an empty step list.

        The endpoint uses ``list_events`` which returns [] for unknown runs,
        so the response is still 200 with zero summary.
        """
        case = _make_case()
        store = _StubCaseStore(case, events_by_run={})
        app = _build_app(store)
        client = TestClient(app)

        resp = client.get("/api/cases/case-1/runs/nonexistent/steps")

        assert resp.status_code == 200
        body = resp.json()
        assert body["steps"] == []
        assert body["total"] == 0

    def test_case_not_found_returns_404(self):
        """Requesting steps for an unknown case returns 404."""
        store = _StubCaseStore(_make_case("real-case"), events_by_run={})
        app = _build_app(store)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/api/cases/missing-case/runs/run-1/steps")

        assert resp.status_code == 404

    def test_non_step_events_are_ignored(self):
        """Progress / heartbeat events do not appear in the step list."""
        events = [
            {"event": "step_start", "key": "discover", "timestamp": "2026-06-26T00:00:00Z"},
            {"event": "progress", "key": "discover", "percent": 50, "timestamp": "2026-06-26T00:00:02Z"},
            {"event": "heartbeat", "timestamp": "2026-06-26T00:00:03Z"},
            {"event": "step_result", "key": "discover", "status": "ran", "timestamp": "2026-06-26T00:00:05Z"},
        ]
        case = _make_case()
        store = _StubCaseStore(case, events_by_run={"run-1": events})
        app = _build_app(store)
        client = TestClient(app)

        resp = client.get("/api/cases/case-1/runs/run-1/steps")

        body = resp.json()
        assert len(body["steps"]) == 1
        assert body["steps"][0]["key"] == "discover"
        assert body["steps"][0]["status"] == "completed"
