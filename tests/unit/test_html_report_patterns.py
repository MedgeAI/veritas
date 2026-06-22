"""Tests for engine.static_audit.html_report._patterns and _benign modules."""

from __future__ import annotations

from collections import Counter

from engine.static_audit.html_report._patterns import (
    build_pattern_groups,
    displayable_patterns,
    factual_pattern_title,
    first_report_sentence,
    is_context_only_pattern,
    is_primary_pattern,
    irreducible_evidence_ledger,
    key_sheets,
    pattern_agent_sentences,
    pattern_definition,
    pattern_display_text,
    pattern_group_cards,
    pattern_sort_key,
    tier_patterns,
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
    _collect_source_sheets_cols,
    _parameterized_benign_explanation,
    cluster_benign_explanations,
    context_aware_review_question,
)


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
            "paired_offset_ratio_reuse", "row_vector_reuse", "duplicate_numeric_columns",
            "formula_derivation", "visual_forensics", "numeric_forensics", "other",
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
            {"pattern_id": 1, "risk_level": "high", "findings": [{"issue_category": "consistency"}]},
            {"pattern_id": 2, "risk_level": "low", "findings": [{"issue_category": "consistency"}]},
            {"pattern_id": 3, "risk_level": "critical", "findings": [{"issue_category": "consistency"}]},
        ]
        primary, secondary = tier_patterns(patterns)
        assert len(primary) == 2
        assert len(secondary) == 1
        assert secondary[0]["pattern_id"] == 2

    def test_tier_respects_top_n(self) -> None:
        patterns = [
            {"pattern_id": i, "risk_level": "high", "findings": [{"issue_category": "consistency"}]}
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
            {"category": "forged_region_suspicious", "figure_id": "Fig.1", "integrity_score": 0.7}
        ]
        result = _benign_explanation_visual_forensics(findings)
        assert "区域完整性" in result[0]

    def test_visual_forensics_generic(self) -> None:
        findings = [{"category": "unknown_visual"}]
        result = _benign_explanation_visual_forensics(findings)
        assert len(result) >= 1

    def test_other_source_data_missing(self) -> None:
        findings = [
            {"category": "source_data_missing", "finding_id": "SDM-SUMMARY-001", "figure_label": "Fig.1"}
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
        result = _parameterized_benign_explanation("duplicate_numeric_columns", findings)
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
        findings = [{"category": "duplicate_numeric_columns", "sheet": "Sheet1", "column_pair": ["A", "B"]}]
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
        findings = [
            {"sheet": "Sheet1", "row_offset": 10, "support_rate": 0.95}
        ]
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
            {"finding_id": "F-001", "category": "fixed_difference", "risk_level": "high", "sheet": "Sheet1"},
            {"finding_id": "F-002", "category": "fixed_ratio", "risk_level": "medium", "sheet": "Sheet2"},
        ]
        result = build_pattern_groups(findings, [], [], [], {}, [])
        # Both fixed_difference and fixed_ratio map to formula_derivation
        keys = [p["pattern_key"] for p in result]
        assert "formula_derivation" in keys

    def test_pattern_has_required_fields(self) -> None:
        findings = [
            {"finding_id": "F-001", "category": "duplicate_numeric_columns", "risk_level": "high", "sheet": "Sheet1"}
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
