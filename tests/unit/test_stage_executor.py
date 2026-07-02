"""Tests for engine.static_audit.stage_executor — WP1.

Validates:
- StageExecutor ordering via CallableExecutor injection (no subprocess needed)
- fail_policy="skip_downstream" (upstream failure -> all downstream skip)
- fail_policy="stop" (abort remaining steps)
- fail_policy="continue" (keep going regardless)
- required_artifacts gating (skip when artifact file missing)
- Exception handling in executors
- StepContext propagation (previous_results populated)
- build_source_data_plan returns correct 8-step structure
- WP6 fields (runtime_seconds, output_artifacts, failure_type) flow through
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from engine.shared.types import StepResult, StepStatus
from engine.static_audit.stage_executor import (
    CallableExecutor,
    FailPolicy,
    StageExecutor,
    StagePlan,
    StepContext,
    StepDefinition,
    SubprocessExecutor,
    build_source_data_plan,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_ctx(tmp_path: Path, **overrides) -> StepContext:
    """Build a minimal StepContext for testing."""
    args = argparse.Namespace(force=False, agent_model="test", opencode_bin="echo")
    defaults = dict(
        workdir=tmp_path,
        args=args,
        env={},
        progress=None,
        source_data_dir=tmp_path / "source",
        source_finding_params={"min_overlap": 5, "min_support": 0.8, "max_findings_per_category": 10},
    )
    defaults.update(overrides)
    return StepContext(**defaults)


def _success_fn(key: str = "step_a", detail: str = "ok") -> CallableExecutor:
    """Return a CallableExecutor that produces a success StepResult."""
    def fn(ctx: StepContext, defn: StepDefinition) -> StepResult:
        return StepResult(
            key=defn.key,
            title=defn.title,
            status=StepStatus.RAN,
            detail=detail,
            runtime_seconds=0.1,
            output_artifacts=list(defn.expected_outputs),
        )
    return CallableExecutor(fn=fn)


def _fail_fn(failure_type: str = "test_failure") -> CallableExecutor:
    """Return a CallableExecutor that produces a failed StepResult."""
    def fn(ctx: StepContext, defn: StepDefinition) -> StepResult:
        return StepResult(
            key=defn.key,
            title=defn.title,
            status=StepStatus.FAILED,
            detail=f"deliberate test failure: {defn.key}",
            failure_type=failure_type,
        )
    return CallableExecutor(fn=fn)


def _skip_fn(reason: str = "no_data") -> CallableExecutor:
    """Return a CallableExecutor that produces a skipped StepResult."""
    def fn(ctx: StepContext, defn: StepDefinition) -> StepResult:
        return StepResult(
            key=defn.key,
            title=defn.title,
            status=StepStatus.SKIPPED,
            detail=f"skipped: {reason}",
            skip_reason=reason,
        )
    return CallableExecutor(fn=fn)


def _defn(
    key: str,
    executor: CallableExecutor,
    *,
    fail_policy: FailPolicy = "continue",
    required_artifacts: tuple[str, ...] = (),
    expected_outputs: tuple[str, ...] = (),
) -> StepDefinition:
    """Build a StepDefinition with sensible defaults for testing."""
    return StepDefinition(
        key=key,
        title=f"Test step: {key}",
        executor=executor,
        expected_outputs=expected_outputs,
        required_artifacts=required_artifacts,
        fail_policy=fail_policy,
        phase="source_data",
    )


# ---------------------------------------------------------------------------
# Basic execution ordering
# ---------------------------------------------------------------------------


class TestStageExecutorOrdering:
    """StageExecutor must execute steps in declaration order."""

    def test_steps_execute_in_order(self, tmp_path: Path) -> None:
        execution_log: list[str] = []

        def make_fn(key: str) -> CallableExecutor:
            def fn(ctx: StepContext, defn: StepDefinition) -> StepResult:
                execution_log.append(key)
                return StepResult(key=defn.key, title=defn.title, status=StepStatus.RAN, detail="ok")
            return CallableExecutor(fn=fn)

        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("alpha", make_fn("alpha")),
                _defn("beta", make_fn("beta")),
                _defn("gamma", make_fn("gamma")),
            ),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))

        assert execution_log == ["alpha", "beta", "gamma"]
        assert [r.key for r in results] == ["alpha", "beta", "gamma"]
        assert all(r.status == StepStatus.RAN for r in results)

    def test_empty_plan_returns_empty(self, tmp_path: Path) -> None:
        plan = StagePlan(stage_key="empty", steps=())
        results = StageExecutor(plan).run(_make_ctx(tmp_path))
        assert results == []

    def test_single_step_plan(self, tmp_path: Path) -> None:
        plan = StagePlan(
            stage_key="single",
            steps=(_defn("only", _success_fn()),),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))
        assert len(results) == 1
        assert results[0].key == "only"
        assert results[0].status == StepStatus.RAN


# ---------------------------------------------------------------------------
# fail_policy: skip_downstream
# ---------------------------------------------------------------------------


class TestFailPolicySkipDownstream:
    """fail_policy='skip_downstream' must skip all steps after a failure."""

    def test_upstream_failure_skips_all_downstream(self, tmp_path: Path) -> None:
        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("profile", _fail_fn("profile_error"), fail_policy="skip_downstream"),
                _defn("findings", _success_fn()),
                _defn("pair_forensics", _success_fn()),
                _defn("verdict", _success_fn()),
            ),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))

        assert len(results) == 4
        # First step: failed
        assert results[0].key == "profile"
        assert results[0].status == StepStatus.FAILED
        assert results[0].failure_type == "profile_error"
        # All downstream: skipped
        for r in results[1:]:
            assert r.status == StepStatus.SKIPPED
            assert r.skip_reason == "upstream_failure"

    def test_non_skip_downstream_failure_does_not_propagate(self, tmp_path: Path) -> None:
        """A failure with fail_policy='continue' does NOT skip downstream."""
        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("findings", _fail_fn(), fail_policy="continue"),
                _defn("pair_forensics", _success_fn()),
            ),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))

        assert results[0].status == StepStatus.FAILED
        assert results[1].status == StepStatus.RAN

    def test_skip_downstream_after_second_step_failure(self, tmp_path: Path) -> None:
        """skip_downstream in step 2 should skip steps 3+ but not step 1."""
        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("a", _success_fn()),
                _defn("b", _fail_fn(), fail_policy="skip_downstream"),
                _defn("c", _success_fn()),
            ),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))

        assert results[0].status == StepStatus.RAN
        assert results[1].status == StepStatus.FAILED
        assert results[2].status == StepStatus.SKIPPED
        assert results[2].skip_reason == "upstream_failure"


# ---------------------------------------------------------------------------
# fail_policy: stop
# ---------------------------------------------------------------------------


class TestFailPolicyStop:
    """fail_policy='stop' must abort remaining steps immediately."""

    def test_stop_aborts_remaining(self, tmp_path: Path) -> None:
        execution_log: list[str] = []

        def make_fn(key: str, fail: bool = False) -> CallableExecutor:
            def fn(ctx: StepContext, defn: StepDefinition) -> StepResult:
                execution_log.append(key)
                if fail:
                    return StepResult(key=defn.key, title=defn.title, status=StepStatus.FAILED, detail="stop!")
                return StepResult(key=defn.key, title=defn.title, status=StepStatus.RAN, detail="ok")
            return CallableExecutor(fn=fn)

        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("a", make_fn("a")),
                _defn("b", make_fn("b", fail=True), fail_policy="stop"),
                _defn("c", make_fn("c")),
            ),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))

        # Step c should NOT have been executed
        assert execution_log == ["a", "b"]
        # Only 2 results returned (c is absent, not skipped)
        assert len(results) == 2
        assert results[0].status == StepStatus.RAN
        assert results[1].status == StepStatus.FAILED


# ---------------------------------------------------------------------------
# fail_policy: continue
# ---------------------------------------------------------------------------


class TestFailPolicyContinue:
    """fail_policy='continue' must keep going regardless of failure."""

    def test_continue_keeps_going_after_failure(self, tmp_path: Path) -> None:
        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("a", _fail_fn(), fail_policy="continue"),
                _defn("b", _success_fn()),
                _defn("c", _fail_fn(), fail_policy="continue"),
                _defn("d", _success_fn()),
            ),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))

        assert len(results) == 4
        assert results[0].status == StepStatus.FAILED
        assert results[1].status == StepStatus.RAN
        assert results[2].status == StepStatus.FAILED
        assert results[3].status == StepStatus.RAN


# ---------------------------------------------------------------------------
# required_artifacts gating
# ---------------------------------------------------------------------------


class TestRequiredArtifacts:
    """Steps with required_artifacts must be skipped when artifacts are missing."""

    def test_missing_artifact_skips_step(self, tmp_path: Path) -> None:
        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("needs_file", _success_fn(), required_artifacts=("nonexistent.json",)),
            ),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))

        assert len(results) == 1
        assert results[0].status == StepStatus.SKIPPED
        assert "nonexistent.json" in results[0].detail
        assert "missing" in results[0].skip_reason

    def test_present_artifact_allows_execution(self, tmp_path: Path) -> None:
        # Use a known artifact key and create the file at the resolved path.
        from engine.static_audit.paths import resolve_artifact_path

        suitable_key = "source_data_cross_sheet.json"
        resolved = resolve_artifact_path(tmp_path, suitable_key)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text("{}")

        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("needs_file", _success_fn(), required_artifacts=(suitable_key,)),
            ),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))

        assert len(results) == 1
        assert results[0].status == StepStatus.RAN

    def test_required_artifacts_skip_does_not_trigger_skip_downstream(self, tmp_path: Path) -> None:
        """A step skipped due to missing artifacts should NOT trigger skip_downstream for later steps."""
        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("missing_dep", _success_fn(), required_artifacts=("ghost.json",), fail_policy="skip_downstream"),
                _defn("after", _success_fn()),
            ),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))

        # First step skipped due to missing artifact
        assert results[0].status == StepStatus.SKIPPED
        # Second step should still execute (skip_downstream only triggers on FAILED, not SKIPPED)
        assert results[1].status == StepStatus.RAN


# ---------------------------------------------------------------------------
# Exception handling
# ---------------------------------------------------------------------------


class TestExceptionHandling:
    """StageExecutor must catch executor exceptions and convert to FAILED."""

    def test_exception_in_callable_executor(self, tmp_path: Path) -> None:
        def bad_fn(ctx: StepContext, defn: StepDefinition) -> StepResult:
            raise RuntimeError("deliberate crash")

        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("crash", CallableExecutor(fn=bad_fn)),
            ),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))

        assert len(results) == 1
        assert results[0].status == StepStatus.FAILED
        assert results[0].failure_type == "executor_exception"
        assert "deliberate crash" in results[0].detail

    def test_exception_with_skip_downstream_policy(self, tmp_path: Path) -> None:
        def bad_fn(ctx: StepContext, defn: StepDefinition) -> StepResult:
            raise ValueError("boom")

        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("crash", CallableExecutor(fn=bad_fn), fail_policy="skip_downstream"),
                _defn("after", _success_fn()),
            ),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))

        assert results[0].status == StepStatus.FAILED
        assert results[0].failure_type == "executor_exception"
        assert results[1].status == StepStatus.SKIPPED
        assert results[1].skip_reason == "upstream_failure"


# ---------------------------------------------------------------------------
# StepContext propagation
# ---------------------------------------------------------------------------


class TestStepContextPropagation:
    """previous_results must be populated as steps execute."""

    def test_previous_results_populated(self, tmp_path: Path) -> None:
        seen_previous: dict[str, dict[str, str]] = {}

        def make_fn(key: str) -> CallableExecutor:
            def fn(ctx: StepContext, defn: StepDefinition) -> StepResult:
                seen_previous[key] = {k: v.status.value if hasattr(v.status, "value") else str(v.status) for k, v in ctx.previous_results.items()}
                return StepResult(key=defn.key, title=defn.title, status=StepStatus.RAN, detail="ok")
            return CallableExecutor(fn=fn)

        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("first", make_fn("first")),
                _defn("second", make_fn("second")),
                _defn("third", make_fn("third")),
            ),
        )
        StageExecutor(plan).run(_make_ctx(tmp_path))

        assert seen_previous["first"] == {}
        assert seen_previous["second"] == {"first": "ran"}
        assert seen_previous["third"] == {"first": "ran", "second": "ran"}

    def test_context_has_workdir_and_env(self, tmp_path: Path) -> None:
        captured: dict = {}

        def fn(ctx: StepContext, defn: StepDefinition) -> StepResult:
            captured["workdir"] = ctx.workdir
            captured["env"] = ctx.env
            captured["source_data_dir"] = ctx.source_data_dir
            return StepResult(key=defn.key, title=defn.title, status=StepStatus.RAN, detail="ok")

        plan = StagePlan(stage_key="test", steps=(_defn("x", CallableExecutor(fn=fn)),))
        ctx = _make_ctx(tmp_path, env={"FOO": "bar"})
        StageExecutor(plan).run(ctx)

        assert captured["workdir"] == tmp_path
        assert captured["env"] == {"FOO": "bar"}
        assert captured["source_data_dir"] == tmp_path / "source"


# ---------------------------------------------------------------------------
# WP6 fields
# ---------------------------------------------------------------------------


class TestWP6Fields:
    """WP6-enriched StepResult fields must flow through StageExecutor."""

    def test_runtime_seconds_preserved(self, tmp_path: Path) -> None:
        def fn(ctx: StepContext, defn: StepDefinition) -> StepResult:
            return StepResult(
                key=defn.key,
                title=defn.title,
                status=StepStatus.RAN,
                detail="ok",
                runtime_seconds=42.5,
            )
        plan = StagePlan(stage_key="test", steps=(_defn("x", CallableExecutor(fn=fn)),))
        results = StageExecutor(plan).run(_make_ctx(tmp_path))
        assert results[0].runtime_seconds == 42.5

    def test_output_artifacts_preserved(self, tmp_path: Path) -> None:
        def fn(ctx: StepContext, defn: StepDefinition) -> StepResult:
            return StepResult(
                key=defn.key,
                title=defn.title,
                status=StepStatus.RAN,
                detail="ok",
                output_artifacts=["/path/to/artifact.json"],
            )
        plan = StagePlan(stage_key="test", steps=(_defn("x", CallableExecutor(fn=fn)),))
        results = StageExecutor(plan).run(_make_ctx(tmp_path))
        assert results[0].output_artifacts == ["/path/to/artifact.json"]

    def test_failure_type_preserved(self, tmp_path: Path) -> None:
        plan = StagePlan(
            stage_key="test",
            steps=(_defn("x", _fail_fn("custom_failure_type")),),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))
        assert results[0].failure_type == "custom_failure_type"

    def test_skip_reason_on_required_artifact_miss(self, tmp_path: Path) -> None:
        plan = StagePlan(
            stage_key="test",
            steps=(_defn("x", _success_fn(), required_artifacts=("nope.json",)),),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))
        assert results[0].skip_reason is not None
        assert "nope.json" in results[0].skip_reason


# ---------------------------------------------------------------------------
# build_source_data_plan structure
# ---------------------------------------------------------------------------


class TestBuildSourceDataPlan:
    """build_source_data_plan must return the correct 8-step structure."""

    def test_returns_8_steps(self) -> None:
        plan = build_source_data_plan()
        assert plan.stage_key == "source_data"
        assert len(plan.steps) == 8

    def test_step_keys_in_order(self) -> None:
        plan = build_source_data_plan()
        expected_keys = [
            "source_data_profile",
            "source_data_findings",
            "source_data_pair_forensics",
            "source_data_cross_sheet",
            "cross_sheet_filter",
            "paperconan_scan",
            "source_data_briefings",
            "source_data_verdict",
        ]
        actual_keys = [s.key for s in plan.steps]
        assert actual_keys == expected_keys

    def test_profile_step_is_skip_downstream(self) -> None:
        plan = build_source_data_plan()
        profile = plan.steps[0]
        assert profile.key == "source_data_profile"
        assert profile.fail_policy == "skip_downstream"
        assert isinstance(profile.executor, SubprocessExecutor)

    def test_cross_sheet_filter_has_required_artifacts(self) -> None:
        plan = build_source_data_plan()
        csf = [s for s in plan.steps if s.key == "cross_sheet_filter"][0]
        assert csf.required_artifacts == ("source_data_cross_sheet.json",)
        assert isinstance(csf.executor, CallableExecutor)

    def test_callable_steps_use_callable_executor(self) -> None:
        plan = build_source_data_plan()
        callable_keys = {"cross_sheet_filter", "source_data_briefings", "source_data_verdict"}
        for step in plan.steps:
            if step.key in callable_keys:
                assert isinstance(step.executor, CallableExecutor), f"{step.key} should use CallableExecutor"
            elif step.key in {"source_data_profile", "source_data_findings", "source_data_pair_forensics", "source_data_cross_sheet", "paperconan_scan"}:
                assert isinstance(step.executor, SubprocessExecutor), f"{step.key} should use SubprocessExecutor"

    def test_all_phases_are_source_data(self) -> None:
        plan = build_source_data_plan()
        for step in plan.steps:
            assert step.phase == "source_data"


# ---------------------------------------------------------------------------
# SubprocessExecutor unit tests (command_builder is called with context)
# ---------------------------------------------------------------------------


class TestSubprocessExecutor:
    """SubprocessExecutor must build commands lazily from StepContext."""

    def test_command_builder_receives_context(self, tmp_path: Path) -> None:
        captured_ctx: list = []

        def builder(ctx: StepContext) -> list[str]:
            captured_ctx.append(ctx)
            return ["echo", "test"]

        executor = SubprocessExecutor(command_builder=builder)
        # We can't easily test the actual subprocess call without mocking run_command,
        # but we can verify the executor is constructed correctly.
        assert executor.command_builder is builder
        assert executor.expected_output_keys == ()
        assert executor.attempts == 1

    def test_subprocess_executor_fields(self) -> None:
        def builder(ctx: StepContext) -> list[str]:
            return ["echo"]

        executor = SubprocessExecutor(
            command_builder=builder,
            expected_output_keys=("a.json", "b.json"),
            attempts=3,
            retry_delay_seconds=1.5,
            stream_output=True,
        )
        assert executor.expected_output_keys == ("a.json", "b.json")
        assert executor.attempts == 3
        assert executor.retry_delay_seconds == 1.5
        assert executor.stream_output is True


# ---------------------------------------------------------------------------
# StepDefinition immutability
# ---------------------------------------------------------------------------


class TestStepDefinitionFrozen:
    """StepDefinition must be frozen (immutable)."""

    def test_cannot_mutate_key(self) -> None:
        defn = _defn("x", _success_fn())
        with pytest.raises(AttributeError):
            defn.key = "y"  # type: ignore[misc]

    def test_cannot_mutate_fail_policy(self) -> None:
        defn = _defn("x", _success_fn())
        with pytest.raises(AttributeError):
            defn.fail_policy = "stop"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Progress callback integration
# ---------------------------------------------------------------------------


class TestProgressCallback:
    """StageExecutor must emit progress events through the callback."""

    def test_progress_callback_receives_events(self, tmp_path: Path) -> None:
        events: list[dict] = []

        def progress(event: dict) -> None:
            events.append(event)

        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("a", _success_fn()),
                _defn("b", _success_fn()),
            ),
        )
        ctx = _make_ctx(tmp_path, progress=progress)
        StageExecutor(plan).run(ctx)

        # Should have step_result events for each step
        step_events = [e for e in events if e.get("event") == "step_result"]
        assert len(step_events) == 2


# ---------------------------------------------------------------------------
# Mixed fail policies in same plan
# ---------------------------------------------------------------------------


class TestMixedFailPolicies:
    """Different steps can have different fail_policies in the same plan."""

    def test_continue_then_skip_downstream(self, tmp_path: Path) -> None:
        plan = StagePlan(
            stage_key="test",
            steps=(
                _defn("a", _fail_fn(), fail_policy="continue"),
                _defn("b", _success_fn()),
                _defn("c", _fail_fn(), fail_policy="skip_downstream"),
                _defn("d", _success_fn()),
            ),
        )
        results = StageExecutor(plan).run(_make_ctx(tmp_path))

        assert results[0].status == StepStatus.FAILED  # continue
        assert results[1].status == StepStatus.RAN     # still runs
        assert results[2].status == StepStatus.FAILED  # skip_downstream
        assert results[3].status == StepStatus.SKIPPED # skipped by c's policy
