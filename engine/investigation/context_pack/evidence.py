from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from engine.static_audit.paths import resolve_artifact_path
from engine.investigation.context_pack._shared import (
    _canonical_ids_cache,
    _CANONICAL_FINDING_ARTIFACTS,
    _EXCLUDED_EXTENSIONS,
    _artifact_path,
    _read_json_artifact,
    _artifact_type,
    _artifact_file_summary,
)


def _scan_artifact_finding_ids(
    data: dict | list | None,
    target: set[str],
) -> None:
    """Extract finding_id values from a parsed JSON artifact into *target*."""
    if not isinstance(data, dict):
        return
    for list_key in ("priority_findings", "findings", "review_queue", "relationships"):
        items = data.get(list_key) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                fid = item.get("finding_id")
                if isinstance(fid, str) and fid:
                    target.add(fid)


def get_all_canonical_finding_ids(
    workdir: Path,
    *,
    _read: Callable[[Path, str], dict | None] | None = None,
) -> set[str]:
    """Return the union of finding_ids across all canonical audit artifacts.

    Scans source_data_findings, source_data_pair_forensics, visual_findings,
    image_relationships, static_audit_bundle, and investigation追加 artifacts.
    Results are cached per workdir to avoid redundant I/O within a single run.
    """
    workdir_str = str(workdir)
    if workdir_str in _canonical_ids_cache:
        return set(_canonical_ids_cache[workdir_str])

    _reader = _read or _read_json_artifact

    all_ids: set[str] = set()
    for artifact_name in _CANONICAL_FINDING_ARTIFACTS:
        data = _reader(workdir, artifact_name)
        _scan_artifact_finding_ids(data, all_ids)

    # Investigation追加 artifacts (JSONL records)
    investigation_path = _artifact_path(workdir, "investigation_rounds.jsonl")
    if investigation_path.exists():
        try:
            for line in investigation_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    _scan_artifact_finding_ids(record, all_ids)
                    for artifact_ref in record.get("output_artifacts") or []:
                        if isinstance(artifact_ref, str) and artifact_ref.endswith(
                            ".json"
                        ):
                            ref_data = _reader(workdir, artifact_ref)
                            _scan_artifact_finding_ids(ref_data, all_ids)
        except OSError:
            pass

    _canonical_ids_cache[workdir_str] = all_ids
    return set(all_ids)


def get_artifact_backref(
    finding_id: str,
    workdir: Path,
    *,
    _read: Callable[[Path, str], dict | None] | None = None,
) -> str | None:
    """Return the relative artifact path where *finding_id* was first found.

    Scans canonical artifacts in order and returns the first match.
    Returns None if the finding_id is not present in any artifact.
    """
    _reader = _read or _read_json_artifact
    for artifact_name in _CANONICAL_FINDING_ARTIFACTS:
        data = _reader(workdir, artifact_name)
        if not isinstance(data, dict):
            continue
        for list_key in (
            "priority_findings",
            "findings",
            "review_queue",
            "relationships",
        ):
            items = data.get(list_key) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("finding_id") == finding_id:
                    return str(
                        resolve_artifact_path(workdir, artifact_name).relative_to(
                            workdir
                        )
                    )
    return None


def clear_canonical_ids_cache() -> None:
    """Clear the canonical finding IDs cache. Intended for tests."""
    _canonical_ids_cache.clear()


