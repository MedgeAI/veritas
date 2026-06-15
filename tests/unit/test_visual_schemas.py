"""Tests for visual evidence schemas."""

from __future__ import annotations

from engine.static_audit.visual_schemas import (
    FigureEvidence,
    FORBIDDEN_PHRASES,
    ImageRelationship,
    PanelEvidence,
    VISUAL_SCHEMA_VERSION,
    VisualFinding,
    check_language_compliance,
)


class TestVisualSchemaVersion:
    """Test schema version consistency."""

    def test_visual_schema_version(self):
        """All schemas should have version 1.0."""
        assert VISUAL_SCHEMA_VERSION == "1.0"

    def test_forbidden_phrases_not_empty(self):
        """FORBIDDEN_PHRASES should contain at least some phrases."""
        assert len(FORBIDDEN_PHRASES) > 0


class TestFigureEvidence:
    """Test FigureEvidence schema."""

    def test_figure_evidence_round_trip(self):
        """FigureEvidence should serialize and deserialize correctly."""
        fig = FigureEvidence(
            figure_id="FE-0001",
            source_image_path="images/Figure1.png",
            label="Figure 1",
            caption="This is Figure 1",
            page_number=5,
            bbox=[100, 200, 300, 400],
            width=800,
            height=600,
            panel_count=4,
            metadata={"source": "mineru"},
        )
        data = fig.to_dict()
        fig2 = FigureEvidence.from_dict(data)
        assert fig2.figure_id == fig.figure_id
        assert fig2.source_image_path == fig.source_image_path
        assert fig2.label == fig.label
        assert fig2.caption == fig.caption
        assert fig2.page_number == fig.page_number
        assert fig2.bbox == fig.bbox
        assert fig2.width == fig.width
        assert fig2.height == fig.height
        assert fig2.panel_count == fig.panel_count
        assert fig2.metadata == fig.metadata

    def test_figure_evidence_validate_valid(self):
        """Valid FigureEvidence should pass validation."""
        fig = FigureEvidence(
            figure_id="FE-0001",
            source_image_path="images/Figure1.png",
            label="Figure 1",
            caption="This is Figure 1",
            page_number=5,
            bbox=[100, 200, 300, 400],
            width=800,
            height=600,
        )
        errors = fig.validate()
        assert errors == []

    def test_figure_evidence_validate_missing_required(self):
        """Missing required fields should fail validation."""
        fig = FigureEvidence(
            figure_id="",
            source_image_path="",
            label="Figure 1",
            caption="This is Figure 1",
            page_number=None,
            bbox=None,
            width=0,
            height=0,
        )
        errors = fig.validate()
        assert "figure_id is required" in errors
        assert "source_image_path is required" in errors
        assert any("width" in e for e in errors)
        assert any("height" in e for e in errors)

    def test_figure_evidence_validate_invalid_bbox(self):
        """Invalid bbox should fail validation."""
        fig = FigureEvidence(
            figure_id="FE-0001",
            source_image_path="images/Figure1.png",
            label="Figure 1",
            caption="This is Figure 1",
            page_number=5,
            bbox=[100, 200],  # Wrong length
            width=800,
            height=600,
        )
        errors = fig.validate()
        assert any("bbox" in e for e in errors)

    def test_figure_evidence_validate_negative_bbox(self):
        """Negative bbox coordinates should fail validation."""
        fig = FigureEvidence(
            figure_id="FE-0001",
            source_image_path="images/Figure1.png",
            label="Figure 1",
            caption="This is Figure 1",
            page_number=5,
            bbox=[-100, 200, 300, 400],  # Negative x
            width=800,
            height=600,
        )
        errors = fig.validate()
        assert any("bbox" in e for e in errors)


