"""Authentication system for Veritas Web API.

This module provides authentication primitives and context management.
It supports multiple auth modes (none, bearer, basic) through a pluggable
provider architecture.
"""
from __future__ import annotations

import base64
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import bcrypt
import jwt


@dataclass(frozen=True)
class AuthContext:
    """Authenticated user context.

    Attributes:
        user_id: Unique identifier for the user.
        email: User email address, or ``None`` if unknown.
        roles: Set of role names assigned to the user (e.g., 'admin', 'pi', 'reviewer').
        metadata: Additional user metadata (optional).
    """
    user_id: str
    email: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)
    metadata: dict[str, Any] = field(default_factory=dict)

    def has_role(self, role: str) -> bool:
        """Check if user has a specific role."""
        return role in self.roles

    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return "admin" in self.roles


class AuthProvider(ABC):
    """Abstract base class for authentication providers.

    Subclasses implement specific auth mechanisms (JWT, basic auth, etc.).
    All providers receive the raw HTTP request headers so they can extract
    the credentials they need.
    """

    @abstractmethod
    def authenticate(self, headers: dict[str, Any]) -> AuthContext | None:
        """Authenticate a request from its HTTP headers.

        Args:
            headers: HTTP request headers as a ``dict`` (keys are
                case-sensitive as provided by ``http.server``).

        Returns:
            An ``AuthContext`` on success, ``None`` when the request
            cannot be authenticated.
        """
        ...

    @abstractmethod
    def is_enabled(self) -> bool:
        """Return whether this provider can authenticate requests."""
        ...


class NoAuthProvider(AuthProvider):
    """No-op auth provider for development and testing.

    Returns a default operator with admin role regardless of headers.
    Used when ``VERITAS_AUTH_MODE=none`` (the default).
    """

    def authenticate(self, headers: dict[str, Any]) -> AuthContext:
        """Return the default operator context.

        Args:
            headers: Ignored.

        Returns:
            ``AuthContext`` with ``user_id="operator"`` and ``admin`` role.
        """
        return AuthContext(
            user_id="operator",
            email="operator@veritas.local",
            roles=frozenset({"admin"}),
            metadata={"auth_mode": "none"},
        )

    def is_enabled(self) -> bool:
        """Always returns ``True``."""
        return True


class BearerTokenProvider(AuthProvider):
    """JWT bearer token auth provider.

    Validates HS256-signed tokens issued by an upstream product.  The token
    payload must contain ``userId`` (str), ``userName`` (str), ``exp`` (int),
    and ``iss`` (str).

    Attributes:
        shared_secret: HS256 signing key shared with the token issuer.
        issuer: Expected ``iss`` claim in the token.
    """

    def __init__(self, shared_secret: str, issuer: str = "veritas") -> None:
        self.shared_secret = shared_secret
        self.issuer = issuer

    def authenticate(self, headers: dict[str, Any]) -> AuthContext | None:
        """Extract and validate a Bearer JWT from the ``Authorization`` header.

        Args:
            headers: HTTP request headers.

        Returns:
            ``AuthContext`` on success, ``None`` when the header is missing,
            malformed, or the token fails validation.
        """
        auth_header = headers.get("Authorization") or headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header[len("Bearer "):]
        try:
            payload = jwt.decode(
                token,
                self.shared_secret,
                algorithms=["HS256"],
                issuer=self.issuer,
                options={"require": ["exp", "iss", "userId"]},
            )
        except jwt.InvalidTokenError:
            return None

        user_id = payload.get("userId")
        if not isinstance(user_id, str) or not user_id.strip():
            return None

        return AuthContext(
            user_id=user_id.strip(),
            email=None,
            roles=frozenset({"operator"}),
            metadata={
                "userName": payload.get("userName", ""),
                "source": "main_product",
            },
        )

    def is_enabled(self) -> bool:
        """Always returns ``True``."""
        return True


class BasicAuthProvider(AuthProvider):
    """HTTP Basic Authentication backed by a SQLite user store.

    Passwords are hashed with bcrypt.  The user table is created lazily on
    first access so callers can point at a fresh database file without any
    manual migration step.

    Attributes:
        db_path: Filesystem path to the SQLite database.
    """

    def __init__(self, db_path: str = "veritas_users.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Create the users table if it does not already exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username      TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    email         TEXT,
                    roles         TEXT DEFAULT 'operator',
                    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def authenticate(self, headers: dict[str, Any]) -> AuthContext | None:
        """Authenticate a request via HTTP Basic Auth.

        Args:
            headers: HTTP request headers.

        Returns:
            ``AuthContext`` on success, ``None`` on any failure.
        """
        auth_header = (
            headers.get("Authorization") or headers.get("authorization") or ""
        )
        if not auth_header.startswith("Basic "):
            return None

        try:
            decoded = base64.b64decode(auth_header[len("Basic "):]).decode("utf-8")
        except Exception:
            return None

        parts = decoded.split(":", 1)
        if len(parts) != 2:
            return None
        username, password = parts

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT password_hash, email, roles FROM users WHERE username = ?",
                (username,),
            ).fetchone()

        if row is None:
            return None

        password_hash, email, roles_str = row
        if not bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
            return None

        return AuthContext(
            user_id=username,
            email=email or "",
            roles=frozenset((roles_str or "operator").split(",")),
        )

    def add_user(
        self,
        username: str,
        password: str,
        email: str | None = None,
        roles: str = "operator",
    ) -> None:
        """Hash *password* with bcrypt and upsert the user row."""
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO users
                    (username, password_hash, email, roles)
                VALUES (?, ?, ?, ?)
                """,
                (username, password_hash, email, roles),
            )

    def list_users(self) -> list[dict[str, Any]]:
        """Return all user rows as dicts (excluding password hashes)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT username, email, roles, created_at FROM users ORDER BY username"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_user(self, username: str) -> bool:
        """Delete a user. Returns ``True`` if the row existed."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM users WHERE username = ?", (username,))
        return cursor.rowcount > 0

    def change_password(self, username: str, new_password: str) -> bool:
        """Update the password for *username*. Returns ``True`` if the user existed."""
        password_hash = bcrypt.hashpw(
            new_password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (password_hash, username),
            )
        return cursor.rowcount > 0

    def challenge_headers(self) -> dict[str, str]:
        """Return the ``WWW-Authenticate`` header for a 401 response."""
        return {"WWW-Authenticate": 'Basic realm="Veritas"'}

    def is_enabled(self) -> bool:
        """Always returns ``True``."""
        return True