def _scan_workdir_artifacts(workdir: Path) -> list[dict[str, Any]]:
    """Scan workdir for existing artifacts, excluding binary/PDF/image."""
    manifest: list[dict[str, Any]] = []
    if not workdir.is_dir():
        return manifest

    for path in sorted(workdir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in _EXCLUDED_EXTENSIONS:
            continue
        artifact_id = path.relative_to(workdir).as_posix()
        size_bytes = path.stat().st_size
        summary = _artifact_file_summary(path)
        manifest.append(
            {
                "id": artifact_id,
                "type": _artifact_type(path),
                "size_bytes": size_bytes,
                "summary": summary,
            }
        )
    return manifest


def _extract_evidence_refs(workdir: Path) -> list[dict[str, Any]]:
    """Extract evidence_refs: pointers to artifact_id + line ranges."""
    refs: list[dict[str, Any]] = []

    source_findings = _read_json_artifact(workdir, "source_data_findings.json")
    if isinstance(source_findings, dict):
        refs.extend(
            {
                "artifact_id": "source_data_findings.json",
                "finding_id": item.get("finding_id"),
                "risk_level": item.get("risk_level"),
                "category": item.get("category"),
            }
            for item in (source_findings.get("priority_findings") or [])[:10]
            if isinstance(item, dict)
        )

    pair_forensics = _read_json_artifact(workdir, "source_data_pair_forensics.json")
    if isinstance(pair_forensics, dict):
        refs.extend(
            {
                "artifact_id": "source_data_pair_forensics.json",
                "finding_id": item.get("finding_id"),
                "risk_level": item.get("risk_level"),
                "category": item.get("category"),
            }
            for item in (pair_forensics.get("priority_findings") or [])[:10]
            if isinstance(item, dict)
        )

    image_dups = _read_json_artifact(workdir, "exact_image_duplicates.json")
    if isinstance(image_dups, dict) and image_dups.get("duplicate_group_count", 0) > 0:
        refs.append(
            {
                "artifact_id": "exact_image_duplicates.json",
                "duplicate_group_count": image_dups.get("duplicate_group_count"),
                "duplicate_image_count": image_dups.get("duplicate_image_count"),
            }
        )

    return refs


def _extract_top_n_findings(
    workdir: Path,
    n: int = 5,
) -> list[dict[str, Any]]:
    """Extract Top-N findings from deterministic audit artifacts."""
    findings: list[dict[str, Any]] = []

    source_findings = _read_json_artifact(workdir, "source_data_findings.json")
    if isinstance(source_findings, dict):
        findings.extend(
            _compact_priority_finding(item)
            for item in (source_findings.get("priority_findings") or [])[:n]
            if isinstance(item, dict)
        )

    pair_forensics = _read_json_artifact(workdir, "source_data_pair_forensics.json")
    if isinstance(pair_forensics, dict):
        remaining = n - len(findings)
        findings.extend(
            _compact_pair_forensics_finding(item)
            for item in (pair_forensics.get("priority_findings") or [])[:remaining]
            if isinstance(item, dict)
        )

    numeric = _read_json_artifact(workdir, "numeric_forensics.json")
    if isinstance(numeric, dict):
        remaining = n - len(findings)
        benford = numeric.get("benford") or {}
        if (
            benford.get("applicability")
            and benford.get("mad", benford.get("mean_absolute_deviation")) is not None
        ):
            findings.append(
                {
                    "source": "numeric_forensics.json",
                    "category": "benford_analysis",
                    "mad": benford.get("mad", benford.get("mean_absolute_deviation")),
                    "applicability": benford.get("applicability"),
                }
            )

    return findings[:n]


def _compact_priority_finding(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "source_data_findings.json",
        "finding_id": item.get("finding_id"),
        "risk_level": item.get("risk_level"),
        "category": item.get("category"),
        "workbook": item.get("workbook"),
        "sheet": item.get("sheet"),
        "column_pair": item.get("column_pair"),
        "relationship_value": item.get("relationship_value"),
        "benign_explanations": (item.get("benign_explanations") or [])[:3],
    }


def _compact_pair_forensics_finding(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "source_data_pair_forensics.json",
        "finding_id": item.get("finding_id"),
        "risk_level": item.get("risk_level"),
        "category": item.get("category"),
        "workbook": item.get("workbook"),
        "sheet": item.get("sheet"),
        "support_rate": item.get("support_rate"),
        "sample_pairs": (
            item.get("sample_pairs") or item.get("sample_exact_pairs") or []
        )[:5],
    }
