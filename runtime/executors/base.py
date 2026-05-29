from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExecutionRequest:
    command: str
    workdir: Path
    timeout_seconds: int = 30


@dataclass
class ExecutionResult:
    command: str
    workdir: str
    exit_code: int
    success: bool
    timed_out: bool
    stdout_tail: str
    stderr_tail: str
