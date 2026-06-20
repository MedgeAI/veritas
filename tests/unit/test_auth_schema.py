"""Tests for authentication schema and configuration.

Verifies AuthContext creation, NoAuthProvider behavior, and AuthConfig.from_env().
"""

from __future__ import annotations

import pytest

from web.backend.veritas_web.auth import (
    AuthContext,
    NoAuthProvider,
)
from web.backend.veritas_web.config import AuthConfig


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
        monkeypatch.setenv("VERITAS_JWT_SECRET", "my-secret-key")
        monkeypatch.setenv("VERITAS_JWT_ISSUER", "my-issuer")
        monkeypatch.setenv("VERITAS_USERS_DB", "/tmp/test_users.db")

        config = AuthConfig.from_env()

        assert config.mode == "bearer"
        assert config.jwt_shared_secret == "my-secret-key"
        assert config.jwt_issuer == "my-issuer"
        assert str(config.sqlite_db_path) == "/tmp/test_users.db"

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

        config = AuthConfig.from_env()

        assert config.mode == "bearer"
