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
    timeout_seconds: int = 300

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
            force=False,
            attempts=self.attempts,
            retry_delay_seconds=self.retry_delay_seconds,
            stream_output=self.stream_output,
            timeout_seconds=self.timeout_seconds,
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

    cross_sheet_path = resolve_artifact_path(
        ctx.workdir, "source_data_cross_sheet.json"
    )
    try:
        from engine.llm.client import VeritasLLMClient
        from engine.static_audit._shared import run_cross_sheet_filter

        cross_sheet_data = json.loads(cross_sheet_path.read_text(encoding="utf-8"))
        findings = cross_sheet_data.get(
            "cross_sheet_findings", cross_sheet_data.get("findings", [])
        )

        if findings:
            # N10: Minimum retention rule — when <= 3 findings, skip filter
            # to avoid swallowing rare but potentially important discoveries.
            if len(findings) <= 3:
                cross_sheet_data["findings"] = findings
                cross_sheet_data["filter_metadata"] = {
                    "original_count": len(findings),
                    "filtered_count": len(findings),
                    "filter_applied": False,
                    "skip_reason": "minimum_retention_rule (original_count <= 3)",
                }
                cross_sheet_path.write_text(
                    json.dumps(cross_sheet_data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return StepResult(
                    key=definition.key,
                    title=definition.title,
                    status=StepStatus.RAN,
                    detail=f"retained all {len(findings)} findings (minimum retention rule)",
                )

            llm_client = VeritasLLMClient()
            filtered_findings, filter_reasons = run_cross_sheet_filter(
                ctx.workdir, findings, llm_client
            )
            cross_sheet_data["findings"] = filtered_findings
            cross_sheet_data["filter_metadata"] = {
                "original_count": len(findings),
                "filtered_count": len(filtered_findings),
                "filter_applied": True,
                "filter_reasons": filter_reasons,
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


# ---------------------------------------------------------------------------
# WP2: PaperConan Translator callable
# ---------------------------------------------------------------------------


def _run_paperconan_translate_callable(
    ctx: StepContext, definition: StepDefinition
) -> StepResult:
    """CallableExecutor fn for paperconan_translate step.

    Reads numeric/paperconan_scan.json, translates all PaperConan findings
    into canonical NumericSignals, writes paperconan_signals.json and
    paperconan_translation_ledger.json.
    """
    scan_path = resolve_artifact_path(ctx.workdir, "numeric/paperconan_scan.json")
    if not scan_path.exists():
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.SKIPPED,
            detail="no paperconan_scan.json found",
            skip_reason="no_paperconan_output",
        )
    try:
        scan_data = json.loads(scan_path.read_text(encoding="utf-8"))
        scan_result = scan_data.get("scan_result", scan_data)
        profile = scan_data.get("profile", "review")

        from engine.static_audit.adapters.paperconan_adapter.translator import (
            translate_paperconan_scan,
        )

        result = translate_paperconan_scan(scan_result, profile=profile)

        num_dir = resolve_artifact_path(ctx.workdir, "numeric")
        num_dir.mkdir(parents=True, exist_ok=True)

        signals_path, ledger_path = result.write_artifacts(num_dir)

        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.RAN,
            detail=f"signals={len(result.signals)} skipped={len(result.ledger)}",
            output_artifacts=[str(signals_path), str(ledger_path)],
        )
    except Exception as exc:
        logger.warning("paperconan_translate failed: %s", exc)
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.FAILED,
            detail=f"translate failed: {exc}",
            failure_type="translator_error",
        )


# ---------------------------------------------------------------------------
# WP3: Deterministic Profile/Prefilter callable
# ---------------------------------------------------------------------------


