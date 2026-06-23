"""Operational metrics endpoint.

Exposes aggregate case/run statistics and uptime as plain JSON.
No authentication required — intended for internal network monitoring.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from ..dependencies import AppDependencies, get_app_dependencies

router = APIRouter(tags=["metrics"])

_start_epoch: float = time.monotonic()


def _uptime_seconds() -> int:
    """Seconds elapsed since the metrics module was first imported."""
    return int(time.monotonic() - _start_epoch)


@router.get("/metrics")
async def get_metrics(
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Return aggregate operational metrics as JSON."""
    store = deps.store
    cases = store.list_cases()
    runs = store.list_all_runs()

    cases_by_status: dict[str, int] = {}
    for case in cases:
        cases_by_status[case.status] = cases_by_status.get(case.status, 0) + 1

    runs_active = 0
    runs_completed = 0
    runs_failed = 0
    runs_interrupted = 0
    for run in runs:
        s = run.status
        if s == "running":
            runs_active += 1
        elif s == "completed":
            runs_completed += 1
        elif s == "failed":
            runs_failed += 1
        elif s == "interrupted":
            runs_interrupted += 1

    return {
        "cases_total": len(cases),
        "cases_by_status": cases_by_status,
        "runs_total": len(runs),
        "runs_active": runs_active,
        "runs_completed": runs_completed,
        "runs_failed": runs_failed,
        "runs_interrupted": runs_interrupted,
        "uptime_seconds": _uptime_seconds(),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
