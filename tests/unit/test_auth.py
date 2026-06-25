"""Tests for authentication modules.

Merged from: test_{basic_auth,bearer_auth,auth_schema}.
"""

from __future__ import annotations

import base64
import jwt
import pytest
import time

from web.backend.veritas_web.auth import (
    AuthContext,
    NoAuthProvider,
)
from web.backend.veritas_web.auth import BasicAuthProvider
from web.backend.veritas_web.auth import BearerTokenProvider
from web.backend.veritas_web.config import AuthConfig


# ===========================================================================
# test_basic_auth.py
# ===========================================================================


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
def basic_provider(tmp_path):
    """Return a ``BasicAuthProvider`` backed by a temp SQLite file."""
    return BasicAuthProvider(db_path=str(tmp_path / "test_users.db"))


@pytest.fixture()
def basic_provider_with_user(basic_provider):
    """Provider pre-populated with user *alice* (password ``secret``)."""
    basic_provider.add_user(
        "alice", "secret", email="alice@example.com", roles="operator,reviewer"
    )
    return basic_provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuthenticateValid:
    """Happy path: valid Basic Auth credentials."""

    def test_returns_auth_context(self, basic_provider_with_user):
        ctx = basic_provider_with_user.authenticate(_basic_header("alice", "secret"))

        assert isinstance(ctx, AuthContext)
        assert ctx.user_id == "alice"
        assert ctx.email == "alice@example.com"
        assert "operator" in ctx.roles
        assert "reviewer" in ctx.roles

    def test_is_enabled(self, basic_provider):
        assert basic_provider.is_enabled() is True


class TestAuthenticateRejection:
    """Invalid or missing credentials must return None."""

    def test_invalid_password(self, basic_provider_with_user):
        assert basic_provider_with_user.authenticate(_basic_header("alice", "wrong")) is None

    def test_unknown_user(self, basic_provider_with_user):
        assert basic_provider_with_user.authenticate(_basic_header("bob", "secret")) is None

    def test_missing_authorization_header(self, basic_provider_with_user):
        assert basic_provider_with_user.authenticate({}) is None

    def test_malformed_base64(self, basic_provider_with_user):
        assert (
            basic_provider_with_user.authenticate({"Authorization": "Basic !!!not-base64!!!"})
            is None
        )

    def test_missing_colon_in_credentials(self, basic_provider_with_user):
        token = base64.b64encode(b"no-colon-here").decode()
        assert (
            basic_provider_with_user.authenticate({"Authorization": f"Basic {token}"}) is None
        )

    def test_bearer_scheme_rejected(self, basic_provider_with_user):
        assert (
            basic_provider_with_user.authenticate({"Authorization": "Bearer token123"})
            is None
        )


class TestAddUserAndAuthenticate:
    """add_user → authenticate round-trip."""

    def test_add_then_authenticate(self, basic_provider):
        basic_provider.add_user("bob", "p@ss!", email="bob@test.com", roles="admin,operator")

        ctx = basic_provider.authenticate(_basic_header("bob", "p@ss!"))
        assert ctx is not None
        assert ctx.user_id == "bob"
        assert ctx.email == "bob@test.com"
        assert ctx.has_role("admin")
        assert ctx.has_role("operator")

    def test_default_roles_are_operator(self, basic_provider):
        basic_provider.add_user("carol", "pw")

        ctx = basic_provider.authenticate(_basic_header("carol", "pw"))
        assert ctx is not None
        assert ctx.roles == frozenset({"operator"})

    def test_upsert_replaces_existing_user(self, basic_provider):
        basic_provider.add_user("dave", "old_pw", email="old@test.com")
        basic_provider.add_user("dave", "new_pw", email="new@test.com")

        # Old password must no longer work.
        assert basic_provider.authenticate(_basic_header("dave", "old_pw")) is None
        # New password must work with updated metadata.
        ctx = basic_provider.authenticate(_basic_header("dave", "new_pw"))
        assert ctx is not None
        assert ctx.email == "new@test.com"


class TestChallengeHeaders:
    """challenge_headers must return a proper WWW-Authenticate value."""

    def test_contains_basic_realm(self, basic_provider):
        headers = basic_provider.challenge_headers()
        assert headers == {"WWW-Authenticate": 'Basic realm="Veritas"'}



# ===========================================================================
# test_bearer_auth.py
# ===========================================================================

SHARED_SECRET = "test-secret"
ISSUER = "gin-blog"


def _make_token(
    payload: dict,
    secret: str = SHARED_SECRET,
    algorithm: str = "HS256",
) -> str:
    """Encode a JWT with the given payload."""
    return jwt.encode(payload, secret, algorithm=algorithm)


@pytest.fixture
def bearer_provider() -> BearerTokenProvider:
    return BearerTokenProvider(shared_secret=SHARED_SECRET, issuer=ISSUER)


def _valid_payload() -> dict:
    return {
        "userId": "507f1f77bcf86cd799439011",
        "userName": "alice",
        "exp": int(time.time()) + 3600,
        "iss": ISSUER,
    }


