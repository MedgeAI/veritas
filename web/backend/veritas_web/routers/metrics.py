"""Operational metrics endpoint.

Exposes aggregate case/run statistics and uptime as plain JSON.
Admin-only — aggregate data covers all users' cases.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import AuthContext
from ..dependencies import AppDependencies, get_app_dependencies, get_auth_context
from ..permissions import require_admin

router = APIRouter(tags=["metrics"])

_start_epoch: float = time.monotonic()


def _uptime_seconds() -> int:
    """Seconds elapsed since the metrics module was first imported."""
    return int(time.monotonic() - _start_epoch)


@router.get("/metrics")
async def get_metrics(
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Return aggregate operational metrics as JSON.  Admin only."""
    require_admin(auth)
    summary = await asyncio.get_event_loop().run_in_executor(
        None, deps.store.metrics_summary
    )

    return {
        **summary,
        "uptime_seconds": _uptime_seconds(),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
