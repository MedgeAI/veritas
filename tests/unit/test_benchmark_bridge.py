"""Unit tests for engine.benchmark.bridge (detector output -> ClaimPrediction)."""

from __future__ import annotations

import math

from engine.benchmark.bridge import (
    clean_predictions,
    dirty_prediction,
    predictions_from_round2,
)
from engine.benchmark.metrics import claim_prf, false_accusation_rate
from engine.benchmark.schema import LABEL_CLEAN, LABEL_DIRTY


def test_dirty_prediction_flagged_only_when_real():
    p = dirty_prediction("t1", detected=True, verdict="real")
    assert p.gt_label == LABEL_DIRTY and p.predicted_flag and p.confidence == 1.0
    # detected but verdict not 'real' -> not flagged (a hit that the verdict downgraded)
    p2 = dirty_prediction("t2", detected=True, verdict="benign")
    assert not p2.predicted_flag and p2.confidence == 1.0
    # missed entirely
    p3 = dirty_prediction("t3", detected=False, verdict="missing")
    assert not p3.predicted_flag and p3.confidence == 0.0


def test_clean_predictions_flag_count():
    preds = clean_predictions(5, n_flagged=2)
    assert all(p.gt_label == LABEL_CLEAN for p in preds)
    assert sum(1 for p in preds if p.predicted_flag) == 2


def test_clean_predictions_bounds():
    try:
        clean_predictions(3, n_flagged=4)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for n_flagged > n_clean")


def test_predictions_from_round2_cns098_shape():
    # 24 injected (14 detected+real, 10 missing) + 376 clean, 0 false accusations
    round2 = {
        "injected_results": (
            [{"twin": f"real_{i}", "detected": True, "verdict": "real"} for i in range(14)]
            + [{"twin": f"miss_{i}", "detected": False, "verdict": "missing"} for i in range(10)]
        ),
        "mother": {"post_whitelist_findings": 376},
    }
    preds = predictions_from_round2(round2, mother_false_accusations=0)
    assert len(preds) == 24 + 376
    prf = claim_prf(preds)
    assert prf["tp"] == 14 and prf["fn"] == 10 and prf["fp"] == 0
    assert math.isclose(prf["recall"], 14 / 24)
    assert math.isclose(prf["precision"], 1.0)      # 0 false accusations
    assert false_accusation_rate(preds) == 0.0


def test_raw_detector_baseline_far_is_one():
    round2 = {
        "injected_results": [{"twin": "t", "detected": True, "verdict": "real"}],
        "mother": {"post_whitelist_findings": 10},
    }
    preds = predictions_from_round2(round2, mother_false_accusations=10)
    assert false_accusation_rate(preds) == 1.0     # raw detector flags every benign locus
