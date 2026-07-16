"""Build the steps list from pipeline events.

This module provides :func:`build_steps_list`, which consumes the raw
``run_events`` list (as returned by ``CaseStore.list_events``) and the
step-label mapping from :mod:`engine.static_audit.step_labels`, and produces
a list of step dicts suitable for the ``GET /steps`` API response.

Each step in the returned list has the shape::

    {
        "key": "visual_tru_for",
        "title": "TruFor 伪造检测",
        "phase": "视觉取证",
        "phase_order": 5,
        "status": "completed" | "running" | "failed" | "skipped" | "warning",
        "duration_seconds": 46 | None,
        "started_at": "2026-06-26T00:01:00Z" | None,
    }

The list is ordered by discovery order (the order in which step_start events
first appeared).  Steps without a step_start are still included if a
step_result is present, in which case ``started_at`` is ``None``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from .step_labels import STEP_LABELS, get_step_label


# Status tokens emitted by the pipeline that map to terminal statuses.
_RESULT_STATUS_COMPLETED = frozenset({"ran", "reused"})
_RESULT_STATUS_FAILED = frozenset({"failed"})
_RESULT_STATUS_SKIPPED = frozenset({"skipped"})
_RESULT_STATUS_WARNING = frozenset({"warning"})
_TERMINAL_RUN_STATUSES = frozenset(
    {
        "completed",
        "completed_with_warnings",
        "failed",
        "failed_timeout",
        "failed_dependency",
        "failed_runtime",
        "interrupted",
        "cancelled",
        "partial_available",
    }
)


def _parse_timestamp(value: Any) -> datetime | None:
    """Best-effort parse of an ISO-8601 timestamp string.

    Returns ``None`` if *value* is falsy or cannot be parsed.  Naive strings
    are assumed to be UTC.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        normalised = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalised)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    except ValueError:
        return None


def _duration_seconds(start: datetime | None, end: datetime | None) -> float | None:
    """Return the difference in seconds between *end* and *start*, or ``None``."""
    if start is None or end is None:
        return None
    delta = (end - start).total_seconds()
    return delta if delta >= 0 else None


def build_steps_list(
    events: Iterable[dict[str, Any]],
    step_labels: dict[str, dict[str, Any]] | None = None,
    *,
    run_status: str | None = None,
) -> list[dict[str, Any]]:
    """Build an ordered step list from a sequence of pipeline events.

    Parameters
    ----------
    events:
        The raw events list.  Only events whose ``event`` field is
        ``"step_start"`` or ``"step_result"`` contribute to the output.
        Each event may carry ``"key"``, ``"status"``, ``"title"`` and
        ``"timestamp"`` fields.
    step_labels:
        Optional override for the label mapping.  When ``None`` (the
        default), :func:`engine.static_audit.step_labels.get_step_label`
        is used.
    run_status:
        Optional persisted run status.  When the run has already reached a
        terminal status, orphan ``step_start`` events are shown as warnings
        instead of forever-running steps.

    Returns
    -------
    list[dict]
        Ordered list of step dicts.  Each dict has the keys ``key``,
        ``title``, ``phase``, ``phase_order``, ``status``,
        ``duration_seconds`` and ``started_at``.
    """
    label_lookup = step_labels if step_labels is not None else STEP_LABELS

    # First pass: collect per-step start/result timestamps and statuses,
    # preserving first-seen order.
    steps_order: list[str] = []
    seen_keys: set[str] = set()

    # key -> {start_ts, end_ts, result_status, title, detail}
    step_data: dict[str, dict[str, Any]] = {}
    run_is_terminal = (run_status or "") in _TERMINAL_RUN_STATUSES

    for event in events:
        event_type = event.get("event")
        if event_type not in ("step_start", "step_result"):
            continue
        key = event.get("key")
        if not isinstance(key, str) or not key:
            continue

        if key not in seen_keys:
            seen_keys.add(key)
            steps_order.append(key)
            step_data[key] = {
                "start_ts": None,
                "end_ts": None,
                "result_status": None,
                "title": None,
                "detail": None,
            }

        bucket = step_data[key]
        ts = _parse_timestamp(event.get("timestamp"))

        if event_type == "step_start":
            if bucket["start_ts"] is None:
                bucket["start_ts"] = ts
            if isinstance(event.get("title"), str):
                bucket["title"] = event["title"]
            if isinstance(event.get("detail"), str):
                bucket["detail"] = event["detail"]

        elif event_type == "step_result":
            bucket["end_ts"] = ts
            raw_status = event.get("status")
            if isinstance(raw_status, str):
                bucket["result_status"] = raw_status.lower()
            if isinstance(event.get("title"), str):
                bucket["title"] = event["title"]
            if isinstance(event.get("detail"), str):
                bucket["detail"] = event["detail"]

    # Second pass: resolve status and build output rows.
    output: list[dict[str, Any]] = []
    for key in steps_order:
        bucket = step_data[key]

        # Resolve display label.
        if key in label_lookup:
            label_info = label_lookup[key]
        else:
            label_info = get_step_label(key)

        title = bucket.get("title") or label_info.get("title") or key
        phase = label_info.get("phase", "Unknown")
        phase_order = label_info.get("phase_order", 99)

        # Determine status.
        result_status = bucket.get("result_status")
        if result_status in _RESULT_STATUS_COMPLETED:
            status = "completed"
        elif result_status in _RESULT_STATUS_FAILED:
            status = "failed"
        elif result_status in _RESULT_STATUS_SKIPPED:
            status = "skipped"
        elif result_status in _RESULT_STATUS_WARNING:
            status = "warning"
        elif bucket["start_ts"] is not None and bucket["end_ts"] is None:
            status = "warning" if run_is_terminal else "running"
        else:
            status = "completed" if result_status else "pending"
        detail = bucket.get("detail")
        if (
            status == "warning"
            and result_status is None
            and bucket["start_ts"] is not None
            and bucket["end_ts"] is None
            and run_is_terminal
        ):
            detail = (
                "Run reached terminal status before this step emitted step_result."
            )

        duration = _duration_seconds(bucket["start_ts"], bucket["end_ts"])
        started_at: str | None
        if bucket["start_ts"] is not None:
            started_at = bucket["start_ts"].isoformat().replace("+00:00", "Z")
        else:
            started_at = None

        output.append(
            {
                "key": key,
                "title": title,
                "phase": phase,
                "phase_order": phase_order,
                "status": status,
                "duration_seconds": duration,
                "started_at": started_at,
                "detail": detail or "",
            }
        )

    return output


