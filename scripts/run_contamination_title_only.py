"""Task② — title-only contamination ablation (memorization probe).

threats.tex §contamination promises a title-only comparison as the first line of defence against
training-set memorization, but never reports the numbers. This runs it.

DESIGN — the contrast is on the AGENT tier (B1 bare), NOT B3+:
  memorization is a property of the LLM, not of the deterministic verifier. B3's verifier does exact
  math on the two value series; strip the series and it has nothing to operate on. So the clean probe
  is "same bare LLM, only the artifact context changes":
    * full     : the agent sees the real source-data series (the standard B1 neutral renderer).
    * title_only: the agent sees ONLY the paper title (+ the neutral claim). No source data, no
                  series, no numbers. Everything else in the pipeline is identical.
  Both arms run in ONE process with ONE agent instance, so the ONLY variable is the artifact context
  (no run-to-run / instance confound with the frozen main-table B1).

READ-OUT (write into threats):
  * title_only FAR/F1 MUCH LOWER than full  -> the model relies on the artifact, not memory ->
    contamination does not explain our results.
  * title_only ~= full                       -> danger signal; report honestly.

Gold is never shown (same leak-guard as the main loop). No main-table file is touched.

Run:  AUDIT_BACKBONE=qwen3.7-plus EVAL_ALL=1 PYTHONPATH=. uv run python scripts/run_contamination_title_only.py
Dry:  VBENCH_FAKE_AGENT=1 EVAL_ALL=1 PYTHONPATH=. uv run python scripts/run_contamination_title_only.py
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from engine.benchmark.agent_harness import run_bare_agent
from engine.benchmark.backbones import make_json_agent
from engine.benchmark.metrics import main_table_row
from scripts.live_backbones import AUDITOR_SYSTEM, make_backbone
from scripts.run_veritasbench_b1b5 import (
    _bootstrap_ci,
    _dispatch_render,
    _fake_agent,
    _hb,
    _leak_scan,
    _load_corpus,
    _timed,
)

BACKBONE = os.environ.get("AUDIT_BACKBONE", "qwen3.7-plus")
MAX_TOKENS = int(os.environ.get("AUDIT_MAX_TOKENS", "4000"))
ALPHA = float(os.environ.get("EVAL_ALPHA", "0.05"))
OUT = Path("benchmarks/veritasbench/suites/contamination_title_only.json")
METRIC_KEYS = ["claim_f1", "far", f"recall_at_far<={ALPHA:g}", "claim_recall", "coverage"]


def _title_only_renderer():
    """Artifact context = the paper title ONLY. No source data, no series, no numeric loci.

    The claim text itself is oracle-safe (it names the two loci in neutral prose but carries NO
    values); with the series removed, the agent can only fall back on prior knowledge of the paper —
    which is exactly the memorization signal we want to isolate."""
    def render(_claim, case) -> str:
        title = case.title or case.base_paper_id or case.case_id
        return f"(source data withheld for this condition)\nPAPER TITLE: {title}"
    return render


def _retracted_stratum(case) -> str:
    """Best-effort retracted/non-retracted tag from case metadata, for the optional stratification.
    Unknown -> 'unknown' (never guess); the main contrast does not depend on this."""
    md = getattr(case, "metadata", None) or {}
    v = md.get("retracted")
    if v is True:
        return "retracted"
    if v is False:
        return "non_retracted"
    return "unknown"


def _row(by_case) -> dict:
    preds = [p for ps in by_case for p in ps]
    r = main_table_row(preds, alpha=ALPHA)
    out = {k: round(r.get(k, 0.0), 4) for k in METRIC_KEYS}
    out["n_claims"] = len(preds)
    out["ci95"] = {"far": _bootstrap_ci(by_case, "far"),
                   "claim_f1": _bootstrap_ci(by_case, "claim_f1")}
    return out


def main() -> int:
    fake = os.environ.get("VBENCH_FAKE_AGENT")
    _dev, test = _load_corpus()
    n_claims = sum(len(c.claims) for c in test)
    _hb(f"[contamination] backbone={BACKBONE} test_cases={len(test)} claims={n_claims} fake={bool(fake)}")

    full_render = _dispatch_render()
    title_render = _title_only_renderer()

    # HARD GATE 1 (both arms): prove no gold leaks before spending an API call.
    for tag, r in (("full", full_render), ("title_only", title_render)):
        _leak_scan(test, r)
    _hb("[contamination] leak-guard passed for both arms ✓")

    agent = _fake_agent if fake else make_json_agent(
        make_backbone(BACKBONE, max_tokens=MAX_TOKENS), system=AUDITOR_SYSTEM)

    t0 = time.time()
    arms: dict = {}
    for tag, render in (("full", full_render), ("title_only", title_render)):
        by_case = [run_bare_agent(c, _timed(agent, f"{BACKBONE} {tag}"), render=render) for c in test]
        arms[tag] = _row(by_case)
        _hb(f"[contamination] arm={tag} done: FAR={arms[tag]['far']} F1={arms[tag]['claim_f1']} "
            f"recall@far={arms[tag][f'recall_at_far<={ALPHA:g}']}")

    delta = {k: round(arms["full"][k] - arms["title_only"][k], 4)
             for k in ("far", "claim_f1", f"recall_at_far<={ALPHA:g}")}
    verdict = ("title_only far below full -> results rely on artifacts, not memorization"
               if delta["claim_f1"] > 0.1 or delta["far"] > 0.05
               else "title_only comparable to full -> possible memorization, report honestly")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "_doc": "Title-only contamination ablation. Contrast is on B1 bare (memorization is an LLM "
                "property; B3+ verifier operates on series that title-only removes). Same agent, one "
                "process; only artifact context differs.",
        "backbone": BACKBONE, "alpha": ALPHA, "n_test_cases": len(test), "n_claims": n_claims,
        "elapsed_s": round(time.time() - t0, 1), "fake": bool(fake),
        "conditions": {
            "full": {"tier": "B1_bare", "artifact": "real source-data series", **arms["full"]},
            "title_only": {"tier": "B1_bare", "artifact": "paper title only, source data withheld",
                           **arms["title_only"]},
        },
        "delta_full_minus_title": delta, "readout": verdict,
    }, ensure_ascii=False, indent=2))

    print(json.dumps({"backbone": BACKBONE, "full": arms["full"], "title_only": arms["title_only"],
                      "delta": delta, "readout": verdict, "out": str(OUT)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
