"""Tests for the rep_ (reproduction / honest-FP) eval adapter.

rep_ cases are all-clean (consistent + insufficient, no inconsistent) — the FAR / selective-
prediction axis. Locks: L1 claims load, the agent never sees the gold, and the recompute B3
verifier is node-only (it does not fire on a genuinely-reproducing value).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.benchmark.schema import LABEL_CLEAN
from engine.benchmark.veritasbench_rep_adapter import (
    load_rep_case,
    rep_recompute_verifier,
    rep_renderer,
)

CASES = Path("benchmarks/veritasbench/cases")
REP = ["rep_pbc_surv", "rep_coexpr", "rep_mediator", "rep_winnerscurse"]


@pytest.mark.skipif(not CASES.exists(), reason="signed corpus not present")
@pytest.mark.parametrize("cid", REP)
def test_rep_claims_load_and_are_clean(cid):
    case, rep = load_rep_case(CASES / cid)
    assert rep["loaded"] == rep["total_l1"] and rep["loaded"] > 0
    # the honest-FP family carries no dirty (inconsistent) claim
    assert all(c.label == LABEL_CLEAN for c in case.claims)


@pytest.mark.skipif(not CASES.exists(), reason="signed corpus not present")
@pytest.mark.parametrize("cid", REP)
def test_gold_not_in_oracle_content(cid):
    # what the agent sees (claim_text + rendered values) must not carry the gold verdict/discrepancy
    case, _ = load_rep_case(CASES / cid)
    render = rep_renderer()
    for c in case.claims:
        seen = (c.claim_text + "\n" + render(c, case)).lower()
        assert c.verdict not in ("inconsistent",) or "inconsistent" not in seen
        if c.discrepancy_type:
            assert c.discrepancy_type.lower() not in seen


@pytest.mark.skipif(not CASES.exists(), reason="signed corpus not present")
def test_recompute_verifier_is_node_only():
    # on genuinely reproducing values the node verifier stays quiet (clean FAR) — it cannot see
    # the naive-vs-correct methodology (the reported node-vs-edge blind spot)
    verify = rep_recompute_verifier()
    case, _ = load_rep_case(CASES / "rep_coexpr")
    assert all(not verify(c, case).fired for c in case.claims)
