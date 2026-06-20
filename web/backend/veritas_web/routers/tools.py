"""Tool catalog and health endpoints."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import AuthContext
from ..dependencies import AppDependencies, get_app_dependencies, get_auth_context
from ..diagnostics import run_full_diagnostics
from ..embeddings import SSCDEncoder
from ..tool_catalog import get_investigation_catalog, seed_tool_registry

router = APIRouter(tags=["tools"])


@router.get("/tools/catalog")
async def tool_catalog(
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Return the list of agent-selectable deterministic tools."""
    if deps._session_factory is None:
        return {"tools": []}

    session = deps._session_factory()
    try:
        seed_tool_registry(session)
        tools = get_investigation_catalog(session)
        return {"tools": tools}
    finally:
        session.close()


@router.get("/tools/health")
async def tools_health(
    auth: AuthContext = Depends(get_auth_context),
) -> dict[str, Any]:
    """Health check for tool infrastructure (Docker, GPU, model weights)."""
    docker = _command_health(["docker", "info", "--format", "{{json .ServerVersion}}"])
    gpu = _command_health(["nvidia-smi", "-L"])
    encoder = SSCDEncoder()
    return {
        "docker_available": docker["ok"],
        "gpu_available": gpu["ok"],
        "sscd_model_available": encoder.available,
        "details": {
            "docker": docker,
            "gpu": gpu,
            "sscd_model_path": str(encoder._model_path),
        },
    }


@router.get("/diag")
async def diag(
    auth: AuthContext = Depends(get_auth_context),
) -> dict[str, Any]:
    """Full diagnostic report — infrastructure, deps, models, env, filesystem."""
    return run_full_diagnostics().to_dict()


def _command_health(args: list[str], *, timeout_seconds: float = 2.0) -> dict[str, Any]:
    executable = shutil.which(args[0])
    if executable is None:
        return {"ok": False, "detail": f"{args[0]} not found on PATH"}
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"{args[0]} timed out after {timeout_seconds}s"}
    except OSError as exc:
        return {"ok": False, "detail": str(exc)}
    detail = (result.stdout or result.stderr).strip()
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "detail": detail[:500],
    }
