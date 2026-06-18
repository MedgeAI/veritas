"""Agent Function Runtime — AgentStepRunner.

Replaces the legacy ``_run_opencode_json()`` in ``opencode_agent.py``
with structured error classification, log artifact writing, and a
unified interface that returns ``AgentRunResult`` from ``agent_models``.

See PRD: prd/opencode-agent-function-runtime.md
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from engine.env import load_project_env
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
        model: str = "dashscope/qwen3.7-plus",
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

        env = load_project_env(self.project_root, base_env=self.env)
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
                    encoding="utf-8",
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

            opencode_error = self._extract_opencode_error_detail(last_stdout)
            if opencode_error:
                last_error_category = "model_failure"
                last_detail = f"opencode error event: {opencode_error}"
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

    def _extract_opencode_error_detail(self, stdout: str) -> str:
        """Return a compact detail string when opencode emits type=error events."""
        details: list[str] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict) or item.get("type") != "error":
                continue
            error = item.get("error")
            if not isinstance(error, dict):
                details.append("unknown opencode error")
                continue
            name = str(error.get("name") or "UnknownError")
            data = error.get("data")
            message = ""
            status_code = None
            if isinstance(data, dict):
                message = str(data.get("message") or "")
                status_code = data.get("statusCode")
            if status_code is not None:
                details.append(f"{name} status={status_code}: {message}"[:1000])
            else:
                details.append(f"{name}: {message}"[:1000])
        return " | ".join(details[:3])

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
            f"Command: {' '.join(self._safe_command_args(command))}",
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

    def _safe_command_args(self, command: list[str]) -> list[str]:
        """Return argv suitable for logs without embedding long prompts."""
        safe_args: list[str] = []
        for index, arg in enumerate(command):
            if index == 2 and len(command) > 2 and command[1] == "run":
                digest = hashlib.sha256(arg.encode("utf-8", errors="replace")).hexdigest()[:12]
                safe_args.append(f"<prompt chars={len(arg)} sha256={digest}>")
            elif len(arg) > 500:
                digest = hashlib.sha256(arg.encode("utf-8", errors="replace")).hexdigest()[:12]
                safe_args.append(f"<arg chars={len(arg)} sha256={digest}>")
            else:
                safe_args.append(arg)
        return safe_args
