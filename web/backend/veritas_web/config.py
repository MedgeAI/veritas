"""Configuration for Veritas authentication system.

Loads auth settings from environment variables with sensible defaults
for development.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .auth import (
    AuthProvider,
    BasicAuthProvider,
    BearerTokenProvider,
    CloudflareAccessProvider,
    NoAuthProvider,
)


AuthMode = Literal["none", "bearer", "basic", "cloudflare"]


@dataclass(frozen=True)
class AuthConfig:
    """Authentication configuration.

    Attributes:
        mode: Auth mode ('none', 'bearer', 'basic', 'cloudflare').
        jwt_shared_secret: Secret key for JWT signing/verification.
        jwt_issuer: Expected JWT issuer claim.
        sqlite_db_path: Path to SQLite database for user storage.
        cf_team_name: Cloudflare Access team name (for JWKS URL).
        cf_audience_tag: Cloudflare Access Application AUD tag.
        cf_bootstrap_admins: Emails that auto-promote to admin on first access.
    """

    mode: AuthMode = "none"
    jwt_shared_secret: str = ""
    jwt_issuer: str = "veritas"
    sqlite_db_path: Path = Path("web_data/users.db")
    cf_team_name: str = ""
    cf_audience_tag: str = ""
    cf_bootstrap_admins: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> AuthConfig:
        """Load config from environment variables.

        Environment variables:
            VERITAS_AUTH_MODE: Auth mode ('none', 'bearer', 'basic', 'cloudflare').
            VERITAS_JWT_SECRET: JWT shared secret. Default: empty string.
            VERITAS_JWT_ISSUER: JWT issuer claim. Default: 'veritas'.
            VERITAS_USERS_DB: Path to SQLite users database.
            VERITAS_CF_TEAM_NAME: Cloudflare Access team name.
            VERITAS_CF_AUDIENCE_TAG: Cloudflare Access AUD tag.
            VERITAS_BOOTSTRAP_ADMIN_EMAILS: Comma-separated admin emails.

        Returns:
            AuthConfig instance with values from environment.

        Raises:
            ValueError: If VERITAS_AUTH_MODE is invalid.
            ValueError: If bearer mode but JWT secret is too short.
            ValueError: If cloudflare mode but team_name or audience_tag missing.
        """
        mode = os.getenv("VERITAS_AUTH_MODE", "none").lower()
        if mode not in ("none", "bearer", "basic", "cloudflare"):
            raise ValueError(
                f"Invalid VERITAS_AUTH_MODE: {mode!r}. "
                "Must be 'none', 'bearer', 'basic', or 'cloudflare'."
            )

        secret = os.getenv("VERITAS_JWT_SECRET", "")
        if mode == "bearer" and len(secret) < 32:
            raise ValueError(
                "VERITAS_JWT_SECRET must be at least 32 characters when "
                "VERITAS_AUTH_MODE=bearer. "
                "Set a strong secret or switch to VERITAS_AUTH_MODE=none."
            )

        cf_team_name = os.getenv("VERITAS_CF_TEAM_NAME", "")
        cf_audience_tag = os.getenv("VERITAS_CF_AUDIENCE_TAG", "")
        if mode == "cloudflare":
            if not cf_team_name:
                raise ValueError(
                    "VERITAS_CF_TEAM_NAME is required when "
                    "VERITAS_AUTH_MODE=cloudflare."
                )
            if not cf_audience_tag:
                raise ValueError(
                    "VERITAS_CF_AUDIENCE_TAG is required when "
                    "VERITAS_AUTH_MODE=cloudflare."
                )

        bootstrap_raw = os.getenv("VERITAS_BOOTSTRAP_ADMIN_EMAILS", "")
        bootstrap_admins = [
            e.strip().lower() for e in bootstrap_raw.split(",") if e.strip()
        ]

        return cls(
            mode=mode,
            jwt_shared_secret=secret,
            jwt_issuer=os.getenv("VERITAS_JWT_ISSUER", "veritas"),
            sqlite_db_path=Path(os.getenv("VERITAS_USERS_DB", "web_data/users.db")),
            cf_team_name=cf_team_name,
            cf_audience_tag=cf_audience_tag,
            cf_bootstrap_admins=bootstrap_admins,
        )


def create_auth_provider(config: AuthConfig) -> AuthProvider:
    """Instantiate an auth provider based on the configuration mode.

    Args:
        config: Authentication configuration.

    Returns:
        An ``AuthProvider`` instance matching ``config.mode``.
    """
    if config.mode == "none":
        return NoAuthProvider()
    elif config.mode == "bearer":
        return BearerTokenProvider(config.jwt_shared_secret, config.jwt_issuer)
    elif config.mode == "basic":
        return BasicAuthProvider(str(config.sqlite_db_path))
    elif config.mode == "cloudflare":
        return CloudflareAccessProvider(
            team_name=config.cf_team_name,
            aud=config.cf_audience_tag,
            bootstrap_admins=config.cf_bootstrap_admins,
        )
    else:
        raise ValueError(f"Unknown auth mode: {config.mode!r}")
