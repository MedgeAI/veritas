"""Tests for engine.follow_up module — generator, templates, prompts."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from engine.follow_up.generator import (
    LLMFollowUpGenerator,
    TemplateFollowUpGenerator,
    create_follow_up_generator,
)
from engine.follow_up.prompts import build_follow_up_prompt
from engine.follow_up.templates import (
    _column_ref,
    _first,
    _fmt_list,
    _gen_copy_move,
    _gen_default,
    _gen_exact_image_duplicate,
    _gen_fixed_relation,
    _gen_forged_region,
    _gen_overlap_reuse,
    _gen_paperfraud,
    _gen_paired_reuse,
    _gen_source_data_missing,
    _metadata,
    _panel_ref,
    _score_ref,
    _sheet_ref,
    _support_ref,
    generate_fallback_questions,
)


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


class TestFmtList:
    def test_list_of_strings(self) -> None:
        assert _fmt_list(["a", "b", "c"]) == "a, b, c"

    def test_list_of_ints(self) -> None:
        assert _fmt_list([1, 2, 3]) == "1, 2, 3"

    def test_string_passthrough(self) -> None:
        assert _fmt_list("hello") == "hello"

    def test_none_returns_na(self) -> None:
        assert _fmt_list(None) == "N/A"

    def test_empty_list_returns_empty(self) -> None:
        assert _fmt_list([]) == ""


class TestMetadata:
    def test_basic_metadata(self) -> None:
        finding = {"metadata": {"key": "value"}}
        result = _metadata(finding)
        assert result["key"] == "value"

    def test_nested_metadata_merged(self) -> None:
        finding = {"metadata": {"key1": "v1", "metadata": {"key2": "v2"}}}
        result = _metadata(finding)
        assert result["key1"] == "v1"
        assert result["key2"] == "v2"

    def test_no_metadata(self) -> None:
        assert _metadata({}) == {}

    def test_non_dict_metadata(self) -> None:
        assert _metadata({"metadata": "invalid"}) == {}


class TestFirst:
    def test_returns_first_non_empty(self) -> None:
        m = {"a": "", "b": None, "c": "value", "d": "other"}
        assert _first(m, "a", "b", "c", "d") == "value"

    def test_all_empty_returns_default(self) -> None:
        m = {"a": "", "b": None}
        assert _first(m, "a", "b", default="fallback") == "fallback"

    def test_list_value_skipped(self) -> None:
        m = {"a": [], "b": "value"}
        assert _first(m, "a", "b") == "value"


class TestColumnRef:
    def test_column_labels(self) -> None:
        assert _column_ref({"column_labels": ["E", "G"]}) == "E, G"

    def test_columns(self) -> None:
        assert _column_ref({"columns": ["A", "B"]}) == "A, B"

    def test_column_pair(self) -> None:
        assert _column_ref({"column_pair": ["D", "E"]}) == "D, E"

    def test_col_a_col_b(self) -> None:
        assert _column_ref({"col_a": "X", "col_b": "Y"}) == "X, Y"


class TestSheetRef:
    def test_workbook_and_sheet(self) -> None:
        assert _sheet_ref({"workbook": "source.xlsx", "sheet": "Fig2"}) == "source.xlsx / Fig2"

    def test_sheet_only(self) -> None:
        assert _sheet_ref({"sheet": "Fig2"}) == "Fig2"

    def test_workbook_only(self) -> None:
        assert _sheet_ref({"workbook": "source.xlsx"}) == "source.xlsx"

    def test_fallback(self) -> None:
        assert _sheet_ref({}) == "Source Data"

    def test_file_key(self) -> None:
        assert _sheet_ref({"file": "data.xlsx", "sheet": "Sheet1"}) == "data.xlsx / Sheet1"


class TestSupportRef:
    def test_equal_and_overlap_rows(self) -> None:
        result = _support_ref({"equal_rows": 18, "overlap_rows": 20})
        assert result == "18/20 行"

    def test_matched_and_overlap_pairs(self) -> None:
        result = _support_ref({"matched_pairs": 10, "overlap_pairs": 12})
        assert result == "10/12 对"

    def test_support_rate(self) -> None:
        result = _support_ref({"support_rate": 0.95})
        assert "0.95" in result

    def test_support_rows_fallback(self) -> None:
        result = _support_ref({"support_rows": 25})
        assert "25" in result

    def test_no_support_data(self) -> None:
        assert _support_ref({}) == "?"


class TestPanelRef:
    def test_panels_list(self) -> None:
        assert _panel_ref({"panels": ["P-001", "P-002"]}) == "P-001, P-002"

    def test_source_and_target(self) -> None:
        assert _panel_ref({"source_panel_id": "P-A", "target_panel_id": "P-B"}) == "P-A, P-B"


class TestScoreRef:
    def test_float_score(self) -> None:
        assert _score_ref({"score": 0.87}) == "0.870"

    def test_int_score(self) -> None:
        assert _score_ref({"score": 1}) == "1"

    def test_no_score(self) -> None:
        assert _score_ref({}) == ""

    def test_confidence_fallback(self) -> None:
        assert _score_ref({"confidence": 0.95}) == "0.950"


# ---------------------------------------------------------------------------
# Per-category generators
# ---------------------------------------------------------------------------


class TestGenDuplicateColumn:
    def test_basic(self) -> None:
        finding = {
            "category": "duplicate_numeric_columns",
            "metadata": {"workbook": "s.xlsx", "sheet": "S1", "column_labels": ["E", "G"], "equal_rows": 18, "overlap_rows": 18},
        }
        questions = generate_fallback_questions(finding)
        assert "s.xlsx / S1" in questions[0]
        assert "E, G" in questions[0]
        assert "18/18" in questions[0]


class TestGenFixedRelation:
    def test_fixed_difference(self) -> None:
        finding = {
            "category": "fixed_difference",
            "metadata": {"workbook": "s.xlsx", "sheet": "S1", "column_pair": ["D", "E"], "support_rows": 35, "overlap_rows": 35, "difference": "0.3"},
        }
        questions = generate_fallback_questions(finding)
        assert "固定差值关系" in questions[0]
        assert "0.3" in questions[0]

    def test_fixed_ratio(self) -> None:
        finding = {
            "category": "fixed_ratio",
            "metadata": {"workbook": "s.xlsx", "sheet": "S1", "column_pair": ["A", "B"], "support_rows": 20, "ratio": "2.0"},
        }
        questions = generate_fallback_questions(finding)
        assert "固定比例关系" in questions[0]
        assert "2.0" in questions[0]

    def test_formula_derived(self) -> None:
        finding = {
            "category": "formula_derived_column",
            "metadata": {"workbook": "s.xlsx", "sheet": "S1", "column_pair": ["A", "B"], "support_rows": 10, "value": "A/B"},
        }
        questions = generate_fallback_questions(finding)
        assert "公式派生" in questions[0]


class TestGenPairedReuse:
    def test_paired_ratio_reuse(self) -> None:
        finding = {
            "category": "long_format_paired_ratio_reuse",
            "metadata": {"workbook": "s.xlsx", "sheet": "S1", "column_pair": ["A", "B"], "matched_pairs": 10, "overlap_pairs": 10, "row_offset": 5},
        }
        questions = generate_fallback_questions(finding)
        assert "成对复用模式" in questions[0]
        assert "row_offset=5" in questions[0]

    def test_duplicate_row_vector(self) -> None:
        finding = {
            "category": "duplicate_row_vector",
            "metadata": {"workbook": "s.xlsx", "sheet": "S1", "duplicate_row_count": 4},
        }
        questions = generate_fallback_questions(finding)
        assert "成对复用模式" in questions[0]


class TestGenCopyMove:
    def test_basic(self) -> None:
        finding = {
            "category": "copy_move_cross",
            "metadata": {"source_panel_id": "P-A", "target_panel_id": "P-B", "score": 0.85, "match_method": "rootsift"},
        }
        questions = generate_fallback_questions(finding)
        assert "P-A" in questions[0]
        assert "P-B" in questions[0]
        assert "0.850" in questions[0]
        assert "rootsift" in questions[0]


class TestGenSourceDataMissing:
    def test_with_figure_id(self) -> None:
        finding = {"category": "source_data_missing", "metadata": {"figure_id": "Fig.3"}}
        questions = generate_fallback_questions(finding)
        assert "Fig.3" in questions[0]

    def test_without_figure_id(self) -> None:
        finding = {"category": "source_data_missing", "metadata": {}}
        questions = generate_fallback_questions(finding)
        assert "Source Data" in questions[0]


class TestGenExactImageDuplicate:
    def test_with_images(self) -> None:
        finding = {"category": "exact_image_duplicate", "metadata": {"images": ["fig1.png", "fig2.png"]}}
        questions = generate_fallback_questions(finding)
        assert "fig1.png" in questions[0]

    def test_with_file_a(self) -> None:
        finding = {"category": "exact_image_duplicate", "metadata": {"file_a": "img1.png"}}
        questions = generate_fallback_questions(finding)
        assert "img1.png" in questions[0]


class TestGenOverlapReuse:
    def test_basic(self) -> None:
        finding = {
            "category": "overlap_reuse_detected",
            "metadata": {"figure_a": "Fig.1", "figure_b": "Fig.2", "shared_area": "1234"},
        }
        questions = generate_fallback_questions(finding)
        assert "Fig.1" in questions[0]
        assert "Fig.2" in questions[0]
        assert "1234" in questions[0]


class TestGenForgedRegion:
    def test_basic(self) -> None:
        finding = {
            "category": "forged_region_suspicious",
            "metadata": {"source_panel_id": "P-001", "target_panel_id": "P-002", "score": 0.7, "heatmap_path": "heat.png"},
        }
        questions = generate_fallback_questions(finding)
        assert "P-001" in questions[0]
        assert "0.700" in questions[0]
        assert "heat.png" in questions[0]


class TestGenPaperfraud:
    def test_basic(self) -> None:
        finding = {
            "category": "paperfraud.fraud_detection",
            "summary": "Statistical anomaly detected",
            "metadata": {"rule_id": "statistical.test"},
        }
        questions = generate_fallback_questions(finding)
        assert "statistical.test" in questions[0]
        assert "Statistical anomaly" in questions[0]


class TestGenDefault:
    def test_with_finding_id(self) -> None:
        finding = {"finding_id": "GEN-001", "category": "unknown", "summary": "Custom finding"}
        questions = generate_fallback_questions(finding)
        assert "GEN-001" in questions[0]
        assert "Custom finding" in questions[0]

    def test_without_finding_id(self) -> None:
        finding = {"category": "unknown", "summary": "Custom finding"}
        questions = generate_fallback_questions(finding)
        assert "Custom finding" in questions[0]


# ---------------------------------------------------------------------------
# generate_fallback_questions() dispatch
# ---------------------------------------------------------------------------


class TestGenerateFallbackQuestions:
    def test_dispatches_to_correct_handler(self) -> None:
        finding = {"category": "duplicate_numeric_columns", "metadata": {"sheet": "S1"}}
        questions = generate_fallback_questions(finding)
        assert len(questions) >= 1

    def test_paperfraud_prefix(self) -> None:
        finding = {"category": "paperfraud.methodology_review", "summary": "test", "metadata": {"rule_id": "test.rule"}}
        questions = generate_fallback_questions(finding)
        assert "test.rule" in questions[0]

    def test_unknown_category_default(self) -> None:
        finding = {"category": "completely_unknown", "summary": "test"}
        questions = generate_fallback_questions(finding)
        assert len(questions) >= 1

    def test_empty_category(self) -> None:
        finding = {"category": ""}
        questions = generate_fallback_questions(finding)
        assert len(questions) >= 1


# ---------------------------------------------------------------------------
# TemplateFollowUpGenerator
# ---------------------------------------------------------------------------


class TestTemplateFollowUpGenerator:
    def test_name(self) -> None:
        gen = TemplateFollowUpGenerator()
        assert gen.name == "template"

    def test_generate_returns_questions(self) -> None:
        gen = TemplateFollowUpGenerator()
        finding = {"category": "duplicate_numeric_columns", "metadata": {"sheet": "S1"}}
        result = asyncio.run(gen.generate(finding))
        assert len(result) >= 1
        assert all(isinstance(q, str) for q in result)


# ---------------------------------------------------------------------------
# LLMFollowUpGenerator
# ---------------------------------------------------------------------------


class TestLLMFollowUpGenerator:
    def test_name_set_in_init(self) -> None:
        client = MagicMock()
        gen = LLMFollowUpGenerator(client)
        assert gen.name == "llm"

    def test_falls_back_on_llm_error(self) -> None:
        client = MagicMock()
        client.chat.side_effect = Exception("LLM unavailable")
        gen = LLMFollowUpGenerator(client)
        finding = {"category": "duplicate_numeric_columns", "metadata": {"sheet": "S1"}, "finding_id": "F-001"}
        result = asyncio.run(gen.generate(finding))
        assert len(result) >= 1  # Falls back to template

    def test_parses_valid_json_response(self) -> None:
        response = MagicMock()
        response.content = json.dumps({"questions": ["Q1", "Q2"]})
        client = MagicMock()
        client.chat.return_value = response
        gen = LLMFollowUpGenerator(client)
        finding = {"category": "test", "metadata": {}}
        result = asyncio.run(gen.generate(finding))
        assert result == ["Q1", "Q2"]

    def test_limits_to_two_questions(self) -> None:
        response = MagicMock()
        response.content = json.dumps({"questions": ["Q1", "Q2", "Q3"]})
        client = MagicMock()
        client.chat.return_value = response
        gen = LLMFollowUpGenerator(client)
        finding = {"category": "test", "metadata": {}}
        result = asyncio.run(gen.generate(finding))
        assert len(result) == 2

    def test_falls_back_on_invalid_json(self) -> None:
        response = MagicMock()
        response.content = "not json"
        client = MagicMock()
        client.chat.return_value = response
        gen = LLMFollowUpGenerator(client)
        finding = {"category": "test", "metadata": {}}
        result = asyncio.run(gen.generate(finding))
        assert len(result) >= 1  # Falls back

    def test_falls_back_on_empty_questions(self) -> None:
        response = MagicMock()
        response.content = json.dumps({"questions": []})
        client = MagicMock()
        client.chat.return_value = response
        gen = LLMFollowUpGenerator(client)
        finding = {"category": "test", "metadata": {}}
        result = asyncio.run(gen.generate(finding))
        assert len(result) >= 1  # Falls back


# ---------------------------------------------------------------------------
# create_follow_up_generator()
# ---------------------------------------------------------------------------


class TestCreateFollowUpGenerator:
    def test_returns_template_when_no_llm(self) -> None:
        deps = MagicMock()
        deps.llm_client = None
        gen = create_follow_up_generator(deps)
        assert isinstance(gen, TemplateFollowUpGenerator)

    def test_returns_template_when_llm_unavailable(self) -> None:
        deps = MagicMock()
        deps.llm_client = MagicMock()
        deps.llm_client.is_available.return_value = False
        gen = create_follow_up_generator(deps)
        assert isinstance(gen, TemplateFollowUpGenerator)

    def test_returns_llm_when_available(self) -> None:
        deps = MagicMock()
        deps.llm_client = MagicMock()
        deps.llm_client.is_available.return_value = True
        gen = create_follow_up_generator(deps)
        assert isinstance(gen, LLMFollowUpGenerator)


# ---------------------------------------------------------------------------
# build_follow_up_prompt()
# ---------------------------------------------------------------------------


class TestBuildFollowUpPrompt:
    def test_contains_finding_id(self) -> None:
        finding = {"finding_id": "F-001", "category": "test"}
        prompt = build_follow_up_prompt(finding)
        assert "F-001" in prompt

    def test_contains_category(self) -> None:
        finding = {"category": "duplicate_numeric_columns"}
        prompt = build_follow_up_prompt(finding)
        assert "duplicate_numeric_columns" in prompt

    def test_contains_metadata_json(self) -> None:
        finding = {"metadata": {"workbook": "source.xlsx"}}
        prompt = build_follow_up_prompt(finding)
        assert "source.xlsx" in prompt

    def test_contains_output_format(self) -> None:
        prompt = build_follow_up_prompt({})
        assert "questions" in prompt

    def test_default_values_for_missing_keys(self) -> None:
        prompt = build_follow_up_prompt({})
        assert "N/A" in prompt
        assert "unknown" in prompt

    def test_instructs_not_to_use_accusatory_terms(self) -> None:
        prompt = build_follow_up_prompt({})
        # The prompt instructs NOT to use these terms
        assert "不使用定罪性措辞" in prompt
        assert "保持中立" in prompt
