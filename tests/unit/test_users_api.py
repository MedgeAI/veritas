"""Tests for the /api/users management endpoints."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from tests.helpers.asgi_client import LocalASGITestClient as TestClient
from web.backend.veritas_web.app import create_app
from web.backend.veritas_web.auth import BasicAuthProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basic_auth(username: str, password: str) -> dict[str, str]:
    """Return an ``Authorization: Basic ...`` header dict."""
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _json_request(
    client: TestClient,
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> "ASGIResponse":  # type: ignore[name-defined]  # noqa: F821
    """Send a JSON request with an arbitrary HTTP method."""
    body = json.dumps(payload or {}).encode("utf-8") if payload else b""
    hdrs = dict(headers or {})
    if payload is not None:
        hdrs.setdefault("content-type", "application/json")
    return client.request(method, path, body=body, headers=hdrs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(tmp_path: Path):
    """Create a FastAPI app backed by a temp SQLite user store."""
    db_path = str(tmp_path / "users.db")
    provider = BasicAuthProvider(db_path=db_path)
    # Seed an admin user and a regular operator.
    provider.add_user("admin", "adminpw", email="admin@test.com", roles="admin")
    provider.add_user("operator", "oppw", email="op@test.com", roles="operator")
    return create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        auth_provider=provider,
    )


@pytest.fixture()
def client(app):
    return TestClient(app)


ADMIN_HEADERS = _basic_auth("admin", "adminpw")
OPERATOR_HEADERS = _basic_auth("operator", "oppw")


# ---------------------------------------------------------------------------
# GET /api/users
# ---------------------------------------------------------------------------


class TestListUsers:
    def test_admin_lists_users(self, client):
        resp = client.get("/api/users", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        usernames = {u["username"] for u in data}
        assert "admin" in usernames
        assert "operator" in usernames

    def test_non_admin_forbidden(self, client):
        resp = client.get("/api/users", headers=OPERATOR_HEADERS)
        assert resp.status_code == 403

    def test_no_auth_rejected(self, client):
        resp = client.get("/api/users")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/users
# ---------------------------------------------------------------------------


class TestCreateUser:
    def test_admin_creates_user(self, client):
        resp = _json_request(
            client,
            "POST",
            "/api/users",
            {
                "username": "alice",
                "password": "secret",
                "email": "alice@test.com",
                "roles": "operator",
            },
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "created"
        assert data["username"] == "alice"

        # Verify the user appears in list.
        resp2 = client.get("/api/users", headers=ADMIN_HEADERS)
        usernames = {u["username"] for u in resp2.json()}
        assert "alice" in usernames

    def test_non_admin_forbidden(self, client):
        resp = _json_request(
            client,
            "POST",
            "/api/users",
            {"username": "bob", "password": "pw"},
            headers=OPERATOR_HEADERS,
        )
        assert resp.status_code == 403

    def test_missing_username_rejected(self, client):
        resp = _json_request(
            client,
            "POST",
            "/api/users",
            {"password": "pw"},
            headers=ADMIN_HEADERS,
        )
        # FastAPI returns 422 for validation errors.
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/users/{username}
# ---------------------------------------------------------------------------


class TestUpdateUser:
    def test_admin_updates_email(self, client):
        resp = _json_request(
            client,
            "PUT",
            "/api/users/operator",
            {"email": "newop@test.com"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

        # Verify the email was actually updated.
        users = {u["username"]: u for u in client.get("/api/users", headers=ADMIN_HEADERS).json()}
        assert users["operator"]["email"] == "newop@test.com"

    def test_admin_updates_roles(self, client):
        resp = _json_request(
            client,
            "PUT",
            "/api/users/operator",
            {"roles": "admin,operator"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        users = {u["username"]: u for u in client.get("/api/users", headers=ADMIN_HEADERS).json()}
        assert "admin" in users["operator"]["roles"]

    def test_non_admin_forbidden(self, client):
        resp = _json_request(
            client,
            "PUT",
            "/api/users/operator",
            {"email": "x@test.com"},
            headers=OPERATOR_HEADERS,
        )
        assert resp.status_code == 403

    def test_unknown_user_404(self, client):
        resp = _json_request(
            client,
            "PUT",
            "/api/users/nobody",
            {"email": "x@test.com"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/users/{username}
# ---------------------------------------------------------------------------


class TestDeleteUser:
    def test_admin_deletes_user(self, client):
        # Create a user first.
        _json_request(
            client,
            "POST",
            "/api/users",
            {"username": "temp", "password": "pw"},
            headers=ADMIN_HEADERS,
        )
        resp = client.request("DELETE", "/api/users/temp", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # User should no longer appear.
        users = {u["username"] for u in client.get("/api/users", headers=ADMIN_HEADERS).json()}
        assert "temp" not in users

    def test_non_admin_forbidden(self, client):
        resp = client.request("DELETE", "/api/users/operator", headers=OPERATOR_HEADERS)
        assert resp.status_code == 403

    def test_unknown_user_404(self, client):
        resp = client.request("DELETE", "/api/users/nobody", headers=ADMIN_HEADERS)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/users/{username}/password
# ---------------------------------------------------------------------------


class TestChangePassword:
    def test_admin_changes_password(self, client):
        resp = _json_request(
            client,
            "POST",
            "/api/users/operator/password",
            {"password": "newpass"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "password_updated"

        # Old password should no longer work.
        assert client.get("/api/users", headers=OPERATOR_HEADERS).status_code == 401
        # New password should work.
        new_headers = _basic_auth("operator", "newpass")
        assert client.get("/api/users", headers=new_headers).status_code == 403  # non-admin

    def test_self_changes_password(self, client):
        resp = _json_request(
            client,
            "POST",
            "/api/users/operator/password",
            {"password": "mynewpw"},
            headers=OPERATOR_HEADERS,
        )
        assert resp.status_code == 200
        # Authenticate with the new password.
        new_headers = _basic_auth("operator", "mynewpw")
        resp2 = _json_request(
            client,
            "POST",
            "/api/users/operator/password",
            {"password": "again"},
            headers=new_headers,
        )
        assert resp2.status_code == 200

    def test_other_user_forbidden(self, client):
        # Create another non-admin user.
        _json_request(
            client,
            "POST",
            "/api/users",
            {"username": "bob", "password": "pw"},
            headers=ADMIN_HEADERS,
        )
        bob_headers = _basic_auth("bob", "pw")
        # Bob tries to change operator's password.
        resp = _json_request(
            client,
            "POST",
            "/api/users/operator/password",
            {"password": "hacked"},
            headers=bob_headers,
        )
        assert resp.status_code == 403

    def test_unknown_user_404(self, client):
        resp = _json_request(
            client,
            "POST",
            "/api/users/nobody/password",
            {"password": "pw"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404
