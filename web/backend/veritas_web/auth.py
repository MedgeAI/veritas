"""Authentication system for Veritas Web API.

This module provides authentication primitives and context management.
It supports multiple auth modes (none, bearer, basic, cloudflare) through
a pluggable provider architecture.
"""

from __future__ import annotations

import base64
import logging
import sqlite3
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import bcrypt
import jwt

logger = logging.getLogger(__name__)


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

        token = auth_header[len("Bearer ") :]
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
        auth_header = headers.get("Authorization") or headers.get("authorization") or ""
        if not auth_header.startswith("Basic "):
            return None

        try:
            decoded = base64.b64decode(auth_header[len("Basic ") :]).decode("utf-8")
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
        result = []
        for row in rows:
            user_dict = dict(row)
            # Convert roles from comma-separated string to list
            roles_str = user_dict.get("roles", "")
            user_dict["roles"] = [r.strip() for r in roles_str.split(",") if r.strip()] if roles_str else []
            result.append(user_dict)
        return result

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

    def update_user(
        self,
        username: str,
        email: str | None = None,
        roles: str | None = None,
    ) -> bool:
        """Update email and/or roles for *username*. Returns ``True`` if the user existed."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE users SET email = ?, roles = ? WHERE username = ?",
                (email, roles, username),
            )
        return cursor.rowcount > 0

    def challenge_headers(self) -> dict[str, str]:
        """Return the ``WWW-Authenticate`` header for a 401 response."""
        return {"WWW-Authenticate": 'Basic realm="Veritas"'}

    def is_enabled(self) -> bool:
        """Always returns ``True``."""
        return True


class CloudflareAccessProvider(AuthProvider):
    """Cloudflare Access JWT authentication.

    Validates RS256-signed JWTs issued by Cloudflare Access.  The public
    keys are fetched from the Cloudflare JWKS endpoint and cached in memory
    with a 1-hour TTL.

    On first contact the user is auto-registered in the ``cf_users`` table
    with ``roles='operator'``.  If their email matches a bootstrap admin
    address they are promoted to ``admin`` instead.

    Attributes:
        team_name: Cloudflare Access team name (used to build JWKS URL).
        aud: Expected ``aud`` claim (Access Application AUD tag).
        bootstrap_admins: Emails auto-promoted to admin on first access.
    """

    _JWKS_TTL_SECONDS = 3600  # 1 hour

    def __init__(
        self,
        team_name: str,
        aud: str,
        bootstrap_admins: list[str] | None = None,
    ) -> None:
        self._team_name = team_name
        self._aud = aud
        self._jwks_url = (
            f"https://{team_name}.cloudflareaccess.com/cdn-cgi/access/certs"
        )
        self._bootstrap_admins = [e.lower() for e in (bootstrap_admins or [])]
        self._jwks_data: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0
        self._engine: Any = None  # lazily bound on first authenticate()

    # -- AuthProvider interface ------------------------------------------

    def authenticate(self, headers: dict[str, Any]) -> AuthContext | None:
        """Validate Cloudflare Access JWT from request headers.

        Reads ``cf-access-jwt-assertion`` (injected by cloudflared tunnel
        into every origin-bound request).
        """
        token = headers.get("cf-access-jwt-assertion")
        if not token:
            return None

        claims = self._verify_jwt(token)
        if claims is None:
            return None

        email = (claims.get("email") or "").lower()
        if not email:
            logger.warning("Cloudflare JWT missing email claim")
            return None

        self._ensure_user(email, claims.get("name"))
        roles = self._load_roles(email)

        return AuthContext(
            user_id=email,
            email=email,
            roles=roles,
            metadata={"source": "cloudflare_access"},
        )

    def is_enabled(self) -> bool:
        return True

    # -- JWT verification ------------------------------------------------

    def _verify_jwt(self, token: str) -> dict[str, Any] | None:
        """Verify RS256 signature and standard claims.

        Returns the decoded payload on success, ``None`` on any failure.
        On signature failure the JWKS cache is refreshed once to handle
        key rotation.
        """
        for attempt in range(2):
            jwks = self._get_jwks(force_refresh=(attempt == 1))
            if jwks is None:
                return None
            try:
                signing_key = self._find_signing_key(token, jwks)
                if signing_key is None:
                    if attempt == 0:
                        continue  # refresh JWKS and retry
                    return None
                return jwt.decode(
                    token,
                    signing_key,
                    algorithms=["RS256"],
                    audience=self._aud,
                    issuer=f"https://{self._team_name}.cloudflareaccess.com",
                    options={"require": ["exp", "iss", "aud", "email"]},
                )
            except jwt.InvalidTokenError as exc:
                logger.debug("JWT verification failed (attempt %d): %s", attempt + 1, exc)
                if attempt == 1:
                    return None
        return None

    def _get_jwks(self, *, force_refresh: bool = False) -> dict[str, Any] | None:
        """Fetch and cache the Cloudflare JWKS document."""
        now = time.monotonic()
        if (
            not force_refresh
            and self._jwks_data is not None
            and (now - self._jwks_fetched_at) < self._JWKS_TTL_SECONDS
        ):
            return self._jwks_data

        try:
            import json
            import urllib.request

            with urllib.request.urlopen(self._jwks_url, timeout=10) as resp:
                self._jwks_data = json.loads(resp.read())
            self._jwks_fetched_at = now
            return self._jwks_data
        except Exception as exc:
            logger.error("Failed to fetch JWKS from %s: %s", self._jwks_url, exc)
            return None

    @staticmethod
    def _find_signing_key(token: str, jwks: dict[str, Any]) -> Any:
        """Locate the matching public key from JWKS for the given token."""
        try:
            unverified = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            return None
        kid = unverified.get("kid")
        if not kid:
            return None

        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                return jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
        return None

    # -- User management (cf_users table) --------------------------------

    def _get_engine(self) -> Any:
        """Return the SQLAlchemy engine, lazily initialising on first call."""
        if self._engine is None:
            from .database import create_db_engine

            self._engine = create_db_engine()
        return self._engine

    def _ensure_user(self, email: str, display_name: str | None) -> None:
        """Auto-register user on first access."""
        from .models import CloudflareUserModel

        engine = self._get_engine()
        with engine.connect() as conn:
            existing = conn.execute(
                CloudflareUserModel.__table__.select().where(
                    CloudflareUserModel.__table__.c.email == email
                )
            ).fetchone()

            if existing is None:
                roles = "admin" if email in self._bootstrap_admins else "operator"
                conn.execute(
                    CloudflareUserModel.__table__.insert().values(
                        email=email,
                        display_name=display_name or "",
                        roles=roles,
                    )
                )
                conn.commit()
                logger.info(
                    "Auto-registered Cloudflare user %s with role=%s", email, roles
                )
            elif display_name and not existing.display_name:
                conn.execute(
                    CloudflareUserModel.__table__.update()
                    .where(CloudflareUserModel.__table__.c.email == email)
                    .values(display_name=display_name)
                )
                conn.commit()

    def _load_roles(self, email: str) -> frozenset[str]:
        """Load roles for *email* from cf_users table."""
        from .models import CloudflareUserModel

        engine = self._get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                CloudflareUserModel.__table__.select().where(
                    CloudflareUserModel.__table__.c.email == email
                )
            ).fetchone()

        if row is None:
            return frozenset({"operator"})
        roles_str = row.roles or "operator"
        return frozenset(r.strip() for r in roles_str.split(",") if r.strip())

    # -- User management API (for /api/users router) ---------------------

    def list_users(self) -> list[dict[str, Any]]:
        """Return all cf_users rows as dicts."""
        from .models import CloudflareUserModel

        engine = self._get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                CloudflareUserModel.__table__.select().order_by(
                    CloudflareUserModel.__table__.c.email
                )
            ).fetchall()
        return [
            {
                "email": row.email,
                "display_name": row.display_name or "",
                "roles": [
                    r.strip()
                    for r in (row.roles or "operator").split(",")
                    if r.strip()
                ],
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def update_user_roles(self, email: str, roles: str) -> bool:
        """Update roles for *email*. Returns ``True`` if the user existed."""
        from .models import CloudflareUserModel

        engine = self._get_engine()
        with engine.connect() as conn:
            cursor = conn.execute(
                CloudflareUserModel.__table__.update()
                .where(CloudflareUserModel.__table__.c.email == email)
                .values(roles=roles)
            )
            conn.commit()
        return cursor.rowcount > 0

    def delete_user(self, email: str) -> bool:
        """Delete a user record. Returns ``True`` if the row existed."""
        from .models import CloudflareUserModel

        engine = self._get_engine()
        with engine.connect() as conn:
            cursor = conn.execute(
                CloudflareUserModel.__table__.delete().where(
                    CloudflareUserModel.__table__.c.email == email
                )
            )
            conn.commit()
        return cursor.rowcount > 0
