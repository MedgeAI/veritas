"""Demo: the REAL source-data verifier driving B3/B4/B5 on a REAL paper (paper2, NPC).

Closes the loop from mock to real: builds a BenchmarkCase over paper2's actual xlsx (6 PubPeer-
confirmed dirty sheets + benign sheets as clean controls), then runs B3/B4/B5 with the real
`source_data_verifier` (which runs the deterministic detectors on the real files). No LLM needed —
the typed verifier carries the load; a useless agent stands in for the backbone.

Run:  VERITAS_REAL_PAPERS_ROOT=<root> PYTHONPATH=. python3 scripts/run_real_verifier_demo.py
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from engine.benchmark.agent_harness import (
    run_graph_agent,
    run_risk_controlled_agent,
    run_tool_augmented_agent,
)
from engine.benchmark.decision import fit_decision
from engine.benchmark.metrics import main_table_row
from engine.benchmark.real_paper import case_data_dir
from engine.benchmark.schema import (
    LABEL_CLEAN,
    LABEL_DIRTY,
    LEVEL_RELATION,
    BenchmarkCase,
    ClaimInstance,
    Evidence,
)
from engine.benchmark.verifiers import source_data_verifier

DOI = "10.1038/s41588-025-02253-8"
DIRTY = [  # (workbook, sheet) — PubPeer-confirmed source-data fabrications
    ("41588_2025_2253_MOESM8_ESM.xlsx", "Fig.5c"),
    ("41588_2025_2253_MOESM9_ESM.xlsx", "Fig.6i"),
    ("41588_2025_2253_MOESM11_ESM.xlsx", "Fig.8f"),
    ("41588_2025_2253_MOESM6_ESM.xlsx", "Fig.3f"),
    ("41588_2025_2253_MOESM10_ESM.xlsx", "Fig.7d"),
    ("41588_2025_2253_MOESM13_ESM.xlsx", "Extended Data Fig.3g"),
]


def _claim(workbook: str, sheet: str, label: str) -> ClaimInstance:
    return ClaimInstance(
        claim_id=f"{workbook}:{sheet}", claim_type="source_data.duplicate_columns", level="L3",
        label=label, relation=LEVEL_RELATION["L3"],
        evidence=Evidence(evidence_type="source_data", target=f"{workbook} / {sheet}",
                          workbook=workbook, sheet=sheet),
        evidence_span=f"L3:{workbook}->{workbook}:{sheet}",
    )


def _benign_claims(data_dir: Path, dirty: set[tuple[str, str]], limit: int = 12) -> list[ClaimInstance]:
    """A few sheets NOT flagged by PubPeer, as clean controls (genuine data -> should not fire)."""
    out: list[ClaimInstance] = []
    for wb_path in sorted(data_dir.glob("*.xlsx")):
        wb = load_workbook(wb_path, read_only=True)
        for ws in wb.worksheets:
            if (wb_path.name, ws.title) in dirty:
                continue
            out.append(_claim(wb_path.name, ws.title, LABEL_CLEAN))
            if len(out) >= limit:
                wb.close()
                return out
        wb.close()
    return out


def main() -> int:
    data_dir = case_data_dir(DOI)
    if not data_dir.exists():
        print(f"missing data at {data_dir} — set VERITAS_REAL_PAPERS_ROOT to a local copy")
        return 1

    dirty_set = set(DIRTY)
    claims = [_claim(wb, sh, LABEL_DIRTY) for wb, sh in DIRTY] + _benign_claims(data_dir, dirty_set)
    case = BenchmarkCase(case_id="NPC-paper2", split="real-test", base_paper_id=DOI, claims=tuple(claims))
    verify = source_data_verifier(data_dir)
    useless = lambda p: {"verdict": "insufficient"}  # noqa: E731 — real verifier does the work

    b4 = run_graph_agent(case, useless, [verify])
    decision = fit_decision(b4, alpha=0.05)
    rows = {
        "B3 tool-augmented": main_table_row(run_tool_augmented_agent(case, useless, [verify])),
        "B4 graph-aggregated": main_table_row(b4),
        "B5 risk-controlled": main_table_row(run_risk_controlled_agent(case, useless, [verify], decision)),
    }
    n_dirty = sum(1 for c in claims if c.label == LABEL_DIRTY)
    n_clean = sum(1 for c in claims if c.label == LABEL_CLEAN)
    print(f"paper2 real case: {n_dirty} dirty sheets + {n_clean} benign controls, REAL detectors\n")
    keys = ["claim_f1", "claim_recall", "far", "evidence_precision", "coverage"]
    print(f"{'system':22s} " + " ".join(f"{k:>12s}" for k in keys))
    for name, row in rows.items():
        print(f"{name:22s} " + " ".join(f"{row[k]:>12.3f}" for k in keys))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
