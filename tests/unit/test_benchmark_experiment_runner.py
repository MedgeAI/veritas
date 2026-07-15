"""Tests for the reproducible VeritasBench experiment ledger."""

import hashlib
import json
from pathlib import Path

import yaml

from engine.reproduction.benchmark.experiment_runner import (
    ExperimentLedger,
    result_digest,
)


ROOT = Path(__file__).parents[2]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_dataset(root: Path) -> None:
    case_dir = root / "cases" / "paper_001"
    artifacts = case_dir / "artifacts"
    artifacts.mkdir(parents=True)
    source = b"source=1\n"
    table = b"table=1\n"
    (artifacts / "source.txt").write_bytes(source)
    (artifacts / "table.txt").write_bytes(table)

    source_ref = "artifacts/source.txt#value"
    table_ref = "artifacts/table.txt#value"
    case = {
        "case_id": "paper_001",
        "paper_title": "A paper",
        "paper_authors": ["Author"],
        "artifacts": {
            "source": {
                "path": "artifacts/source.txt",
                "sha256": _sha256(source),
                "kind": "source_data",
            },
            "table": {
                "path": "artifacts/table.txt",
                "sha256": _sha256(table),
                "kind": "table",
            },
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
                "annotation_timestamp": "2026-07-14T00:00:00Z",
                "is_clean_claim": True,
            }
        ],
        "metadata": {
            "paper_split": "paper_001",
            "primary_failure_mode": "grounding",
        },
    }
    case_dir.joinpath("case.json").write_text(json.dumps(case), encoding="utf-8")
    (root / "suites").mkdir()
    (root / "suites" / "veritasbench_1.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "veritasbench_1",
                "case_ids": ["paper_001"],
            }
        ),
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


def _write_config(path: Path, *, expected_cases: int = 1) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "experiment_id": "test_experiment",
                "dataset": {
                    "manifest": "manifest.json",
                    "suite": "veritasbench_1",
                    "expected_cases": expected_cases,
                    "split_unit": "paper",
                },
                "tiers": [
                    {
                        "id": tier_id,
                        "pipeline_tier": pipeline_tier,
                        "audit_profile": "fast",
                        "aggregation_policy": policy,
                        "roles": ["judge"],
                    }
                    for tier_id, pipeline_tier, policy in [
                        ("B1", "bare", "flat"),
                        ("B2", "structured", "flat"),
                        ("B3", "artifact", "flat"),
                        ("B4", "provenance", "flat"),
                        ("B5", "provenance", "graph_aware"),
                    ]
                ],
                "consistency": {
                    "repeats": 3,
                    "canonical_fields": ["case_id", "verdicts"],
                    "exclude_from_digest": ["started_at", "finished_at"],
                },
                "metrics": ["claim_f1"],
            }
        ),
        encoding="utf-8",
    )


class FakeBackend:
    backend_id = "test-backend"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def run_case(self, case, tier, repeat_index):
        self.calls.append((case.case_id, tier.tier_id, repeat_index))
        return {
            "metrics": {"claim_f1": 1.0},
            "verdicts": [{"claim_id": "claim_001", "verdict": "pass"}],
            "evidence_spans": ["L1:source->table"],
        }


def test_ledger_prepares_plan_and_executes_all_repeats(tmp_path):
    base_path = tmp_path / "veritasbench"
    _write_dataset(base_path)
    config_path = tmp_path / "experiment.yaml"
    _write_config(config_path)
    output_dir = tmp_path / "outputs"

    ledger = ExperimentLedger(
        config_path,
        base_path=base_path,
        output_dir=output_dir,
        tool_registry_path=ROOT / "engine/tools/registry.py",
    )
    prepared = ledger.prepare()
    assert len(prepared.plan["runs"]) == 15
    assert (output_dir / "plan.json").is_file()
    assert (output_dir / "preflight.json").is_file()

    backend = FakeBackend()
    summary = ledger.execute(backend, prepared=prepared)

    assert len(backend.calls) == 15
    assert summary["complete"] is True
    assert summary["successful_runs"] == 15
    assert summary["failed_runs"] == 0
    assert summary["consistency"]["digest_mismatch_rate"] == 0.0
    assert len(list((output_dir / "runs").glob("*.json"))) == 15


def test_ledger_resume_does_not_reexecute_successful_runs(tmp_path):
    base_path = tmp_path / "veritasbench"
    _write_dataset(base_path)
    config_path = tmp_path / "experiment.yaml"
    _write_config(config_path)
    output_dir = tmp_path / "outputs"
    kwargs = {
        "base_path": base_path,
        "output_dir": output_dir,
        "tool_registry_path": ROOT / "engine/tools/registry.py",
    }

    first_ledger = ExperimentLedger(config_path, **kwargs)
    first_ledger.execute(FakeBackend())

    second_backend = FakeBackend()
    second_ledger = ExperimentLedger(config_path, **kwargs)
    summary = second_ledger.execute(second_backend)

    assert second_backend.calls == []
    assert summary["complete"] is True


def test_result_digest_excludes_runtime_fields():
    base = {"metrics": {"claim_f1": 1.0}, "verdicts": ["pass"]}
    with_runtime = {
        **base,
        "started_at": "one",
        "finished_at": "two",
        "duration_seconds": 4.2,
    }
    assert result_digest(base) == result_digest(with_runtime)


def test_partial_plan_is_explicit_and_has_pilot_cardinality(tmp_path):
    base_path = tmp_path / "veritasbench"
    _write_dataset(base_path)
    manifest_path = base_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["case_count"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    config_path = tmp_path / "experiment.yaml"
    _write_config(config_path, expected_cases=2)

    ledger = ExperimentLedger(
        config_path,
        base_path=base_path,
        output_dir=tmp_path / "outputs",
        tool_registry_path=ROOT / "engine/tools/registry.py",
        allow_partial=True,
    )
    prepared = ledger.prepare()

    assert prepared.plan["partial"] is True
    assert prepared.plan["planned_cases"] == 1
    assert prepared.plan["planned_repeat_runs"] == 15
