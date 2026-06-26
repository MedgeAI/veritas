"""User management API.

Provides admin-only CRUD endpoints for user stores.
Supports three auth backends:

- ``basic``: SQLite-backed user store (username/password).
- ``cloudflare``: PostgreSQL ``cf_users`` table (email-based, no passwords).
- ``none``: Mock provider with a single operator user (dev/demo).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import AuthContext, BasicAuthProvider, CloudflareAccessProvider
from ..dependencies import AppDependencies, get_app_dependencies, get_auth_context
from ..permissions import require_admin

router = APIRouter(prefix="/users", tags=["users"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateUserRequest(BaseModel):
    """Payload for creating a new user (basic mode only)."""

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1)
    email: str | None = None
    roles: str = "operator"


class UpdateRolesRequest(BaseModel):
    """Payload for updating a user's roles."""

    email: str | None = None
    roles: str | None = None


class ChangePasswordRequest(BaseModel):
    """Payload for changing a user's password (basic mode only)."""

    password: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_basic_provider(deps: AppDependencies) -> BasicAuthProvider:
    """Return the BasicAuthProvider, or a mock for no-auth mode."""
    from ..auth import NoAuthProvider

    provider = deps.auth_provider
    if isinstance(provider, NoAuthProvider):

        class MockBasicProvider:
            def list_users(self):
                return [
                    {
                        "username": "operator",
                        "email": "operator@veritas.local",
                        "roles": ["admin"],
                        "created_at": "2026-01-01T00:00:00",
                    }
                ]

            def add_user(self, username, password, email=None, roles="operator"):
                return None

            def delete_user(self, username):
                return True

            def change_password(self, username, new_password):
                return True

        return MockBasicProvider()  # type: ignore[return-value]
    if not isinstance(provider, BasicAuthProvider):
        raise HTTPException(
            status_code=500,
            detail="user management requires BasicAuthProvider",
        )
    return provider


def _get_cf_provider(deps: AppDependencies) -> CloudflareAccessProvider:
    """Return the CloudflareAccessProvider."""
    provider = deps.auth_provider
    if not isinstance(provider, CloudflareAccessProvider):
        raise HTTPException(
            status_code=500,
            detail="this endpoint requires Cloudflare Access auth mode",
        )
    return provider


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_users(
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> list[dict[str, Any]]:
    """Return all users (admin only)."""
    require_admin(auth)

    if isinstance(deps.auth_provider, CloudflareAccessProvider):
        cf = _get_cf_provider(deps)
        return cf.list_users()

    provider = _get_basic_provider(deps)
    return provider.list_users()


@router.post("", status_code=201)
async def create_user(
    body: CreateUserRequest,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, str]:
    """Create a new user (basic mode only — Cloudflare auto-registers)."""
    require_admin(auth)

    if isinstance(deps.auth_provider, CloudflareAccessProvider):
        raise HTTPException(
            status_code=400,
            detail="user creation is not needed in Cloudflare mode — "
            "users are auto-registered on first access",
        )

    provider = _get_basic_provider(deps)
    provider.add_user(
        username=body.username,
        password=body.password,
        email=body.email,
        roles=body.roles,
    )
    return {"status": "created", "username": body.username}


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateRolesRequest,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, str]:
    """Update a user's roles (admin only).

    In basic mode, *user_id* is the username.
    In cloudflare mode, *user_id* is the email address.
    """
    require_admin(auth)

    if isinstance(deps.auth_provider, CloudflareAccessProvider):
        cf = _get_cf_provider(deps)
        if body.roles is None:
            raise HTTPException(status_code=400, detail="roles is required")
        if not cf.update_user_roles(user_id, body.roles):
            raise HTTPException(status_code=404, detail=f"user not found: {user_id}")
        return {"status": "updated", "email": user_id}

    provider = _get_basic_provider(deps)
    users = {u["username"]: u for u in provider.list_users()}
    if user_id not in users:
        raise HTTPException(status_code=404, detail=f"user not found: {user_id}")

    current = users[user_id]
    email = body.email if body.email is not None else current.get("email")
    roles = body.roles if body.roles is not None else current.get("roles")
    if isinstance(roles, list):
        roles = ",".join(roles)

    existed = provider.update_user(user_id, email=email, roles=roles)
    if not existed:
        raise HTTPException(status_code=404, detail=f"user not found: {user_id}")
    return {"status": "updated", "username": user_id}


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, str]:
    """Delete a user (admin only)."""
    require_admin(auth)

    if isinstance(deps.auth_provider, CloudflareAccessProvider):
        cf = _get_cf_provider(deps)
        if not cf.delete_user(user_id):
            raise HTTPException(status_code=404, detail=f"user not found: {user_id}")
        return {"status": "deleted", "email": user_id}

    provider = _get_basic_provider(deps)
    if not provider.delete_user(user_id):
        raise HTTPException(status_code=404, detail=f"user not found: {user_id}")
    return {"status": "deleted", "username": user_id}


@router.post("/{username}/password")
async def change_password(
    username: str,
    body: ChangePasswordRequest,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, str]:
    """Change a user's password.  Basic mode only.

    Allowed for admins or the user themselves.
    """
    if isinstance(deps.auth_provider, CloudflareAccessProvider):
        raise HTTPException(
            status_code=400,
            detail="password management is handled by Cloudflare Access",
        )

    if auth.user_id != username and not auth.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")
    provider = _get_basic_provider(deps)
    if not provider.change_password(username, body.password):
        raise HTTPException(status_code=404, detail=f"user not found: {username}")
    return {"status": "password_updated", "username": username}
