"""Unit tests for engine.benchmark.provenance — the L1 (C->T) provenance verifier skeleton.

Replay is stubbed via static_replay. The crux is rounding-aware comparison: a code output of
0.0501 vs a reported 0.05 must NOT flag (false-positive trap), but a genuine mismatch must.
"""

from __future__ import annotations

from engine.benchmark.agent_harness import run_provenance_gear
from engine.benchmark.metrics import claim_prf
from engine.benchmark.provenance import (
    ComputedValue,
    ObservedRelation,
    l1_computation_verifier,
    l2_method_verifier,
    l3_claim_verifier,
    l4_encoding_verifier,
    methods_equivalent,
    results_replay,
    static_figure_probe,
    static_method_probe,
    static_relation_probe,
    static_replay,
    values_consistent,
)
from engine.benchmark.schema import (
    LABEL_CLEAN,
    LABEL_DIRTY,
    LEVEL_RELATION,
    BenchmarkCase,
    ClaimInstance,
    Evidence,
)


def test_values_consistent_is_rounding_aware():
    assert values_consistent("0.05", 0.0501)          # rounds to 0.05 -> consistent (not a false accusation)
    assert values_consistent("1.23", 1.2300004)       # within rel_tol
    assert values_consistent(0.5, 0.5)
    assert not values_consistent("0.05", 0.061)       # genuine mismatch
    assert not values_consistent("0.80", 0.60)
    assert not values_consistent("1.0", None)         # replay failed -> not consistent


def _l1_claim(cid, label, source, target, reported):
    return ClaimInstance(
        claim_id=cid, claim_type="computation.p_value", level="L1", label=label,
        relation=LEVEL_RELATION["L1"],
        evidence=Evidence(evidence_type="code", target=target),
        evidence_span=f"L1:{source}->{target}", metadata={"reported_value": reported},
    )


def test_l1_verifier_fires_on_mismatch_silent_on_rounding():
    replay = static_replay({"t.json:a": 0.60, "t.json:b": 0.0501})
    verify = l1_computation_verifier(replay)
    case = BenchmarkCase("c", "real-test", "c", ())

    dirty = _l1_claim("d", LABEL_DIRTY, "code.py:funcA", "t.json:a", "0.80")   # 0.80 vs computed 0.60
    clean = _l1_claim("c", LABEL_CLEAN, "code.py:funcB", "t.json:b", "0.05")   # 0.05 vs computed 0.0501

    sig_dirty = verify(dirty, case)
    assert sig_dirty is not None and sig_dirty.fired
    assert sig_dirty.evidence_span == "L1:code.py:funcA->t.json:a"

    sig_clean = verify(clean, case)
    assert sig_clean is not None and not sig_clean.fired   # rounding -> consistent, no accusation


def test_values_consistent_is_ci_and_sd_aware():
    # stochastic: 0.837 vs computed 0.845 -> inconsistent by fixed tol, CONSISTENT within the CI
    assert not values_consistent(0.837, 0.845)                                   # fixed tol too tight
    assert values_consistent(0.837, 0.845, ci_lo=0.825, ci_hi=0.869)             # within bootstrap CI
    assert values_consistent(0.837, 0.845, sd=0.027)                             # within 2 SD
    assert not values_consistent(0.90, 0.845, ci_lo=0.825, ci_hi=0.869)          # outside CI -> real mismatch


def _pbc_shape_csv(tmp_path):
    d = tmp_path / "code" / "results"
    d.mkdir(parents=True)
    (d / "summary_metrics.csv").write_text(
        "model,C_mean,C_sd,C_boot_lo,C_boot_hi\n"
        "xgb,0.845,0.027,0.825,0.869\n", encoding="utf-8")
    return tmp_path


def test_results_replay_enriches_uncertainty(tmp_path):
    replay = results_replay(_pbc_shape_csv(tmp_path))
    cv = replay("code/x.py", "code/results/summary_metrics.csv:xgb_C_mean", BenchmarkCase("c", "real-test", "c", ()))
    assert cv.value == 0.845 and cv.sd == 0.027 and cv.ci_lo == 0.825 and cv.ci_hi == 0.869


