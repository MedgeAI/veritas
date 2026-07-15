"""Tests for the executable VeritasBench experiment contract."""

from pathlib import Path

import pytest
import yaml

from engine.reproduction.benchmark.experiment_contract import (
    ExperimentContractError,
    build_run_manifest,
    canonical_digest,
    load_experiment_spec,
)
from engine.reproduction.benchmark.experiment_plan import build_experiment_plan


ROOT = Path(__file__).parents[2]
CONFIG = ROOT / "configs/experiments/veritasbench_b1_b5.yaml"


def test_veritasbench_matrix_is_paper_ready():
    spec = load_experiment_spec(CONFIG)

    assert [tier.tier_id for tier in spec.tiers] == ["B1", "B2", "B3", "B4", "B5"]
    assert spec.expected_primary_runs == 250
    assert spec.expected_repeat_runs == 750
    assert spec.tier("B4").pipeline_tier == spec.tier("B5").pipeline_tier
    assert spec.tier("B4").audit_profile == spec.tier("B5").audit_profile
    assert spec.tier("B4").aggregation_policy == "flat"
    assert spec.tier("B5").aggregation_policy == "graph_aware"


def test_identity_digest_ignores_mapping_order():
    assert canonical_digest({"b": 2, "a": 1}) == canonical_digest({"a": 1, "b": 2})


def test_run_manifest_is_stable_and_contains_control_identity():
    spec = load_experiment_spec(CONFIG)
    first = build_run_manifest(
        spec=spec,
        tier_id="B5",
        case_id="case_001",
        repeat_index=1,
        input_hashes={"paper.pdf": "a" * 64},
        tool_registry_digest="b" * 64,
        model_id="test-model",
        seed=7,
        temperature=0.0,
    )
    second = build_run_manifest(
        spec=spec,
        tier_id="B5",
        case_id="case_001",
        repeat_index=1,
        input_hashes={"paper.pdf": "a" * 64},
        tool_registry_digest="b" * 64,
        model_id="test-model",
        seed=7,
        temperature=0.0,
    )

    assert first == second
    assert first["aggregation_policy"] == "graph_aware"
    assert len(first["identity_digest"]) == 64


def test_b4_b5_control_mismatch_fails(tmp_path):
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw["tiers"][4]["audit_profile"] = "full"
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ExperimentContractError, match="B4/B5"):
        load_experiment_spec(invalid)


def test_l1_pilot_can_explicitly_stop_at_b3(tmp_path):
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw["experiment_id"] = "veritasbench_pilot3_b1_b3_v1"
    raw["dataset"]["expected_cases"] = 3
    raw["dataset"]["suite"] = "veritasbench_trial3"
    raw["tiers"] = raw["tiers"][:3]
    pilot = tmp_path / "pilot.yaml"
    pilot.write_text(yaml.safe_dump(raw), encoding="utf-8")

    spec = load_experiment_spec(pilot)

    assert [tier.tier_id for tier in spec.tiers] == ["B1", "B2", "B3"]
    assert spec.expected_primary_runs == 9
    assert spec.expected_repeat_runs == 27


def test_repeat_index_is_bounded():
    spec = load_experiment_spec(CONFIG)
    with pytest.raises(ExperimentContractError, match="repeat_index"):
        build_run_manifest(
            spec=spec,
            tier_id="B1",
            case_id="case_001",
            repeat_index=0,
            input_hashes={},
            tool_registry_digest="a" * 64,
            model_id="test-model",
            seed=0,
            temperature=0.0,
        )


def test_plan_has_expected_cardinality_and_unique_identities():
    spec = load_experiment_spec(CONFIG)
    case_input_hashes = {
        f"case_{index:02d}": {"paper.pdf": f"{index:064x}"}
        for index in range(50)
    }

    plan = build_experiment_plan(
        spec=spec,
        case_input_hashes=case_input_hashes,
        tool_registry_digest="b" * 64,
        model_id="test-model",
        seed=7,
        temperature=0.0,
    )

    assert len(plan["runs"]) == 750
    assert len({run["identity_digest"] for run in plan["runs"]}) == 750
    b4 = next(run for run in plan["runs"] if run["tier_id"] == "B4")
    b5 = next(run for run in plan["runs"] if run["tier_id"] == "B5")
    assert b4["pipeline_tier"] == b5["pipeline_tier"]
    assert b4["audit_profile"] == b5["audit_profile"]
    assert b4["aggregation_policy"] != b5["aggregation_policy"]
