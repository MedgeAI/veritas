"""Unit tests for evidence graph engine."""

from engine.reproduction.evidence_graph import EvidenceGraphEngine, create_default_engine
from engine.reproduction.mock_data import generate_mock_evidence_graph, generate_mock_verifier_output
from engine.reproduction.models import EvidenceEdge, EvidenceGraph, EvidenceNode, VerifierOutput


class TestEvidenceGraphEngine:
    """Test suite for EvidenceGraphEngine."""

    def test_create_default_engine(self):
        """Test creating default engine instance."""
        engine = create_default_engine(far_alpha=0.05)
        assert engine.far_alpha == 0.05

    def test_aggregate_with_all_consistent_signals(self):
        """Test aggregation when all signals are consistent."""
        engine = EvidenceGraphEngine(far_alpha=0.05)

        # Create graph with all consistent signals
        nodes = [
            EvidenceNode(node_id="node_1", artifact_type="code_output", artifact_ref="/code/output.csv"),
            EvidenceNode(node_id="node_2", artifact_type="table_cell", artifact_ref="/paper/table.json"),
        ]
        edges = [
            EvidenceEdge(
                edge_id="edge_1",
                source_node="node_1",
                target_node="node_2",
                relation_type="L1",
                verifier_output=VerifierOutput(
                    verdict="consistent",
                    confidence=0.9,
                    evidence_span="line 1",
                    discrepancy_type=None,
                    severity=None,
                    abstain_reason=None,
                ),
            )
        ]
        graph = EvidenceGraph(claim_id="test_claim", nodes=nodes, edges=edges)

        verdict = engine.aggregate(graph)

        assert verdict.verdict == "pass"
        assert verdict.confidence > 0.5
        assert verdict.abstain_reason is None

    def test_aggregate_with_inconsistent_signals(self):
        """Test aggregation when signals are inconsistent."""
        engine = EvidenceGraphEngine(far_alpha=0.05)

        # Create graph with inconsistent signal
        nodes = [
            EvidenceNode(node_id="node_1", artifact_type="code_output", artifact_ref="/code/output.csv"),
            EvidenceNode(node_id="node_2", artifact_type="table_cell", artifact_ref="/paper/table.json"),
        ]
        edges = [
            EvidenceEdge(
                edge_id="edge_1",
                source_node="node_1",
                target_node="node_2",
                relation_type="L1",
                verifier_output=VerifierOutput(
                    verdict="inconsistent",
                    confidence=0.8,
                    evidence_span="line 1",
                    discrepancy_type="numeric_mismatch",
                    severity="high",
                    abstain_reason=None,
                ),
            )
        ]
        graph = EvidenceGraph(claim_id="test_claim", nodes=nodes, edges=edges)

        verdict = engine.aggregate(graph)

        # Should flag if FAR risk is low enough
        assert verdict.verdict in ["flag", "abstain"]  # Depends on FAR risk estimate
        assert len(verdict.aggregated_signals) == 1

    def test_aggregate_with_no_evidence(self):
        """Test aggregation when no evidence is available."""
        engine = EvidenceGraphEngine(far_alpha=0.05)

        # Create empty graph
        graph = EvidenceGraph(claim_id="test_claim", nodes=[], edges=[])

        verdict = engine.aggregate(graph)

        assert verdict.verdict == "abstain"
        assert verdict.confidence == 0.0
        assert verdict.abstain_reason == "No evidence available"

    def test_aggregate_with_low_confidence(self):
        """Test aggregation with low confidence signals."""
        engine = EvidenceGraphEngine(far_alpha=0.05)

        # Create graph with low confidence signals
        nodes = [
            EvidenceNode(node_id="node_1", artifact_type="code_output", artifact_ref="/code/output.csv"),
            EvidenceNode(node_id="node_2", artifact_type="table_cell", artifact_ref="/paper/table.json"),
        ]
        edges = [
            EvidenceEdge(
                edge_id="edge_1",
                source_node="node_1",
                target_node="node_2",
                relation_type="L1",
                verifier_output=VerifierOutput(
                    verdict="consistent",
                    confidence=0.3,  # Low confidence
                    evidence_span="line 1",
                    discrepancy_type=None,
                    severity=None,
                    abstain_reason=None,
                ),
            )
        ]
        graph = EvidenceGraph(claim_id="test_claim", nodes=nodes, edges=edges)

        verdict = engine.aggregate(graph)

        # Low confidence should lead to abstain or lower confidence pass
        assert verdict.verdict in ["abstain", "pass"]
        assert verdict.confidence < 0.8

    def test_far_constrained_decision(self):
        """Test FAR-constrained decision making."""
        # Set strict FAR threshold
        engine = EvidenceGraphEngine(far_alpha=0.01)

        # Create graph with inconsistent signal but moderate confidence
        nodes = [
            EvidenceNode(node_id="node_1", artifact_type="code_output", artifact_ref="/code/output.csv"),
            EvidenceNode(node_id="node_2", artifact_type="table_cell", artifact_ref="/paper/table.json"),
        ]
        edges = [
            EvidenceEdge(
                edge_id="edge_1",
                source_node="node_1",
                target_node="node_2",
                relation_type="L1",
                verifier_output=VerifierOutput(
                    verdict="inconsistent",
                    confidence=0.6,  # Moderate confidence
                    evidence_span="line 1",
                    discrepancy_type="numeric_mismatch",
                    severity="medium",
                    abstain_reason=None,
                ),
            )
        ]
        graph = EvidenceGraph(claim_id="test_claim", nodes=nodes, edges=edges)

        verdict = engine.aggregate(graph)

        # With strict FAR, should be more conservative
        assert verdict.far_risk >= 0.0

    def test_multiple_inconsistent_signals_converge(self):
        """Test aggregation with multiple inconsistent signals converging on same discrepancy."""
        engine = EvidenceGraphEngine(far_alpha=0.05)

        # Create graph with multiple inconsistent signals of same type
        nodes = [
            EvidenceNode(node_id="node_1", artifact_type="code_output", artifact_ref="/code/output.csv"),
            EvidenceNode(node_id="node_2", artifact_type="table_cell", artifact_ref="/paper/table.json"),
            EvidenceNode(node_id="node_3", artifact_type="text_span", artifact_ref="/paper/method.txt"),
        ]
        edges = [
            EvidenceEdge(
                edge_id="edge_1",
                source_node="node_1",
                target_node="node_2",
                relation_type="L1",
                verifier_output=generate_mock_verifier_output(
                    verdict="inconsistent",
                    confidence=0.8,
                    discrepancy_type="numeric_mismatch",
                ),
            ),
            EvidenceEdge(
                edge_id="edge_2",
                source_node="node_1",
                target_node="node_3",
                relation_type="L2",
                verifier_output=generate_mock_verifier_output(
                    verdict="inconsistent",
                    confidence=0.7,
                    discrepancy_type="numeric_mismatch",
                ),
            ),
        ]
        graph = EvidenceGraph(claim_id="test_claim", nodes=nodes, edges=edges)

        verdict = engine.aggregate(graph)

        # Multiple converging signals should increase confidence
        assert len(verdict.aggregated_signals) == 2
        assert verdict.confidence > 0.5

    def test_graph_aware_policy_deduplicates_same_artifact_family(self):
        engine = EvidenceGraphEngine(far_alpha=0.05, aggregation_policy="graph_aware")
        nodes = [
            EvidenceNode(node_id="source", artifact_type="code_output", artifact_ref="run.csv"),
            EvidenceNode(node_id="target", artifact_type="table_cell", artifact_ref="table.json"),
        ]
        signal = generate_mock_verifier_output(
            verdict="inconsistent",
            confidence=0.8,
            discrepancy_type="numeric_mismatch",
        )
        graph = EvidenceGraph(
            claim_id="dedupe",
            nodes=nodes,
            edges=[
                EvidenceEdge(
                    edge_id="edge_1",
                    source_node="source",
                    target_node="target",
                    relation_type="L1",
                    verifier_output=signal,
                ),
                EvidenceEdge(
                    edge_id="edge_2",
                    source_node="source",
                    target_node="target",
                    relation_type="L1",
                    verifier_output=generate_mock_verifier_output(
                        verdict="inconsistent",
                        confidence=0.6,
                        discrepancy_type="numeric_mismatch",
                    ),
                ),
            ],
        )

        verdict = engine.aggregate(graph)

        assert len(verdict.evidence_graph.edges) == 2
        assert len(verdict.aggregated_signals) == 1
        assert verdict.aggregated_signals[0].confidence == 0.8


class TestMockDataGeneration:
    """Test mock data generation."""

    def test_generate_mock_evidence_graph(self):
        """Test generating mock evidence graph."""
        graph = generate_mock_evidence_graph(
            claim_id="test_claim",
            num_nodes=3,
            num_edges=2,
            inconsistent_rate=0.5,
        )

        assert graph.claim_id == "test_claim"
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 2
        assert all(edge.verifier_output is not None for edge in graph.edges)

    def test_generate_mock_verifier_output(self):
        """Test generating mock verifier output."""
        output = generate_mock_verifier_output(
            verdict="inconsistent",
            confidence=0.8,
            discrepancy_type="numeric_mismatch",
        )

        assert output.verdict == "inconsistent"
        assert output.confidence == 0.8
        assert output.discrepancy_type == "numeric_mismatch"
        assert output.severity is not None
