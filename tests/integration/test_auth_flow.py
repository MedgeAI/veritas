"""Integration tests for the Veritas Web authentication flow.

Tests the full HTTP request path through the auth layer for all three
auth modes (none, bearer, basic) and verifies that ownership enforcement
works correctly across different users.
"""
from __future__ import annotations

import base64
import datetime
import json
from pathlib import Path

import jwt
from fastapi.testclient import TestClient

from web.backend.veritas_web.app import create_app
from web.backend.veritas_web.auth import (
    BasicAuthProvider,
    BearerTokenProvider,
    NoAuthProvider,
)
from web.backend.veritas_web.case_store import CaseStore
from web.backend.veritas_web.config import AuthConfig, create_auth_provider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _basic_auth(username: str, password: str) -> tuple[str, str]:
    """Return (username, password) for TestClient's built-in basic auth."""
    return username, password


def _bearer_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _basic_header(username: str, password: str) -> dict[str, str]:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def _make_jwt(secret: str, user_id: str, issuer: str = "veritas") -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "userId": user_id,
        "userName": user_id,
        "iss": issuer,
        "exp": now + datetime.timedelta(hours=1),
        "iat": now,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _seed_completed_case(tmp_path: Path, db_url: str) -> tuple[str, str]:
    """Create an Alice-owned completed case.  Returns (case_id, run_id)."""
    store = CaseStore(tmp_path / "web_data", database_url=db_url)
    case = store.create_case(user_id="alice", paper_title="Alice Paper", case_id="alice-private")
    run = store.create_run(case.case_id)
    workdir = tmp_path / "outputs" / case.case_id / "research-integrity-audit"
    workdir.mkdir(parents=True)
    (workdir / "static_audit_bundle.json").write_text(
        json.dumps({"secret": "alice-data"}), encoding="utf-8",
    )
    (workdir / "final_audit_report.html").write_text(
        "<html>Alice private report</html>", encoding="utf-8",
    )
    run.status = "completed"
    run.workdir = str(workdir)
    run.summary = {"workdir": str(workdir)}
    store.save_run(run)
    store.append_event(case.case_id, run.run_id, {"event": "alice_private_event"})
    return case.case_id, run.run_id


# ---------------------------------------------------------------------------
# NoAuth mode tests
# ---------------------------------------------------------------------------

class TestNoAuthMode:
    def test_list_cases_without_auth(self, tmp_path: Path) -> None:
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=NoAuthProvider(),
        )
        client = TestClient(app)
        resp = client.get("/api/cases")
        assert resp.status_code == 200
        assert resp.json() == {"cases": []}

    def test_create_case_without_auth(self, tmp_path: Path) -> None:
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=NoAuthProvider(),
        )
        client = TestClient(app)
        resp = client.post("/api/cases", json={"paper_title": "Test Paper"})
        assert resp.status_code == 201
        assert resp.json()["paper_title"] == "Test Paper"
        assert resp.json()["owner"] == "operator"

    def test_health_endpoint_without_auth(self, tmp_path: Path) -> None:
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=NoAuthProvider(),
        )
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Bearer (JWT) mode tests
# ---------------------------------------------------------------------------

class TestBearerMode:
    def test_missing_token_returns_401(self, tmp_path: Path) -> None:
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=BearerTokenProvider("test-secret"),
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/cases")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, tmp_path: Path) -> None:
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=BearerTokenProvider("test-secret"),
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/cases", headers=_bearer_header("not-a-real-token"))
        assert resp.status_code == 401

    def test_valid_token_returns_200(self, tmp_path: Path) -> None:
        secret = "test-secret"
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=BearerTokenProvider(secret),
        )
        client = TestClient(app)
        token = _make_jwt(secret, "alice")
        resp = client.get("/api/cases", headers=_bearer_header(token))
        assert resp.status_code == 200
        assert resp.json() == {"cases": []}

    def test_valid_token_create_case_uses_jwt_user(self, tmp_path: Path) -> None:
        secret = "test-secret"
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=BearerTokenProvider(secret),
        )
        client = TestClient(app)
        token = _make_jwt(secret, "alice")
        resp = client.post("/api/cases", json={"paper_title": "Alice Paper"}, headers=_bearer_header(token))
        assert resp.status_code == 201
        assert resp.json()["owner"] == "alice"

    def test_wrong_issuer_returns_401(self, tmp_path: Path) -> None:
        secret = "test-secret"
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=BearerTokenProvider(secret, issuer="veritas"),
        )
        client = TestClient(app, raise_server_exceptions=False)
        token = _make_jwt(secret, "alice", issuer="wrong-issuer")
        resp = client.get("/api/cases", headers=_bearer_header(token))
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Basic mode tests
# ---------------------------------------------------------------------------

