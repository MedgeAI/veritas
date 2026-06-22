"""Tests for engine.static_audit.html_report._executive module."""

from __future__ import annotations

from engine.static_audit.html_report._executive import (
    audit_depth_label,
    collect_limitations,
    executive_summary,
    hero_action_list,
    hero_metric,
    hero_pattern_list,
    report_verdict,
    source_coverage_text,
    source_coverage_value,
    summary_pattern_clause,
)


# ---------------------------------------------------------------------------
# audit_depth_label()
# ---------------------------------------------------------------------------


class TestAuditDepthLabel:
    def test_v0_no_evidence_no_steps(self) -> None:
        bundle = {"evidence_items": [], "claim_mappings": []}
        assert audit_depth_label(bundle, []) == "V0 coverage"

    def test_v4_execution_ran(self) -> None:
        bundle = {
            "evidence_items": [{"evidence_id": "EV-001"}],
            "execution_status": {"status": "ran"},
        }
        tool_runs = [{"key": "some_step", "status": "ran"}]
        assert audit_depth_label(bundle, tool_runs) == "V4 coverage"

    def test_v3_claim_mappings(self) -> None:
        bundle = {
            "evidence_items": [{"evidence_id": "EV-001"}],
            "claim_mappings": [{"mapping_id": "CM-001"}],
            "execution_status": {"status": "not_provided"},
        }
        assert audit_depth_label(bundle, []) == "V3 coverage"

    def test_v3_agent_traces(self) -> None:
        bundle = {
            "evidence_items": [{"evidence_id": "EV-001"}],
            "claim_mappings": [],
            "agent_traces": [{"role_id": "test"}],
            "execution_status": {"status": "not_provided"},
        }
        assert audit_depth_label(bundle, []) == "V3 coverage"

    def test_v2_source_data_steps(self) -> None:
        bundle = {
            "evidence_items": [{"evidence_id": "EV-001"}],
            "claim_mappings": [],
            "execution_status": {"status": "not_provided"},
        }
        tool_runs = [{"key": "source_data_profile", "status": "ran"}]
        assert audit_depth_label(bundle, tool_runs) == "V2 coverage"

    def test_v2_exact_image_step(self) -> None:
        bundle = {
            "evidence_items": [{"evidence_id": "EV-001"}],
            "claim_mappings": [],
            "execution_status": {"status": "not_provided"},
        }
        tool_runs = [{"key": "exact_image_duplicates", "status": "ran"}]
        assert audit_depth_label(bundle, tool_runs) == "V2 coverage"

    def test_v1_fallback(self) -> None:
        bundle = {
            "evidence_items": [{"evidence_id": "EV-001"}],
            "claim_mappings": [],
            "execution_status": {"status": "not_provided"},
        }
        tool_runs = [{"key": "other_step", "status": "ran"}]
        assert audit_depth_label(bundle, tool_runs) == "V1 coverage"

    def test_step_key_alternate_name(self) -> None:
        bundle = {
            "evidence_items": [{"evidence_id": "EV-001"}],
            "claim_mappings": [],
            "execution_status": {"status": "not_provided"},
        }
        tool_runs = [{"step_key": "source_data_findings", "status": "ran"}]
        assert audit_depth_label(bundle, tool_runs) == "V2 coverage"


# ---------------------------------------------------------------------------
# report_verdict()
# ---------------------------------------------------------------------------


class TestReportVerdict:
    def test_critical_findings_fail(self) -> None:
        findings = [{"finding_id": "F-001", "category": "fixed_difference", "risk_level": "critical"}]
        result = report_verdict(findings, [], [], {})
        assert result["label"] == "需优先复核"
        assert result["result"] == "fail"

    def test_findings_with_warning(self) -> None:
        findings = [{"finding_id": "F-001", "category": "fixed_difference", "risk_level": "high"}]
        result = report_verdict(findings, [], [], {})
        assert result["label"] == "需人工复核"
        assert result["result"] == "warning"

    def test_manual_tasks_with_no_findings(self) -> None:
        tasks = [{"task_id": "T-001", "question": "check this"}]
        result = report_verdict([], tasks, [], {})
        assert result["label"] == "需人工复核"
        assert result["result"] == "warning"

    def test_failed_tool_warning(self) -> None:
        tool_runs = [{"key": "step1", "status": "failed"}]
        result = report_verdict([], [], tool_runs, {})
        assert result["label"] == "需人工复核"
        assert result["result"] == "warning"

    def test_no_findings_no_tasks_pass(self) -> None:
        result = report_verdict([], [], [], {})
        assert result["label"] == "未见高优先级项"
        assert result["result"] == "pass"

    def test_verdict_includes_depth(self) -> None:
        bundle = {"evidence_items": [], "claim_mappings": []}
        result = report_verdict([], [], [], bundle)
        assert result["depth"] == "V0 coverage"


# ---------------------------------------------------------------------------
# source_coverage_value() / source_coverage_text()
# ---------------------------------------------------------------------------


