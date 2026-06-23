"""User management API.

Provides admin-only CRUD endpoints for the SQLite-backed user store.
All routes require the ``admin`` role except ``POST /users/{username}/password``
which also allows the user to change their own password.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import AuthContext, BasicAuthProvider
from ..dependencies import AppDependencies, get_app_dependencies, get_auth_context
from ..permissions import require_admin

router = APIRouter(prefix="/users", tags=["users"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateUserRequest(BaseModel):
    """Payload for creating a new user."""

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1)
    email: str | None = None
    roles: str = "operator"


class UpdateUserRequest(BaseModel):
    """Payload for updating an existing user."""

    email: str | None = None
    roles: str | None = None


class ChangePasswordRequest(BaseModel):
    """Payload for changing a user's password."""

    password: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_basic_provider(deps: AppDependencies) -> BasicAuthProvider:
    """Return the auth provider, or a mock provider for no-auth mode."""
    from ..auth import NoAuthProvider
    provider = deps.auth_provider
    if isinstance(provider, NoAuthProvider):
        # In no-auth mode, return a mock provider with a single operator user
        # This allows the admin UI to work for demonstration purposes
        class MockBasicProvider:
            def list_users(self):
                return [{"username": "operator", "email": "operator@veritas.local", "roles": ["admin"], "created_at": "2026-01-01T00:00:00"}]
            def add_user(self, username, password, email=None, roles="operator"):
                return None  # No-op in no-auth mode
            def delete_user(self, username):
                return True
            def change_password(self, username, new_password):
                return True
        return MockBasicProvider()
    if not isinstance(provider, BasicAuthProvider):
        raise HTTPException(
            status_code=500,
            detail="user management requires BasicAuthProvider",
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
    provider = _get_basic_provider(deps)
    return provider.list_users()


@router.post("", status_code=201)
async def create_user(
    body: CreateUserRequest,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, str]:
    """Create a new user (admin only)."""
    require_admin(auth)
    provider = _get_basic_provider(deps)
    provider.add_user(
        username=body.username,
        password=body.password,
        email=body.email,
        roles=body.roles,
    )
    return {"status": "created", "username": body.username}


@router.put("/{username}")
async def update_user(
    username: str,
    body: UpdateUserRequest,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, str]:
    """Update a user's email and/or roles (admin only)."""
    require_admin(auth)
    provider = _get_basic_provider(deps)

    # Resolve current values for fields the caller did not supply.
    users = {u["username"]: u for u in provider.list_users()}
    if username not in users:
        raise HTTPException(status_code=404, detail=f"user not found: {username}")

    current = users[username]
    email = body.email if body.email is not None else current.get("email")
    roles = body.roles if body.roles is not None else current.get("roles")
    # DB stores roles as comma-separated text; serialize list before binding.
    if isinstance(roles, list):
        roles = ",".join(roles)

    existed = provider.update_user(username, email=email, roles=roles)
    if not existed:
        raise HTTPException(status_code=404, detail=f"user not found: {username}")
    return {"status": "updated", "username": username}


@router.delete("/{username}")
async def delete_user(
    username: str,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, str]:
    """Delete a user (admin only)."""
    require_admin(auth)
    provider = _get_basic_provider(deps)
    if not provider.delete_user(username):
        raise HTTPException(status_code=404, detail=f"user not found: {username}")
    return {"status": "deleted", "username": username}


@router.post("/{username}/password")
async def change_password(
    username: str,
    body: ChangePasswordRequest,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, str]:
    """Change a user's password.  Allowed for admins or the user themselves."""
    if auth.user_id != username and not auth.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")
    provider = _get_basic_provider(deps)
    if not provider.change_password(username, body.password):
        raise HTTPException(status_code=404, detail=f"user not found: {username}")
    return {"status": "password_updated", "username": username}
