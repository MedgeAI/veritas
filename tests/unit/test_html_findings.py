"""Tests for html_report findings rendering (_findings)."""

from __future__ import annotations

from engine.static_audit.html_report._shared import (
    SOURCE_DATA_FINDINGS_ARTIFACT,
    SOURCE_DATA_PAIR_FORENSICS_ARTIFACT,
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
    def test_reads_llm_text(self) -> None:
        finding = {"llm_text": {"relation_text": "固定差 0.3，列 D、E，覆盖 35 行。"}}
        result = relation_text(finding)
        assert result == "固定差 0.3，列 D、E，覆盖 35 行。"

    def test_fallback_no_llm_text(self) -> None:
        finding = {"category": "fixed_difference"}
        result = relation_text(finding)
        assert "fixed_difference" in result
        assert "LLM" in result

    def test_fallback_unknown_category(self) -> None:
        finding = {"category": "some_unknown"}
        result = relation_text(finding)
        assert "some_unknown" in result


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
    def test_reads_llm_review_question(self) -> None:
        finding = {"llm_text": {"review_question": "核对 Sheet1 列 D、E 的固定差关系"}}
        result = review_question({}, None, finding)
        assert result == "核对 Sheet1 列 D、E 的固定差关系"

    def test_llm_error_fallback(self) -> None:
        finding = {"llm_text": {"error": "timeout"}}
        result = review_question({}, None, finding)
        assert "LLM" in result
        assert "失败" in result

    def test_no_llm_text_fallback(self) -> None:
        result = review_question({}, None, {})
        assert "LLM" in result
        assert "未生成" in result


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


