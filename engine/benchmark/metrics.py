"""VeritasBench publishable metrics (claim-level, benchmark-wide aggregation).

The current twin scorer (engine/twins/scorer.py) reports per-class recall/FAR and a
hallucination_rate on the mother, but NOT the paper's main-table metrics, and its precision is a
placeholder (`1.0 if tp else 0.0`). This module implements the real ones as PURE FUNCTIONS over a
list of `ClaimPrediction` records, so they are correct and unit-testable independently of how the
auditor produces those records.

Positive class = "dirty" (a genuine inconsistency exists). A "clean" claim is a matched benign
locus; flagging it is a *false accusation*. FAR = false-accusation rate over clean claims.

Signal note: detectors today emit an ordinal `severity` (critical/warning/info), not a continuous
confidence. Map that to a float `confidence` (e.g. 1.0/0.66/0.33) when building records; the sweep
in `recall_at_far` / `risk_coverage_curve` then works, just at coarse resolution. When the auditor
emits a continuous score, the same functions give a smooth curve with no change here.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.benchmark.schema import LABEL_CLEAN, LABEL_DIRTY


@dataclass(frozen=True)
class ClaimPrediction:
    """One auditor decision on one benchmark claim, aligned to ground truth."""

    claim_id: str
    gt_label: str            # dirty | clean
    predicted_flag: bool     # system flagged this locus as an inconsistency (its chosen operating point)
    confidence: float = 0.0  # score used for threshold sweeps (higher = more sure it is dirty)
    abstained: bool = False  # selective prediction: system declined to decide
    evidence_correct: bool = False  # for a flag: did the cited evidence match the GT locus (IoU>=0.5)

    def __post_init__(self) -> None:
        if self.gt_label not in (LABEL_DIRTY, LABEL_CLEAN):
            raise ValueError(f"{self.claim_id}: gt_label must be dirty|clean, got {self.gt_label!r}")


def _answered(preds: list[ClaimPrediction]) -> list[ClaimPrediction]:
    return [p for p in preds if not p.abstained]


def claim_prf(preds: list[ClaimPrediction]) -> dict[str, float]:
    """Precision / recall / F1 for the dirty class over ANSWERED claims (abstentions excluded)."""
    answered = _answered(preds)
    tp = sum(1 for p in answered if p.gt_label == LABEL_DIRTY and p.predicted_flag)
    fp = sum(1 for p in answered if p.gt_label == LABEL_CLEAN and p.predicted_flag)
    fn = sum(1 for p in answered if p.gt_label == LABEL_DIRTY and not p.predicted_flag)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def evidence_precision(preds: list[ClaimPrediction]) -> float:
    """Of all answered flags, the fraction whose cited evidence matches the GT locus.

    A flag that lands on the wrong cells is not real evidence even if the case is dirty, so this is
    stricter than label precision.
    """
    flags = [p for p in _answered(preds) if p.predicted_flag]
    if not flags:
        return 0.0
    return sum(1 for p in flags if p.gt_label == LABEL_DIRTY and p.evidence_correct) / len(flags)


def false_accusation_rate(preds: list[ClaimPrediction]) -> float:
    """FAR = answered clean claims that were flagged / answered clean claims."""
    clean = [p for p in _answered(preds) if p.gt_label == LABEL_CLEAN]
    if not clean:
        return 0.0
    return sum(1 for p in clean if p.predicted_flag) / len(clean)


def recall_at_far(preds: list[ClaimPrediction], alpha: float = 0.05) -> dict[str, float]:
    """Max dirty-recall achievable while FAR <= alpha, by sweeping the confidence threshold.

    Flags a claim iff (not abstained) and confidence >= threshold. Sweeps every observed
    confidence as a candidate threshold plus +inf (flag nothing). Returns the best recall whose
    FAR <= alpha and the threshold that achieves it.
    """
    answered = _answered(preds)
    dirty_total = sum(1 for p in answered if p.gt_label == LABEL_DIRTY)
    clean_total = sum(1 for p in answered if p.gt_label == LABEL_CLEAN)
    if dirty_total == 0:
        return {"recall_at_far": 0.0, "threshold": float("inf"), "far": 0.0, "alpha": alpha}

    thresholds = sorted({p.confidence for p in answered}, reverse=True) + [float("inf")]
    best = {"recall_at_far": 0.0, "threshold": float("inf"), "far": 0.0, "alpha": alpha}
    for tau in thresholds:
        tp = sum(1 for p in answered if p.gt_label == LABEL_DIRTY and p.confidence >= tau)
        fp = sum(1 for p in answered if p.gt_label == LABEL_CLEAN and p.confidence >= tau)
        far = fp / clean_total if clean_total else 0.0
        recall = tp / dirty_total
        if far <= alpha and recall > best["recall_at_far"]:
            best = {"recall_at_far": recall, "threshold": tau, "far": far, "alpha": alpha}
    return best


def coverage_abstention(preds: list[ClaimPrediction]) -> dict[str, float]:
    """Coverage = answered / total; abstention = 1 - coverage. Guards the 'abstain to fake FAR' pit."""
    total = len(preds)
    if total == 0:
        return {"coverage": 0.0, "abstention": 0.0, "answered": 0, "total": 0}
    answered = len(_answered(preds))
    return {
        "coverage": answered / total,
        "abstention": (total - answered) / total,
        "answered": answered,
        "total": total,
    }


def risk_coverage_curve(preds: list[ClaimPrediction]) -> list[dict[str, float]]:
    """Sweep the confidence threshold high->low; at each operating point report coverage & FAR.

    Proves a low-FAR system earns it by discrimination, not by answering little. Coverage here =
    fraction of ALL claims flagged-or-passed at threshold tau among answered claims that are >=tau
    (i.e. how much of the benchmark you commit a positive decision on).
    """
    answered = _answered(preds)
    if not answered:
        return []
    dirty_total = sum(1 for p in answered if p.gt_label == LABEL_DIRTY) or 1
    clean_total = sum(1 for p in answered if p.gt_label == LABEL_CLEAN) or 1
    thresholds = sorted({p.confidence for p in answered}, reverse=True)
    curve = []
    for tau in thresholds:
        flagged = [p for p in answered if p.confidence >= tau]
        tp = sum(1 for p in flagged if p.gt_label == LABEL_DIRTY)
        fp = sum(1 for p in flagged if p.gt_label == LABEL_CLEAN)
        curve.append({
            "threshold": tau,
            "coverage": len(flagged) / len(answered),
            "recall": tp / dirty_total,
            "far": fp / clean_total,
        })
    return curve


def main_table_row(preds: list[ClaimPrediction], *, alpha: float = 0.05) -> dict[str, float]:
    """Assemble the paper's main-table row for one system over the whole benchmark."""
    prf = claim_prf(preds)
    cov = coverage_abstention(preds)
    return {
        "claim_f1": prf["f1"],
        "claim_precision": prf["precision"],
        "claim_recall": prf["recall"],
        "evidence_precision": evidence_precision(preds),
        "far": false_accusation_rate(preds),
        f"recall_at_far<={alpha:g}": recall_at_far(preds, alpha)["recall_at_far"],
        "coverage": cov["coverage"],
        "abstention": cov["abstention"],
    }
