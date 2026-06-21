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
            trace_ref = None
            if log_dir:
                log_ref, trace_ref = self._write_log_artifact(
                    log_dir=log_dir,
                    role=role,
                    command=command,
                    prompt_text=prompt,
                    stdout=last_stdout,
                    stderr=last_stderr,
                    error_category=None,
                    attempt=attempt,
                    context_pack_path=context_pack_path,
                    validated_output=validated,
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
                    "trace_ref": trace_ref,
                },
            )

        total_runtime = time.monotonic() - start_all
        log_ref = None
        trace_ref = None
        if log_dir:
            log_ref, trace_ref = self._write_log_artifact(
                log_dir=log_dir,
                role=role,
                command=command,
                prompt_text=prompt,
                stdout=last_stdout,
                stderr=last_stderr,
                error_category=last_error_category or "non_zero_exit",
                attempt=max_retries,
                context_pack_path=context_pack_path,
                validated_output=None,
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
                "trace_ref": trace_ref,
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
        prompt_text: str,
        stdout: str,
        stderr: str,
        error_category: AgentErrorCategory | None,
        attempt: int,
        context_pack_path: Path | None = None,
        validated_output: dict | None = None,
    ) -> tuple[str, str | None]:
        """Write enhanced log artifact + structured trace JSON.

        Returns (log_ref, trace_ref) — relative paths to the log file and
        the trace JSON file.
        """
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_filename = f"{role}_{timestamp}.log"
        log_path = log_dir / log_filename

        # Extract token usage from JSONL stdout
        token_usage = self._extract_token_usage(stdout)
        runtime_seconds = self._extract_runtime(stdout)

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
        trace_ref = self._write_trace_artifact(
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
        )

        try:
            log_ref = str(log_path.relative_to(self.project_root))
        except ValueError:
            log_ref = str(log_path)

        return log_ref, trace_ref

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
        if total:
            lines.append(
                f"Runtime: {runtime_seconds:.1f}s | "
                f"Tokens: {total:,} (in={inp:,} out={out:,} reason={reason:,})"
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
        """Parse JSONL stdout for token usage from step_finish event."""
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
                    return {
                        "total": tokens.get("total", 0),
                        "input": tokens.get("input", 0),
                        "output": tokens.get("output", 0),
                        "reasoning": tokens.get("reasoning", 0),
                    }
        return {}

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
    ) -> str | None:
        """Write structured trace JSON for machine-readable observability."""
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
            "hallucination_checks": hallucination_checks,
        }

        trace_path.write_text(
            json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        try:
            return str(trace_path.relative_to(self.project_root))
        except ValueError:
            return str(trace_path)

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
