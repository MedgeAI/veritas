"""Manual task rendering and display-priority helpers."""

from __future__ import annotations

from typing import Any

from engine.static_audit.html_report._html_utils import h
from engine.static_audit.html_report._shared import (
    _confidence_badge,
    clean_report_text,
    has_row_vector_signal_text,
    has_stronger_signal_text,
    risk_label,
    risk_score,
)

# ---------------------------------------------------------------------------
# Task classification helpers
# ---------------------------------------------------------------------------


def manual_task_text(task: dict[str, Any]) -> str:
    question = str(task.get("question") or "")
    refs = " ".join(str(ref) for ref in (task.get("evidence_refs") or []))
    return f"{question} {refs}".lower()


def manual_task_focus_score(task: dict[str, Any]) -> int:
    combined = manual_task_text(task)
    has_row_vector = has_row_vector_signal_text(combined)
    has_stronger = has_stronger_signal_text(combined)
    if has_row_vector and has_stronger:
        return 1
    if has_row_vector:
        return 2
    return 0


def is_context_only_manual_task(task: dict[str, Any]) -> bool:
    combined = manual_task_text(task)
    return has_row_vector_signal_text(combined) and not has_stronger_signal_text(
        combined
    )


# ---------------------------------------------------------------------------
# Display priority
# ---------------------------------------------------------------------------


def display_priority_for_manual_task(task: dict[str, Any]) -> str:
    if is_context_only_manual_task(task):
        return "context"
    return str(task.get("priority") or "medium")


def display_priority_for_pair_task(task: dict[str, Any]) -> str:
    if str(
        task.get("category") or ""
    ) == "duplicate_row_vector" or is_context_only_manual_task(task):
        return "context"
    return str(task.get("priority") or "medium")


def display_risk_level_for_judge_risk(risk: dict[str, Any]) -> str:
    refs = " ".join(str(ref) for ref in (risk.get("evidence_refs") or []))
    combined = f"{risk.get('reason') or ''} {refs}"
    if has_row_vector_signal_text(combined) and not has_stronger_signal_text(combined):
        return "context"
    return str(risk.get("risk_level") or "medium")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def manual_tasks_table(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "<p class='muted'>未生成独立人工复核任务。</p>"
    rows = []
    visible_tasks = sorted(
        [task for task in tasks if isinstance(task, dict)],
        key=lambda task: (
            -risk_score(display_priority_for_manual_task(task)),
            manual_task_focus_score(task),
        ),
    )
    for task in visible_tasks[:10]:
        refs = task.get("evidence_refs") or []
        priority = display_priority_for_manual_task(task)
        rows.append(
            "<tr>"
            f"<td><code>{h(task.get('task_id', '-'))}</code></td>"
            f"<td><span class='badge {h(priority)}'>{h(risk_label(priority))}</span></td>"
            f"<td>{_confidence_badge('data')}{h(clean_report_text(task.get('question', '-')))}</td>"
            f"<td><code>{h(', '.join(str(ref) for ref in refs[:5]) or '-')}</code></td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>任务</th><th>优先级</th><th>问题</th><th>证据 refs</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )
