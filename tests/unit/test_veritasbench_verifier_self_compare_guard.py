"""Golden contract for B3's self-comparison guard (l1_relationship_verifier).

Locks a two-directional invariant discovered during holdout_detector_disjoint_v4 verification
(natcomm_nguyen_mirna, provenance_mismatch): the guard is keyed on LOCUS IDENTITY, never on value
equality.

  (i)  src and tgt name the SAME locus  -> a series compared to itself is a tautology -> MUST NOT fire
       (extends classify_relationship's len<2 guard to multi-cell same-locus ranges).
  (ii) an elementwise-identical series across TWO DISTINCT loci is a real cross-position copy-paste
       -> MUST still fire. This proves the guard does not dull B3's core duplicate-detection ability.

If (ii) ever regresses to no-fire, the guard has gone value-keyed and silently kills true-positive
duplicate detection — that is the failure this golden test exists to catch.
"""

from __future__ import annotations

from engine.benchmark.schema import Evidence, ClaimInstance, BenchmarkCase
from engine.benchmark.veritasbench_verifiers import classify_relationship, l1_relationship_verifier


def _l1_claim(*, claim_id: str, label: str, src_label: str, tgt_label: str,
              src: list[float], tgt: list[float]) -> ClaimInstance:
    return ClaimInstance(
        claim_id=claim_id,
        claim_type="source_data.l1_consistency",
        level="L1",
        label=label,
        relation="L1",
        evidence=Evidence(evidence_type="source_data", target=tgt_label),
        metadata={"axis": "L1", "src_series": src, "tgt_series": tgt,
                  "src_label": src_label, "tgt_label": tgt_label},
    )


_CASE = BenchmarkCase(case_id="_t", split="real-test", base_paper_id="_t", claims=())


def test_self_comparison_same_locus_does_not_fire():
    """(i) src==tgt locus (nguyen_mirna shape): identical multi-cell series, same range -> no fire."""
    claim = _l1_claim(
        claim_id="self_compare", label="clean",
        src_label="Figure 7f D4:F4", tgt_label="Figure 7f D4:F4",
        src=[12.5, 16.667, 20.0], tgt=[12.5, 16.667, 20.0],
    )
    sig = l1_relationship_verifier()(claim, _CASE)
    # sanity: the underlying math DOES call this a duplicate (a series equals itself) ...
    assert classify_relationship(claim.metadata["src_series"], claim.metadata["tgt_series"])[0] == "duplicate"
    # ... but the locus-keyed guard suppresses the tautological fire.
    assert sig is not None and sig.fired is False


def test_identical_series_distinct_loci_still_fires():
    """(ii) same values, DIFFERENT loci = real copy-paste -> MUST still fire (guard is not value-keyed)."""
    claim = _l1_claim(
        claim_id="cross_locus_dup", label="dirty",
        src_label="Fig 3a B2:B9", tgt_label="Fig 3b D2:D9",
        src=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
        tgt=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
    )
    sig = l1_relationship_verifier()(claim, _CASE)
    assert sig is not None and sig.fired is True


def test_constant_offset_distinct_loci_still_fires():
    """(ii, offset variant): fixed-offset across distinct loci (aldometanib shape) -> MUST still fire."""
    claim = _l1_claim(
        claim_id="cross_locus_offset", label="dirty",
        src_label="Fig4m C4:C12", tgt_label="FigS10a C4:C12",
        src=[1.0, 2.0, 3.0, 4.0, 5.0],
        tgt=[1.908, 2.908, 3.908, 4.908, 5.908],
    )
    sig = l1_relationship_verifier()(claim, _CASE)
    assert sig is not None and sig.fired is True
