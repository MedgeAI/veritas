"""paperconan adapter for Veritas static audit.

Wraps the third-party paperconan numeric forensics tool to detect data fabrication
patterns in source data (identical columns, GRIM/GRIMMER inconsistencies, last-digit
anomalies, cross-sheet duplicates, etc.).

paperconan is a third-party capability source. This adapter:
1. Calls paperconan's scan_dir() API
2. Transforms paperconan's in-memory scan result into a bounded Veritas artifact
3. Writes structured artifacts to outputs/<case_id>/

The adapter does NOT modify paperconan's source code. It treats paperconan as a
read-only capability image under third_party/paperconan/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Add paperconan to sys.path so we can import it without installing
_PAPERCONAN_SRC = Path(__file__).parents[4] / "third_party" / "paperconan" / "src"
if _PAPERCONAN_SRC.is_dir() and str(_PAPERCONAN_SRC) not in sys.path:
    sys.path.insert(0, str(_PAPERCONAN_SRC))


__all__ = ["run_paperconan_scan", "PaperconanAdapterError"]

_SUPPORTED_SOURCE_SUFFIXES = {".xlsx", ".csv", ".tsv", ".pdf", ".docx"}
_LEGACY_UPSTREAM_SCAN_NAME = "scan.json"
_BULKY_ARTIFACT_KEYS = {
    "base64",
    "evidence",
    "image_base64",
    "plot_base64",
    "raw",
    "raw_data",
    "raw_distribution",
    "raw_values",
}


class PaperconanAdapterError(RuntimeError):
    """Raised when the paperconan adapter fails to run or transform results."""


def _load_paperconan() -> tuple[Any, type[Exception]]:
    try:
        from paperconan import scan_dir
        from paperconan.schema import PaperconanInputError
    except ModuleNotFoundError as exc:
        raise PaperconanAdapterError(
            f"paperconan dependency is not available: {exc.name}. Run dependency sync before scanning source data."
        ) from exc
    return scan_dir, PaperconanInputError


def run_paperconan_scan(
    source_data_dir: Path,
    output_dir: Path,
    *,
    profile: str = "review",
    write_html: bool = False,
    write_md: bool = False,
) -> dict[str, Any]:
    """Run paperconan scan on a source data directory and return Veritas-shaped results.

    Args:
        source_data_dir: Directory containing xlsx/csv/tsv/pdf/docx files.
        output_dir: Directory to write paperconan_scan.json artifact.
        profile: False-positive demotion profile ("review", "forensic", "triage").
        write_html: Whether to write paperconan's HTML report (default False, Veritas
            generates its own HTML report).
        write_md: Whether to write paperconan's Markdown report (default False).

    Returns:
        dict with keys:
            - tool: "paperconan"
            - tool_version: str
            - status: "success" | "error" | "no_data"
            - scan_result: compact paperconan scan content (if status == "success")
            - error: error message (if status == "error")
            - findings_summary: dict with counts by severity and kind
            - artifact_path: path to the written paperconan_scan.json

    Raises:
        PaperconanAdapterError: If the scan fails catastrophically.
    """
    if not source_data_dir.is_dir():
        raise PaperconanAdapterError(
            f"source_data_dir does not exist or is not a directory: {source_data_dir}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / "paperconan_scan.json"
    legacy_scan_path = output_dir / _LEGACY_UPSTREAM_SCAN_NAME
    if legacy_scan_path.exists():
        legacy_scan_path.unlink()

    if not any(
        path.is_file() and path.suffix.lower() in _SUPPORTED_SOURCE_SUFFIXES
        for path in source_data_dir.rglob("*")
    ):
        error_result = {
            "tool": "paperconan",
            "tool_version": "unknown",
            "status": "no_data",
            "error": "no supported files found in source_data_dir",
            "findings_summary": {
                "high": 0,
                "medium": 0,
                "low": 0,
                "by_kind": {},
                "total": 0,
            },
            "artifact_path": str(artifact_path),
        }
        _write_error_artifact(artifact_path, error_result)
        return error_result

    scan_dir, paperconan_input_error = _load_paperconan()

    try:
        scan_result = scan_dir(
            in_dir=str(source_data_dir),
            out_dir=str(output_dir),
            write_md=write_md,
            write_html=write_html,
            profile=profile,
            write_json=False,
            evidence=write_html,
        )
    except paperconan_input_error as e:
        # No supported files found — record as "no_data", not a hard failure
        error_result = {
            "tool": "paperconan",
            "tool_version": "unknown",
            "status": "no_data",
            "error": str(e),
            "findings_summary": {
                "high": 0,
                "medium": 0,
                "low": 0,
                "by_kind": {},
                "total": 0,
            },
            "artifact_path": str(artifact_path),
        }
        _write_error_artifact(artifact_path, error_result)
        return error_result
    except Exception as e:
        # Unexpected failure — record as "error"
        error_result = {
            "tool": "paperconan",
            "tool_version": "unknown",
            "status": "error",
            "error": f"paperconan scan failed: {e}",
            "findings_summary": {
                "high": 0,
                "medium": 0,
                "low": 0,
                "by_kind": {},
                "total": 0,
            },
            "artifact_path": str(artifact_path),
        }
        _write_error_artifact(artifact_path, error_result)
        return error_result

    # Transform scan_result into Veritas-shaped findings summary
    findings_summary = _summarize_findings(scan_result)
    compact_scan_result = _compact_scan_result(scan_result)

    veritas_result = {
        "tool": "paperconan",
        "tool_version": scan_result.get("tool_version", "unknown"),
        "status": "success",
        "artifact_policy": {
            "upstream_scan_json": "disabled",
            "omitted_fields": sorted(_BULKY_ARTIFACT_KEYS),
            "reason": "Veritas stores bounded summaries and evidence references, not raw table snippets.",
        },
        "scan_result": compact_scan_result,
        "findings_summary": findings_summary,
        "artifact_path": str(artifact_path),
    }

    # Write the Veritas-shaped artifact
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(veritas_result, f, indent=2, default=str)

    return veritas_result


def _compact_scan_result(scan_result: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe paperconan result without bulky embedded evidence.

    paperconan's native ``scan.json`` is designed as a standalone inspection
    artifact and may embed table snippets in every finding. Veritas keeps source
    files as the evidence of record, so this adapter stores only finding
    metadata, metrics, and source references.
    """
    compact = _drop_bulky_fields(scan_result)
    return compact if isinstance(compact, dict) else {}


