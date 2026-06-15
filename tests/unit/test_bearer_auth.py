"""Tests for BearerTokenProvider in veritas_web.auth."""
from __future__ import annotations

import time

import jwt
import pytest

from web.backend.veritas_web.auth import BearerTokenProvider, AuthContext

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
def provider() -> BearerTokenProvider:
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

    def test_valid_jwt_returns_auth_context(self, provider: BearerTokenProvider) -> None:
        token = _make_token(_valid_payload())
        headers = {"Authorization": f"Bearer {token}"}

        ctx = provider.authenticate(headers)

        assert ctx is not None
        assert isinstance(ctx, AuthContext)
        assert ctx.user_id == "507f1f77bcf86cd799439011"
        assert ctx.email is None
        assert "operator" in ctx.roles
        assert ctx.metadata["userName"] == "alice"
        assert ctx.metadata["source"] == "main_product"

    def test_valid_jwt_with_missing_optional_userName(self, provider: BearerTokenProvider) -> None:
        payload = _valid_payload()
        del payload["userName"]
        token = _make_token(payload)
        headers = {"Authorization": f"Bearer {token}"}

        ctx = provider.authenticate(headers)

        assert ctx is not None
        assert ctx.metadata["userName"] == ""

    def test_valid_signature_missing_required_user_id_returns_none(self, provider: BearerTokenProvider) -> None:
        payload = _valid_payload()
        del payload["userId"]
        token = _make_token(payload)
        headers = {"Authorization": f"Bearer {token}"}

        assert provider.authenticate(headers) is None

    def test_valid_signature_empty_required_user_id_returns_none(self, provider: BearerTokenProvider) -> None:
        payload = _valid_payload()
        payload["userId"] = ""
        token = _make_token(payload)
        headers = {"Authorization": f"Bearer {token}"}

        assert provider.authenticate(headers) is None

    def test_valid_signature_missing_required_exp_returns_none(self, provider: BearerTokenProvider) -> None:
        payload = _valid_payload()
        del payload["exp"]
        token = _make_token(payload)
        headers = {"Authorization": f"Bearer {token}"}

        assert provider.authenticate(headers) is None

    def test_invalid_signature_returns_none(self, provider: BearerTokenProvider) -> None:
        token = _make_token(_valid_payload(), secret="wrong-secret")
        headers = {"Authorization": f"Bearer {token}"}

        assert provider.authenticate(headers) is None

    def test_garbage_token_returns_none(self, provider: BearerTokenProvider) -> None:
        headers = {"Authorization": "Bearer not.a.valid.jwt"}

        assert provider.authenticate(headers) is None

    def test_expired_jwt_returns_none(self, provider: BearerTokenProvider) -> None:
        payload = _valid_payload()
        payload["exp"] = int(time.time()) - 60
        token = _make_token(payload)
        headers = {"Authorization": f"Bearer {token}"}

        assert provider.authenticate(headers) is None

    def test_wrong_issuer_returns_none(self, provider: BearerTokenProvider) -> None:
        payload = _valid_payload()
        payload["iss"] = "wrong-issuer"
        token = _make_token(payload)
        headers = {"Authorization": f"Bearer {token}"}

        assert provider.authenticate(headers) is None

    def test_missing_authorization_header_returns_none(self, provider: BearerTokenProvider) -> None:
        assert provider.authenticate({}) is None

    def test_empty_authorization_header_returns_none(self, provider: BearerTokenProvider) -> None:
        assert provider.authenticate({"Authorization": ""}) is None

    def test_non_bearer_authorization_returns_none(self, provider: BearerTokenProvider) -> None:
        headers = {"Authorization": "Basic dXNlcjpwYXNz"}

        assert provider.authenticate(headers) is None

    def test_bearer_prefix_without_token_returns_none(self, provider: BearerTokenProvider) -> None:
        headers = {"Authorization": "Bearer "}

        assert provider.authenticate(headers) is None

    def test_case_insensitive_authorization_header(self, provider: BearerTokenProvider) -> None:
        token = _make_token(_valid_payload())
        headers = {"authorization": f"Bearer {token}"}

        ctx = provider.authenticate(headers)

        assert ctx is not None
        assert ctx.user_id == "507f1f77bcf86cd799439011"

    def test_is_enabled_returns_true(self, provider: BearerTokenProvider) -> None:
        assert provider.is_enabled() is True
