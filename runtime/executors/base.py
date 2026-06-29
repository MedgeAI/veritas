from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class ExecutionRequest:
    """Request to execute a command in a subprocess."""

    command: list[str]  # argv list (NOT a string)
    workdir: Path
    timeout_seconds: int = 30
    env: dict[str, str] | None = None
    expected_outputs: list[Path] = field(default_factory=list)
    stream_output: bool = False
    progress_callback: Callable[..., None] | None = None
    attempts: int = 1
    retry_delay_seconds: float = 0.0
    step_key: str = ""
    step_title: str = ""
    stdin_data: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    """Result of a subprocess execution."""

    command: list[str]
    workdir: str
    exit_code: int
    success: bool
    timed_out: bool
    stdout: str
    stderr: str
    stdout_tail: str
    stderr_tail: str
    runtime_seconds: float = 0.0
    output_files: list[Path] = field(default_factory=list)
