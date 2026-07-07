"""Tests for 5-gate visual finding pipeline (PRD Phase 1)."""

from __future__ import annotations

from engine.static_audit.visual_pipeline.gates import (
    GATE_PIPELINE,
    GateContext,
    GateResult,
    GateVerdict,
    artifact_quality_gate,
    build_gate_context_from_relationship,
    build_gate_context_from_trufor,
    gate_result_to_finding,
    geometry_verification_gate,
    local_evidence_gate,
    modality_gate,
    run_gate_pipeline,
    semantic_review_gate,
)


# ---------------------------------------------------------------------------
# Gate pipeline structure
# ---------------------------------------------------------------------------


class TestGatePipelineStructure:
    """Tests for the pipeline structure."""

    def test_pipeline_has_five_gates(self):
        """The pipeline must contain exactly 5 gates."""
        assert len(GATE_PIPELINE) == 5

    def test_gate_verdict_values(self):
        """GateVerdict has expected values."""
        assert GateVerdict.PASS == "pass"
        assert GateVerdict.SKIP == "skip"
        assert GateVerdict.CAP == "cap"
        assert GateVerdict.REJECT == "reject"
        assert GateVerdict.DEMOTE == "demote"


# ---------------------------------------------------------------------------
# Gate 1: Modality Gate
# ---------------------------------------------------------------------------


class TestModalityGate:
    """Tests for modality_gate."""

    def test_exact_duplicate_always_passes(self):
        """exact_duplicate is never skipped regardless of panel type."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="exact_duplicate",
            raw_score=1.0,
            normalized_score=1.0,
            panel_type="Graphs",
            source_panel={"extraction_confidence": 0.9},
            target_panel={"extraction_confidence": 0.9},
        )
        result = modality_gate(ctx)
        assert result.verdict == GateVerdict.PASS

    def test_dhash_similar_always_passes(self):
        """dhash_similar is never skipped regardless of panel type."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="dhash_similar",
            raw_score=0.6,
            normalized_score=0.6,
            panel_type="Graphs",
            source_panel={"extraction_confidence": 0.9},
        )
        result = modality_gate(ctx)
        assert result.verdict == GateVerdict.PASS

    def test_copy_move_on_graphs_skipped(self):
        """copy_move on Graphs panel is skipped when confidence is high."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="copy_move_single",
            raw_score=0.8,
            normalized_score=0.8,
            panel_type="Graphs",
            source_panel={"extraction_confidence": 0.9},
            target_panel={"extraction_confidence": 0.9},
        )
        result = modality_gate(ctx)
        assert result.verdict == GateVerdict.SKIP
        assert "Graphs" in result.skip_reason

    def test_copy_move_on_graphs_low_confidence_passes(self):
        """copy_move on Graphs panel passes when extraction confidence is low."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="copy_move_single",
            raw_score=0.8,
            normalized_score=0.8,
            panel_type="Graphs",
            source_panel={"extraction_confidence": 0.3},
            target_panel={"extraction_confidence": 0.3},
        )
        result = modality_gate(ctx)
        assert result.verdict == GateVerdict.PASS

    def test_copy_move_on_blots_passes(self):
        """copy_move on Blots panel always passes."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="copy_move_cross",
            raw_score=0.8,
            normalized_score=0.8,
            panel_type="Blots",
        )
        result = modality_gate(ctx)
        assert result.verdict == GateVerdict.PASS

    def test_overlap_reuse_on_flow_cytometry_skipped(self):
        """overlap_reuse on Flow Cytometry is skipped with high confidence."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="overlap_reuse_cross_panel",
            raw_score=0.7,
            normalized_score=0.7,
            panel_type="Flow Cytometry",
            source_panel={"extraction_confidence": 0.8},
        )
        result = modality_gate(ctx)
        assert result.verdict == GateVerdict.SKIP

    def test_unknown_source_type_passes(self):
        """Unknown source types are not skipped."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="some_unknown_type",
            raw_score=0.5,
            normalized_score=0.5,
            panel_type="Graphs",
        )
        result = modality_gate(ctx)
        assert result.verdict == GateVerdict.PASS


# ---------------------------------------------------------------------------
# Gate 2: Artifact Quality Gate
# ---------------------------------------------------------------------------


class TestArtifactQualityGate:
    """Tests for artifact_quality_gate."""

    def test_normal_quality_passes(self):
        """Normal extraction quality passes through unchanged."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="copy_move_single",
            raw_score=0.8,
            normalized_score=0.8,
            source_panel={"extraction_method": "contour_edge_detection"},
            target_panel={"extraction_method": "contour_edge_detection"},
        )
        prev = GateResult(displayed_score=0.8, risk_level="high")
        result = artifact_quality_gate(ctx, prev)
        assert result.displayed_score == 0.8
        assert result.risk_level == "high"

    def test_whole_figure_fallback_caps_score(self):
        """whole_figure_fallback caps displayed_score to 0.39."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="copy_move_single",
            raw_score=0.8,
            normalized_score=0.8,
            source_panel={"extraction_method": "whole_figure_fallback"},
            target_panel={"extraction_method": "contour_edge_detection"},
        )
        prev = GateResult(displayed_score=0.8, risk_level="high")
        result = artifact_quality_gate(ctx, prev)
        assert result.displayed_score == 0.39
        assert result.risk_level == "medium"
        assert any("whole_figure_fallback" in a for a in result.confidence_adjustments)


# ---------------------------------------------------------------------------
# Gate 3: Local Evidence Gate
# ---------------------------------------------------------------------------


class TestLocalEvidenceGate:
    """Tests for local_evidence_gate."""

    def test_score_below_threshold_rejected(self):
        """Score below threshold is REJECT."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="copy_move_single",
            raw_score=0.3,
            normalized_score=0.3,
            high_score_threshold=0.4,
        )
        prev = GateResult(displayed_score=0.3)
        result = local_evidence_gate(ctx, prev)
        assert result.verdict == GateVerdict.REJECT
        assert "threshold" in result.skip_reason

    def test_score_at_threshold_passes(self):
        """Score at threshold passes."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="copy_move_single",
            raw_score=0.4,
            normalized_score=0.4,
            high_score_threshold=0.4,
        )
        prev = GateResult(displayed_score=0.4)
        result = local_evidence_gate(ctx, prev)
        assert result.verdict == GateVerdict.PASS

    def test_overlap_reuse_capped_at_high(self):
        """overlap_reuse_cross_panel risk is capped at high (never critical)."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="overlap_reuse_cross_panel",
            raw_score=0.9,
            normalized_score=0.9,
            high_score_threshold=0.4,
        )
        prev = GateResult(displayed_score=0.9)
        result = local_evidence_gate(ctx, prev)
        assert result.risk_level in ("high", "medium", "low")
        assert result.risk_level != "critical"


