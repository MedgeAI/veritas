"""Runtime checks that keep paper benchmark inputs separate from labels."""

import json

import pytest

from engine.reproduction.benchmark.case_loader import BenchmarkCaseLoader
from engine.reproduction.benchmark.runner import BenchmarkDataError, BenchmarkRunner


def _write_case(tmp_path, *, source_value=1.0, target_value=1.0, label="inconsistent"):
    (tmp_path / "suites").mkdir()
    case_dir = tmp_path / "cases" / "case_001"
    case_dir.mkdir(parents=True)
    (tmp_path / "suites" / "suite.json").write_text(
        json.dumps({"name": "suite", "case_ids": ["case_001"]}),
        encoding="utf-8",
    )
    annotation = {
        "annotation_id": "ann_001",
        "claim_id": "claim_001",
        "claim_atom": "The reported value is one.",
        "source_artifact": "source.csv#value",
        "target_artifact": "table.json#value",
        "relation_type": "L1",
        "verdict": label,
        "discrepancy_type": "numeric_mismatch" if label == "inconsistent" else None,
        "evidence_span": "line 1",
        "is_clean_claim": False,
    }
    provenance = {
        "source_artifact": "source.csv",
        "source_artifact_hash": "a" * 64,
        "source_span": "row 1",
    }
    case = {
        "case_id": "case_001",
        "paper_title": "Test paper",
        "paper_authors": ["Author"],
        "artifacts": {},
        "observations": {
            "source.csv#value": {**provenance, "value": source_value},
            "table.json#value": {**provenance, "value": target_value},
        },
        "claims": [annotation],
        "metadata": {},
    }
    (case_dir / "case.json").write_text(json.dumps(case), encoding="utf-8")


def test_loader_rejects_missing_real_benchmark_directory(tmp_path):
    with pytest.raises(FileNotFoundError, match="allow_mock=True"):
        BenchmarkCaseLoader(tmp_path / "missing")


def test_loader_fails_loudly_on_case_missing_from_disk(tmp_path):
    (tmp_path / "suites").mkdir()
    (tmp_path / "suites" / "suite.json").write_text(
        json.dumps({"name": "suite", "case_ids": ["case_001"]}),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="case_001"):
        BenchmarkCaseLoader(tmp_path).load_suite("suite")


def test_real_runner_does_not_use_annotation_label(tmp_path):
    _write_case(tmp_path, source_value=1.0, target_value=1.0, label="inconsistent")
    runner = BenchmarkRunner(
        case_loader=BenchmarkCaseLoader(tmp_path),
        use_mock_verdicts=False,
    )

    result = runner.run("suite")

    assert result.claim_verdicts[0].verdict == "pass"


def test_real_runner_accepts_zero_observation(tmp_path):
    _write_case(tmp_path, source_value=0.0, target_value=0.0, label="inconsistent")
    runner = BenchmarkRunner(
        case_loader=BenchmarkCaseLoader(tmp_path),
        use_mock_verdicts=False,
    )

    result = runner.run("suite")

    assert result.claim_verdicts[0].verdict == "pass"


def test_real_runner_fails_on_missing_observation(tmp_path):
    _write_case(tmp_path)
    case_path = tmp_path / "cases" / "case_001" / "case.json"
    case = json.loads(case_path.read_text(encoding="utf-8"))
    del case["observations"]["table.json#value"]
    case_path.write_text(json.dumps(case), encoding="utf-8")
    runner = BenchmarkRunner(case_loader=BenchmarkCaseLoader(tmp_path))

    with pytest.raises(BenchmarkDataError, match="Missing observation"):
        runner.run("suite")
