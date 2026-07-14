"""Bridge detector / auditor output into VeritasBench ClaimPrediction records.

The twin scorer (engine/twins/scorer.py) and the round-2 script produce, per injected twin, a
`detected` + `verdict` summary, and per mother a count of findings surviving the whitelist. This
module turns that into `ClaimPrediction` records so engine.benchmark.metrics can compute the real
main-table row (Claim F1 / Evidence Precision / FAR / Recall@FAR / Coverage / Abstention).

IMPORTANT — this fixes a metric-naming bug in scripts/round2_score_cns098.py `_metrics`: there
`far = fn / total`, i.e. the MISS rate on dirty claims, NOT a false-accusation rate. A real FAR is
"a CLEAN locus that got flagged". Dirty claims contribute recall; clean claims (the mother's
benign loci) contribute FAR. This bridge keeps the two apart.
"""

from __future__ import annotations

from typing import Any

from engine.benchmark.metrics import ClaimPrediction
from engine.benchmark.schema import LABEL_CLEAN, LABEL_DIRTY

# ordinal detector severity -> continuous confidence for the threshold sweep.
# detectors today have no severity field, so callers fall back to detected -> 1.0 / miss -> 0.0.
_SEVERITY_CONFIDENCE = {"critical": 1.0, "warning": 0.66, "info": 0.33}


def severity_to_confidence(severity: str | None, *, default: float = 1.0) -> float:
    return _SEVERITY_CONFIDENCE.get(str(severity), default)


def dirty_prediction(
    claim_id: str,
    *,
    detected: bool,
    verdict: str,
    confidence: float | None = None,
) -> ClaimPrediction:
    """One injected (dirty) twin -> a prediction. Flagged iff detected AND verdict == 'real'.

    evidence_correct mirrors the flag here because a delta finding is, by construction, matched at
    the injection anchor cells (scorer.delta_findings restricts to the anchor); when raw findings
    with cell refs are available, pass a computed value instead.
    """
    flagged = bool(detected) and verdict == "real"
    conf = confidence if confidence is not None else (1.0 if detected else 0.0)
    return ClaimPrediction(
        claim_id=claim_id,
        gt_label=LABEL_DIRTY,
        predicted_flag=flagged,
        confidence=conf,
        evidence_correct=flagged,
    )


def clean_predictions(
    n_clean: int,
    *,
    n_flagged: int,
    prefix: str = "clean",
    flagged_confidence: float = 1.0,
) -> list[ClaimPrediction]:
    """`n_clean` matched-clean loci (mother benign relations); `n_flagged` were called real.

    A flagged clean claim is a false accusation. `n_flagged` comes from the system's verdict step
    on the mother (e.g. scorer.score_verdict_level -> mother_real_fp); it is 0 when the system
    controls FAR perfectly and equals n_clean for a raw detector with no triage.
    """
    if not 0 <= n_flagged <= n_clean:
        raise ValueError(f"n_flagged {n_flagged} must be in [0, {n_clean}]")
    preds: list[ClaimPrediction] = []
    for i in range(n_clean):
        flagged = i < n_flagged
        preds.append(
            ClaimPrediction(
                claim_id=f"{prefix}_{i:04d}",
                gt_label=LABEL_CLEAN,
                predicted_flag=flagged,
                confidence=flagged_confidence if flagged else 0.0,
            )
        )
    return preds


def predictions_from_round2(
    round2: dict[str, Any],
    *,
    mother_false_accusations: int = 0,
) -> list[ClaimPrediction]:
    """Build the full prediction set for one system from a round2_scores.json dict.

    Dirty predictions come from `injected_results`; clean predictions from the mother's
    `post_whitelist_findings` count, of which `mother_false_accusations` were verdict=real.
    Pass `mother_false_accusations=post_whitelist_findings` to see the raw-detector (no-triage)
    FAR=1.0 baseline, or the verdict-step count for the controlled system.
    """
    preds = [
        dirty_prediction(row["twin"], detected=bool(row.get("detected")), verdict=str(row.get("verdict", "")))
        for row in round2.get("injected_results", [])
    ]
    n_clean = int(round2.get("mother", {}).get("post_whitelist_findings", 0))
    preds.extend(clean_predictions(n_clean, n_flagged=mother_false_accusations, prefix="mother_clean"))
    return preds
