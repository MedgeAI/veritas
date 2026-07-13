"""Mock data generator for Veritas-Auditor development.

This module generates synthetic claim-relation instances with known ground truth
for development and testing before real benchmark data is available.
"""

import random
import uuid
from typing import Any

from engine.reproduction.models import (
    BenchmarkCase,
    ClaimRelationAnnotation,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    VerifierOutput,
)


def generate_mock_claim_id() -> str:
    """Generate a unique claim ID."""
    return f"claim_{uuid.uuid4().hex[:8]}"


def generate_mock_annotation_id() -> str:
    """Generate a unique annotation ID."""
    return f"ann_{uuid.uuid4().hex[:8]}"


def _mock_evidence_span(relation_type: str, source: str, target: str) -> str:
    """Generate a canonical evidence span matching NumericComparator format.

    Format: ``{relation_type}:{source_artifact}->{target_artifact}``

    This must match the format produced by
    ``engine.reproduction.verifiers.numeric_comparator._build_evidence_span``
    so that GT and predicted spans can be compared for evidence_precision/recall.
    """
    return f"{relation_type}:{source}->{target}"


def generate_mock_evidence_node(
    artifact_type: str = "table_cell",
    node_id: str | None = None,
) -> EvidenceNode:
    """Generate a mock evidence node."""
    if node_id is None:
        node_id = f"node_{uuid.uuid4().hex[:8]}"
    return EvidenceNode(
        node_id=node_id,
        artifact_type=artifact_type,  # type: ignore
        artifact_ref=f"/mock/artifacts/{node_id}.json",
        artifact_hash=f"sha256:{uuid.uuid4().hex}",
    )


def generate_mock_verifier_output(
    verdict: str = "consistent",
    confidence: float | None = None,
    discrepancy_type: str | None = None,
) -> VerifierOutput:
    """Generate a mock verifier output."""
    if confidence is None:
        confidence = random.uniform(0.7, 1.0) if verdict == "consistent" else random.uniform(0.3, 0.7)

    return VerifierOutput(
        verdict=verdict,  # type: ignore
        confidence=confidence,
        evidence_span=f"line {random.randint(1, 100)}",
        discrepancy_type=discrepancy_type if verdict == "inconsistent" else None,
        severity="medium" if verdict == "inconsistent" else None,
        abstain_reason=None,
    )


def generate_mock_evidence_edge(
    source_node: EvidenceNode,
    target_node: EvidenceNode,
    relation_type: str = "L1",
    verifier_output: VerifierOutput | None = None,
) -> EvidenceEdge:
    """Generate a mock evidence edge."""
    if verifier_output is None:
        # Default to consistent for testing
        verifier_output = generate_mock_verifier_output(verdict="consistent")

    return EvidenceEdge(
        edge_id=f"edge_{uuid.uuid4().hex[:8]}",
        source_node=source_node.node_id,
        target_node=target_node.node_id,
        relation_type=relation_type,  # type: ignore
        verifier_output=verifier_output,
    )


def generate_mock_evidence_graph(
    claim_id: str,
    num_nodes: int = 3,
    num_edges: int = 2,
    inconsistent_rate: float = 0.2,
) -> EvidenceGraph:
    """Generate a mock evidence graph for testing.

    Args:
        claim_id: Claim ID
        num_nodes: Number of nodes in the graph
        num_edges: Number of edges in the graph
        inconsistent_rate: Fraction of edges that are inconsistent

    Returns:
        EvidenceGraph with mock nodes and edges
    """
    # Generate nodes
    nodes = []
    artifact_types = ["data", "code_output", "table_cell", "figure_mark", "text_span"]
    for i in range(num_nodes):
        artifact_type = artifact_types[i % len(artifact_types)]
        node = generate_mock_evidence_node(
            artifact_type=artifact_type,
            node_id=f"{claim_id}_node_{i}",
        )
        nodes.append(node)

    # Generate edges
    edges = []
    relation_types = ["L1", "L2", "L3", "L4"]
    for i in range(num_edges):
        source_idx = i % len(nodes)
        target_idx = (i + 1) % len(nodes)

        # Determine verdict based on inconsistent_rate
        if random.random() < inconsistent_rate:
            verdict = "inconsistent"
            discrepancy_type = random.choice(["numeric_mismatch", "method_mismatch", "encoding_error"])
        else:
            verdict = "consistent"
            discrepancy_type = None

        verifier_output = generate_mock_verifier_output(
            verdict=verdict,
            discrepancy_type=discrepancy_type,
        )

        edge = generate_mock_evidence_edge(
            source_node=nodes[source_idx],
            target_node=nodes[target_idx],
            relation_type=relation_types[i % len(relation_types)],
            verifier_output=verifier_output,
        )
        edges.append(edge)

    return EvidenceGraph(claim_id=claim_id, nodes=nodes, edges=edges)