# ---------------------------------------------------------------------------
# Gate 4: Geometry Verification Gate
# ---------------------------------------------------------------------------


class TestGeometryVerificationGate:
    """Tests for geometry_verification_gate."""

    def test_non_demotable_always_passes(self):
        """Non-demotable categories pass through."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="copy_move_single",
            raw_score=0.8,
            normalized_score=0.8,
            corroboration_families=frozenset(),
        )
        prev = GateResult(displayed_score=0.8, risk_level="high")
        result = geometry_verification_gate(ctx, prev)
        assert result.verdict == GateVerdict.PASS

    def test_demotable_without_corroboration_demoted(self):
        """Demotable category without corroboration is DEMOTE."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="exact_duplicate",
            raw_score=1.0,
            normalized_score=1.0,
            corroboration_families=frozenset(),
        )
        prev = GateResult(displayed_score=1.0, risk_level="high")
        result = geometry_verification_gate(ctx, prev)
        assert result.verdict == GateVerdict.DEMOTE
        assert "SHA-256" in result.skip_reason

    def test_demotable_with_copy_move_corroboration_passes(self):
        """Demotable category with copy_move corroboration passes."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="exact_duplicate",
            raw_score=1.0,
            normalized_score=1.0,
            corroboration_families=frozenset({"copy_move"}),
        )
        prev = GateResult(displayed_score=1.0, risk_level="high")
        result = geometry_verification_gate(ctx, prev)
        assert result.verdict == GateVerdict.PASS

    def test_trufor_without_corroboration_demoted(self):
        """TruFor without corroboration at same figure scope is DEMOTE."""
        ctx = GateContext(
            source_panel_id="",
            target_panel_id="",
            source_type="forged_region_suspicious",
            raw_score=0.9,
            normalized_score=0.9,
            corroboration_families=frozenset(),
        )
        prev = GateResult(displayed_score=0.9, risk_level="high")
        result = geometry_verification_gate(ctx, prev)
        assert result.verdict == GateVerdict.DEMOTE


# ---------------------------------------------------------------------------
# Gate 5: Semantic Review Gate
# ---------------------------------------------------------------------------


class TestSemanticReviewGate:
    """Tests for semantic_review_gate."""

    def test_pass_generates_summary(self):
        """PASS verdict generates summary, benign_explanations, questions."""
        ctx = GateContext(
            source_panel_id="PE-001",
            target_panel_id="PE-002",
            source_type="copy_move_single",
            raw_score=0.8,
            normalized_score=0.8,
        )
        prev = GateResult(
            verdict=GateVerdict.PASS, risk_level="high", displayed_score=0.8
        )
        result = semantic_review_gate(ctx, prev)
        assert result.summary
        assert len(result.benign_explanations) > 0
        assert len(result.manual_review_questions) > 0

    def test_flip_detection_adds_question(self):
        """Flip detection adds a review question."""
        ctx = GateContext(
            source_panel_id="PE-001",
            target_panel_id="PE-002",
            source_type="copy_move_single",
            raw_score=0.8,
            normalized_score=0.8,
            flip_detected=True,
        )
        prev = GateResult(
            verdict=GateVerdict.PASS, risk_level="high", displayed_score=0.8
        )
        result = semantic_review_gate(ctx, prev)
        assert any("翻转" in q for q in result.manual_review_questions)
        assert "[FLIP DETECTED]" in result.summary

    def test_non_passing_skips_text_generation(self):
        """Non-passing verdicts skip text generation."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="copy_move_single",
            raw_score=0.8,
            normalized_score=0.8,
        )
        prev = GateResult(verdict=GateVerdict.SKIP, skip_reason="test")
        result = semantic_review_gate(ctx, prev)
        assert result.summary == ""
        assert result.benign_explanations == []

    def test_overlay_path_only_for_medium_plus(self):
        """Overlay path is only kept for medium+ risk."""
        ctx = GateContext(
            source_panel_id="PE-001",
            target_panel_id="PE-002",
            source_type="copy_move_single",
            raw_score=0.8,
            normalized_score=0.8,
            overlay_path="visual/overlay.png",
        )
        # Medium risk → overlay kept
        prev = GateResult(
            verdict=GateVerdict.PASS, risk_level="medium", displayed_score=0.8
        )
        result = semantic_review_gate(ctx, prev)
        assert result.overlay_path == "visual/overlay.png"

        # Low risk → overlay dropped
        prev_low = GateResult(
            verdict=GateVerdict.PASS, risk_level="low", displayed_score=0.8
        )
        result_low = semantic_review_gate(ctx, prev_low)
        assert result_low.overlay_path is None


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


