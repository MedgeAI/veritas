from __future__ import annotations

from runtime.executors.base import ExecutionRequest, ExecutionResult


def execute_docker(request: ExecutionRequest) -> ExecutionResult:
    return ExecutionResult(
        command=request.command,
        workdir=str(request.workdir),
        exit_code=125,
        success=False,
        timed_out=False,
        stdout_tail="",
        stderr_tail="Docker executor is planned but not implemented in the MVP.",
    )
