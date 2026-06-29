from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from engine.exceptions import ToolExecutionError
from runtime.executors.base import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


def execute_subprocess(request: ExecutionRequest) -> ExecutionResult:
    """Execute a subprocess command with retry, streaming, and progress support."""
    last_result: ExecutionResult | None = None

    for attempt in range(1, request.attempts + 1):
        # Emit progress: starting
        if request.progress_callback:
            request.progress_callback(
                "step_start",
                step=request.step_key,
                title=request.step_title,
                attempt=attempt,
                total_attempts=request.attempts,
            )

        t0 = time.monotonic()

        try:
            if request.stream_output:
                completed = _execute_streaming(request, attempt)
            else:
                completed = _execute_simple(request, attempt)

            elapsed = time.monotonic() - t0
            result = ExecutionResult(
                command=list(request.command),
                workdir=str(request.workdir),
                exit_code=completed.returncode,
                success=completed.returncode == 0,
                timed_out=False,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
                stdout_tail=_tail(completed.stdout or ""),
                stderr_tail=_tail(completed.stderr or ""),
                runtime_seconds=elapsed,
                output_files=_verify_outputs(request)
                if completed.returncode == 0
                else [],
            )

            if request.progress_callback:
                request.progress_callback(
                    "step_result",
                    step=request.step_key,
                    status="ran" if result.success else "failed",
                    exit_code=result.exit_code,
                    runtime_seconds=elapsed,
                )

            if result.success:
                return result

            last_result = result

        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - t0
            result = ExecutionResult(
                command=list(request.command),
                workdir=str(request.workdir),
                exit_code=124,
                success=False,
                timed_out=True,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                stdout_tail=_tail(exc.stdout or ""),
                stderr_tail=_tail(exc.stderr or ""),
                runtime_seconds=elapsed,
            )
            last_result = result

            if request.progress_callback:
                request.progress_callback(
                    "step_result",
                    step=request.step_key,
                    status="failed",
                    exit_code=124,
                    error="timeout",
                    runtime_seconds=elapsed,
                )

        # Retry delay
        if attempt < request.attempts and request.retry_delay_seconds > 0:
            time.sleep(request.retry_delay_seconds)

    # All attempts exhausted -- raise ToolExecutionError
    assert last_result is not None
    raise ToolExecutionError(
        f"Command failed after {request.attempts} attempt(s): {' '.join(request.command[:3])}...",
        tool_id=request.step_key or None,
        exit_code=last_result.exit_code,
        stderr_tail=last_result.stderr_tail,
        timed_out=last_result.timed_out,
    )


def _execute_simple(
    request: ExecutionRequest, attempt: int
) -> subprocess.CompletedProcess:
    return subprocess.run(
        request.command,
        cwd=request.workdir,
        env=request.env,
        text=True,
        capture_output=True,
        timeout=request.timeout_seconds,
        check=False,
        input=request.stdin_data,
    )


def _execute_streaming(
    request: ExecutionRequest, attempt: int
) -> subprocess.CompletedProcess:
    """Execute with real-time stdout streaming via Popen."""
    proc = subprocess.Popen(
        request.command,
        cwd=request.workdir,
        env=request.env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout_lines: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            stdout_lines.append(line)
            if request.progress_callback:
                request.progress_callback(
                    "step_output",
                    step=request.step_key,
                    line=line.rstrip("\n"),
                )
        proc.wait(timeout=request.timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise

    stdout = "".join(stdout_lines)
    stderr = proc.stderr.read() if proc.stderr else ""

    return subprocess.CompletedProcess(
        args=request.command,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _verify_outputs(request: ExecutionRequest) -> list[Path]:
    """Check that expected output files exist."""
    found = []
    for path in request.expected_outputs:
        if path.exists():
            found.append(path)
    return found


def _tail(text: str, limit: int = 1000) -> str:
    return text[-limit:] if len(text) > limit else text
