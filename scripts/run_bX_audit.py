"""First real B1–B5 numbers on the audit line — SYNTHETIC calibration tier (NOT headline).

Scope (director decision A, 2026-07-14): the forensics story fits the WITHIN-DATASET duplication
cluster only. audit-1 = dev, audit-2 = test (both within-dataset copy: block/near/linear/cross-
group). Cross-dataset (audit-3) and design-fraud (audit-5/6/9) are separate axes, not here.

Two axes per dataset (metadata['axis']): ARTIFACT (node, forensics verifier) + CLAIM-SUPPORT
(edge L3, agent-only PILOT — no deterministic edge verifier for audit). Gears:
  B1 bare / B2 structured  — agent judges from NEUTRAL descriptive stats (audit_renderer).
  B3 artifact              — + forensics verifier; run TWICE (naive exact-match vs robust
                             byte-overlap+regression) — the "exact-match is a reflex" ablation.
  (B4/B5 collapse to B3 for audit: only one deterministic tool layer exists; the claim-support
   edge verifier is not built, so those gears reduce to agent-only. Reported as such.)

All output is labelled `synthetic` (calibration/ablation), never headline. CI = bootstrap over
DATASETS with a recipe-correlation caveat (n_task=1 in test → task-cluster CI is undefined).

Run:  VERITAS_REAL_PAPERS_ROOT unused; AUDIT_TASKS=<dir> PYTHONPATH=. python3 scripts/run_bX_audit.py
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

from engine.benchmark.agent_harness import run_bare_agent, run_constrained_agent
from engine.benchmark.audit_adapter import AXIS_ARTIFACT, axis_claims, load_audit_task
from engine.benchmark.audit_verifiers import audit_renderer, detect_duplicate_columns
from engine.benchmark.backbones import make_json_agent
from engine.benchmark.metrics import ClaimPrediction, main_table_row
from engine.benchmark.schema import LABEL_DIRTY
from scripts.live_backbones import AUDITOR_SYSTEM, make_backbone

AUDIT = Path(os.environ.get("AUDIT_TASKS",
             "/Users/chaco/Desktop/medgebench/workspace/data-crawl/downloads/audit-tasks"))
BACKBONE = os.environ.get("AUDIT_BACKBONE", "qwen3.7-plus")   # ≥1 real backbone
# reasoning backbones (deepseek-v4-pro, glm-5.2) burn tokens THINKING before emitting the JSON
# verdict; a truncated reply parses to {} = a spurious abstention that deflates coverage. Give
# them headroom so coverage reflects judgement, not token starvation.
MAX_TOKENS = int(os.environ.get("AUDIT_MAX_TOKENS", "4000"))
METRIC_KEYS = ["claim_f1", "claim_recall", "far", "coverage"]


def _axis_preds(preds: list[ClaimPrediction], suffix: str) -> list[ClaimPrediction]:
    return [p for p in preds if p.claim_id.endswith(suffix)]


def _forensic_artifact_metrics(case, mode: str) -> dict:
    """Deterministic B3 forensics on the artifact axis (no agent): recall / FAR / evidence-precision."""
    tp = fp = fn = tn = 0
    ev_hit = ev_flagged = 0
    for claim in axis_claims(case, AXIS_ARTIFACT):
        dataset = claim.metadata["dataset"]
        path = Path(case.artifacts["data"]) / dataset / "expression.csv"
        dupes = detect_duplicate_columns(path, mode=mode) if path.exists() else []
        detected_cols = {c for pair in dupes for c in pair[:2]}
        flagged = bool(dupes)
        dirty = claim.label == LABEL_DIRTY
        tp += flagged and dirty
        fp += flagged and not dirty
        fn += (not flagged) and dirty
        tn += (not flagged) and not dirty
        if flagged and dirty:
            ev_flagged += 1
            injected = {str(r.get("sample") if isinstance(r, dict) else r)
                        for r in (claim.metadata.get("injected_samples") or [])}
            if injected & detected_cols:
                ev_hit += 1
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    far = fp / (fp + tn) if (fp + tn) else 0.0
    return {"mode": mode, "recall": round(recall, 4), "far": round(far, 4),
            "evidence_precision": round(ev_hit / ev_flagged, 4) if ev_flagged else 0.0,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def _bootstrap_recall_far(case, mode: str, *, n: int = 1000) -> dict:
    """Dataset-level bootstrap CI (CAVEAT: datasets share the injection recipe -> CI understates
    correlation; task-cluster CI is undefined at n_task=1)."""
    datasets = [c.metadata["dataset"] for c in axis_claims(case, AXIS_ARTIFACT)]
    labels = {c.metadata["dataset"]: (c.label == LABEL_DIRTY) for c in axis_claims(case, AXIS_ARTIFACT)}
    flagged = {}
    for ds in datasets:
        path = Path(case.artifacts["data"]) / ds / "expression.csv"
        flagged[ds] = bool(detect_duplicate_columns(path, mode=mode)) if path.exists() else False
    rng = random.Random(0)
    recalls, fars = [], []
    for _ in range(n):
        sample = [rng.choice(datasets) for _ in datasets]
        tp = sum(1 for d in sample if flagged[d] and labels[d])
        fn = sum(1 for d in sample if not flagged[d] and labels[d])
        fp = sum(1 for d in sample if flagged[d] and not labels[d])
        tn = sum(1 for d in sample if not flagged[d] and not labels[d])
        recalls.append(tp / (tp + fn) if (tp + fn) else 0.0)
        fars.append(fp / (fp + tn) if (fp + tn) else 0.0)
    recalls.sort()
    fars.sort()
    lo, hi = int(0.025 * n), int(0.975 * n)
    return {"recall_ci95": [round(recalls[lo], 3), round(recalls[hi], 3)],
            "far_ci95": [round(fars[lo], 3), round(fars[hi], 3)]}


def main() -> int:
    dev = load_audit_task(AUDIT / "medge-audit-1", split="synthetic-dev")
    test = load_audit_task(AUDIT / "medge-audit-2", split="synthetic-test")
    agent = make_json_agent(make_backbone(BACKBONE, max_tokens=MAX_TOKENS), system=AUDITOR_SYSTEM)
    render = audit_renderer()

    out = {"tier": "synthetic", "note": "calibration/ablation only, NOT headline",
           "backbone": BACKBONE, "dev_task": dev.case_id, "test_task": test.case_id,
           "datasets_test": len(axis_claims(test, AXIS_ARTIFACT)), "gears": {}}

    # agent gears (both axes) on the test task
    print(f"running B1/B2 agent gears with backbone={BACKBONE} on {test.case_id} ...")
    b1 = run_bare_agent(test, agent, render=render)
    b2 = run_constrained_agent(test, agent, render=render)
    for name, preds in [("B1_bare", b1), ("B2_structured", b2)]:
        out["gears"][name] = {
            "artifact": {k: round(main_table_row(_axis_preds(preds, "::integrity"))[k], 4) for k in METRIC_KEYS},
            "claim_support_pilot": {k: round(main_table_row(_axis_preds(preds, "::claim_support"))[k], 4) for k in METRIC_KEYS},
        }

    # B3 forensics on the artifact axis — deterministic, naive vs robust (the ablation)
    out["gears"]["B3_artifact_naive"] = {"artifact": _forensic_artifact_metrics(test, "naive")}
    out["gears"]["B3_artifact_robust"] = {"artifact": _forensic_artifact_metrics(test, "robust"),
                                          "ci_dataset_bootstrap": _bootstrap_recall_far(test, "robust")}
    out["note_gears"] = "B4/B5 == B3 for audit (single deterministic tool layer; claim-support edge verifier not built)"

    Path("outputs").mkdir(exist_ok=True)
    # per-backbone file so a multi-backbone sweep doesn't clobber earlier runs; keep the generic
    # name as an alias to the most recent run for backward-compat.
    safe = BACKBONE.replace("/", "_").replace(".", "-")
    (Path("outputs") / f"audit_b1b5_{safe}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    (Path("outputs") / "audit_b1b5_maintable.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))

    # console summary
    print(json.dumps({"backbone": BACKBONE, "test": test.case_id,
                      "B3_naive_artifact": out["gears"]["B3_artifact_naive"]["artifact"],
                      "B3_robust_artifact": out["gears"]["B3_artifact_robust"]["artifact"],
                      "B1_artifact": out["gears"]["B1_bare"]["artifact"],
                      "B2_artifact": out["gears"]["B2_structured"]["artifact"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