class TestRunGatePipeline:
    """Tests for run_gate_pipeline end-to-end."""

    def test_high_score_copy_move_passes_all_gates(self):
        """High score copy_move on Blots passes all 5 gates."""
        ctx = build_gate_context_from_relationship(
            {
                "source_panel_id": "A",
                "target_panel_id": "B",
                "source_type": "copy_move_single",
                "score": 0.8,
                "match_method": "rootsift_magsac",
                "inlier_count": 42,
            },
            {"A": {"panel_type": "Blots"}, "B": {"panel_type": "Blots"}},
            0.4,
        )
        result = run_gate_pipeline(ctx)
        assert result.verdict == GateVerdict.PASS
        assert result.risk_level in ("high", "critical")
        assert result.summary

    def test_exact_duplicate_alone_demoted(self):
        """exact_duplicate without corroboration is demoted."""
        ctx = build_gate_context_from_relationship(
            {
                "source_panel_id": "A",
                "target_panel_id": "B",
                "source_type": "exact_duplicate",
                "score": 1.0,
            },
            {},
            0.4,
        )
        result = run_gate_pipeline(ctx)
        assert result.verdict == GateVerdict.DEMOTE

    def test_exact_duplicate_with_copy_move_promoted(self):
        """exact_duplicate with copy_move corroboration is promoted."""
        ctx = build_gate_context_from_relationship(
            {
                "source_panel_id": "A",
                "target_panel_id": "B",
                "source_type": "exact_duplicate",
                "score": 1.0,
            },
            {},
            0.4,
            corroboration_index={"panel:A:B": {"copy_move"}},
        )
        result = run_gate_pipeline(ctx)
        assert result.verdict == GateVerdict.PASS

    def test_low_score_rejected(self):
        """Low score finding is rejected by local_evidence_gate."""
        ctx = build_gate_context_from_relationship(
            {
                "source_panel_id": "A",
                "target_panel_id": "B",
                "source_type": "copy_move_single",
                "score": 0.2,
            },
            {},
            0.4,
        )
        result = run_gate_pipeline(ctx)
        assert result.verdict == GateVerdict.REJECT

    def test_graphs_panel_copy_move_skipped(self):
        """copy_move on Graphs panel is skipped by modality_gate."""
        ctx = build_gate_context_from_relationship(
            {
                "source_panel_id": "A",
                "target_panel_id": "B",
                "source_type": "copy_move_single",
                "score": 0.8,
            },
            {
                "A": {"panel_type": "Graphs", "extraction_confidence": 0.9},
                "B": {"panel_type": "Graphs", "extraction_confidence": 0.9},
            },
            0.4,
        )
        result = run_gate_pipeline(ctx)
        assert result.verdict == GateVerdict.SKIP

    def test_trufor_alone_demoted(self):
        """TruFor alone without corroboration is demoted."""
        ctx = build_gate_context_from_trufor(
            {
                "figure_id": "FE-0001",
                "integrity_score": 0.9,
                "is_suspicious": True,
                "forged_region_evidence_id": "FRE-0001",
            },
            {},
            0.5,
        )
        result = run_gate_pipeline(ctx)
        assert result.verdict == GateVerdict.DEMOTE


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------