def test_l1_verifier_ci_aware_does_not_flag_stochastic(tmp_path):
    # reported 0.837 vs code output 0.845 (seed-different) -> NOT flagged, because within the CI.
    replay = results_replay(_pbc_shape_csv(tmp_path))
    verify = l1_computation_verifier(replay)
    claim = _l1_claim("s", LABEL_CLEAN, "code/x.py", "code/results/summary_metrics.csv:xgb_C_mean", "0.837")
    sig = verify(claim, BenchmarkCase("c", "real-test", "c", ()))
    assert sig is not None and not sig.fired      # CI-aware -> consistent, no false accusation


def test_l1_verifier_out_of_scope_and_unreproducible_return_none():
    verify = l1_computation_verifier(static_replay({}))
    case = BenchmarkCase("c", "real-test", "c", ())
    # non-L1 claim -> out of scope
    l2 = ClaimInstance(claim_id="x", claim_type="method.x", level="L2", label=LABEL_DIRTY,
                       relation=LEVEL_RELATION["L2"], evidence=Evidence(evidence_type="code", target="a.py"))
    assert verify(l2, case) is None
    # L1 but no reported value -> out of scope
    no_val = ClaimInstance(claim_id="y", claim_type="computation.x", level="L1", label=LABEL_DIRTY,
                           relation=LEVEL_RELATION["L1"], evidence=Evidence(evidence_type="code", target="t"),
                           evidence_span="L1:code->t")
    assert verify(no_val, case) is None
    # L1 with reported value but replay can't reproduce -> abstain (None)
    unrepro = _l1_claim("z", LABEL_DIRTY, "missing.py:f", "t:c", "1.0")
    assert verify(unrepro, case) is None


def test_l1_verifier_drives_b4_provenance_gear():
    replay = static_replay({"t.json:a": 0.60, "t.json:b": 0.0501})
    case = BenchmarkCase("c", "real-test", "c", (
        _l1_claim("d", LABEL_DIRTY, "code.py:funcA", "t.json:a", "0.80"),   # mismatch -> should flag
        _l1_claim("c", LABEL_CLEAN, "code.py:funcB", "t.json:b", "0.05"),   # rounding -> should pass
    ))
    useless = lambda p: {"verdict": "insufficient"}  # noqa: E731
    prf = claim_prf(run_provenance_gear(case, useless, [l1_computation_verifier(replay)]))
    assert prf["tp"] == 1 and prf["fn"] == 0     # caught the real L1 inconsistency
    assert prf["fp"] == 0                          # did not falsely accuse the rounding-consistent one


def test_results_replay_reads_real_csv_shape(tmp_path):
    # mirrors the PBC results/summary_metrics.csv shape: first column = row id, rest = metrics
    d = tmp_path / "code" / "results"
    d.mkdir(parents=True)
    (d / "summary_metrics.csv").write_text(
        "model,C_mean,C_sd,gap_C_to_best\nxgb,0.845,0.027,0.0\ncox,0.837,0.027,0.008\n", encoding="utf-8")
    replay = results_replay(tmp_path)
    case = BenchmarkCase("c", "real-test", "c", ())
    assert replay("code/x.py", "code/results/summary_metrics.csv:xgb_C_mean", case).value == 0.845
    assert replay("x", "code/results/summary_metrics.csv:cox_gap_C_to_best", case).value == 0.008
    assert not replay("x", "code/results/summary_metrics.csv:zzz_C_mean", case).ok   # no such row
    assert not replay("x", "code/results/missing.csv:xgb_C_mean", case).ok            # no such file


def test_computed_value_dataclass():
    assert ComputedValue(0.5, ok=True).value == 0.5
    assert not ComputedValue(None, ok=False, detail="x").ok


# ---- L2 method↔code -----------------------------------------------------------------------

def _claim(level, cid, label, source, target, relation_key, **md):
    return ClaimInstance(
        claim_id=cid, claim_type=f"{'method' if level=='L2' else 'report' if level=='L3' else 'encoding' if level=='L4' else 'computation'}.x",
        level=level, label=label, relation=LEVEL_RELATION[level],
        evidence=Evidence(evidence_type="code", target=target),
        evidence_span=f"{level}:{source}->{target}", metadata=md or None,
    )


