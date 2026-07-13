"""Veritas-Auditor: Risk-controlled provenance-structured reference auditor.

Core algorithm: evidence graph aggregation + FAR-constrained selective prediction.
"""

from engine.reproduction.evidence_graph import (
    EvidenceGraphEngine,
    VerifierAwareEvidenceGraphEngine,
)
from engine.reproduction.models import (
    ClaimRelationAnnotation,
    ClaimVerdict,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    ExtractionEvidence,
    VerifierOutput,
)

__all__ = [
    "ClaimRelationAnnotation",
    "ClaimVerdict",
    "EvidenceEdge",
    "EvidenceGraph",
    "EvidenceGraphEngine",
    "EvidenceNode",
    "ExtractionEvidence",
    "VerifierAwareEvidenceGraphEngine",
    "VerifierOutput",
]