class TestContextBuilders:
    """Tests for GateContext construction."""

    def test_relationship_context_basic(self):
        """Relationship context has expected fields."""
        ctx = build_gate_context_from_relationship(
            {
                "source_panel_id": "A",
                "target_panel_id": "B",
                "source_type": "copy_move_single",
                "score": 0.8,
                "overlay_path": "test.png",
                "flip_detected": True,
            },
            {},
            0.4,
        )
        assert ctx.source_panel_id == "A"
        assert ctx.target_panel_id == "B"
        assert ctx.source_type == "copy_move_single"
        assert ctx.normalized_score == 0.8
        assert ctx.overlay_path == "test.png"
        assert ctx.flip_detected is True
        assert not ctx.is_trufor

    def test_trufor_context_basic(self):
        """TruFor context has expected fields."""
        ctx = build_gate_context_from_trufor(
            {
                "figure_id": "FE-0001",
                "integrity_score": 0.9,
                "forged_region_evidence_id": "FRE-0001",
            },
            {},
            0.5,
        )
        assert ctx.figure_id == "FE-0001"
        assert ctx.integrity_score == 0.9
        assert ctx.is_trufor
        assert ctx.high_score_threshold == 0.5

    def test_score_clamped_to_01(self):
        """Score is clamped to [0, 1]."""
        ctx = build_gate_context_from_relationship(
            {
                "source_panel_id": "A",
                "target_panel_id": "B",
                "source_type": "x",
                "score": 1.5,
            },
            {},
            0.4,
        )
        assert ctx.normalized_score == 1.0

        ctx_neg = build_gate_context_from_relationship(
            {
                "source_panel_id": "A",
                "target_panel_id": "B",
                "source_type": "x",
                "score": -0.5,
            },
            {},
            0.4,
        )
        assert ctx_neg.normalized_score == 0.0


# ---------------------------------------------------------------------------
# Result → Finding conversion
# ---------------------------------------------------------------------------


class TestGateResultToFinding:
    """Tests for gate_result_to_finding."""

    def test_basic_conversion(self):
        """Basic conversion produces valid finding dict."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="copy_move_single",
            raw_score=0.8,
            normalized_score=0.8,
            relationship_id="IR-0001",
            match_method="rootsift_magsac",
        )
        result = GateResult(
            verdict=GateVerdict.PASS,
            risk_level="high",
            displayed_score=0.8,
            summary="Test summary",
            benign_explanations=["explanation 1"],
            manual_review_questions=["question 1"],
        )
        finding = gate_result_to_finding(ctx, result, 1)
        assert finding["finding_id"] == "VF-0001"
        assert finding["category"] == "copy_move_single"
        assert finding["risk_level"] == "high"
        assert finding["summary"] == "Test summary"
        assert finding["relationship_id"] == "IR-0001"

    def test_finding_id_sequential(self):
        """Finding IDs are sequential."""
        ctx = GateContext(
            source_panel_id="A",
            target_panel_id="B",
            source_type="copy_move_single",
            raw_score=0.8,
            normalized_score=0.8,
        )
        result = GateResult(verdict=GateVerdict.PASS, risk_level="high")
        f1 = gate_result_to_finding(ctx, result, 1)
        f2 = gate_result_to_finding(ctx, result, 2)
        assert f1["finding_id"] == "VF-0001"
        assert f2["finding_id"] == "VF-0002"
