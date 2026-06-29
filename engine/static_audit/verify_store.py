"""Verification store for public report verification.

Stores minimal verification summaries as JSON files for public lookup.
No database dependency — reads/writes JSON files from a configurable directory.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_VERIFY_DIR = "web_data/verifications"


def _get_verify_dir(override: str | Path | None = None) -> Path:
    """Get verification directory, creating it if needed.

    Parameters
    ----------
    override :
        If provided, use this path directly instead of the env-based default.
        Used by tests and by callers that manage their own storage location.
    """
    if override is not None:
        path = Path(override)
    else:
        from engine.env import get_env

        verify_dir = get_env(
            "VERITAS_VERIFY_DIR", required=False, default=DEFAULT_VERIFY_DIR
        )
        path = Path(verify_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_case_index(directory: Path) -> dict[str, Any]:
    """Load case_id -> metadata index. Returns empty dict if missing."""
    index_path = directory / "case_index.json"
    if not index_path.exists():
        return {}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return data.get("cases", {})
    except (OSError, json.JSONDecodeError):
        return {}


def _update_case_index(
    directory: Path, case_id: str, entry: dict[str, Any]
) -> None:
    """Add or update a case_id entry in the index. Atomic write."""
    index_path = directory / "case_index.json"
    index_data: dict[str, Any] = {"cases": {}}
    if index_path.exists():
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    cases = index_data.setdefault("cases", {})
    entries: list[dict[str, Any]] = cases.get(case_id, [])
    if not isinstance(entries, list):
        entries = [entries]
    entries = [e for e in entries if e.get("version") != entry.get("version")]
    entries.append(entry)
    entries.sort(key=lambda e: e.get("version", 0))
    cases[case_id] = entries
    tmp_path = index_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(
            json.dumps(index_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(str(tmp_path), str(index_path))
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def save_verification_summary(
    case_id: str,
    report_id: str,
    paper_title: str,
    grade_data: dict[str, Any],
    *,
    report_version: int | None = None,
    verify_dir: str | Path | None = None,
) -> Path:
    """Save verification summary for public lookup.

    Parameters
    ----------
    case_id : str
        Case identifier.
    report_id : str
        Generated report ID (e.g., "VRT-202606-A3F9B2").
    paper_title : str
        Paper title from the case.
    grade_data : dict
        Certification grade data from ``compute_grade()`` (as dict).
    report_version :
        Optional version number. When provided, the summary includes the
        version and a ``version_history`` list of prior versions.
    verify_dir :
        Optional override for the storage directory.

    Returns
    -------
    Path
        Path to the saved verification JSON file.
    """
    directory = _get_verify_dir(verify_dir)

    # Serialize dimensions — handle both dataclass and dict forms
    raw_dims = grade_data.get("dimensions", [])
    dimensions = []
    for d in raw_dims:
        if hasattr(d, "__dataclass_fields__"):
            from dataclasses import asdict
            dimensions.append(asdict(d))
        elif isinstance(d, dict):
            dimensions.append(d)
        else:
            dimensions.append({"name": str(d)})

    summary: dict[str, Any] = {
        "report_id": report_id,
        "case_id": case_id,
        "paper_title": paper_title,
        "grade": grade_data.get("grade", "?"),
        "grade_label": grade_data.get("label", "Unknown"),
        "dimensions": dimensions,
        "summary": grade_data.get("summary", ""),
        "total_findings": grade_data.get("total_findings", 0),
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if report_version is not None:
        summary["report_version"] = report_version
        # Build version_history from prior versions of the same case
        prior = _collect_prior_versions(
            directory, case_id, current_version=report_version
        )
        summary["version_history"] = prior

    file_path = directory / f"{report_id}.json"
    file_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Update case index for fast lookups
    index_entry = {
        "version": report_version,
        "report_id": report_id,
        "grade": summary.get("grade", "?"),
        "grade_label": summary.get("grade_label", ""),
        "date": summary.get("created_at", ""),
        "paper_title": paper_title,
    }
    _update_case_index(directory, case_id, index_entry)

    logger.info("Verification summary saved: %s -> %s", report_id, file_path)
    return file_path


def _collect_prior_versions(
    directory: Path,
    case_id: str,
    current_version: int,
) -> list[dict[str, Any]]:
    """Collect version entries for all prior versions of *case_id*.

    Returns a list of ``{"version": int, "report_id": str}`` dicts sorted
    by version ascending, excluding the current version.
    """
    prior: list[dict[str, Any]] = []
    # Fast path: use case index if available
    index = _load_case_index(directory)
    if case_id in index:
        entries = index[case_id]
        if not isinstance(entries, list):
            entries = [entries]
        for e in entries:
            v = e.get("version")
            if v is not None and isinstance(v, int) and v < current_version:
                prior.append({
                    "version": v,
                    "report_id": e.get("report_id", ""),
                })
        prior.sort(key=lambda x: x["version"])
        return prior

    # Fallback: linear scan of VRT files
    for path in sorted(directory.glob("VRT-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, KeyError):
            continue
        if data.get("case_id") != case_id:
            continue
        v = data.get("report_version")
        if v is not None and isinstance(v, int) and v < current_version:
            prior.append({
                "version": v,
                "report_id": data.get("report_id", ""),
            })
    prior.sort(key=lambda x: x["version"])
    return prior


def load_verification_summary(
    report_id: str,
    *,
    verify_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """Load verification summary by report ID.

    Parameters
    ----------
    report_id : str
        The report ID to look up.
    verify_dir :
        Optional override for the storage directory.

    Returns
    -------
    dict or None
        Verification summary dict if found, None otherwise.
    """
    directory = _get_verify_dir(verify_dir)
    file_path = directory / f"{report_id}.json"

    if not file_path.exists():
        return None

    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("Failed to load verification summary %s: %s", report_id, e)
        return None


def list_version_history(
    case_id: str,
    *,
    verify_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """List all verification versions for a case, ordered by version ascending.

    Scans the verification directory for JSON files whose ``case_id`` matches.
    Returns a list of version summaries sorted by ``report_version``.
    """
    directory = _get_verify_dir(verify_dir)
    versions: list[dict[str, Any]] = []

    # Fast path: use case index if available
    index = _load_case_index(directory)
    if index:
        entries = index.get(case_id, [])
        if not isinstance(entries, list):
            entries = [entries]
        for e in entries:
            v = e.get("version")
            if v is None:
                continue
            versions.append({
                "version": int(v),
                "report_id": e.get("report_id", ""),
                "grade": e.get("grade", "?"),
                "grade_label": e.get("grade_label", ""),
                "date": e.get("date", ""),
                "paper_title": e.get("paper_title", ""),
            })
        versions.sort(key=lambda x: x["version"])
        if versions:
            return versions

    # Fallback: linear scan of VRT files
    for path in sorted(directory.glob("VRT-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, KeyError):
            continue
        if data.get("case_id") != case_id:
            continue
        v = data.get("report_version")
        if v is None:
            continue
        versions.append({
            "version": int(v),
            "report_id": data.get("report_id", ""),
            "grade": data.get("grade", "?"),
            "grade_label": data.get("grade_label", ""),
            "date": data.get("created_at", ""),
            "paper_title": data.get("paper_title", ""),
        })

    versions.sort(key=lambda x: x["version"])
    return versions
