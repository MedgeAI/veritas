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
from typing import Any, Callable

from engine.investigation.agent_models import AgentErrorCategory, AgentRunResult
from engine.investigation.agent_step_components import (
    AgentCommandInvoker,
    AgentGroundingChecker,
    AgentOutputParser,
    AgentOutputValidator,
    AgentTraceWriter,
    _RetryState,
)
from engine.llm.config import DEFAULT_LLM_MODEL
from engine.tools.executor import run_simple_command


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
        model: str | None = None,
        opencode_bin: str | Path = "opencode",
        env: dict[str, str] | None = None,
    ):
        self.project_root = Path(project_root)
        self.model = model or DEFAULT_LLM_MODEL
        self.opencode_bin = str(opencode_bin)
        self.env = env or {}
        # Grounding info from the last run, for trace artifact
        self._last_grounding: dict | None = None

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
        workdir: Path | None = None,
    ) -> AgentRunResult:
        """Execute opencode with retry and structured error handling.

        Facade that composes AgentCommandInvoker, AgentOutputParser,
        AgentOutputValidator, AgentGroundingChecker, and AgentTraceWriter
        in the exact control flow order from PRD §WP2.
        """
        invoker = AgentCommandInvoker(
            self.project_root, self.opencode_bin, self.env, run_simple_command
        )
        parser = AgentOutputParser()
        validator = AgentOutputValidator()
        grounding_checker = AgentGroundingChecker()
        trace_writer = AgentTraceWriter(self)

        command = invoker.build_command(prompt, self.model, files, context_pack_path)
        env = invoker.load_env()

        state = _RetryState()
        start_all = time.monotonic()

        for attempt in range(max_retries + 1):
            if attempt and state.last_detail:
                command[2] = self._build_retry_prompt(prompt, state)

            invoke_result = invoker.invoke(command, env, timeout_seconds)
            if invoke_result.completed is None:
                break

            classification = self._classify_invocation(
                invoke_result.completed, state, timeout_seconds
            )
            if classification == "continue":
                continue
            if classification == "break":
                break

            parse_result = parser.parse(state.last_stdout)
            if parse_result.parsed is None:
                state.record_failure(
                    attempt,
                    "schema_validation",
                    f"JSON extraction failed: {type(parse_result.error).__name__}: {parse_result.error}",
                )
                continue

            validation_result = validator.validate(
                parse_result.parsed, output_validator
            )
            if validation_result.validated is None:
                state.record_failure(
                    attempt,
                    "schema_validation",
                    f"validation failed: {validation_result.error}",
                )
                continue

            validated = validation_result.validated

            if workdir is not None:
                grounding_result = grounding_checker.check(validated, Path(workdir))
                if not grounding_result.passed:
                    detail = f"agent cited {len(grounding_result.unknown_finding_ids)} finding_id(s) not in canonical artifacts: {grounding_result.unknown_finding_ids[:5]}"
                    self._last_grounding = grounding_result.grounding_info
                    state.record_failure(attempt, "grounding_failure", detail)
                    continue

            # Hallucination gate (N2): block output that cites finding_ids
            # not present in the context_pack top_n_findings.
            hallucination = self._run_hallucination_checks(validated, context_pack_path)
            if not hallucination["all_passed"]:
                detail = f"hallucination gate: {hallucination['warnings'][:2]}"
                state.record_failure(attempt, "hallucination_failure", detail)
                continue

            return self._build_success_result(
                role,
                validated,
                state,
                trace_writer,
                log_dir,
                command,
                prompt,
                context_pack_path,
                workdir,
                timeout_seconds,
                attempt,
                start_all,
            )

        return self._build_failed_result(
            role,
            state,
            trace_writer,
            log_dir,
            command,
            prompt,
            context_pack_path,
            workdir,
            timeout_seconds,
            max_retries,
            start_all,
        )

    def _build_retry_prompt(self, prompt: str, state: _RetryState) -> str:
        """Construct retry prompt with previous error context."""
        raw_tail = state.last_stdout[-2000:] if state.last_stdout else ""
        return f"{prompt}\n\nPrevious attempt failed: {state.last_detail}\nRaw output tail:\n{raw_tail}\n\nPlease repair the JSON only. Return one valid JSON object."

    def _classify_invocation(
        self,
        completed: subprocess.CompletedProcess,
        state: _RetryState,
        timeout_seconds: int,
    ) -> str:
        """Classify invocation result. Returns 'continue', 'break', or 'proceed'."""
        if completed.returncode == 124:
            state.last_error_category = "timeout"
            state.last_detail = f"opencode timed out after {timeout_seconds}s"
            state.last_stdout = ""
            state.last_stderr = ""
            state.record_failure(
                len(state.repair_history), "timeout", state.last_detail
            )
            return "continue"
        if completed.returncode == 127:
            state.last_error_category = "non_zero_exit"
            state.last_detail = f"opencode launch failed: {completed.stderr}"
            state.last_stdout = ""
            state.last_stderr = ""
            state.record_failure(
                len(state.repair_history), "non_zero_exit", state.last_detail
            )
            return "break"

        state.last_stdout = completed.stdout or ""
        state.last_stderr = completed.stderr or ""

        if completed.returncode != 0:
            state.last_error_category = self._classify_exit_error(state.last_stderr)
            state.last_detail = f"opencode exit_code={completed.returncode} stderr_tail={state.last_stderr[-1000:]!r}"
            state.record_failure(
                len(state.repair_history), state.last_error_category, state.last_detail
            )
            return "continue"

        opencode_error = self._extract_opencode_error_detail(state.last_stdout)
        if opencode_error:
            state.last_error_category = "model_failure"
            state.last_detail = f"opencode error event: {opencode_error}"
            state.record_failure(
                len(state.repair_history), "model_failure", state.last_detail
            )
            return "continue"

        return "proceed"

    def _build_success_result(
        self,
        role: str,
        validated: dict,
        state: _RetryState,
        trace_writer: AgentTraceWriter,
        log_dir: Path | None,
        command: list[str],
        prompt: str,
        context_pack_path: Path | None,
        workdir: Path | None,
        timeout_seconds: int,
        attempt: int,
        start_all: float,
    ) -> AgentRunResult:
        """Construct success AgentRunResult."""
        total_runtime = time.monotonic() - start_all
        trace_refs = None
        if log_dir:
            trace_refs = trace_writer.write(
                log_dir=log_dir,
                role=role,
                command=command,
                prompt_text=prompt,
                stdout=state.last_stdout,
                stderr=state.last_stderr,
                error_category=None,
                attempt=attempt,
                context_pack_path=context_pack_path,
                validated_output=validated,
                workdir=Path(workdir) if workdir else None,
                timeout_seconds=timeout_seconds,
                repair_history=state.repair_history,
                last_detail=None,
            )

        result_metadata: dict = {
            "model": self.model,
            "runtime_seconds": total_runtime,
            "attempts": attempt + 1,
            "trace_ref": trace_refs.trace_ref if trace_refs else None,
        }
        if trace_refs and trace_refs.grounding_info:
            result_metadata["grounding"] = trace_refs.grounding_info
        if state.repair_history:
            result_metadata["repair_history"] = state.repair_history
            result_metadata["repair_attempts"] = len(state.repair_history)
        if trace_refs:
            result_metadata.update(trace_refs.validation_artifacts)

        return AgentRunResult(
            status="success",
            role=role,
            output=validated,
            error_category=None,
            runtime_seconds=total_runtime,
            log_ref=trace_refs.log_ref if trace_refs else None,
            metadata=result_metadata,
        )

    def _build_failed_result(
        self,
        role: str,
        state: _RetryState,
        trace_writer: AgentTraceWriter,
        log_dir: Path | None,
        command: list[str],
        prompt: str,
        context_pack_path: Path | None,
        workdir: Path | None,
        timeout_seconds: int,
        max_retries: int,
        start_all: float,
    ) -> AgentRunResult:
        """Construct failed AgentRunResult."""
        total_runtime = time.monotonic() - start_all
        trace_refs = None
        grounding_info = self._last_grounding
        if log_dir:
            trace_refs = trace_writer.write(
                log_dir=log_dir,
                role=role,
                command=command,
                prompt_text=prompt,
                stdout=state.last_stdout,
                stderr=state.last_stderr,
                error_category=state.last_error_category or "non_zero_exit",
                attempt=max_retries,
                context_pack_path=context_pack_path,
                validated_output=None,
                workdir=Path(workdir) if workdir else None,
                timeout_seconds=timeout_seconds,
                repair_history=state.repair_history,
                last_detail=state.last_detail,
            )
            if trace_refs.grounding_info:
                grounding_info = trace_refs.grounding_info

        failed_metadata: dict = {
            "schema_version": "agent_output_validation.v1",
            "role_id": role,
            "model": self.model,
            "runtime_seconds": total_runtime,
            "attempts": max_retries + 1,
            "last_detail": state.last_detail,
            "trace_ref": trace_refs.trace_ref if trace_refs else None,
            "failure_type": state.last_error_category or "non_zero_exit",
            "timeout_seconds": timeout_seconds,
            "repair_attempts": len(state.repair_history),
            "repair_history": state.repair_history,
        }
        if trace_refs:
            failed_metadata.update(trace_refs.validation_artifacts)
        if grounding_info:
            failed_metadata["grounding"] = grounding_info

        return AgentRunResult(
            status="failed",
            role=role,
            output=None,
            error_category=state.last_error_category or "non_zero_exit",
            runtime_seconds=total_runtime,
            log_ref=trace_refs.log_ref if trace_refs else None,
            metadata=failed_metadata,
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
    ) -> tuple[str, str | None, dict | None, dict[str, Any]]:
        """Write enhanced log artifact + structured trace JSON.

        Returns (log_ref, trace_ref, grounding_info) — relative paths to the log
        file and the trace JSON file, plus grounding metadata if applicable.
        """
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_filename = f"{role}_{timestamp}.log"
        log_path = log_dir / log_filename

        # Extract token usage from JSONL stdout
        token_usage = self._extract_token_usage(stdout)
        runtime_seconds = self._extract_runtime(stdout)
        raw_path = log_dir / f"{role}_{timestamp}.raw.txt"
        raw_path.write_text(stdout or "", encoding="utf-8")
        validation_path = log_dir / f"{role}_{timestamp}.validation.json"
        validation_payload = {
            "schema_version": "agent_output_validation.v1",
            "role_id": role,
            "status": "success" if error_category is None else "failed",
            "failure_type": error_category,
            "timeout_seconds": timeout_seconds,
            "last_detail": last_detail,
            "raw_output_path": str(raw_path),
            "repair_attempts": len(repair_history or []),
            "repair_history": repair_history or [],
        }
        validation_path.write_text(
            json.dumps(validation_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Build enhanced header
        header_lines = self._build_log_header(
            role=role,
            attempt=attempt,
            error_category=error_category,
            prompt_text=prompt_text,
            token_usage=token_usage,
            runtime_seconds=runtime_seconds,
            context_pack_path=context_pack_path,
            validated_output=validated_output,
        )

        content_lines = [
            *header_lines,
            "",
            "=== STDOUT (raw JSONL) ===",
            stdout,
            "",
            "=== STDERR ===",
            stderr,
        ]

        log_path.write_text("\n".join(content_lines), encoding="utf-8")

        # Write structured trace JSON (P1)
        trace_ref, grounding_info = self._write_trace_artifact(
            log_dir=log_dir,
            role=role,
            timestamp=timestamp,
            attempt=attempt,
            error_category=error_category,
            prompt_text=prompt_text,
            context_pack_path=context_pack_path,
            validated_output=validated_output,
            token_usage=token_usage,
            runtime_seconds=runtime_seconds,
            stdout=stdout,
            workdir=workdir,
            timeout_seconds=timeout_seconds,
            repair_history=repair_history or [],
            raw_output_path=raw_path,
            validation_error_path=validation_path,
            last_detail=last_detail,
        )

        try:
            log_ref = str(log_path.relative_to(self.project_root))
        except ValueError:
            log_ref = str(log_path)

        artifact_meta = {
            "raw_output_path": str(raw_path),
            "validation_error_path": str(validation_path),
        }
        return log_ref, trace_ref, grounding_info, artifact_meta

    def _build_log_header(
        self,
        *,
        role: str,
        attempt: int,
        error_category: AgentErrorCategory | None,
        prompt_text: str,
        token_usage: dict,
        runtime_seconds: float,
        context_pack_path: Path | None,
        validated_output: dict | None,
    ) -> list[str]:
        """Build human-readable log header for hallucination debugging."""
        lines = [
            "=== Agent Step Log ===",
            f"Role: {role}",
            f"Attempt: {attempt + 1}",
            f"Error Category: {error_category or 'none'}",
        ]

        # Token/cost summary
        total = token_usage.get("total", 0)
        inp = token_usage.get("input", 0)
        out = token_usage.get("output", 0)
        reason = token_usage.get("reasoning", 0)
        step_count = token_usage.get("step_count", 0)
        cache = token_usage.get("cache", {})
        cache_read = cache.get("read", 0) if isinstance(cache, dict) else 0
        if total:
            lines.append(
                f"Runtime: {runtime_seconds:.1f}s | "
                f"Tokens: {total:,} (in={inp:,} out={out:,} reason={reason:,})"
            )
            if step_count or cache_read:
                lines.append(
                    f"Token detail: steps={step_count:,} cache_read={cache_read:,}"
                )

        # Prompt summary (first 500 chars, not hashed)
        lines.append("")
        lines.append(f"--- Prompt Summary ({len(prompt_text):,} chars, first 500) ---")
        prompt_preview = prompt_text[:500]
        if len(prompt_text) > 500:
            prompt_preview += "..."
        lines.append(prompt_preview)
        lines.append("[Full prompt: opencode command argv[2], context_pack below]")

        # Context pack summary (what the agent saw)
        if context_pack_path and Path(context_pack_path).exists():
            cp_summary = self._summarize_context_pack(Path(context_pack_path))
            lines.append("")
            lines.append("--- Input Evidence (from context_pack) ---")
            lines.append(f"Context pack: {context_pack_path}")
            for key, desc in cp_summary.items():
                lines.append(f"  {key}: {desc}")

        # Output summary (what the agent produced)
        lines.append("")
        if validated_output:
            out_summary = self._summarize_output(validated_output, role)
            lines.append("--- Output Summary ---")
            for key, desc in out_summary.items():
                lines.append(f"  {key}: {desc}")
        else:
            lines.append("--- Output Summary ---")
            lines.append("  [no valid output — see error category above]")

        return lines

    def _extract_token_usage(self, stdout: str) -> dict:
        """Parse JSONL stdout for aggregate token usage from step_finish events."""
        aggregate = {
            "total": 0,
            "input": 0,
            "output": 0,
            "reasoning": 0,
            "cache": {"read": 0, "write": 0},
            "step_count": 0,
            "steps": [],
        }
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("type") == "step_finish":
                part = item.get("part", {})
                tokens = part.get("tokens", {})
                if isinstance(tokens, dict):
                    cache = tokens.get("cache", {})
                    cache_read = cache.get("read", 0) if isinstance(cache, dict) else 0
                    cache_write = (
                        cache.get("write", 0) if isinstance(cache, dict) else 0
                    )
                    step = {
                        "reason": part.get("reason"),
                        "total": tokens.get("total", 0) or 0,
                        "input": tokens.get("input", 0) or 0,
                        "output": tokens.get("output", 0) or 0,
                        "reasoning": tokens.get("reasoning", 0) or 0,
                        "cache_read": cache_read or 0,
                        "cache_write": cache_write or 0,
                    }
                    aggregate["step_count"] += 1
                    aggregate["total"] += step["total"]
                    aggregate["input"] += step["input"]
                    aggregate["output"] += step["output"]
                    aggregate["reasoning"] += step["reasoning"]
                    aggregate["cache"]["read"] += step["cache_read"]
                    aggregate["cache"]["write"] += step["cache_write"]
                    aggregate["steps"].append(step)
        if aggregate["step_count"] == 0:
            return {}
        return aggregate

    def _build_token_ledger(
        self,
        *,
        prompt_text: str,
        context_pack_path: Path | None,
        token_usage: dict,
    ) -> dict[str, Any]:
        """Build a non-invasive token observability ledger for this agent step."""
        cache = token_usage.get("cache", {})
        cache_read = cache.get("read", 0) if isinstance(cache, dict) else 0
        cache_write = cache.get("write", 0) if isinstance(cache, dict) else 0

        context_pack_bytes = 0
        if context_pack_path and Path(context_pack_path).exists():
            try:
                context_pack_bytes = Path(context_pack_path).stat().st_size
            except OSError:
                context_pack_bytes = 0

        return {
            "schema_version": "1.0",
            "step_count": token_usage.get("step_count", 0),
            "model": self.model,
            "input_payload": {
                "prompt_chars": len(prompt_text),
                "context_pack_path": str(context_pack_path)
                if context_pack_path
                else None,
                "context_pack_bytes": context_pack_bytes,
            },
            "token_classes": {
                "uncached_input": token_usage.get("input", 0),
                "cache_read": cache_read,
                "cache_write": cache_write,
                "output": token_usage.get("output", 0),
                "reasoning": token_usage.get("reasoning", 0),
                "total": token_usage.get("total", 0),
            },
            "billing_inputs": {
                "full_rate_input_tokens": token_usage.get("input", 0),
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
                "output_tokens": token_usage.get("output", 0),
                "reasoning_tokens": token_usage.get("reasoning", 0),
            },
        }

    def _extract_runtime(self, stdout: str) -> float:
        """Estimate runtime from JSONL timestamps."""
        first_ts = None
        last_ts = None
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = item.get("timestamp")
            if isinstance(ts, (int, float)):
                if first_ts is None:
                    first_ts = ts
                last_ts = ts
        if first_ts and last_ts and last_ts > first_ts:
            return (last_ts - first_ts) / 1000.0  # ms → s
        return 0.0

    def _summarize_context_pack(self, path: Path) -> dict[str, str]:
        """Extract a compact summary from a context_pack JSON."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"error": "could not read context_pack"}

        summary = {}

        # artifact_manifest
        manifest = data.get("artifact_manifest")
        if isinstance(manifest, list):
            summary["artifacts"] = f"{len(manifest)} items"

        # evidence_refs
        refs = data.get("evidence_refs")
        if isinstance(refs, list):
            summary["evidence_refs"] = f"{len(refs)} refs"

        # top_n_findings — key for hallucination debugging
        findings = data.get("top_n_findings")
        if isinstance(findings, list):
            risk_counts: dict[str, int] = {}
            for f in findings:
                if isinstance(f, dict):
                    risk = f.get("risk_level", "?")
                    risk_counts[risk] = risk_counts.get(risk, 0) + 1
            risk_str = ", ".join(f"{k}={v}" for k, v in sorted(risk_counts.items()))
            summary["top_n_findings"] = f"{len(findings)} findings ({risk_str})"

        # limitations
        lims = data.get("limitations")
        if isinstance(lims, list):
            summary["limitations"] = f"{len(lims)} items"

        # bounded_excerpts
        excerpts = data.get("bounded_excerpts")
        if isinstance(excerpts, dict):
            summary["bounded_excerpts"] = f"{len(excerpts)} sources"

        return summary

    def _summarize_output(self, output: dict, role: str) -> dict[str, str]:
        """Extract a compact summary from agent output."""
        summary = {}

        # Status
        status = output.get("status")
        if status:
            summary["status"] = str(status)

        # Role-specific summaries
        # Judge
        if "risk_suggestions" in output:
            suggestions = output["risk_suggestions"]
            summary["risk_suggestions"] = f"{len(suggestions)} items"
        if "report_notes" in output:
            notes = output["report_notes"]
            summary["report_notes"] = f"{len(notes)} items"

        # Claim extractor
        if "claims" in output:
            claims = output["claims"]
            summary["claims"] = f"{len(claims)} extracted"

        # Source data auditor
        if "finding_reviews" in output:
            reviews = output["finding_reviews"]
            verdicts: dict[str, int] = {}
            for r in reviews:
                if isinstance(r, dict):
                    v = r.get("verdict", "?")
                    verdicts[v] = verdicts.get(v, 0) + 1
            v_str = ", ".join(f"{k}={v}" for k, v in sorted(verdicts.items()))
            summary["finding_reviews"] = f"{len(reviews)} ({v_str})"
        if "manual_review_tasks" in output:
            tasks = output["manual_review_tasks"]
            summary["manual_review_tasks"] = f"{len(tasks)} tasks"

        # Review
        if "candidate_claims" in output:
            summary["candidate_claims"] = f"{len(output['candidate_claims'])} items"

        # Limitations (common to all roles)
        lims = output.get("limitations")
        if isinstance(lims, list):
            summary["limitations"] = f"{len(lims)} items"

        # Generic fallback: top-level keys
        if not summary:
            keys = list(output.keys())
            summary["output_keys"] = f"{len(keys)} keys: {', '.join(keys[:8])}"

        return summary

    def _write_trace_artifact(
        self,
        *,
        log_dir: Path,
        role: str,
        timestamp: str,
        attempt: int,
        error_category: AgentErrorCategory | None,
        prompt_text: str,
        context_pack_path: Path | None,
        validated_output: dict | None,
        token_usage: dict,
        runtime_seconds: float,
        stdout: str,
        workdir: Path | None = None,
        timeout_seconds: int | None = None,
        repair_history: list[dict[str, Any]] | None = None,
        raw_output_path: Path | None = None,
        validation_error_path: Path | None = None,
        last_detail: str | None = None,
    ) -> tuple[str | None, dict | None]:
        """Write structured trace JSON for machine-readable observability.

        Returns (trace_ref, grounding_info) — relative path to the trace JSON
        file and grounding metadata if grounding check was performed.
        """
        trace_path = log_dir / f"step_trace_{role}_{timestamp}.json"

        # Build context pack summary
        cp_summary = {}
        if context_pack_path and Path(context_pack_path).exists():
            cp_summary = self._summarize_context_pack(Path(context_pack_path))

        # Build output summary
        out_summary = {}
        if validated_output:
            out_summary = self._summarize_output(validated_output, role)

        # Basic hallucination checks
        hallucination_checks = self._run_hallucination_checks(
            validated_output, context_pack_path
        )
        token_ledger = self._build_token_ledger(
            prompt_text=prompt_text,
            context_pack_path=context_pack_path,
            token_usage=token_usage,
        )

        trace = {
            "role": role,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attempt": attempt + 1,
            "status": "success" if error_category is None else "failed",
            "error_category": error_category,
            "runtime_seconds": round(runtime_seconds, 1),
            "model": self.model,
            "input": {
                "context_pack_path": str(context_pack_path)
                if context_pack_path
                else None,
                "context_pack_summary": cp_summary,
                "prompt_chars": len(prompt_text),
                "prompt_sha256": hashlib.sha256(
                    prompt_text.encode("utf-8", errors="replace")
                ).hexdigest()[:16],
            },
            "output": {
                "status": validated_output.get("status") if validated_output else None,
                "summary": out_summary,
            },
            "token_usage": token_usage,
            "token_ledger": token_ledger,
            "hallucination_checks": hallucination_checks,
            "validation": {
                "schema_version": "agent_output_validation.v1",
                "failure_type": error_category,
                "timeout_seconds": timeout_seconds,
                "last_detail": last_detail,
                "raw_output_path": str(raw_output_path) if raw_output_path else None,
                "validation_error_path": str(validation_error_path)
                if validation_error_path
                else None,
                "repair_attempts": len(repair_history or []),
                "repair_history": repair_history or [],
            },
        }

        trace_path.write_text(
            json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Run grounding check if workdir provided and output is valid
        grounding_info: dict | None = None
        if workdir and validated_output:
            grounding_info = self._run_grounding_check(validated_output, Path(workdir))
            if grounding_info:
                trace["grounding"] = grounding_info
                trace_path.write_text(
                    json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
                )

        try:
            return str(trace_path.relative_to(self.project_root)), grounding_info
        except ValueError:
            return str(trace_path), grounding_info

    def _run_hallucination_checks(
        self,
        output: dict | None,
        context_pack_path: Path | None,
    ) -> dict:
        """Run basic hallucination detection checks."""
        checks: dict[str, bool | list[str]] = {
            "all_passed": True,
            "warnings": [],
        }

        if output is None:
            return checks

        # Check 1: cited finding_ids exist in context_pack
        if context_pack_path and Path(context_pack_path).exists():
            try:
                cp = json.loads(Path(context_pack_path).read_text(encoding="utf-8"))
                known_ids = set()
                for f in cp.get("top_n_findings", []):
                    if isinstance(f, dict):
                        fid = f.get("finding_id")
                        if fid:
                            known_ids.add(str(fid))

                # Scan output for finding_id references
                cited_ids = self._extract_finding_ids(output)
                unknown = cited_ids - known_ids
                if unknown and known_ids:
                    checks["warnings"].append(
                        f"Cited {len(unknown)} finding_id(s) not in context_pack: "
                        f"{sorted(unknown)[:5]}"
                    )
                    checks["all_passed"] = False
            except (json.JSONDecodeError, OSError):
                pass

        return checks

    def _run_grounding_check(
        self,
        output: dict,
        workdir: Path,
    ) -> dict:
        """Check that all cited finding_ids exist in canonical artifacts.

        PRD3-T7: Validates agent output against the full set of canonical
        finding IDs from all audit artifacts, not just context_pack top_n.
        Returns grounding metadata for trace artifact.
        """
        from engine.investigation.context_pack import (
            get_all_canonical_finding_ids,
            get_artifact_backref,
        )

        cited_ids = self._extract_finding_ids(output)
        if not cited_ids:
            return {"all_passed": True, "unknown_finding_ids": []}

        canonical_ids = get_all_canonical_finding_ids(workdir)
        unknown_ids = cited_ids - canonical_ids

        if not unknown_ids:
            return {"all_passed": True, "unknown_finding_ids": []}

        # Build backref map for known IDs
        artifact_backrefs: dict[str, str] = {}
        for fid in cited_ids - unknown_ids:
            backref = get_artifact_backref(fid, workdir)
            if backref:
                artifact_backrefs[fid] = backref

        return {
            "all_passed": False,
            "unknown_finding_ids": sorted(unknown_ids),
            "artifact_backrefs": artifact_backrefs,
        }

    def _extract_finding_ids(self, obj: Any, depth: int = 0) -> set[str]:
        """Recursively extract finding_id values from nested dicts/lists."""
        if depth > 10:
            return set()
        ids: set[str] = set()
        if isinstance(obj, dict):
            fid = obj.get("finding_id")
            if fid and isinstance(fid, str):
                ids.add(fid)
            for v in obj.values():
                ids |= self._extract_finding_ids(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                ids |= self._extract_finding_ids(item, depth + 1)
        return ids

    def _safe_command_args(self, command: list[str]) -> list[str]:
        """Return argv suitable for logs without embedding long prompts."""
        safe_args: list[str] = []
        for index, arg in enumerate(command):
            if index == 2 and len(command) > 2 and command[1] == "run":
                digest = hashlib.sha256(
                    arg.encode("utf-8", errors="replace")
                ).hexdigest()[:12]
                safe_args.append(f"<prompt chars={len(arg)} sha256={digest}>")
            elif len(arg) > 500:
                digest = hashlib.sha256(
                    arg.encode("utf-8", errors="replace")
                ).hexdigest()[:12]
                safe_args.append(f"<arg chars={len(arg)} sha256={digest}>")
            else:
                safe_args.append(arg)
        return safe_args