class TestBasicMode:
    def _setup_provider(self, tmp_path: Path) -> BasicAuthProvider:
        db_path = str(tmp_path / "test_users.db")
        provider = BasicAuthProvider(db_path)
        provider.add_user("alice", "alice-pass", email="alice@lab.org", roles="admin,operator")
        provider.add_user("bob", "bob-pass", email="bob@lab.org", roles="operator")
        return provider

    def test_missing_credentials_returns_401(self, tmp_path: Path) -> None:
        provider = self._setup_provider(tmp_path)
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=provider,
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/cases")
        assert resp.status_code == 401

    def test_wrong_password_returns_401(self, tmp_path: Path) -> None:
        provider = self._setup_provider(tmp_path)
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=provider,
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/cases", headers=_basic_header("alice", "wrong"))
        assert resp.status_code == 401

    def test_valid_credentials_returns_200(self, tmp_path: Path) -> None:
        provider = self._setup_provider(tmp_path)
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=provider,
        )
        client = TestClient(app)
        resp = client.get("/api/cases", headers=_basic_header("alice", "alice-pass"))
        assert resp.status_code == 200
        assert resp.json() == {"cases": []}

    def test_valid_credentials_create_case_uses_username(self, tmp_path: Path) -> None:
        provider = self._setup_provider(tmp_path)
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=provider,
        )
        client = TestClient(app)
        resp = client.post(
            "/api/cases",
            json={"paper_title": "Alice Paper"},
            headers=_basic_header("alice", "alice-pass"),
        )
        assert resp.status_code == 201
        assert resp.json()["owner"] == "alice"


# ---------------------------------------------------------------------------
# Cross-user isolation tests
# ---------------------------------------------------------------------------

class TestCrossUserIsolation:
    def test_basic_mode_user_isolation(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test_users.db")
        provider = BasicAuthProvider(db_path)
        provider.add_user("alice", "alice-pass", roles="operator")
        provider.add_user("bob", "bob-pass", roles="operator")

        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=provider,
        )
        client = TestClient(app, raise_server_exceptions=False)

        # Alice creates a case
        resp = client.post(
            "/api/cases",
            json={"paper_title": "Alice Paper"},
            headers=_basic_header("alice", "alice-pass"),
        )
        assert resp.status_code == 201
        case_id = resp.json()["case_id"]

        # Alice can see her case
        resp = client.get("/api/cases", headers=_basic_header("alice", "alice-pass"))
        assert resp.status_code == 200
        assert len(resp.json()["cases"]) == 1

        # Bob cannot see Alice's case
        resp = client.get("/api/cases", headers=_basic_header("bob", "bob-pass"))
        assert resp.status_code == 200
        assert resp.json()["cases"] == []

        # Bob cannot access Alice's case directly
        resp = client.get(f"/api/cases/{case_id}", headers=_basic_header("bob", "bob-pass"))
        assert resp.status_code == 403

    def test_basic_mode_case_subresources_enforce_owner(self, tmp_path: Path) -> None:
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        db_path = str(tmp_path / "test_users.db")
        provider = BasicAuthProvider(db_path)
        provider.add_user("alice", "alice-pass", roles="operator")
        provider.add_user("bob", "bob-pass", roles="operator")
        case_id, run_id = _seed_completed_case(tmp_path, db_url)

        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            database_url=db_url,
            auth_provider=provider,
        )
        client = TestClient(app, raise_server_exceptions=False)
        bob = _basic_header("bob", "bob-pass")

        protected_reads = [
            f"/api/cases/{case_id}/runs/{run_id}",
            f"/api/cases/{case_id}/runs/{run_id}/events",
            f"/api/cases/{case_id}/artifacts",
            f"/api/cases/{case_id}/report/html",
        ]
        for path in protected_reads:
            resp = client.get(path, headers=bob)
            assert resp.status_code == 403, f"expected 403 for {path}, got {resp.status_code}"

        resp = client.post(
            f"/api/cases/{case_id}/inputs",
            json={"filename": "stolen.txt", "content": "tampered"},
            headers=bob,
        )
        assert resp.status_code == 403

    def test_basic_mode_run_events_must_belong_to_requested_case(self, tmp_path: Path) -> None:
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        db_path = str(tmp_path / "test_users.db")
        provider = BasicAuthProvider(db_path)
        provider.add_user("alice", "alice-pass", roles="operator")
        provider.add_user("bob", "bob-pass", roles="operator")
        _alice_case_id, alice_run_id = _seed_completed_case(tmp_path, db_url)

        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            database_url=db_url,
            auth_provider=provider,
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/cases",
            json={"case_id": "bob-visible", "paper_title": "Bob Paper"},
            headers=_basic_header("bob", "bob-pass"),
        )
        assert resp.status_code == 201

        resp = client.get(
            f"/api/cases/bob-visible/runs/{alice_run_id}/events",
            headers=_basic_header("bob", "bob-pass"),
        )
        assert resp.status_code == 404
        assert "alice_private_event" not in resp.text

    def test_bearer_mode_user_isolation(self, tmp_path: Path) -> None:
        secret = "test-secret"
        app = create_app(
            data_root=tmp_path / "web_data",
            output_root=tmp_path / "outputs",
            auth_provider=BearerTokenProvider(secret),
        )
        client = TestClient(app, raise_server_exceptions=False)

        # Alice creates a case
        token_a = _make_jwt(secret, "alice")
        resp = client.post(
            "/api/cases",
            json={"paper_title": "Alice Paper"},
            headers=_bearer_header(token_a),
        )
        assert resp.status_code == 201
        case_id = resp.json()["case_id"]

        # Alice can list her cases
        resp = client.get("/api/cases", headers=_bearer_header(token_a))
        assert resp.status_code == 200
        assert len(resp.json()["cases"]) == 1

        # Bob cannot see Alice's cases
        token_b = _make_jwt(secret, "bob")
        resp = client.get("/api/cases", headers=_bearer_header(token_b))
        assert resp.status_code == 200
        assert resp.json()["cases"] == []

        # Bob gets 403 on Alice's case
        resp = client.get(f"/api/cases/{case_id}", headers=_bearer_header(token_b))
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# create_auth_provider factory tests
# ---------------------------------------------------------------------------

class TestCreateAuthProvider:
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