class TestPanelEvidence:
    """Test PanelEvidence schema."""

    def test_panel_evidence_round_trip(self):
        """PanelEvidence should serialize and deserialize correctly."""
        panel = PanelEvidence(
            panel_id="PE-0001-01",
            parent_figure_id="FE-0001",
            label="a",
            bbox=[10, 20, 100, 80],
            crop_path="panels/FE-0001/a.png",
            width=100,
            height=80,
            extraction_confidence=0.85,
            extraction_method="contour_edge_detection",
            metadata={"source": "panel_extraction"},
        )
        data = panel.to_dict()
        panel2 = PanelEvidence.from_dict(data)
        assert panel2.panel_id == panel.panel_id
        assert panel2.parent_figure_id == panel.parent_figure_id
        assert panel2.label == panel.label
        assert panel2.bbox == panel.bbox
        assert panel2.crop_path == panel.crop_path
        assert panel2.width == panel.width
        assert panel2.height == panel.height
        assert panel2.extraction_confidence == panel.extraction_confidence
        assert panel2.extraction_method == panel.extraction_method

    def test_panel_evidence_validate_valid(self):
        """Valid PanelEvidence should pass validation."""
        panel = PanelEvidence(
            panel_id="PE-0001-01",
            parent_figure_id="FE-0001",
            label="a",
            bbox=[10, 20, 100, 80],
            crop_path="panels/FE-0001/a.png",
            width=100,
            height=80,
            extraction_confidence=0.85,
            extraction_method="contour_edge_detection",
        )
        errors = panel.validate()
        assert errors == []

    def test_panel_evidence_validate_missing_parent(self):
        """Missing parent_figure_id should fail validation."""
        panel = PanelEvidence(
            panel_id="PE-0001-01",
            parent_figure_id="",
            label="a",
            bbox=[10, 20, 100, 80],
            crop_path="panels/FE-0001/a.png",
            width=100,
            height=80,
            extraction_confidence=0.85,
            extraction_method="contour_edge_detection",
        )
        errors = panel.validate()
        assert "parent_figure_id is required" in errors

    def test_panel_evidence_validate_invalid_confidence(self):
        """Invalid extraction_confidence should fail validation."""
        panel = PanelEvidence(
            panel_id="PE-0001-01",
            parent_figure_id="FE-0001",
            label="a",
            bbox=[10, 20, 100, 80],
            crop_path="panels/FE-0001/a.png",
            width=100,
            height=80,
            extraction_confidence=1.5,  # Out of range
            extraction_method="contour_edge_detection",
        )
        errors = panel.validate()
        assert any("extraction_confidence" in e for e in errors)


class TestVisualFinding:
    """Test VisualFinding schema."""

    def test_visual_finding_round_trip(self):
        """VisualFinding should serialize and deserialize correctly."""
        finding = VisualFinding(
            finding_id="VF-0001",
            category="copy_move_single",
            risk_level="high",
            summary="Panel A and Panel B show high similarity",
            source_panel_id="PE-0001-01",
            target_panel_id="PE-0001-02",
            relationship_id="IR-0001",
            score=0.85,
            benign_explanations=["合法的实验对照"],
            manual_review_questions=["验证是否来自不同实验"],
            overlay_path="visual/overlays/VF-0001.png",
            metadata={"method": "orb_ransac"},
        )
        data = finding.to_dict()
        finding2 = VisualFinding.from_dict(data)
        assert finding2.finding_id == finding.finding_id
        assert finding2.category == finding.category
        assert finding2.risk_level == finding.risk_level
        assert finding2.summary == finding.summary
        assert finding2.score == finding.score
        assert finding2.benign_explanations == finding.benign_explanations

    def test_visual_finding_risk_levels(self):
        """VisualFinding should validate risk levels."""
        for risk_level in ["info", "low", "medium", "high", "critical"]:
            finding = VisualFinding(
                finding_id="VF-0001",
                category="copy_move_single",
                risk_level=risk_level,
                summary="Test summary",
                source_panel_id="PE-0001-01",
                target_panel_id="PE-0001-02",
                relationship_id="IR-0001",
                score=0.5,
            )
            errors = finding.validate()
            assert errors == []

    def test_visual_finding_invalid_risk_level(self):
        """Invalid risk level should fail validation."""
        finding = VisualFinding(
            finding_id="VF-0001",
            category="copy_move_single",
            risk_level="invalid",  # Not a valid risk level
            summary="Test summary",
            source_panel_id="PE-0001-01",
            target_panel_id="PE-0001-02",
            relationship_id="IR-0001",
            score=0.5,
        )
        errors = finding.validate()
        assert any("risk_level" in e for e in errors)

    def test_visual_finding_score_bounds(self):
        """Score out of bounds should fail validation."""
        finding = VisualFinding(
            finding_id="VF-0001",
            category="copy_move_single",
            risk_level="high",
            summary="Test summary",
            source_panel_id="PE-0001-01",
            target_panel_id="PE-0001-02",
            relationship_id="IR-0001",
            score=1.5,  # Out of bounds
        )
        errors = finding.validate()
        assert any("score" in e for e in errors)


