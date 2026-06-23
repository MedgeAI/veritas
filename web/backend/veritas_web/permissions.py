"""Permission helpers for the Veritas Web API.

Thin guards that turn role checks into HTTP 403 responses.  Routers call
these before performing privileged operations so that authorisation logic
lives in one place instead of being duplicated across every endpoint.
"""

from __future__ import annotations

from fastapi import HTTPException

from .auth import AuthContext


def require_admin(auth: AuthContext) -> None:
    """Raise 403 if *auth* does not carry the ``admin`` role."""
    if not auth.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")


def require_owner_or_admin(auth: AuthContext, case_owner: str) -> None:
    """Raise 403 unless *auth* is the owner or an admin."""
    if auth.user_id != case_owner and not auth.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")
