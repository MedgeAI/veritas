"""Tests for html_report shared utilities (_shared, _html_utils, _manual_tasks)."""

from __future__ import annotations

from pathlib import Path
import json

from engine.static_audit.html_report._html_utils import h_attr
from engine.static_audit.html_report._manual_tasks import (
    display_priority_for_manual_task,
    display_priority_for_pair_task,
    display_risk_level_for_judge_risk,
    is_context_only_manual_task,
    manual_task_focus_score,
    manual_task_text,
    manual_tasks_table,
)
from engine.static_audit.html_report._shared import (
    SOURCE_DATA_FINDINGS_ARTIFACT,
    SOURCE_DATA_PAIR_FORENSICS_ARTIFACT,
    _confidence_badge,
    category_label,
    clean_report_text,
    dedupe,
    display_risk_level_for_finding,
    finding_display_score,
    finding_support_value,
    has_row_vector_signal_text,
    has_stronger_signal_text,
    highest_display_risk,
    h,
    is_context_only_finding,
    list_items,
    metric,
    pattern_key_for_finding,
    read_json,
    ref_mentions_finding,
    risk_label,
    risk_score,
    shorten,
    status_label,
    summary_text,
)

class TestHtmlEscape:
    def test_h_escapes_angle_brackets(self) -> None:
        assert (
            h("<script>alert('x')</script>")
            == "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"
        )

    def test_h_escapes_ampersand(self) -> None:
        assert h("a&b") == "a&amp;b"

    def test_h_escapes_double_quotes(self) -> None:
        assert h('a"b') == "a&quot;b"

    def test_h_none_returns_empty(self) -> None:
        assert h(None) == ""

    def test_h_int_converts_to_str(self) -> None:
        assert h(42) == "42"

    def test_h_float_converts_to_str(self) -> None:
        assert h(3.14) == "3.14"

    def test_h_attr_none_returns_empty(self) -> None:
        assert h_attr(None) == ""

    def test_h_attr_escapes_quotes(self) -> None:
        assert h_attr('value="x"') == "value=&quot;x&quot;"

    def test_h_empty_string(self) -> None:
        assert h("") == ""

    def test_h_preserves_normal_text(self) -> None:
        assert h("hello world") == "hello world"


# ---------------------------------------------------------------------------
# dedupe()
# ---------------------------------------------------------------------------


class TestDedupe:
    def test_empty_list(self) -> None:
        assert dedupe([]) == []

    def test_no_duplicates(self) -> None:
        assert dedupe(["a", "b", "c"]) == ["a", "b", "c"]

    def test_removes_duplicates_preserving_order(self) -> None:
        assert dedupe(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]

    def test_skips_empty_strings(self) -> None:
        assert dedupe(["a", "", "b", ""]) == ["a", "b"]

    def test_skips_none_like_empty(self) -> None:
        # empty string is falsy, so it's skipped
        result = dedupe(["", "", "x"])
        assert result == ["x"]


# ---------------------------------------------------------------------------
# read_json()
# ---------------------------------------------------------------------------


class TestReadJson:
    def test_reads_valid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "test.json"
        p.write_text('{"key": "value"}', encoding="utf-8")
        assert read_json(p) == {"key": "value"}

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        assert read_json(tmp_path / "nonexistent.json") is None

    def test_reads_nested_json(self, tmp_path: Path) -> None:
        p = tmp_path / "nested.json"
        data = {"a": [1, 2, {"b": 3}]}
        p.write_text(json.dumps(data), encoding="utf-8")
        result = read_json(p)
        assert result == data


# ---------------------------------------------------------------------------
# clean_report_text()
# ---------------------------------------------------------------------------


