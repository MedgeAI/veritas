from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from web.backend.veritas_web.case_store import CaseStore
from web.backend.veritas_web.runner import AuditRunner, _resolve_max_concurrent


def _noop_audit_func(paper_dir: Path, **kwargs: Any) -> dict[str, Any]:
    """Minimal audit function that returns immediately."""
    case_id = kwargs["case_id"]
    output_root = Path(kwargs["output_root"])
    workdir = output_root / case_id / "research-integrity-audit"
    workdir.mkdir(parents=True, exist_ok=True)
    return {
        "exit_code": 0,
        "case_id": case_id,
        "workdir": str(workdir),
        "final_html_report": "",
        "failed_steps": [],
    }


def _make_store_with_cases(tmp_path: Path, count: int) -> CaseStore:
    """Create a CaseStore with *count* cases, each with a run and input files."""
    store = CaseStore(tmp_path / "web_data")
    for i in range(count):
        case = store.create_case(case_id=f"case-{i}")
        store.write_input(case.case_id, "paper.pdf", b"%PDF-1.4\n")
        store.create_run(case.case_id)
    return store


def _set_runs_running(store: CaseStore, indices: list[int]) -> None:
    """Set runs at given indices to status='running'."""
    all_runs = store.list_all_runs()
    for idx in indices:
        all_runs[idx].status = "running"
        store.save_run(all_runs[idx])


# ------------------------------------------------------------------
# _resolve_max_concurrent
# ------------------------------------------------------------------


def test_resolve_max_concurrent_default() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VERITAS_MAX_CONCURRENT_AUDITS", None)
        assert _resolve_max_concurrent() == 5


def test_resolve_max_concurrent_env_override() -> None:
    with patch.dict(os.environ, {"VERITAS_MAX_CONCURRENT_AUDITS": "8"}):
        assert _resolve_max_concurrent() == 8


def test_resolve_max_concurrent_invalid_falls_back_to_5() -> None:
    with patch.dict(os.environ, {"VERITAS_MAX_CONCURRENT_AUDITS": "garbage"}):
        assert _resolve_max_concurrent() == 5


def test_resolve_max_concurrent_zero_clamps_to_one() -> None:
    with patch.dict(os.environ, {"VERITAS_MAX_CONCURRENT_AUDITS": "0"}):
        assert _resolve_max_concurrent() == 1


def test_resolve_max_concurrent_negative_clamps_to_one() -> None:
    with patch.dict(os.environ, {"VERITAS_MAX_CONCURRENT_AUDITS": "-3"}):
        assert _resolve_max_concurrent() == 1


# ------------------------------------------------------------------
# AuditRunner: max_concurrent resolution
# ------------------------------------------------------------------


def test_default_max_concurrent_is_5(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "web_data")
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VERITAS_MAX_CONCURRENT_AUDITS", None)
        runner = AuditRunner(store, audit_func=_noop_audit_func)
    assert runner._max_concurrent == 5


def test_explicit_max_workers_overrides_env(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "web_data")
    with patch.dict(os.environ, {"VERITAS_MAX_CONCURRENT_AUDITS": "10"}):
        runner = AuditRunner(
            store, audit_func=_noop_audit_func, max_workers=2
        )
    assert runner._max_concurrent == 2


def test_env_var_sets_max_concurrent_when_no_explicit_workers(
    tmp_path: Path,
) -> None:
    store = CaseStore(tmp_path / "web_data")
    with patch.dict(os.environ, {"VERITAS_MAX_CONCURRENT_AUDITS": "7"}):
        runner = AuditRunner(store, audit_func=_noop_audit_func)
    assert runner._max_concurrent == 7


# ------------------------------------------------------------------
# AuditRunner: _active_runs_count
# ------------------------------------------------------------------


def test_active_runs_count_zero_when_no_running(tmp_path: Path) -> None:
    store = _make_store_with_cases(tmp_path, 3)
    runner = AuditRunner(store, audit_func=_noop_audit_func, max_workers=5)
    # Fresh runs default to non-running status
    assert runner._active_runs_count() == 0


