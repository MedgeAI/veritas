"""Configuration for Veritas authentication system.

Loads auth settings from environment variables with sensible defaults
for development.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .auth import AuthProvider, BasicAuthProvider, BearerTokenProvider, NoAuthProvider


AuthMode = Literal["none", "bearer", "basic"]


@dataclass(frozen=True)
class AuthConfig:
    """Authentication configuration.

    Attributes:
        mode: Auth mode ('none', 'bearer', 'basic').
        jwt_shared_secret: Secret key for JWT signing/verification.
        jwt_issuer: Expected JWT issuer claim.
        sqlite_db_path: Path to SQLite database for user storage.
    """
    mode: AuthMode = "none"
    jwt_shared_secret: str = ""
    jwt_issuer: str = "veritas"
    sqlite_db_path: Path = Path("web_data/users.db")

    @classmethod
    def from_env(cls) -> AuthConfig:
        """Load config from environment variables.

        Environment variables:
            VERITAS_AUTH_MODE: Auth mode ('none', 'bearer', 'basic'). Default: 'none'.
            VERITAS_JWT_SECRET: JWT shared secret. Default: empty string.
            VERITAS_JWT_ISSUER: JWT issuer claim. Default: 'veritas'.
            VERITAS_USERS_DB: Path to SQLite users database. Default: 'web_data/users.db'.

        Returns:
            AuthConfig instance with values from environment.

        Raises:
            ValueError: If VERITAS_AUTH_MODE is invalid.
        """
        mode = os.getenv("VERITAS_AUTH_MODE", "none").lower()
        if mode not in ("none", "bearer", "basic"):
            raise ValueError(
                f"Invalid VERITAS_AUTH_MODE: {mode!r}. "
                "Must be 'none', 'bearer', or 'basic'."
            )

        return cls(
            mode=mode,
            jwt_shared_secret=os.getenv("VERITAS_JWT_SECRET", ""),
            jwt_issuer=os.getenv("VERITAS_JWT_ISSUER", "veritas"),
            sqlite_db_path=Path(os.getenv("VERITAS_USERS_DB", "web_data/users.db")),
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
    else:
        raise ValueError(f"Unknown auth mode: {config.mode!r}")