class TestCleanReportText:
    def test_replaces_fraud_with_data_integrity(self) -> None:
        result = clean_report_text("疑似造假行为")
        assert "造假" not in result
        assert "数据完整性问题" in result

    def test_replaces_academic_misconduct(self) -> None:
        result = clean_report_text("学术不端行为")
        assert "学术不端" not in result
        assert "最终判断" in result

    def test_replaces_suspicious(self) -> None:
        result = clean_report_text("可疑模式")
        assert "可疑" not in result

    def test_strips_conf_badge_html(self) -> None:
        text = '<span class="conf-badge conf-data">数据关联</span>Some text'
        result = clean_report_text(text)
        assert "conf-badge" not in result
        assert "Some text" in result

    def test_collapses_whitespace(self) -> None:
        result = clean_report_text("  lots   of   spaces  ")
        assert result == "lots of spaces"

    def test_none_returns_empty(self) -> None:
        assert clean_report_text(None) == ""

    def test_replaces_copy_move(self) -> None:
        result = clean_report_text("copy-move detection")
        assert "copy-move" not in result
        assert "局部相似" in result

    def test_replaces_suspicious_forged_region(self) -> None:
        result = clean_report_text("可疑伪造区域 detected")
        assert "伪造" not in result
        assert "区域完整性记录" in result

    def test_replaces_p_hacking(self) -> None:
        result = clean_report_text("p-hacking detected")
        assert "p-hacking" not in result


# ---------------------------------------------------------------------------
# shorten()
# ---------------------------------------------------------------------------


class TestShorten:
    def test_short_text_unchanged(self) -> None:
        assert shorten("hello", 10) == "hello"

    def test_long_text_truncated_with_ellipsis(self) -> None:
        result = shorten("a" * 20, 10)
        # shorten takes text[:limit-1] + "..." -> 9 + 3 = 12
        assert result.endswith("...")
        assert len(result) < 20

    def test_collapses_whitespace_before_truncation(self) -> None:
        result = shorten("  lots   of   spaces  ", 10)
        assert "  " not in result

    def test_zero_limit(self) -> None:
        result = shorten("hello", 0)
        assert result == "..."

    def test_exact_limit_not_truncated(self) -> None:
        assert shorten("hello", 5) == "hello"


# ---------------------------------------------------------------------------
# metric() / list_items()
# ---------------------------------------------------------------------------


