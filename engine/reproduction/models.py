"""Core data models for Veritas-Auditor.

This module defines the data structures for claim-provenance consistency auditing:
- ExtractionEvidence: Provenance-anchored extraction from execution output
- EvidenceNode/Edge/Graph: Claim-level evidence graph
- VerifierOutput: Output from typed verifiers
- ClaimVerdict: Final claim-level decision (flag/pass/abstain)
- ClaimRelationAnnotation: Benchmark ground truth
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ExtractionEvidence:
    """Provenance-anchored extraction from execution output.

    Key constraints:
    - Every extracted value must anchor to an immutable artifact (stdout/stderr, output file) with hash
    - Every extracted value must include source_artifact, source_artifact_hash, source_span
    - Extractions without artifact anchor or with schema validation failure
      must not enter the deterministic fact layer
    """

    extraction_id: str
    claim_id: str
    row: int
    col: str
    extractor: Literal["deterministic_parser", "llm", "hybrid"]
    source_artifact: str  # Source file path
    source_artifact_hash: str  # SHA256
    source_span: str | None  # Line number, JSON path, etc.
    source_snippet: str | None  # Original snippet
    extracted_value: Any  # Extracted value
    normalized_value: Any  # Normalized value
    confidence: float  # 0-1
    validation_status: Literal["valid", "low_confidence", "missing_span", "invalid"]
    metadata: dict[str, Any] = field(default_factory=dict)  # model_id, prompt_version, schema_version


@dataclass
class EvidenceNode:
    """Evidence graph node (artifact)."""

    node_id: str
    artifact_type: Literal["data", "code_output", "table_cell", "figure_mark", "text_span"]
    artifact_ref: str  # Reference to the actual artifact
    artifact_hash: str | None = None


@dataclass
class VerifierOutput:
    """Output from a typed verifier.

    Each verifier runs on an evidence graph edge and produces this output.
    """

    verdict: Literal["consistent", "inconsistent", "insufficient"]
    confidence: float  # 0-1
    evidence_span: str | None  # Location of evidence
    discrepancy_type: str | None  # Type of discrepancy (if inconsistent)
    severity: Literal["low", "medium", "high", "critical"] | None
    abstain_reason: str | None  # Reason for abstention (if verdict is insufficient)


@dataclass
class EvidenceEdge:
    """Evidence graph edge (typed relation).

    Each edge represents a consistency relation between two artifacts.
    """

    edge_id: str
    source_node: str  # node_id
    target_node: str  # node_id
    relation_type: Literal["L1", "L2", "L3", "L4"]
    verifier_output: VerifierOutput | None = None  # Populated after verifier runs


@dataclass
class EvidenceGraph:
    """Claim-level evidence graph.

    G_c = (V_c, E_c) where V_c are artifact nodes and E_c are typed relations.
    """

    claim_id: str
    nodes: list[EvidenceNode] = field(default_factory=list)
    edges: list[EvidenceEdge] = field(default_factory=list)


@dataclass
class ClaimVerdict:
    """Claim-level final verdict from Veritas-Auditor.

    The verdict is one of:
    - flag: Evidence sufficient and FAR risk low
    - pass: No material inconsistency found
    - abstain: Evidence insufficient / artifact missing / verifier conflict
    """

    claim_id: str
    verdict: Literal["flag", "pass", "abstain"]
    confidence: float  # 0-1
    evidence_graph: EvidenceGraph
    aggregated_signals: list[VerifierOutput]
    far_risk: float  # False accusation risk estimate
    abstain_reason: str | None = None


@dataclass
class ClaimRelationAnnotation:
    """Benchmark ground truth annotation.

    Each annotation is a claim-relation instance:
    (claim_atom, source_artifact, target_artifact, relation_type, verdict, ...)
    """

    annotation_id: str
    claim_id: str
    claim_atom: str  # Structured claim atom description
    source_artifact: str  # Source artifact reference
    target_artifact: str  # Target artifact reference
    relation_type: Literal["L1", "L2", "L3", "L4"]
    verdict: Literal["consistent", "inconsistent", "insufficient"]
    discrepancy_type: str | None = None
    evidence_span: str | None = None
    severity: Literal["low", "medium", "high", "critical"] | None = None
    annotator_id: str = ""
    annotation_timestamp: str = ""
    is_clean_claim: bool = False  # Whether this is a clean claim (for FAR measurement)


@dataclass
class BenchmarkCase:
    """A paper-level case in VeritasBench."""

    case_id: str
    paper_title: str
    paper_authors: list[str]
    artifacts: dict[str, Any]  # artifact_id -> artifact metadata
    claims: list[ClaimRelationAnnotation]
    observations: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)  # language, statistical_method, etc.


@dataclass
class BenchmarkResult:
    """Result from running VeritasBench."""

    suite_name: str
    num_cases: int
    num_claims: int
    num_relations: int
    metrics: dict[str, float]
    claim_verdicts: list[ClaimVerdict]
    risk_coverage_curve: list[dict[str, float]] = field(default_factory=list)
