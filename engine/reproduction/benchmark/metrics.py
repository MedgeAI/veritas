"""Metrics calculator for VeritasBench evaluation.

Computes claim-level F1, evidence precision/recall, FAR, recall@FAR,
coverage and abstention rate from paired predictions and ground truth.
"""

from __future__ import annotations

from engine.reproduction.models import ClaimRelationAnnotation, ClaimVerdict


def _safe_div(numerator: float, denominator: float) -> float:
    """Return numerator/denominator, or 0.0 when denominator is zero."""
    return numerator / denominator if denominator != 0 else 0.0


def _compute_f1(precision: float, recall: float) -> float:
    """Harmonic mean of precision and recall; 0.0 if both are zero."""
    return _safe_div(2 * precision * recall, precision + recall)


class MetricsCalculator:
    """Compute VeritasBench metrics over (predictions, ground_truth) pairs."""

    # ------------------------------------------------------------------
    # top-level entry point
    # ------------------------------------------------------------------

    def calculate(
        self,
        predictions: list[ClaimVerdict],
        ground_truth: list[ClaimRelationAnnotation],
    ) -> dict[str, float]:
        """Return every metric as a flat dict."""
        return {
            "claim_f1": self.calculate_claim_f1(predictions, ground_truth),
            "evidence_precision": self.calculate_evidence_precision(predictions, ground_truth),
            "evidence_recall": self.calculate_evidence_recall(predictions, ground_truth),
            "far": self.calculate_far(predictions, ground_truth),
            "recall_at_far_05": self.calculate_recall_at_far(predictions, ground_truth, 0.05),
            "recall_at_far_10": self.calculate_recall_at_far(predictions, ground_truth, 0.10),
            "coverage": self.calculate_coverage(predictions),
            "abstention_rate": self.calculate_abstention_rate(predictions),
        }

    # ------------------------------------------------------------------
    # claim-level F1
    # ------------------------------------------------------------------

    def calculate_claim_f1(
        self,
        predictions: list[ClaimVerdict],
        ground_truth: list[ClaimRelationAnnotation],
    ) -> float:
        """F1 for claim-level flag detection.

        Positive class = "flag" on the prediction side, "inconsistent" on the
        GT side (any annotation on that claim is inconsistent → claim is dirty).
        """
        pred_by_claim: dict[str, ClaimVerdict] = {v.claim_id: v for v in predictions}

        gt_dirty_claims: set[str] = {
            ann.claim_id for ann in ground_truth if ann.verdict == "inconsistent"
        }
        # A claim is positive iff any annotation on it is inconsistent.
        gt_flagged_ids = gt_dirty_claims

        pred_flagged_ids = {
            cid for cid, v in pred_by_claim.items() if v.verdict == "flag"
        }

        tp = len(pred_flagged_ids & gt_flagged_ids)
        fp = len(pred_flagged_ids - gt_flagged_ids)
        fn = len(gt_flagged_ids - pred_flagged_ids)

        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        return _compute_f1(precision, recall)

    # ------------------------------------------------------------------
    # evidence precision / recall
    # ------------------------------------------------------------------

    def _predicted_spans(self, predictions: list[ClaimVerdict]) -> dict[str, set[str]]:
        """Map claim_id -> set of predicted evidence spans (deduplicated)."""
        spans: dict[str, set[str]] = {}
        for v in predictions:
            claim_spans: set[str] = set()
            for edge in v.evidence_graph.edges:
                vo = edge.verifier_output
                if vo is not None and vo.evidence_span:
                    claim_spans.add(vo.evidence_span)
            spans[v.claim_id] = claim_spans
        return spans

    def _gt_spans(self, ground_truth: list[ClaimRelationAnnotation]) -> dict[str, set[str]]:
        """Map claim_id -> set of GT evidence spans (from annotations with a span)."""
        spans: dict[str, set[str]] = {}
        for ann in ground_truth:
            if ann.evidence_span:
                spans.setdefault(ann.claim_id, set()).add(ann.evidence_span)
        return spans

    def calculate_evidence_precision(
        self,
        predictions: list[ClaimVerdict],
        ground_truth: list[ClaimRelationAnnotation],
    ) -> float:
        """#correct evidence spans / #predicted evidence spans."""
        pred_spans = self._predicted_spans(predictions)
        gt_spans = self._gt_spans(ground_truth)

        total_pred = 0
        total_correct = 0
        for claim_id, p_set in pred_spans.items():
            if not p_set:
                continue
            g_set = gt_spans.get(claim_id, set())
            total_pred += len(p_set)
            total_correct += len(p_set & g_set)
        return _safe_div(total_correct, total_pred)

    def calculate_evidence_recall(
        self,
        predictions: list[ClaimVerdict],
        ground_truth: list[ClaimRelationAnnotation],
    ) -> float:
        """#correct evidence spans / #GT evidence spans."""
        pred_spans = self._predicted_spans(predictions)
        gt_spans = self._gt_spans(ground_truth)

        total_gt = 0
        total_correct = 0
        for claim_id, g_set in gt_spans.items():
            if not g_set:
                continue
            p_set = pred_spans.get(claim_id, set())
            total_gt += len(g_set)
            total_correct += len(p_set & g_set)
        return _safe_div(total_correct, total_gt)

    # ------------------------------------------------------------------
    # FAR and recall@FAR
    # ------------------------------------------------------------------

    def calculate_far(
        self,
        predictions: list[ClaimVerdict],
        ground_truth: list[ClaimRelationAnnotation],
    ) -> float:
        """False Accusation Rate: #flagged clean claims / #total clean claims."""
        clean_claims: set[str] = {
            ann.claim_id for ann in ground_truth if ann.is_clean_claim
        }
        if not clean_claims:
            return 0.0

        pred_by_claim = {v.claim_id: v for v in predictions}
        flagged_clean = sum(
            1
            for cid in clean_claims
            if pred_by_claim.get(cid) is not None and pred_by_claim[cid].verdict == "flag"
        )
        return flagged_clean / len(clean_claims)

    def calculate_recall_at_far(
        self,
        predictions: list[ClaimVerdict],
        ground_truth: list[ClaimRelationAnnotation],
        far_alpha: float = 0.05,
    ) -> float:
        """Recall under the constraint FAR <= alpha.

        Strategy: sort flagged predictions by ascending far_risk (ascending
        confidence in the accusation). Sweep a threshold on far_risk — accept
        only accusations with far_risk <= threshold. Pick the largest threshold
        that keeps empirical FAR <= alpha, then compute recall over accepted
        accusations.
        """
        clean_claims: set[str] = {
            ann.claim_id for ann in ground_truth if ann.is_clean_claim
        }
        dirty_claims: set[str] = set()
        for ann in ground_truth:
            if ann.verdict == "inconsistent":
                dirty_claims.add(ann.claim_id)
        dirty_claims -= clean_claims  # clean claims take precedence

        flagged = [v for v in predictions if v.verdict == "flag"]
        # sort by far_risk ascending — low risk accusations accepted first
        flagged_sorted = sorted(flagged, key=lambda v: v.far_risk)

        n_clean = len(clean_claims)
        n_dirty = len(dirty_claims)
        if n_clean == 0 or n_dirty == 0:
            return 0.0

        best_recall = 0.0
        accepted_clean = 0
        accepted_dirty = 0

        # evaluate threshold after each acceptance
        for v in flagged_sorted:
            if v.claim_id in clean_claims:
                accepted_clean += 1
            elif v.claim_id in dirty_claims:
                accepted_dirty += 1
            else:
                continue  # claim not in GT — ignore for FAR/recall

            current_far = accepted_clean / n_clean
            if current_far <= far_alpha:
                recall = accepted_dirty / n_dirty
                if recall > best_recall:
                    best_recall = recall

        return best_recall

    # ------------------------------------------------------------------
    # coverage / abstention
    # ------------------------------------------------------------------

    def calculate_coverage(self, predictions: list[ClaimVerdict]) -> float:
        """Fraction of claims with a definitive (flag/pass) verdict."""
        if not predictions:
            return 0.0
        definitive = sum(1 for v in predictions if v.verdict != "abstain")
        return definitive / len(predictions)

    def calculate_abstention_rate(self, predictions: list[ClaimVerdict]) -> float:
        """Fraction of claims with an abstain verdict."""
        if not predictions:
            return 0.0
        abstained = sum(1 for v in predictions if v.verdict == "abstain")
        return abstained / len(predictions)
