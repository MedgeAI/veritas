"""Tests for html_report source data display (_source_data)."""

from __future__ import annotations

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