def _drop_bulky_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_bulky_fields(item)
            for key, item in value.items()
            if str(key).lower() not in _BULKY_ARTIFACT_KEYS
        }
    if isinstance(value, list):
        return [_drop_bulky_fields(item) for item in value]
    return value


def _summarize_findings(scan_result: dict[str, Any]) -> dict[str, Any]:
    """Summarize paperconan findings by severity and kind.

    Args:
        scan_result: paperconan's scan.json content.

    Returns:
        dict with keys:
            - high: count of high-severity findings
            - medium: count of medium-severity findings
            - low: count of low-severity findings
            - by_kind: dict mapping finding kind to count
            - total: total number of findings
    """
    summary = {
        "high": 0,
        "medium": 0,
        "low": 0,
        "by_kind": {},
        "total": 0,
    }

    # Count findings from relations_blocks
    for block in scan_result.get("relations_blocks", []):
        for finding_list_key in (
            "relations",
            "progressions",
            "equal_pairs",
            "within_col",
            "identical_after_rounding",
            "grim",
        ):
            for finding in block.get(finding_list_key, []):
                severity = finding.get("severity", "low")
                kind = finding.get("kind", "unknown")
                if severity in ("high", "medium", "low"):
                    summary[severity] += 1
                summary["by_kind"][kind] = summary["by_kind"].get(kind, 0) + 1
                summary["total"] += 1

    # Count cross-sheet findings
    for finding in scan_result.get("cross_sheet_findings", []):
        severity = finding.get("severity", "low")
        kind = finding.get("kind", "unknown")
        if severity in ("high", "medium", "low"):
            summary[severity] += 1
        summary["by_kind"][kind] = summary["by_kind"].get(kind, 0) + 1
        summary["total"] += 1

    # Count digit/decimal findings (these are per-sheet, not per-finding)
    summary["digit_distribution_sheets"] = len(
        scan_result.get("digit_distribution", [])
    )
    summary["decimal_endings_sheets"] = len(scan_result.get("decimal_endings", []))

    return summary


def _write_error_artifact(artifact_path: Path, error_result: dict[str, Any]) -> None:
    """Write an error artifact so downstream tools can detect the failure."""
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(error_result, f, indent=2, default=str)
