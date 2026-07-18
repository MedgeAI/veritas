"""Golden contract for veritasbench_renderer's stat() on non-numeric series.

Found during the v5 holdout backbone smoke test: a label_swap locus carries STRING cell values
(e.g. src=['Osanetant'] / tgt=['Vehicle']), and stat() crashed on sum(int+str). The renderer feeds
B1/B2 the real series content, so any string-valued locus would abort a live run mid-case.

Locks two invariants:
  (i)  a purely numeric series renders EXACTLY as before (n/mean/sd) — the B1-B5 main-table prompt
       content must not shift for the numeric ncb_/rep_ corpus.
  (ii) a non-numeric or mixed series degrades gracefully (no crash), and mixed series compute stats
       over the numeric subset only, flagging the dropped count.
"""

from __future__ import annotations

from engine.benchmark.schema import Evidence, ClaimInstance, BenchmarkCase
from engine.benchmark.veritasbench_eval_adapter import veritasbench_renderer

_CASE = BenchmarkCase(case_id="_t", split="real-test", base_paper_id="_t", claims=())


def _mk(a, b):
    return ClaimInstance(
        claim_id="x", claim_type="source_data.l1_consistency", level="L1", label="dirty",
        relation="L1", evidence=Evidence(evidence_type="source_data", target="t"),
        metadata={"axis": "L1", "src_series": a, "tgt_series": b, "src_label": "A", "tgt_label": "B"},
    )


def test_numeric_series_render_is_unchanged():
    """(i) red line: numeric series still render as n/mean/sd exactly."""
    out = veritasbench_renderer()(_mk([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]), _CASE)
    assert "n=3, mean=2, sd=0.8165" in out
    assert "n=3, mean=5, sd=0.8165" in out
    assert "non-numeric" not in out


def test_non_numeric_series_degrades_gracefully():
    """(ii) label_swap string loci: no crash, reported as non-numeric."""
    out = veritasbench_renderer()(_mk(["Osanetant"], ["Vehicle"]), _CASE)
    assert "n=1, non-numeric" in out
    # the raw values are still shown for the agent to read
    assert "Osanetant" in out and "Vehicle" in out


def test_mixed_series_uses_numeric_subset():
    """(ii) mixed: stats over numeric subset, dropped count flagged."""
    out = veritasbench_renderer()(_mk([1.0, "NA", 3.0], [2.0, 2.0, 2.0]), _CASE)
    assert "n=3, mean=2, sd=1, 1 non-numeric" in out
    assert "n=3, mean=2, sd=0" in out
