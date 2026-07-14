"""Unit tests for engine.benchmark.audit_adapter — audit tasks -> VeritasBench BenchmarkCase.

Uses a synthetic mini audit-task dir (no dependency on the rsync'd real tasks). Verifies the
two-axis mapping, the over-accusation trap decoupling, hard-negative handling, injected samples
landing in Evidence.cells, and axis filtering.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.benchmark.audit_adapter import (
    AXIS_ARTIFACT,
    AXIS_CLAIM_SUPPORT,
    axis_claims,
    load_audit_task,
)
from engine.benchmark.schema import LABEL_CLEAN, LABEL_DIRTY

# dataset_01 = over-accusation trap (fabricated but claim still holds); 02 = clean+supported;
# 03 = fabricated + claim NOT supported; 04 = hard negative (clean, but a "suspicious" claim).
_GT = {
    "dataset_01": {"integrity": "fabricated", "claim_supported": "yes",
                   "injected_samples": [{"sample": "S15", "source": "S22"}, {"sample": "S05", "source": "S11"}]},
    "dataset_02": {"integrity": "clean", "claim_supported": "yes"},
    "dataset_03": {"integrity": "fabricated", "claim_supported": "no",
                   "injected_samples": [{"sample": "S02", "source": "S12"}]},
    "dataset_04": {"integrity": "clean", "claim_supported": "yes"},
}


def _make_task(tmp_path: Path, name: str = "medge-audit-1") -> Path:
    task = tmp_path / name
    (task / "tests" / "ground_truth").mkdir(parents=True)
    (task / "tests" / "ground_truth" / "audit_gt.json").write_text(json.dumps(_GT), encoding="utf-8")
    for ds in _GT:
        d = task / "environment" / "data" / ds
        d.mkdir(parents=True)
        (d / "claim.txt").write_text(f"Case vs control claim for {ds}", encoding="utf-8")
    return task


def _by_id(case, suffix):
    return next(c for c in case.claims if c.claim_id.endswith(suffix))


def test_two_claims_per_dataset_and_split(tmp_path):
    case = load_audit_task(_make_task(tmp_path))
    assert case.case_id == "medge-audit-1"
    assert case.split == "synthetic-dev"           # audit-1 is a dev task
    assert len(case.claims) == 2 * len(_GT)         # 2 claims per dataset
    assert case.artifacts["data"].endswith("environment/data")


def test_integrity_axis_labels_and_injected_cells(tmp_path):
    case = load_audit_task(_make_task(tmp_path))
    i01 = _by_id(case, "dataset_01::integrity")
    assert (i01.metadata or {})["axis"] == AXIS_ARTIFACT
    assert i01.label == LABEL_DIRTY                 # fabricated
    assert i01.evidence.cells == frozenset({"S15", "S05"})   # injected sample columns
    assert i01.level == "L3"                        # placeholder only
    i02 = _by_id(case, "dataset_02::integrity")
    assert i02.label == LABEL_CLEAN and not i02.evidence.cells


def test_claim_support_axis_labels(tmp_path):
    case = load_audit_task(_make_task(tmp_path))
    cs01 = _by_id(case, "dataset_01::claim_support")
    assert (cs01.metadata or {})["axis"] == AXIS_CLAIM_SUPPORT
    assert cs01.label == LABEL_CLEAN               # claim_supported == yes -> clean
    assert "dataset_01" in cs01.claim_text
    cs03 = _by_id(case, "dataset_03::claim_support")
    assert cs03.label == LABEL_DIRTY               # claim_supported == no -> dirty (overstated)


def test_over_accusation_trap_decouples_axes(tmp_path):
    # dataset_01: fabricated data BUT claim still holds -> integrity dirty, claim-support clean.
    case = load_audit_task(_make_task(tmp_path))
    assert _by_id(case, "dataset_01::integrity").label == LABEL_DIRTY
    assert _by_id(case, "dataset_01::claim_support").label == LABEL_CLEAN


def test_hard_negative_both_clean(tmp_path):
    # dataset_04: clean data + supported claim -> flagging either is a false accusation.
    case = load_audit_task(_make_task(tmp_path))
    assert _by_id(case, "dataset_04::integrity").label == LABEL_CLEAN
    assert _by_id(case, "dataset_04::claim_support").label == LABEL_CLEAN


def test_axis_claims_filter(tmp_path):
    case = load_audit_task(_make_task(tmp_path))
    art = axis_claims(case, AXIS_ARTIFACT)
    sup = axis_claims(case, AXIS_CLAIM_SUPPORT)
    assert len(art) == len(_GT) and len(sup) == len(_GT)
    assert all((c.metadata or {})["axis"] == AXIS_ARTIFACT for c in art)


def test_split_override(tmp_path):
    case = load_audit_task(_make_task(tmp_path, name="medge-audit-9"), split="synthetic-test")
    assert case.split == "synthetic-test"
