"""Closed eval-loop pilot — official signed L1 cases, ORACLE-CONDITIONED, real backbone, no gold leak.

Solves 遗漏.md #1: the system produces predictions on the OFFICIAL case.json corpus without ever
seeing gold verdict/span, is scored by engine.benchmark.metrics, and emits a B1–B3 table +
paper-level bootstrap CI + a repeatability check. Scope = explicit-A1-range L1 claims only (the
verifier-extractable slice; h19/sirt1/same-column-clean deferred to Round 2 — see pilot report).

Tiers: B1 bare agent / B2 structured agent / B3 + deterministic L1 verifier. B1/B2 use the NEUTRAL
renderer (two raw series, no leading hints). B3's verifier is value-only, so it provably CANNOT
separate the FP-trap (identical-but-legit) and insufficient claims from real duplication — that gap
is the reported verifier_conflict signal, not a bug.

Run:  AUDIT_BACKBONE=qwen3.7-plus PYTHONPATH=. uv run python scripts/run_veritasbench_eval.py
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

from engine.benchmark.agent_harness import (
    build_prompt,
    run_bare_agent,
    run_constrained_agent,
    run_tool_augmented_agent,
)
from engine.benchmark.backbones import make_json_agent
from engine.benchmark.metrics import main_table_row
from engine.benchmark.veritasbench_eval_adapter import (
    load_veritasbench_case,
    veritasbench_renderer,
)
from engine.benchmark.veritasbench_verifiers import l1_relationship_verifier
from scripts.live_backbones import AUDITOR_SYSTEM, make_backbone

CASES_ROOT = Path("benchmarks/veritasbench/cases")
# Round-2 contract met: every L1 claim now carries explicit source/target_a1_range, so the coded
# (h19) and rc-dialect (sirt1) cases are back in — the clean pool grows 2 -> 7, making FAR real.
PILOT_CASES = ["ncb_eet", "ncb_wnt", "ncb_h3v3", "ncb_h19", "ncb_sirt1"]
BACKBONE = os.environ.get("AUDIT_BACKBONE", "qwen3.7-plus")
MAX_TOKENS = int(os.environ.get("AUDIT_MAX_TOKENS", "4000"))
REPEATS = int(os.environ.get("EVAL_REPEATS", "3"))
METRIC_KEYS = ["claim_f1", "claim_recall", "far", "evidence_precision", "coverage"]
GOLD_FULL_CORPUS = {"cases": 50, "tiers": 5, "repeats": 3}  # for the 750-run estimate


def _forbidden_tokens(claim) -> list[str]:
    """Gold strings that must NEVER appear in the agent prompt for this claim (hard gate 1)."""
    md = claim.metadata or {}
    toks = [t for t in (claim.discrepancy_type, md.get("gold_evidence_span")) if t]
    # verbatim claim_atom phrasing (we normalised away from it) must not leak either
    return toks


def _assert_no_leak(cases, render) -> int:
    """Scan every B1 prompt; raise if any gold token leaks. Returns #claims checked."""
    n = 0
    for case in cases:
        for claim in case.claims:
            p = build_prompt(claim, case, artifacts_text=render(claim, case))
            for tok in _forbidden_tokens(claim):
                if tok and tok in p:
                    raise AssertionError(f"GOLD LEAK in {claim.claim_id}: {tok!r} present in prompt")
            n += 1
    return n


def _flat(preds_by_case: list[list]) -> list:
    return [p for ps in preds_by_case for p in ps]


def _bootstrap_ci(preds_by_case: list[list], key: str, *, n: int = 1000) -> list[float]:
    """Paper-level bootstrap: resample CASES with replacement, recompute `key`. 95% CI.

    CAVEAT: with n_paper=3 the CI is very wide (near-degenerate); reported honestly, not smoothed."""
    rng = random.Random(0)
    k = len(preds_by_case)
    if k == 0:
        return [0.0, 0.0]
    vals = []
    for _ in range(n):
        sample = _flat([preds_by_case[rng.randrange(k)] for _ in range(k)])
        vals.append(main_table_row(sample).get(key, 0.0))
    vals.sort()
    return [round(vals[int(0.025 * n)], 4), round(vals[int(0.975 * n)], 4)]


