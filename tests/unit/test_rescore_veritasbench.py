"""Proves the trace-retention guarantee: a run can be re-scored from its trace with ZERO model calls,
the default rubric reproduces the stored result, and a different rubric changes the numbers — all
from the retained trace, no re-run.
"""

from __future__ import annotations

import json

from engine.benchmark.metrics import ClaimPrediction, main_table_row
from scripts.rescore_veritasbench import (
    conf_gated_rubric,
    default_rubric,
    load_trace,
    rescore,
)

METRIC_KEYS = ["claim_f1", "claim_recall", "far", "evidence_precision", "coverage"]


def _packet(cid, label, flag, dirtiness, verdict, conf, evc=False, abst=False):
    return {"tier": "B1_bare", "repeat": 0, "claim_id": cid,
            "gold": {"label": label},
            "parsed": {"verdict": verdict, "confidence": conf},
            "scored": {"predicted_flag": flag, "dirtiness": dirtiness, "abstained": abst,
                       "evidence_correct": evc},
            "verifier": None}


def _write_job(tmp):
    trace = [
        _packet("c1", "dirty", True, 0.9, "inconsistent", 0.9, evc=True),   # TP
        _packet("c2", "clean", True, 0.6, "inconsistent", 0.5),             # FP (agent conf 0.5)
        _packet("c3", "clean", False, 0.1, "consistent", 0.9),              # TN
        _packet("c4", "dirty", False, 0.4, "consistent", 0.8),              # FN
    ]
    job = tmp / "rep__qwen__v1"
    job.mkdir()
    with (job / "trace.jsonl").open("w") as f:
        for t in trace:
            f.write(json.dumps(t) + "\n")
    # stored result = default scoring, so the fidelity check has something to match
    preds = [default_rubric(p) for p in trace]
    row = main_table_row(preds)
    (job / "result.json").write_text(json.dumps(
        {"tiers": {"B1_bare": {k: round(row.get(k, 0.0), 4) for k in METRIC_KEYS}}}))
    (job / "config.json").write_text(json.dumps(
        {"family": "rep", "backbone": "qwen", "run_tag": "v1", "n_claims": 4, "created_at": "t"}))
    return job


def test_default_rescore_reproduces_result(tmp_path):
    job = _write_job(tmp_path)
    trace = load_trace(job)
    got = rescore(trace, default_rubric)["B1_bare"]
    stored = json.loads((job / "result.json").read_text())["tiers"]["B1_bare"]
    assert got == stored  # zero model calls, exact reproduction


def test_conf_gated_rubric_changes_numbers_from_same_trace(tmp_path):
    job = _write_job(tmp_path)
    trace = load_trace(job)
    default_far = rescore(trace, default_rubric)["B1_bare"]["far"]
    gated_far = rescore(trace, conf_gated_rubric)["B1_bare"]["far"]
    # c2 was a false accusation at conf 0.5; the conf>=0.7 gate drops it -> FAR falls, no re-run
    assert default_far > 0.0 and gated_far == 0.0


def test_rescore_needs_no_gold_verdict_reparse(tmp_path):
    # the trace carries the raw parse; a new rubric reads it directly (proving re-score, not re-run)
    job = _write_job(tmp_path)
    preds = [conf_gated_rubric(p) for p in load_trace(job)]
    assert isinstance(preds[0], ClaimPrediction) and len(preds) == 4
