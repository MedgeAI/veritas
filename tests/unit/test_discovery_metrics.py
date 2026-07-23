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
    GoldClaim,
    linking_accuracy,
    linking_accuracy_finding,
    load_gold,
    score_case,
    SysClaim,
)

CASES = Path("benchmarks/veritasbench/cases")


@pytest.mark.skipif(
    not (CASES / "ncb_sting" / "case.json").exists(), reason="signed corpus not present"
)
def test_ncb_sting_gold_enriches_dirty_series():
    gold = load_gold(CASES / "ncb_sting" / "case.json")
    dirty = next(g for g in gold if not g.is_clean)
    # the atom is pure text ("are independent measurements"); numbers come only
    # from observations via the adapter's _series_for_locus
    assert dirty.numbers  # not empty
    assert 0.444025 in dirty.numbers
    assert 0.264686 in dirty.numbers
    assert 0.4075 in dirty.numbers


@pytest.mark.skipif(
    not (CASES / "ncb_sting" / "case.json").exists(), reason="signed corpus not present"
)
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


@pytest.mark.skipif(
    not (CASES / "ncb_sting" / "case.json").exists(), reason="signed corpus not present"
)
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


# ---- finding-based linking (the source_data_auditor emits sparse claim_mappings,
# but forensics FIND the anomalies as findings[] -> this metric recovers that) ----


def _dirty_gold():
    return [
        GoldClaim(
            claim_id="c1",
            atom="independent measurements",
            source_artifact="artifacts/x.xlsx#Figure 1!B20",
            target_artifact="artifacts/x.xlsx#Figure 1!B31",
            source_a1="B20:J20",
            target_a1="B31:J31",
            verdict="inconsistent",
            is_clean=False,
        )
    ]


def test_finding_locus_recall_hits_on_overlapping_columns():
    # system found a duplicate_row_vector in Figure 1 cols B,C (column-granular
    # locator); gold's dirty range is Figure 1 B20:J20 (cols B..J) -> overlap hit
    gold = _dirty_gold()
    findings = [{"evidence_refs": ["EV-1"]}]
    ei_map = {
        "EV-1": {
            "evidence_id": "EV-1",
            "locator": {"sheet": "Figure 1", "columns": "B, C"},
        }
    }
    m = linking_accuracy_finding(gold, findings, ei_map)
    assert m["finding_locus_recall"] == 1.0
    assert m["n_located"] == 1 and m["n_dirty"] == 1


def test_finding_locus_recall_misses_on_different_sheet():
    gold = _dirty_gold()
    findings = [{"evidence_refs": ["EV-1"]}]
    ei_map = {
        "EV-1": {
            "evidence_id": "EV-1",
            "locator": {"sheet": "Figure 2", "columns": "B, C"},
        }
    }
    m = linking_accuracy_finding(gold, findings, ei_map)
    assert m["finding_locus_recall"] == 0.0
    assert m["n_located"] == 0


def test_finding_locus_recall_zero_dirty():
    # no dirty claims -> 0/0 reported as 0.0 (not a crash)
    clean = [
        GoldClaim(
            claim_id="c",
            atom="independent",
            source_artifact="a#s!A1",
            target_artifact="a#s!B1",
            source_a1="A1:A1",
            target_a1="B1:B1",
            verdict="consistent",
            is_clean=True,
        )
    ]
    m = linking_accuracy_finding(clean, [], {})
    assert m["finding_locus_recall"] == 0.0 and m["n_dirty"] == 0


@pytest.mark.skipif(
    not Path(
        "outputs/ncb_il17a/research-integrity-audit/reports/static_audit_bundle.json"
    ).exists(),
    reason="ncb_il17a audit-paper run not present (outputs/ is gitignored)",
)
def test_ncb_il17a_finding_locus_recall_nonzero_on_real_bundle():
    # the real audit-paper run found 145 findings (incl. duplicate_row_vector in
    # Figure 1 cols B,C); the 2 gold dirty claims are in Figure 1 B..J / B..M ->
    # the finding-based metric must recover non-zero linking (claim_mappings was 0/0).
    m = score_case(Path("outputs/ncb_il17a"), CASES / "ncb_il17a" / "case.json")
    assert m["n_dirty"] == 2
    assert m["finding_locus_recall"] > 0.0  # system located the duplications
