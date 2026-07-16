"""Full B1-B5 experiment runner — produces the paper's §5 tables from the combined L1 corpus.

Combines both L1 families into one evaluation and runs the five-gear ablation the paper defines:
  B1 bare / B2 structured / B3 +node-forensics / B4 +edge-verifiers / B5 +decision(FAR budget).

The two families give a clean node/edge split (no collapse on L1):
  * artifact (node, B3) verifier = l1_relationship_verifier — fires on ncb_ DUPLICATION claims.
  * provenance (edge, B4) verifier = rep_recompute_verifier — fires on rep_ REPRODUCTION claims.
  * B5 runs both, then re-decides flag/abstain/pass under FAR<=alpha calibrated on a DEV split.
Each verifier is in scope only for its own family, so B3 leaves rep_ to the agent, B4 leaves ncb_
to the agent, and B5 covers both — a real B3->B4->B5 progression.

Recall lives on ncb_ (real inconsistencies); FAR lives on rep_ (all-clean honest-FP traps); the
combined corpus measures both under one operating point. Split is by CASE (paper-clustered).

Run:  AUDIT_BACKBONE=qwen3.7-plus [EVAL_ALL=1] PYTHONPATH=. uv run python scripts/run_veritasbench_b1b5.py
Dry:  VBENCH_FAKE_AGENT=1 ...  (no API — structural check)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from engine.benchmark.agent_harness import (
    run_artifact_gear,
    run_bare_agent,
    run_constrained_agent,
    run_dual_layer_gear,
    run_provenance_gear,
)
from engine.benchmark.backbones import make_json_agent
from engine.benchmark.decision import apply_decision, fit_decision
from engine.benchmark.metrics import main_table_row, risk_coverage_curve
from engine.benchmark.veritasbench_eval_adapter import load_veritasbench_case, veritasbench_renderer
from engine.benchmark.veritasbench_rep_adapter import (
    load_rep_case,
    rep_recompute_verifier,
    rep_renderer,
)
from engine.benchmark.veritasbench_verifiers import l1_relationship_verifier
from scripts.live_backbones import AUDITOR_SYSTEM, make_backbone

CASES_ROOT = Path("benchmarks/veritasbench/cases")
BACKBONES = os.environ.get("EVAL_BACKBONES", "qwen3.7-plus,deepseek-v4-pro,glm-5.2").split(",")
MAX_TOKENS = int(os.environ.get("AUDIT_MAX_TOKENS", "4000"))
ALPHA = float(os.environ.get("EVAL_ALPHA", "0.05"))
METRIC_KEYS = ["claim_f1", "far", "evidence_precision", f"recall_at_far<={ALPHA:g}", "coverage"]
# small representative default; EVAL_ALL=1 sweeps the whole loadable L1 corpus
PILOT = {"ncb": ["ncb_eet", "ncb_wnt", "ncb_h3v3", "ncb_h19", "ncb_sirt1"],
         "rep": ["rep_coexpr", "rep_mediator", "rep_winnerscurse", "rep_pbc_surv", "rep_methclock"]}


def _dispatch_render():
    """Per-claim neutral renderer: ncb_ duplication -> series view; rep_ reproduction -> values view."""
    ncb_r, rep_r = veritasbench_renderer(), rep_renderer()

    def render(claim, case):
        return (rep_r if (claim.metadata or {}).get("axis") == "reproduction" else ncb_r)(claim, case)

    return render


SPLIT_FILE = Path("benchmarks/veritasbench/splits/l1_dev_test.json")


def _load_corpus():
    """Load combined ncb_+rep_ L1 cases; return (dev_cases, test_cases) per the FIXED split file."""
    split = json.loads(SPLIT_FILE.read_text(encoding="utf-8"))
    dev_ids, test_ids = set(split["dev"]), set(split["test"])
    if os.environ.get("EVAL_ALL"):
        ncb = sorted(p.name for p in CASES_ROOT.iterdir() if p.name.startswith("ncb_"))
        rep = sorted(p.name for p in CASES_ROOT.iterdir() if p.name.startswith("rep_"))
    else:
        ncb, rep = PILOT["ncb"], PILOT["rep"]
    dev, test = [], []
    for cid in ncb + rep:
        loader = load_veritasbench_case if cid.startswith("ncb_") else load_rep_case
        c, _ = loader(CASES_ROOT / cid)
        if not c.claims:
            continue
        (dev if c.case_id in dev_ids else test if c.case_id in test_ids else test).append(c)
    return dev, test


def _flat(by_case):
    return [p for ps in by_case for p in ps]


def _row(preds):
    r = main_table_row(preds, alpha=ALPHA)
    return {k: round(r.get(k, 0.0), 4) for k in METRIC_KEYS}


def _run_gears(cases, agent, render, art_v, prov_v, b5_decision):
    """Run B1-B5 on `cases`; B5 re-decided under `b5_decision` (fit on dev)."""
    b1 = _flat([run_bare_agent(c, agent, render=render) for c in cases])
    b2 = _flat([run_constrained_agent(c, agent, render=render) for c in cases])
    b3 = _flat([run_artifact_gear(c, agent, art_v, render=render) for c in cases])
    b4 = _flat([run_provenance_gear(c, agent, prov_v, render=render) for c in cases])
    b5_raw = _flat([run_dual_layer_gear(c, agent, art_v, prov_v, render=render) for c in cases])
    b5 = apply_decision(b5_raw, b5_decision) if b5_decision else b5_raw
    return {"B1": b1, "B2": b2, "B3": b3, "B4": b4, "B5": b5, "B5_raw": b5_raw}


def _fake_agent(prompt):  # dry-run: deterministic, no API
    return {"verdict": "inconsistent", "evidence_span": "L1:x->y", "confidence": 0.5}


def main() -> int:
    render = _dispatch_render()
    art_v, prov_v = [l1_relationship_verifier()], [rep_recompute_verifier()]
    dev, test = _load_corpus()
    n_claims = sum(len(c.claims) for c in test)
    fake = os.environ.get("VBENCH_FAKE_AGENT")

    out = {"corpus": {"dev_cases": [c.case_id for c in dev], "test_cases": [c.case_id for c in test],
                      "n_test_claims": n_claims}, "alpha": ALPHA, "backbones": {}}

    backbones = ["fake"] if fake else BACKBONES
    for bb in backbones:
        agent = _fake_agent if fake else make_json_agent(make_backbone(bb, max_tokens=MAX_TOKENS), system=AUDITOR_SYSTEM)
        # calibrate B5 decision on DEV (dual-layer predictions), FAR<=alpha
        dev_b5 = _flat([run_dual_layer_gear(c, agent, art_v, prov_v, render=render) for c in dev])
        decision = fit_decision(dev_b5, alpha=ALPHA)
        gears = _run_gears(test, agent, render, art_v, prov_v, decision)
        out["backbones"][bb] = {
            "tiers": {g: _row(gears[g]) for g in ("B1", "B2", "B3", "B4", "B5")},
            "risk_coverage_B5": risk_coverage_curve(gears["B5_raw"])[:8],
            "decision": {"flag_threshold": round(decision.flag_threshold, 4),
                         "abstain_threshold": round(decision.abstain_threshold, 4)},
        }
        print(f"[{bb}] B1 FAR={out['backbones'][bb]['tiers']['B1']['far']} "
              f"B5 FAR={out['backbones'][bb]['tiers']['B5']['far']} "
              f"B5 F1={out['backbones'][bb]['tiers']['B5']['claim_f1']}")

    Path("outputs/experiments/veritasbench").mkdir(parents=True, exist_ok=True)
    dest = Path(f"outputs/experiments/veritasbench/b1b5_maintable{'_fake' if fake else ''}.json")
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"-> {dest}  (test claims={n_claims}, dev={len(dev)} cases, test={len(test)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
