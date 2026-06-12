"""Agent Function Runtime — AgentStepRunner.

Replaces the legacy ``_run_opencode_json()`` in ``opencode_agent.py``
with structured error classification, log artifact writing, and a
unified interface that returns ``AgentRunResult`` from ``agent_models``.

See PRD: prd/opencode-agent-function-runtime.md
"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from engine.investigation.agent_models import AgentErrorCategory, AgentRunResult


def extract_json(text: str) -> dict:
    from engine.investigation.opencode_agent import extract_json as _extract_json

    return _extract_json(text)


class AgentStepRunner:
    """Invoke opencode subprocess with retry, validation, and error classification.

    The runner builds the opencode command, manages retries with error
    feedback, classifies failures into structured categories, and writes
    log artifacts for observability.
    """

    def __init__(
        self,
        project_root: Path,
        model: str = "dashscope/qwen3.7-max",
        opencode_bin: str | Path = "opencode",
        env: dict[str, str] | None = None,
    ):
        self.project_root = Path(project_root)
        self.model = model
        self.opencode_bin = str(opencode_bin)
        self.env = env or {}

    def run(
        self,
        role: str,
        prompt: str,
        output_validator: Callable[[dict], dict],
        timeout_seconds: int = 300,
        max_retries: int = 2,
        files: list[Path] | None = None,
        context_pack_path: Path | None = None,
        log_dir: Path | None = None,
    ) -> AgentRunResult:
        """Execute opencode with retry and structured error handling.

        Returns AgentRunResult with status="success" on first valid output,
        or status="failed" after all retries exhausted.
        """
        command = [
            self.opencode_bin,
            "run",
            prompt,
            "--format",
            "json",
            "--model",
            self.model,
            "--dir",
            str(self.project_root),
        ]

        env = dict(self.env)
        env.setdefault("XDG_DATA_HOME", str(self.project_root / ".opencode" / "data"))

        for path in files or []:
            if Path(path).exists():
                command.extend(["--file", str(path)])

        if context_pack_path and Path(context_pack_path).exists():
            command.extend(["--file", str(context_pack_path)])

        last_error_category: AgentErrorCategory | None = None
        last_detail = ""
        last_stdout = ""
        last_stderr = ""
        start_all = time.monotonic()

        for attempt in range(max_retries + 1):
            attempt_prompt = prompt
            if attempt and last_detail:
                attempt_prompt = (
                    f"{prompt}\n\nPrevious attempt failed: {last_detail}\n"
                    "Please fix the issue and return valid JSON."
                )
                command[2] = attempt_prompt

            try:
                completed = subprocess.run(
                    command,
                    cwd=self.project_root,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                last_error_category = "timeout"
                last_detail = f"opencode timed out after {timeout_seconds}s"
                last_stdout = ""
                last_stderr = ""
                continue
            except OSError as exc:
                last_error_category = "non_zero_exit"
                last_detail = f"opencode launch failed: {exc}"
                last_stdout = ""
                last_stderr = ""
                break

            last_stdout = completed.stdout or ""
            last_stderr = completed.stderr or ""

            if completed.returncode != 0:
                last_error_category = self._classify_exit_error(last_stderr)
                last_detail = (
                    f"opencode exit_code={completed.returncode} "
                    f"stderr_tail={last_stderr[-1000:]!r}"
                )
                continue

            try:
                parsed = extract_json(last_stdout)
            except Exception as exc:
                last_error_category = "schema_validation"
                last_detail = f"JSON extraction failed: {type(exc).__name__}: {exc}"
                continue

            try:
                validated = output_validator(parsed)
            except ValueError as exc:
                last_error_category = "schema_validation"
                last_detail = f"validation failed: {exc}"
                continue

            total_runtime = time.monotonic() - start_all
            log_ref = None
            if log_dir:
                log_ref = self._write_log_artifact(
                    log_dir=log_dir,
                    role=role,
                    command=command,
                    stdout=last_stdout,
                    stderr=last_stderr,
                    error_category=None,
                    attempt=attempt,
                )

            return AgentRunResult(
                status="success",
                role=role,
                output=validated,
                error_category=None,
                runtime_seconds=total_runtime,
                log_ref=log_ref,
                metadata={
                    "model": self.model,
                    "runtime_seconds": total_runtime,
                    "attempts": attempt + 1,
                },
            )

        total_runtime = time.monotonic() - start_all
        log_ref = None
        if log_dir:
            log_ref = self._write_log_artifact(
                log_dir=log_dir,
                role=role,
                command=command,
                stdout=last_stdout,
                stderr=last_stderr,
                error_category=last_error_category or "non_zero_exit",
                attempt=max_retries,
            )

        return AgentRunResult(
            status="failed",
            role=role,
            output=None,
            error_category=last_error_category or "non_zero_exit",
            runtime_seconds=total_runtime,
            log_ref=log_ref,
            metadata={
                "model": self.model,
                "runtime_seconds": total_runtime,
                "attempts": max_retries + 1,
                "last_detail": last_detail,
            },
        )

    def _classify_exit_error(self, stderr: str) -> AgentErrorCategory:
        """Classify non-zero exit based on stderr content."""
        stderr_lower = stderr.lower()
        if "permission" in stderr_lower or "auto-reject" in stderr_lower:
            return "permission_rejected"
        if "error" in stderr_lower or "failed" in stderr_lower:
            return "model_failure"
        return "non_zero_exit"

    def _write_log_artifact(
        self,
        *,
        log_dir: Path,
        role: str,
        command: list[str],
        stdout: str,
        stderr: str,
        error_category: AgentErrorCategory | None,
        attempt: int,
    ) -> str:
        """Write log artifact and return relative path as log_ref."""
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_filename = f"{role}_{timestamp}.log"
        log_path = log_dir / log_filename

        content_lines = [
            "=== Agent Step Log ===",
            f"Role: {role}",
            f"Attempt: {attempt + 1}",
            f"Error Category: {error_category or 'none'}",
            f"Command: {' '.join(command)}",
            "",
            "=== STDOUT ===",
            stdout,
            "",
            "=== STDERR ===",
            stderr,
        ]

        log_path.write_text("\n".join(content_lines), encoding="utf-8")

        try:
            return str(log_path.relative_to(self.project_root))
        except ValueError:
            return str(log_path)
