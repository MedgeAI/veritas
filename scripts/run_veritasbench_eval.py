"""Closed eval-loop pilot — official signed L1 cases, ORACLE-CONDITIONED, real backbone, no gold leak.

Solves 遗漏.md #1: the system produces predictions on the OFFICIAL case.json corpus without ever
seeing gold verdict/span, is scored by engine.benchmark.metrics, and emits a B1–B3 table +
paper-level bootstrap CI + a repeatability check. Scope = explicit-A1-range L1 claims only (the
verifier-extractable slice; h19/sirt1/same-column-clean returned via the Round-2 range contract).

Tiers: B1 bare agent / B2 structured agent / B3 + deterministic L1 verifier. B1/B2 use the NEUTRAL
renderer (two raw series, no leading hints). B3's verifier is value-only, so it provably CANNOT
separate the FP-trap (identical-but-legit) and insufficient claims from real duplication — that gap
is the reported verifier_conflict signal, not a bug.

RETENTION (mirrors medge-bench/jobs/{task}-{model}-{version}/): every run writes a self-contained
job dir under outputs/experiments/veritasbench/eval_jobs/{backbone}__{tag}/ with
  config.json      — reproducible invocation (backbone, tiers, temp, max_tokens, cases, git sha, ts)
  result.json      — scored metrics + CI + repeatability + token totals + timestamps + estimate
  trace.jsonl      — ONE evidence packet per (tier, repeat, claim): the exact neutral prompt the
                     agent saw, its raw response, the parsed decision, the scored prediction, the
                     gold fields (audit-only) and the B3 verifier signal
  leak_guard.json  — hard-gate-1 proof: per-claim forbidden-token scan
  run.log          — console log

Run:  AUDIT_BACKBONE=qwen3.7-plus EVAL_RUN_TAG=v1 PYTHONPATH=. uv run python scripts/run_veritasbench_eval.py
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from engine.benchmark.agent_harness import (
    build_prompt,
    parse_decision,
    run_bare_agent,
    run_constrained_agent,
    run_tool_augmented_agent,
)
from engine.benchmark.backbones import extract_json, make_json_agent
from engine.benchmark.metrics import main_table_row
from engine.benchmark.schema import LABEL_DIRTY
from engine.benchmark.veritasbench_eval_adapter import (
    load_veritasbench_case,
    veritasbench_renderer,
)
from engine.benchmark.veritasbench_rep_adapter import (
    load_rep_case,
    rep_recompute_verifier,
    rep_renderer,
)
from engine.benchmark.veritasbench_verifiers import l1_relationship_verifier
from scripts.live_backbones import AUDITOR_SYSTEM, make_backbone

CASES_ROOT = Path("benchmarks/veritasbench/cases")
# Two families share one loop: ncb_ = duplication (recall axis, l1_relationship verifier); rep_ =
# reproduction / honest-FP (FAR + abstention axis, recompute verifier). FAMILY env selects.
FAMILIES = {
    "ncb": {"cases": ["ncb_eet", "ncb_wnt", "ncb_h3v3", "ncb_h19", "ncb_sirt1"],
            "load": load_veritasbench_case, "render": veritasbench_renderer,
            "verifier": l1_relationship_verifier},
    "rep": {"cases": ["rep_pbc_surv", "rep_coexpr", "rep_mediator", "rep_winnerscurse", "rep_triangulation"],
            "load": load_rep_case, "render": rep_renderer, "verifier": rep_recompute_verifier},
}
FAMILY = os.environ.get("EVAL_FAMILY", "ncb")
BACKBONE = os.environ.get("AUDIT_BACKBONE", "qwen3.7-plus")
RUN_TAG = os.environ.get("EVAL_RUN_TAG", "v1")
MAX_TOKENS = int(os.environ.get("AUDIT_MAX_TOKENS", "4000"))
REPEATS = int(os.environ.get("EVAL_REPEATS", "3"))
METRIC_KEYS = ["claim_f1", "claim_recall", "far", "evidence_precision", "coverage"]
GOLD_FULL_CORPUS = {"cases": 50, "tiers": 5, "repeats": 3}  # for the 750-run estimate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None


class TracingModelCall:
    """Wrap a ModelCall to record the exact (prompt, raw text) of every call, in order.

    make_json_agent applies extract_json and drops the raw text; we capture it here so the trace
    keeps the verbatim model output. Call order == flat claim order for B1/B2 (one call per claim)."""

    def __init__(self, base):
        self.base = base
        self.records: list[dict] = []

    def __call__(self, prompt: str) -> str:
        raw = self.base(prompt)
        self.records.append({"prompt": prompt, "raw": raw})
        return raw

    def reset(self) -> None:
        self.records = []


# Failure-mode hint words that must NOT appear in any prompt: telling the agent to look for
# duplication/fraud would leak the task. It must infer "identical values contradict independence".
HINT_WORDS = ("suspicious", "duplicat", "fabricat", "fraud", "copied", "tamper",
              "exact relationship", "exact match", "offset", "identical")


def _forbidden_tokens(claim) -> list[str]:
    """Gold strings that must NEVER appear in the agent prompt for this claim (hard gate 1)."""
    md = claim.metadata or {}
    return [t for t in (claim.discrepancy_type, md.get("gold_evidence_span")) if t]


def _leak_scan(cases, render) -> dict:
    """Scan every prompt for (a) gold tokens and (b) failure-mode hint words; proof, raises on leak."""
    per_claim = []
    for case in cases:
        for claim in case.claims:
            p = build_prompt(claim, case, artifacts_text=render(claim, case))
            leaked = [t for t in _forbidden_tokens(claim) if t and t in p]
            hints = [w for w in HINT_WORDS if w in p.lower()]
            if leaked:
                raise AssertionError(f"GOLD LEAK in {claim.claim_id}: {leaked}")
            if hints:
                raise AssertionError(f"TASK-HINT LEAK in {claim.claim_id}: {hints} (prompt names the failure mode)")
            per_claim.append({"claim_id": claim.claim_id,
                              "forbidden_checked": _forbidden_tokens(claim), "leaked": leaked, "hints": hints})
    return {"prompts_scanned": len(per_claim), "gold_leak_free": True,
            "task_hint_free": True, "hint_words_checked": list(HINT_WORDS), "per_claim": per_claim}


def _flat(preds_by_case: list[list]) -> list:
    return [p for ps in preds_by_case for p in ps]


def _flat_claims(cases) -> list:
    return [(c, cl) for c in cases for cl in c.claims]


def _gold(claim) -> dict:
    """Gold fields — recorded in the trace for AUDIT ONLY (never fed to the agent)."""
    md = claim.metadata or {}
    return {"verdict": claim.verdict, "label": "dirty" if claim.label == LABEL_DIRTY else "clean",
            "evidence_span": claim.evidence_span, "gold_evidence_span_raw": md.get("gold_evidence_span"),
            "discrepancy_type": claim.discrepancy_type}


def _trace_agent_tier(cases, preds_by_case, records, tier, *, repeat=0) -> list[dict]:
    """Evidence packets for an agent tier (B1/B2): join claims, predictions and captured raw text."""
    lines = []
    for (case, claim), pred, rec in zip(_flat_claims(cases), _flat(preds_by_case), records):
        dec = parse_decision(extract_json(rec["raw"]))
        lines.append({
            "tier": tier, "repeat": repeat, "case_id": case.case_id, "claim_id": claim.claim_id,
            "gold": _gold(claim),
            "input": {"neutral_prompt": rec["prompt"],
                      "src_series": (claim.metadata or {}).get("src_series"),
                      "tgt_series": (claim.metadata or {}).get("tgt_series")},
            "output": {"raw_response": rec["raw"]},
            "parsed": {"verdict": dec.verdict, "evidence_span": dec.evidence_span,
                       "confidence": dec.confidence, "rationale": dec.rationale},
            "scored": {"predicted_flag": pred.predicted_flag, "abstained": pred.abstained,
                       "evidence_correct": pred.evidence_correct, "dirtiness": pred.confidence},
            "verifier": None,
        })
    return lines


def _trace_verifier_tier(cases, preds_by_case, verifier, tier) -> list[dict]:
    """Evidence packets for B3: deterministic verifier signal per claim (no agent call)."""
    lines = []
    for (case, claim), pred in zip(_flat_claims(cases), _flat(preds_by_case)):
        sig = verifier(claim, case)
        lines.append({
            "tier": tier, "repeat": 0, "case_id": case.case_id, "claim_id": claim.claim_id,
            "gold": _gold(claim),
            "input": {"neutral_prompt": None,
                      "src_series": (claim.metadata or {}).get("src_series"),
                      "tgt_series": (claim.metadata or {}).get("tgt_series")},
            "output": {"raw_response": None},
            "parsed": None,
            "scored": {"predicted_flag": pred.predicted_flag, "abstained": pred.abstained,
                       "evidence_correct": pred.evidence_correct, "dirtiness": pred.confidence},
            "verifier": {"fired": sig.fired, "evidence_span": sig.evidence_span,
                         "confidence": sig.confidence} if sig else None,
        })
    return lines


def _bootstrap_ci(preds_by_case: list[list], key: str, *, n: int = 1000) -> list[float]:
    """Paper-level bootstrap: resample CASES with replacement, recompute `key`. 95% CI.

    CAVEAT: with n_paper=5 the CI is very wide (near-degenerate); reported honestly, not smoothed."""
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


def _token_totals(sink: list[dict]) -> dict:
    return {"calls": len(sink),
            "prompt_tokens": sum((u.get("prompt_tokens") or 0) for u in sink),
            "completion_tokens": sum((u.get("completion_tokens") or 0) for u in sink),
            "total_tokens": sum((u.get("total_tokens") or 0) for u in sink)}


def main() -> int:
    fam = FAMILIES[FAMILY]
    render = fam["render"]()
    verifier = fam["verifier"]()
    usage_sink: list[dict] = []
    tracer = TracingModelCall(make_backbone(BACKBONE, max_tokens=MAX_TOKENS, usage_sink=usage_sink))
    agent = make_json_agent(tracer, system=AUDITOR_SYSTEM)

    job = Path(f"outputs/experiments/veritasbench/eval_jobs/"
               f"{FAMILY}__{BACKBONE.replace('/', '_').replace('.', '-')}__{RUN_TAG}")
    job.mkdir(parents=True, exist_ok=True)
    logs: list[str] = []

    def log(msg: str) -> None:
        logs.append(msg)
        print(msg)

    cases, load_report = [], {}
    for cid in fam["cases"]:
        case, rep = fam["load"](CASES_ROOT / cid)
        if case.claims:
            cases.append(case)
        load_report[cid] = rep
    n_claims = sum(len(c.claims) for c in cases)

    # HARD GATE 1: prove no gold leaks into any prompt before spending a single API call.
    leak = _leak_scan(cases, render)
    (job / "leak_guard.json").write_text(json.dumps(leak, ensure_ascii=False, indent=2))
    log(f"leak-guard: {leak['prompts_scanned']} prompts scanned, 0 gold tokens leaked ✓")

    started = _now()
    trace: list[dict] = []
    tokens_by_tier: dict[str, dict] = {}
    tiers_out: dict[str, dict] = {}

    t0 = time.monotonic()
    # ---- agent tiers: reset tracer+usage per tier so tokens/records are attributable ----
    for name, runner, prompt_kind in [("B1_bare", run_bare_agent, "bare"),
                                       ("B2_structured", run_constrained_agent, "constrained")]:
        tracer.reset()
        usage_sink.clear()
        by_case = [runner(c, agent, render=render) for c in cases]
        tokens_by_tier[name] = _token_totals(usage_sink)
        trace += _trace_agent_tier(cases, by_case, list(tracer.records), name)
        row = main_table_row(_flat(by_case))
        tiers_out[name] = {**{k: round(row.get(k, 0.0), 4) for k in METRIC_KEYS},
                           "paper_bootstrap_ci95": {"claim_f1": _bootstrap_ci(by_case, "claim_f1"),
                                                    "far": _bootstrap_ci(by_case, "far")}}

    # ---- B3 verifier tier: deterministic, no agent call ----
    b3_by_case = [run_tool_augmented_agent(c, agent, [verifier]) for c in cases]
    trace += _trace_verifier_tier(cases, b3_by_case, verifier, "B3_verifier")
    row = main_table_row(_flat(b3_by_case))
    tiers_out["B3_verifier"] = {**{k: round(row.get(k, 0.0), 4) for k in METRIC_KEYS},
                                "paper_bootstrap_ci95": {"claim_f1": _bootstrap_ci(b3_by_case, "claim_f1"),
                                                         "far": _bootstrap_ci(b3_by_case, "far")}}
    elapsed = time.monotonic() - t0

    # ---- repeatability: B1 x REPEATS (each repeat's trace kept) ----
    rep_runs, verdicts_per_claim = [], {}
    for r in range(REPEATS):
        tracer.reset()
        by_case = [run_bare_agent(c, agent, render=render) for c in cases]
        trace += _trace_agent_tier(cases, by_case, list(tracer.records), "B1_bare", repeat=r + 1)
        preds = _flat(by_case)
        rep_runs.append(main_table_row(preds)["claim_f1"])
        for p in preds:
            verdicts_per_claim.setdefault(p.claim_id, []).append(p.predicted_flag)
    repeatability = {"repeats": REPEATS, "claims": len(verdicts_per_claim),
                     "flipped_claims": sum(1 for v in verdicts_per_claim.values() if len(set(v)) > 1),
                     "claim_f1_runs": [round(x, 4) for x in rep_runs],
                     "claim_f1_spread": round(max(rep_runs) - min(rep_runs), 4)}

    # HARD GATE 6: 750-run cost/time estimate from measured per-call latency + token totals
    agent_calls = n_claims * 2
    per_call = elapsed / max(agent_calls, 1)
    full_runs = GOLD_FULL_CORPUS["cases"] * GOLD_FULL_CORPUS["tiers"] * GOLD_FULL_CORPUS["repeats"]
    avg_claims = n_claims / max(len(cases), 1)
    est_calls = full_runs * avg_claims * 0.6
    tok_total = sum(t["total_tokens"] for t in tokens_by_tier.values())
    estimate = {"measured_per_agent_call_s": round(per_call, 2), "full_runs": full_runs,
                "avg_claims_per_case": round(avg_claims, 1), "est_agent_calls": int(est_calls),
                "est_wall_hours_serial": round(est_calls * per_call / 3600, 1),
                "pilot_total_tokens": tok_total,
                "est_total_tokens_750run": int(est_calls / max(agent_calls, 1) * tok_total)
                if agent_calls else None,
                "failure_recovery": "per-job checkpointed dir; a failed run is idempotent-retryable "
                                    "(same tag overwrites); malformed reply -> {} -> insufficient (never crashes)"}

    # ---- write the job dir (config / result / trace / log) ----
    scope = {"ncb": "L1 duplication (recall axis, recompute-free)",
             "rep": "L1 reproduction / honest-FP (FAR + abstention axis, recompute B3)"}[FAMILY]
    config = {"job_name": job.name, "backbone": BACKBONE, "run_tag": RUN_TAG, "family": FAMILY,
              "pilot": "veritasbench-eval-loop", "scope": scope,
              "tiers": list(tiers_out.keys()), "temperature": 0.0, "max_tokens": MAX_TOKENS,
              "repeats": REPEATS, "cases": [c.case_id for c in cases], "n_claims": n_claims,
              "renderer": "neutral (values only, no leading hints)",
              "gold_fields_withheld": ["verdict", "discrepancy_type", "is_clean_claim", "gold_evidence_span"],
              "script": "scripts/run_veritasbench_eval.py", "git_sha": _git_sha(), "created_at": started}
    result = {"started_at": started, "finished_at": _now(), "elapsed_s": round(elapsed, 2),
              "backbone": BACKBONE, "n_claims": n_claims, "cases": [c.case_id for c in cases],
              "load_report": load_report, "gold_leak_free": True, "leak_prompts_scanned": leak["prompts_scanned"],
              "tiers": tiers_out, "repeatability_B1": repeatability,
              "tokens_by_tier": tokens_by_tier, "estimate_750run": estimate}

    (job / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2))
    (job / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    with (job / "trace.jsonl").open("w", encoding="utf-8") as f:
        for line in trace:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    # legacy flat summary (kept for existing readers)
    Path("outputs/experiments/veritasbench").mkdir(parents=True, exist_ok=True)
    Path(f"outputs/experiments/veritasbench/eval_pilot_{FAMILY}_{BACKBONE.replace('.', '-')}.json").write_text(
        json.dumps({"backbone": BACKBONE, "n_claims": n_claims, "cases": config["cases"],
                    "tiers": tiers_out, "repeatability_B1": repeatability,
                    "estimate_750run": estimate}, ensure_ascii=False, indent=2))

    log(f"trace: {len(trace)} evidence packets -> {job/'trace.jsonl'}")
    log(f"job dir: {job}")
    (job / "run.log").write_text("\n".join(logs) + "\n")
    print(json.dumps({"backbone": BACKBONE, "job": str(job), "n_claims": n_claims,
                      "tiers": {k: {m: v[m] for m in METRIC_KEYS} for k, v in tiers_out.items()},
                      "repeatability": repeatability, "trace_packets": len(trace),
                      "pilot_total_tokens": tok_total}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
