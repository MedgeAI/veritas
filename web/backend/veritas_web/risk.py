from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.static_audit.paths import resolve_artifact_path


RISK_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
RISK_LEVELS = ("critical", "high", "medium", "low", "info")
ISSUE_CATEGORY_ORDER = {"completeness": 1, "matching": 2, "consistency": 3}


def risk_rank(value: str | None) -> int:
    return RISK_ORDER.get(str(value or "info").lower(), 0)


def issue_category_rank(value: str | None) -> int:
    return ISSUE_CATEGORY_ORDER.get(str(value or "").lower(), 0)


def normalize_risk_level(value: Any) -> str:
    level = str(value or "info").lower()
    return level if level in RISK_ORDER else "info"


def static_audit_bundle_path(workdir: str | Path | None) -> Path | None:
    if not workdir:
        return None
    root = Path(workdir)
    mapped = resolve_artifact_path(root, "static_audit_bundle.json")
    if mapped.exists():
        return mapped
    legacy = root / "static_audit_bundle.json"
    if legacy.exists():
        return legacy
    return None


def load_static_audit_bundle(workdir: str | Path | None) -> dict[str, Any] | None:
    path = static_audit_bundle_path(workdir)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def summarize_findings(findings: list[Any], *, top_limit: int = 5) -> dict[str, Any]:
    valid_findings = [f for f in findings if isinstance(f, dict)]
    risk_counts = {level: 0 for level in RISK_LEVELS}
    for finding in valid_findings:
        risk_counts[normalize_risk_level(finding.get("risk_level"))] += 1

    overall_risk = "info"
    for level in RISK_LEVELS:
        if risk_counts[level] > 0:
            overall_risk = level
            break

    high_quality_findings = [
        finding
        for finding in valid_findings
        if risk_rank(finding.get("risk_level")) >= risk_rank("medium")
    ]
    top_findings = sorted(
        high_quality_findings,
        key=lambda finding: (
            issue_category_rank(finding.get("issue_category")),
            risk_rank(finding.get("risk_level")),
        ),
        reverse=True,
    )[:top_limit]

    return {
        "status": "ok",
        "overall_risk": overall_risk,
        "risk_counts": risk_counts,
        "top_findings": top_findings,
        "total_findings": len(valid_findings),
        "high_quality_count": len(high_quality_findings),
    }
