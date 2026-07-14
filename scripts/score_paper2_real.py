"""Score paper2 (NPC, Nat Genet 2025) as a REAL headline test case — recall + FAR from one paper.

Thin driver over engine.benchmark.real_paper.score_real_paper ("一鱼两吃": recall from the 6
PubPeer-confirmed dirty sheets + FAR from benign column-pair controls in the same paper). The
source data is read from the SHARED store (engine.env.real_papers_root() -> ...
downloads/real-papers/<doi>__<slug>/source_data/), so multiple windows use one copy.

Run from repo root:  PYTHONPATH=. python3 scripts/score_paper2_real.py
"""

from __future__ import annotations

import json

import yaml

from engine.benchmark.real_paper import DirtyLocus, RealPaperCase, case_data_dir, score_real_paper
from engine.twins.matched_clean import clean_control_rows

DOI = "10.1038/s41588-025-02253-8"
PAPER_ID = "NPC-radioresistance-s41588-025-02253-8"

CASE = RealPaperCase(
    paper_id=PAPER_ID,
    doi=DOI,
    data_dir=str(case_data_dir(DOI)),
    dirty=(
        DirtyLocus("41588_2025_2253_MOESM8_ESM.xlsx", "Fig.5c", "source_data.duplicate_row_vector", "#3"),
        DirtyLocus("41588_2025_2253_MOESM9_ESM.xlsx", "Fig.6i", "source_data.row_offset_exact_reuse", "#5"),
        DirtyLocus("41588_2025_2253_MOESM11_ESM.xlsx", "Fig.8f", "source_data.row_offset_exact_reuse", "#4"),
        DirtyLocus("41588_2025_2253_MOESM6_ESM.xlsx", "Fig.3f", "source_data.duplicate_row_vector", "#8"),
        DirtyLocus("41588_2025_2253_MOESM10_ESM.xlsx", "Fig.7d", "source_data.fixed_ratio", "#9"),
        DirtyLocus("41588_2025_2253_MOESM13_ESM.xlsx", "Extended Data Fig.3g", "source_data.paired_difference_spread", "#12"),
    ),
)


def main() -> int:
    result = score_real_paper(CASE)
    controls = result.pop("controls")

    # generated artifacts go in the case's parent dir, keeping source_data/ pristine.
    case_root = case_data_dir(DOI).parent
    if controls:
        doc = {"paper": {"base_paper_id": PAPER_ID, "source": "human",
                         "note": "matched-clean controls from benign (non-PubPeer-flagged) source-data sheets"},
               "claims": clean_control_rows(controls)}
        (case_root / "clean_controls.annotations.yaml").write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (case_root / "real_score.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    row = result["main_table_row"]
    print(json.dumps({
        "data_dir": CASE.data_dir,
        "recall_sheetlevel": f"{result['recall']['detected']}/{result['recall']['dirty_sheets']}",
        "clean_controls": result["far"]["total"], "far": round(result["far"]["far"], 4),
        "claim_f1": round(row["claim_f1"], 4), "claim_recall": round(row["claim_recall"], 4),
    }, ensure_ascii=False))
    for r in result["recall"]["rows"]:
        print(f"  {r['sheet']:22s} {r['pubpeer']:4s} {r['claim_type']:34s} detected={r['detected']} cats={r['categories']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
