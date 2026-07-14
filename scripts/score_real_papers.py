"""Score the real-paper headline test set (multi-paper) — the growing VeritasBench test.

Each RealPaperCase reads its source data from the SHARED store (case_data_dir(doi) under
VERITAS_REAL_PAPERS_ROOT). Dirty loci come from the shared INDEX.md curated by w1 (PubPeer /
corpus-confirmed fabrications). For every paper we score recall (over its dirty sheets) + FAR
(over benign column-pair controls), then pool all per-claim predictions into ONE benchmark-wide
main-table row. Per Heiser: the statistical unit is the PAPER, so per-paper rows are shown too.

Run:  VERITAS_REAL_PAPERS_ROOT=<root> PYTHONPATH=. python3 scripts/score_real_papers.py
(local dev must point the env at a reachable copy; on the server the default /srv root is used.)
"""

from __future__ import annotations

import json

from engine.benchmark.metrics import ClaimPrediction, main_table_row
from engine.benchmark.real_paper import DirtyLocus, RealPaperCase, case_data_dir, score_real_paper

# --- the headline test set (DOI -> PubPeer/corpus-confirmed dirty sheets) --------------------
# claim_type documents the fabrication kind; recall detection itself runs ALL detectors per sheet.
_CASES = [
    RealPaperCase(
        paper_id="NPC-radioresistance", doi="10.1038/s41588-025-02253-8",
        data_dir="", dirty=(
            DirtyLocus("41588_2025_2253_MOESM8_ESM.xlsx", "Fig.5c", "source_data.duplicate_row_vector", "#3"),
            DirtyLocus("41588_2025_2253_MOESM9_ESM.xlsx", "Fig.6i", "source_data.row_offset_exact_reuse", "#5"),
            DirtyLocus("41588_2025_2253_MOESM11_ESM.xlsx", "Fig.8f", "source_data.row_offset_exact_reuse", "#4"),
            DirtyLocus("41588_2025_2253_MOESM6_ESM.xlsx", "Fig.3f", "source_data.duplicate_row_vector", "#8"),
            DirtyLocus("41588_2025_2253_MOESM10_ESM.xlsx", "Fig.7d", "source_data.fixed_ratio", "#9"),
            DirtyLocus("41588_2025_2253_MOESM13_ESM.xlsx", "Extended Data Fig.3g", "source_data.paired_difference_spread", "#12"),
        )),
    RealPaperCase(
        paper_id="H19-muscular-dystrophy", doi="10.1038/s41556-020-00595-5",
        data_dir="", dirty=(
            DirtyLocus("MOESM35.xlsx", "Ex. Fig. 9c-d", "source_data.fixed_difference", "ExFig9c-d:9d=9c+10000"),
            DirtyLocus("MOESM25.xlsx", "Ex. Fig. 3h", "source_data.duplicate_columns", "ExFig3h:WT/Homo cross-group"),
        )),
    RealPaperCase(
        paper_id="EET-asthma", doi="10.1038/s41556-021-00762-2",
        data_dir="", dirty=(
            DirtyLocus("MOESM16_ExFig4.xlsx", "ED4", "source_data.fixed_ratio", "ED4:IL-25 NEUWT vs EOSPAD4 ±×10"),
        )),
]


def _with_data_dir(case: RealPaperCase) -> RealPaperCase:
    return RealPaperCase(case.paper_id, case.doi, str(case_data_dir(case.doi)), case.dirty)


def main() -> int:
    pooled: list[ClaimPrediction] = []
    per_paper = []
    for case in (_with_data_dir(c) for c in _CASES):
        r = score_real_paper(case)
        pooled.extend(r["predictions"])
        per_paper.append({
            "paper_id": case.paper_id, "doi": case.doi,
            "recall": f"{r['recall']['detected']}/{r['recall']['dirty_sheets']}",
            "clean_controls": r["far"]["total"], "far": round(r["far"]["far"], 4),
            "f1": round(r["main_table_row"]["claim_f1"], 4),
            "dirty_rows": r["recall"]["rows"],
        })

    benchmark_row = main_table_row(pooled)
    print(json.dumps({
        "papers": len(per_paper),
        "total_dirty_sheets": sum(int(p["recall"].split("/")[1]) for p in per_paper),
        "total_clean_controls": sum(p["clean_controls"] for p in per_paper),
        "benchmark_wide_row": {k: round(v, 4) for k, v in benchmark_row.items()},
    }, ensure_ascii=False, indent=2))
    for p in per_paper:
        print(f"\n=== {p['paper_id']}  ({p['doi']}) ===")
        print(f"  recall(sheet)={p['recall']}  clean_controls={p['clean_controls']}  FAR={p['far']}  F1={p['f1']}")
        for d in p["dirty_rows"]:
            print(f"    {d['sheet']:24s} det={d['detected']} cats={d['categories']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