class TestBearerTokenProviderAuthenticate:
    """authenticate() should return AuthContext for valid tokens and None otherwise."""

    def test_valid_jwt_returns_auth_context(
        self, bearer_provider: BearerTokenProvider
    ) -> None:
        token = _make_token(_valid_payload())
        headers = {"Authorization": f"Bearer {token}"}

        ctx = bearer_provider.authenticate(headers)

        assert ctx is not None
        assert isinstance(ctx, AuthContext)
        assert ctx.user_id == "507f1f77bcf86cd799439011"
        assert ctx.email is None
        assert "operator" in ctx.roles
        assert ctx.metadata["userName"] == "alice"
        assert ctx.metadata["source"] == "main_product"

    def test_valid_jwt_with_missing_optional_userName(
        self, bearer_provider: BearerTokenProvider
    ) -> None:
        payload = _valid_payload()
        del payload["userName"]
        token = _make_token(payload)
        headers = {"Authorization": f"Bearer {token}"}

        ctx = bearer_provider.authenticate(headers)

        assert ctx is not None
        assert ctx.metadata["userName"] == ""

    def test_valid_signature_missing_required_user_id_returns_none(
        self, bearer_provider: BearerTokenProvider
    ) -> None:
        payload = _valid_payload()
        del payload["userId"]
        token = _make_token(payload)
        headers = {"Authorization": f"Bearer {token}"}

        assert bearer_provider.authenticate(headers) is None

    def test_valid_signature_empty_required_user_id_returns_none(
        self, bearer_provider: BearerTokenProvider
    ) -> None:
        payload = _valid_payload()
        payload["userId"] = ""
        token = _make_token(payload)
        headers = {"Authorization": f"Bearer {token}"}

        assert bearer_provider.authenticate(headers) is None

    def test_valid_signature_missing_required_exp_returns_none(
        self, bearer_provider: BearerTokenProvider
    ) -> None:
        payload = _valid_payload()
        del payload["exp"]
        token = _make_token(payload)
        headers = {"Authorization": f"Bearer {token}"}

        assert bearer_provider.authenticate(headers) is None

    def test_invalid_signature_returns_none(
        self, bearer_provider: BearerTokenProvider
    ) -> None:
        token = _make_token(_valid_payload(), secret="wrong-secret")
        headers = {"Authorization": f"Bearer {token}"}

        assert bearer_provider.authenticate(headers) is None

    def test_garbage_token_returns_none(self, bearer_provider: BearerTokenProvider) -> None:
        headers = {"Authorization": "Bearer not.a.valid.jwt"}

        assert bearer_provider.authenticate(headers) is None

    def test_expired_jwt_returns_none(self, bearer_provider: BearerTokenProvider) -> None:
        payload = _valid_payload()
        payload["exp"] = int(time.time()) - 60
        token = _make_token(payload)
        headers = {"Authorization": f"Bearer {token}"}

        assert bearer_provider.authenticate(headers) is None

    def test_wrong_issuer_returns_none(self, bearer_provider: BearerTokenProvider) -> None:
        payload = _valid_payload()
        payload["iss"] = "wrong-issuer"
        token = _make_token(payload)
        headers = {"Authorization": f"Bearer {token}"}

        assert bearer_provider.authenticate(headers) is None

    def test_missing_authorization_header_returns_none(
        self, bearer_provider: BearerTokenProvider
    ) -> None:
        assert bearer_provider.authenticate({}) is None

    def test_empty_authorization_header_returns_none(
        self, bearer_provider: BearerTokenProvider
    ) -> None:
        assert bearer_provider.authenticate({"Authorization": ""}) is None

    def test_non_bearer_authorization_returns_none(
        self, bearer_provider: BearerTokenProvider
    ) -> None:
        headers = {"Authorization": "Basic dXNlcjpwYXNz"}

        assert bearer_provider.authenticate(headers) is None

    def test_bearer_prefix_without_token_returns_none(
        self, bearer_provider: BearerTokenProvider
    ) -> None:
        headers = {"Authorization": "Bearer "}

        assert bearer_provider.authenticate(headers) is None

    def test_case_insensitive_authorization_header(
        self, bearer_provider: BearerTokenProvider
    ) -> None:
        token = _make_token(_valid_payload())
        headers = {"authorization": f"Bearer {token}"}

        ctx = bearer_provider.authenticate(headers)

        assert ctx is not None
        assert ctx.user_id == "507f1f77bcf86cd799439011"

    def test_is_enabled_returns_true(self, bearer_provider: BearerTokenProvider) -> None:
        assert bearer_provider.is_enabled() is True



# ===========================================================================
# test_auth_schema.py
# ===========================================================================


