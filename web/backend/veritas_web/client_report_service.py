"""Client Report BFF service — aggregates data for the customer-facing report.

Reads from case store, run artifacts, risk summaries, certainty enrichment,
review queue, and verification store to build a single ClientReportView dict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import artifact_file_path
from .risk import summarize_findings


def build_client_report(deps: Any, case_id: str) -> dict[str, Any]:
    """Build the aggregated ClientReportView for a given case.

    Returns a dict with shape:
    {
      "status": "ready" | "running" | "failed" | "unavailable",
      "case": {...},
      "run": {...},
      "certification": {...},
      "risk": {...},
      "findings": [...],
    }
    """
    # 1. Get case
    case = deps.store.get_case(case_id)
    case_dict = case.to_dict()

    # 2. Find latest run
    latest_run_id = case.latest_run_id
    if not latest_run_id:
        return _unavailable(case_dict)

    run = deps.store.get_run(case_id, latest_run_id)
    run_dict = run.to_dict() if hasattr(run, "to_dict") else {}

    # 3. Determine status from run
    if run.status == "running" or run.status == "queued":
        return {
            "status": "running",
            "case": case_dict,
            "run": run_dict,
            "certification": {},
            "risk": {},
            "findings": [],
        }

    if run.status in ("failed", "interrupted", "cancelled"):
        return {
            "status": "failed",
            "case": case_dict,
            "run": run_dict,
            "certification": {},
            "risk": {},
            "findings": [],
        }

    # 4. Completed run — build full report
    workdir = deps.artifacts.latest_workdir(case_id)
    if not workdir:
        return {
            "status": "unavailable",
            "case": case_dict,
            "run": run_dict,
            "certification": {},
            "risk": {},
            "findings": [],
        }

    # 5. Certification grade from run.summary
    certification: dict[str, Any] = {}
    if run.summary:
        grade = (run.summary or {}).get("certification_grade")
        if grade and isinstance(grade, dict):
            certification = {
                "grade": grade.get("grade", "?"),
                "grade_label": grade.get("label", ""),
                "summary": grade.get("summary", ""),
                "dimensions": grade.get("dimensions", []),
                "total_findings": grade.get("total_findings", 0),
            }

    # 6. Report ID from verify_store (search by case_id)
    report_id = _find_report_id_for_case(case_id)
    if report_id:
        certification["report_id"] = report_id

    # 7. Read static_audit_bundle to get findings
    bundle = _load_bundle(workdir)
    findings_raw: list[dict] = []
    if bundle:
        findings_raw = bundle.get("findings", []) or []

    # 8. Summarize findings via risk service
    risk_summary = summarize_findings(findings_raw)

    # 9. Read certainty_data artifact → convert array to Record by finding_id
    certainty_map = _load_certainty_map(workdir)

    # 10. Load review items to inject source_ref and review_decision_allowed
    review_items = _load_review_items(deps, case_id, workdir)
    review_by_finding_id: dict[str, dict] = {}
    for item in review_items:
        fid = item.get("finding_id")
        if fid:
            review_by_finding_id[fid] = item

    # 11. Enrich findings with certainty layers, review data, and location
    enriched_findings = []
    for finding in findings_raw:
        if not isinstance(finding, dict):
            continue
        fid = finding.get("finding_id", "")

        # Certainty layers
        cert = certainty_map.get(fid, {})
        finding["certainty"] = {
            "fact": cert.get("fact", ""),
            "inference": cert.get("inference", ""),
            "suggestion": cert.get("suggestion", ""),
        }

        # Review data
        review = review_by_finding_id.get(fid, {})
        if review:
            finding["source_ref"] = review.get("source_ref", "")
            finding["review_decision_allowed"] = bool(review.get("decision"))
        else:
            finding["source_ref"] = ""
            finding["review_decision_allowed"] = False

        # Location from metadata (PRD §7.3)
        finding["location"] = _extract_location(finding.get("metadata", {}))

        enriched_findings.append(finding)

    return {
        "status": "ready",
        "case": case_dict,
        "run": run_dict,
        "certification": certification,
        "risk": risk_summary,
        "findings": enriched_findings,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _unavailable(case_dict: dict) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "case": case_dict,
        "run": {},
        "certification": {},
        "risk": {},
        "findings": [],
    }


def _load_bundle(workdir: Path) -> dict[str, Any] | None:
    """Load static_audit_bundle.json from workdir."""
    path = artifact_file_path(workdir, "static_audit_bundle.json")
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _find_report_id_for_case(case_id: str) -> str | None:
    """Search verify_store for the latest report_id matching this case_id."""
    try:
        from engine.static_audit.verify_store import _get_verify_dir, _load_case_index

        directory = _get_verify_dir()
        index = _load_case_index(directory)
        entries = index.get(case_id)
        if not entries:
            return None
        # Index may store a list or a single dict (legacy)
        if isinstance(entries, list):
            if not entries:
                return None
            # Return the latest version (last in sorted list)
            latest = entries[-1]
            return latest.get("report_id")
        elif isinstance(entries, dict):
            return entries.get("report_id")
        return None
    except Exception:
        pass
    return None


def _load_certainty_map(workdir: Path) -> dict[str, dict]:
    """Load certainty_data.json and return {finding_id: {fact, inference, suggestion}}."""
    path = artifact_file_path(workdir, "certainty_data.json")
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, list):
        return {}
    result: dict[str, dict] = {}
    for entry in data:
        if isinstance(entry, dict) and "finding_id" in entry:
            result[entry["finding_id"]] = entry
    return result


def _load_review_items(
    deps: Any, case_id: str, workdir: Path
) -> list[dict[str, Any]]:
    """Load review items from review_queue, returning empty list on failure."""
    if deps._session_factory is None:
        return []
    try:
        from .review_queue import list_review_items as _list

        session = deps._session_factory()
        try:
            result = _list(session, case_id, workdir)
            return result.get("items", [])
        finally:
            session.close()
    except Exception:
        return []


def _extract_location(metadata: dict | None) -> str:
    """Extract human-readable location from finding metadata (PRD §7.3).

    Priority: sheet_name + cell_ref > file_name > pattern description.
    """
    if not metadata or not isinstance(metadata, dict):
        return ""
    sheet = metadata.get("sheet_name", "")
    cell = metadata.get("cell_ref", "")
    if sheet and cell:
        return f"{sheet}!{cell}"
    if sheet:
        return sheet
    file_name = metadata.get("file_name", "")
    if file_name:
        return file_name
    pattern = metadata.get("pattern", "")
    if pattern:
        return pattern
    return ""
