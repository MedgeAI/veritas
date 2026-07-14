"""Demo: the B1 -> B5 ablation under the DUAL-LAYER design (2026-07-13), mock-first (no LLM).

The ablation is which TOOL LAYER the agent gets. A tiny case carries two fabrications on different
layers plus a clean control:
  - an ARTIFACT-integrity fabrication (node: source-data copied)   -> only the artifact tool sees it
  - a PROVENANCE-consistency fabrication (edge: code output != table) -> only the provenance tool sees it

  B1 bare        over-eager agent: accuses all (FAR up, no grounding).
  B2 structured  forces a grounded span: ungrounded accusations refused.
  B3 artifact    + Artifact-Integrity tools: catches the NODE fraud, misses the edge one.
  B4 provenance  + Provenance-Consistency tools: catches the EDGE fraud, misses the node one.
  B5 dual-layer  + BOTH: catches both (complementary coverage — RQ3).
  (FAR-constrained abstention is cross-cutting via apply_far_control — RQ4, not a gear.)

Run:  PYTHONPATH=. python3 scripts/run_b1_demo.py
"""

from __future__ import annotations

from engine.benchmark.agent_harness import (
    VerifierSignal,
    run_artifact_gear,
    run_bare_agent,
    run_constrained_agent,
    run_dual_layer_gear,
    run_provenance_gear,
)
from engine.benchmark.metrics import main_table_row
from engine.benchmark.schema import (
    LABEL_CLEAN,
    LABEL_DIRTY,
    LEVEL_RELATION,
    BenchmarkCase,
    ClaimInstance,
    Evidence,
)

KEYS = ["claim_f1", "claim_recall", "far", "evidence_precision", "coverage"]


def _claim(cid, label, span):
    return ClaimInstance(claim_id=cid, claim_type="report.x", level="L3", label=label,
                         relation=LEVEL_RELATION["L3"],
                         evidence=Evidence(evidence_type="source_data", target=cid), evidence_span=span)


def _case():
    return BenchmarkCase("dl-demo", "real-test", "dl", (
        _claim("art::sourcedata_copy", LABEL_DIRTY, "L3:d->art"),        # node-layer fraud
        _claim("prov::code_ne_table", LABEL_DIRTY, "L3:t->prov"),        # edge-layer fraud
        _claim("clean::genuine", LABEL_CLEAN, "L3:x->clean"),
    ))


def _layer_tool(tag):
    def v(claim, _case):
        fires = tag in claim.claim_id and claim.label == LABEL_DIRTY
        return VerifierSignal(claim.relation, fired=fires, evidence_span=claim.evidence_span, confidence=0.9)
    return v


def main() -> int:
    case = _case()
    over_eager = lambda p: {"verdict": "inconsistent", "confidence": 0.6}  # noqa: E731
    artifact = [_layer_tool("art")]       # Artifact-Integrity tools (node)
    provenance = [_layer_tool("prov")]    # Provenance-Consistency tools (edge)

    rows = {
        "B1 bare": main_table_row(run_bare_agent(case, over_eager)),
        "B2 structured": main_table_row(run_constrained_agent(case, over_eager)),
        "B3 artifact": main_table_row(run_artifact_gear(case, over_eager, artifact)),
        "B4 provenance": main_table_row(run_provenance_gear(case, over_eager, provenance)),
        "B5 dual-layer": main_table_row(run_dual_layer_gear(case, over_eager, artifact, provenance)),
    }
    print("case: 1 artifact-fraud + 1 provenance-fraud + 1 clean\n")
    print(f"{'system':16s} " + " ".join(f"{k:>18s}" for k in KEYS))
    for name, row in rows.items():
        print(f"{name:16s} " + " ".join(f"{row[k]:>18.3f}" for k in KEYS))
    print("\nB3 catches only the node fraud, B4 only the edge fraud, B5 catches BOTH (dual-layer")
    print("complementarity, RQ3). FAR-constrained abstention is cross-cutting (apply_far_control).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
