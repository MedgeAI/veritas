"""Unit tests for the E1 discovery + linking scorer.

Locks the ncb_sting behavior: gold numeric enrichment via the veritas adapter
(series values, including 0.444025), discovery matches the dirty claim, and
locus-level linking is 1.0 when the system cites the gold target range.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.benchmark.discovery_metrics import (
    align,
    linking_accuracy,
    load_gold,
    SysClaim,
)

CASES = Path("benchmarks/veritasbench/cases")


@pytest.mark.skipif(not (CASES / "ncb_sting" / "case.json").exists(),
                    reason="signed corpus not present")
def test_ncb_sting_gold_enriches_dirty_series():
    gold = load_gold(CASES / "ncb_sting" / "case.json")
    dirty = next(g for g in gold if not g.is_clean)
    # the atom is pure text ("are independent measurements"); numbers come only
    # from observations via the adapter's _series_for_locus
    assert dirty.numbers  # not empty
    assert 0.444025 in dirty.numbers
    assert 0.264686 in dirty.numbers
    assert 0.4075 in dirty.numbers


@pytest.mark.skipif(not (CASES / "ncb_sting" / "case.json").exists(),
                    reason="signed corpus not present")
def test_ncb_sting_discovers_and_links_dirty_claim():
    gold = load_gold(CASES / "ncb_sting" / "case.json")
    dirty = next(g for g in gold if not g.is_clean)
    # system 'discovers' the claim text and links it to the correct target locus
    sys_claim = SysClaim(text=dirty.atom, source_data_refs=[dirty.target_artifact])
    matches, unmatched_sys, _ = align([sys_claim], gold)
    assert len(matches) == 1
    assert not unmatched_sys
    # matched the DIRTY claim, not the clean one
    assert not gold[matches[0][2]].is_clean
    link = linking_accuracy(matches, [sys_claim], gold)
    assert link["linking_accuracy_locus"] == 1.0
    assert link["n_correct_link_locus"] == 1


@pytest.mark.skipif(not (CASES / "ncb_sting" / "case.json").exists(),
                    reason="signed corpus not present")
def test_ncb_sting_wrong_target_locus_does_not_link():
    gold = load_gold(CASES / "ncb_sting" / "case.json")
    dirty = next(g for g in gold if not g.is_clean)
    # system cites the SOURCE range (B5:F5) instead of the target (I4:M4) -> no
    # locus-level link (artifact-basename still matches the same workbook).
    sys_claim = SysClaim(text=dirty.atom, source_data_refs=[dirty.source_artifact])
    matches, _, _ = align([sys_claim], gold)
    assert len(matches) == 1
    link = linking_accuracy(matches, [sys_claim], gold)
    assert link["linking_accuracy_locus"] == 0.0
    assert link["linking_accuracy_artifact"] == 1.0  # same workbook basename
