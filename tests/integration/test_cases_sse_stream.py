"""Integration tests for the cases SSE stream endpoint.

Tests the new ``GET /cases/{case_id}/runs/{run_id}/stream`` endpoint
that provides real-time progress updates for a specific run.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from web.backend.veritas_web.app import create_app
from web.backend.veritas_web.case_store import CaseStore
from web.backend.veritas_web.models import CaseRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_case_store(cases: dict[str, CaseRecord] | None = None) -> CaseStore:
    """Build a minimal CaseStore with mocked case access."""
    store = MagicMock(spec=CaseStore)
    if cases is None:
        cases = {}

    def get_case(case_id: str, user_id: str | None = None) -> CaseRecord:
        if case_id not in cases:
            raise FileNotFoundError(f"case not found: {case_id}")
        case = cases[case_id]
        # Admin (user_id=None) bypasses ownership check
        if user_id is not None and case.owner != user_id:
            raise PermissionError(f"not the owner of case {case_id}")
        return case

    store.get_case.side_effect = get_case
    return store


def _make_case_record(
    case_id: str,
    owner: str = "alice@example.com",
    paper_title: str = "Test Paper",
) -> CaseRecord:
    """Build a minimal CaseRecord."""
    return CaseRecord(
        case_id=case_id,
        paper_title=paper_title,
        owner=owner,
        created_at="2026-06-26T00:00:00Z",
        updated_at="2026-06-26T00:00:00Z",
        status="idle",
        latest_run_id=None,
        review_needed_count=0,
        technical_risk="unknown",
    )


def _make_auth_context(user_id: str, is_admin: bool = False):
    """Build a minimal AuthContext mock."""
    auth = MagicMock()
    auth.user_id = user_id
    auth.is_admin.return_value = is_admin
    return auth


def _make_dependencies(store: CaseStore):
    """Build minimal AppDependencies with mocked internals."""
    from web.backend.veritas_web.dependencies import AppDependencies

    deps = MagicMock(spec=AppDependencies)
    deps.store = store
    deps._engine = None
    return deps


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCasesStreamEndpoint:
    """Tests for GET /cases/{case_id}/runs/{run_id}/stream."""

    def _client(self, store: CaseStore, auth_user_id: str = "alice@example.com", is_admin: bool = False):
        """Build a TestClient with mocked dependencies."""
        from web.backend.veritas_web.dependencies import get_app_dependencies, get_auth_context
        from web.backend.veritas_web.routers.audit_jobs import get_auth_context_sse

        app = create_app()
        app.dependency_overrides[get_app_dependencies] = lambda: _make_dependencies(store)
        app.dependency_overrides[get_auth_context] = lambda: _make_auth_context(auth_user_id, is_admin)
        app.dependency_overrides[get_auth_context_sse] = lambda: _make_auth_context(auth_user_id, is_admin)
        return TestClient(app)

    def test_stream_endpoint_exists(self):
        """Stream endpoint should be reachable."""
        case = _make_case_record("case-1")
        store = _make_case_store({"case-1": case})
        client = self._client(store)

        # Mock the SSE event stream to avoid real DB queries
        import web.backend.veritas_web.routers.cases as cases_module

        async def mock_sse_stream(*args, **kwargs):
            yield "event: completed\ndata: {}\n\n"

        original_func = cases_module.sse_event_stream
        cases_module.sse_event_stream = mock_sse_stream

        try:
            response = client.get(
                "/api/cases/case-1/runs/run-1/stream",
                headers={"Accept": "text/event-stream"},
            )

            # Should be a streaming response (200)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
        finally:
            cases_module.sse_event_stream = original_func

    def test_stream_accepts_last_event_id_header(self):
        """Last-Event-ID header should be accepted for reconnection."""
        case = _make_case_record("case-1")
        store = _make_case_store({"case-1": case})
        client = self._client(store)

        # Mock the SSE event stream and capture the call
        import web.backend.veritas_web.routers.cases as cases_module

        async def mock_sse_stream(*args, **kwargs):
            yield "event: completed\ndata: {}\n\n"

        original_func = cases_module.sse_event_stream
        call_args = {}

        def capture_call(*args, **kwargs):
            call_args.update(kwargs)
            return mock_sse_stream(*args, **kwargs)

        cases_module.sse_event_stream = capture_call

        try:
            response = client.get(
                "/api/cases/case-1/runs/run-1/stream",
                headers={
                    "Accept": "text/event-stream",
                    "Last-Event-ID": "42",
                },
            )

            assert response.status_code == 200
            # Verify sse_event_stream was called with last_event_id
            assert call_args.get("last_event_id") == "42"
        finally:
            cases_module.sse_event_stream = original_func

    def test_stream_validates_events_parameter(self):
        """Invalid events parameter should default to lifecycle."""
        case = _make_case_record("case-1")
        store = _make_case_store({"case-1": case})
        client = self._client(store)

        import web.backend.veritas_web.routers.cases as cases_module

        async def mock_sse_stream(*args, **kwargs):
            yield "event: completed\ndata: {}\n\n"

        original_func = cases_module.sse_event_stream
        call_args = {}

        def capture_call(*args, **kwargs):
            call_args.update(kwargs)
            return mock_sse_stream(*args, **kwargs)

        cases_module.sse_event_stream = capture_call

        try:
            response = client.get(
                "/api/cases/case-1/runs/run-1/stream?events=invalid",
                headers={"Accept": "text/event-stream"},
            )

            assert response.status_code == 200
            assert call_args.get("level") == "lifecycle"
        finally:
            cases_module.sse_event_stream = original_func

    def test_stream_accepts_valid_events_levels(self):
        """Should accept lifecycle, agent, and debug event levels."""
        case = _make_case_record("case-1")
        store = _make_case_store({"case-1": case})

        for level in ("lifecycle", "agent", "debug"):
            client = self._client(store)

            import web.backend.veritas_web.routers.cases as cases_module

            async def mock_sse_stream(*args, **kwargs):
                yield "event: completed\ndata: {}\n\n"

            original_func = cases_module.sse_event_stream
            call_args = {}

            def capture_call(*args, **kwargs):
                call_args.update(kwargs)
                return mock_sse_stream(*args, **kwargs)

            cases_module.sse_event_stream = capture_call

            try:
                response = client.get(
                    f"/api/cases/case-1/runs/run-1/stream?events={level}",
                    headers={"Accept": "text/event-stream"},
                )

                assert response.status_code == 200
                assert call_args.get("level") == level
            finally:
                cases_module.sse_event_stream = original_func

    def test_stream_returns_404_for_missing_case(self):
        """Should return 404 when case does not exist."""
        store = _make_case_store({})  # No cases
        client = self._client(store)

        response = client.get("/api/cases/missing-case/runs/run-1/stream")
        assert response.status_code == 404

    def test_stream_returns_403_for_non_owner(self):
        """Should return 403 when user is not the case owner."""
        case = _make_case_record("case-1", owner="bob@example.com")
        store = _make_case_store({"case-1": case})
        client = self._client(store, auth_user_id="alice@example.com", is_admin=False)

        response = client.get("/api/cases/case-1/runs/run-1/stream")
        assert response.status_code == 403

    def test_stream_admin_bypasses_ownership_check(self):
        """Admin users should bypass ownership checks."""
        case = _make_case_record("case-1", owner="bob@example.com")
        store = _make_case_store({"case-1": case})
        client = self._client(store, auth_user_id="admin@example.com", is_admin=True)

        import web.backend.veritas_web.routers.cases as cases_module

        async def mock_sse_stream(*args, **kwargs):
            yield "event: completed\ndata: {}\n\n"

        original_func = cases_module.sse_event_stream
        cases_module.sse_event_stream = mock_sse_stream

        try:
            response = client.get(
                "/api/cases/case-1/runs/run-1/stream",
                headers={"Accept": "text/event-stream"},
            )

            assert response.status_code == 200
        finally:
            cases_module.sse_event_stream = original_func

    def test_stream_has_correct_media_type(self):
        """Response should have text/event-stream media type."""
        case = _make_case_record("case-1")
        store = _make_case_store({"case-1": case})
        client = self._client(store)

        import web.backend.veritas_web.routers.cases as cases_module

        async def mock_sse_stream(*args, **kwargs):
            yield "event: completed\ndata: {}\n\n"

        original_func = cases_module.sse_event_stream
        cases_module.sse_event_stream = mock_sse_stream

        try:
            response = client.get(
                "/api/cases/case-1/runs/run-1/stream",
                headers={"Accept": "text/event-stream"},
            )

            assert "text/event-stream" in response.headers["content-type"]
        finally:
            cases_module.sse_event_stream = original_func

    def test_stream_has_no_cache_headers(self):
        """Response should have Cache-Control: no-cache."""
        case = _make_case_record("case-1")
        store = _make_case_store({"case-1": case})
        client = self._client(store)

        import web.backend.veritas_web.routers.cases as cases_module

        async def mock_sse_stream(*args, **kwargs):
            yield "event: completed\ndata: {}\n\n"

        original_func = cases_module.sse_event_stream
        cases_module.sse_event_stream = mock_sse_stream

        try:
            response = client.get(
                "/api/cases/case-1/runs/run-1/stream",
                headers={"Accept": "text/event-stream"},
            )

            assert response.headers.get("cache-control") == "no-cache"
        finally:
            cases_module.sse_event_stream = original_func
