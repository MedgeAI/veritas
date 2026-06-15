from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Any, Callable

from engine.static_audit.orchestrator import run_static_audit

from .case_store import CaseStore
from .models import STALE_RUN_THRESHOLD_SECONDS, AuditRunRecord, utc_now

AuditFunction = Callable[..., dict[str, Any]]


class AuditRunner:
    def __init__(
        self,
        store: CaseStore,
        audit_func: AuditFunction = run_static_audit,
        output_root: str | Path = "outputs",
    ) -> None:
        self.store = store
        self.audit_func = audit_func
        self.output_root = str(output_root)

    def start(self, case_id: str, params: dict[str, Any] | None = None) -> AuditRunRecord:
        params = params or {}
        run = self.store.create_run(case_id, agent_mode=str(params.get("agent_mode", "review")))
        thread = Thread(target=self.run_sync, args=(case_id, run.run_id, params), daemon=True)
        thread.start()
        return run

    def run_sync(self, case_id: str, run_id: str, params: dict[str, Any] | None = None) -> AuditRunRecord:
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
                opencode_bin=str(params.get("opencode_bin", "opencode")),
                agent_timeout_seconds=int(params.get("agent_timeout_seconds", 300)),
                agent_max_retries=int(params.get("agent_max_retries", 1)),
                progress=progress,
            )
            run.summary = summary
            run.workdir = summary.get("workdir")
            run.final_html_report_url = f"/api/cases/{case_id}/report/html"
            run.completed_at = utc_now()
            run.status = "completed" if int(summary.get("exit_code", 1)) == 0 else "failed"
            if run.status == "failed":
                run.error = f"failed_steps={summary.get('failed_steps', [])}"
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
        self.store.save_run(run)
        self._update_case_after_run(run)
        return run

    def _update_case_after_run(self, run: AuditRunRecord) -> None:
        case_record = self.store.get_case(run.case_id)
        if run.status == "completed":
            failed_steps = []
            if run.summary:
                failed_steps = list(run.summary.get("failed_steps") or [])
            case_record.status = "Review Needed" if failed_steps else "Report Ready"
            case_record.review_needed_count = len(failed_steps)
        elif run.status == "failed":
            case_record.status = "Review Needed"
            case_record.review_needed_count = max(case_record.review_needed_count, 1)
        elif run.status == "interrupted":
            case_record.status = "Review Needed"
            case_record.review_needed_count = max(case_record.review_needed_count, 1)
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
                last_event_dt = datetime.fromisoformat(run.last_event_at.replace("Z", "+00:00"))
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
                "failed_steps": ["backend_restart"] if reason == "backend_restart" else ["stale_detection"],
                "interrupted": True,
                "detail": "Web backend exited before this run wrote a terminal state." if reason == "backend_restart" else detail,
            }
            default_workdir = Path(self.output_root) / run.case_id / "research-integrity-audit"
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
