"""Tests for engine.static_audit.html_report module.

Merged from: test_html_report_{shared,submodules,findings,patterns,executive,visual}.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import json

from engine.static_audit.html_report._appendix import (
    artifact_links,
    canonical_mapping_table,
    claim_impact_matrix,
    investigation_table,
    judge_summary_text,
    material_plan_panel,
    risks_table,
    steps_table,
    traces_table,
)
from engine.static_audit.html_report._benign import (
    _benign_explanation_duplicate_numeric,
    _benign_explanation_formula_derivation,
    _benign_explanation_other,
    _benign_explanation_paired_offset,
    _benign_explanation_partial_copy,
    _benign_explanation_row_vector,
    _benign_explanation_visual_forensics,
    _benign_items_to_html,
    _parameterized_benign_explanation,
    cluster_benign_explanations,
    context_aware_review_question,
)
from engine.static_audit.html_report._clusters import (
    build_evidence_clusters,
    brief_list,
    claims_for_finding_ids,
    cluster_headline,
    evidence_cluster_cards,
    finding_signal,
    tasks_for_finding_ids,
)
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
from engine.static_audit.html_report._findings import (
    annotate_findings,
    best_paper_ref,
    collect_report_findings,
    dedupe_findings,
    default_finding_summary,
    evidence_card_findings,
    first_claim,
    map_findings_to_mappings,
    map_reviews,
    mapping_granularity_note,
    normalize_bundle_finding,
    paper_refs,
    pdf_locator_html,
    relation_text,
    render_findings_by_category,
    review_question,
    risk_for_finding,
    sample_evidence_html,
    sample_pairs_html,
    source_artifact_for_finding,
    source_locator,
    source_path_for_evidence_refs,
)
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
from engine.static_audit.html_report._patterns import (
    build_pattern_groups,
    displayable_patterns,
    factual_pattern_title,
    first_report_sentence,
    is_context_only_pattern,
    is_primary_pattern,
    key_sheets,
    pattern_agent_sentences,
    pattern_definition,
    pattern_sort_key,
    tier_patterns,
)
from engine.static_audit.html_report._shared import (
    SOURCE_DATA_FINDINGS_ARTIFACT,
    SOURCE_DATA_PAIR_FORENSICS_ARTIFACT,
)
from engine.static_audit.html_report._shared import (
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
from engine.static_audit.html_report._source_data import (
    display_risk_level_for_pair_cluster,
    evidence_locator,
    evidence_records_table,
    evidence_sample_text,
    evidence_source_text,
    excluded_findings_section,
    paperfraud_rule_section,
    pair_forensics_cluster_table,
    pair_forensics_review_tasks_table,
    pair_forensics_table,
    support_text,
)
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


# ===========================================================================
# Shared utilities (_shared)
# ===========================================================================


# ---------------------------------------------------------------------------
# h() and h_attr() — HTML escaping
# ---------------------------------------------------------------------------


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


class TestSourceArtifactForFinding:
    def test_explicit_source_artifact(self) -> None:
        finding = {"source_artifact": "custom.json"}
        assert source_artifact_for_finding(finding) == "custom.json"

    def test_pair_category_returns_pair_forensics(self) -> None:
        finding = {"category": "row_offset_scalar_multiple"}
        assert (
            source_artifact_for_finding(finding) == SOURCE_DATA_PAIR_FORENSICS_ARTIFACT
        )

    def test_paired_ratio_reuse(self) -> None:
        finding = {"category": "long_format_paired_ratio_reuse"}
        assert (
            source_artifact_for_finding(finding) == SOURCE_DATA_PAIR_FORENSICS_ARTIFACT
        )

    def test_duplicate_row_vector(self) -> None:
        finding = {"category": "duplicate_row_vector"}
        assert (
            source_artifact_for_finding(finding) == SOURCE_DATA_PAIR_FORENSICS_ARTIFACT
        )

    def test_workbook_returns_source_findings(self) -> None:
        finding = {"workbook": "source.xlsx", "category": "fixed_difference"}
        assert source_artifact_for_finding(finding) == SOURCE_DATA_FINDINGS_ARTIFACT

    def test_sheet_returns_source_findings(self) -> None:
        finding = {"sheet": "Sheet1", "category": "fixed_ratio"}
        assert source_artifact_for_finding(finding) == SOURCE_DATA_FINDINGS_ARTIFACT

    def test_fallback_to_bundle(self) -> None:
        finding = {"category": "unknown_category"}
        assert source_artifact_for_finding(finding) == "static_audit_bundle.json"


# ---------------------------------------------------------------------------
# relation_text()
# ---------------------------------------------------------------------------


class TestRelationText:
    def test_fixed_difference(self) -> None:
        finding = {
            "category": "fixed_difference",
            "relationship_value": "0.3",
            "column_pair": ["D", "E"],
        }
        result = relation_text(finding)
        assert "固定差关系" in result
        assert "0.3" in result
        assert "D, E" in result

    def test_duplicate_numeric_columns(self) -> None:
        finding = {"category": "duplicate_numeric_columns", "column_pair": ["B", "C"]}
        result = relation_text(finding)
        assert "数值列完全重复" in result
        assert "B, C" in result

    def test_row_offset_scalar_multiple(self) -> None:
        finding = {
            "category": "row_offset_scalar_multiple",
            "row_offset": 12,
            "columns": ["value"],
        }
        result = relation_text(finding)
        assert "固定行偏移" in result
        assert "12" in result

    def test_long_format_paired_ratio_reuse(self) -> None:
        finding = {
            "category": "long_format_paired_ratio_reuse",
            "pair_id_offset": 6,
            "columns": ["group_a", "group_b"],
        }
        result = relation_text(finding)
        assert "配对两组比例复用" in result
        assert "6" in result

    def test_duplicate_row_vector(self) -> None:
        finding = {"category": "duplicate_row_vector", "duplicate_row_count": 4}
        result = relation_text(finding)
        assert "行向量重复" in result
        assert "4" in result

    def test_unknown_category(self) -> None:
        finding = {"category": "some_unknown"}
        assert relation_text(finding) == "some_unknown"


# ---------------------------------------------------------------------------
# default_finding_summary()
# ---------------------------------------------------------------------------


class TestDefaultFindingSummary:
    def test_workbook_sheet_finding(self) -> None:
        finding = {
            "workbook": "source.xlsx",
            "sheet": "Fig2",
            "column_pair": ["B", "C"],
            "category": "fixed_difference",
        }
        result = default_finding_summary(finding)
        assert "source.xlsx" in result
        assert "Fig2" in result
        assert "B, C" in result

    def test_source_artifact_finding(self) -> None:
        finding = {"source_artifact": "image.json", "category": "copy_move"}
        result = default_finding_summary(finding)
        assert "copy_move" in result

    def test_summary_fallback(self) -> None:
        finding = {"summary": "Custom summary text"}
        result = default_finding_summary(finding)
        assert "Custom summary text" in result

    def test_category_fallback(self) -> None:
        finding = {"category": "unknown"}
        result = default_finding_summary(finding)
        assert "unknown" in result


# ---------------------------------------------------------------------------
# annotate_findings() / dedupe_findings()
# ---------------------------------------------------------------------------


class TestAnnotateAndDedupe:
    def test_annotate_adds_source_artifact(self) -> None:
        findings = [{"finding_id": "F-001", "category": "test"}]
        result = annotate_findings(findings, "custom.json")
        assert result[0]["source_artifact"] == "custom.json"

    def test_annotate_adds_issue_category(self) -> None:
        findings = [{"finding_id": "F-001"}]
        result = annotate_findings(findings, "test.json")
        assert result[0]["issue_category"] == "consistency"

    def test_annotate_preserves_existing_source_artifact(self) -> None:
        findings = [{"finding_id": "F-001", "source_artifact": "existing.json"}]
        result = annotate_findings(findings, "custom.json")
        assert result[0]["source_artifact"] == "existing.json"

    def test_annotate_skips_non_dict(self) -> None:
        findings = [{"finding_id": "F-001"}, "invalid", None]
        result = annotate_findings(findings, "test.json")
        assert len(result) == 1

    def test_dedupe_by_finding_id(self) -> None:
        findings = [
            {"finding_id": "F-001", "category": "a"},
            {"finding_id": "F-001", "category": "b"},
            {"finding_id": "F-002", "category": "c"},
        ]
        result = dedupe_findings(findings)
        assert len(result) == 2

    def test_dedupe_without_finding_id(self) -> None:
        findings = [{"category": "a"}, {"category": "a"}, {"category": "b"}]
        result = dedupe_findings(findings)
        assert len(result) == 2

    def test_dedupe_skips_non_dict(self) -> None:
        findings = [{"finding_id": "F-001"}, "invalid"]
        result = dedupe_findings(findings)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# collect_report_findings()
# ---------------------------------------------------------------------------


class TestCollectReportFindings:
    def test_merges_source_and_pair_findings(self) -> None:
        source = {
            "priority_findings": [
                {
                    "finding_id": "SRC-001",
                    "category": "fixed_difference",
                    "risk_level": "medium",
                }
            ]
        }
        pair = {
            "priority_findings": [
                {
                    "finding_id": "PAIR-001",
                    "category": "row_offset_scalar_multiple",
                    "risk_level": "high",
                }
            ]
        }
        bundle = {"findings": [], "evidence_items": []}
        result = collect_report_findings(source, pair, bundle)
        ids = [f["finding_id"] for f in result]
        assert "SRC-001" in ids
        assert "PAIR-001" in ids

    def test_suppressed_findings_excluded(self) -> None:
        source = {
            "priority_findings": [
                {
                    "finding_id": "SRC-001",
                    "category": "fixed_difference",
                    "risk_level": "medium",
                }
            ]
        }
        bundle = {
            "findings": [{"finding_id": "SRC-001", "suppressed_by": "other_finding"}],
            "evidence_items": [],
        }
        result = collect_report_findings(source, {}, bundle)
        assert len(result) == 0

    def test_bundle_findings_merged(self) -> None:
        source = {"priority_findings": []}
        bundle = {
            "findings": [
                {
                    "finding_id": "B-001",
                    "category": "execution_status",
                    "risk_level": "medium",
                    "metadata": {"source_artifact": "runtime.json"},
                }
            ],
            "evidence_items": [],
        }
        result = collect_report_findings(source, {}, bundle)
        assert any(f["finding_id"] == "B-001" for f in result)

    def test_sorted_by_risk_then_support(self) -> None:
        source = {
            "priority_findings": [
                {
                    "finding_id": "LOW",
                    "category": "fixed_difference",
                    "risk_level": "low",
                    "support_rows": 10,
                },
                {
                    "finding_id": "HIGH",
                    "category": "fixed_difference",
                    "risk_level": "high",
                    "support_rows": 5,
                },
            ]
        }
        bundle = {"findings": [], "evidence_items": []}
        result = collect_report_findings(source, {}, bundle)
        assert result[0]["finding_id"] == "HIGH"

    def test_deduplication_across_sources(self) -> None:
        source = {
            "priority_findings": [
                {
                    "finding_id": "DUP-001",
                    "category": "fixed_difference",
                    "risk_level": "medium",
                }
            ]
        }
        bundle = {
            "findings": [
                {
                    "finding_id": "DUP-001",
                    "category": "fixed_difference",
                    "risk_level": "medium",
                }
            ],
            "evidence_items": [],
        }
        result = collect_report_findings(source, {}, bundle)
        assert len([f for f in result if f["finding_id"] == "DUP-001"]) == 1


# ---------------------------------------------------------------------------
# map_findings_to_mappings() / map_reviews()
# ---------------------------------------------------------------------------


class TestFindingMappings:
    def test_map_findings_to_mappings(self) -> None:
        mappings = [
            {
                "mapping_id": "CM-001",
                "linked_priority_findings": [{"finding_id": "F-001"}],
            },
            {
                "mapping_id": "CM-002",
                "linked_priority_findings": [
                    {"finding_id": "F-001"},
                    {"finding_id": "F-002"},
                ],
            },
        ]
        result = map_findings_to_mappings(mappings)
        assert "F-001" in result
        assert len(result["F-001"]) == 2
        assert "F-002" in result

    def test_map_findings_to_mappings_empty(self) -> None:
        assert map_findings_to_mappings([]) == {}

    def test_map_reviews(self) -> None:
        reviews = [
            {"finding_id": "F-001", "disposition": "needs_review"},
            {"finding_id": "F-002", "disposition": "ok"},
        ]
        result = map_reviews(reviews)
        assert "F-001" in result
        assert result["F-001"]["disposition"] == "needs_review"

    def test_map_reviews_skips_no_id(self) -> None:
        reviews = [{"disposition": "orphan"}]
        result = map_reviews(reviews)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# risk_for_finding() / paper_refs() / best_paper_ref()
# ---------------------------------------------------------------------------


class TestRiskAndRefs:
    def test_risk_for_finding_found(self) -> None:
        risks = [{"evidence_refs": ["F-001"], "reason": "check this"}]
        result = risk_for_finding(risks, "F-001")
        assert result is not None
        assert result["reason"] == "check this"

    def test_risk_for_finding_not_found(self) -> None:
        risks = [{"evidence_refs": ["F-001"]}]
        assert risk_for_finding(risks, "F-999") is None

    def test_risk_for_finding_none_id(self) -> None:
        assert risk_for_finding([], None) is None

    def test_paper_refs_extracts_refs(self) -> None:
        mappings = [
            {"matched_paper_references": [{"text": "ref1"}, {"text": "ref2"}]},
            {"matched_paper_references": [{"text": "ref3"}]},
        ]
        refs = paper_refs(mappings)
        assert len(refs) == 3

    def test_best_paper_ref_prefers_long_text(self) -> None:
        refs = [
            {"text": "See next page"},
            {"text": "A" * 50},
        ]
        result = best_paper_ref(refs)
        assert len(result["text"]) == 50

    def test_best_paper_ref_empty(self) -> None:
        assert best_paper_ref([]) == {}

    def test_best_paper_ref_all_short(self) -> None:
        refs = [{"text": "short"}, {"text": "tiny"}]
        result = best_paper_ref(refs)
        assert result == refs[0]


# ---------------------------------------------------------------------------
# source_locator() / first_claim()
# ---------------------------------------------------------------------------


class TestSourceLocator:
    def test_line_range(self) -> None:
        ref = {"line_start": 10, "line_end": 20, "match_label": "Fig. 1"}
        result = source_locator({}, ref)
        assert result["line"] == "full.md:10-20"
        assert result["figure"] == "Fig. 1"

    def test_single_line(self) -> None:
        ref = {"line_start": 10, "match_label": "Fig. 2"}
        result = source_locator({}, ref)
        assert result["line"] == "full.md:10"

    def test_no_line_info(self) -> None:
        ref = {"match_label": "Fig. 3"}
        result = source_locator({}, ref)
        assert result["line"] == "未定位"

    def test_no_match_label(self) -> None:
        ref = {}
        result = source_locator({}, ref)
        assert result["figure"] == "-"


class TestFirstClaim:
    def test_from_candidate_claims(self) -> None:
        mappings = [{"candidate_claims": [{"text": "The treatment is effective."}]}]
        assert first_claim(mappings) == "The treatment is effective."

    def test_from_paper_references(self) -> None:
        mappings = [{"matched_paper_references": [{"text": "See figure 2."}]}]
        assert first_claim(mappings) == "See figure 2."

    def test_empty_mappings(self) -> None:
        assert first_claim([]) == ""

    def test_truncates_long_text(self) -> None:
        long_text = "A" * 1000
        mappings = [{"candidate_claims": [{"text": long_text}]}]
        result = first_claim(mappings)
        assert len(result) <= 700


# ---------------------------------------------------------------------------
# review_question() / mapping_granularity_note()
# ---------------------------------------------------------------------------


class TestReviewQuestion:
    def test_risk_requires_human_review(self) -> None:
        risk = {"requires_human_review": True, "reason": "Check data integrity"}
        result = review_question({}, risk, {})
        assert "Check data integrity" in result

    def test_workbook_sheet_review(self) -> None:
        finding = {"workbook": "source.xlsx", "sheet": "Sheet1"}
        result = review_question({}, None, finding)
        assert "workbook/sheet" in result

    def test_generic_review(self) -> None:
        result = review_question({}, None, {})
        assert "原始 artifact" in result

    def test_linked_claims_in_review(self) -> None:
        source_review = {"evidence_refs": {"linked_claims": ["AC-001", "AC-002"]}}
        result = review_question(source_review, None, {})
        assert "AC-001" in result
        assert "AC-002" in result


class TestMappingGranularityNote:
    def test_source_data_findings_note(self) -> None:
        finding = {"source_artifact": SOURCE_DATA_FINDINGS_ARTIFACT}
        result = mapping_granularity_note(finding)
        assert "figure/sheet 级" in result

    def test_pair_forensics_note(self) -> None:
        finding = {"source_artifact": SOURCE_DATA_PAIR_FORENSICS_ARTIFACT}
        result = mapping_granularity_note(finding)
        assert "figure/sheet 级" in result

    def test_other_artifact_note(self) -> None:
        finding = {"source_artifact": "static_audit_bundle.json"}
        result = mapping_granularity_note(finding)
        assert "原始 artifact" in result


# ---------------------------------------------------------------------------
# pdf_locator_html()
# ---------------------------------------------------------------------------


class TestPdfLocatorHtml:
    def test_with_page_and_bbox(self) -> None:
        ref = {"page": 5, "bbox": [100, 200, 300, 400]}
        result = pdf_locator_html(ref)
        assert "page=5" in result
        assert "bbox=" in result

    def test_with_page_only(self) -> None:
        ref = {"page_number": 3}
        result = pdf_locator_html(ref)
        assert "page=3" in result

    def test_no_page_or_bbox(self) -> None:
        ref = {}
        result = pdf_locator_html(ref)
        assert "page/bbox 未记录" in result


# ---------------------------------------------------------------------------
# sample_evidence_html() / sample_pairs_html()
# ---------------------------------------------------------------------------


class TestSampleEvidence:
    def test_with_sample_pairs(self) -> None:
        finding = {"sample_pairs": [{"row": 1, "left": "0.5", "right": "0.3"}]}
        result = sample_evidence_html(finding)
        assert "sample-row" in result
        assert "0.5" in result

    def test_no_sample_data(self) -> None:
        finding = {}
        result = sample_evidence_html(finding)
        assert "muted" in result

    def test_sample_pairs_html_empty(self) -> None:
        result = sample_pairs_html([])
        assert "muted" in result

    def test_sample_pairs_html_with_data(self) -> None:
        pairs = [
            {"row": 1, "left": "0.5", "right": "0.3"},
            {"row": 2, "left": "0.6", "right": "0.4"},
        ]
        result = sample_pairs_html(pairs)
        assert "sample-row" in result
        assert "左列" in result

    def test_sample_pairs_limits_to_eight(self) -> None:
        pairs = [{"row": i, "left": str(i), "right": str(i + 1)} for i in range(10)]
        result = sample_pairs_html(pairs)
        # Should only render 8 rows
        assert result.count("sample-row") <= 10  # header + 8 data rows


# ---------------------------------------------------------------------------
# evidence_card_findings()
# ---------------------------------------------------------------------------


class TestEvidenceCardFindings:
    def test_sorted_by_score_and_limited(self) -> None:
        findings = [
            {
                "finding_id": f"F-{i}",
                "risk_level": "low",
                "category": "fixed_difference",
            }
            for i in range(15)
        ]
        findings[0]["risk_level"] = "critical"
        result = evidence_card_findings(findings)
        assert len(result) <= 8
        assert result[0]["finding_id"] == "F-0"

    def test_empty_findings(self) -> None:
        assert evidence_card_findings([]) == []


# ---------------------------------------------------------------------------
# render_findings_by_category()
# ---------------------------------------------------------------------------


class TestRenderFindingsByCategory:
    def test_empty_findings(self) -> None:
        result = render_findings_by_category({}, {}, {}, [])
        assert "未生成高优先级复核记录" in result

    def test_groups_by_category(self) -> None:
        findings = [
            {
                "finding_id": "F-001",
                "issue_category": "consistency",
                "risk_level": "high",
                "category": "fixed_difference",
            },
            {
                "finding_id": "F-002",
                "issue_category": "completeness",
                "risk_level": "low",
                "category": "source_data_missing",
            },
        ]
        result = render_findings_by_category(findings, {}, {}, [])
        assert "一致性问题" in result
        assert "完整性问题" in result
        assert "一、" in result
        assert "三、" in result

    def test_category_count(self) -> None:
        findings = [
            {
                "finding_id": "F-001",
                "issue_category": "consistency",
                "risk_level": "high",
                "category": "a",
            },
            {
                "finding_id": "F-002",
                "issue_category": "consistency",
                "risk_level": "high",
                "category": "b",
            },
        ]
        result = render_findings_by_category(findings, {}, {}, [])
        assert "(2 条)" in result


# ---------------------------------------------------------------------------
# source_path_for_evidence_refs()
# ---------------------------------------------------------------------------


class TestSourcePathForEvidenceRefs:
    def test_resolves_paths_from_bundle(self) -> None:
        bundle = {
            "evidence_items": [
                {"evidence_id": "EV-001", "source_path": "images/fig1.png"},
                {"evidence_id": "EV-002", "source_path": "images/fig2.png"},
            ]
        }
        result = source_path_for_evidence_refs(["EV-001", "EV-002"], bundle)
        assert "images/fig1.png" in result
        assert "images/fig2.png" in result

    def test_deduplicates_paths(self) -> None:
        bundle = {
            "evidence_items": [
                {"evidence_id": "EV-001", "source_path": "images/fig1.png"},
            ]
        }
        result = source_path_for_evidence_refs(["EV-001", "EV-001"], bundle)
        assert result.count("images/fig1.png") == 1

    def test_unknown_ref_returns_empty(self) -> None:
        bundle = {"evidence_items": []}
        result = source_path_for_evidence_refs(["EV-999"], bundle)
        assert result == ""


# ---------------------------------------------------------------------------
# normalize_bundle_finding()
# ---------------------------------------------------------------------------


class TestNormalizeBundleFinding:
    def test_basic_normalization(self) -> None:
        item = {
            "finding_id": "F-001",
            "category": "test_category",
            "risk_level": "high",
            "metadata": {"source_artifact": "test.json"},
        }
        bundle = {"evidence_items": []}
        result = normalize_bundle_finding(item, bundle)
        assert result["finding_id"] == "F-001"
        assert result["category"] == "test_category"
        assert result["source_artifact"] == "test.json"
        assert result["issue_category"] == "consistency"

    def test_metadata_merged(self) -> None:
        item = {
            "finding_id": "F-001",
            "metadata": {"custom_field": "value", "source_artifact": "meta.json"},
        }
        bundle = {"evidence_items": []}
        result = normalize_bundle_finding(item, bundle)
        assert result.get("custom_field") == "value"

    def test_source_path_resolved_from_evidence(self) -> None:
        item = {
            "finding_id": "F-001",
            "evidence_refs": ["EV-001"],
            "metadata": {},
        }
        bundle = {
            "evidence_items": [
                {"evidence_id": "EV-001", "source_path": "images/fig1.png"}
            ]
        }
        result = normalize_bundle_finding(item, bundle)
        assert result["source_path"] == "images/fig1.png"


# ===========================================================================
# Patterns and benign explanations (_patterns, _benign)
# ===========================================================================


# ---------------------------------------------------------------------------
# pattern_sort_key()
# ---------------------------------------------------------------------------


class TestPatternSortKey:
    def test_paired_offset_first(self) -> None:
        key = pattern_sort_key(("paired_offset_ratio_reuse", [1, 2, 3]))
        assert key[0] == 0

    def test_other_last(self) -> None:
        key = pattern_sort_key(("other", [1]))
        assert key[0] == 9

    def test_unknown_key_default(self) -> None:
        key = pattern_sort_key(("unknown_key", [1]))
        assert key[0] == 7

    def test_more_findings_sorts_earlier(self) -> None:
        key_few = pattern_sort_key(("other", [1]))
        key_many = pattern_sort_key(("other", [1, 2, 3, 4, 5]))
        assert key_many < key_few  # negative count


# ---------------------------------------------------------------------------
# pattern_definition()
# ---------------------------------------------------------------------------


class TestPatternDefinition:
    def test_known_keys(self) -> None:
        for key in [
            "paired_offset_ratio_reuse",
            "row_vector_reuse",
            "duplicate_numeric_columns",
            "formula_derivation",
            "visual_forensics",
            "numeric_forensics",
            "other",
        ]:
            defn = pattern_definition(key)
            assert "title" in defn
            assert "thesis" in defn
            assert "review_question" in defn

    def test_category_prefix(self) -> None:
        defn = pattern_definition("category:source_data_missing")
        assert "完整性问题" in defn["title"] or "source_data_missing" in defn["title"]

    def test_unknown_key_returns_other(self) -> None:
        defn = pattern_definition("totally_unknown")
        other_defn = pattern_definition("other")
        assert defn == other_defn


# ---------------------------------------------------------------------------
# key_sheets()
# ---------------------------------------------------------------------------


class TestKeySheets:
    def test_extracts_unique_sheets(self) -> None:
        clusters = [
            {"sheet": "Sheet1"},
            {"sheet": "Sheet2"},
            {"sheet": "Sheet1"},  # duplicate
        ]
        result = key_sheets(clusters, 10)
        assert result == ["Sheet1", "Sheet2"]

    def test_respects_limit(self) -> None:
        clusters = [{"sheet": f"Sheet{i}"} for i in range(10)]
        result = key_sheets(clusters, 3)
        assert len(result) == 3

    def test_skips_empty_sheets(self) -> None:
        clusters = [{"sheet": ""}, {"sheet": "Sheet1"}]
        result = key_sheets(clusters, 10)
        assert result == ["Sheet1"]


# ---------------------------------------------------------------------------
# factual_pattern_title()
# ---------------------------------------------------------------------------


class TestFactualPatternTitle:
    def test_uses_most_common_category(self) -> None:
        findings = [
            {"category": "fixed_difference"},
            {"category": "fixed_difference"},
            {"category": "fixed_ratio"},
        ]
        result = factual_pattern_title("formula_derivation", findings)
        assert "固定差关系" in result
        assert "3 条原始记录" in result

    def test_fallback_to_pattern_key_label(self) -> None:
        findings = [{"category": ""}]
        result = factual_pattern_title("category:custom_type", findings)
        assert "1 条原始记录" in result

    def test_empty_findings(self) -> None:
        result = factual_pattern_title("other", [])
        assert "0 条原始记录" in result


# ---------------------------------------------------------------------------
# first_report_sentence()
# ---------------------------------------------------------------------------


class TestFirstReportSentence:
    def test_splits_at_period(self) -> None:
        result = first_report_sentence("第一句。第二句。")
        assert result.startswith("第一句")
        assert "第二句" not in result

    def test_removes_confirmation_suffix(self) -> None:
        result = first_report_sentence("需确认这些数据是否合法")
        assert "需确认" not in result

    def test_strips_trailing_punctuation(self) -> None:
        result = first_report_sentence("句子；；：")
        assert not result.endswith("；")


# ---------------------------------------------------------------------------
# displayable_patterns() / is_context_only_pattern()
# ---------------------------------------------------------------------------


class TestDisplayablePatterns:
    def test_filters_rule_source(self) -> None:
        patterns = [
            {"pattern_key": "test", "summary_source": "rule"},
            {"pattern_key": "test", "summary_source": "data"},
            {"pattern_key": "test", "summary_source": "agent"},
        ]
        result = displayable_patterns(patterns)
        assert len(result) == 2

    def test_filters_context_only(self) -> None:
        patterns = [
            {
                "pattern_key": "row_vector_reuse",
                "summary_source": "data",
                "findings": [{"category": "duplicate_row_vector"}],
            }
        ]
        result = displayable_patterns(patterns)
        assert len(result) == 0


class TestIsContextOnlyPattern:
    def test_non_row_vector_key(self) -> None:
        assert is_context_only_pattern({"pattern_key": "other"}) is False

    def test_row_vector_with_all_drv(self) -> None:
        pattern = {
            "pattern_key": "row_vector_reuse",
            "findings": [{"category": "duplicate_row_vector"}],
        }
        assert is_context_only_pattern(pattern) is True

    def test_row_vector_with_mixed_categories(self) -> None:
        pattern = {
            "pattern_key": "row_vector_reuse",
            "findings": [
                {"category": "duplicate_row_vector"},
                {"category": "row_offset_scalar_multiple"},
            ],
        }
        assert is_context_only_pattern(pattern) is False

    def test_row_vector_no_findings(self) -> None:
        pattern = {"pattern_key": "row_vector_reuse", "findings": []}
        assert is_context_only_pattern(pattern) is True


# ---------------------------------------------------------------------------
# is_primary_pattern() / tier_patterns()
# ---------------------------------------------------------------------------


class TestTierPatterns:
    def test_primary_requires_high_risk_and_consistency(self) -> None:
        pattern = {
            "risk_level": "high",
            "findings": [{"issue_category": "consistency"}],
        }
        assert is_primary_pattern(pattern) is True

    def test_low_risk_not_primary(self) -> None:
        pattern = {
            "risk_level": "low",
            "findings": [{"issue_category": "consistency"}],
        }
        assert is_primary_pattern(pattern) is False

    def test_matching_category_not_primary(self) -> None:
        pattern = {
            "risk_level": "high",
            "findings": [{"issue_category": "matching"}],
        }
        assert is_primary_pattern(pattern) is False

    def test_tier_splits_correctly(self) -> None:
        patterns = [
            {
                "pattern_id": 1,
                "risk_level": "high",
                "findings": [{"issue_category": "consistency"}],
            },
            {
                "pattern_id": 2,
                "risk_level": "low",
                "findings": [{"issue_category": "consistency"}],
            },
            {
                "pattern_id": 3,
                "risk_level": "critical",
                "findings": [{"issue_category": "consistency"}],
            },
        ]
        primary, secondary = tier_patterns(patterns)
        assert len(primary) == 2
        assert len(secondary) == 1
        assert secondary[0]["pattern_id"] == 2

    def test_tier_respects_top_n(self) -> None:
        patterns = [
            {
                "pattern_id": i,
                "risk_level": "high",
                "findings": [{"issue_category": "consistency"}],
            }
            for i in range(30)
        ]
        primary, secondary = tier_patterns(patterns, top_n=5)
        assert len(primary) == 5
        assert len(secondary) == 25


# ---------------------------------------------------------------------------
# pattern_agent_sentences()
# ---------------------------------------------------------------------------


class TestPatternAgentSentences:
    def test_from_risks(self) -> None:
        risks = [{"reason": "Risk reason 1"}]
        result = pattern_agent_sentences([], risks, [])
        assert "Risk reason 1" in result

    def test_from_reviews(self) -> None:
        reviews = [{"benign_explanations": ["Explanation 1", "Explanation 2"]}]
        result = pattern_agent_sentences([], [], reviews)
        assert "Explanation 1" in result
        assert "Explanation 2" not in result  # only first

    def test_from_manual_tasks(self) -> None:
        tasks = [{"question": "Check this data"}]
        result = pattern_agent_sentences(tasks, [], [])
        assert "Check this data" in result

    def test_deduplication(self) -> None:
        risks = [{"reason": "Same text"}]
        tasks = [{"question": "Same text"}]
        result = pattern_agent_sentences(tasks, risks, [])
        assert result.count("Same text") == 1


# ---------------------------------------------------------------------------
# Benign explanation helpers
# ---------------------------------------------------------------------------


class TestBenignExplanations:
    def test_paired_offset(self) -> None:
        findings = [
            {
                "sheet": "Sheet1",
                "column_pair": ["A", "B"],
                "row_offset": 10,
                "support_rate": 1.0,
            }
        ]
        result = _benign_explanation_paired_offset(findings)
        assert "Sheet1" in result[0]
        assert "A, B" in result[0]
        assert "行偏移" in result[0]

    def test_paired_offset_complete_pattern(self) -> None:
        findings = [
            {"sheet": "Sheet1", "pattern_strength": "complete", "row_offset": 5}
        ]
        result = _benign_explanation_paired_offset(findings)
        assert any("complete" in item for item in result)

    def test_row_vector(self) -> None:
        findings = [
            {"sheet": "Sheet1", "column_pair": ["A", "B"], "duplicate_row_count": 4}
        ]
        result = _benign_explanation_row_vector(findings)
        assert "行向量重复" in result[0]

    def test_duplicate_numeric(self) -> None:
        findings = [{"sheet": "Sheet1", "column_pair": ["A", "B"]}]
        result = _benign_explanation_duplicate_numeric(findings)
        assert "高度相同" in result[0]

    def test_partial_copy(self) -> None:
        findings = [{"sheet": "Sheet1", "column_pair": ["A", "B"]}]
        result = _benign_explanation_partial_copy(findings)
        assert "部分复用" in result[0]

    def test_formula_derivation(self) -> None:
        findings = [
            {"sheet": "Sheet1", "column_pair": ["A", "B"], "category": "fixed_ratio"}
        ]
        result = _benign_explanation_formula_derivation(findings)
        assert "公式派生" in result[0] or "单位换算" in result[0]

    def test_visual_forensics_copy_move(self) -> None:
        findings = [
            {
                "category": "copy_move_single",
                "source_panel_id": "P-001",
                "target_panel_id": "P-002",
                "score": 0.85,
            }
        ]
        result = _benign_explanation_visual_forensics(findings)
        assert "局部相似" in result[0]

    def test_visual_forensics_forged(self) -> None:
        findings = [
            {
                "category": "forged_region_suspicious",
                "figure_id": "Fig.1",
                "integrity_score": 0.7,
            }
        ]
        result = _benign_explanation_visual_forensics(findings)
        assert "区域完整性" in result[0]

    def test_visual_forensics_generic(self) -> None:
        findings = [{"category": "unknown_visual"}]
        result = _benign_explanation_visual_forensics(findings)
        assert len(result) >= 1

    def test_other_source_data_missing(self) -> None:
        findings = [
            {
                "category": "source_data_missing",
                "finding_id": "SDM-SUMMARY-001",
                "figure_label": "Fig.1",
            }
        ]
        result = _benign_explanation_other(findings)
        assert "Fig.1" in result[0]
        assert "Source Data" in result[0]

    def test_other_no_missing(self) -> None:
        findings = [{"category": "something_else"}]
        result = _benign_explanation_other(findings)
        assert result == []


class TestParameterizedBenignExplanation:
    def test_dispatches_to_handler(self) -> None:
        findings = [{"sheet": "Sheet1", "column_pair": ["A", "B"]}]
        result = _parameterized_benign_explanation(
            "duplicate_numeric_columns", findings
        )
        assert "高度相同" in result[0]

    def test_visual_forensics(self) -> None:
        findings = [{"category": "copy_move_single"}]
        result = _parameterized_benign_explanation("visual_forensics", findings)
        assert len(result) >= 1

    def test_execution_evidence(self) -> None:
        result = _parameterized_benign_explanation("execution_evidence", [])
        assert "环境差异" in result[0]

    def test_numeric_forensics(self) -> None:
        result = _parameterized_benign_explanation("numeric_forensics", [])
        assert "OCR" in result[0]

    def test_generic_fallback(self) -> None:
        result = _parameterized_benign_explanation("unknown_pattern", [])
        assert "归一化" in result[0]


# ---------------------------------------------------------------------------
# cluster_benign_explanations()
# ---------------------------------------------------------------------------


class TestClusterBenignExplanations:
    def test_from_reviews(self) -> None:
        reviews = [{"benign_explanations": ["Agent explanation"]}]
        result = cluster_benign_explanations([], reviews)
        assert ("Agent explanation", "agent") in result

    def test_from_findings(self) -> None:
        findings = [{"benign_explanations": ["Finding explanation"]}]
        result = cluster_benign_explanations(findings, [])
        assert ("Finding explanation", "agent") in result

    def test_parameterized_fallback(self) -> None:
        findings = [
            {
                "category": "duplicate_numeric_columns",
                "sheet": "Sheet1",
                "column_pair": ["A", "B"],
            }
        ]
        result = cluster_benign_explanations(findings, [])
        assert any(source == "data" for _, source in result)

    def test_deduplication(self) -> None:
        reviews = [{"benign_explanations": ["Same text"]}]
        findings = [{"benign_explanations": ["Same text"]}]
        result = cluster_benign_explanations(findings, reviews)
        texts = [text for text, _ in result]
        assert texts.count("Same text") == 1

    def test_limits_to_five(self) -> None:
        reviews = [{"benign_explanations": [f"Explanation {i}" for i in range(10)]}]
        result = cluster_benign_explanations([], reviews)
        assert len(result) <= 5


# ---------------------------------------------------------------------------
# context_aware_review_question()
# ---------------------------------------------------------------------------


class TestContextAwareReviewQuestion:
    def test_paired_offset_handler(self) -> None:
        findings = [{"sheet": "Sheet1", "row_offset": 10, "support_rate": 0.95}]
        result = context_aware_review_question("paired_offset_ratio_reuse", findings)
        assert "Sheet1" in result
        assert "行偏移" in result

    def test_row_vector_handler(self) -> None:
        findings = [{"sheet": "Sheet1", "duplicate_row_count": 4}]
        result = context_aware_review_question("row_vector_reuse", findings)
        assert "行向量重复" in result

    def test_duplicate_numeric_handler(self) -> None:
        findings = [{"sheet": "Sheet1", "column_pair": ["A", "B"]}]
        result = context_aware_review_question("duplicate_numeric_columns", findings)
        assert "高度相同" in result

    def test_visual_forensics_handler(self) -> None:
        findings = [{"source_panel_id": "P-001", "score": 0.85}]
        result = context_aware_review_question("visual_forensics", findings)
        assert "P-001" in result

    def test_category_prefix_handler(self) -> None:
        findings = [{"category": "source_data_missing"}]
        result = context_aware_review_question("category:source_data_missing", findings)
        assert "source_data_missing" in result
        assert "1 条" in result

    def test_numeric_forensics_fallback(self) -> None:
        result = context_aware_review_question("numeric_forensics", [])
        assert "数字取证" in result or "原始表格" in result


# ---------------------------------------------------------------------------
# _benign_items_to_html()
# ---------------------------------------------------------------------------


class TestBenignItemsToHtml:
    def test_empty(self) -> None:
        result = _benign_items_to_html([])
        assert "muted" in result

    def test_string_items(self) -> None:
        result = _benign_items_to_html(["Explanation 1", "Explanation 2"])
        assert "Explanation 1" in result
        assert "Explanation 2" in result

    def test_tuple_items_with_source(self) -> None:
        items = [("Agent text", "agent"), ("Data text", "data")]
        result = _benign_items_to_html(items)
        assert "conf-agent" in result
        assert "conf-data" in result


# ---------------------------------------------------------------------------
# build_pattern_groups()
# ---------------------------------------------------------------------------


class TestBuildPatternGroups:
    def test_groups_findings_by_pattern_key(self) -> None:
        findings = [
            {
                "finding_id": "F-001",
                "category": "fixed_difference",
                "risk_level": "high",
                "sheet": "Sheet1",
            },
            {
                "finding_id": "F-002",
                "category": "fixed_ratio",
                "risk_level": "medium",
                "sheet": "Sheet2",
            },
        ]
        result = build_pattern_groups(findings, [], [], [], {}, [])
        # Both fixed_difference and fixed_ratio map to formula_derivation
        keys = [p["pattern_key"] for p in result]
        assert "formula_derivation" in keys

    def test_pattern_has_required_fields(self) -> None:
        findings = [
            {
                "finding_id": "F-001",
                "category": "duplicate_numeric_columns",
                "risk_level": "high",
                "sheet": "Sheet1",
            }
        ]
        result = build_pattern_groups(findings, [], [], [], {}, [])
        assert len(result) == 1
        pattern = result[0]
        assert "pattern_id" in pattern
        assert "pattern_key" in pattern
        assert "title" in pattern
        assert "thesis" in pattern
        assert "risk_level" in pattern
        assert "findings" in pattern
        assert "sheets" in pattern

    def test_empty_findings(self) -> None:
        result = build_pattern_groups([], [], [], [], {}, [])
        assert result == []


# ===========================================================================
# Executive summary (_executive)
# ===========================================================================


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


# ===========================================================================
# Visual forensics (_visual)
# ===========================================================================


# ---------------------------------------------------------------------------
# _visual_img()
# ---------------------------------------------------------------------------


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


class TestClaimsForFindingIds:
    def test_matches_by_source_data_refs(self) -> None:
        claims = [{"claim_id": "AC-001", "claim_text": "Test claim"}]
        mappings = [
            {"claim_id": "AC-001", "source_data_refs": ["source_data_findings:F-001"]}
        ]
        result = claims_for_finding_ids(["F-001"], claims, mappings)
        assert len(result) == 1
        assert result[0]["claim_id"] == "AC-001"

    def test_no_match(self) -> None:
        claims = [{"claim_id": "AC-001"}]
        mappings = [{"claim_id": "AC-001", "source_data_refs": ["F-999"]}]
        result = claims_for_finding_ids(["F-001"], claims, mappings)
        assert len(result) == 0

    def test_matches_by_evidence_refs(self) -> None:
        claims = [{"claim_id": "AC-001", "evidence_refs": ["F-001"]}]
        result = claims_for_finding_ids(["F-001"], claims, [])
        assert len(result) == 1


class TestTasksForFindingIds:
    def test_matches_by_evidence_refs(self) -> None:
        tasks = [{"task_id": "T-001", "evidence_refs": ["source_data_findings:F-001"]}]
        result = tasks_for_finding_ids(["F-001"], tasks)
        assert len(result) == 1

    def test_no_match(self) -> None:
        tasks = [{"task_id": "T-001", "evidence_refs": ["F-999"]}]
        result = tasks_for_finding_ids(["F-001"], tasks)
        assert len(result) == 0


class TestClusterHeadline:
    def test_renders_headline(self) -> None:
        findings = [
            {"category": "fixed_difference"},
            {"category": "fixed_ratio"},
        ]
        result = cluster_headline("Sheet1", findings, [])
        assert "Sheet1" in result
        assert "2 条" in result

    def test_with_claims(self) -> None:
        result = cluster_headline("Sheet1", [{"category": "test"}], [{"claim_id": "AC-001"}])
        assert "已关联 1 条论文表述" in result


class TestFindingSignal:
    def test_row_offset_signal(self) -> None:
        finding = {
            "category": "row_offset_scalar_multiple",
            "row_offset": 10,
            "columns": ["value"],
            "support_rows": 10,
        }
        result = finding_signal(finding)
        assert "固定行偏移" in result
        assert "10" in result

    def test_paired_ratio_reuse_signal(self) -> None:
        finding = {
            "category": "long_format_paired_ratio_reuse",
            "pair_id_offset": 6,
            "columns": ["group_a"],
        }
        result = finding_signal(finding)
        assert "比例复用" in result

    def test_duplicate_row_vector_signal(self) -> None:
        finding = {
            "category": "duplicate_row_vector",
            "duplicate_row_count": 4,
            "columns": ["A"],
        }
        result = finding_signal(finding)
        assert "行向量重复" in result

    def test_generic_signal(self) -> None:
        finding = {"category": "unknown", "columns": ["A"]}
        result = finding_signal(finding)
        assert "unknown" in result or "支持行数" in result


class TestBuildEvidenceClusters:
    def test_groups_by_source_anchor(self) -> None:
        findings = [
            {"finding_id": "F-001", "workbook": "source.xlsx", "sheet": "Sheet1", "risk_level": "high", "category": "fixed_difference"},
            {"finding_id": "F-002", "workbook": "source.xlsx", "sheet": "Sheet1", "risk_level": "medium", "category": "fixed_ratio"},
            {"finding_id": "F-003", "workbook": "source.xlsx", "sheet": "Sheet2", "risk_level": "low", "category": "duplicate_numeric_columns"},
        ]
        result = build_evidence_clusters(findings, [], [], [], {}, [])
        assert len(result) == 2
        assert result[0]["cluster_id"] == "EC-001"

    def test_empty_findings(self) -> None:
        result = build_evidence_clusters([], [], [], [], {}, [])
        assert result == []


class TestEvidenceClusterCards:
    def test_empty_clusters(self) -> None:
        result = evidence_cluster_cards([])
        assert "未形成" in result

    def test_renders_cluster_card(self) -> None:
        from collections import Counter
        clusters = [
            {
                "cluster_id": "EC-001",
                "workbook": "source.xlsx",
                "sheet": "Sheet1",
                "risk_level": "high",
                "headline": "Test headline",
                "signals": ["Signal 1"],
                "claims": [],
                "manual_tasks": [],
                "categories": Counter({"fixed_difference": 1}),
                "finding_ids": ["F-001"],
                "benign_explanations": [],
                "source_artifact": "source_data_findings.json",
            }
        ]
        result = evidence_cluster_cards(clusters)
        assert "EC-001" in result
        assert "Sheet1" in result
        assert "Test headline" in result


class TestBriefList:
    def test_empty_clusters(self) -> None:
        result = brief_list([])
        assert "未生成" in result

    def test_renders_clusters(self) -> None:
        clusters = [
            {"sheet": "Sheet1", "headline": "Test headline"},
            {"sheet": "Sheet2", "headline": "Another headline"},
        ]
        result = brief_list(clusters)
        assert "Sheet1" in result
        assert "Sheet2" in result


# ---------------------------------------------------------------------------
# _manual_tasks.py
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


class TestEvidenceSourceText:
    def test_workbook_and_sheet(self) -> None:
        assert evidence_source_text({"workbook": "source.xlsx", "sheet": "Fig2"}) == "source.xlsx / Fig2"

    def test_source_path(self) -> None:
        assert evidence_source_text({"source_path": "images/fig.png"}) == "images/fig.png"

    def test_evidence_refs(self) -> None:
        assert evidence_source_text({"evidence_refs": ["EV-001"]}) == "EV-001"

    def test_no_source(self) -> None:
        assert evidence_source_text({}) == "-"


class TestEvidenceLocator:
    def test_columns_and_offset(self) -> None:
        result = evidence_locator({"columns": ["A", "B"], "row_offset": 10})
        assert "cols=A,B" in result
        assert "row_offset=10" in result

    def test_pair_id_offset(self) -> None:
        result = evidence_locator({"pair_id_offset": 6})
        assert "pair_id_offset=6" in result

    def test_formula(self) -> None:
        result = evidence_locator({"dominant_formula_pattern": "A/B"})
        assert "formula=A/B" in result

    def test_figure(self) -> None:
        result = evidence_locator({"figure": "Fig.1"})
        assert "figure=Fig.1" in result

    def test_empty(self) -> None:
        assert evidence_locator({}) == "-"


class TestSupportText:
    def test_support_and_overlap(self) -> None:
        result = support_text({"support_rows": 18, "overlap_rows": 20, "support_rate": 0.9})
        assert "18/20" in result
        assert "0.9" in result

    def test_with_pattern_strength(self) -> None:
        result = support_text({"support_rows": 18, "overlap_rows": 20, "support_rate": 1.0, "pattern_strength": "complete"})
        assert "complete" in result

    def test_support_only(self) -> None:
        result = support_text({"support_rows": 18})
        assert "18" in result

    def test_no_support(self) -> None:
        result = support_text({})
        assert "未记录" in result


class TestEvidenceSampleText:
    def test_sample_formulas(self) -> None:
        finding = {"sample_formulas": [{"ref": "C2", "formula": "=A2/B2"}]}
        result = evidence_sample_text(finding)
        assert "C2" in result
        assert "=A2/B2" in result

    def test_sample_pairs(self) -> None:
        finding = {"sample_pairs": [{"row": 1, "left": "0.5", "right": "0.3"}]}
        result = evidence_sample_text(finding)
        assert "0.5" in result

    def test_summary_fallback(self) -> None:
        finding = {"summary": "Custom summary"}
        result = evidence_sample_text(finding)
        assert "Custom summary" in result

    def test_no_sample_data(self) -> None:
        assert evidence_sample_text({}) == "-"


class TestEvidenceRecordsTable:
    def test_empty_findings(self) -> None:
        result = evidence_records_table([])
        assert "muted" in result

    def test_renders_findings(self) -> None:
        findings = [
            {"finding_id": "F-001", "category": "fixed_difference", "workbook": "source.xlsx", "sheet": "Sheet1", "support_rows": 18, "overlap_rows": 20}
        ]
        result = evidence_records_table(findings)
        assert "F-001" in result
        assert "固定差关系" in result


class TestPaperfraudRuleSection:
    def test_empty_artifact(self) -> None:
        result = paperfraud_rule_section({})
        assert "规则库提示" in result
        assert "未命中" in result or "muted" in result

    def test_with_triggered_rules(self) -> None:
        artifact = {
            "summary": {"total_rules_loaded": 48, "total_triggered": 1},
            "triggered_rules": [
                {"rule_id": "test.rule", "severity": "orange", "rule_type": "methodology_review", "title": "Test", "evidence": "Found X", "human_review": "Check X"}
            ],
        }
        result = paperfraud_rule_section(artifact)
        assert "test.rule" in result
        assert "orange" in result


class TestPairForensicsTables:
    def test_pair_forensics_table_empty(self) -> None:
        result = pair_forensics_table([])
        assert "未生成" in result

    def test_pair_forensics_table_with_data(self) -> None:
        findings = [
            {"finding_id": "PAIR-001", "category": "row_offset_scalar_multiple", "risk_level": "high", "workbook": "source.xlsx", "sheet": "Sheet1", "row_offset": 10, "support_rows": 10, "overlap_rows": 10}
        ]
        result = pair_forensics_table(findings)
        assert "PAIR-001" in result

    def test_pair_forensics_review_tasks_empty(self) -> None:
        result = pair_forensics_review_tasks_table([])
        assert "未生成" in result

    def test_pair_forensics_cluster_table_empty(self) -> None:
        result = pair_forensics_cluster_table([])
        assert "未生成" in result

    def test_display_risk_level_for_pair_cluster(self) -> None:
        assert display_risk_level_for_pair_cluster({"category": "duplicate_row_vector"}) == "context"
        assert display_risk_level_for_pair_cluster({"category": "other", "risk_level": "high"}) == "high"


class TestExcludedFindingsSection:
    def test_empty_excluded(self) -> None:
        assert excluded_findings_section([], {}) == ""

    def test_with_excluded_findings(self) -> None:
        excluded = [
            {
                "finding_id": "DC-FP-001",
                "category": "duplicate_numeric_columns",
                "workbook": "source.xlsx",
                "sheet": "Stats",
                "llm_verdict_confidence": 0.91,
                "llm_verdict_explanation": "Descriptive statistics",
                "llm_sheet_pattern": "descriptive_stats",
            }
        ]
        summary = {"total_findings": 2, "false_positive": 1, "true_positive": 0, "uncertain": 1}
        result = excluded_findings_section(excluded, summary)
        assert "DC-FP-001" in result
        assert "假阳性" in result


# ---------------------------------------------------------------------------
# _appendix.py
# ---------------------------------------------------------------------------


class TestStepsTable:
    def test_empty_steps(self) -> None:
        result = steps_table([])
        assert "<table" in result

    def test_renders_steps(self) -> None:
        steps = [{"key": "source_data_profile", "title": "Profile", "status": "ran", "detail": "Completed"}]
        result = steps_table(steps)
        assert "source_data_profile" in result
        assert "已执行" in result


class TestTracesTable:
    def test_empty_traces(self) -> None:
        result = traces_table([])
        assert "<table" in result

    def test_renders_traces(self) -> None:
        traces = [{"role_id": "claim_extractor", "status": "success", "output_summary": {"claims": 5}, "output_path": "output.json"}]
        result = traces_table(traces)
        assert "claim_extractor" in result
        assert "success" in result


class TestMaterialPlanPanel:
    def test_empty_material_plan(self) -> None:
        result = material_plan_panel({}, {})
        assert "材料清单" in result
        assert "材料处理计划" in result

    def test_with_lanes(self) -> None:
        plan = {
            "selected_optional_lanes": [
                {"lane_id": "source_data_xlsx", "status": "selected", "root": "source_data/", "reason": "Contains XLSX"}
            ]
        }
        result = material_plan_panel({}, plan)
        assert "source_data_xlsx" in result


class TestCanonicalMappingTable:
    def test_empty_mappings(self) -> None:
        result = canonical_mapping_table([], [])
        assert "未生成" in result

    def test_with_mappings(self) -> None:
        claims = [{"claim_id": "AC-001", "text": "Test claim"}]
        mappings = [{"mapping_id": "CM-001", "claim_id": "AC-001", "confidence": "high"}]
        result = canonical_mapping_table(claims, mappings)
        assert "CM-001" in result
        assert "AC-001" in result


class TestInvestigationTable:
    def test_empty_records(self) -> None:
        result = investigation_table([])
        assert "未生成" in result

    def test_with_records(self) -> None:
        records = [
            {"round_id": 1, "action_id": "IR-01-A001", "tool_id": "image.similarity_candidates", "status": "success", "hypothesis": "Check images", "output_artifacts": ["output.json"]}
        ]
        result = investigation_table(records)
        assert "IR-01-A001" in result
        assert "image.similarity_candidates" in result


class TestRisksTable:
    def test_empty_risks(self) -> None:
        result = risks_table([])
        assert "未生成" in result

    def test_with_risks(self) -> None:
        risks = [{"risk_level": "high", "reason": "Check data", "evidence_refs": ["F-001"]}]
        result = risks_table(risks)
        assert "Check data" in result


class TestJudgeSummaryText:
    def test_with_actual_artifacts(self) -> None:
        judge = {"technical_risk_summary": "均未产出，无法进行 claim-to-evidence 复核。"}
        extractor = {"claims": [{"claim_id": "AC-001"}]}
        auditor = {"claim_to_source_data": [{"claim_id": "AC-001"}], "finding_reviews": [], "manual_review_tasks": []}
        result = judge_summary_text(judge, extractor, auditor)
        assert "已按产物计数校正" in result

    def test_without_stale_markers(self) -> None:
        judge = {"technical_risk_summary": "All clear."}
        result = judge_summary_text(judge, {}, {})
        assert "All clear." in result


class TestArtifactLinks:
    def test_renders_links(self, tmp_path: Path) -> None:
        result = artifact_links(tmp_path)
        assert "artifact-list" in result
        assert "static_audit_bundle.json" in result

    def test_shows_missing_for_nonexistent(self, tmp_path: Path) -> None:
        result = artifact_links(tmp_path)
        assert "缺失" in result


class TestClaimImpactMatrix:
    def test_empty_mappings(self) -> None:
        result = claim_impact_matrix([], [], [])
        assert "未生成" in result

    def test_with_source_mappings(self) -> None:
        source_mappings = [{"claim_id": "AC-001", "source_data_refs": ["F-001"], "needs_human_review": True}]
        claims = [{"claim_id": "AC-001", "claim_text": "Test claim"}]
        result = claim_impact_matrix(source_mappings, claims, [])
        assert "AC-001" in result
        assert "Test claim" in result
