"""Tests for BasicAuthProvider.

All tests use a temporary SQLite database so they are fully isolated and
leave no artefacts on disk.
"""

from __future__ import annotations

import base64

import pytest

from web.backend.veritas_web.auth import AuthContext, BasicAuthProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basic_header(username: str, password: str) -> dict[str, str]:
    """Build an ``Authorization: Basic ...`` header dict."""
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def provider(tmp_path):
    """Return a ``BasicAuthProvider`` backed by a temp SQLite file."""
    return BasicAuthProvider(db_path=str(tmp_path / "test_users.db"))


@pytest.fixture()
def provider_with_user(provider):
    """Provider pre-populated with user *alice* (password ``secret``)."""
    provider.add_user(
        "alice", "secret", email="alice@example.com", roles="operator,reviewer"
    )
    return provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuthenticateValid:
    """Happy path: valid Basic Auth credentials."""

    def test_returns_auth_context(self, provider_with_user):
        ctx = provider_with_user.authenticate(_basic_header("alice", "secret"))

        assert isinstance(ctx, AuthContext)
        assert ctx.user_id == "alice"
        assert ctx.email == "alice@example.com"
        assert "operator" in ctx.roles
        assert "reviewer" in ctx.roles

    def test_is_enabled(self, provider):
        assert provider.is_enabled() is True


class TestAuthenticateRejection:
    """Invalid or missing credentials must return None."""

    def test_invalid_password(self, provider_with_user):
        assert provider_with_user.authenticate(_basic_header("alice", "wrong")) is None

    def test_unknown_user(self, provider_with_user):
        assert provider_with_user.authenticate(_basic_header("bob", "secret")) is None

    def test_missing_authorization_header(self, provider_with_user):
        assert provider_with_user.authenticate({}) is None

    def test_malformed_base64(self, provider_with_user):
        assert (
            provider_with_user.authenticate({"Authorization": "Basic !!!not-base64!!!"})
            is None
        )

    def test_missing_colon_in_credentials(self, provider_with_user):
        token = base64.b64encode(b"no-colon-here").decode()
        assert (
            provider_with_user.authenticate({"Authorization": f"Basic {token}"}) is None
        )

    def test_bearer_scheme_rejected(self, provider_with_user):
        assert (
            provider_with_user.authenticate({"Authorization": "Bearer token123"})
            is None
        )


class TestAddUserAndAuthenticate:
    """add_user → authenticate round-trip."""

    def test_add_then_authenticate(self, provider):
        provider.add_user("bob", "p@ss!", email="bob@test.com", roles="admin,operator")

        ctx = provider.authenticate(_basic_header("bob", "p@ss!"))
        assert ctx is not None
        assert ctx.user_id == "bob"
        assert ctx.email == "bob@test.com"
        assert ctx.has_role("admin")
        assert ctx.has_role("operator")

    def test_default_roles_are_operator(self, provider):
        provider.add_user("carol", "pw")

        ctx = provider.authenticate(_basic_header("carol", "pw"))
        assert ctx is not None
        assert ctx.roles == frozenset({"operator"})

    def test_upsert_replaces_existing_user(self, provider):
        provider.add_user("dave", "old_pw", email="old@test.com")
        provider.add_user("dave", "new_pw", email="new@test.com")

        # Old password must no longer work.
        assert provider.authenticate(_basic_header("dave", "old_pw")) is None
        # New password must work with updated metadata.
        ctx = provider.authenticate(_basic_header("dave", "new_pw"))
        assert ctx is not None
        assert ctx.email == "new@test.com"


class TestChallengeHeaders:
    """challenge_headers must return a proper WWW-Authenticate value."""

    def test_contains_basic_realm(self, provider):
        headers = provider.challenge_headers()
        assert headers == {"WWW-Authenticate": 'Basic realm="Veritas"'}
