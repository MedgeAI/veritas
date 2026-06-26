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
        "status": "completed" | "running" | "failed" | "skipped",
        "duration_seconds": 46 | None,
        "started_at": "2026-06-26T00:01:00Z" | None,
    }

The list is ordered by discovery order (the order in which step_start events
first appeared).  Steps without a step_start are still included if a
step_result is present, in which case ``started_at`` is ``None``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .step_labels import STEP_LABELS, get_step_label


# Status tokens emitted by the pipeline that map to terminal statuses.
_RESULT_STATUS_COMPLETED = frozenset({"ran", "reused"})
_RESULT_STATUS_FAILED = frozenset({"failed"})
_RESULT_STATUS_SKIPPED = frozenset({"skipped"})


def _parse_timestamp(value: Any) -> datetime | None:
    """Best-effort parse of an ISO-8601 timestamp string.

    Returns ``None`` if *value* is falsy or cannot be parsed.  Naive strings
    are assumed to be UTC.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        normalised = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalised)
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

    # key -> {start_ts, end_ts, result_status, title}
    step_data: dict[str, dict[str, Any]] = {}

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
            }

        bucket = step_data[key]
        ts = _parse_timestamp(event.get("timestamp"))

        if event_type == "step_start":
            if bucket["start_ts"] is None:
                bucket["start_ts"] = ts
            if isinstance(event.get("title"), str):
                bucket["title"] = event["title"]

        elif event_type == "step_result":
            bucket["end_ts"] = ts
            raw_status = event.get("status")
            if isinstance(raw_status, str):
                bucket["result_status"] = raw_status.lower()
            if isinstance(event.get("title"), str):
                bucket["title"] = event["title"]

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
        elif bucket["start_ts"] is not None and bucket["end_ts"] is None:
            status = "running"
        else:
            status = "completed" if result_status else "pending"

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
    progress_pct = int(completed / total * 100) if total else 0
    return {
        "total": total,
        "completed": completed,
        "running": running,
        "failed": failed,
        "skipped": skipped,
        "progress_pct": progress_pct,
    }