class TestAuthContext:
    """Tests for AuthContext dataclass."""

    def test_create_minimal_context(self) -> None:
        """Test creating AuthContext with minimal required fields."""
        ctx = AuthContext(user_id="user1", email="user1@example.com")

        assert ctx.user_id == "user1"
        assert ctx.email == "user1@example.com"
        assert len(ctx.roles) == 0
        assert ctx.metadata == {}

    def test_create_context_with_roles(self) -> None:
        """Test creating AuthContext with roles."""
        ctx = AuthContext(
            user_id="admin1",
            email="admin@example.com",
            roles=frozenset({"admin", "pi"}),
        )

        assert ctx.has_role("admin")
        assert ctx.has_role("pi")
        assert not ctx.has_role("reviewer")
        assert ctx.is_admin()

    def test_create_context_with_metadata(self) -> None:
        """Test creating AuthContext with metadata."""
        ctx = AuthContext(
            user_id="user2",
            email="user2@example.com",
            metadata={"department": "biology", "level": 3},
        )

        assert ctx.metadata["department"] == "biology"
        assert ctx.metadata["level"] == 3

    def test_context_is_frozen(self) -> None:
        """Test that AuthContext is immutable."""
        ctx = AuthContext(user_id="user3", email="user3@example.com")

        with pytest.raises(AttributeError):
            ctx.user_id = "changed"  # type: ignore[misc]


class TestNoAuthProvider:
    """Tests for NoAuthProvider."""

    def test_authenticate_returns_operator(self) -> None:
        """Test that NoAuthProvider returns operator context."""
        provider = NoAuthProvider()
        ctx = provider.authenticate({})

        assert ctx is not None
        assert ctx.user_id == "operator"
        assert ctx.email == "operator@veritas.local"
        assert ctx.is_admin()
        assert ctx.metadata["auth_mode"] == "none"

    def test_is_enabled(self) -> None:
        """Test that NoAuthProvider is always enabled."""
        provider = NoAuthProvider()
        assert provider.is_enabled() is True


class TestAuthConfig:
    """Tests for AuthConfig and from_env()."""

    def test_default_config(self) -> None:
        """Test default AuthConfig values."""
        config = AuthConfig()

        assert config.mode == "none"
        assert config.jwt_shared_secret == ""
        assert config.jwt_issuer == "veritas"
        assert str(config.sqlite_db_path) == "web_data/users.db"

    def test_from_env_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test from_env() with no environment variables set."""
        # Clear any existing env vars
        monkeypatch.delenv("VERITAS_AUTH_MODE", raising=False)
        monkeypatch.delenv("VERITAS_JWT_SECRET", raising=False)
        monkeypatch.delenv("VERITAS_JWT_ISSUER", raising=False)
        monkeypatch.delenv("VERITAS_USERS_DB", raising=False)

        config = AuthConfig.from_env()

        assert config.mode == "none"
        assert config.jwt_shared_secret == ""
        assert config.jwt_issuer == "veritas"

    def test_from_env_bearer_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test from_env() with bearer mode."""
        monkeypatch.setenv("VERITAS_AUTH_MODE", "bearer")
        monkeypatch.setenv("VERITAS_JWT_SECRET", "a" * 32)
        monkeypatch.setenv("VERITAS_JWT_ISSUER", "my-issuer")
        monkeypatch.setenv("VERITAS_USERS_DB", "/tmp/test_users.db")

        config = AuthConfig.from_env()

        assert config.mode == "bearer"
        assert config.jwt_shared_secret == "a" * 32
        assert config.jwt_issuer == "my-issuer"
        assert str(config.sqlite_db_path) == "/tmp/test_users.db"

    def test_from_env_bearer_short_secret_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bearer mode with a secret shorter than 32 chars must fail fast."""
        monkeypatch.setenv("VERITAS_AUTH_MODE", "bearer")
        monkeypatch.setenv("VERITAS_JWT_SECRET", "short")

        with pytest.raises(ValueError, match="at least 32 characters"):
            AuthConfig.from_env()

    def test_from_env_bearer_empty_secret_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bearer mode with an empty secret must fail fast."""
        monkeypatch.setenv("VERITAS_AUTH_MODE", "bearer")
        monkeypatch.delenv("VERITAS_JWT_SECRET", raising=False)

        with pytest.raises(ValueError, match="at least 32 characters"):
            AuthConfig.from_env()

    def test_from_env_basic_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test from_env() with basic mode."""
        monkeypatch.setenv("VERITAS_AUTH_MODE", "basic")

        config = AuthConfig.from_env()

        assert config.mode == "basic"

    def test_from_env_invalid_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test from_env() raises ValueError for invalid mode."""
        monkeypatch.setenv("VERITAS_AUTH_MODE", "oauth")

        with pytest.raises(ValueError, match="Invalid VERITAS_AUTH_MODE"):
            AuthConfig.from_env()

    def test_from_env_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test from_env() is case-insensitive for mode."""
        monkeypatch.setenv("VERITAS_AUTH_MODE", "BEARER")
        monkeypatch.setenv("VERITAS_JWT_SECRET", "b" * 32)

        config = AuthConfig.from_env()

        assert config.mode == "bearer"
