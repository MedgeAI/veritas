"""Review-queue artifact readers — pure domain logic.

Reads review-item suggestions from audit artifacts (visual findings,
pair forensics, agent review).  No database access.

Moved from web/backend/veritas_web/review_queue.py to enforce the
UI -> Engine -> Config layering rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.static_audit.paths import resolve_artifact_path

# Risk order for sorting review items (highest risk first).
RISK_ORDER_REVIEW: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


def read_json_artifact(workdir: Path, artifact_name: str) -> dict[str, Any] | None:
    """Read a JSON artifact, trying the mapped path then the legacy flat path."""
    mapped = resolve_artifact_path(workdir, artifact_name)
    if mapped.exists():
        return json.loads(mapped.read_text(encoding="utf-8"))
    legacy = workdir / artifact_name
    if legacy.exists():
        return json.loads(legacy.read_text(encoding="utf-8"))
    return None


def from_visual_findings(workdir: Path) -> list[dict[str, Any]]:
    """Extract review items from ``visual/findings.json``."""
    data = read_json_artifact(workdir, "visual_findings.json")
    if not data:
        data = read_json_artifact(workdir, "visual/findings.json")
    if not data:
        return []

    items: list[dict[str, Any]] = []
    findings = data.get("findings") or []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        finding_id = finding.get("finding_id") or finding.get("id") or "unknown"
        risk = finding.get("risk_level", "medium")
        category = finding.get("issue_category", "consistency")
        source_ref = f"visual_findings:{finding_id}"
        items.append(
            {
                "source_ref": source_ref,
                "title": finding.get("title", f"Visual finding {finding_id}"),
                "risk_level": risk,
                "issue_category": category,
                "source": "visual_findings",
                "evidence_refs": finding.get("evidence_refs", []),
                "recommended_action": finding.get("recommended_action", ""),
                "benign_explanation": finding.get("benign_explanation", ""),
                "finding_id": finding_id,
            }
        )
    return items


def from_pair_forensics(workdir: Path) -> list[dict[str, Any]]:
    """Extract review items from ``source_data/pair_forensics.json``."""
    data = read_json_artifact(workdir, "source_data/pair_forensics.json")
    if not data:
        data = read_json_artifact(workdir, "source_data_pair_forensics.json")
    if not data:
        return []

    items: list[dict[str, Any]] = []
    review_tasks = data.get("pair_forensics_review_tasks") or []
    for task in review_tasks:
        if not isinstance(task, dict):
            continue
        task_id = task.get("task_id") or task.get("id") or "unknown"
        items.append(
            {
                "source_ref": f"pair_forensics:{task_id}",
                "title": task.get("title", f"Pair forensics review: {task_id}"),
                "risk_level": task.get("risk_level", "medium"),
                "issue_category": task.get("issue_category", "consistency"),
                "source": "pair_forensics",
                "evidence_refs": task.get("evidence_refs", []),
                "recommended_action": task.get("recommended_action", ""),
                "benign_explanation": task.get("benign_explanation", ""),
            }
        )
    return items


def from_agent_review(workdir: Path) -> list[dict[str, Any]]:
    """Extract review items from ``agents/review.json``."""
    data = read_json_artifact(workdir, "agents/review.json")
    if not data:
        data = read_json_artifact(workdir, "agent_review.json")
    if not data:
        return []

    items: list[dict[str, Any]] = []
    review_tasks = data.get("manual_review_tasks") or []
    for task in review_tasks:
        if not isinstance(task, dict):
            continue
        task_id = task.get("task_id") or task.get("id") or "unknown"
        items.append(
            {
                "source_ref": f"agent_review:{task_id}",
                "title": task.get("title", f"Agent review task: {task_id}"),
                "risk_level": task.get("risk_level", "medium"),
                "issue_category": task.get("issue_category", "matching"),
                "source": "agent_review",
                "evidence_refs": task.get("evidence_refs", []),
                "recommended_action": task.get("recommended_action", ""),
                "benign_explanation": task.get("benign_explanation", ""),
            }
        )
    return items