def _run_source_data_prefilter_callable(
    ctx: StepContext, definition: StepDefinition
) -> StepResult:
    """CallableExecutor fn for source_data_prefilter step.

    Reads numeric/paperconan_signals.json, runs deterministic prefilter,
    writes numeric/numeric_prefilter_ledger.json.
    """
    signals_path = resolve_artifact_path(ctx.workdir, "numeric/paperconan_signals.json")
    if not signals_path.exists():
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.SKIPPED,
            detail="no paperconan_signals.json found",
            skip_reason="no_canonical_signals",
        )
    try:
        signals_data = json.loads(signals_path.read_text(encoding="utf-8"))
        # NumericSignalSet.to_dict() returns {"signals": [...], ...}
        signals = (
            signals_data.get("signals", signals_data)
            if isinstance(signals_data, dict)
            else signals_data
        )
        profile = getattr(ctx.args, "profile", "review") or "review"

        from engine.static_audit.tools.source_data_prefilter.prefilter import (
            run_prefilter,
        )

        ledger = run_prefilter(signals, profile=profile)

        num_dir = resolve_artifact_path(ctx.workdir, "numeric")
        ledger_path = num_dir / "numeric_prefilter_ledger.json"
        ledger_path.write_text(
            json.dumps(
                ledger.to_dict() if hasattr(ledger, "to_dict") else ledger,
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.RAN,
            detail=f"profile={profile} entries={len(signals)}",
            output_artifacts=[str(ledger_path)],
        )
    except Exception as exc:
        logger.warning("source_data_prefilter failed: %s", exc, exc_info=True)
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.FAILED,
            detail=f"prefilter failed: {exc}",
            failure_type="prefilter_error",
        )


# ---------------------------------------------------------------------------
# WP8: Claim/Impact Fusion callable
# ---------------------------------------------------------------------------


def _run_claim_fusion_callable(
    ctx: StepContext, definition: StepDefinition
) -> StepResult:
    """CallableExecutor fn for claim_fusion step.

    Reads numeric/paperconan_signals.json and paper metadata (if available),
    enriches signals with claim_refs/impact_scope, writes
    numeric/enriched_signals.json.
    """
    signals_path = resolve_artifact_path(ctx.workdir, "numeric/paperconan_signals.json")
    if not signals_path.exists():
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.SKIPPED,
            detail="no canonical signals to enrich",
            skip_reason="no_canonical_signals",
        )
    try:
        signals_dicts = json.loads(signals_path.read_text(encoding="utf-8"))
        # NumericSignalSet.to_dict() returns {"signals": [...], ...}
        signals_list = (
            signals_dicts.get("signals", signals_dicts)
            if isinstance(signals_dicts, dict)
            else signals_dicts
        )

        from engine.static_audit.numeric_signal_schema import NumericSignal

        signals = [NumericSignal.from_dict(s) for s in signals_list]

        # Try to load paper metadata for claim mapping
        paper_meta_path = resolve_artifact_path(ctx.workdir, "paper_metadata.json")
        claim_index = None
        if paper_meta_path.exists():
            try:
                paper_meta = json.loads(paper_meta_path.read_text(encoding="utf-8"))
                from engine.static_audit.claim_fusion import build_claim_index

                claim_index = build_claim_index(
                    claims=paper_meta.get("claims"),
                    figures=paper_meta.get("figures"),
                    source_data_map=paper_meta.get("source_data_map"),
                )
            except Exception:
                claim_index = None

        enriched = signals
        if claim_index is not None:
            from engine.static_audit.claim_fusion import (
                fuse_signals_to_claims,
                enrich_signal_with_claim_mapping,
            )

            claim_mappings = fuse_signals_to_claims(signals, claim_index)
            # fuse_signals_to_claims returns list[ClaimMapping] in signal order;
            # build a lookup dict by signal_id.
            mapping_by_id = {m.signal_id: m for m in claim_mappings}
            enriched = []
            for sig in signals:
                mapping = mapping_by_id.get(sig.signal_id)
                if mapping:
                    enriched.append(enrich_signal_with_claim_mapping(sig, mapping))
                else:
                    enriched.append(sig)

        num_dir = resolve_artifact_path(ctx.workdir, "numeric")
        enriched_path = num_dir / "enriched_signals.json"
        # Write as NumericSignalSet wrapper (Q5: unified format with metadata)
        from engine.static_audit.numeric_signal_schema import NumericSignalSet

        enriched_set = NumericSignalSet(signals=enriched)
        enriched_path.write_text(
            json.dumps(enriched_set.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        mapped_count = sum(1 for s in enriched if s.impact_scope != "unknown")
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.RAN,
            detail=f"signals={len(enriched)} claim_mapped={mapped_count}",
            output_artifacts=[str(enriched_path)],
        )
    except Exception as exc:
        logger.warning("claim_fusion failed: %s", exc)
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.FAILED,
            detail=f"claim_fusion failed: {exc}",
            failure_type="claim_fusion_error",
        )


# ---------------------------------------------------------------------------
# WP7: Review Dossier builder callable
# ---------------------------------------------------------------------------


def _run_build_review_dossiers_callable(
    ctx: StepContext, definition: StepDefinition
) -> StepResult:
    """CallableExecutor fn for build_review_dossiers step.

    Reads enriched signals (or paperconan_signals as fallback) and builds
    ReviewDossier for high-priority signals (tier 1 or 2).
    """
    enriched_path = resolve_artifact_path(ctx.workdir, "numeric/enriched_signals.json")
    fallback_path = resolve_artifact_path(
        ctx.workdir, "numeric/paperconan_signals.json"
    )
    sig_path = enriched_path if enriched_path.exists() else fallback_path
    if not sig_path.exists():
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.SKIPPED,
            detail="no signals to build dossiers from",
            skip_reason="no_signals",
        )
    try:
        from engine.static_audit.numeric_signal_schema import NumericSignal
        from engine.static_audit.dossiers.review_dossier import ReviewDossier

        signals_data = json.loads(sig_path.read_text(encoding="utf-8"))
        signals_list = (
            signals_data.get("signals", signals_data)
            if isinstance(signals_data, dict)
            else signals_data
        )
        signals = [NumericSignal.from_dict(s) for s in signals_list]

        # Build dossiers for tier 1/2 (high/critical risk) signals
        high_priority = [s for s in signals if s.risk_level_raw in ("critical", "high")]

        dossiers_dir = resolve_artifact_path(ctx.workdir, "numeric/review_dossiers")
        dossiers_dir.mkdir(parents=True, exist_ok=True)

        dossier_ids = []
        for sig in high_priority:
            dossier = ReviewDossier(
                dossier_id=f"DOSSIER-{sig.signal_id}",
                target_signal_ids=[sig.signal_id],
                signal_summary=f"{sig.detector_family}/{sig.raw_kind}",
                detector_family=sig.detector_family,
                risk_level_raw=sig.risk_level_raw,
                evidence_locator=(
                    sig.evidence_locator.to_dict() if sig.evidence_locator else {}
                ),
                claim_refs=sig.claim_refs,
                figure_refs=sig.figure_refs,
                impact_scope=sig.impact_scope,
                review_status="pending",
            )
            dossier_path = dossiers_dir / f"{sig.signal_id}.json"
            dossier_path.write_text(
                json.dumps(
                    dossier.to_dict() if hasattr(dossier, "to_dict") else {},
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                ),
                encoding="utf-8",
            )
            dossier_ids.append(sig.signal_id)

        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.RAN,
            detail=f"dossiers={len(dossier_ids)} high_priority={len(high_priority)}",
            output_artifacts=[str(dossiers_dir)],
        )
    except Exception as exc:
        logger.warning("build_review_dossiers failed: %s", exc, exc_info=True)
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.FAILED,
            detail=f"dossier build failed: {exc}",
            failure_type="dossier_error",
        )


# ---------------------------------------------------------------------------
# WP7: Red-Team Refute callable
# ---------------------------------------------------------------------------