def test_active_runs_count_counts_only_running(tmp_path: Path) -> None:
    store = _make_store_with_cases(tmp_path, 4)
    runner = AuditRunner(store, audit_func=_noop_audit_func, max_workers=5)

    all_runs = store.list_all_runs()

    # Mark 2 as running
    all_runs[0].status = "running"
    store.save_run(all_runs[0])
    all_runs[2].status = "running"
    store.save_run(all_runs[2])
    assert runner._active_runs_count() == 2

    # Mark others as terminal states — should not affect count
    all_runs[1].status = "completed"
    store.save_run(all_runs[1])
    all_runs[3].status = "failed"
    store.save_run(all_runs[3])
    assert runner._active_runs_count() == 2


# ------------------------------------------------------------------
# AuditRunner: start() concurrency guard
# ------------------------------------------------------------------


def test_start_raises_429_when_at_capacity(tmp_path: Path) -> None:
    store = _make_store_with_cases(tmp_path, 3)
    runner = AuditRunner(store, audit_func=_noop_audit_func, max_workers=2)

    _set_runs_running(store, [0, 1])
    assert runner._active_runs_count() == 2

    all_runs = store.list_all_runs()
    with pytest.raises(HTTPException) as exc_info:
        runner.start(all_runs[2].case_id)

    assert exc_info.value.status_code == 429
    assert "Too many concurrent audits" in exc_info.value.detail
    assert "max=2" in exc_info.value.detail


def test_start_succeeds_when_below_capacity(tmp_path: Path) -> None:
    store = _make_store_with_cases(tmp_path, 3)
    runner = AuditRunner(
        store,
        audit_func=_noop_audit_func,
        output_root=tmp_path / "outputs",
        max_workers=2,
    )

    # Only 1 running — below capacity of 2
    _set_runs_running(store, [0])
    assert runner._active_runs_count() == 1

    all_runs = store.list_all_runs()
    new_run = runner.start(all_runs[2].case_id)
    assert new_run.run_id.startswith("run-")


def test_start_succeeds_when_no_running_runs(tmp_path: Path) -> None:
    store = _make_store_with_cases(tmp_path, 2)
    runner = AuditRunner(
        store,
        audit_func=_noop_audit_func,
        output_root=tmp_path / "outputs",
        max_workers=2,
    )

    assert runner._active_runs_count() == 0

    all_runs = store.list_all_runs()
    new_run = runner.start(all_runs[0].case_id)
    assert new_run.run_id.startswith("run-")


def test_completed_runs_do_not_block_new_starts(tmp_path: Path) -> None:
    """Completed/failed runs should not count toward the limit."""
    store = _make_store_with_cases(tmp_path, 3)
    runner = AuditRunner(
        store,
        audit_func=_noop_audit_func,
        output_root=tmp_path / "outputs",
        max_workers=2,
    )

    all_runs = store.list_all_runs()
    # Set 2 runs to terminal states — neither should block
    all_runs[0].status = "completed"
    store.save_run(all_runs[0])
    all_runs[1].status = "failed"
    store.save_run(all_runs[1])

    assert runner._active_runs_count() == 0

    new_run = runner.start(all_runs[2].case_id)
    assert new_run.run_id.startswith("run-")


# ------------------------------------------------------------------
# End-to-end: env var controls 429 threshold
# ------------------------------------------------------------------


def test_env_var_controls_limit_end_to_end(tmp_path: Path) -> None:
    store = _make_store_with_cases(tmp_path, 5)

    with patch.dict(os.environ, {"VERITAS_MAX_CONCURRENT_AUDITS": "3"}):
        runner = AuditRunner(
            store,
            audit_func=_noop_audit_func,
            output_root=tmp_path / "outputs",
        )

    assert runner._max_concurrent == 3

    _set_runs_running(store, [0, 1, 2])
    assert runner._active_runs_count() == 3

    all_runs = store.list_all_runs()
    with pytest.raises(HTTPException) as exc_info:
        runner.start(all_runs[3].case_id)
    assert exc_info.value.status_code == 429
    assert "max=3" in exc_info.value.detail

    # Drop one running → 2 active, below limit of 3
    fresh_runs = store.list_all_runs()
    # Find the run we manually set to "running" (run for case-0)
    target_run = next(r for r in fresh_runs if r.case_id == "case-0")
    target_run.status = "completed"
    store.save_run(target_run)

    # Count only the runs we control (case-1 and case-2 should still be "running")
    controlled_runnings = sum(
        1 for r in store.list_all_runs()
        if r.case_id in ("case-1", "case-2") and r.status == "running"
    )
    assert controlled_runnings == 2

    # start() should now succeed
    new_run = runner.start("case-4")
    assert new_run.run_id.startswith("run-")
