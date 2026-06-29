"""Stale run watchdog — detect and recover audit runs stuck in 'running'.

Scans the database for runs whose ``last_event_at`` is older than
``STALE_THRESHOLD_SECONDS`` (default 600 s).  For each stale run:

* If an HTML report exists on disk → mark as ``completed_with_warnings``.
* Otherwise → mark as ``failed_timeout``.

A ``timeout_recovery`` event is appended to the run's event log so the
recovery is auditable.

This module is self-contained — it defines its own lightweight ORM mirror
over the ``runs`` / ``run_events`` tables to avoid importing the web
layer's SQLAlchemy models (Engine must not depend on Web).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from engine.tasks._task_orm import (
    _RunEventRow,
    _RunRow,
    _get_session_factory,
    _utc_now,
)

logger = logging.getLogger(__name__)

STALE_THRESHOLD_SECONDS = 600

# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------


def _is_stale(last_event_at: str | None, threshold: int = STALE_THRESHOLD_SECONDS) -> bool:
    """Return True if *last_event_at* is older than *threshold* seconds."""
    if not last_event_at:
        return True
    try:
        ts = datetime.fromisoformat(last_event_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age > threshold


def _html_report_exists(run: _RunRow) -> bool:
    """Check whether the HTML report file exists for *run*."""
    if not run.workdir:
        return False
    html_path = Path(run.workdir) / "reports" / "final_audit_report.html"
    return html_path.is_file()


def scan_and_recover(threshold: int = STALE_THRESHOLD_SECONDS) -> list[dict]:
    """Find stale runs and apply timeout recovery.

    Creates its own DB session from ``VERITAS_DATABASE_URL``.

    Returns a list of dicts describing each recovered run (``run_id``,
    ``case_id``, ``new_status``, ``had_html``).
    """
    factory = _get_session_factory()
    session = factory()
    try:
        stale_runs = (
            session.query(_RunRow)
            .filter(_RunRow.status == "running")
            .all()
        )

        recovered: list[dict] = []
        for run in stale_runs:
            if not _is_stale(run.last_event_at, threshold):
                continue

            had_html = _html_report_exists(run)
            new_status = "completed_with_warnings" if had_html else "failed_timeout"
            now = _utc_now()

            run.status = new_status
            run.completed_at = now
            if not had_html:
                run.error = "stale run: no heartbeat for >%ds" % threshold

            recovery_event = _RunEventRow(
                run_id=run.run_id,
                event_type="timeout_recovery",
                payload={
                    "previous_status": "running",
                    "new_status": new_status,
                    "html_report_present": had_html,
                    "threshold_seconds": threshold,
                    "last_event_at": run.last_event_at,
                },
                created_at=now,
            )
            session.add(recovery_event)

            recovered.append({
                "run_id": run.run_id,
                "case_id": run.case_id,
                "new_status": new_status,
                "had_html": had_html,
            })

            logger.warning(
                "Stale run %s (case %s) recovered as %s (html=%s)",
                run.run_id, run.case_id, new_status, had_html,
            )

        if recovered:
            session.commit()

        return recovered
    except Exception:  # Deliberately broad: DB session rollback must catch any SQLAlchemy or connection error
        session.rollback()
        raise
    finally:
        session.close()
