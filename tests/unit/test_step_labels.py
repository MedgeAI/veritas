"""Unit tests for engine.static_audit.step_labels."""

from __future__ import annotations

import pytest

from engine.static_audit.step_labels import (
    STEP_LABELS,
    get_step_label,
    _UNKNOWN_PHASE,
    _UNKNOWN_PHASE_ORDER,
)


# ---------------------------------------------------------------------------
# Known keys
# ---------------------------------------------------------------------------


class TestGetStepLabelKnown:
    """Verify that known step keys return correct labels."""

    @pytest.mark.parametrize(
        "key,expected_title,expected_phase,expected_order",
        [
            ("discover", "发现输入材料", "准备", 1),
            ("material_inventory", "材料清单扫描", "准备", 1),
            ("figure_classification", "图像类型分类", "准备", 1),
            ("agent_material_plan", "材料计划", "准备", 1),
            ("agent_plan", "审查计划", "准备", 1),
            ("mineru", "PDF 解析", "文档解析", 2),
            ("evidence_ledger", "构建证据索引", "文档解析", 2),
            ("numeric_forensics", "数值取证", "数值取证", 3),
            ("paperconan_scan", "GRIM/GRIMMER 检测", "数值取证", 3),
            ("paperfraud_rule_match", "规则库匹配", "数值取证", 3),
            ("source_data_profile", "Source Data 画像", "数据分析", 4),
            ("source_data_findings", "Source Data 发现", "数据分析", 4),
            ("source_data_pair_forensics", "数值对取证", "数据分析", 4),
            ("source_data_cross_sheet", "跨 Sheet 检测", "数据分析", 4),
            ("source_data_briefings", "Sheet 简报", "数据分析", 4),
            ("source_data_verdict", "Source Data 裁决", "数据分析", 4),
            ("exact_image_duplicates", "图片字节级去重", "视觉取证", 5),
            ("visual_panel_extraction", "图片拆分", "视觉取证", 5),
            ("visual_tru_for", "TruFor 伪造检测", "视觉取证", 5),
            ("visual_copy_move", "Copy-Move 检测", "视觉取证", 5),
            ("visual_copy_move_dense", "SILA 密集 Copy-Move", "视觉取证", 5),
            ("visual_image_quality", "图片质量异常", "视觉取证", 5),
            ("visual_provenance_graph", "溯源图构建", "视觉取证", 5),
            ("visual_finding_pipeline", "视觉证据聚合", "视觉取证", 5),
            ("visual_overlap_reuse", "Overlap/Reuse 检测", "视觉取证", 5),
            ("investigation", "Agent 调查轮次", "Agent 审查", 6),
            ("agent_review", "Agent 审查", "Agent 审查", 6),
            ("static_audit_bundle", "生成审查包", "报告生成", 7),
            ("report", "生成 Markdown 报告", "报告生成", 7),
            ("html_report", "生成 HTML 报告", "报告生成", 7),
        ],
    )
    def test_known_keys(self, key, expected_title, expected_phase, expected_order):
        result = get_step_label(key)
        assert result["title"] == expected_title
        assert result["phase"] == expected_phase
        assert result["phase_order"] == expected_order

    def test_figure_classification_present(self):
        """Wave 2 新增步骤必须在映射表中."""
        assert "figure_classification" in STEP_LABELS
        assert STEP_LABELS["figure_classification"]["title"] == "图像类型分类"

    def test_vlm_triage_not_present(self):
        """Wave 1 已删除的 vlm_triage 不应在映射表中."""
        assert "vlm_triage" not in STEP_LABELS


# ---------------------------------------------------------------------------
# Fallback for unknown keys
# ---------------------------------------------------------------------------


class TestGetStepLabelFallback:
    """Unknown keys must fall back gracefully."""

    def test_unknown_key_returns_dict(self):
        result = get_step_label("some_future_step")
        assert isinstance(result, dict)
        assert "title" in result
        assert "phase" in result
        assert "phase_order" in result

    def test_unknown_key_title_format(self):
        result = get_step_label("some_future_step")
        assert result["title"] == "Some Future Step"

    def test_unknown_key_single_word(self):
        result = get_step_label("newthing")
        assert result["title"] == "Newthing"

    def test_unknown_key_phase_is_unknown(self):
        result = get_step_label("mystery_step")
        assert result["phase"] == _UNKNOWN_PHASE

    def test_unknown_key_phase_order_is_99(self):
        result = get_step_label("mystery_step")
        assert result["phase_order"] == _UNKNOWN_PHASE_ORDER

    def test_unknown_key_empty_string(self):
        result = get_step_label("")
        assert result["title"] == ""
        assert result["phase"] == _UNKNOWN_PHASE


# ---------------------------------------------------------------------------
# Phase ordering
# ---------------------------------------------------------------------------


class TestPhaseOrdering:
    """Verify phase_order values are consistent and sortable."""

    def test_all_known_phases_have_order(self):
        for key, label in STEP_LABELS.items():
            assert "phase_order" in label, f"{key} missing phase_order"
            assert isinstance(label["phase_order"], int)

    def test_phase_order_values(self):
        """All phase_order values should be in range 1-7."""
        orders = {label["phase_order"] for label in STEP_LABELS.values()}
        assert orders == {1, 2, 3, 4, 5, 6, 7}

    def test_phases_sort_correctly(self):
        """Sorting steps by phase_order should group them by phase."""
        sorted_steps = sorted(STEP_LABELS.values(), key=lambda x: x["phase_order"])
        phases_in_order = [s["phase"] for s in sorted_steps]
        # Each phase should appear contiguously
        seen = set()
        prev_phase = None
        for phase in phases_in_order:
            if prev_phase is not None and phase != prev_phase:
                assert phase not in seen, (
                    f"Phase {phase} appeared, then another phase, then {phase} again"
                )
            seen.add(prev_phase)
            prev_phase = phase

    def test_prepare_phase_order_less_than_report(self):
        prepare_order = STEP_LABELS["discover"]["phase_order"]
        report_order = STEP_LABELS["html_report"]["phase_order"]
        assert prepare_order < report_order


# ---------------------------------------------------------------------------
# Coverage completeness
# ---------------------------------------------------------------------------


class TestCoverageCompleteness:
    """Verify the mapping covers the expected number of step keys."""

    def test_minimum_entry_count(self):
        """Mapping should have at least 30 entries (current pipeline coverage)."""
        assert len(STEP_LABELS) >= 30

    def test_all_entries_have_required_fields(self):
        for key, label in STEP_LABELS.items():
            assert "title" in label, f"{key} missing title"
            assert "phase" in label, f"{key} missing phase"
            assert "phase_order" in label, f"{key} missing phase_order"
            assert isinstance(label["title"], str)
            assert isinstance(label["phase"], str)
            assert isinstance(label["phase_order"], int)