class TestMetric:
    def test_metric_renders_html(self) -> None:
        result = metric("Test Label", 42)
        assert "Test Label" in result
        assert "42" in result
        assert "metric" in result

    def test_metric_escapes_html(self) -> None:
        result = metric("<script>", "<value>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


class TestListItems:
    def test_empty_list_renders_muted(self) -> None:
        result = list_items([])
        assert "muted" in result
        assert "未记录" in result

    def test_items_rendered_as_li(self) -> None:
        result = list_items(["item1", "item2"])
        assert "<li>" in result
        assert "item1" in result
        assert "item2" in result


# ---------------------------------------------------------------------------
# status_label() / risk_label() / risk_score() / category_label()
# ---------------------------------------------------------------------------


class TestLabels:
    def test_status_label_known(self) -> None:
        assert status_label("ran") == "已执行"
        assert status_label("skipped") == "已跳过"
        assert status_label("failed") == "失败"
        assert status_label("reused") == "已复用"
        assert status_label("warning") == "警告"
        assert status_label("not_provided") == "未提供"
        assert status_label("missing_material") == "材料缺失"
        assert status_label("present") == "已生成"
        assert status_label("missing") == "缺失"

    def test_status_label_unknown_returns_string(self) -> None:
        assert status_label("unknown_status") == "unknown_status"

    def test_risk_label_known(self) -> None:
        assert risk_label("critical") == "最高优先级"
        assert risk_label("high") == "高优先级"
        assert risk_label("medium") == "中优先级"
        assert risk_label("low") == "低优先级"

    def test_risk_label_unknown(self) -> None:
        assert risk_label("unknown_risk") == "unknown_risk"

    def test_risk_score_values(self) -> None:
        assert risk_score("critical") == 4
        assert risk_score("high") == 3
        assert risk_score("medium") == 2
        assert risk_score("low") == 1
        assert risk_score("info") == 0
        assert risk_score("context") == 0

    def test_risk_score_unknown(self) -> None:
        assert risk_score("nonexistent") == 0

    def test_category_label_known(self) -> None:
        assert category_label("duplicate_numeric_columns") == "数值列重复"
        assert category_label("fixed_difference") == "固定差关系"
        assert category_label("fixed_ratio") == "固定比例关系"
        assert category_label("copy_move_single") == "单图内局部相似"
        assert category_label("exact_duplicate") == "字节级完全重复"

    def test_category_label_unknown_returns_string(self) -> None:
        assert category_label("unknown_category") == "unknown_category"


# ---------------------------------------------------------------------------
# summary_text()
# ---------------------------------------------------------------------------


class TestSummaryText:
    def test_empty_dict(self) -> None:
        assert summary_text({}) == "-"

    def test_string_values(self) -> None:
        result = summary_text({"key1": "value1", "key2": "value2"})
        assert "key1=value1" in result
        assert "key2=value2" in result

    def test_numeric_values(self) -> None:
        result = summary_text({"count": 42})
        assert "count=42" in result

    def test_truncates_long_values(self) -> None:
        result = summary_text({"key": "a" * 200})
        # Value should be truncated to 90 chars
        assert len(result) < 200

    def test_limits_to_four_keys(self) -> None:
        result = summary_text({"a": 1, "b": 2, "c": 3, "d": 4, "e": 5})
        assert "e=" not in result


# ---------------------------------------------------------------------------
# _confidence_badge()
# ---------------------------------------------------------------------------


class TestConfidenceBadge:
    def test_rule_badge(self) -> None:
        result = _confidence_badge("rule")
        assert "conf-rule" in result
        assert "仅原始记录" in result

    def test_data_badge(self) -> None:
        result = _confidence_badge("data")
        assert "conf-data" in result
        assert "证据记录" in result

    def test_agent_badge(self) -> None:
        result = _confidence_badge("agent")
        assert "conf-agent" in result
        assert "复核摘要" in result

    def test_unknown_returns_empty(self) -> None:
        assert _confidence_badge("nonexistent") == ""


# ---------------------------------------------------------------------------
# Signal text detection
# ---------------------------------------------------------------------------


class TestSignalText:
    def test_row_vector_signal_tokens(self) -> None:
        assert has_row_vector_signal_text("drv-001 duplicate_row_vector") is True
        assert has_row_vector_signal_text("row vector detected") is True
        assert has_row_vector_signal_text("行向量重复 found") is True
        assert has_row_vector_signal_text("nothing relevant") is False

    def test_stronger_signal_tokens(self) -> None:
        assert has_stronger_signal_text("dc-001 fixed difference") is True
        assert has_stronger_signal_text("fr-001 固定比例") is True
        assert has_stronger_signal_text("trufor detected") is True
        assert has_stronger_signal_text("copy-move found") is True
        assert has_stronger_signal_text("nothing relevant") is False

    def test_case_insensitive(self) -> None:
        assert has_row_vector_signal_text("DRV-001") is True
        assert has_stronger_signal_text("TRUFOR scan") is True


# ---------------------------------------------------------------------------
# ref_mentions_finding()
# ---------------------------------------------------------------------------


class TestRefMentionsFinding:
    def test_string_ref_contains_finding_id(self) -> None:
        assert ref_mentions_finding("source_data_findings:F-001", ["F-001"]) is True

    def test_string_ref_does_not_contain(self) -> None:
        assert ref_mentions_finding("source_data_findings:F-002", ["F-001"]) is False

    def test_dict_ref_serialized_and_checked(self) -> None:
        ref = {"evidence_id": "F-001", "source": "test"}
        assert ref_mentions_finding(ref, ["F-001"]) is True

    def test_empty_finding_id(self) -> None:
        assert ref_mentions_finding("some text", [""]) is False

    def test_multiple_finding_ids(self) -> None:
        assert ref_mentions_finding("refs F-002", ["F-001", "F-002"]) is True


# ---------------------------------------------------------------------------
# pattern_key_for_finding()
# ---------------------------------------------------------------------------


class TestPatternKeyForFinding:
    def test_paired_offset_ratio_reuse(self) -> None:
        finding = {
            "category": "row_offset_scalar_multiple",
            "source_artifact": "x.json",
        }
        assert pattern_key_for_finding(finding) == "paired_offset_ratio_reuse"

    def test_long_format_paired_ratio(self) -> None:
        finding = {"category": "long_format_paired_ratio_reuse"}
        assert pattern_key_for_finding(finding) == "paired_offset_ratio_reuse"

    def test_within_pair_ratio_enrichment(self) -> None:
        finding = {"category": "long_format_within_pair_ratio_enrichment"}
        assert pattern_key_for_finding(finding) == "paired_offset_ratio_reuse"

    def test_duplicate_row_vector(self) -> None:
        finding = {"category": "duplicate_row_vector"}
        assert pattern_key_for_finding(finding) == "row_vector_reuse"

    def test_partial_copy_rounding_bias(self) -> None:
        finding = {"category": "row_offset_partial_copy_rounding_bias"}
        assert pattern_key_for_finding(finding) == "partial_copy_rounding_bias"

    def test_duplicate_numeric_columns(self) -> None:
        finding = {"category": "duplicate_numeric_columns"}
        assert pattern_key_for_finding(finding) == "duplicate_numeric_columns"

    def test_formula_derived_column(self) -> None:
        finding = {"category": "formula_derived_column"}
        assert pattern_key_for_finding(finding) == "formula_derivation"

    def test_fixed_ratio(self) -> None:
        finding = {"category": "fixed_ratio"}
        assert pattern_key_for_finding(finding) == "formula_derivation"

    def test_fixed_difference(self) -> None:
        finding = {"category": "fixed_difference"}
        assert pattern_key_for_finding(finding) == "formula_derivation"

    def test_visual_forensics_from_category(self) -> None:
        finding = {"category": "copy_move_single"}
        assert pattern_key_for_finding(finding) == "visual_forensics"

    def test_visual_forensics_from_source_artifact(self) -> None:
        finding = {"category": "unknown", "source_artifact": "visual_evidence.json"}
        assert pattern_key_for_finding(finding) == "visual_forensics"

    def test_trufor_via_source_artifact(self) -> None:
        # forged_region_suspicious is not directly matched by visual tokens,
        # but visual_evidence.json as source_artifact triggers visual_forensics
        finding = {
            "category": "forged_region_suspicious",
            "source_artifact": "visual_evidence.json",
        }
        assert pattern_key_for_finding(finding) == "visual_forensics"

    def test_numeric_forensics(self) -> None:
        finding = {"category": "benford_analysis"}
        assert pattern_key_for_finding(finding) == "numeric_forensics"

    def test_execution_evidence(self) -> None:
        finding = {"category": "execution_status"}
        assert pattern_key_for_finding(finding) == "execution_evidence"

    def test_unknown_category_with_prefix(self) -> None:
        finding = {"category": "custom_type"}
        assert pattern_key_for_finding(finding) == "category:custom_type"

    def test_empty_category(self) -> None:
        finding = {"category": ""}
        assert pattern_key_for_finding(finding) == "other"


# ---------------------------------------------------------------------------
# Finding display helpers
# ---------------------------------------------------------------------------


class TestFindingDisplayHelpers:
    def test_is_context_only_finding_true(self) -> None:
        assert is_context_only_finding({"category": "duplicate_row_vector"}) is True

    def test_is_context_only_finding_false(self) -> None:
        assert is_context_only_finding({"category": "fixed_difference"}) is False

    def test_display_risk_level_context_only(self) -> None:
        finding = {"category": "duplicate_row_vector", "risk_level": "high"}
        assert display_risk_level_for_finding(finding) == "context"

    def test_display_risk_level_normal(self) -> None:
        finding = {"category": "fixed_difference", "risk_level": "high"}
        assert display_risk_level_for_finding(finding) == "high"

    def test_display_risk_level_default_medium(self) -> None:
        finding = {"category": "fixed_difference"}
        assert display_risk_level_for_finding(finding) == "medium"

    def test_finding_display_score(self) -> None:
        finding = {"category": "fixed_difference", "risk_level": "high"}
        assert finding_display_score(finding) == 3

    def test_finding_display_score_context(self) -> None:
        finding = {"category": "duplicate_row_vector", "risk_level": "high"}
        assert finding_display_score(finding) == 0

    def test_highest_display_risk(self) -> None:
        findings = [
            {"category": "fixed_difference", "risk_level": "low"},
            {"category": "fixed_ratio", "risk_level": "critical"},
        ]
        assert highest_display_risk(findings) == "critical"

    def test_highest_display_risk_empty(self) -> None:
        assert highest_display_risk([]) == "medium"

    def test_finding_support_value_support_rows(self) -> None:
        assert finding_support_value({"support_rows": 42}) == 42

    def test_finding_support_value_matched_pairs(self) -> None:
        assert finding_support_value({"matched_pairs": 10}) == 10

    def test_finding_support_value_duplicate_row_count(self) -> None:
        assert finding_support_value({"duplicate_row_count": 5}) == 5

    def test_finding_support_value_equal_rows(self) -> None:
        assert finding_support_value({"equal_rows": 20}) == 20

    def test_finding_support_value_no_support(self) -> None:
        assert finding_support_value({}) == 0

    def test_finding_support_value_float_converted(self) -> None:
        assert finding_support_value({"support_rows": 10.0}) == 10


# ===========================================================================
# Findings rendering (_findings)
# ===========================================================================


# ---------------------------------------------------------------------------
# source_artifact_for_finding()
# ---------------------------------------------------------------------------


class TestManualTaskText:
    def test_combines_question_and_refs(self) -> None:
        task = {"question": "Check data", "evidence_refs": ["F-001"]}
        result = manual_task_text(task)
        assert "check data" in result
        assert "f-001" in result


class TestManualTaskFocusScore:
    def test_row_vector_and_stronger(self) -> None:
        task = {"question": "drv-001 dc-001 fixed difference"}
        assert manual_task_focus_score(task) == 1

    def test_row_vector_only(self) -> None:
        task = {"question": "drv-001 duplicate_row_vector"}
        assert manual_task_focus_score(task) == 2

    def test_no_row_vector(self) -> None:
        task = {"question": "Check data integrity"}
        assert manual_task_focus_score(task) == 0


class TestIsContextOnlyManualTask:
    def test_row_vector_only_is_context(self) -> None:
        task = {"question": "Check drv-001 row vector pattern"}
        assert is_context_only_manual_task(task) is True

    def test_row_vector_with_stronger_not_context(self) -> None:
        task = {"question": "Check drv-001 and dc-001 patterns"}
        assert is_context_only_manual_task(task) is False

    def test_no_row_vector_not_context(self) -> None:
        task = {"question": "Check fixed difference"}
        assert is_context_only_manual_task(task) is False


class TestDisplayPriorityForManualTask:
    def test_context_only(self) -> None:
        task = {"question": "Check drv-001 row vector", "priority": "high"}
        assert display_priority_for_manual_task(task) == "context"

    def test_normal_priority(self) -> None:
        task = {"question": "Check fixed difference", "priority": "high"}
        assert display_priority_for_manual_task(task) == "high"

    def test_default_medium(self) -> None:
        task = {"question": "Check something"}
        assert display_priority_for_manual_task(task) == "medium"


class TestDisplayPriorityForPairTask:
    def test_duplicate_row_vector_is_context(self) -> None:
        task = {"category": "duplicate_row_vector", "priority": "high"}
        assert display_priority_for_pair_task(task) == "context"

    def test_context_only_task(self) -> None:
        task = {"question": "Check drv-001 row vector"}
        assert display_priority_for_pair_task(task) == "context"

    def test_normal_task(self) -> None:
        task = {"category": "row_offset_scalar_multiple", "priority": "high"}
        assert display_priority_for_pair_task(task) == "high"


class TestDisplayRiskLevelForJudgeRisk:
    def test_row_vector_only_context(self) -> None:
        risk = {"risk_level": "high", "reason": "drv-001 row vector", "evidence_refs": []}
        assert display_risk_level_for_judge_risk(risk) == "context"

    def test_stronger_signal_not_context(self) -> None:
        risk = {"risk_level": "high", "reason": "dc-001 fixed difference", "evidence_refs": []}
        assert display_risk_level_for_judge_risk(risk) == "high"


class TestManualTasksTable:
    def test_empty_tasks(self) -> None:
        result = manual_tasks_table([])
        assert "未生成" in result

    def test_renders_task(self) -> None:
        tasks = [
            {"task_id": "T-001", "priority": "high", "question": "Check data", "evidence_refs": ["F-001"]}
        ]
        result = manual_tasks_table(tasks)
        assert "T-001" in result
        assert "Check data" in result

    def test_limits_to_ten(self) -> None:
        tasks = [{"task_id": f"T-{i}", "priority": "high", "question": f"Q{i}"} for i in range(15)]
        result = manual_tasks_table(tasks)
        assert "T-14" not in result


# ---------------------------------------------------------------------------
# _source_data.py
# ---------------------------------------------------------------------------