class TestImageRelationship:
    """Test ImageRelationship schema."""

    def test_image_relationship_round_trip(self):
        """ImageRelationship should serialize and deserialize correctly."""
        rel = ImageRelationship(
            relationship_id="IR-0001",
            source_type="copy_move_single",
            source_panel_id="PE-0001-01",
            target_panel_id="PE-0001-02",
            score=0.75,
            match_method="orb_ransac",
            inlier_count=25,
            homography=[[1.0, 0.0, 10.0], [0.0, 1.0, 20.0], [0.0, 0.0, 1.0]],
            overlay_path="visual/overlays/IR-0001.png",
            metadata={"method_version": "1.0"},
        )
        data = rel.to_dict()
        rel2 = ImageRelationship.from_dict(data)
        assert rel2.relationship_id == rel.relationship_id
        assert rel2.source_type == rel.source_type
        assert rel2.source_panel_id == rel.source_panel_id
        assert rel2.target_panel_id == rel.target_panel_id
        assert rel2.score == rel.score
        assert rel2.match_method == rel.match_method
        assert rel2.inlier_count == rel.inlier_count

    def test_image_relationship_score_bounds(self):
        """Score out of bounds should fail validation."""
        rel = ImageRelationship(
            relationship_id="IR-0001",
            source_type="copy_move_single",
            source_panel_id="PE-0001-01",
            target_panel_id="PE-0001-02",
            score=-0.1,  # Out of bounds
            match_method="orb_ransac",
            inlier_count=25,
        )
        errors = rel.validate()
        assert any("score" in e for e in errors)

    def test_image_relationship_same_panels(self):
        """Source and target panels must be different, except for copy_move_single."""
        # copy_move_single allows same panel (within-panel detection)
        rel = ImageRelationship(
            relationship_id="IR-0001",
            source_type="copy_move_single",
            source_panel_id="PE-0001-01",
            target_panel_id="PE-0001-01",
            score=0.75,
            match_method="rootsift_magsac_single",
            inlier_count=25,
        )
        errors = rel.validate()
        assert not any("different" in e for e in errors)

        # copy_move_cross with same panels should fail
        rel_cross = ImageRelationship(
            relationship_id="IR-0002",
            source_type="copy_move_cross",
            source_panel_id="PE-0001-01",
            target_panel_id="PE-0001-01",
            score=0.75,
            match_method="rootsift_magsac_cross",
            inlier_count=25,
        )
        errors = rel_cross.validate()
        assert any("different" in e for e in errors)

    def test_image_relationship_invalid_homography(self):
        """Invalid homography matrix should fail validation."""
        rel = ImageRelationship(
            relationship_id="IR-0001",
            source_type="copy_move_single",
            source_panel_id="PE-0001-01",
            target_panel_id="PE-0001-02",
            score=0.75,
            match_method="orb_ransac",
            inlier_count=25,
            homography=[[1.0, 0.0], [0.0, 1.0]],  # Wrong shape
        )
        errors = rel.validate()
        assert any("homography" in e for e in errors)


class TestLanguageCompliance:
    """Test language compliance checking."""

    def test_check_language_compliance_pass(self):
        """Clean text should pass compliance check."""
        text = "Panel A and Panel B show high similarity, requiring manual review."
        violations = check_language_compliance(text)
        assert violations == []

    def test_check_language_compliance_fail_english(self):
        """English forbidden phrases should be caught."""
        text = "This proves fraud in the data."
        violations = check_language_compliance(text)
        assert "proves fraud" in violations

    def test_check_language_compliance_fail_chinese(self):
        """Chinese forbidden phrases should be caught."""
        text = "这确认造假行为。"
        violations = check_language_compliance(text)
        assert "确认造假" in violations

    def test_check_language_compliance_case_insensitive(self):
        """Check should be case-insensitive."""
        text = "This PROVES FRAUD in the data."
        violations = check_language_compliance(text)
        assert "proves fraud" in violations

    def test_forbidden_phrases_in_finding_summary(self):
        """VisualFinding with forbidden phrases in summary should fail validation."""
        finding = VisualFinding(
            finding_id="VF-0001",
            category="copy_move_single",
            risk_level="high",
            summary="This proves fraud in the data.",
            source_panel_id="PE-0001-01",
            target_panel_id="PE-0001-02",
            relationship_id="IR-0001",
            score=0.85,
        )
        errors = finding.validate()
        assert any("forbidden phrases" in e for e in errors)