def summarise_steps(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate counters for a step list.

    Returns a dict with ``total``, ``completed``, ``running``, ``failed``,
    ``skipped`` and ``progress_pct`` keys.
    """
    total = len(steps)
    completed = sum(1 for s in steps if s.get("status") == "completed")
    running = sum(1 for s in steps if s.get("status") == "running")
    failed = sum(1 for s in steps if s.get("status") == "failed")
    skipped = sum(1 for s in steps if s.get("status") == "skipped")
    warnings = sum(1 for s in steps if s.get("status") == "warning")
    progress_pct = int(completed / total * 100) if total else 0
    return {
        "total": total,
        "completed": completed,
        "running": running,
        "failed": failed,
        "skipped": skipped,
        "warnings": warnings,
        "progress_pct": progress_pct,
    }


def _safe_seconds_between(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    seconds = int((end - start).total_seconds())
    return seconds if seconds >= 0 else None


def _display_step(step: dict[str, Any] | None) -> dict[str, Any] | None:
    if step is None:
        return None
    return {
        "key": step.get("key"),
        "title": step.get("title"),
        "phase": step.get("phase"),
        "status": step.get("status"),
        "started_at": step.get("started_at"),
    }


def summarise_run_timing(
    steps: list[dict[str, Any]],
    *,
    run_status: str | None,
    started_at: str | None,
    completed_at: str | None,
    last_event_at: str | None,
    stale_after_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return factual run timing/status metadata without estimating ETA.

    Agent-driven audit runs can branch, retry, wait on model/tool output, or
    skip optional lanes, so this deliberately reports observable facts instead
    of a synthetic "remaining time".
    """
    now_dt = now or datetime.now(UTC)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=UTC)

    started_dt = _parse_timestamp(started_at)
    completed_dt = _parse_timestamp(completed_at)
    last_event_dt = _parse_timestamp(last_event_at)

    terminal_statuses = _TERMINAL_RUN_STATUSES
    active_statuses = {"queued", "running", "enhancing"}
    status = run_status or "unknown"

    elapsed_until = completed_dt if status in terminal_statuses else now_dt
    elapsed_seconds = _safe_seconds_between(started_dt, elapsed_until)
    seconds_since_last_event = _safe_seconds_between(last_event_dt, now_dt)
    is_stale = (
        status in active_statuses
        and seconds_since_last_event is not None
        and seconds_since_last_event > stale_after_seconds
    )

    current_step = next(
        (step for step in steps if step.get("status") == "running"),
        None,
    )
    latest_step = steps[-1] if steps else None

    if status in {"completed", "completed_with_warnings", "partial_available"}:
        timing_status = "complete"
    elif status == "cancelled":
        timing_status = "cancelled"
    elif status.startswith("failed") or status == "interrupted":
        timing_status = "failed"
    elif is_stale:
        timing_status = "stale"
    elif status == "queued":
        timing_status = "queued"
    elif current_step is not None:
        timing_status = "active"
    elif status in active_statuses:
        timing_status = "waiting"
    else:
        timing_status = "unknown"

    return {
        "run_status": status,
        "timing_status": timing_status,
        "current_step": _display_step(current_step),
        "latest_step": _display_step(latest_step),
        "elapsed_seconds": elapsed_seconds,
        "last_event_at": last_event_at,
        "seconds_since_last_event": seconds_since_last_event,
        "stale_after_seconds": stale_after_seconds,
        "is_stale": is_stale,
        "eta": None,
    }
