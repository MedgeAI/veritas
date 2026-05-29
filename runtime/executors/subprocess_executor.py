from __future__ import annotations

import shlex
import subprocess

from runtime.executors.base import ExecutionRequest, ExecutionResult


def execute_subprocess(request: ExecutionRequest) -> ExecutionResult:
    try:
        completed = subprocess.run(
            shlex.split(request.command),
            cwd=request.workdir,
            text=True,
            capture_output=True,
            timeout=request.timeout_seconds,
            check=False,
        )
        return ExecutionResult(
            command=request.command,
            workdir=str(request.workdir),
            exit_code=completed.returncode,
            success=completed.returncode == 0,
            timed_out=False,
            stdout_tail=_tail(completed.stdout),
            stderr_tail=_tail(completed.stderr),
        )
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            command=request.command,
            workdir=str(request.workdir),
            exit_code=124,
            success=False,
            timed_out=True,
            stdout_tail=_tail(exc.stdout or ""),
            stderr_tail=_tail(exc.stderr or ""),
        )


def _tail(text: str, limit: int = 400) -> str:
    return text[-limit:]
