"""Full B1-B5 experiment runner — produces the paper's §5 tables from the combined L1 corpus.

Combines both L1 families into one evaluation and runs the five-gear ablation the paper defines,
CUMULATIVE so the table is monotone (each gear adds one layer on top of the previous):
  B1 bare / B2 structured / B3 +node-forensics / B4 +edge-verifiers / B5 +decision(FAR budget).

The two families give a clean node/edge split (no collapse on L1):
  * artifact (node) verifier = l1_relationship_verifier — fires on ncb_ DUPLICATION claims.
  * provenance (edge) verifier = rep_recompute_verifier — fires on rep_ REPRODUCTION claims.
  * B3 adds the node verifier (helps ncb_, leaves rep_ to the agent).
  * B4 adds the edge verifier ON TOP of the node verifier (node+edge dual-layer): B3 ⊆ B4.
  * B5 keeps B4's dual-layer predictions and adds a flag/abstain/pass decision under FAR<=alpha
    calibrated on a DEV split. B4 and B5 share one dual-layer pass (computed once).
A per-family breakdown (node-only vs edge-only contribution) lives in the appendix, not this table.

Recall lives on ncb_ (real inconsistencies); FAR lives on rep_ (all-clean honest-FP traps); the
combined corpus measures both under one operating point. Split is by CASE (paper-clustered).

Run:  AUDIT_BACKBONE=qwen3.7-plus [EVAL_ALL=1] PYTHONPATH=. uv run python scripts/run_veritasbench_b1b5.py
Dry:  VBENCH_FAKE_AGENT=1 ...  (no API — structural check)
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from engine.benchmark.agent_harness import (
    run_artifact_gear,
    run_bare_agent,
    run_constrained_agent,
    run_dual_layer_gear,
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
from scripts.run_veritasbench_eval import (
    _bootstrap_ci,  # paper-level 95% CI: resample CASES with replacement, recompute metric
    _leak_scan,     # hard-gate-1: gold + task-hint prompt scan
)

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


def _hb(msg):
    """Heartbeat line to stderr (flushed) so a long run is observable in real time — distinguishes
    'slow but progressing' (steady lines) from a genuine stall (lines stop). Real backbone calls on
    this benchmark take ~15-60s each (big prompt + 4k reasoning budget), so a backbone is ~30+ min
    and the final per-backbone print alone gives no intra-run signal."""
    print(msg, file=sys.stderr, flush=True)


def _timed(agent, tag):
    """Wrap an AgentFn so every model call emits a heartbeat with its own latency + a running count."""
    n = {"i": 0}

    def wrapped(prompt):
        n["i"] += 1
        t = time.time()
        r = agent(prompt)
        _hb(f"  [{tag}] call {n['i']} {time.time() - t:5.1f}s")
        return r

    return wrapped


def _flat(by_case):
    return [p for ps in by_case for p in ps]


def _row(preds):
    r = main_table_row(preds, alpha=ALPHA)
    return {k: round(r.get(k, 0.0), 4) for k in METRIC_KEYS}


def _run_gears(cases, agent, render, art_v, prov_v, b5_decision, bb=""):
    """Run B1-B5 on `cases`; B5 re-decided under `b5_decision` (fit on dev). Every gear returns
    predictions grouped BY CASE (list[list]) so paper-level bootstrap CI can resample whole cases."""
    def gear(tag, fn):
        t = time.time()
        _hb(f"[{bb}] {tag} start ({len(cases)} cases)")
        by_case = [fn(c, _timed(agent, f"{bb} {tag}")) for c in cases]  # list[list], one per case
        _hb(f"[{bb}] {tag} done in {time.time() - t:.0f}s")
        return by_case

    b1 = gear("B1", lambda c, a: run_bare_agent(c, a, render=render))
    b2 = gear("B2", lambda c, a: run_constrained_agent(c, a, render=render))
    b3 = gear("B3", lambda c, a: run_artifact_gear(c, a, art_v, render=render))
    # B4 = CUMULATIVE node+edge (dual-layer, no decision) so the ablation is monotone B3 ⊆ B4.
    # B5 = the SAME dual-layer predictions + the FAR-budget decision layer, so compute the gear once
    # and reuse it for both (saves a whole extra pass of agent calls per backbone).
    b4 = gear("B4", lambda c, a: run_dual_layer_gear(c, a, art_v, prov_v, render=render))
    b5_raw = b4
    # decision is per-claim independent, so apply it within each case to keep the by-case grouping.
    b5 = [apply_decision(cp, b5_decision) for cp in b5_raw] if b5_decision else b5_raw
    return {"B1": b1, "B2": b2, "B3": b3, "B4": b4, "B5": b5, "B5_raw": b5_raw}


def _fake_agent(prompt):  # dry-run: deterministic, no API
    return {"verdict": "inconsistent", "evidence_span": "L1:x->y", "confidence": 0.5}


def _save_maintable(out: dict, fake) -> Path:
    """Write the main table, MERGING into any existing same-corpus table. Called after EVERY
    backbone (not just at the end) so an unattended run that dies mid-matrix still keeps the
    backbones it already finished. Merge is idempotent: out['backbones'] accumulates in-process and
    re-merging the on-disk entries is a no-op; a different corpus on disk overwrites, not merges."""
    dest = Path(f"outputs/experiments/veritasbench/b1b5_maintable{'_fake' if fake else ''}.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    merged = out
    if dest.exists():
        prev = json.loads(dest.read_text(encoding="utf-8"))
        if prev.get("corpus", {}).get("test_cases") == out["corpus"]["test_cases"]:
            merged = {**out, "backbones": {**prev.get("backbones", {}), **out["backbones"]}}
        else:
            _hb(f"[warn] existing {dest.name} has a different corpus -> overwriting, not merging")
    dest.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
    return dest


def main() -> int:
    render = _dispatch_render()
    art_v, prov_v = [l1_relationship_verifier()], [rep_recompute_verifier()]
    dev, test = _load_corpus()
    n_claims = sum(len(c.claims) for c in test)
    fake = os.environ.get("VBENCH_FAKE_AGENT")

    out = {"corpus": {"dev_cases": [c.case_id for c in dev], "test_cases": [c.case_id for c in test],
                      "n_test_claims": n_claims}, "alpha": ALPHA, "backbones": {}}

    # HARD GATE 1 (before ANY API call): scan every dev+test prompt for gold tokens AND failure-mode
    # hint words. The agent must NEVER be told the task is fraud/duplication detection — it infers
    # (in)consistency from data alone. A leak raises here and aborts, so no tainted numbers are spent.
    leak = _leak_scan(dev + test, render)
    Path("outputs/experiments/veritasbench").mkdir(parents=True, exist_ok=True)
    Path("outputs/experiments/veritasbench/b1b5_leak_guard.json").write_text(
        json.dumps(leak, ensure_ascii=False, indent=2))
    _hb(f"[leak-guard] {leak['prompts_scanned']} prompts scanned, gold_leak_free + task_hint_free OK")

    backbones = ["fake"] if fake else BACKBONES
    for bb in backbones:
        t_bb = time.time()
        _hb(f"=== backbone {bb} start ({len(dev)} dev + {len(test)} test cases) ===")
        agent = _fake_agent if fake else make_json_agent(make_backbone(bb, max_tokens=MAX_TOKENS), system=AUDITOR_SYSTEM)
        # calibrate B5 decision on DEV (dual-layer predictions), FAR<=alpha
        _hb(f"[{bb}] calibrating B5 decision on {len(dev)} dev cases...")
        dev_b5 = _flat([run_dual_layer_gear(c, _timed(agent, f"{bb} dev"), art_v, prov_v, render=render)
                        for c in dev])
        decision = fit_decision(dev_b5, alpha=ALPHA)
        gears = _run_gears(test, agent, render, art_v, prov_v, decision, bb=bb)
        _hb(f"=== backbone {bb} done in {time.time() - t_bb:.0f}s ===")
        # each gears[g] is BY CASE (list[list]); _flat for point metrics, keep grouping for CI.
        out["backbones"][bb] = {
            "tiers": {g: _row(_flat(gears[g])) for g in ("B1", "B2", "B3", "B4", "B5")},
            # paper-level 95% bootstrap CI (resample cases) on the two headline metrics per tier
            "ci95": {g: {"claim_f1": _bootstrap_ci(gears[g], "claim_f1"),
                         "far": _bootstrap_ci(gears[g], "far")}
                     for g in ("B1", "B3", "B5")},
            "risk_coverage_B5": risk_coverage_curve(_flat(gears["B5_raw"]))[:8],
            "decision": {"flag_threshold": round(decision.flag_threshold, 4),
                         "abstain_threshold": round(decision.abstain_threshold, 4)},
        }
        # retain raw per-claim predictions (by case, by gear) so any future rubric can re-score
        # WITHOUT re-calling the model — mirrors the eval loop's trace-retention requirement.
        preds_dir = Path("outputs/experiments/veritasbench/b1b5_predictions")
        preds_dir.mkdir(parents=True, exist_ok=True)
        (preds_dir / f"{bb}.json").write_text(json.dumps(
            {"corpus": out["corpus"], "alpha": ALPHA,
             "predictions": {g: [[asdict(p) for p in case] for case in gears[g]]
                             for g in ("B1", "B2", "B3", "B4", "B5", "B5_raw")}},
            ensure_ascii=False))
        print(f"[{bb}] B1 FAR={out['backbones'][bb]['tiers']['B1']['far']} "
              f"B5 FAR={out['backbones'][bb]['tiers']['B5']['far']} "
              f"B5 F1={out['backbones'][bb]['tiers']['B5']['claim_f1']}")
        # incremental save: crash-safe for long unattended runs (keeps finished backbones)
        dest = _save_maintable(out, fake)
        _hb(f"[{bb}] saved -> {dest.name} (backbones so far: {list(out['backbones'])})")

    dest = _save_maintable(out, fake)
    print(f"-> {dest}  (backbones={list(out['backbones'])}, test claims={n_claims}, "
          f"dev={len(dev)} cases, test={len(test)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
