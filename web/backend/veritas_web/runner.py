from __future__ import annotations

import os
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from engine.static_audit.orchestrator import run_static_audit

from .case_store import CaseStore
from .models import STALE_RUN_THRESHOLD_SECONDS, AuditRunRecord, utc_now
from .risk import load_static_audit_bundle, risk_rank, summarize_findings

AuditFunction = Callable[..., dict[str, Any]]


def _resolve_max_concurrent() -> int:
    """Read VERITAS_MAX_CONCURRENT_AUDITS env var, default 5."""
    raw = os.environ.get("VERITAS_MAX_CONCURRENT_AUDITS", "5")
    try:
        value = int(raw)
    except (ValueError, TypeError):
        return 5
    return max(1, value)


class AuditRunner:
    def __init__(
        self,
        store: CaseStore,
        audit_func: AuditFunction = run_static_audit,
        output_root: str | Path = "outputs",
        max_workers: int | None = None,
    ) -> None:
        self.store = store
        self.audit_func = audit_func
        self.output_root = str(output_root)
        resolved_workers = (
            max_workers if max_workers is not None else _resolve_max_concurrent()
        )
        self._max_concurrent = resolved_workers
        self._executor = ThreadPoolExecutor(
            max_workers=resolved_workers, thread_name_prefix="audit"
        )

    def _active_runs_count(self) -> int:
        """Count runs with status='running' across all cases."""
        return sum(
            1 for run in self.store.list_all_runs() if run.status == "running"
        )

    def start(
        self, case_id: str, params: dict[str, Any] | None = None
    ) -> AuditRunRecord:
        if self._active_runs_count() >= self._max_concurrent:
            raise HTTPException(
                status_code=429,
                detail=(f"Too many concurrent audits (max={self._max_concurrent})"),
            )
        params = params or {}
        run = self.store.create_run(
            case_id, agent_mode=str(params.get("agent_mode", "review"))
        )
        if os.environ.get("VERITAS_USE_CELERY", "").lower() in ("1", "true", "yes"):
            return self._dispatch_celery_task(run, case_id, params)
        self._executor.submit(self.run_sync, case_id, run.run_id, params)
        return run

    def run_sync(
        self, case_id: str, run_id: str, params: dict[str, Any] | None = None
    ) -> AuditRunRecord:
        params = params or {}
        run = self.store.get_run(case_id, run_id)
        run.status = "running"
        run.started_at = utc_now()
        run.last_event_at = run.started_at  # initial heartbeat
        self.store.save_run(run)
        case_record = self.store.get_case(case_id)
        case_record.status = "Running"
        self.store.save_case(case_record)

        def progress(event: dict[str, Any]) -> None:
            run.last_event_at = utc_now()
            self.store.save_run(run)
            self.store.append_event(case_id, run_id, event)

        try:
            summary = self.audit_func(
                self.store.inputs_dir(case_id),
                case_id=case_id,
                output_root=str(params.get("output_root", self.output_root)),
                fresh=bool(params.get("fresh", True)),
                force=bool(params.get("force", True)),
                no_env_file=bool(params.get("no_env_file", False)),
                agent_mode=str(params.get("agent_mode", "review")),
                agent_model=str(params.get("agent_model", "dashscope/qwen3.7-plus")),
                opencode_bin=str(
                    params.get("opencode_bin")
                    or os.environ.get("OPENCODE_BIN", "opencode")
                ),
                agent_timeout_seconds=int(params.get("agent_timeout_seconds", 300)),
                agent_max_retries=int(params.get("agent_max_retries", 1)),
                progress=progress,
            )
            run.summary = summary
            run.workdir = summary.get("workdir")
            run.final_html_report_url = f"/api/cases/{case_id}/report/html"
            run.completed_at = utc_now()
            run.status = (
                "completed" if int(summary.get("exit_code", 1)) == 0 else "failed"
            )
            # Safety net: if reports were generated despite exit_code!=0,
            # treat as completed (partial failure) rather than failed.
            if run.status == "failed":
                report_path = summary.get("final_report", "")
                html_path = summary.get("final_html_report", "")
                if report_path and html_path:
                    from pathlib import Path

                    if Path(report_path).exists() and Path(html_path).exists():
                        run.status = "completed"
            if run.status == "failed":
                run.error = f"failed_steps={summary.get('failed_steps', [])}"
            elif run.status == "completed" and summary.get("failed_steps"):
                run.error = f"partial: {summary['failed_steps']}"
        except Exception as exc:  # pragma: no cover - exercised by integration failures
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
            run.completed_at = utc_now()
            self.store.append_event(
                case_id,
                run_id,
                {
                    "timestamp": utc_now(),
                    "event": "runner_exception",
                    "error": run.error,
                    "traceback": traceback.format_exc(limit=8),
                },
            )
        # ---------------------------------------------------------------
        # Guard: re-read run status from DB before writing terminal state.
        # If the run was cancelled (e.g. by cancel_run()) while this
        # thread was executing the pipeline, do NOT overwrite the
        # cancelled status.
        # ---------------------------------------------------------------
        current_run = self.store.get_run(case_id, run_id)
        if current_run.status == "cancelled":
            run.status = "cancelled"
            run.completed_at = current_run.completed_at
            self.store.save_run(run)
            self._update_case_after_run(run)
            return run

        self.store.save_run(run)
        self._update_case_after_run(run)
        return run
    # ------------------------------------------------------------------

    def _dispatch_celery_task(
        self,
        run: AuditRunRecord,
        case_id: str,
        params: dict[str, Any],
    ) -> AuditRunRecord:
        """Dispatch the audit as a Celery task and store the celery_task_id.

        Called by :meth:`start` when ``VERITAS_USE_CELERY`` is truthy.  The
        Celery worker performs the four-layer idempotency guard internally
        (see ``engine.tasks.audit_task``).
        """
        from engine.tasks.celery_app import celery_app
        import engine.tasks.audit_task  # noqa: F401 — triggers task registration

        paper_dir = self.store.inputs_dir(case_id)
        options: dict[str, Any] = {
            "output_root": params.get("output_root", self.output_root),
            "fresh": bool(params.get("fresh", True)),
            "force": bool(params.get("force", True)),
            "no_env_file": bool(params.get("no_env_file", False)),
            "agent_mode": str(params.get("agent_mode", "review")),
            "agent_model": str(params.get("agent_model", "dashscope/qwen3.7-plus")),
            "opencode_bin": str(
                params.get("opencode_bin") or os.environ.get("OPENCODE_BIN", "opencode")
            ),
            "agent_timeout_seconds": int(params.get("agent_timeout_seconds", 300)),
            "agent_max_retries": int(params.get("agent_max_retries", 1)),
        }

        try:
            async_result = celery_app.send_task(
                "run_audit",
                args=[run.run_id, case_id, str(paper_dir), options],
            )
        except Exception as exc:
            run.status = "failed"
            run.error = f"Celery dispatch failed: {exc}"
            self.store.save_run(run)
            return run

        self.store.set_run_celery_task_id(run.run_id, async_result.id)
        return run

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    def cancel_run(self, run_id: str, case_id: str) -> AuditRunRecord:
        """Cancel a running or queued audit.

        * If Celery dispatched the task, revoke it.
        * If the run was ``running`` in the thread pool, call
          :func:`cleanup_audit_processes` to release subprocesses.
        """
        from .models import utc_now

        run = self.store.get_run(case_id, run_id)
        if run.status not in ("queued", "running"):
            raise HTTPException(
                status_code=409,
                detail=f"run {run_id} is not active (status={run.status})",
            )

        was_running = run.status == "running"

        # Revoke Celery task if bound.
        celery_task_id = self.store.get_run_celery_task_id(run_id)
        if celery_task_id:
            try:
                from engine.tasks.celery_app import celery_app

                celery_app.control.revoke(celery_task_id, terminate=True)
            except Exception:
                pass

        run.status = "cancelled"
        run.completed_at = utc_now()
        self.store.save_run(run)

        if was_running:
            try:
                from engine.tasks.process_cleanup import cleanup_audit_processes

                cleanup_audit_processes(run_id, case_id)
            except Exception:
                pass

        self._update_case_after_run(run)
        return run

    def _update_case_after_run(self, run: AuditRunRecord) -> None:
        case_record = self.store.get_case(run.case_id)
        if run.status == "completed":
            failed_steps = []
            if run.summary:
                failed_steps = list(run.summary.get("failed_steps") or [])
            bundle = load_static_audit_bundle(run.workdir)
            finding_review_count = 0
            if bundle is not None:
                findings = bundle.get("findings", [])
                summary = summarize_findings(
                    findings if isinstance(findings, list) else []
                )
                case_record.technical_risk = summary["overall_risk"]
                finding_review_count = int(summary["high_quality_count"])
            else:
                case_record.technical_risk = "unknown"
            case_record.status = (
                "Review Needed"
                if failed_steps or finding_review_count > 0
                else "Report Ready"
            )
            case_record.review_needed_count = max(
                finding_review_count, len(failed_steps)
            )
        elif run.status == "failed":
            case_record.status = "Review Needed"
            case_record.review_needed_count = max(case_record.review_needed_count, 1)
            if risk_rank(case_record.technical_risk) < risk_rank("high"):
                case_record.technical_risk = "high"
        elif run.status == "interrupted":
            case_record.status = "Review Needed"
            case_record.review_needed_count = max(case_record.review_needed_count, 1)
            if risk_rank(case_record.technical_risk) < risk_rank("high"):
                case_record.technical_risk = "high"
        elif run.status == "cancelled":
            case_record.status = "Cancelled"
            case_record.review_needed_count = 0
        case_record.latest_run_id = run.run_id
        self.store.save_case(case_record)

    def recover_interrupted_runs(self) -> int:
        recovered_count = 0
        now_iso = utc_now()
        now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        for run in self.store.list_all_runs():
            if run.status not in {"queued", "running"}:
                continue

            # Determine recovery strategy based on heartbeat
            if run.last_event_at is None:
                # Legacy run without heartbeat — mark as failed (backward compat)
                status = "failed"
                error = "interrupted_by_backend_restart"
                reason = "backend_restart"
                detail = "Recovered a queued/running Web run after backend startup; thread runner cannot survive backend exit."
            else:
                # Check heartbeat freshness
                last_event_dt = datetime.fromisoformat(
                    run.last_event_at.replace("Z", "+00:00")
                )
                elapsed_seconds = (now_dt - last_event_dt).total_seconds()
                if elapsed_seconds < STALE_RUN_THRESHOLD_SECONDS:
                    # Still fresh — might be running in another process, skip
                    continue
                # Stale — mark as interrupted
                status = "interrupted"
                error = f"no_heartbeat_for_{int(elapsed_seconds)}_seconds"
                reason = "stale_detection"
                detail = f"No heartbeat for {int(elapsed_seconds)} seconds (threshold: {STALE_RUN_THRESHOLD_SECONDS}s)"

            recovered_count += 1
            run.status = status
            run.completed_at = now_iso
            run.error = error
            run.summary = {
                "exit_code": 1,
                "failed_steps": ["backend_restart"]
                if reason == "backend_restart"
                else ["stale_detection"],
                "interrupted": True,
                "detail": "Web backend exited before this run wrote a terminal state."
                if reason == "backend_restart"
                else detail,
            }
            default_workdir = (
                Path(self.output_root) / run.case_id / "research-integrity-audit"
            )
            if not run.workdir and default_workdir.exists():
                run.workdir = str(default_workdir)
            self.store.save_run(run)
            self.store.append_event(
                run.case_id,
                run.run_id,
                {
                    "timestamp": now_iso,
                    "event": "runner_interrupted",
                    "status": status,
                    "reason": reason,
                    "detail": detail,
                },
            )
            self._update_case_after_run(run)
        return recovered_count