class TestSourceCoverage:
    def test_coverage_no_data(self) -> None:
        assert source_coverage_value({}) == "未选择"

    def test_coverage_with_both(self) -> None:
        assert source_coverage_value({"workbook_count": 3, "sheet_count": 12}) == "3 / 12"

    def test_coverage_workbook_only(self) -> None:
        assert source_coverage_value({"workbook_count": 3}) == "3 / -"

    def test_coverage_sheet_only(self) -> None:
        assert source_coverage_value({"sheet_count": 12}) == "- / 12"

    def test_coverage_text_no_data(self) -> None:
        assert "未形成" in source_coverage_text({})

    def test_coverage_text_with_data(self) -> None:
        result = source_coverage_text({"workbook_count": 2, "sheet_count": 5})
        assert "2" in result
        assert "5" in result


# ---------------------------------------------------------------------------
# summary_pattern_clause()
# ---------------------------------------------------------------------------


class TestSummaryPatternClause:
    def test_no_patterns(self) -> None:
        result = summary_pattern_clause([])
        assert "未形成重点摘要" in result

    def test_patterns_with_titles(self) -> None:
        patterns = [{"title": "Pattern A"}, {"title": "Pattern B"}]
        result = summary_pattern_clause(patterns)
        assert "2 类重点摘要" in result
        assert "Pattern A" in result

    def test_patterns_without_titles(self) -> None:
        patterns = [{"no_title": True}]
        result = summary_pattern_clause(patterns)
        assert "未形成重点摘要" in result

    def test_limits_to_three_titles(self) -> None:
        patterns = [{"title": f"P{i}"} for i in range(5)]
        result = summary_pattern_clause(patterns)
        assert "P3" not in result


# ---------------------------------------------------------------------------
# executive_summary()
# ---------------------------------------------------------------------------


class TestExecutiveSummary:
    def test_no_findings_clean_report(self) -> None:
        result = executive_summary([], [], {"claim_mappings": 0}, {}, {})
        assert "未生成高优先级复核记录" in result

    def test_visual_critical_and_source_data(self) -> None:
        patterns = [
            {
                "pattern_key": "visual_forensics",
                "findings": [{"risk_level": "critical", "category": "copy_move_single"}],
            },
            {
                "pattern_key": "paired_offset_ratio_reuse",
                "findings": [{"risk_level": "high", "category": "row_offset_scalar_multiple"}],
            },
        ]
        findings = [
            {"risk_level": "critical", "category": "copy_move_single"},
            {"risk_level": "high", "category": "row_offset_scalar_multiple"},
        ]
        result = executive_summary(
            patterns, findings, {"claim_mappings": 2},
            {"workbook_count": 1, "sheet_count": 3}, {"image_count": 10},
        )
        assert "图像复核记录" in result
        assert "Source Data 复核记录" in result

    def test_multiple_source_data_patterns(self) -> None:
        patterns = [
            {
                "pattern_key": "paired_offset_ratio_reuse",
                "findings": [{"risk_level": "high", "category": "row_offset_scalar_multiple"}],
                "sheets": ["Sheet1"],
            },
            {
                "pattern_key": "duplicate_numeric_columns",
                "findings": [{"risk_level": "high", "category": "duplicate_numeric_columns"}],
                "sheets": ["Sheet2"],
            },
        ]
        findings = [
            {"risk_level": "high", "category": "row_offset_scalar_multiple"},
            {"risk_level": "high", "category": "duplicate_numeric_columns"},
        ]
        result = executive_summary(
            patterns, findings, {"claim_mappings": 1},
            {"workbook_count": 1, "sheet_count": 2}, {"image_count": 5},
        )
        assert "Source Data 中形成" in result
        assert "2 类模式" in result

    def test_visual_critical_only(self) -> None:
        patterns = [
            {
                "pattern_key": "visual_forensics",
                "findings": [{"risk_level": "high", "category": "copy_move_single"}],
            },
        ]
        findings = [{"risk_level": "high", "category": "copy_move_single"}]
        result = executive_summary(
            patterns, findings, {"claim_mappings": 0},
            {}, {"image_count": 8},
        )
        assert "图像层面形成" in result

    def test_source_data_findings_only(self) -> None:
        patterns = [
            {
                "pattern_key": "formula_derivation",
                "findings": [{"risk_level": "medium", "category": "fixed_ratio"}],
            },
        ]
        findings = [{"risk_level": "medium", "category": "fixed_ratio"}]
        result = executive_summary(
            patterns, findings, {"claim_mappings": 0},
            {"workbook_count": 1, "sheet_count": 1}, {},
        )
        assert "Source Data 层面形成" in result

    def test_only_completeness(self) -> None:
        patterns = [
            {
                "pattern_key": "other",
                "findings": [{"category": "source_data_missing", "finding_id": "SDM-SUMMARY-001"}],
            },
        ]
        findings = [{"category": "source_data_missing", "finding_id": "SDM-SUMMARY-001"}]
        result = executive_summary(
            patterns, findings, {"claim_mappings": 0}, {}, {},
        )
        assert "材料完整性问题" in result

    def test_generic_findings(self) -> None:
        # Use a pattern key that is not matched by any specific branch
        # (not visual, not source_data, not completeness-only)
        patterns = [
            {
                "pattern_key": "category:custom_type",
                "findings": [{"risk_level": "medium", "category": "custom_finding"}],
            },
        ]
        findings = [{"risk_level": "medium", "category": "custom_finding"}]
        result = executive_summary(
            patterns, findings, {"claim_mappings": 0}, {}, {},
        )
        assert "高优先级复核记录" in result


