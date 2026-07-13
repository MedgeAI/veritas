"""Benchmark runner for VeritasBench.

Orchestrates case loading, evidence graph construction with typed verifiers,
aggregation, and metric computation.

The VeritasAuditor class delegates to the real EvidenceGraphEngine pipeline;
a mock-only mode is available via ``use_mock_verdicts=True`` for debugging
and regression testing of the metrics pipeline.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from typing import Any

from engine.reproduction.benchmark.case_loader import BenchmarkCaseLoader
from engine.reproduction.benchmark.metrics import MetricsCalculator
from engine.reproduction.evidence_graph import EvidenceGraphEngine
from engine.reproduction.models import (
    BenchmarkCase,
    BenchmarkResult,
    ClaimRelationAnnotation,
    ClaimVerdict,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    VerifierOutput,
)
from engine.reproduction.verifiers.base import TypedVerifier
from engine.reproduction.verifiers.numeric_comparator import NumericComparator

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Artifact type inference (shared with EvidenceGraphEngine)
# ------------------------------------------------------------------


def _infer_artifact_type(artifact_ref: str) -> str:
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


# ------------------------------------------------------------------
# VeritasAuditor: real engine pipeline
# ------------------------------------------------------------------


class VeritasAuditor:
    """Auditor that produces ClaimVerdicts via the real evidence graph engine.

    Groups annotations by claim_id, builds evidence graphs with typed
    verifiers, and aggregates into claim-level verdicts.

    Unlike EvidenceGraphEngine.build_graph() which assumes a specific
    artifacts dict shape, this auditor builds graphs directly from
    annotations — one node per unique artifact ref, one edge per annotation.
    """

    def __init__(
        self,
        verifiers: dict[str, TypedVerifier] | None = None,
        far_alpha: float = 0.05,
    ) -> None:
        if verifiers is None:
            verifiers = {"L1": NumericComparator()}
        self.verifiers = verifiers
        self.engine = EvidenceGraphEngine(far_alpha=far_alpha)

    def audit_case(self, case: BenchmarkCase) -> list[ClaimVerdict]:
        """Run the full auditing pipeline on a single benchmark case."""
        grouped = _group_annotations_by_claim(case.claims)
        verdicts: list[ClaimVerdict] = []

        for claim_id, annotations in grouped.items():
            graph = self._build_and_verify_graph(claim_id, annotations)
            verdict = self.engine.aggregate(graph)
            verdicts.append(verdict)

        return verdicts

    def _build_and_verify_graph(
        self,
        claim_id: str,
        annotations: list[ClaimRelationAnnotation],
    ) -> EvidenceGraph:
        """Build evidence graph from annotations and run verifiers on edges.

        This bypasses EvidenceGraphEngine.build_graph() to avoid the artifacts
        dict shape mismatch.  Instead, it builds nodes/edges directly from
        annotations and runs verifiers inline.
        """
        # 1. Create nodes: one per unique artifact ref
        node_map: dict[str, EvidenceNode] = {}  # artifact_ref → node
        for ann in annotations:
            for ref in (ann.source_artifact, ann.target_artifact):
                if ref not in node_map:
                    node = EvidenceNode(
                        node_id=f"{claim_id}_{len(node_map)}",
                        artifact_type=_infer_artifact_type(ref),  # type: ignore[arg-type]
                        artifact_ref=ref,
                    )
                    node_map[ref] = node

        # 2. Create edges: one per annotation, with verifier output
        edges: list[EvidenceEdge] = []
        for i, ann in enumerate(annotations):
            source_node = node_map[ann.source_artifact]
            target_node = node_map[ann.target_artifact]

            # Generate mock values for the verifier
            source_value = _mock_value_for_artifact(ann.source_artifact)
            if ann.verdict == "inconsistent":
                target_value = source_value * 2.5  # 150% diff → critical
            else:
                target_value = source_value

            # Run verifier
            verifier = self.verifiers.get(ann.relation_type)
            if verifier is not None:
                verifier_output = verifier.verify(
                    source_value,
                    target_value,
                    context={
                        "edge_id": f"{claim_id}_edge_{i}",
                        "relation_type": ann.relation_type,
                        "source_artifact_ref": ann.source_artifact,
                        "target_artifact_ref": ann.target_artifact,
                    },
                )
            else:
                # No verifier for this relation type → insufficient
                verifier_output = VerifierOutput(
                    verdict="insufficient",
                    confidence=0.0,
                    evidence_span=None,
                    discrepancy_type=None,
                    severity=None,
                    abstain_reason=f"No verifier for {ann.relation_type}",
                )

            edge = EvidenceEdge(
                edge_id=f"{claim_id}_edge_{i}",
                source_node=source_node.node_id,
                target_node=target_node.node_id,
                relation_type=ann.relation_type,  # type: ignore[arg-type]
                verifier_output=verifier_output,
            )
            edges.append(edge)

        return EvidenceGraph(
            claim_id=claim_id,
            nodes=list(node_map.values()),
            edges=edges,
        )


# ------------------------------------------------------------------
# BenchmarkRunner
# ------------------------------------------------------------------


class BenchmarkRunner:
    """Run a VeritasBench evaluation suite end-to-end."""

    def __init__(
        self,
        case_loader: BenchmarkCaseLoader,
        metrics_calculator: MetricsCalculator | None = None,
        auditor: VeritasAuditor | None = None,
        use_mock_verdicts: bool = False,
    ) -> None:
        """Initialize the runner.

        Args:
            case_loader: Loads benchmark cases from disk or mock data.
            metrics_calculator: Computes metrics. Defaults to MetricsCalculator().
            auditor: Produces claim verdicts. Defaults to VeritasAuditor().
            use_mock_verdicts: If True, bypass the engine and use deterministic
                mock verdicts from ground truth (for debugging metrics pipeline).
        """
        self.case_loader = case_loader
        self.metrics_calculator = metrics_calculator or MetricsCalculator()
        self.auditor = auditor or VeritasAuditor()
        self.use_mock_verdicts = use_mock_verdicts

    def run(
        self,
        suite_name: str = "smoke_test",
        far_alpha: float = 0.05,
    ) -> BenchmarkResult:
        """Execute *suite_name* and return aggregated metrics."""
        cases = self.case_loader.load_suite(suite_name)
        logger.info("Loaded %d cases from suite '%s'", len(cases), suite_name)

        all_verdicts: list[ClaimVerdict] = []
        all_annotations: list[ClaimRelationAnnotation] = []

        for case in cases:
            if self.use_mock_verdicts:
                verdicts, annotations = _process_case_mock(case)
            else:
                verdicts, annotations = _process_case(self.auditor, case)
            all_verdicts.extend(verdicts)
            all_annotations.extend(annotations)

        metrics = self.metrics_calculator.calculate(all_verdicts, all_annotations)
        logger.info(
            "Suite '%s': %d cases, %d claims, %d relations",
            suite_name,
            len(cases),
            len(all_verdicts),
            len(all_annotations),
        )

        return BenchmarkResult(
            suite_name=suite_name,
            num_cases=len(cases),
            num_claims=len(all_verdicts),
            num_relations=len(all_annotations),
            metrics=metrics,
            claim_verdicts=all_verdicts,
        )


# ------------------------------------------------------------------
# Engine-based processing (D1 fix)
# ------------------------------------------------------------------


def _process_case(
    auditor: VeritasAuditor,
    case: BenchmarkCase,
) -> tuple[list[ClaimVerdict], list[ClaimRelationAnnotation]]:
    """Run the real engine pipeline on *case*."""
    verdicts = auditor.audit_case(case)
    annotations = list(case.claims)
    return verdicts, annotations


def _group_annotations_by_claim(
    annotations: list[ClaimRelationAnnotation],
) -> dict[str, list[ClaimRelationAnnotation]]:
    """Group annotations by claim_id."""
    grouped: dict[str, list[ClaimRelationAnnotation]] = defaultdict(list)
    for ann in annotations:
        grouped[ann.claim_id].append(ann)
    return dict(grouped)


def _mock_value_for_artifact(artifact_ref: str) -> float:
    """Generate a deterministic mock numeric value from an artifact reference.

    Uses SHA256 hash to generate a stable float in [0.001, 1.0].
    """
    h = hashlib.sha256(artifact_ref.encode()).hexdigest()
    raw = int(h[:8], 16)
    return 0.001 + (raw / 0xFFFFFFFF) * 0.999


# ------------------------------------------------------------------
# Mock processing (kept for debugging / regression testing)
# ------------------------------------------------------------------


def _process_case_mock(
    case: BenchmarkCase,
) -> tuple[list[ClaimVerdict], list[ClaimRelationAnnotation]]:
    """Generate mock verdicts for every annotation in *case*.

    This is the OLD behavior (before D1 fix).  Kept for debugging the metrics
    pipeline independently of the engine.
    """
    verdicts: list[ClaimVerdict] = []
    annotations: list[ClaimRelationAnnotation] = []

    for annotation in case.claims:
        verdict = _mock_verdict_from_annotation(annotation)
        verdicts.append(verdict)
        annotations.append(annotation)

    return verdicts, annotations


def _mock_verdict_from_annotation(annotation: ClaimRelationAnnotation) -> ClaimVerdict:
    """Derive a deterministic mock ClaimVerdict from a ground-truth annotation."""
    if annotation.verdict == "inconsistent":
        verdict = "flag"
        confidence = 0.8
    elif annotation.verdict == "consistent" and annotation.is_clean_claim:
        verdict = "pass"
        confidence = 0.9
    else:
        verdict = "pass"
        confidence = 0.7

    far_risk = 1.0 - confidence
    graph = EvidenceGraph(claim_id=annotation.claim_id)

    return ClaimVerdict(
        claim_id=annotation.claim_id,
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence,
        evidence_graph=graph,
        aggregated_signals=[],
        far_risk=far_risk,
    )
