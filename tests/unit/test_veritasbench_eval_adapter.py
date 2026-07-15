"""Unit tests for the closed eval-loop adapter — the gold-leak guard is the load-bearing one.

Uses the committed signed cases under benchmarks/veritasbench/cases. The red line (taskbrief §): no
gold verdict / discrepancy_type / is_clean / gold evidence_span, and no verdict-leaking claim_atom
phrasing, may ever reach the agent prompt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.benchmark.agent_harness import build_prompt
from engine.benchmark.schema import LABEL_CLEAN, LABEL_DIRTY
from engine.benchmark.veritasbench_eval_adapter import (
    load_veritasbench_case,
    veritasbench_renderer,
)
from engine.benchmark.veritasbench_verifiers import classify_relationship, l1_relationship_verifier

CASES = Path("benchmarks/veritasbench/cases")
RANGE_CASES = ["ncb_eet", "ncb_wnt", "ncb_h3v3", "ncb_h19", "ncb_sirt1"]
LEAKY_PHRASES = ["genuinely different", "NOT the best", "within its own CI", "duplicated_values",
                 "constant_offset", "is_clean_claim"]


def _all_range_claims():
    for cid in RANGE_CASES:
        case, _ = load_veritasbench_case(CASES / cid)
        for claim in case.claims:
            yield case, claim


@pytest.mark.skipif(not CASES.exists(), reason="signed corpus not present")
def test_no_gold_leaks_into_prompt():
    render = veritasbench_renderer()
    checked = 0
    for case, claim in _all_range_claims():
        prompt = build_prompt(claim, case, artifacts_text=render(claim, case))
        assert claim.discrepancy_type is None or claim.discrepancy_type not in prompt
        gold_span = (claim.metadata or {}).get("gold_evidence_span") or ""
        assert not (gold_span and gold_span in prompt)
        for phrase in LEAKY_PHRASES:
            assert phrase.lower() not in prompt.lower()
        checked += 1
    assert checked >= 5


@pytest.mark.skipif(not CASES.exists(), reason="signed corpus not present")
def test_contract_ranges_make_every_l1_claim_extractable():
    # Round-2 contract: every L1 claim carries source/target_a1_range -> nothing is dropped,
    # including the formerly-ambiguous coded (h19) and rc-dialect (sirt1) cases.
    total = 0
    for cid in RANGE_CASES:
        case, rep = load_veritasbench_case(CASES / cid)
        assert rep["dropped"] == 0, f"{cid} dropped {rep['dropped']} claims"
        total += len(case.claims)
    assert total == 14


@pytest.mark.skipif(not CASES.exists(), reason="signed corpus not present")
def test_label_mapping_insufficient_is_clean():
    labels = {claim.verdict: claim.label for _, claim in _all_range_claims()}
    assert labels["inconsistent"] == LABEL_DIRTY
    assert labels["consistent"] == LABEL_CLEAN
    assert labels["insufficient"] == LABEL_CLEAN  # not the positive/dirty class


def test_classify_relationship_kinds():
    assert classify_relationship([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])[0] == "duplicate"
    assert classify_relationship([1.0, 2.0, 3.0], [3.0, 4.0, 5.0])[0] == "constant_offset"
    assert classify_relationship([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0])[0] == "linear_transform"
    assert classify_relationship([1.0, 5.0, 2.0, 9.0], [3.1, 0.2, 8.7, 1.1])[0] == "independent"


@pytest.mark.skipif(not CASES.exists(), reason="signed corpus not present")
def test_verifier_true_signal_on_fp_trap_and_insufficient():
    """The value-only verifier FIRES on the identical-but-legit (eet consistent) and insufficient
    (wnt) claims — the reported verifier_conflict gap, not a bug."""
    verify = l1_relationship_verifier()
    fired = {}
    for case, claim in _all_range_claims():
        fired[claim.claim_id] = verify(claim, case).fired
    # the value-only verifier FALSE-FIRES on the identical-but-legit FP trap and the insufficient
    # claim (both byte-identical) — the verifier_conflict gap the agent tiers must close.
    assert fired["ncb_eet_claim_001"] is True   # consistent (legitimate reuse) -> false fire
    assert fired["ncb_wnt_claim_002"] is True   # insufficient (undecidable)     -> false fire
    # and it correctly stays quiet on a genuinely-different clean pair
    assert fired["ncb_eet_claim_clean"] is False
