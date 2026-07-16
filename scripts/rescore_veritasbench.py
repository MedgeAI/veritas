"""Re-score a retained eval run from its trace.jsonl — ZERO model calls.

Proves the trace-retention guarantee: every run's job dir keeps the verbatim raw model response +
gold per claim, so ANY future rubric can be scored directly from the trace, and the exact submission
numbers can be regenerated, without ever re-running the model.

  * `--list`                 index every retained run (family, backbone, tag, n_claims, when)
  * `--job <dir>`            re-score one run under `--rubric` (default reproduces result.json)
  * `--rubric default|conf_gated`  pluggable scoring — swap the rubric, re-score from the SAME trace

`default` reconstructs the original scoring (its metrics must match the run's result.json — the
fidelity check). `conf_gated` is a DIFFERENT rubric derived from the retained parsed verdict +
confidence, demonstrating a rubric change needs no re-run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.benchmark.metrics import ClaimPrediction, main_table_row
from engine.benchmark.schema import LABEL_CLEAN, LABEL_DIRTY

JOBS_ROOT = Path("outputs/experiments/veritasbench/eval_jobs")
METRIC_KEYS = ["claim_f1", "claim_recall", "far", "evidence_precision", "coverage"]


def _gt(pkt: dict) -> str:
    return LABEL_DIRTY if pkt["gold"]["label"] == "dirty" else LABEL_CLEAN


def default_rubric(pkt: dict) -> ClaimPrediction:
    """Reconstruct the ORIGINAL scored prediction from the retained trace (fidelity check)."""
    s = pkt["scored"]
    return ClaimPrediction(pkt["claim_id"], _gt(pkt), bool(s["predicted_flag"]),
                           float(s["dirtiness"]), bool(s["abstained"]), bool(s["evidence_correct"]))


def conf_gated_rubric(pkt: dict, thresh: float = 0.7) -> ClaimPrediction:
    """A DIFFERENT rubric, re-derived from the retained raw parse: only flag when the agent said
    'inconsistent' AND its confidence >= thresh. Verifier tiers keep their deterministic signal."""
    parsed, ver = pkt.get("parsed"), pkt.get("verifier")
    if ver is not None and parsed is None:  # deterministic verifier tier
        flag, abstained, conf = bool(ver["fired"]), False, float(ver.get("confidence", 1.0))
    else:
        parsed = parsed or {}
        verdict = str(parsed.get("verdict", "insufficient"))
        conf = float(parsed.get("confidence") or 0.0)
        flag = verdict == "inconsistent" and conf >= thresh
        abstained = verdict == "insufficient"
    return ClaimPrediction(pkt["claim_id"], _gt(pkt), flag, conf, abstained,
                           bool(pkt["scored"].get("evidence_correct", False)))


RUBRICS = {"default": default_rubric, "conf_gated": conf_gated_rubric}


def load_trace(job_dir: Path) -> list[dict]:
    return [json.loads(x) for x in (job_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def rescore(trace: list[dict], rubric) -> dict:
    """Group the MAIN-run packets (repeat 0) by tier and compute metrics from the trace alone."""
    by_tier: dict[str, list[ClaimPrediction]] = {}
    for pkt in trace:
        if pkt.get("repeat", 0) != 0:
            continue
        by_tier.setdefault(pkt["tier"], []).append(rubric(pkt))
    return {t: {k: round(main_table_row(ps).get(k, 0.0), 4) for k in METRIC_KEYS} for t, ps in by_tier.items()}


def _list_runs(root: Path) -> list[dict]:
    runs = []
    for cfg in sorted(root.glob("*/config.json")):
        c = json.loads(cfg.read_text(encoding="utf-8"))
        runs.append({"job": cfg.parent.name, "family": c.get("family"), "backbone": c.get("backbone"),
                     "tag": c.get("run_tag"), "n_claims": c.get("n_claims"), "created_at": c.get("created_at")})
    return runs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Re-score a retained eval run from its trace (no model calls).")
    ap.add_argument("--job", type=Path, help="a job dir under eval_jobs/")
    ap.add_argument("--list", action="store_true", help="index all retained runs")
    ap.add_argument("--rubric", choices=list(RUBRICS), default="default")
    ap.add_argument("--jobs-root", type=Path, default=JOBS_ROOT)
    args = ap.parse_args(argv)

    if args.list or not args.job:
        for r in _list_runs(args.jobs_root):
            print(f"  {r['job']:40} claims={r['n_claims']} {r['created_at']}")
        return 0

    trace = load_trace(args.job)
    metrics = rescore(trace, RUBRICS[args.rubric])
    print(json.dumps({"job": args.job.name, "rubric": args.rubric, "packets": len(trace),
                      "model_calls": 0, "tiers": metrics}, ensure_ascii=False, indent=2))

    # fidelity: default rubric must reproduce the stored result.json
    res = args.job / "result.json"
    if args.rubric == "default" and res.is_file():
        stored = json.loads(res.read_text(encoding="utf-8")).get("tiers", {})
        drift = {t: {k: (metrics[t][k], round(stored[t][k], 4)) for k in METRIC_KEYS
                     if t in stored and abs(metrics[t][k] - round(stored[t].get(k, 0.0), 4)) > 1e-9}
                 for t in metrics}
        drift = {t: d for t, d in drift.items() if d}
        print("fidelity vs result.json:", "MATCH ✓" if not drift else f"DRIFT {drift}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
