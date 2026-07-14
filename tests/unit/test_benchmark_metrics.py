"""Unit tests for engine.benchmark.metrics (VeritasBench main-table metrics)."""

from __future__ import annotations

import math

from engine.benchmark.metrics import (
    ClaimPrediction,
    claim_prf,
    coverage_abstention,
    evidence_precision,
    false_accusation_rate,
    main_table_row,
    recall_at_far,
    risk_coverage_curve,
)

# 3 dirty + 2 clean; hand-computed expectations below.
PREDS = [
    ClaimPrediction("d1", "dirty", predicted_flag=True, confidence=0.9, evidence_correct=True),
    ClaimPrediction("d2", "dirty", predicted_flag=True, confidence=0.6, evidence_correct=False),
    ClaimPrediction("d3", "dirty", predicted_flag=False, confidence=0.2),
    ClaimPrediction("c1", "clean", predicted_flag=False, confidence=0.1),
    ClaimPrediction("c2", "clean", predicted_flag=True, confidence=0.7, evidence_correct=False),
]


def test_claim_prf():
    prf = claim_prf(PREDS)
    assert prf["tp"] == 2 and prf["fp"] == 1 and prf["fn"] == 1
    assert math.isclose(prf["precision"], 2 / 3)
    assert math.isclose(prf["recall"], 2 / 3)
    assert math.isclose(prf["f1"], 2 / 3)


def test_evidence_precision_is_stricter_than_label():
    # 3 flags (d1,d2,c2); only d1 is dirty AND lands on the right cells -> 1/3
    assert math.isclose(evidence_precision(PREDS), 1 / 3)


def test_false_accusation_rate():
    # 2 clean claims, 1 flagged (c2) -> 0.5
    assert math.isclose(false_accusation_rate(PREDS), 0.5)


def test_recall_at_far_needs_high_threshold():
    # c2(clean, conf .7) blocks any FAR<=5% until threshold excludes it; only d1(.9) survives -> 1/3
    got = recall_at_far(PREDS, alpha=0.05)
    assert math.isclose(got["recall_at_far"], 1 / 3)
    assert got["far"] == 0.0
    assert got["threshold"] == 0.9


def test_coverage_no_abstention():
    cov = coverage_abstention(PREDS)
    assert cov["coverage"] == 1.0 and cov["abstention"] == 0.0


def test_abstention_excluded_from_prf_and_lifts_coverage_metric():
    preds = list(PREDS)
    # abstain on the false accusation c2 -> FAR should drop to 0, coverage to 4/5
    preds[4] = ClaimPrediction("c2", "clean", predicted_flag=True, confidence=0.7, abstained=True)
    assert math.isclose(false_accusation_rate(preds), 0.0)
    cov = coverage_abstention(preds)
    assert math.isclose(cov["coverage"], 4 / 5)
    assert math.isclose(cov["abstention"], 1 / 5)


def test_risk_coverage_curve_monotone_coverage():
    curve = risk_coverage_curve(PREDS)
    coverages = [pt["coverage"] for pt in curve]
    assert coverages == sorted(coverages)  # coverage grows as threshold drops
    assert curve[-1]["coverage"] == 1.0


def test_main_table_row_keys():
    row = main_table_row(PREDS, alpha=0.05)
    for key in ("claim_f1", "evidence_precision", "far", "recall_at_far<=0.05", "coverage", "abstention"):
        assert key in row
    assert math.isclose(row["claim_f1"], 2 / 3)
