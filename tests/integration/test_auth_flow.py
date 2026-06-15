"""Integration tests for the Veritas Web authentication flow.

Tests the full HTTP request path through the auth layer for all three
auth modes (none, bearer, basic) and verifies that ownership enforcement
works correctly across different users.
"""
from __future__ import annotations

import base64
import json
import socket
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import jwt
import pytest

from web.backend.veritas_web.app import VeritasWebApp, make_handler
from web.backend.veritas_web.auth import (
    BasicAuthProvider,
    BearerTokenProvider,
    NoAuthProvider,
)
from web.backend.veritas_web.config import AuthConfig, create_auth_provider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    """Return a TCP port that is currently free on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(tmp_path: Path, auth_provider, data_root: Path | None = None):
    """Start a VeritasWebApp server on a free port and return (server, port, data_root)."""
    data_root = data_root or tmp_path / "web_data"
    app = VeritasWebApp(data_root=data_root, output_root=tmp_path / "outputs")
    handler_cls = make_handler(app, auth_provider=auth_provider)
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def _request(port: int, method: str, path: str, headers: dict[str, str] | None = None, body: dict | None = None):
    """Make an HTTP request and return (status_code, response_headers, parsed_body)."""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    payload = json.dumps(body).encode("utf-8") if body else None
    conn.request(method, path, body=payload, headers=hdrs)
    resp = conn.getresponse()
    status = resp.status
    resp_headers = dict(resp.getheaders())
    raw = resp.read().decode("utf-8")
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {"_raw": raw}
    conn.close()
    return status, resp_headers, parsed


def _basic_header(username: str, password: str) -> dict[str, str]:
    """Return an ``Authorization: Basic ...`` header dict."""
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def _bearer_header(token: str) -> dict[str, str]:
    """Return an ``Authorization: Bearer ...`` header dict."""
    return {"Authorization": f"Bearer {token}"}


def _make_jwt(secret: str, user_id: str, issuer: str = "veritas") -> str:
    """Create a short-lived HS256 JWT for testing."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "userId": user_id,
        "userName": user_id,
        "iss": issuer,
        "exp": now + datetime.timedelta(hours=1),
        "iat": now,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# NoAuth mode tests
# ---------------------------------------------------------------------------

class TestNoAuthMode:
    """When VERITAS_AUTH_MODE=none (the default), no credentials are required."""

    def test_list_cases_without_auth(self, tmp_path: Path) -> None:
        server, port = _start_server(tmp_path, NoAuthProvider())
        try:
            status, _, body = _request(port, "GET", "/api/cases")
            assert status == 200
            assert body == {"cases": []}
        finally:
            server.shutdown()

    def test_create_case_without_auth(self, tmp_path: Path) -> None:
        server, port = _start_server(tmp_path, NoAuthProvider())
        try:
            status, _, body = _request(port, "POST", "/api/cases", body={"paper_title": "Test Paper"})
            assert status == 201
            assert body["paper_title"] == "Test Paper"
            assert body["owner"] == "operator"
        finally:
            server.shutdown()

    def test_health_endpoint_without_auth(self, tmp_path: Path) -> None:
        server, port = _start_server(tmp_path, NoAuthProvider())
        try:
            status, _, body = _request(port, "GET", "/api/health")
            assert status == 200
            assert body["status"] == "ok"
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# Bearer (JWT) mode tests
# ---------------------------------------------------------------------------

class TestBearerMode:
    """When VERITAS_AUTH_MODE=bearer, a valid HS256 JWT is required."""

    def test_missing_token_returns_401(self, tmp_path: Path) -> None:
        server, port = _start_server(tmp_path, BearerTokenProvider("test-secret"))
        try:
            status, headers, _ = _request(port, "GET", "/api/cases")
            assert status == 401
        finally:
            server.shutdown()

    def test_invalid_token_returns_401(self, tmp_path: Path) -> None:
        server, port = _start_server(tmp_path, BearerTokenProvider("test-secret"))
        try:
            status, _, _ = _request(port, "GET", "/api/cases", headers=_bearer_header("not-a-real-token"))
            assert status == 401
        finally:
            server.shutdown()

    def test_valid_token_returns_200(self, tmp_path: Path) -> None:
        secret = "test-secret"
        server, port = _start_server(tmp_path, BearerTokenProvider(secret))
        try:
            token = _make_jwt(secret, "alice")
            status, _, body = _request(port, "GET", "/api/cases", headers=_bearer_header(token))
            assert status == 200
            assert body == {"cases": []}
        finally:
            server.shutdown()

    def test_valid_token_create_case_uses_jwt_user(self, tmp_path: Path) -> None:
        secret = "test-secret"
        server, port = _start_server(tmp_path, BearerTokenProvider(secret))
        try:
            token = _make_jwt(secret, "alice")
            status, _, body = _request(
                port, "POST", "/api/cases",
                headers=_bearer_header(token),
                body={"paper_title": "Alice Paper"},
            )
            assert status == 201
            assert body["owner"] == "alice"
        finally:
            server.shutdown()

    def test_wrong_issuer_returns_401(self, tmp_path: Path) -> None:
        secret = "test-secret"
        server, port = _start_server(tmp_path, BearerTokenProvider(secret, issuer="veritas"))
        try:
            token = _make_jwt(secret, "alice", issuer="wrong-issuer")
            status, _, _ = _request(port, "GET", "/api/cases", headers=_bearer_header(token))
            assert status == 401
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# Basic (SQLite) mode tests
# ---------------------------------------------------------------------------

