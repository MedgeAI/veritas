"""B5 — FAR-constrained selective decision (the Veritas-Auditor decision layer).

Turns per-claim confidence scores into flag / pass / abstain decisions under a hard
false-accusation-rate ceiling. This is the risk-controlled selective-prediction contribution:

    fit_decision(dev, alpha)  -> calibrate a flag threshold that maximises recall s.t. FAR <= alpha
                                 on the dev split, plus (optionally) an abstain band below it.
    Decision.decide(conf)     -> "flag" | "abstain" | "pass"
    apply_decision(preds, d)  -> re-decide a set of predictions with that rule (for metrics)

The flag threshold reuses metrics.recall_at_far (the max-recall operating point at FAR<=alpha).
Abstention is optional and coverage-target-driven: to reach coverage c, abstain the (1-c) fraction
of claims sitting just below the flag threshold (the most borderline ones) — never by refusing to
answer indiscriminately (metrics.coverage_abstention keeps that honest).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from engine.benchmark.metrics import ClaimPrediction, recall_at_far

FLAG = "flag"
ABSTAIN = "abstain"
PASS = "pass"


@dataclass(frozen=True)
class Decision:
    """A calibrated flag/pass/abstain rule. Flag >= flag_threshold; abstain in
    [abstain_threshold, flag_threshold); pass below abstain_threshold."""

    flag_threshold: float
    abstain_threshold: float
    alpha: float

    def __post_init__(self) -> None:
        if self.abstain_threshold > self.flag_threshold:
            raise ValueError("abstain_threshold must be <= flag_threshold")

    def decide(self, confidence: float) -> str:
        if confidence >= self.flag_threshold:
            return FLAG
        if confidence >= self.abstain_threshold:
            return ABSTAIN
        return PASS


def fit_decision(
    dev: Iterable[ClaimPrediction],
    *,
    alpha: float = 0.05,
    coverage_target: float | None = None,
) -> Decision:
    """Calibrate a Decision on a labelled dev split.

    flag_threshold = the max-recall operating point with FAR <= alpha (metrics.recall_at_far).
    coverage_target: if given (0<c<=1), set an abstain band so ~ (1-c) of dev claims just below the
    flag threshold are abstained; None (default) => no abstain band (abstain_threshold == flag).
    """
    dev = list(dev)
    flag_threshold = recall_at_far(dev, alpha)["threshold"]

    if coverage_target is None or coverage_target >= 1.0:
        return Decision(flag_threshold, flag_threshold, alpha)
    if not 0.0 < coverage_target < 1.0:
        raise ValueError("coverage_target must be in (0, 1] or None")

    answered = [p for p in dev if not p.abstained]
    below = sorted((p.confidence for p in answered if p.confidence < flag_threshold), reverse=True)
    if not below:
        return Decision(flag_threshold, flag_threshold, alpha)
    # abstain the (1 - coverage_target) fraction of ALL answered claims, taken from just below flag
    n_abstain = min(len(below), round((1.0 - coverage_target) * len(answered)))
    if n_abstain <= 0:
        return Decision(flag_threshold, flag_threshold, alpha)
    abstain_threshold = below[n_abstain - 1]
    return Decision(flag_threshold, abstain_threshold, alpha)


def apply_decision(preds: Iterable[ClaimPrediction], decision: Decision) -> list[ClaimPrediction]:
    """Re-decide predictions under `decision`, setting predicted_flag / abstained from confidence.

    Already-abstained inputs stay abstained. The returned records feed engine.benchmark.metrics.
    """
    out: list[ClaimPrediction] = []
    for p in preds:
        if p.abstained:
            out.append(p)
            continue
        verdict = decision.decide(p.confidence)
        out.append(
            ClaimPrediction(
                claim_id=p.claim_id,
                gt_label=p.gt_label,
                predicted_flag=(verdict == FLAG),
                confidence=p.confidence,
                abstained=(verdict == ABSTAIN),
                evidence_correct=p.evidence_correct,
            )
        )
    return out
