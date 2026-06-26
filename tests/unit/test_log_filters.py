"""Tests for log noise-reduction filters (PRD3-T5)."""

from __future__ import annotations

import logging

from web.backend.veritas_web.logging_config import (
    DuplicateDBConnectFilter,
    PollingRequestFilter,
    is_polling_path,
)


# ---------------------------------------------------------------------------
# PollingRequestFilter
# ---------------------------------------------------------------------------

class TestPollingRequestFilter:
    def setup_method(self):
        self.f = PollingRequestFilter()

    def _record(self, msg: str, level: int = logging.INFO) -> logging.LogRecord:
        return logging.LogRecord(
            name="veritas_web.app",
            level=level,
            pathname="",
            lineno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )

    def test_polling_run_info_dropped(self):
        rec = self._record("GET /api/runs/abc123 -> 200 (12.3ms)")
        assert self.f.filter(rec) is False

    def test_polling_events_info_dropped(self):
        rec = self._record("GET /api/events?run_id=x -> 200 (5.0ms)")
        assert self.f.filter(rec) is False

    def test_polling_artifacts_info_dropped(self):
        rec = self._record("GET /api/artifacts/run1 -> 200 (8.1ms)")
        assert self.f.filter(rec) is False

    def test_non_polling_info_kept(self):
        rec = self._record("GET /api/cases -> 200 (20.0ms)")
        assert self.f.filter(rec) is True

    def test_polling_error_kept(self):
        rec = self._record(
            "GET /api/runs/abc -> 500 (15.0ms)", level=logging.WARNING
        )
        assert self.f.filter(rec) is True

    def test_polling_slow_request_kept(self):
        rec = self._record("GET /api/runs/abc -> 200 (6000.0ms)")
        assert self.f.filter(rec) is True

    def test_is_polling_path_helper(self):
        assert is_polling_path("/api/runs/x") is True
        assert is_polling_path("/api/events") is True
        assert is_polling_path("/api/artifacts/foo") is True
        assert is_polling_path("/api/cases") is False
        assert is_polling_path("/api/health") is False


# ---------------------------------------------------------------------------
# DuplicateDBConnectFilter
# ---------------------------------------------------------------------------

class TestDuplicateDBConnectFilter:
    def setup_method(self):
        DuplicateDBConnectFilter.reset()
        self.f = DuplicateDBConnectFilter()

    def _record(self, msg: str, level: int = logging.INFO) -> logging.LogRecord:
        return logging.LogRecord(
            name="veritas_web.database",
            level=level,
            pathname="",
            lineno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )

    def test_first_db_connect_kept(self):
        rec = self._record("Database connecting: host=localhost port=5432")
        assert self.f.filter(rec) is True

    def test_second_db_connect_dropped(self):
        self._record("Database connecting: host=localhost port=5432")
        self.f.filter(self._record("Database connecting: host=localhost port=5432"))
        rec = self._record("Database connecting: host=localhost port=5432")
        assert self.f.filter(rec) is False

    def test_non_connect_message_kept(self):
        rec = self._record("Query executed in 12ms")
        assert self.f.filter(rec) is True

    def test_db_connect_warning_always_kept(self):
        """Even duplicate warnings must pass through."""
        self.f.filter(
            self._record("Database connecting: host=localhost port=5432")
        )
        rec = self._record(
            "Database connecting: host=localhost port=5432", level=logging.WARNING
        )
        assert self.f.filter(rec) is True
