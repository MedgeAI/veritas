"""Adapter: MedgeBench audit tasks -> VeritasBench BenchmarkCase (SYNTHETIC calibration tier).

Reuses the audit line (`build-kit/tasks/medge-audit-*`) as VeritasBench's synthetic calibration
corpus — controlled fabrication (near-duplicate sample injection on real clean GEO matrices),
built-in hard negatives, and claim-support GT. NOT headline: synthetic is dev/calibration/ablation
only (real PubPeer is headline).

Mapping (each task -> ONE BenchmarkCase = the cluster unit for bootstrap CI; each dataset_NN ->
TWO ClaimInstances on ORTHOGONAL axes, distinguished by metadata['axis'] — the SOLE authoritative
node/edge marker, so the frozen schema is untouched):

  axis='artifact_integrity' (NODE / Artifact-Integrity): dirty iff integrity=='fabricated';
      Evidence.cells = the injected sample COLUMNS. `level='L3'` is a PLACEHOLDER ONLY.
      ★ GUARDRAIL: an artifact claim must NEVER appear in an L1-L4 stratified table nor in a
      level_coverage EDGE count — it appears ONLY in Artifact-F1. Filter with axis_claims(...).
  axis='claim_support' (EDGE, L3 = T/F->S): dirty iff claim_supported=='no'; claim_text from
      the dataset's claim.txt. This one IS a genuine L3 edge.

Over-accusation trap (integrity=fabricated but claim_supported=yes) -> artifact claim dirty +
claim-support claim clean (the dual-layer decoupling). Hard negatives (clean, high-correlation)
-> both clean (flagging them = false accusation, the FAR blade).
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.benchmark.schema import (
    LABEL_CLEAN,
    LABEL_DIRTY,
    LEVEL_RELATION,
    SOURCE_INJECTED,
    BenchmarkCase,
    ClaimInstance,
    Evidence,
)

AXIS_ARTIFACT = "artifact_integrity"
AXIS_CLAIM_SUPPORT = "claim_support"

# split assignment (W1-TASKBRIEF): dev calibrates the decision threshold, test reports ablation.
# Same injection recipe must NOT cross dev/test (inject.py recipe would leak).
SPLIT_MAP: dict[str, str] = {
    "medge-audit-1": "synthetic-dev",
    "medge-audit-2": "synthetic-dev",
    "medge-audit-6": "synthetic-dev",
    "medge-audit-3": "synthetic-test",
    "medge-audit-5": "synthetic-test",
    "medge-audit-5-k10": "synthetic-test",
    "medge-audit-9": "synthetic-test",
    "medge-audit-9-k10": "synthetic-test",
}


def _injected_sample_cols(injected) -> frozenset[str]:
    """Extract injected sample column names; GT lists them as dicts ({sample,source}) OR bare
    strings, and some fabricated datasets omit them entirely (label still dirty via integrity)."""
    cols: set[str] = set()
    for row in injected or []:
        name = row.get("sample") if isinstance(row, dict) else row
        if name:
            cols.add(str(name))
    return frozenset(cols)


def _integrity_claim(task: str, dataset: str, gt: dict) -> ClaimInstance:
    fabricated = str(gt.get("integrity")) == "fabricated"
    injected = gt.get("injected_samples") or []
    cells = _injected_sample_cols(injected)
    return ClaimInstance(
        claim_id=f"{task}::{dataset}::integrity",
        claim_type="source_data.duplicate_columns",
        level="L3",  # PLACEHOLDER — never report under L1-L4; axis marks it as a NODE claim
        label=LABEL_DIRTY if fabricated else LABEL_CLEAN,
        relation=LEVEL_RELATION["L3"],
        claim_text="All samples in this dataset are independent, genuine measurements — no "
                   "duplicated, block-copied, cross-group-copied, or linearly-transformed sample columns.",
        evidence=Evidence(evidence_type="source_data", target=f"{dataset}/expression.csv", cells=cells),
        evidence_span=f"artifact:{dataset}/expression.csv->cols:{','.join(sorted(cells))}" if cells else None,
        source=SOURCE_INJECTED,
        metadata={"axis": AXIS_ARTIFACT, "task": task, "dataset": dataset,
                  "injected_samples": injected},
    )


def _claim_support_claim(task: str, dataset: str, gt: dict, claim_text: str) -> ClaimInstance:
    unsupported = str(gt.get("claim_supported")) == "no"
    return ClaimInstance(
        claim_id=f"{task}::{dataset}::claim_support",
        claim_type="report.claim_support",
        level="L3",  # genuine edge T/F->S
        label=LABEL_DIRTY if unsupported else LABEL_CLEAN,
        relation=LEVEL_RELATION["L3"],
        evidence=Evidence(evidence_type="completeness", target=f"{dataset}/claim.txt"),
        claim_text=claim_text,
        source=SOURCE_INJECTED,
        metadata={"axis": AXIS_CLAIM_SUPPORT, "task": task, "dataset": dataset},
    )


def load_audit_task(task_dir: str | Path, *, split: str | None = None) -> BenchmarkCase:
    """Load one medge-audit-* task into a BenchmarkCase (2 claims per dataset)."""
    task_dir = Path(task_dir)
    task = task_dir.name
    gt = json.loads((task_dir / "tests" / "ground_truth" / "audit_gt.json").read_text(encoding="utf-8"))
    data_root = task_dir / "environment" / "data"

    claims: list[ClaimInstance] = []
    for dataset in sorted(gt):
        claim_path = data_root / dataset / "claim.txt"
        claim_text = claim_path.read_text(encoding="utf-8").strip() if claim_path.exists() else ""
        claims.append(_integrity_claim(task, dataset, gt[dataset]))
        claims.append(_claim_support_claim(task, dataset, gt[dataset], claim_text))

    return BenchmarkCase(
        case_id=task,
        split=split or SPLIT_MAP.get(task, "synthetic-dev"),
        base_paper_id=task,
        claims=tuple(claims),
        artifacts={"task_dir": str(task_dir), "data": str(data_root)},
    )


def load_audit_corpus(tasks_root: str | Path, *, split: str | None = None) -> list[BenchmarkCase]:
    """Load every medge-audit-* task under tasks_root; optionally filter to one split."""
    tasks_root = Path(tasks_root)
    cases = []
    for task_dir in sorted(tasks_root.glob("medge-audit-*")):
        if task_dir.name not in SPLIT_MAP:
            continue  # skip audit-13/14 (single-cell, different schema) and any unmapped task
        case = load_audit_task(task_dir)
        if split is None or case.split == split:
            cases.append(case)
    return cases


def axis_claims(case: BenchmarkCase, axis: str) -> tuple[ClaimInstance, ...]:
    """Select an axis's claims. Use this for per-axis metrics; NEVER level_coverage on artifact claims."""
    return tuple(c for c in case.claims if (c.metadata or {}).get("axis") == axis)
