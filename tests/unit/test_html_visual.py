"""Tests for html_report visual forensics (_visual)."""

from __future__ import annotations

from unittest.mock import patch

from engine.static_audit.html_report._visual import (
    _panel_lookup,
    _resolve_panel,
    _visual_cluster_table,
    _visual_figure_cards,
    _visual_finding_cards,
    _visual_img,
    _visual_relationship_table,
    _visual_review_checklist,
    _visual_review_queue_table,
)

class TestVisualImg:
    def test_with_path(self) -> None:
        result = _visual_img("images/test.png", "test label")
        assert "<img" in result
        assert "images/test.png" in result
        assert "test label" in result

    def test_empty_path(self) -> None:
        result = _visual_img("", "test")
        assert "visual-placeholder" in result
        assert "未生成图像" in result


# ---------------------------------------------------------------------------
# _panel_lookup() / _resolve_panel()
# ---------------------------------------------------------------------------


class TestPanelLookup:
    def test_indexes_by_panel_id(self) -> None:
        panels = [
            {"panel_id": "P-001", "crop_path": "crop1.png"},
            {"panel_id": "P-002", "crop_path": "crop2.png"},
        ]
        lookup = _panel_lookup(panels)
        assert "P-001" in lookup
        assert "P-002" in lookup

    def test_indexes_by_parent_figure_id(self) -> None:
        panels = [
            {"panel_id": "P-001", "parent_figure_id": "Fig-1", "crop_path": "crop.png"},
        ]
        lookup = _panel_lookup(panels)
        assert "Fig-1" in lookup

    def test_skips_non_dict(self) -> None:
        panels = ["invalid", None, {"panel_id": "P-001"}]
        lookup = _panel_lookup(panels)
        assert "P-001" in lookup
        assert len(lookup) == 1

    def test_skips_empty_panel_id(self) -> None:
        panels = [{"panel_id": "", "crop_path": "crop.png"}]
        lookup = _panel_lookup(panels)
        assert len(lookup) == 0


class TestResolvePanel:
    def test_direct_match(self) -> None:
        panels_by_id = {"P-001": {"panel_id": "P-001", "crop_path": "crop.png"}}
        result = _resolve_panel("P-001", panels_by_id)
        assert result["crop_path"] == "crop.png"

    def test_fallback_with_01_suffix(self) -> None:
        panels_by_id = {"P-001-01": {"panel_id": "P-001-01", "crop_path": "crop.png"}}
        result = _resolve_panel("P-001", panels_by_id)
        assert result["crop_path"] == "crop.png"

    def test_no_match_returns_empty(self) -> None:
        result = _resolve_panel("P-999", {})
        assert result == {}

    def test_already_has_01_suffix_no_double_fallback(self) -> None:
        panels_by_id = {"P-001-01": {"panel_id": "P-001-01"}}
        result = _resolve_panel("P-001-01", panels_by_id)
        assert result["panel_id"] == "P-001-01"


# ---------------------------------------------------------------------------
# _visual_figure_cards()
# ---------------------------------------------------------------------------


class TestVisualFigureCards:
    def test_empty_figures(self) -> None:
        result = _visual_figure_cards([], [])
        assert "muted" in result
        assert "未提取到" in result

    def test_renders_figure_with_panels(self) -> None:
        figures = [
            {
                "figure_id": "Fig-1",
                "label": "Figure 1",
                "caption": "Test caption",
                "source_image_path": "images/fig1.png",
                "panel_count": 2,
            }
        ]
        panels = [
            {
                "panel_id": "P-001",
                "parent_figure_id": "Fig-1",
                "label": "Panel A",
                "crop_path": "crops/p1.png",
                "width": 100,
                "height": 200,
                "extraction_confidence": 0.95,
                "extraction_method": "yolov5",
            }
        ]
        result = _visual_figure_cards(figures, panels)
        assert "Figure 1" in result
        assert "Panel A" in result
        assert "P-001" in result
        assert "yolov5" in result

    def test_figure_without_image_path(self) -> None:
        figures = [{"figure_id": "Fig-1", "label": "Figure 1"}]
        result = _visual_figure_cards(figures, [])
        assert "visual-placeholder" in result or "background" in result

    def test_fallback_panel_method_noted(self) -> None:
        figures = [{"figure_id": "Fig-1", "label": "Figure 1", "panel_count": 1}]
        panels = [
            {
                "panel_id": "P-001",
                "parent_figure_id": "Fig-1",
                "label": "Panel A",
                "extraction_method": "whole_figure_fallback",
                "extraction_confidence": 0.0,
            }
        ]
        result = _visual_figure_cards(figures, panels)
        assert "fallback" in result

    def test_limits_to_twenty_figures(self) -> None:
        figures = [{"figure_id": f"Fig-{i}", "label": f"Figure {i}"} for i in range(25)]
        result = _visual_figure_cards(figures, [])
        assert "Fig-24" not in result


