"""Evidence graph engine for Veritas-Auditor.

Core algorithm: dependency-aware evidence aggregation + FAR-constrained selective prediction.

The engine builds claim-level evidence graphs and aggregates evidence from typed verifiers
to make risk-controlled decisions (flag/pass/abstain) under a false accusation rate constraint.
"""

from dataclasses import dataclass
from typing import Any, Literal

from engine.reproduction.models import (
    ClaimVerdict,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    VerifierOutput,
)
from engine.reproduction.verifiers.base import TypedVerifier


@dataclass
class AggregationResult:
    """Result from evidence aggregation."""

    flag_score: float  # Score for flagging (0-1)
    pass_score: float  # Score for passing (0-1)
    abstain_score: float  # Score for abstaining (0-1)
    evidence_independence: float  # How independent the signals are (0-1)
    discrepancy_convergence: float  # How much signals converge on same mismatch (0-1)
    far_risk_estimate: float  # Estimated false accusation risk (0-1)


class EvidenceGraphEngine:
    """Evidence graph aggregation + FAR-constrained decision.

    Core algorithm:
    1. Check evidence independence (are signals from independent artifacts?)
    2. Check discrepancy convergence (do signals point to same mismatch?)
    3. Estimate FAR risk (is evidence sufficient to support flag?)
    4. Decision: flag / pass / abstain

    Objective: max Recall s.t. FAR ≤ α
    """

    def __init__(
        self,
        far_alpha: float = 0.05,
        aggregation_policy: Literal["flat", "graph_aware"] = "flat",
    ):
        """Initialize the engine.

        Args:
            far_alpha: False accusation rate threshold (default 0.05 = 5%)
        """
        self.far_alpha = far_alpha
        self.set_aggregation_policy(aggregation_policy)

    def set_aggregation_policy(self, policy: Literal["flat", "graph_aware"]) -> None:
        """Select the aggregation policy used by subsequent graph decisions."""

        if policy not in {"flat", "graph_aware"}:
            raise ValueError(f"Unknown aggregation policy: {policy}")
        self.aggregation_policy = policy

    def build_graph(
        self,
        claim: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> EvidenceGraph:
        """Build claim-level evidence graph.

        Args:
            claim: Claim dictionary with claim_atom and annotations
            artifacts: Available artifacts (code, tables, figures, etc.)

        Returns:
            EvidenceGraph with nodes and edges
        """
        claim_id = claim.get("claim_id", "unknown")

        # Create nodes for each artifact type
        nodes = []
        for artifact_type, artifact_ref in artifacts.items():
            node = EvidenceNode(
                node_id=f"{claim_id}_{artifact_type}",
                artifact_type=artifact_type,  # type: ignore
                artifact_ref=artifact_ref,
            )
            nodes.append(node)

        # Create edges based on claim annotations
        edges = []
        annotations = claim.get("annotations", [])
        for i, annotation in enumerate(annotations):
            source_type = self._infer_artifact_type(annotation.get("source_artifact", ""))
            target_type = self._infer_artifact_type(annotation.get("target_artifact", ""))

            source_node = next((n for n in nodes if n.artifact_type == source_type), None)
            target_node = next((n for n in nodes if n.artifact_type == target_type), None)

            if source_node and target_node:
                edge = EvidenceEdge(
                    edge_id=f"{claim_id}_edge_{i}",
                    source_node=source_node.node_id,
                    target_node=target_node.node_id,
                    relation_type=annotation.get("relation_type", "L1"),  # type: ignore
                    verifier_output=None,  # Will be populated by verifier
                )
                edges.append(edge)

        return EvidenceGraph(claim_id=claim_id, nodes=nodes, edges=edges)

    def _infer_artifact_type(self, artifact_ref: str) -> str:
        """Infer artifact type from reference path."""
        if "code" in artifact_ref or "output" in artifact_ref:
            return "code_output"
        elif "table" in artifact_ref:
            return "table_cell"
        elif "figure" in artifact_ref or "image" in artifact_ref:
            return "figure_mark"
        elif "method" in artifact_ref or "text" in artifact_ref:
            return "text_span"
        else:
            return "data"

    def aggregate(self, graph: EvidenceGraph) -> ClaimVerdict:
        """Aggregate evidence and make FAR-constrained decision.

        Args:
            graph: Evidence graph with verifier outputs

        Returns:
            ClaimVerdict with flag/pass/abstain decision
        """
        # Collect all verifier outputs
        verifier_outputs = [edge.verifier_output for edge in graph.edges if edge.verifier_output is not None]

        if not verifier_outputs:
            # No evidence, abstain
            return ClaimVerdict(
                claim_id=graph.claim_id,
                verdict="abstain",
                confidence=0.0,
                evidence_graph=graph,
                aggregated_signals=verifier_outputs,
                far_risk=1.0,
                abstain_reason="No evidence available",
            )

        # Graph-aware mode removes repeated observations of the same artifact
        # relation before scoring. Conflicting relations remain visible and
        # therefore increase abstention risk instead of being hidden.
        aggregation_signals = (
            self._graph_aware_signals(graph)
            if self.aggregation_policy == "graph_aware"
            else verifier_outputs
        )

        # Perform aggregation
        agg_result = self._aggregate_signals(aggregation_signals)

        # Make FAR-constrained decision
        verdict, confidence, abstain_reason = self._make_decision(agg_result)

        return ClaimVerdict(
            claim_id=graph.claim_id,
            verdict=verdict,  # type: ignore
            confidence=confidence,
            evidence_graph=graph,
            aggregated_signals=aggregation_signals,
            far_risk=agg_result.far_risk_estimate,
            abstain_reason=abstain_reason,
        )

    def _aggregate_signals(self, signals: list[VerifierOutput]) -> AggregationResult:
        """Aggregate multiple verifier signals.

        This implements the core aggregation logic:
        1. Evidence independence
        2. Discrepancy convergence
        3. FAR risk estimation

        Args:
            signals: List of verifier outputs

        Returns:
            AggregationResult with scores and risk estimate
        """
        if not signals:
            return AggregationResult(
                flag_score=0.0,
                pass_score=0.0,
                abstain_score=1.0,
                evidence_independence=0.0,
                discrepancy_convergence=0.0,
                far_risk_estimate=1.0,
            )

        # Count verdicts
        inconsistent_count = sum(1 for s in signals if s.verdict == "inconsistent")
        consistent_count = sum(1 for s in signals if s.verdict == "consistent")
        insufficient_count = sum(1 for s in signals if s.verdict == "insufficient")

        total = len(signals)
        inconsistent_ratio = inconsistent_count / total
        consistent_ratio = consistent_count / total

        # Calculate average confidence
        avg_confidence = sum(s.confidence for s in signals) / total

        # Evidence independence (simplified: assume all signals are independent for now)
        # TODO: Implement proper independence check based on artifact types
        evidence_independence = 1.0

        # Discrepancy convergence (simplified: check if all inconsistent signals have same type)
        discrepancy_types = [s.discrepancy_type for s in signals if s.verdict == "inconsistent" and s.discrepancy_type]
        if discrepancy_types:
            # If all inconsistent signals have the same discrepancy type, convergence is high
            most_common_type = max(set(discrepancy_types), key=discrepancy_types.count)
            convergence = discrepancy_types.count(most_common_type) / len(discrepancy_types)
        else:
            convergence = 0.0

        # Calculate scores
        # Flag score: high if many inconsistent signals with high confidence
        flag_score = inconsistent_ratio * avg_confidence * evidence_independence

        # Pass score: high if many consistent signals with high confidence
        pass_score = consistent_ratio * avg_confidence

        # Abstain score: high if many insufficient signals or low confidence
        abstain_score = (insufficient_count / total) + (1 - avg_confidence)

        # Normalize scores
        total_score = flag_score + pass_score + abstain_score
        if total_score > 0:
            flag_score /= total_score
            pass_score /= total_score
            abstain_score /= total_score

        # FAR risk estimate
        # Simplified: risk is high if flag score is high but confidence is low
        # or if evidence independence is low
        far_risk = (1 - avg_confidence) * 0.5 + (1 - evidence_independence) * 0.3 + (1 - convergence) * 0.2

        return AggregationResult(
            flag_score=flag_score,
            pass_score=pass_score,
            abstain_score=abstain_score,
            evidence_independence=evidence_independence,
            discrepancy_convergence=convergence,
            far_risk_estimate=far_risk,
        )

    def _graph_aware_signals(self, graph: EvidenceGraph) -> list[VerifierOutput]:
        """Collapse duplicate artifact-relation signals while preserving conflicts.

        Cell/line-level observations from the same source and target artifact
        family should not count as independent corroboration. A different
        artifact family remains an independent signal. If the same relation
        produces conflicting verdicts, verdict is part of the key so both
        outputs survive and the normal abstention logic sees the conflict.
        """

        nodes = {node.node_id: node for node in graph.nodes}
        selected: dict[tuple[str, str, str, str, str], VerifierOutput] = {}
        for edge in graph.edges:
            signal = edge.verifier_output
            if signal is None:
                continue
            source = nodes.get(edge.source_node)
            target = nodes.get(edge.target_node)
            source_family = self._artifact_family(source.artifact_ref if source else edge.source_node)
            target_family = self._artifact_family(target.artifact_ref if target else edge.target_node)
            key = (
                source_family,
                target_family,
                edge.relation_type,
                signal.verdict,
                signal.discrepancy_type or "",
            )
            previous = selected.get(key)
            if previous is None or signal.confidence > previous.confidence:
                selected[key] = signal
        return list(selected.values())

    @staticmethod
    def _artifact_family(artifact_ref: Any) -> str:
        """Normalize row/cell fragments to their immutable artifact family."""

        value = str(artifact_ref)
        for separator in ("#", "::"):
            value = value.split(separator, 1)[0]
        return value

    def _make_decision(
        self,
        agg_result: AggregationResult,
    ) -> tuple[str, float, str | None]:
        """Make FAR-constrained decision.

        Decision logic:
        - If abstain_score is highest → abstain
        - If flag_score is highest AND far_risk ≤ α → flag
        - Otherwise → pass

        Args:
            agg_result: Aggregation result

        Returns:
            Tuple of (verdict, confidence, abstain_reason)
        """
        # Find the highest score
        scores = {
            "flag": agg_result.flag_score,
            "pass": agg_result.pass_score,
            "abstain": agg_result.abstain_score,
        }
        max_verdict = max(scores, key=scores.get)  # type: ignore
        max_score = scores[max_verdict]

        # Decision logic
        if max_verdict == "abstain":
            return "abstain", max_score, "Insufficient evidence"

        if max_verdict == "flag":
            # Check FAR constraint
            if agg_result.far_risk_estimate <= self.far_alpha:
                return "flag", max_score, None
            else:
                # FAR too high, abstain instead
                return "abstain", max_score, "FAR risk too high"

        # Default: pass
        return "pass", max_score, None


class VerifierAwareEvidenceGraphEngine(EvidenceGraphEngine):
    """Engine that builds the evidence graph AND runs typed verifiers on each edge.

    Extends EvidenceGraphEngine with verifier dispatch: for each edge whose
    relation_type has a registered verifier, extract source/target values
    from the artifacts and populate edge.verifier_output.
    """

    def __init__(
        self,
        verifiers: dict[str, TypedVerifier],
        far_alpha: float = 0.05,
        aggregation_policy: Literal["flat", "graph_aware"] = "flat",
    ) -> None:
        super().__init__(far_alpha=far_alpha, aggregation_policy=aggregation_policy)
        self.verifiers = verifiers

    def build_and_verify(
        self,
        claim: dict,
        artifacts: dict,
    ) -> EvidenceGraph:
        """Build the graph and run the appropriate verifier on each edge.

        For each edge, looks up the verifier by edge.relation_type. If a
        verifier is registered, extracts source/target values from the
        artifacts dict (via the nodes' artifact_ref), calls verifier.verify(),
        and sets edge.verifier_output.

        Args:
            claim: Claim dictionary with claim_id and annotations
            artifacts: Available artifacts keyed by artifact type

        Returns:
            EvidenceGraph with verifier_output populated on each edge that
            has a registered verifier.
        """
        graph = self.build_graph(claim, artifacts)

        for edge in graph.edges:
            verifier = self.verifiers.get(edge.relation_type)
            if verifier is None:
                continue

            source_node = next(
                (n for n in graph.nodes if n.node_id == edge.source_node),
                None,
            )
            target_node = next(
                (n for n in graph.nodes if n.node_id == edge.target_node),
                None,
            )
            if source_node is None or target_node is None:
                continue

            source_value = self._extract_value(source_node.artifact_ref, artifacts)
            target_value = self._extract_value(target_node.artifact_ref, artifacts)

            context = {
                "edge_id": edge.edge_id,
                "relation_type": edge.relation_type,
                "source_artifact_ref": source_node.artifact_ref,
                "target_artifact_ref": target_node.artifact_ref,
            }

            edge.verifier_output = verifier.verify(
                source_value,
                target_value,
                context=context,
            )

        return graph

    @staticmethod
    def _extract_value(artifact_ref: Any, artifacts: dict) -> Any:
        """Extract the comparable value for an artifact reference.

        artifact_ref may be a string key into *artifacts* or the resolved
        value itself (the parent build_graph stores artifact dict values
        into node.artifact_ref). If the resolved value is a dict, extracts
        a 'value' key (falling back to 'data' or 'content').
        """
        if isinstance(artifact_ref, dict):
            artifact = artifact_ref
        elif isinstance(artifact_ref, str):
            artifact = artifacts.get(artifact_ref, artifact_ref)
        else:
            artifact = artifact_ref

        if isinstance(artifact, dict):
            for key in ("value", "data", "content"):
                if key in artifact:
                    return artifact[key]
        return artifact


def create_default_engine(
    far_alpha: float = 0.05,
    aggregation_policy: Literal["flat", "graph_aware"] = "flat",
) -> EvidenceGraphEngine:
    """Create a default EvidenceGraphEngine instance.

    Args:
        far_alpha: False accusation rate threshold

    Returns:
        EvidenceGraphEngine instance
    """
    return EvidenceGraphEngine(
        far_alpha=far_alpha,
        aggregation_policy=aggregation_policy,
    )
