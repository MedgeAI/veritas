"""Tests for the lightweight VeritasBench dataset preflight."""

import hashlib
import json
from pathlib import Path

from engine.reproduction.benchmark.dataset_validator import validate_dataset


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_valid_dataset(tmp_path: Path) -> None:
    root = tmp_path / "veritasbench"
    case_dir = root / "cases" / "paper_001"
    artifact_dir = case_dir / "artifacts"
    artifact_dir.mkdir(parents=True)
    source = b"source=1\n"
    table = b"table=1\n"
    (artifact_dir / "source.txt").write_bytes(source)
    (artifact_dir / "table.txt").write_bytes(table)

    source_ref = "artifacts/source.txt#value"
    table_ref = "artifacts/table.txt#value"
    case = {
        "case_id": "paper_001",
        "paper_title": "A paper",
        "paper_authors": ["Author"],
        "artifacts": {
            "source": {"path": "artifacts/source.txt", "sha256": _sha256(source), "kind": "source_data"},
            "table": {"path": "artifacts/table.txt", "sha256": _sha256(table), "kind": "table"},
        },
        "observations": {
            source_ref: {
                "value": 1.0,
                "source_artifact": "artifacts/source.txt",
                "source_artifact_hash": _sha256(source),
                "source_span": "line 1",
            },
            table_ref: {
                "value": 1.0,
                "source_artifact": "artifacts/table.txt",
                "source_artifact_hash": _sha256(table),
                "source_span": "line 1",
            },
        },
        "claims": [
            {
                "annotation_id": "ann_001",
                "claim_id": "claim_001",
                "claim_atom": "The value is one.",
                "source_artifact": source_ref,
                "target_artifact": table_ref,
                "relation_type": "L1",
                "verdict": "consistent",
                "evidence_span": "L1:source->table",
                "annotator_id": "annotator_a",
                "annotation_timestamp": "2026-07-13T00:00:00Z",
                "is_clean_claim": True,
            }
        ],
        "metadata": {
            "paper_split": "paper_001",
            "primary_failure_mode": "grounding",
        },
    }
    (case_dir / "case.json").write_text(json.dumps(case), encoding="utf-8")
    (root / "suites").mkdir()
    (root / "suites" / "suite.json").write_text(
        json.dumps({"schema_version": 1, "name": "suite", "case_ids": ["paper_001"]}),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark_id": "veritasbench",
                "case_count": 1,
                "cases": ["paper_001"],
            }
        ),
        encoding="utf-8",
    )


def test_valid_dataset_passes(tmp_path):
    _write_valid_dataset(tmp_path)

    report = validate_dataset(tmp_path / "veritasbench", suite_name="suite", expected_cases=1)

    assert report.ok
    assert report.case_ids == ["paper_001"]
    assert report.clean_claims == 1


def test_scaffold_fails_without_allow_empty(tmp_path):
    root = tmp_path / "veritasbench"
    (root / "suites").mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark_id": "veritasbench",
                "case_count": 1,
                "cases": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "suites" / "suite.json").write_text(
        json.dumps({"schema_version": 1, "name": "suite", "case_ids": []}),
        encoding="utf-8",
    )

    report = validate_dataset(root, suite_name="suite", expected_cases=1)

    assert not report.ok
    assert any("case IDs" in message for message in report.errors)


def test_partial_dataset_passes_only_with_explicit_flag(tmp_path):
    _write_valid_dataset(tmp_path)
    root = tmp_path / "veritasbench"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["case_count"] = 50
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = validate_dataset(root, suite_name="suite", expected_cases=50, allow_partial=True)

    assert report.ok
    assert report.case_ids == ["paper_001"]
    assert any("partial dataset" in message for message in report.warnings)

    strict_report = validate_dataset(root, suite_name="suite", expected_cases=50)
    assert not strict_report.ok


def test_observation_hash_mismatch_fails(tmp_path):
    _write_valid_dataset(tmp_path)
    case_path = tmp_path / "veritasbench" / "cases" / "paper_001" / "case.json"
    case = json.loads(case_path.read_text(encoding="utf-8"))
    case["observations"]["artifacts/source.txt#value"]["source_artifact_hash"] = "0" * 64
    case_path.write_text(json.dumps(case), encoding="utf-8")

    report = validate_dataset(tmp_path / "veritasbench", suite_name="suite", expected_cases=1)

    assert not report.ok
    assert any("source_artifact_hash does not match" in message for message in report.errors)
