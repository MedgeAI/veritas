"""Unit tests for engine.benchmark.schema — the unified case/claim loader.

Covers the two on-disk formats mapping into BenchmarkCase and the real-test ground-truth
corpus (ground_truth/paper1, ground_truth/paper2) loading + level accounting. These are
real annotations, so the test doubles as a regression guard on the corpus itself: if a
claim_type family is renamed out of the L3 set, level_coverage() changes and this fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.benchmark.schema import (
    LABEL_CLEAN,
    LABEL_DIRTY,
    ClaimInstance,
    Evidence,
    label_from_verdict,
    level_coverage,
    level_of,
    load_annotations,
    parse_evidence_span,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH = REPO_ROOT / "ground_truth"
CASE_JSON = REPO_ROOT / "tests" / "fixtures" / "veritasbench_cases" / "example_case.json"


def test_level_of_maps_families():
    assert level_of("source_data.fixed_difference") == "L3"
    assert level_of("visual.copy_move_keypoint") == "L3"
    assert level_of("completeness.missing_source_data") == "L3"
    # reserved future families resolve without a schema change
    assert level_of("computation.reported_vs_recomputed") == "L1"
    assert level_of("method.described_vs_implemented") == "L2"
    assert level_of("encoding.bar_height_vs_value") == "L4"


def test_level_of_rejects_unknown_family():
    with pytest.raises(ValueError):
        level_of("bogus.something")


def test_claim_defaults_to_dirty_and_derives_relation():
    # human annotations omit `label`; it must default to dirty and carry the L3 relation.
    case = load_annotations(GROUND_TRUTH / "paper1" / "annotations.yaml", split="real-test")
    assert case.case_id == "HDAC6-valine-DNA-damage"
    assert case.split == "real-test"
    assert len(case.dirty_claims()) == 2
    assert not case.clean_claims()
    claim = case.claims[0]
    assert claim.label == LABEL_DIRTY
    assert claim.level == "L3"
    assert claim.relation == "T/F->S"
    assert claim.source == "human"
    assert claim.confirmed_by_human is True


def test_real_test_corpus_level_coverage():
    cases = [
        load_annotations(GROUND_TRUTH / "paper1" / "annotations.yaml", split="real-test"),
        load_annotations(GROUND_TRUTH / "paper2" / "annotations.yaml", split="real-test"),
    ]
    coverage = level_coverage(cases)
    # everything shipping today is an L3 evidence-integrity verifier: 2 (paper1) + 9 (paper2)
    assert coverage == {"L1": 0, "L2": 0, "L3": 11, "L4": 0}


def test_clean_label_is_accepted_and_excluded_from_dirty():
    # matched-clean loci must round-trip as label=clean and count separately (FAR substrate).
    clean = ClaimInstance(
        claim_id="x::clean0",
        claim_type="source_data.fixed_difference",
        level="L3",
        label=LABEL_CLEAN,
        relation="T/F->S",
        evidence=Evidence(evidence_type="source_data", target="benign locus"),
    )
    assert clean.label == LABEL_CLEAN
    assert clean.level == "L3"


def test_invalid_label_rejected():
    with pytest.raises(ValueError):
        ClaimInstance(
            claim_id="x::bad",
            claim_type="source_data.fixed_difference",
            level="L3",
            label="maybe",
            relation="T/F->S",
            evidence=Evidence(evidence_type="source_data", target="t"),
        )


# --- Data-Guide per-case JSON adapter (canonical GT delivery format) ----------------------

def test_parse_evidence_span():
    assert parse_evidence_span("L1:analysis.py:output_p_value->table1.json:row3_col4") == (
        "L1", "analysis.py:output_p_value", "table1.json:row3_col4"
    )
    # no '->' -> whole remainder is the target
    assert parse_evidence_span("L3:fig1.png") == ("L3", "", "fig1.png")


def test_label_from_verdict():
    assert label_from_verdict("inconsistent") == LABEL_DIRTY
    assert label_from_verdict("consistent") == LABEL_CLEAN
    assert label_from_verdict("insufficient") == LABEL_CLEAN
    assert label_from_verdict("inconsistent", is_clean=True) == LABEL_CLEAN  # is_clean wins
    assert label_from_verdict(None) == LABEL_CLEAN


def test_load_case_json_maps_all_fields():
    case = load_annotations(CASE_JSON, split="real-test")
    assert case.case_id == "paper_demo_001"
    assert case.doi == "10.9999/demo.001"
    assert case.title == "Demo honest paper on treatment effect"
    assert case.language == "python"
    assert case.failure_mode_coverage == {"grounding": True, "verifier_conflict": True, "false_positive_trap": True}
    assert len(case.artifacts["tables"]) == 2
    assert len(case.claims) == 3

    c1, c2, c3 = case.claims
    # c1: L1 inconsistent grounding -> dirty, edge parsed, discrepancy family = computation
    assert c1.level == "L1" and c1.label == LABEL_DIRTY
    assert c1.claim_type == "computation.p_value_mismatch"
    assert c1.relation == "C->T/S"
    assert c1.evidence_span == "L1:analysis.py:output_p_value->table1.json:row3_col4"
    assert c1.evidence.target == "table1.json:row3_col4"
    assert c1.failure_mode_trigger == "grounding"
    assert c1.metadata["evidence_chain_length"] == 3
    assert c1.metadata["distractor_artifacts"] == ["table2.json"]

    # c2: L4 verifier-conflict, per-level verdicts captured
    assert c2.level == "L4" and c2.label == LABEL_DIRTY
    assert c2.claim_type == "encoding.axis_truncation"
    assert c2.per_level_verdicts == {"L1": "consistent", "L3": "consistent", "L4": "inconsistent"}

    # c3: L2 consistent + is_clean -> CLEAN (false-positive trap)
    assert c3.level == "L2" and c3.label == LABEL_CLEAN
    assert c3.claim_type == "method.method_synonym"
    assert c3.failure_mode_trigger == "false_positive_trap"
    assert c3.metadata["trap_type"] == "synonym"


def test_case_json_level_coverage_counts_dirty_only():
    case = load_annotations(CASE_JSON, split="real-test")
    # dirty claims: c1(L1) + c2(L4); c3 is clean -> not counted
    assert level_coverage([case]) == {"L1": 1, "L2": 0, "L3": 0, "L4": 1}


def test_invalid_verdict_and_failure_mode_rejected():
    with pytest.raises(ValueError):
        ClaimInstance(
            claim_id="x", claim_type="report.x", level="L3", label=LABEL_DIRTY, relation="T/F->S",
            evidence=Evidence(evidence_type="report", target="t"), verdict="bogus",
        )
    with pytest.raises(ValueError):
        ClaimInstance(
            claim_id="y", claim_type="report.x", level="L3", label=LABEL_DIRTY, relation="T/F->S",
            evidence=Evidence(evidence_type="report", target="t"), failure_mode_trigger="bogus",
        )