def _run_red_team_refute_callable(
    ctx: StepContext, definition: StepDefinition
) -> StepResult:
    """CallableExecutor fn for red_team_refute step.

    Reads review dossiers, runs red-team refute on pending dossiers,
    writes refute artifacts.
    """
    dossiers_dir = resolve_artifact_path(ctx.workdir, "numeric/review_dossiers")
    if not dossiers_dir.exists():
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.SKIPPED,
            detail="no review dossiers found",
            skip_reason="no_dossiers",
        )
    try:
        from engine.static_audit.dossiers.review_dossier import ReviewDossier
        from engine.static_audit.dossiers.red_team_refute import (
            RefuteAttempt,
            run_red_team_refute,
        )
        from engine.static_audit.dossiers.refute_checklist import (
            REFUTE_CHECKLIST,
        )

        refute_dir = resolve_artifact_path(ctx.workdir, "numeric/refute_reviews")
        refute_dir.mkdir(parents=True, exist_ok=True)

        dossier_files = list(dossiers_dir.glob("*.json"))
        refute_count = 0

        for df in dossier_files:
            try:
                dossier_data = json.loads(df.read_text(encoding="utf-8"))
                review_status = dossier_data.get("review_status", "pending")
                if review_status != "pending":
                    continue

                # Construct proper ReviewDossier from persisted JSON
                dossier = ReviewDossier.from_dict(dossier_data)
                signal_id = (
                    dossier.target_signal_ids[0]
                    if dossier.target_signal_ids
                    else df.stem
                )

                # Build initial refute attempts from the 10-item checklist.
                # All mechanisms start as "not_checked" — LLM integration
                # will populate these in a future phase.
                refute_attempts = [
                    RefuteAttempt(
                        mechanism=item.mechanism,
                        status="not_checked",
                        note=item.label,
                    )
                    for item in REFUTE_CHECKLIST
                ]

                refute = run_red_team_refute(
                    dossier=dossier,
                    refute_attempts=refute_attempts,
                    review_id=f"REFUTE-{signal_id}",
                    recommended_final_status="needs_more_material",
                )
                refute_path = refute_dir / f"{signal_id}_refute.json"
                refute_path.write_text(
                    json.dumps(
                        refute.to_dict(),
                        indent=2,
                        ensure_ascii=False,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                refute_count += 1
            except Exception as single_exc:
                logger.warning(
                    "refute for %s failed: %s", df.name, single_exc, exc_info=True
                )

        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.RAN,
            detail=f"refute_reviews={refute_count}/{len(dossier_files)}",
            output_artifacts=[str(refute_dir)],
        )
    except Exception as exc:
        logger.warning("red_team_refute failed: %s", exc, exc_info=True)
        return StepResult(
            key=definition.key,
            title=definition.title,
            status=StepStatus.FAILED,
            detail=f"red_team_refute failed: {exc}",
            failure_type="refute_error",
        )


def build_source_data_plan() -> StagePlan:
    """Build the declarative StagePlan for the source-data stage.

    13 steps (original 8 + 5 PRD integration steps):
    1. source_data_profile       — SubprocessExecutor, fail_policy=skip_downstream
    2. source_data_findings      — SubprocessExecutor
    3. source_data_pair_forensics — SubprocessExecutor
    4. source_data_cross_sheet   — SubprocessExecutor
    5. cross_sheet_filter        — CallableExecutor, required=(cross_sheet_json,)
    6. paperconan_scan           — SubprocessExecutor
    7. paperconan_translate      — CallableExecutor (WP2)
    8. source_data_prefilter     — CallableExecutor (WP3)
    9. source_data_briefings     — CallableExecutor
    10. claim_fusion             — CallableExecutor (WP8)
    11. build_review_dossiers    — CallableExecutor (WP7)
    12. source_data_verdict      — CallableExecutor
    13. red_team_refute          — CallableExecutor (WP7)
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
                    timeout_seconds=900,  # P2-1: 15 min for large workbooks
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
                key="paperconan_translate",
                title="PaperConan scan → canonical NumericSignals",
                executor=CallableExecutor(fn=_run_paperconan_translate_callable),
                required_artifacts=("numeric/paperconan_scan.json",),
                expected_outputs=(
                    "numeric/paperconan_signals.json",
                    "numeric/paperconan_translation_ledger.json",
                ),
                fail_policy="continue",
                phase="source_data",
            ),
            StepDefinition(
                key="source_data_prefilter",
                title="Deterministic profile/prefilter ledger",
                executor=CallableExecutor(fn=_run_source_data_prefilter_callable),
                required_artifacts=("numeric/paperconan_signals.json",),
                expected_outputs=("numeric/numeric_prefilter_ledger.json",),
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
                key="claim_fusion",
                title="Claim / impact signal enrichment",
                executor=CallableExecutor(fn=_run_claim_fusion_callable),
                fail_policy="continue",
                phase="source_data",
            ),
            StepDefinition(
                key="build_review_dossiers",
                title="Review dossier builder (tier 1/2)",
                executor=CallableExecutor(fn=_run_build_review_dossiers_callable),
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
            StepDefinition(
                key="red_team_refute",
                title="Red-team adversarial refute review",
                executor=CallableExecutor(fn=_run_red_team_refute_callable),
                fail_policy="continue",
                phase="source_data",
            ),
        ),
    )
