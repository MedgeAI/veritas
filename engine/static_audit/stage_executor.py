"""Declarative stage executor for source-data (and future) pipeline sections.

Design goals:
- Steps are declared as data (StepDefinition), not hand-wired imperative code.
- Each step has an executor (SubprocessExecutor | CallableExecutor) that is
  independently testable via dependency injection.
- fail_policy controls downstream behavior when a step fails:
  * "stop"        — abort remaining steps immediately
  * "skip_downstream" — mark remaining steps as skipped (used when an
                        upstream artifact is required by all downstream steps)
  * "continue"    — keep going regardless
- required_artifacts gates execution: if any artifact is missing, the step
  is skipped with a clear skip_reason.

Contract:
- StageExecutor.run() returns list[StepResult] identical in shape to what
  the old imperative _run_source_data_steps returned.
- Artifact paths are computed via resolve_artifact_path (same as before).
- Progress events use the same emit_step_start / record_step helpers.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from engine.shared.types import StepResult, StepStatus
from engine.static_audit._shared import (
    PROJECT_ROOT,
    ProgressCallback,
    emit_step_start,
    existing_artifact_path,
    record_step,
    resolve_artifact_path,
    run_command,
)

logger = logging.getLogger(__name__)

FailPolicy = Literal["stop", "skip_downstream", "continue"]
Phase = Literal["source_data", "visual", "investigation", "report"]


# ---------------------------------------------------------------------------
# Executor protocol and implementations
# ---------------------------------------------------------------------------


class StepExecutor(Protocol):
    """Protocol for step executors."""

    def __call__(
        self,
        ctx: StepContext,
        definition: StepDefinition,
    ) -> StepResult: ...


@dataclass(frozen=True, slots=True)
class SubprocessExecutor:
    """Execute a step by running a subprocess command.

    ``command_builder`` receives the StepContext and returns the argv list.
    This keeps command construction lazy (context-dependent) while the
    definition itself stays declarative.
    """

    command_builder: Callable[[StepContext], list[str]]
    expected_output_keys: tuple[str, ...] = ()
    attempts: int = 1
    retry_delay_seconds: float = 0.0
    stream_output: bool = False

    def __call__(
        self,
        ctx: StepContext,
        definition: StepDefinition,
    ) -> StepResult:
        command = self.command_builder(ctx)
        expected_outputs = [
            resolve_artifact_path(ctx.workdir, k) for k in self.expected_output_keys
        ]
        return run_command(
            key=definition.key,
            title=definition.title,
            command=command,
            expected_outputs=expected_outputs,
            cwd=PROJECT_ROOT,
            env=ctx.env,
            force=ctx.force,
            attempts=self.attempts,
            retry_delay_seconds=self.retry_delay_seconds,
            progress=ctx.progress,
            stream_output=self.stream_output,
        )


@dataclass(frozen=True, slots=True)
class CallableExecutor:
    """Execute a step by calling a Python callable.

    The callable receives (StepContext, StepDefinition) and returns a StepResult.
    This is the injection point for testing — pass a stub CallableExecutor
    to verify StageExecutor ordering / fail_policy / required_artifacts logic
    without running real subprocesses.
    """

    fn: Callable[[StepContext, StepDefinition], StepResult]

    def __call__(
        self,
        ctx: StepContext,
        definition: StepDefinition,
    ) -> StepResult:
        return self.fn(ctx, definition)


# ---------------------------------------------------------------------------
# Step context and definition
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StepContext:
    """Runtime context passed to every step executor."""

    workdir: Path
    args: Any  # argparse.Namespace — kept as Any to avoid circular import
    env: dict[str, str]
    progress: ProgressCallback | None
    source_data_dir: Path | None = None
    source_finding_params: dict[str, Any] = field(default_factory=dict)
    previous_results: dict[str, StepResult] = field(default_factory=dict)

    @property
    def force(self) -> bool:
        return getattr(self.args, "force", False)


@dataclass(frozen=True, slots=True)
class StepDefinition:
    """Declarative description of one pipeline step."""

    key: str
    title: str
    executor: SubprocessExecutor | CallableExecutor
    expected_outputs: tuple[str, ...] = ()
    required_artifacts: tuple[str, ...] = ()
    fail_policy: FailPolicy = "continue"
    phase: Phase = "source_data"


# ---------------------------------------------------------------------------
# Stage plan and executor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StagePlan:
    """An ordered collection of StepDefinitions forming a pipeline stage."""

    stage_key: str
    steps: tuple[StepDefinition, ...]


class StageExecutor:
    """Execute a StagePlan, returning list[StepResult].

    Handles:
    - required_artifacts gating (skip if missing)
    - fail_policy (stop / skip_downstream / continue)
    - Progress events via the existing emit_step_start / record_step helpers
    """

    def __init__(self, plan: StagePlan) -> None:
        self.plan = plan

    def run(self, ctx: StepContext) -> list[StepResult]:
        """Execute all steps in the plan, returning StepResult list."""
        results: list[StepResult] = []
        skip_downstream = False

        for definition in self.plan.steps:
            # Check required_artifacts
            missing = self._check_required_artifacts(ctx, definition)
            if missing:
                result = StepResult(
                    key=definition.key,
                    title=definition.title,
                    status=StepStatus.SKIPPED,
                    detail=f"required artifacts missing: {missing}",
                    skip_reason=f"missing: {', '.join(missing)}",
                    output_artifacts=list(definition.expected_outputs),
                )
                record_step(results, result, ctx.progress, workdir=ctx.workdir)
                ctx.previous_results[definition.key] = result
                continue

            # Check skip_downstream flag
            if skip_downstream:
                result = StepResult(
                    key=definition.key,
                    title=definition.title,
                    status=StepStatus.SKIPPED,
                    detail="skipped due to upstream failure (skip_downstream policy)",
                    skip_reason="upstream_failure",
                    output_artifacts=list(definition.expected_outputs),
                )
                record_step(results, result, ctx.progress, workdir=ctx.workdir)
                ctx.previous_results[definition.key] = result
                continue

            # Execute the step
            emit_step_start(ctx.progress, definition.key, definition.title)
            try:
                result = definition.executor(ctx, definition)
            except Exception as exc:
                logger.warning("Step %s raised: %s", definition.key, exc)
                result = StepResult(
                    key=definition.key,
                    title=definition.title,
                    status=StepStatus.FAILED,
                    detail=f"executor exception: {exc}",
                    failure_type="executor_exception",
                    output_artifacts=list(definition.expected_outputs),
                )
                record_step(results, result, ctx.progress, workdir=ctx.workdir)
                ctx.previous_results[definition.key] = result
                if definition.fail_policy == "stop":
                    break
                if definition.fail_policy == "skip_downstream":
                    skip_downstream = True
                continue

            record_step(results, result, ctx.progress, workdir=ctx.workdir)
            ctx.previous_results[definition.key] = result

            # Handle fail_policy based on result status
            if result.status in (StepStatus.FAILED, "failed"):
                if definition.fail_policy == "stop":
                    break
                if definition.fail_policy == "skip_downstream":
                    skip_downstream = True

        return results

    @staticmethod
    def _check_required_artifacts(
        ctx: StepContext,
        definition: StepDefinition,
    ) -> list[str]:
        """Return list of missing required artifact keys (empty = all present)."""
        if not definition.required_artifacts:
            return []
        missing = []
        for artifact_key in definition.required_artifacts:
            path = resolve_artifact_path(ctx.workdir, artifact_key)
            if not path.exists():
                missing.append(artifact_key)
        return missing


# ---------------------------------------------------------------------------
# Source-data stage plan builder
# ---------------------------------------------------------------------------


def _build_source_data_command(ctx: StepContext) -> list[str]:
    """Build command for source_data_profile step."""
    profile_out = resolve_artifact_path(ctx.workdir, "source_data_profile.json")
    return [
        sys.executable,
        "-m",
        "engine.static_audit.tools.source_data_profile",
        str(ctx.source_data_dir),
        "--output",
        str(profile_out),
    ]


def _build_source_data_findings_command(ctx: StepContext) -> list[str]:
    """Build command for source_data_findings step."""
    profile_out = resolve_artifact_path(ctx.workdir, "source_data_profile.json")
    sfp = ctx.source_finding_params
    cmd = [
        sys.executable,
        "-m",
        "engine.static_audit.tools.source_data_findings",
        str(ctx.source_data_dir),
        "--profile",
        str(profile_out),
        "--output",
        str(resolve_artifact_path(ctx.workdir, "source_data_findings.json")),
        "--min-overlap",
        str(sfp["min_overlap"]),
        "--min-support",
        str(sfp["min_support"]),
        "--max-findings-per-category",
        str(sfp["max_findings_per_category"]),
    ]
    full_md = existing_artifact_path(ctx.workdir, "full.md")
    if full_md is not None:
        cmd.extend(["--full-md", str(full_md)])
    return cmd


def _build_pair_forensics_command(ctx: StepContext) -> list[str]:
    """Build command for source_data_pair_forensics step."""
    return [
        sys.executable,
        "-m",
        "engine.static_audit.tools.source_data_pair_forensics",
        str(ctx.source_data_dir),
        "--output",
        str(resolve_artifact_path(ctx.workdir, "source_data_pair_forensics.json")),
    ]


def _build_cross_sheet_command(ctx: StepContext) -> list[str]:
    """Build command for source_data_cross_sheet step."""
    return [
        sys.executable,
        "-m",
        "engine.static_audit.tools.source_data_cross_sheet",
        str(ctx.source_data_dir),
        "--output",
        str(resolve_artifact_path(ctx.workdir, "source_data_cross_sheet.json")),
    ]


def _build_paperconan_command(ctx: StepContext) -> list[str]:
    """Build command for paperconan_scan step."""
    num_dir = resolve_artifact_path(ctx.workdir, "numeric")
    return [
        sys.executable,
        "-c",
        f"import json\n"
        f"from pathlib import Path\n"
        f"from engine.static_audit.adapters.paperconan_adapter import run_paperconan_scan\n"
        f"r = run_paperconan_scan(source_data_dir=Path({str(ctx.source_data_dir)!r}), "
        f"output_dir=Path({str(num_dir)!r}), profile='review')\n"
        f"print(json.dumps({{'status': r['status'], 'findings': r['findings_summary']}}))",
    ]


def _run_cross_sheet_filter_callable(
    ctx: StepContext, definition: StepDefinition
) -> StepResult:
    """CallableExecutor fn for cross_sheet_filter step."""
    from engine.exceptions import VeritasError

    cross_sheet_path = resolve_artifact_path(ctx.workdir, "source_data_cross_sheet.json")
    try:
        from engine.llm.client import VeritasLLMClient
        from engine.static_audit._shared import run_cross_sheet_filter

        cross_sheet_data = json.loads(cross_sheet_path.read_text(encoding="utf-8"))
        findings = cross_sheet_data.get(
            "cross_sheet_findings", cross_sheet_data.get("findings", [])
        )

        if findings:
            llm_client = VeritasLLMClient()
            filtered_findings = run_cross_sheet_filter(
                ctx.workdir, findings, llm_client
            )
            cross_sheet_data["findings"] = filtered_findings
            cross_sheet_data["filter_metadata"] = {
                "original_count": len(findings),
                "filtered_count": len(filtered_findings),
                "filter_applied": True,
            }
            cross_sheet_path.write_text(
                json.dumps(cross_sheet_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return StepResult(
                key=definition.key,
                title=definition.title,
                status=StepStatus.RAN,
                detail=f"filtered={len(findings) - len(filtered_findings)}",
            )
        else:
            return StepResult(
                key=definition.key,
                title=definition.title,
                status=StepStatus.SKIPPED,
                detail="no findings to filter",
                skip_reason="no_findings",
            )
    except (VeritasError, OSError) as exc:
        logger.warning("cross_sheet_filter failed: %s", exc)
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.FAILED,
            detail=f"filter failed: {exc}",
            failure_type="llm_filter_error",
        )


def _run_source_data_briefings_callable(
    ctx: StepContext, definition: StepDefinition
) -> StepResult:
    """CallableExecutor fn for source_data_briefings step."""
    from engine.exceptions import VeritasError

    try:
        from engine.static_audit.tools.source_data_sheet_briefing import (
            build_all_briefings,
        )

        sd_findings = resolve_artifact_path(ctx.workdir, "source_data_findings.json")
        sd_pf = resolve_artifact_path(ctx.workdir, "source_data_pair_forensics.json")
        findings_data = (
            json.loads(sd_findings.read_text(encoding="utf-8"))
            if sd_findings.exists()
            else None
        )
        pf_data = (
            json.loads(sd_pf.read_text(encoding="utf-8")) if sd_pf.exists() else None
        )
        briefings = build_all_briefings(findings_data, pf_data, ctx.source_data_dir)
        briefings_path = resolve_artifact_path(
            ctx.workdir, "source_data_sheet_briefings.json"
        )
        briefings_path.parent.mkdir(parents=True, exist_ok=True)
        briefings_path.write_text(
            json.dumps(briefings, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        bs = briefings.get("sheet_count", 0)
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.RAN,
            detail=f"sheets={bs}",
            output_artifacts=[str(briefings_path)],
        )
    except (VeritasError, OSError) as exc:
        logger.warning("source_data_briefings failed: %s", exc)
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.FAILED,
            detail=f"briefings step exception: {exc}",
            failure_type="briefings_error",
        )


def _run_source_data_verdict_callable(
    ctx: StepContext, definition: StepDefinition
) -> StepResult:
    """CallableExecutor fn for source_data_verdict step."""
    from engine.exceptions import VeritasError

    try:
        from engine.static_audit.tools.source_data_verdict import (
            run_source_data_verdict,
        )

        vr = run_source_data_verdict(
            ctx.workdir,
            source_data_dir=ctx.source_data_dir,
            project_root=PROJECT_ROOT,
            env=ctx.env,
            model=ctx.args.agent_model,
            opencode_bin=ctx.args.opencode_bin,
            force=ctx.force,
            progress=ctx.progress,
        )
        vs = vr.get("summary", {})
        detail = (
            f"sheets={vs.get('total_sheets', 0)} TP={vs.get('true_positive', 0)} "
            f"FP={vs.get('false_positive', 0)} uncertain={vs.get('uncertain', 0)}"
        )
        status = StepStatus.RAN if vs.get("total_sheets", 0) > 0 else StepStatus.SKIPPED
        if vs.get("failed_sheets", 0) > 0:
            status = StepStatus.FAILED
            detail = detail + f" failed_sheets={vs['failed_sheets']}"
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=status,
            detail=detail,
        )
    except (VeritasError, OSError) as exc:
        logger.warning("source_data_verdict failed: %s", exc)
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.FAILED,
            detail=f"verdict step exception: {exc}",
            failure_type="verdict_error",
        )


def build_source_data_plan() -> StagePlan:
    """Build the declarative StagePlan for the source-data stage.

    8 steps, matching the old imperative order:
    1. source_data_profile       — SubprocessExecutor, fail_policy=skip_downstream
    2. source_data_findings      — SubprocessExecutor
    3. source_data_pair_forensics — SubprocessExecutor
    4. source_data_cross_sheet   — SubprocessExecutor
    5. cross_sheet_filter        — CallableExecutor, required=(cross_sheet_json,)
    6. paperconan_scan           — SubprocessExecutor
    7. source_data_briefings     — CallableExecutor
    8. source_data_verdict       — CallableExecutor
    """
    return StagePlan(
        stage_key="source_data",
        steps=(
            StepDefinition(
                key="source_data_profile",
                title="Source Data profile",
                executor=SubprocessExecutor(
                    command_builder=_build_source_data_command,
                    expected_output_keys=("source_data_profile.json",),
                ),
                expected_outputs=("source_data_profile.json",),
                fail_policy="skip_downstream",
                phase="source_data",
            ),
            StepDefinition(
                key="source_data_findings",
                title="Source Data findings",
                executor=SubprocessExecutor(
                    command_builder=_build_source_data_findings_command,
                    expected_output_keys=("source_data_findings.json",),
                ),
                expected_outputs=("source_data_findings.json",),
                fail_policy="continue",
                phase="source_data",
            ),
            StepDefinition(
                key="source_data_pair_forensics",
                title="Source Data pair forensics",
                executor=SubprocessExecutor(
                    command_builder=_build_pair_forensics_command,
                    expected_output_keys=("source_data_pair_forensics.json",),
                ),
                expected_outputs=("source_data_pair_forensics.json",),
                fail_policy="continue",
                phase="source_data",
            ),
            StepDefinition(
                key="source_data_cross_sheet",
                title="Source Data cross-sheet duplicates",
                executor=SubprocessExecutor(
                    command_builder=_build_cross_sheet_command,
                    expected_output_keys=("source_data_cross_sheet.json",),
                ),
                expected_outputs=("source_data_cross_sheet.json",),
                fail_policy="continue",
                phase="source_data",
            ),
            StepDefinition(
                key="cross_sheet_filter",
                title="Cross-sheet LLM metadata filter",
                executor=CallableExecutor(fn=_run_cross_sheet_filter_callable),
                required_artifacts=("source_data_cross_sheet.json",),
                fail_policy="continue",
                phase="source_data",
            ),
            StepDefinition(
                key="paperconan_scan",
                title="Paperconan GRIM/GRIMMER scan",
                executor=SubprocessExecutor(
                    command_builder=_build_paperconan_command,
                    expected_output_keys=("numeric/paperconan_scan.json",),
                ),
                expected_outputs=("numeric/paperconan_scan.json",),
                fail_policy="continue",
                phase="source_data",
            ),
            StepDefinition(
                key="source_data_briefings",
                title="Source Data sheet briefings",
                executor=CallableExecutor(fn=_run_source_data_briefings_callable),
                fail_policy="continue",
                phase="source_data",
            ),
            StepDefinition(
                key="source_data_verdict",
                title="Source Data LLM 语义裁决",
                executor=CallableExecutor(fn=_run_source_data_verdict_callable),
                fail_policy="continue",
                phase="source_data",
            ),
        ),
    )