# ---------------------------------------------------------------------------
# hero_metric() / hero_pattern_list() / hero_action_list()
# ---------------------------------------------------------------------------


class TestHeroHelpers:
    def test_hero_metric_renders(self) -> None:
        result = hero_metric("Test", 42)
        assert "hero-stat" in result
        assert "42" in result
        assert "Test" in result

    def test_hero_pattern_list_empty(self) -> None:
        result = hero_pattern_list([])
        assert "未形成重点摘要" in result

    def test_hero_pattern_list_with_patterns(self) -> None:
        patterns = [
            {"title": "Pattern A", "thesis": "Thesis A", "summary_source": "data"},
            {"title": "Pattern B", "thesis": "Thesis B", "summary_source": "rule"},
        ]
        result = hero_pattern_list(patterns)
        assert "hero-evidence-list" in result
        assert "Pattern A" in result
        assert "Thesis A" in result

    def test_hero_pattern_list_limits_to_three(self) -> None:
        patterns = [{"title": f"P{i}", "thesis": f"T{i}", "summary_source": "data"} for i in range(5)]
        result = hero_pattern_list(patterns)
        assert "P4" not in result

    def test_hero_action_list_empty_tasks(self) -> None:
        result = hero_action_list([])
        assert "action-list" in result
        assert "核对材料清单" in result

    def test_hero_action_list_with_tasks(self) -> None:
        tasks = [
            {"task_id": "T-001", "question": "Check column A in Sheet1"},
            {"task_id": "T-002", "question": "Verify figure 2 source data"},
        ]
        result = hero_action_list(tasks)
        assert "Check column A" in result

    def test_hero_action_list_limits_to_three(self) -> None:
        tasks = [{"task_id": f"T-{i}", "question": f"Question {i}"} for i in range(5)]
        result = hero_action_list(tasks)
        assert "Question 4" not in result


# ---------------------------------------------------------------------------
# collect_limitations()
# ---------------------------------------------------------------------------


class TestCollectLimitations:
    def test_default_limitation_always_present(self) -> None:
        result = collect_limitations({}, {}, {})
        assert "不做最终科研诚信判定" in result[0]

    def test_with_claim_mappings(self) -> None:
        bundle = {"claim_mappings": [{"mapping_id": "CM-001"}]}
        result = collect_limitations(bundle, {}, {})
        assert any("人工确认" in item for item in result)

    def test_without_claim_mappings(self) -> None:
        bundle = {"claim_mappings": []}
        result = collect_limitations(bundle, {}, {})
        assert any("未生成稳定的论文表述与证据映射" in item for item in result)

    def test_execution_not_provided(self) -> None:
        bundle = {"execution_status": {"status": "not_provided"}}
        result = collect_limitations(bundle, {}, {})
        assert any("代码执行审查未形成" in item for item in result)

    def test_similarity_not_available(self) -> None:
        similarity = {"status": "not_available"}
        result = collect_limitations({}, {}, similarity)
        assert any("近似图像相似度未运行" in item for item in result)

    def test_bundle_limitations_included(self) -> None:
        bundle = {"limitations": ["Custom limitation 1", "Custom limitation 2"]}
        result = collect_limitations(bundle, {}, {})
        assert "Custom limitation 1" in result

    def test_judge_limitations_included(self) -> None:
        judge = {"limitations": ["Judge limitation 1"]}
        result = collect_limitations({}, judge, {})
        assert "Judge limitation 1" in result

    def test_deduplication(self) -> None:
        bundle = {"limitations": ["Same limitation"]}
        judge = {"limitations": ["Same limitation"]}
        result = collect_limitations(bundle, judge, {})
        assert result.count("Same limitation") == 1

    def test_limits_to_five_bundle_and_five_judge(self) -> None:
        bundle = {"limitations": [f"BL{i}" for i in range(10)]}
        judge = {"limitations": [f"JL{i}" for i in range(10)]}
        result = collect_limitations(bundle, judge, {})
        bundle_items = [item for item in result if item.startswith("BL")]
        judge_items = [item for item in result if item.startswith("JL")]
        assert len(bundle_items) <= 5
        assert len(judge_items) <= 5

    def test_execution_status_none(self) -> None:
        bundle = {"execution_status": {"status": None}}
        result = collect_limitations(bundle, {}, {})
        assert any("代码执行审查未形成" in item for item in result)

    def test_execution_status_missing_material(self) -> None:
        bundle = {"execution_status": {"status": "missing_material"}}
        result = collect_limitations(bundle, {}, {})
        assert any("代码执行审查未形成" in item for item in result)
