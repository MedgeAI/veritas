"""Unit tests for engine.benchmark.decision (B5 FAR-constrained selective decision)."""

from __future__ import annotations

import math

from engine.benchmark.decision import ABSTAIN, FLAG, PASS, apply_decision, fit_decision
from engine.benchmark.metrics import ClaimPrediction, coverage_abstention, false_accusation_rate

# dirty at 0.9/0.8/0.7/0.4 ; clean at 0.6/0.3/0.2/0.1
DEV = (
    [ClaimPrediction(f"d{i}", "dirty", predicted_flag=False, confidence=c)
     for i, c in enumerate([0.9, 0.8, 0.7, 0.4])]
    + [ClaimPrediction(f"c{i}", "clean", predicted_flag=False, confidence=c)
       for i, c in enumerate([0.6, 0.3, 0.2, 0.1])]
)


def test_flag_threshold_respects_far():
    # only threshold > 0.6 keeps the clean-at-0.6 out -> flag_threshold == 0.7
    d = fit_decision(DEV, alpha=0.05)
    assert d.flag_threshold == 0.7 and d.abstain_threshold == 0.7  # no abstain band by default


def test_apply_decision_holds_far_bound():
    d = fit_decision(DEV, alpha=0.05)
    out = apply_decision(DEV, d)
    assert false_accusation_rate(out) <= 0.05
    # 3 dirty (0.9/0.8/0.7) flagged, the 0.4 dirty passes
    assert sum(1 for p in out if p.predicted_flag) == 3


def test_decide_three_way():
    d = fit_decision(DEV, alpha=0.05, coverage_target=0.75)
    assert d.decide(0.95) == FLAG
    assert d.decide(0.05) == PASS
    # abstain band opened just below 0.7
    assert d.abstain_threshold < d.flag_threshold
    assert d.decide(d.abstain_threshold) == ABSTAIN


def test_coverage_target_abstains_borderline():
    # abstain (1-0.75)*8 = 2 borderline claims -> coverage 6/8
    d = fit_decision(DEV, alpha=0.05, coverage_target=0.75)
    out = apply_decision(DEV, d)
    cov = coverage_abstention(out)
    assert math.isclose(cov["coverage"], 0.75)
    assert sum(1 for p in out if p.abstained) == 2


def test_already_abstained_stay_abstained():
    preds = list(DEV) + [ClaimPrediction("x", "dirty", predicted_flag=False, confidence=0.95, abstained=True)]
    d = fit_decision(DEV, alpha=0.05)
    out = apply_decision(preds, d)
    x = next(p for p in out if p.claim_id == "x")
    assert x.abstained and not x.predicted_flag
