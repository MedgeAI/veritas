"""Lightweight preflight validation for a VeritasBench dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
FAILURE_MODES = {
    "grounding",
    "verifier_conflict",
    "false_positive_trap",
    "mixed_boundary",
}


@dataclass
class ValidationReport:
    """Machine-readable result of one dataset preflight."""

    base_path: str
    suite_name: str
    expected_cases: int
    case_ids: list[str] = field(default_factory=list)
    clean_claims: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "base_path": self.base_path,
            "suite_name": self.suite_name,
            "expected_cases": self.expected_cases,
            "actual_cases": len(self.case_ids),
            "case_ids": self.case_ids,
            "clean_claims": self.clean_claims,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def validate_dataset(
    base_path: Path | str = "benchmarks/veritasbench",
    *,
    suite_name: str = "veritasbench_50",
    expected_cases: int = 50,
    allow_empty: bool = False,
    allow_partial: bool = False,
) -> ValidationReport:
    """Validate the case manifest, artifacts, observations, and annotations."""

    root = Path(base_path)
    report = ValidationReport(str(root), suite_name, expected_cases)
    if expected_cases <= 0:
        report.errors.append("expected_cases must be positive")
        return report
    if not root.is_dir():
        report.errors.append(f"benchmark directory not found: {root}")
        return report

    manifest = _read_json(root / "manifest.json", report, "manifest.json")
    suite = _read_json(root / "suites" / f"{suite_name}.json", report, f"suite {suite_name}")
    if manifest is None or suite is None:
        return report

    _validate_manifest(manifest, report)
    suite_ids = _validate_suite(suite, report)
    manifest_ids = _extract_case_ids(manifest.get("cases"), "manifest.cases", report)

    if manifest.get("case_count") != expected_cases:
        report.errors.append(
            f"manifest.case_count must be {expected_cases}, got {manifest.get('case_count')!r}"
        )
    if allow_partial and len(suite_ids) > expected_cases:
        report.errors.append(
            f"suite {suite_name} cannot contain more than {expected_cases} case IDs, got {len(suite_ids)}"
        )
    elif not allow_partial and len(suite_ids) != expected_cases:
        _empty_or_count_error(
            report,
            allow_empty,
            f"suite {suite_name} must contain {expected_cases} case IDs, got {len(suite_ids)}",
        )
    elif allow_partial and not suite_ids:
        report.errors.append(f"suite {suite_name} must contain at least one case ID for partial validation")
    if allow_partial and len(manifest_ids) > expected_cases:
        report.errors.append(
            f"manifest.cases cannot contain more than {expected_cases} case IDs, got {len(manifest_ids)}"
        )
    elif not allow_partial and len(manifest_ids) != expected_cases:
        _empty_or_count_error(
            report,
            allow_empty,
            f"manifest.cases must contain {expected_cases} case IDs, got {len(manifest_ids)}",
        )
    elif allow_partial and not manifest_ids:
        report.errors.append("manifest.cases must contain at least one case ID for partial validation")
    if suite_ids and manifest_ids and suite_ids != manifest_ids:
        report.errors.append("manifest.cases and suite.case_ids differ or are in a different order")
    if len(set(suite_ids)) != len(suite_ids):
        report.errors.append(f"suite {suite_name} contains duplicate case IDs")
    if len(set(manifest_ids)) != len(manifest_ids):
        report.errors.append("manifest.cases contains duplicate case IDs")
    if allow_partial and 0 < len(suite_ids) < expected_cases:
        report.warnings.append(
            f"partial dataset accepted for pilot validation: {len(suite_ids)}/{expected_cases} cases"
        )

    report.case_ids = suite_ids
    for case_id in suite_ids:
        _validate_case(root / "cases" / case_id, case_id, report)
    return report


def _validate_manifest(data: Mapping[str, Any], report: ValidationReport) -> None:
    if data.get("schema_version") != 1:
        report.errors.append("manifest.schema_version must be 1")
    if data.get("benchmark_id") != "veritasbench":
        report.errors.append("manifest.benchmark_id must be 'veritasbench'")


def _validate_suite(data: Mapping[str, Any], report: ValidationReport) -> list[str]:
    if data.get("schema_version") != 1:
        report.errors.append("suite.schema_version must be 1")
    return _extract_case_ids(data.get("case_ids"), "suite.case_ids", report)


def _extract_case_ids(value: Any, field_name: str, report: ValidationReport) -> list[str]:
    if not isinstance(value, list):
        report.errors.append(f"{field_name} must be a list")
        return []
    case_ids: list[str] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            case_id = item
        elif isinstance(item, Mapping):
            case_id = item.get("case_id")
        else:
            case_id = None
        if not isinstance(case_id, str) or not case_id:
            report.errors.append(f"{field_name}[{index}] must contain a non-empty case_id")
            continue
        case_ids.append(case_id)
    return case_ids


def _validate_case(case_dir: Path, case_id: str, report: ValidationReport) -> None:
    case_path = case_dir / "case.json"
    data = _read_json(case_path, report, f"case {case_id}")
    if data is None:
        return
    if data.get("case_id") != case_id:
        report.errors.append(f"{case_path}: case_id does not match directory name")

    for key in ("paper_title", "paper_authors", "artifacts", "observations", "claims", "metadata"):
        if key not in data:
            report.errors.append(f"{case_path}: missing required field {key!r}")
    if not isinstance(data.get("paper_authors"), list):
        report.errors.append(f"{case_path}: paper_authors must be a list")
    metadata = data.get("metadata")
    if not isinstance(metadata, Mapping):
        report.errors.append(f"{case_path}: metadata must be an object")
    else:
        if not isinstance(metadata.get("paper_split"), str) or not metadata.get("paper_split"):
            report.errors.append(f"{case_path}: metadata.paper_split is required")
        if metadata.get("primary_failure_mode") not in FAILURE_MODES:
            report.errors.append(
                f"{case_path}: metadata.primary_failure_mode must be one of {sorted(FAILURE_MODES)}"
            )

    artifact_hashes = _validate_artifacts(case_dir, data.get("artifacts"), report)
    observations = _validate_observations(case_path, data.get("observations"), artifact_hashes, report)
    _validate_claims(case_path, data.get("claims"), observations, report)


def _validate_artifacts(
    case_dir: Path,
    value: Any,
    report: ValidationReport,
) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        report.errors.append(f"{case_dir / 'case.json'}: artifacts must be a non-empty object")
        return {}
    hashes: dict[str, str] = {}
    for artifact_id, artifact in value.items():
        prefix = f"{case_dir / 'case.json'} artifacts[{artifact_id!r}]"
        if not isinstance(artifact, Mapping):
            report.errors.append(f"{prefix} must be an object")
            continue
        path_value = artifact.get("path")
        digest = artifact.get("sha256")
        if not isinstance(path_value, str) or not path_value:
            report.errors.append(f"{prefix}.path is required")
            continue
        if Path(path_value).is_absolute():
            report.errors.append(f"{prefix}.path must be relative to the case directory")
            continue
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            report.errors.append(f"{prefix}.sha256 must be a 64-character hexadecimal digest")
            continue
        artifact_path = case_dir / path_value
        if not artifact_path.is_file():
            report.errors.append(f"{prefix}.path does not exist as a file: {artifact_path}")
            continue
        actual = _sha256_file(artifact_path)
        if actual.lower() != digest.lower():
            report.errors.append(f"{prefix}.sha256 does not match {artifact_path}")
            continue
        hashes[_normalise_ref(path_value)] = actual.lower()
    return hashes


def _validate_observations(
    case_path: Path,
    value: Any,
    artifact_hashes: Mapping[str, str],
    report: ValidationReport,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        report.errors.append(f"{case_path}: observations must be a non-empty object")
        return {}
    observations: dict[str, Any] = {}
    for reference, observation in value.items():
        prefix = f"{case_path} observations[{reference!r}]"
        if not isinstance(reference, str) or not reference:
            report.errors.append(f"{case_path}: observation references must be non-empty strings")
            continue
        if not isinstance(observation, Mapping):
            report.errors.append(f"{prefix} must be an object")
            continue
        for key in ("value", "source_artifact", "source_artifact_hash", "source_span"):
            if key not in observation or observation[key] in (None, ""):
                report.errors.append(f"{prefix}.{key} is required")
        source_hash = observation.get("source_artifact_hash")
        if not isinstance(source_hash, str) or not SHA256_RE.fullmatch(source_hash):
            report.errors.append(f"{prefix}.source_artifact_hash must be a 64-character hexadecimal digest")
        source_artifact = observation.get("source_artifact")
        if isinstance(source_artifact, str):
            normalized = _normalise_ref(source_artifact)
            expected_hash = artifact_hashes.get(normalized)
            if expected_hash is None:
                report.errors.append(f"{prefix}.source_artifact is not listed in artifacts: {source_artifact}")
            elif isinstance(source_hash, str) and source_hash.lower() != expected_hash:
                report.errors.append(f"{prefix}.source_artifact_hash does not match {source_artifact}")
        observations[reference] = dict(observation)
    return observations


def _validate_claims(
    case_path: Path,
    value: Any,
    observations: Mapping[str, Any],
    report: ValidationReport,
) -> None:
    if not isinstance(value, list) or not value:
        report.errors.append(f"{case_path}: claims must be a non-empty list")
        return
    annotation_ids: set[str] = set()
    clean_claims = 0
    for index, claim in enumerate(value):
        prefix = f"{case_path} claims[{index}]"
        if not isinstance(claim, Mapping):
            report.errors.append(f"{prefix} must be an object")
            continue
        for key in (
            "annotation_id",
            "claim_id",
            "claim_atom",
            "source_artifact",
            "target_artifact",
            "relation_type",
            "verdict",
            "is_clean_claim",
            "annotator_id",
            "annotation_timestamp",
        ):
            if key not in claim or claim[key] in (None, ""):
                report.errors.append(f"{prefix}.{key} is required")
        annotation_id = claim.get("annotation_id")
        if isinstance(annotation_id, str):
            if annotation_id in annotation_ids:
                report.errors.append(f"{prefix}.annotation_id is duplicated: {annotation_id}")
            annotation_ids.add(annotation_id)
        if claim.get("relation_type") not in {"L1", "L2", "L3", "L4"}:
            report.errors.append(f"{prefix}.relation_type must be L1, L2, L3, or L4")
        if claim.get("verdict") not in {"consistent", "inconsistent", "insufficient"}:
            report.errors.append(f"{prefix}.verdict is invalid")
        if not isinstance(claim.get("is_clean_claim"), bool):
            report.errors.append(f"{prefix}.is_clean_claim must be boolean")
        elif claim["is_clean_claim"]:
            clean_claims += 1
            if claim.get("verdict") != "consistent":
                report.errors.append(f"{prefix}: a clean claim must have verdict=consistent")
        for key in ("source_artifact", "target_artifact"):
            reference = claim.get(key)
            if isinstance(reference, str) and reference not in observations:
                report.errors.append(f"{prefix}.{key} is missing from observations: {reference}")
        if claim.get("verdict") in {"consistent", "inconsistent"} and not claim.get("evidence_span"):
            report.errors.append(f"{prefix}.evidence_span is required for a determinate verdict")
    if clean_claims == 0:
        report.errors.append(f"{case_path}: at least one clean claim is required")
    report.clean_claims += clean_claims


def _read_json(path: Path, report: ValidationReport, label: str) -> dict[str, Any] | None:
    if not path.is_file():
        report.errors.append(f"{label} not found: {path}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.errors.append(f"{label} is not valid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        report.errors.append(f"{label} root must be an object")
        return None
    return value


def _empty_or_count_error(report: ValidationReport, allow_empty: bool, message: str) -> None:
    if allow_empty and "got 0" in message:
        report.warnings.append(message)
    else:
        report.errors.append(message)


def _normalise_ref(value: str) -> str:
    return Path(value.replace("\\", "/")).as_posix().lstrip("./")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-path", type=Path, default=Path("benchmarks/veritasbench"))
    parser.add_argument("--suite", default="veritasbench_50")
    parser.add_argument("--expected-cases", type=int, default=50)
    parser.add_argument("--allow-empty", action="store_true", help="Only useful for scaffold checks")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow a non-empty subset for pilot validation; do not use for final results",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    report = validate_dataset(
        args.base_path,
        suite_name=args.suite,
        expected_cases=args.expected_cases,
        allow_empty=args.allow_empty,
        allow_partial=args.allow_partial,
    )
    if args.as_json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        status = "OK" if report.ok else "FAILED"
        print(f"{status}: {len(report.case_ids)}/{report.expected_cases} cases, {report.clean_claims} clean claims")
        for message in report.errors:
            print(f"ERROR: {message}")
        for message in report.warnings:
            print(f"WARNING: {message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
