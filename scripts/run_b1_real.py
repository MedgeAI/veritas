"""Run the B1 bare-agent baseline with REAL model backbones (the story-arc competitors).

Same B1 protocol, several (provider, model) backbones -> one main-table row each. This is the
bare-agent baseline the ablation improves on. Reads keys from .env.

NOTE: on the tiny example_case the artifacts are placeholder paths with no real content, so the
models must guess — this run proves the LIVE backbone + harness + metrics wiring end-to-end;
meaningful numbers need cases whose artifacts carry real content (吴关渡's code-bearing cases).

Run:  PYTHONPATH=. python3 scripts/run_b1_real.py
"""

from __future__ import annotations

import sys

from engine.benchmark.agent_harness import run_bare_agent
from engine.benchmark.backbones import make_json_agent
from engine.benchmark.metrics import main_table_row
from engine.benchmark.schema import load_annotations
from scripts.live_backbones import AUDITOR_SYSTEM, CANONICAL_MODELS, make_backbone

CASE = "tests/fixtures/veritasbench_cases/example_case.json"
KEYS = ["claim_f1", "claim_recall", "far", "evidence_precision", "coverage", "abstention"]


def main() -> int:
    case = load_annotations(CASE, split="real-test")
    print(f"case={case.case_id}  claims={len(case.claims)}  (B1 bare agent, live backbones)\n")
    print(f"{'backbone':18s} " + " ".join(f"{k:>10s}" for k in KEYS))
    for model in CANONICAL_MODELS:
        try:
            agent = make_json_agent(make_backbone(model), system=AUDITOR_SYSTEM)
            row = main_table_row(run_bare_agent(case, agent))
            print(f"{model:18s} " + " ".join(f"{row[k]:>10.3f}" for k in KEYS))
        except Exception as e:  # noqa: BLE001 — one backbone failing shouldn't kill the sweep
            print(f"{model:18s} ERROR: {type(e).__name__}: {str(e)[:60]}", file=sys.stderr)
    print("\n(placeholder artifacts -> guessy numbers; this proves the live backbone wiring.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