class TestBasicMode:
    """When VERITAS_AUTH_MODE=basic, HTTP Basic Auth with a SQLite user store."""

    def _setup_provider(self, tmp_path: Path) -> BasicAuthProvider:
        db_path = str(tmp_path / "test_users.db")
        provider = BasicAuthProvider(db_path)
        provider.add_user("alice", "alice-pass", email="alice@lab.org", roles="admin,operator")
        provider.add_user("bob", "bob-pass", email="bob@lab.org", roles="operator")
        return provider

    def test_missing_credentials_returns_401_with_challenge(self, tmp_path: Path) -> None:
        provider = self._setup_provider(tmp_path)
        server, port = _start_server(tmp_path, provider)
        try:
            status, headers, _ = _request(port, "GET", "/api/cases")
            assert status == 401
            assert "WWW-Authenticate" in headers
            assert "Basic" in headers["WWW-Authenticate"]
        finally:
            server.shutdown()

    def test_wrong_password_returns_401(self, tmp_path: Path) -> None:
        provider = self._setup_provider(tmp_path)
        server, port = _start_server(tmp_path, provider)
        try:
            status, _, _ = _request(port, "GET", "/api/cases", headers=_basic_header("alice", "wrong"))
            assert status == 401
        finally:
            server.shutdown()

    def test_valid_credentials_returns_200(self, tmp_path: Path) -> None:
        provider = self._setup_provider(tmp_path)
        server, port = _start_server(tmp_path, provider)
        try:
            status, _, body = _request(port, "GET", "/api/cases", headers=_basic_header("alice", "alice-pass"))
            assert status == 200
            assert body == {"cases": []}
        finally:
            server.shutdown()

    def test_valid_credentials_create_case_uses_username(self, tmp_path: Path) -> None:
        provider = self._setup_provider(tmp_path)
        server, port = _start_server(tmp_path, provider)
        try:
            status, _, body = _request(
                port, "POST", "/api/cases",
                headers=_basic_header("alice", "alice-pass"),
                body={"paper_title": "Alice Paper"},
            )
            assert status == 201
            assert body["owner"] == "alice"
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# Cross-user isolation tests
# ---------------------------------------------------------------------------

class TestCrossUserIsolation:
    """Verify that user A's cases are not visible to user B."""

    def test_basic_mode_user_isolation(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test_users.db")
        provider = BasicAuthProvider(db_path)
        provider.add_user("alice", "alice-pass", roles="operator")
        provider.add_user("bob", "bob-pass", roles="operator")

        server, port = _start_server(tmp_path, provider)
        try:
            # Alice creates a case
            status, _, alice_case = _request(
                port, "POST", "/api/cases",
                headers=_basic_header("alice", "alice-pass"),
                body={"paper_title": "Alice Paper"},
            )
            assert status == 201
            case_id = alice_case["case_id"]

            # Alice can see her case
            status, _, body = _request(port, "GET", "/api/cases", headers=_basic_header("alice", "alice-pass"))
            assert status == 200
            assert len(body["cases"]) == 1
            assert body["cases"][0]["case_id"] == case_id

            # Bob cannot see Alice's case in list
            status, _, body = _request(port, "GET", "/api/cases", headers=_basic_header("bob", "bob-pass"))
            assert status == 200
            assert body["cases"] == []

            # Bob cannot access Alice's case directly
            status, _, body = _request(
                port, "GET", f"/api/cases/{case_id}",
                headers=_basic_header("bob", "bob-pass"),
            )
            assert status == 403
        finally:
            server.shutdown()

    def test_bearer_mode_user_isolation(self, tmp_path: Path) -> None:
        secret = "test-secret"
        server, port = _start_server(tmp_path, BearerTokenProvider(secret))
        try:
            # Alice creates a case
            token_a = _make_jwt(secret, "alice")
            status, _, alice_case = _request(
                port, "POST", "/api/cases",
                headers=_bearer_header(token_a),
                body={"paper_title": "Alice Paper"},
            )
            assert status == 201
            case_id = alice_case["case_id"]

            # Alice can list her cases
            status, _, body = _request(port, "GET", "/api/cases", headers=_bearer_header(token_a))
            assert status == 200
            assert len(body["cases"]) == 1

            # Bob cannot see Alice's cases
            token_b = _make_jwt(secret, "bob")
            status, _, body = _request(port, "GET", "/api/cases", headers=_bearer_header(token_b))
            assert status == 200
            assert body["cases"] == []

            # Bob gets 403 on Alice's case
            status, _, _ = _request(
                port, "GET", f"/api/cases/{case_id}",
                headers=_bearer_header(token_b),
            )
            assert status == 403
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# create_auth_provider factory tests
# ---------------------------------------------------------------------------

class TestCreateAuthProvider:
    """Verify the factory creates the correct provider type."""

    def test_none_mode(self) -> None:
        config = AuthConfig(mode="none")
        provider = create_auth_provider(config)
        assert isinstance(provider, NoAuthProvider)

    def test_bearer_mode(self) -> None:
        config = AuthConfig(mode="bearer", jwt_shared_secret="secret")
        provider = create_auth_provider(config)
        assert isinstance(provider, BearerTokenProvider)

    def test_basic_mode(self, tmp_path: Path) -> None:
        config = AuthConfig(mode="basic", sqlite_db_path=tmp_path / "users.db")
        provider = create_auth_provider(config)
        assert isinstance(provider, BasicAuthProvider)
