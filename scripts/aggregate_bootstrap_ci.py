"""Task① — paper-clustered bootstrap CI from the FROZEN b1b5 predictions (NO backbone re-run).

The manuscript setup promises "95% bootstrap intervals resampled by case (paper-clustered)", but
tab:main-results / tab:ablation-results carry no CI. This closes that gap by aggregating the frozen
per-claim predictions only — the exact predictions the published point estimates came from — so the
CIs are guaranteed consistent with the reported points, and no model is called.

Resample unit = CASE (paper). Reuses `run_veritasbench_eval._bootstrap_ci` verbatim (seed=0, B=1000,
resample cases with replacement, recompute the metric via `main_table_row`) so the CI method is
identical to the one the main-table builder already uses for claim_f1/far — this run just extends it
to every gear B1-B5 and adds the third headline metric Recall@FAR<=0.05.

Run:  PYTHONPATH=. uv run python scripts/aggregate_bootstrap_ci.py
Out:  benchmarks/veritasbench/suites/b1b5_bootstrap_ci.json
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.benchmark.metrics import ClaimPrediction, main_table_row
from scripts.run_veritasbench_eval import _bootstrap_ci

PREDS_DIR = Path("outputs/experiments/veritasbench/b1b5_predictions")
OUT = Path("benchmarks/veritasbench/suites/b1b5_bootstrap_ci.json")
BACKBONES = ("qwen3.7-plus", "deepseek-v4-pro", "glm-5.2")
GEARS = ("B1", "B2", "B3", "B4", "B5")
# (json key in main_table_row, label used in the manuscript / delivery)
METRICS = (("far", "far"), ("claim_f1", "claim_f1"), ("recall_at_far<=0.05", "recall_at_far<=0.05"))
B = 1000
SEED = 0  # _bootstrap_ci hard-codes Random(0); recorded here for the artifact contract


def _rebuild_by_case(gear_preds: list[list[dict]]) -> list[list[ClaimPrediction]]:
    """Frozen JSON (asdict) -> ClaimPrediction, keeping the by-case grouping for paper clustering."""
    return [[ClaimPrediction(**d) for d in case] for case in gear_preds]


def main() -> int:
    rows: list[dict] = []
    n_test_cases = 0
    for bb in BACKBONES:
        doc = json.loads((PREDS_DIR / f"{bb}.json").read_text(encoding="utf-8"))
        preds = doc["predictions"]
        n_test_cases = len(preds["B1"])  # cases are the paper-clustering unit
        for gear in GEARS:
            by_case = _rebuild_by_case(preds[gear])
            for key, label in METRICS:
                lo, hi = _bootstrap_ci(by_case, key, n=B)
                # point estimate = the metric on the full (un-resampled) corpus
                point = round(main_table_row([p for c in by_case for p in c]).get(key, 0.0), 4)
                rows.append({"backbone": bb, "config": gear, "metric": label,
                             "point": point, "ci_lo": lo, "ci_hi": hi,
                             "B": B, "seed": SEED, "resample_unit": "paper"})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "_doc": "Paper-clustered bootstrap 95% CI from FROZEN b1b5 predictions (no re-run). "
                "Resample unit = case/paper; B=1000; seed=0; recompute via main_table_row.",
        "resample_unit": "paper", "B": B, "seed": SEED,
        "n_test_cases": n_test_cases,
        "backbones": list(BACKBONES), "gears": list(GEARS),
        "metrics": [m[1] for m in METRICS], "rows": rows,
    }, ensure_ascii=False, indent=2))
    # console: the headline B1/B3/B5 far + f1 + recall, so a partial/wrong run is visibly wrong
    for r in rows:
        if r["config"] in ("B1", "B3", "B5"):
            print(f"{r['backbone']:16s} {r['config']} {r['metric']:20s} "
                  f"{r['point']:.4f}  [{r['ci_lo']}, {r['ci_hi']}]")
    print(f"\n{len(rows)} rows -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
