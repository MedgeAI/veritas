"""Tests for DELETE /api/cases/{case_id} endpoint."""

from __future__ import annotations

from pathlib import Path


from tests.helpers.asgi_client import LocalASGITestClient as TestClient
from web.backend.veritas_web.app import create_app
from web.backend.veritas_web.auth import BasicAuthProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basic_header(username: str, password: str) -> dict[str, str]:
    import base64

    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _create_case(client: TestClient, case_id: str) -> None:
    resp = client.post(
        "/api/cases", json={"case_id": case_id, "paper_title": "Test Paper"}
    )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Tests — admin (NoAuth) can delete
# ---------------------------------------------------------------------------


def test_admin_delete_case(tmp_path: Path) -> None:
    """NoAuth mode defaults to admin — deletion succeeds with 204."""
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)

    _create_case(client, "del-case-1")

    # Verify case exists
    resp = client.get("/api/cases/del-case-1")
    assert resp.status_code == 200

    # Delete it (NoAuth → admin)
    resp = client.request("DELETE", "/api/cases/del-case-1")
    assert resp.status_code == 204

    # Confirm it is gone
    resp = client.get("/api/cases/del-case-1")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests — non-admin gets 403
# ---------------------------------------------------------------------------


def test_non_admin_delete_forbidden(tmp_path: Path) -> None:
    """A user without the admin role receives 403 on DELETE."""
    auth_provider = BasicAuthProvider(db_path=str(tmp_path / "users.db"))
    auth_provider.add_user("viewer", "pass123", roles="operator")

    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        auth_provider=auth_provider,
    )
    client = TestClient(app, raise_server_exceptions=False)

    # Create a case as the viewer
    resp = client.post(
        "/api/cases",
        json={"case_id": "forbidden-case", "paper_title": "Test"},
        headers=_basic_header("viewer", "pass123"),
    )
    assert resp.status_code == 201

    # Attempt delete — should be forbidden
    resp = client.request(
        "DELETE",
        "/api/cases/forbidden-case",
        headers=_basic_header("viewer", "pass123"),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests — delete non-existent case returns 404
# ---------------------------------------------------------------------------


def test_delete_nonexistent_case_returns_404(tmp_path: Path) -> None:
    """Deleting a case that does not exist returns 404."""
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.request("DELETE", "/api/cases/does-not-exist")
    assert resp.status_code == 404