# ---------------------------------------------------------------------------
# _visual_relationship_table()
# ---------------------------------------------------------------------------


class TestVisualRelationshipTable:
    def test_empty_relationships(self) -> None:
        result = _visual_relationship_table([])
        assert "未发现" in result

    def test_renders_sorted_by_score(self) -> None:
        rels = [
            {"source_panel_id": "P-001", "target_panel_id": "P-002", "source_type": "copy_move", "score": 0.85, "match_method": "rootsift", "inlier_count": 10},
            {"source_panel_id": "P-003", "target_panel_id": "P-004", "source_type": "overlap", "score": 0.95, "match_method": "dhash", "inlier_count": 5},
        ]
        result = _visual_relationship_table(rels)
        assert "P-001" in result
        assert "P-003" in result
        # Higher score should appear first
        idx_high = result.index("P-003")
        idx_low = result.index("P-001")
        assert idx_high < idx_low

    def test_limits_to_thirty(self) -> None:
        rels = [
            {"source_panel_id": f"P-{i:03d}", "target_panel_id": f"P-{i+1:03d}", "score": 0.5}
            for i in range(40)
        ]
        result = _visual_relationship_table(rels)
        assert "P-039" not in result


# ---------------------------------------------------------------------------
# _visual_review_queue_table()
# ---------------------------------------------------------------------------


class TestVisualReviewQueueTable:
    def test_empty_tasks(self) -> None:
        result = _visual_review_queue_table([])
        assert "未生成" in result

    def test_renders_task(self) -> None:
        tasks = [
            {
                "task_id": "RQ-001",
                "priority": "high",
                "cluster_id": "CL-001",
                "category": "copy_move",
                "scope": "intra-paper",
                "figure_ids": ["Fig-1"],
                "finding_count": 2,
                "relationship_count": 1,
                "panel_extraction_quality": "high",
                "question": "Check if panels are from same experiment",
            }
        ]
        result = _visual_review_queue_table(tasks)
        assert "RQ-001" in result
        assert "高优先级" in result
        assert "Check if panels" in result

    def test_fallback_quality_noted(self) -> None:
        tasks = [
            {
                "task_id": "RQ-001",
                "priority": "medium",
                "panel_extraction_quality": "whole_figure_fallback",
                "question": "test",
            }
        ]
        result = _visual_review_queue_table(tasks)
        assert "fallback 降级" in result


# ---------------------------------------------------------------------------
# _visual_cluster_table()
# ---------------------------------------------------------------------------


class TestVisualClusterTable:
    def test_empty_clusters(self) -> None:
        result = _visual_cluster_table([])
        assert "未生成" in result

    def test_renders_cluster(self) -> None:
        clusters = [
            {
                "cluster_id": "CL-001",
                "risk_level": "high",
                "category": "copy_move",
                "scope": "intra-paper",
                "figure_ids": ["Fig-1", "Fig-2"],
                "finding_count": 3,
                "relationship_count": 2,
                "max_score": 0.95,
                "panel_extraction_quality": "high",
                "representative_finding_ids": ["VF-001", "VF-002"],
            }
        ]
        result = _visual_cluster_table(clusters)
        assert "CL-001" in result
        assert "高优先级" in result
        assert "VF-001" in result