def test_l2_flags_method_mismatch_allows_synonyms():
    assert methods_equivalent("OLS", "linear regression")     # synonym -> equivalent
    assert not methods_equivalent("t-test", "mann-whitney")
    probe = static_method_probe({"a.py:f1": "mann-whitney", "a.py:f2": "linear regression"})
    verify = l2_method_verifier(probe)
    case = BenchmarkCase("c", "real-test", "c", ())
    bad = _claim("L2", "d", LABEL_DIRTY, "a.py:f1", "m", "L2", claimed_method="t-test")
    ok = _claim("L2", "c", LABEL_CLEAN, "a.py:f2", "m", "L2", claimed_method="OLS")
    assert verify(bad, case).fired
    assert not verify(ok, case).fired


# ---- L3 text↔evidence (overstatement) -----------------------------------------------------

def test_l3_flags_overstatement_not_faithful_claims():
    probe = static_relation_probe({
        "figA": ObservedRelation("increase", significant=False, ok=True),   # not actually significant
        "figB": ObservedRelation("increase", significant=True, ok=True),
    })
    verify = l3_claim_verifier(probe)
    case = BenchmarkCase("c", "real-test", "c", ())
    overstated = _claim("L3", "d", LABEL_DIRTY, "s", "figA", "L3", claimed_significant=True, claimed_direction="increase")
    faithful = _claim("L3", "c", LABEL_CLEAN, "s", "figB", "L3", claimed_significant=True, claimed_direction="increase")
    assert verify(overstated, case).fired      # claimed significant, evidence isn't
    assert not verify(faithful, case).fired


# ---- L4 data↔figure encoding --------------------------------------------------------------

def test_l4_flags_encoding_mismatch_tolerates_rounding():
    probe = static_figure_probe({"figA": [1.0, 2.0, 9.0], "figB": [1.0, 2.001, 3.0]})
    verify = l4_encoding_verifier(probe)
    case = BenchmarkCase("c", "real-test", "c", ())
    wrong = _claim("L4", "d", LABEL_DIRTY, "t", "figA", "L4", data_values=[1.0, 2.0, 3.0])   # bar 3 -> 9
    faithful = _claim("L4", "c", LABEL_CLEAN, "t", "figB", "L4", data_values=[1.0, 2.0, 3.0])
    assert verify(wrong, case).fired
    assert not verify(faithful, case).fired


def test_verifier_out_of_scope_by_level():
    # each verifier is None for claims of other levels
    case = BenchmarkCase("c", "real-test", "c", ())
    l1c = _claim("L1", "x", LABEL_DIRTY, "s", "t", "L1", reported_value="1.0")
    assert l2_method_verifier(static_method_probe({}))(l1c, case) is None
    assert l3_claim_verifier(static_relation_probe({}))(l1c, case) is None
    assert l4_encoding_verifier(static_figure_probe({}))(l1c, case) is None


def test_all_four_provenance_verifiers_drive_b4_gear():
    # a case with one fabrication on each edge L1-L4; the full provenance verifier set catches all.
    from engine.benchmark.agent_harness import run_provenance_gear
    from engine.benchmark.metrics import claim_prf

    case = BenchmarkCase("c", "real-test", "c", (
        _claim("L1", "l1", LABEL_DIRTY, "code:f", "t:a", "L1", reported_value="0.80"),
        _claim("L2", "l2", LABEL_DIRTY, "code:g", "m", "L2", claimed_method="t-test"),
        _claim("L3", "l3", LABEL_DIRTY, "s", "figA", "L3", claimed_significant=True, claimed_direction="increase"),
        _claim("L4", "l4", LABEL_DIRTY, "t", "figB", "L4", data_values=[1.0, 2.0, 3.0]),
    ))
    verifiers = [
        l1_computation_verifier(static_replay({"t:a": 0.60})),
        l2_method_verifier(static_method_probe({"code:g": "mann-whitney"})),
        l3_claim_verifier(static_relation_probe({"figA": ObservedRelation("increase", significant=False, ok=True)})),
        l4_encoding_verifier(static_figure_probe({"figB": [1.0, 2.0, 9.0]})),
    ]
    useless = lambda p: {"verdict": "insufficient"}  # noqa: E731
    prf = claim_prf(run_provenance_gear(case, useless, verifiers))
    assert prf["tp"] == 4 and prf["fn"] == 0     # all four edge fabrications caught
