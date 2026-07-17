"""Emit the manuscript's §5 LaTeX table rows straight from b1b5_maintable.json.

The paper window should NOT hand-transcribe numbers (transcription errors + the numbers move as
runs complete). Instead: run the full B1-B5 matrix, then run this once to regenerate the exact rows
for `sections/experiments.tex`. Backbones not yet present in the table render as \\tbd{?} so the
partial state is visible rather than silently wrong. Percentages match the paper (FAR, Recall in %).

Maps to (see /Users/chaco/Downloads/manuscript/latex/sections/experiments.tex):
  * Table 1  tab:main-results     — Backbone x {Claim-F1 B1/B5, FAR B1/B5}
  * Table 2  tab:ablation-results — Config B1-B5 x {FAR per backbone, Recall@FAR<=alpha per backbone}
  * Fig 1    fig:risk-coverage    — B5 risk-coverage points per backbone (data dump for plotting)

Run:  PYTHONPATH=. uv run python scripts/maintable_to_latex.py [path/to/b1b5_maintable.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Director-decided backbone set + display names (NOT Opus; see the handoff doc).
BACKBONES = ["qwen3.7-plus", "deepseek-v4-pro", "glm-5.2"]
DISPLAY = {"qwen3.7-plus": "Qwen3.7-Plus", "deepseek-v4-pro": "DeepSeek-V4-Pro", "glm-5.2": "GLM-5.2"}
GEARS = ["B1", "B2", "B3", "B4", "B5"]
GEAR_LABEL = {"B1": "B1 (bare)", "B2": "B2 (protocol)", "B3": "B3 (+forensics)",
              "B4": "B4 (+verifiers)", "B5": "B5 (+decision)"}
TBD = r"\tbd{?}"


def _f1(tiers: dict, bb: str, gear: str) -> str:
    t = tiers.get(bb, {}).get(gear)
    return f"{t['claim_f1']:.3f}" if t else TBD


def _pct(tiers: dict, bb: str, gear: str, key: str) -> str:
    t = tiers.get(bb, {}).get(gear)
    if not t or key not in t:
        return TBD
    return f"{t[key] * 100:.1f}"


def _recall_key(doc: dict) -> str:
    """The recall metric key carries alpha (e.g. 'recall_at_far<=0.05'); find it generically."""
    for bb in doc.get("backbones", {}).values():
        for t in bb.get("tiers", {}).values():
            for k in t:
                if k.startswith("recall_at_far"):
                    return k
    return "recall_at_far<=0.05"


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "outputs/experiments/veritasbench/b1b5_maintable.json")
    doc = json.loads(src.read_text(encoding="utf-8"))
    tiers = {bb: v["tiers"] for bb, v in doc.get("backbones", {}).items()}
    rk = _recall_key(doc)
    present = [bb for bb in BACKBONES if bb in tiers]
    alpha = doc.get("alpha", 0.05)

    print(f"% ==== generated from {src} ====")
    print(f"% backbones present: {present or '(none)'} | alpha={alpha} | "
          f"test cases={len(doc.get('corpus', {}).get('test_cases', []))}")
    print()

    print("% ---- Table 1  tab:main-results (B1 vs B5) ----")
    for bb in BACKBONES:
        name = DISPLAY[bb]
        print(f"{name} & {_f1(tiers, bb, 'B1')} & {_f1(tiers, bb, 'B5')} "
              f"& {_pct(tiers, bb, 'B1', 'far')} & {_pct(tiers, bb, 'B5', 'far')} \\\\")
    print()

    print("% ---- Table 2  tab:ablation-results (FAR% | Recall@FAR<=alpha per backbone) ----")
    for gear in GEARS:
        far_cells = " & ".join(_pct(tiers, bb, gear, "far") for bb in BACKBONES)
        rec_cells = " & ".join(_pct(tiers, bb, gear, rk) for bb in BACKBONES)
        print(f"{GEAR_LABEL[gear]:16} & {far_cells} & {rec_cells} \\\\")
    print()

    print("% ---- 95% bootstrap CI (resample cases) for B1/B3/B5 — claim_f1 [lo,hi], far% [lo,hi] ----")
    for bb in present:
        ci = doc["backbones"][bb].get("ci95", {})
        for gear in ("B1", "B3", "B5"):
            c = ci.get(gear)
            if not c:
                continue
            f1 = c["claim_f1"]
            far = [round(x * 100, 1) for x in c["far"]]
            print(f"% {DISPLAY[bb]:16} {gear}: F1 [{f1[0]:.3f}, {f1[1]:.3f}]  FAR% [{far[0]}, {far[1]}]")
    if not present:
        print("% (no backbones yet)")
    print()

    print("% ---- Fig 1  fig:risk-coverage (B5 points: threshold, coverage, far%, recall%) ----")
    for bb in present:
        print(f"% {DISPLAY[bb]}:")
        for pt in doc["backbones"][bb].get("risk_coverage_B5", []):
            print(f"%   thr={pt['threshold']:.3f} cov={pt['coverage'] * 100:.1f} "
                  f"far={pt['far'] * 100:.1f} recall={pt['recall'] * 100:.1f}")
    if not present:
        print("% (no backbones yet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