# ---------------------------------------------------------------------------
# _visual_finding_cards()
# ---------------------------------------------------------------------------


class TestVisualFindingCards:
    def test_empty_findings(self) -> None:
        result = _visual_finding_cards([], [])
        assert "未生成" in result

    @patch("engine.static_audit.visual_schemas.check_language_compliance", return_value=[])
    def test_renders_finding_card(self, _mock: object) -> None:
        findings = [
            {
                "finding_id": "VF-001",
                "category": "copy_move_single",
                "risk_level": "high",
                "summary": "Copy-move detected between panels",
                "source_panel_id": "P-001",
                "target_panel_id": "P-002",
                "score": 0.85,
                "overlay_path": "overlay.png",
                "metadata": {"panel_extraction_quality": "high"},
                "benign_explanations": [],
            }
        ]
        panels = [
            {"panel_id": "P-001", "crop_path": "crop1.png"},
            {"panel_id": "P-002", "crop_path": "crop2.png"},
        ]
        result = _visual_finding_cards(findings, panels)
        assert "VF-001" in result
        assert "copy_move_single" in result
        assert "高优先级" in result
        assert "P-001" in result

    @patch("engine.static_audit.visual_schemas.check_language_compliance", return_value=["violation"])
    def test_language_violation_hides_summary(self, _mock: object) -> None:
        findings = [
            {
                "finding_id": "VF-001",
                "category": "copy_move_single",
                "summary": "篡改 detected",
                "source_panel_id": "P-001",
                "target_panel_id": "P-002",
                "score": 0.85,
                "metadata": {},
            }
        ]
        result = _visual_finding_cards(findings, [])
        assert "禁用措辞" in result

    @patch("engine.static_audit.visual_schemas.check_language_compliance", return_value=[])
    def test_overlay_comparison(self, _mock: object) -> None:
        findings = [
            {
                "finding_id": "VF-001",
                "category": "copy_move_single",
                "summary": "Test",
                "source_panel_id": "P-001",
                "target_panel_id": "P-002",
                "score": 0.85,
                "overlay_path": "overlay.png",
                "metadata": {},
            }
        ]
        panels = [
            {"panel_id": "P-001", "crop_path": "crop1.png"},
            {"panel_id": "P-002", "crop_path": "crop2.png"},
        ]
        result = _visual_finding_cards(findings, panels)
        assert "overlay-compare" in result
        assert "overlay.png" in result

    @patch("engine.static_audit.visual_schemas.check_language_compliance", return_value=[])
    def test_risk_cap_note(self, _mock: object) -> None:
        findings = [
            {
                "finding_id": "VF-001",
                "category": "copy_move_single",
                "summary": "Test",
                "source_panel_id": "P-001",
                "target_panel_id": "P-002",
                "score": 0.85,
                "metadata": {"confidence_adjustment": "quality too low"},
            }
        ]
        result = _visual_finding_cards(findings, [])
        assert "quality too low" in result


# ---------------------------------------------------------------------------
# _visual_review_checklist()
# ---------------------------------------------------------------------------


class TestVisualReviewChecklist:
    def test_empty_questions(self) -> None:
        result = _visual_review_checklist([])
        assert "未生成" in result

    def test_renders_questions(self) -> None:
        questions = ["Check panel alignment", "Verify image source"]
        result = _visual_review_checklist(questions)
        assert "Check panel alignment" in result
        assert "Verify image source" in result

    def test_limits_to_ten(self) -> None:
        questions = [f"Question {i}" for i in range(15)]
        result = _visual_review_checklist(questions)
        assert "Question 14" not in result


# ===========================================================================
# Submodules (_clusters, _manual_tasks, _source_data, _appendix)
# ===========================================================================


# ---------------------------------------------------------------------------
# _clusters.py
# ---------------------------------------------------------------------------