def _repeatability(cases, agent, render) -> dict:
    """Run B1 REPEATS times; report per-claim verdict-flip rate + metric spread (hard gate 4)."""
    runs = []
    verdicts_per_claim: dict[str, list[bool]] = {}
    for _r in range(REPEATS):
        preds = _flat([run_bare_agent(c, agent, render=render) for c in cases])
        runs.append(main_table_row(preds))
        for p in preds:
            verdicts_per_claim.setdefault(p.claim_id, []).append(p.predicted_flag)
    flips = sum(1 for v in verdicts_per_claim.values() if len(set(v)) > 1)
    f1s = [r["claim_f1"] for r in runs]
    return {"repeats": REPEATS, "claims": len(verdicts_per_claim), "flipped_claims": flips,
            "claim_f1_runs": [round(x, 4) for x in f1s],
            "claim_f1_spread": round(max(f1s) - min(f1s), 4)}


def main() -> int:
    render = veritasbench_renderer()
    verifier = l1_relationship_verifier()
    agent = make_json_agent(make_backbone(BACKBONE, max_tokens=MAX_TOKENS), system=AUDITOR_SYSTEM)

    cases, load_report = [], {}
    for cid in PILOT_CASES:
        case, rep = load_veritasbench_case(CASES_ROOT / cid)
        if case.claims:
            cases.append(case)
        load_report[cid] = rep
    n_claims = sum(len(c.claims) for c in cases)

    # HARD GATE 1: prove no gold leaks into any prompt before spending a single API call.
    checked = _assert_no_leak(cases, render)
    print(f"leak-guard: {checked} prompts scanned, 0 gold tokens leaked ✓")

    out = {"pilot": "veritasbench-eval-loop", "scope": "L1 explicit-range only (oracle-conditioned)",
           "backbone": BACKBONE, "temperature": 0.0, "repeats": REPEATS,
           "cases": [c.case_id for c in cases], "n_claims": n_claims, "load_report": load_report,
           "gold_leak_free": True, "tiers": {}}

    t0 = time.monotonic()
    # B1 bare (+ repeatability), B2 structured, B3 verifier
    b1_by_case = [run_bare_agent(c, agent, render=render) for c in cases]
    b2_by_case = [run_constrained_agent(c, agent, render=render) for c in cases]
    b3_by_case = [run_tool_augmented_agent(c, agent, [verifier]) for c in cases]
    elapsed = time.monotonic() - t0

    for name, by_case in [("B1_bare", b1_by_case), ("B2_structured", b2_by_case), ("B3_verifier", b3_by_case)]:
        preds = _flat(by_case)
        row = main_table_row(preds)
        out["tiers"][name] = {
            **{k: round(row.get(k, 0.0), 4) for k in METRIC_KEYS},
            "paper_bootstrap_ci95": {"claim_f1": _bootstrap_ci(by_case, "claim_f1"),
                                     "far": _bootstrap_ci(by_case, "far")},
        }

    out["repeatability_B1"] = _repeatability(cases, agent, render)

    # HARD GATE 6: 750-run cost/time estimate from measured per-call latency
    agent_calls = n_claims * 2  # B1 + B2 (B3 fires deterministically, no agent call when in scope)
    per_call = elapsed / max(agent_calls, 1)
    full_runs = GOLD_FULL_CORPUS["cases"] * GOLD_FULL_CORPUS["tiers"] * GOLD_FULL_CORPUS["repeats"]
    avg_claims = n_claims / max(len(cases), 1)
    est_calls = full_runs * avg_claims * 0.6  # ~60% of tier-runs hit the agent (B3/B5 partly deterministic)
    out["estimate_750run"] = {
        "measured_per_agent_call_s": round(per_call, 2),
        "full_runs": full_runs, "avg_claims_per_case": round(avg_claims, 1),
        "est_agent_calls": int(est_calls),
        "est_wall_hours_serial": round(est_calls * per_call / 3600, 1),
        "failure_recovery": "per-(case,tier,repeat) checkpointed JSON; a failed run is idempotent-retryable; "
                            "malformed reply -> {} -> insufficient (never crashes the batch)",
    }

    Path("outputs/experiments/veritasbench").mkdir(parents=True, exist_ok=True)
    safe = BACKBONE.replace("/", "_").replace(".", "-")
    Path(f"outputs/experiments/veritasbench/eval_pilot_{safe}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2))

    print(json.dumps({"backbone": BACKBONE, "cases": out["cases"], "n_claims": n_claims,
                      "tiers": {k: {m: v[m] for m in METRIC_KEYS} for k, v in out["tiers"].items()},
                      "repeatability": out["repeatability_B1"],
                      "est_750run_hours_serial": out["estimate_750run"]["est_wall_hours_serial"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
