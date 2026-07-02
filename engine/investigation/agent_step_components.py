"""AgentStepRunner component split — PRD §WP2.

Five single-responsibility components extracted from AgentStepRunner.run:

  AgentCommandInvoker   — opencode command/env/subprocess
  AgentOutputParser     — JSONL/raw stdout → JSON object
  AgentOutputValidator  — validator + repair prompt metadata
  AgentGroundingChecker — finding_id grounding check
  AgentTraceWriter      — write raw/validation/trace/token ledger artifacts

These components are composed by AgentStepRunner.run (facade),
which preserves the exact control flow graph from PRD §WP2.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from engine.env import load_project_env
from engine.investigation.agent_models import AgentErrorCategory


# ---------------------------------------------------------------------------
# Result dataclasses — each component returns a structured result
# ---------------------------------------------------------------------------


@dataclass
class InvokeResult:
    """Result from AgentCommandInvoker.invoke()."""

    completed: subprocess.CompletedProcess | None = None
    # OSError during subprocess launch (mapped to returncode 127 by run_simple_command)
    os_error: str | None = None
    # Classified error category if a failure was detected
    error_category: AgentErrorCategory | None = None
    error_detail: str | None = None


@dataclass
class ParseResult:
    """Result from AgentOutputParser.parse()."""

    parsed: dict | None = None
    error: Exception | None = None


@dataclass
class ValidationResult:
    """Result from AgentOutputValidator.validate()."""

    validated: dict | None = None
    error: ValueError | None = None


@dataclass
class GroundingResult:
    """Result from AgentGroundingChecker.check()."""

    passed: bool = True
    unknown_finding_ids: list[str] = field(default_factory=list)
    grounding_info: dict | None = None


@dataclass
class TraceRefs:
    """Result from AgentTraceWriter.write()."""

    log_ref: str | None = None
    trace_ref: str | None = None
    grounding_info: dict | None = None
    validation_artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass
class _RetryState:
    """Accumulated state across retry attempts."""

    last_error_category: AgentErrorCategory | None = None
    last_detail: str = ""
    last_stdout: str = ""
    last_stderr: str = ""
    repair_history: list[dict[str, Any]] = field(default_factory=list)

    def record_failure(self, attempt_index: int, category: AgentErrorCategory, detail: str) -> None:
        self.last_error_category = category
        self.last_detail = detail
        self.repair_history.append({
            "attempt": attempt_index + 1,
            "failure_type": category,
            "error": detail[:1000],
            "action": self._next_action(attempt_index),
        })

    @staticmethod
    def _next_action(attempt_index: int) -> str:
        if attempt_index == 0:
            return "retry_with_raw_output"
        if attempt_index == 1:
            return "retry_with_schema_error"
        return "deterministic_extractor_exhausted"


# ---------------------------------------------------------------------------
# AgentCommandInvoker
# ---------------------------------------------------------------------------


class AgentCommandInvoker:
    """Build opencode command, load env, run subprocess.

    Pure infrastructure concern: subprocess invocation. No business logic.
    """

    def __init__(
        self,
        project_root: Path,
        opencode_bin: str | Path = "opencode",
        env: dict[str, str] | None = None,
        run_fn: Callable[..., subprocess.CompletedProcess] | None = None,
    ):
        self.project_root = Path(project_root)
        self.opencode_bin = str(opencode_bin)
        self.base_env = env or {}
        if run_fn is None:
            from engine.tools.executor import run_simple_command as _default_run
            self._run_fn = _default_run
        else:
            self._run_fn = run_fn

    def build_command(
        self,
        prompt: str,
        model: str,
        files: list[Path] | None = None,
        context_pack_path: Path | None = None,
    ) -> list[str]:
        """Build the opencode argv list."""
        command = [
            self.opencode_bin,
            "run",
            prompt,
            "--format",
            "json",
            "--model",
            model,
            "--dir",
            str(self.project_root),
        ]
        for path in files or []:
            if Path(path).exists():
                command.extend(["--file", str(path)])
        if context_pack_path and Path(context_pack_path).exists():
            command.extend(["--file", str(context_pack_path)])
        return command

    def load_env(self) -> dict[str, str]:
        """Load project env with XDG_DATA_HOME default."""
        env = load_project_env(self.project_root, base_env=self.base_env)
        env.setdefault("XDG_DATA_HOME", str(self.project_root / ".opencode" / "data"))
        return env

    def invoke(
        self,
        command: list[str],
        env: dict[str, str],
        timeout: int,
    ) -> InvokeResult:
        """Run subprocess, return InvokeResult."""
        completed = self._run_fn(
            command,
            cwd=self.project_root,
            env=env,
            timeout=timeout,
        )
        return InvokeResult(completed=completed)


# ---------------------------------------------------------------------------
# AgentOutputParser
# ---------------------------------------------------------------------------


class AgentOutputParser:
    """Extract JSON from opencode stdout (JSONL or raw text)."""

    def __init__(self, extract_fn: Callable[[str], dict] | None = None):
        # Allow injection for testing; default uses the module-level extract_json
        self._extract_fn = extract_fn

    def parse(self, stdout: str) -> ParseResult:
        """Attempt JSON extraction from stdout."""
        if self._extract_fn is None:
            from engine.investigation.agent_step_runner import extract_json

            extract = extract_json
        else:
            extract = self._extract_fn
        try:
            parsed = extract(stdout)
            return ParseResult(parsed=parsed)
        except Exception as exc:  # Deliberately broad: JSON extraction from LLM output may raise various parse errors
            return ParseResult(error=exc)


# ---------------------------------------------------------------------------
# AgentOutputValidator
# ---------------------------------------------------------------------------


class AgentOutputValidator:
    """Run user-supplied validator on parsed output."""

    def validate(
        self,
        parsed: dict,
        output_validator: Callable[[dict], dict],
    ) -> ValidationResult:
        """Run validator, catch ValueError."""
        try:
            validated = output_validator(parsed)
            return ValidationResult(validated=validated)
        except ValueError as exc:
            return ValidationResult(error=exc)


# ---------------------------------------------------------------------------
# AgentGroundingChecker
# ---------------------------------------------------------------------------


class AgentGroundingChecker:
    """Check that finding_ids in agent output exist in canonical artifacts."""

    def check(self, output: dict, workdir: Path) -> GroundingResult:
        """Run grounding check, return result."""
        from engine.investigation.agent_step_runner import AgentStepRunner

        # Delegate to the static method on AgentStepRunner for grounding logic
        # to avoid duplicating the _run_grounding_check/_extract_finding_ids code.
        runner_stub = AgentStepRunner.__new__(AgentStepRunner)
        grounding = runner_stub._run_grounding_check(output, workdir)
        unknown_ids = grounding.get("unknown_finding_ids") or []
        return GroundingResult(
            passed=not unknown_ids,
            unknown_finding_ids=unknown_ids,
            grounding_info=grounding if unknown_ids else None,
        )


# ---------------------------------------------------------------------------
# AgentTraceWriter
# ---------------------------------------------------------------------------


class AgentTraceWriter:
    """Write log artifacts: raw output, validation JSON, trace JSON, token ledger.

    Delegates to AgentStepRunner._write_log_artifact which encapsulates the
    full artifact writing logic (header building, token extraction, etc.).
    """

    def __init__(self, runner: Any):
        """Hold a reference to the owning AgentStepRunner instance."""
        self._runner = runner

    def write(
        self,
        *,
        log_dir: Path,
        role: str,
        command: list[str],
        prompt_text: str,
        stdout: str,
        stderr: str,
        error_category: AgentErrorCategory | None,
        attempt: int,
        context_pack_path: Path | None = None,
        validated_output: dict | None = None,
        workdir: Path | None = None,
        timeout_seconds: int | None = None,
        repair_history: list[dict[str, Any]] | None = None,
        last_detail: str | None = None,
    ) -> TraceRefs:
        """Write artifacts and return TraceRefs."""
        log_ref, trace_ref, grounding_info, validation_artifacts = (
            self._runner._write_log_artifact(
                log_dir=log_dir,
                role=role,
                command=command,
                prompt_text=prompt_text,
                stdout=stdout,
                stderr=stderr,
                error_category=error_category,
                attempt=attempt,
                context_pack_path=context_pack_path,
                validated_output=validated_output,
                workdir=workdir,
                timeout_seconds=timeout_seconds,
                repair_history=repair_history,
                last_detail=last_detail,
            )
        )
        return TraceRefs(
            log_ref=log_ref,
            trace_ref=trace_ref,
            grounding_info=grounding_info,
            validation_artifacts=validation_artifacts,
        )