def generate_mock_claims(num_claims: int = 50) -> list[dict[str, Any]]:
    """Generate mock claims with known ground truth.

    Args:
        num_claims: Number of claims to generate

    Returns:
        List of mock claim dictionaries with ground truth annotations
    """
    claims = []
    fraud_patterns = ["clean", "numeric_tampering", "method_mismatch", "data_transform_undeclared"]

    for i in range(num_claims):
        claim_id = f"claim_{i:03d}"
        fraud_pattern = random.choice(fraud_patterns)

        # Generate annotations based on fraud pattern
        annotations = []
        if fraud_pattern == "clean":
            # All relations consistent
            for level in ["L1", "L2"]:
                src = f"/mock/code/output_{i}.csv"
                tgt = f"/mock/paper/table_{i}.json"
                annotations.append(
                    ClaimRelationAnnotation(
                        annotation_id=generate_mock_annotation_id(),
                        claim_id=claim_id,
                        claim_atom=f"Mock claim {i} - {level}",
                        source_artifact=src,
                        target_artifact=tgt,
                        relation_type=level,  # type: ignore
                        verdict="consistent",
                        evidence_span=_mock_evidence_span(level, src, tgt),
                        is_clean_claim=True,
                    )
                )
        elif fraud_pattern == "numeric_tampering":
            # L1 inconsistent, L2 consistent
            src_l1 = f"/mock/code/output_{i}.csv"
            tgt_l1 = f"/mock/paper/table_{i}.json"
            annotations.append(
                ClaimRelationAnnotation(
                    annotation_id=generate_mock_annotation_id(),
                    claim_id=claim_id,
                    claim_atom=f"Mock claim {i} - L1 (numeric mismatch)",
                    source_artifact=src_l1,
                    target_artifact=tgt_l1,
                    relation_type="L1",
                    verdict="inconsistent",
                    discrepancy_type="numeric_mismatch",
                    severity="high",
                    evidence_span=_mock_evidence_span("L1", src_l1, tgt_l1),
                    is_clean_claim=False,
                )
            )
            src_l2 = f"/mock/paper/method_{i}.txt"
            tgt_l2 = f"/mock/code/analysis_{i}.py"
            annotations.append(
                ClaimRelationAnnotation(
                    annotation_id=generate_mock_annotation_id(),
                    claim_id=claim_id,
                    claim_atom=f"Mock claim {i} - L2 (consistent)",
                    source_artifact=src_l2,
                    target_artifact=tgt_l2,
                    relation_type="L2",
                    verdict="consistent",
                    evidence_span=_mock_evidence_span("L2", src_l2, tgt_l2),
                    is_clean_claim=False,
                )
            )
        elif fraud_pattern == "method_mismatch":
            # L1 consistent, L2 inconsistent
            src_l1 = f"/mock/code/output_{i}.csv"
            tgt_l1 = f"/mock/paper/table_{i}.json"
            annotations.append(
                ClaimRelationAnnotation(
                    annotation_id=generate_mock_annotation_id(),
                    claim_id=claim_id,
                    claim_atom=f"Mock claim {i} - L1 (consistent)",
                    source_artifact=src_l1,
                    target_artifact=tgt_l1,
                    relation_type="L1",
                    verdict="consistent",
                    evidence_span=_mock_evidence_span("L1", src_l1, tgt_l1),
                    is_clean_claim=False,
                )
            )
            src_l2 = f"/mock/paper/method_{i}.txt"
            tgt_l2 = f"/mock/code/analysis_{i}.py"
            annotations.append(
                ClaimRelationAnnotation(
                    annotation_id=generate_mock_annotation_id(),
                    claim_id=claim_id,
                    claim_atom=f"Mock claim {i} - L2 (method mismatch)",
                    source_artifact=src_l2,
                    target_artifact=tgt_l2,
                    relation_type="L2",
                    verdict="inconsistent",
                    discrepancy_type="method_mismatch",
                    severity="medium",
                    evidence_span=_mock_evidence_span("L2", src_l2, tgt_l2),
                    is_clean_claim=False,
                )
            )

        claims.append(
            {
                "claim_id": claim_id,
                "claim_atom": f"Mock claim {i} - {fraud_pattern}",
                "fraud_pattern": fraud_pattern,
                "annotations": annotations,
                "evidence_graph": generate_mock_evidence_graph(
                    claim_id=claim_id,
                    inconsistent_rate=0.0 if fraud_pattern == "clean" else 0.5,
                ),
            }
        )

    return claims


def generate_mock_benchmark_case(
    case_id: str = "case_001",
    num_claims: int = 5,
) -> BenchmarkCase:
    """Generate a mock benchmark case.

    Args:
        case_id: Case ID
        num_claims: Number of claims in the case

    Returns:
        BenchmarkCase with mock data
    """
    claims = []
    for i in range(num_claims):
        claim_id = f"{case_id}_claim_{i:03d}"
        src = f"/mock/code/output_{i}.csv"
        tgt = f"/mock/paper/table_{i}.json"
        annotations = [
            ClaimRelationAnnotation(
                annotation_id=generate_mock_annotation_id(),
                claim_id=claim_id,
                claim_atom=f"Mock claim {i}",
                source_artifact=src,
                target_artifact=tgt,
                relation_type="L1",
                verdict="consistent" if i % 2 == 0 else "inconsistent",
                discrepancy_type=None if i % 2 == 0 else "numeric_mismatch",
                evidence_span=_mock_evidence_span("L1", src, tgt),
                is_clean_claim=(i % 2 == 0),
            )
        ]
        claims.extend(annotations)

    return BenchmarkCase(
        case_id=case_id,
        paper_title=f"Mock Paper {case_id}",
        paper_authors=["Author A", "Author B"],
        artifacts={
            "paper_pdf": f"/mock/papers/{case_id}.pdf",
            "code": f"/mock/code/{case_id}/",
            "source_data": f"/mock/data/{case_id}.xlsx",
        },
        claims=claims,
        metadata={
            "language": "python",
            "statistical_methods": ["t-test", "regression"],
            "num_claims": num_claims,
        },
    )
