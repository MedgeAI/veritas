"""FastAPI dependency functions for auth, DB sessions, and case access.

These are thin wrappers that bridge the existing auth/DB infrastructure to
FastAPI's ``Depends()`` injection.  The underlying ``AuthProvider``,
``CaseStore``, and ``database`` modules are unchanged.
"""

from __future__ import annotations

from typing import Generator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .auth import AuthContext, AuthProvider, NoAuthProvider
from .case_store import CaseStore
from .database import create_session_factory
from .models import CaseRecord


class AppDependencies:
    """Bundles shared services for FastAPI dependency injection.

    Created once at app startup and attached to ``app.state``.  Individual
    dependency functions extract what they need from this object.
    """

    def __init__(
        self,
        store: CaseStore,
        auth_provider: AuthProvider,
        engine=None,
    ) -> None:
        self.store = store
        self.auth_provider = auth_provider
        self._engine = engine
        self._session_factory = None
        if engine is not None:
            self._session_factory = create_session_factory(engine)

    def get_session(self) -> Generator[Session, None, None]:
        if self._session_factory is None:
            raise RuntimeError("database not configured")
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()


# ---------------------------------------------------------------------------
# Module-level singleton (set by app.py at startup)
# ---------------------------------------------------------------------------

_deps: AppDependencies | None = None


def set_dependencies(deps: AppDependencies) -> None:
    """Register the global dependency bundle.  Called once by ``app.py``."""
    global _deps
    _deps = deps


def _require_deps() -> AppDependencies:
    if _deps is None:
        raise RuntimeError("AppDependencies not initialised — call set_dependencies() first")
    return _deps


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


def get_app_dependencies(request: Request) -> AppDependencies:
    """Return dependencies attached to the current FastAPI app.

    The module-level fallback is kept for legacy tests/helpers that call
    ``_require_deps()`` directly after ``create_app()``.
    """
    deps = getattr(request.app.state, "dependencies", None)
    if deps is not None:
        return deps
    return _require_deps()


def get_db(
    deps: AppDependencies = Depends(get_app_dependencies),
) -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session."""
    yield from deps.get_session()


def get_auth_context(
    authorization: str | None = Header(None),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> AuthContext:
    """Authenticate the request and return an ``AuthContext``.

    Translates the legacy ``AuthProvider.authenticate(headers_dict)`` call
    into a FastAPI-compatible dependency.
    """
    provider = deps.auth_provider

    if isinstance(provider, NoAuthProvider):
        return AuthContext(user_id="operator", roles=frozenset({"admin"}))

    # Build a headers dict from the FastAPI Header parameter
    headers: dict[str, str] = {}
    if authorization:
        headers["Authorization"] = authorization

    ctx = provider.authenticate(headers)
    if ctx is None:
        challenge = getattr(provider, "challenge_headers", None)
        headers_map = challenge() if callable(challenge) else None
        raise HTTPException(
            status_code=401,
            detail="authentication failed",
            headers=headers_map,
        )
    return ctx


def require_case_access(
    case_id: str,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> CaseRecord:
    """Return the case if the authenticated user owns it; 403 otherwise."""
    try:
        return deps.store.get_case(case_id, user_id=auth.user_id)
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"not the owner of case {case_id}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"case not found: {case_id}")
