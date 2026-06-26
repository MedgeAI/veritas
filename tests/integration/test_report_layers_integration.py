"""Integration tests for report layer grouping (PRD2-T7).

Exercises the REAL ``classify_finding``, ``group_findings_by_layer``, and
``render_html`` functions from engine.static_audit._shared and engine.reporting.layers.

Tests cover:
- Finding classification into layers based on risk_level + category
- Layer grouping with mixed findings
- HTML rendering with layered findings
- VerificationReport model with layer fields
- LAYER_METADATA constants
"""

from __future__ import annotations

import pytest

from engine.reporting.layers import LAYER_METADATA, group_findings_by_layer
from engine.reporting.models import Finding, VerificationReport, report_from_dict
from engine.reporting.render_html import render_html
from engine.static_audit._shared import classify_finding


# ---------------------------------------------------------------------------
# classify_finding
# ---------------------------------------------------------------------------


class TestClassifyFinding:
    """Tests for the classify_finding pure function."""

    def test_high_risk_pair_forensics_goes_to_layer_1(self):
        finding = {
            "risk_level": "high",
            "category": "row_offset_scalar_multiple",
            "source_artifact": "source_data_pair_forensics.json",
        }
        assert classify_finding(finding) == "layer_1"

    def test_critical_risk_goes_to_layer_1(self):
        finding = {
            "risk_level": "critical",
            "category": "fixed_ratio",
            "source_artifact": "source_data_findings.json",
        }
        assert classify_finding(finding) == "layer_1"

    def test_duplicate_row_vector_always_layer_3(self):
        """DRV is always Layer 3 regardless of risk level."""
        for risk in ["critical", "high", "medium", "low", "info"]:
            finding = {
                "risk_level": risk,
                "category": "duplicate_row_vector",
                "source_artifact": "source_data_pair_forensics.json",
            }
            assert classify_finding(finding) == "layer_3", f"Expected layer_3 for risk={risk}"

    def test_medium_risk_goes_to_layer_2(self):
        finding = {
            "risk_level": "medium",
            "category": "paired_difference_too_narrow",
            "source_artifact": "source_data_pair_forensics.json",
        }
        assert classify_finding(finding) == "layer_2"

    def test_low_risk_goes_to_layer_3(self):
        finding = {
            "risk_level": "low",
            "category": "cross_sheet_duplicate",
            "source_artifact": "source_data_findings.json",
        }
        assert classify_finding(finding) == "layer_3"

    def test_info_risk_goes_to_layer_3(self):
        finding = {
            "risk_level": "info",
            "category": "numeric_pattern",
            "source_artifact": "numeric_forensics.json",
        }
        assert classify_finding(finding) == "layer_3"

    def test_high_risk_paperconan_goes_to_layer_2(self):
        """Per PRD section 5, Paperconan HIGH-risk goes to Layer 2, not Layer 1."""
        finding = {
            "risk_level": "high",
            "category": "paperfraud.fraud_detection",
            "source_artifact": "numeric_forensics.json",
        }
        assert classify_finding(finding) == "layer_2"

    def test_methodology_review_always_layer_3(self):
        """paperfraud.methodology_review is always Layer 3."""
        for risk in ["critical", "high", "medium"]:
            finding = {
                "risk_level": risk,
                "category": "paperfraud.methodology_review",
                "source_artifact": "paperfraud_rule_matches.json",
            }
            assert classify_finding(finding) == "layer_3", f"Expected layer_3 for risk={risk}"

    def test_missing_risk_level_defaults_to_medium(self):
        """Findings without risk_level should default to medium -> layer_2."""
        finding = {
            "category": "fixed_ratio",
            "source_artifact": "source_data_findings.json",
        }
        assert classify_finding(finding) == "layer_2"

    def test_trufor_high_risk_goes_to_layer_1(self):
        finding = {
            "risk_level": "high",
            "category": "forged_region_suspicious",
            "source_artifact": "visual_forensics.json",
        }
        assert classify_finding(finding) == "layer_1"

    def test_copy_move_confirmed_goes_to_layer_1(self):
        finding = {
            "risk_level": "high",
            "category": "copy_move_cross",
            "source_artifact": "visual_forensics.json",
        }
        assert classify_finding(finding) == "layer_1"


# ---------------------------------------------------------------------------
# group_findings_by_layer
# ---------------------------------------------------------------------------


class TestGroupFindingsByLayer:
    """Tests for the group_findings_by_layer function."""

    def test_empty_findings_returns_empty_layers(self):
        result = group_findings_by_layer([])
        assert result == {"layer_1": [], "layer_2": [], "layer_3": []}

    def test_findings_are_annotated_with_layer_field(self):
        findings = [
            {"finding_id": "f1", "risk_level": "high", "category": "fixed_ratio"},
            {"finding_id": "f2", "risk_level": "medium", "category": "paired_difference"},
            {"finding_id": "f3", "risk_level": "low", "category": "numeric_pattern"},
        ]
        result = group_findings_by_layer(findings)

        assert len(result["layer_1"]) == 1
        assert len(result["layer_2"]) == 1
        assert len(result["layer_3"]) == 1

        # Check _layer annotation
        assert result["layer_1"][0]["_layer"] == "layer_1"
        assert result["layer_2"][0]["_layer"] == "layer_2"
        assert result["layer_3"][0]["_layer"] == "layer_3"

    def test_original_findings_not_mutated(self):
        """Ensure the input list is not modified."""
        findings = [
            {"finding_id": "f1", "risk_level": "high", "category": "fixed_ratio"},
        ]
        original_copy = [dict(f) for f in findings]
        group_findings_by_layer(findings)

        assert findings == original_copy
        assert "_layer" not in findings[0]

    def test_mixed_findings_grouped_correctly(self):
        findings = [
            {"finding_id": "f1", "risk_level": "high", "category": "fixed_ratio"},
            {"finding_id": "f2", "risk_level": "high", "category": "duplicate_row_vector"},
            {"finding_id": "f3", "risk_level": "medium", "category": "cross_sheet"},
            {"finding_id": "f4", "risk_level": "high", "category": "paperfraud.fraud_detection"},
            {"finding_id": "f5", "risk_level": "low", "category": "numeric_pattern"},
        ]
        result = group_findings_by_layer(findings)

        # Layer 1: f1 (high, non-DRV, non-paperconan)
        assert len(result["layer_1"]) == 1
        assert result["layer_1"][0]["finding_id"] == "f1"

        # Layer 2: f3 (medium), f4 (high paperconan)
        assert len(result["layer_2"]) == 2
        layer_2_ids = {f["finding_id"] for f in result["layer_2"]}
        assert layer_2_ids == {"f3", "f4"}

        # Layer 3: f2 (DRV), f5 (low)
        assert len(result["layer_3"]) == 2
        layer_3_ids = {f["finding_id"] for f in result["layer_3"]}
        assert layer_3_ids == {"f2", "f5"}

    def test_invalid_findings_are_skipped(self):
        findings = [
            {"finding_id": "f1", "risk_level": "high", "category": "fixed_ratio"},
            None,
            "not a dict",
            42,
            {"finding_id": "f2", "risk_level": "medium", "category": "paired_difference"},
        ]
        result = group_findings_by_layer(findings)

        # Only valid dicts should be processed
        assert len(result["layer_1"]) == 1
        assert len(result["layer_2"]) == 1


# ---------------------------------------------------------------------------
# VerificationReport model
# ---------------------------------------------------------------------------


class TestVerificationReportModel:
    """Tests for VerificationReport model with layer fields."""

    def test_model_has_layer_fields(self):
        report = VerificationReport(
            report_id="test-001",
            generated_at="2026-06-26T00:00:00Z",
            project_name="Test Project",
            verification_level="full",
            overall_status="completed",
            role="pi",
            summary={"total_findings": 0, "critical": 0, "warning": 0, "claims_checked": 0},
            artifacts={},
            layer_1=[{"finding_id": "f1", "_layer": "layer_1"}],
            layer_2=[{"finding_id": "f2", "_layer": "layer_2"}],
            layer_3=[{"finding_id": "f3", "_layer": "layer_3"}],
        )

        assert report.layer_1 == [{"finding_id": "f1", "_layer": "layer_1"}]
        assert report.layer_2 == [{"finding_id": "f2", "_layer": "layer_2"}]
        assert report.layer_3 == [{"finding_id": "f3", "_layer": "layer_3"}]

    def test_to_dict_includes_layer_fields(self):
        report = VerificationReport(
            report_id="test-001",
            generated_at="2026-06-26T00:00:00Z",
            project_name="Test Project",
            verification_level="full",
            overall_status="completed",
            role="pi",
            summary={"total_findings": 0, "critical": 0, "warning": 0, "claims_checked": 0},
            artifacts={},
            layer_1=[{"finding_id": "f1"}],
            layer_2=[{"finding_id": "f2"}],
            layer_3=[{"finding_id": "f3"}],
        )

        result = report.to_dict()
        assert "layer_1" in result
        assert "layer_2" in result
        assert "layer_3" in result
        assert result["layer_1"] == [{"finding_id": "f1"}]
        assert result["layer_2"] == [{"finding_id": "f2"}]
        assert result["layer_3"] == [{"finding_id": "f3"}]

    def test_report_from_dict_loads_layer_fields(self):
        data = {
            "report_id": "test-001",
            "generated_at": "2026-06-26T00:00:00Z",
            "project_name": "Test Project",
            "verification_level": "full",
            "overall_status": "completed",
            "role": "pi",
            "summary": {"total_findings": 0, "critical": 0, "warning": 0, "claims_checked": 0},
            "artifacts": {},
            "layer_1": [{"finding_id": "f1"}],
            "layer_2": [{"finding_id": "f2"}],
            "layer_3": [{"finding_id": "f3"}],
        }

        report = report_from_dict(data)
        assert report.layer_1 == [{"finding_id": "f1"}]
        assert report.layer_2 == [{"finding_id": "f2"}]
        assert report.layer_3 == [{"finding_id": "f3"}]

    def test_layer_fields_default_to_empty_lists(self):
        report = VerificationReport(
            report_id="test-001",
            generated_at="2026-06-26T00:00:00Z",
            project_name="Test Project",
            verification_level="full",
            overall_status="completed",
            role="pi",
            summary={"total_findings": 0, "critical": 0, "warning": 0, "claims_checked": 0},
            artifacts={},
        )

        assert report.layer_1 == []
        assert report.layer_2 == []
        assert report.layer_3 == []


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


class TestHtmlRendering:
    """Tests for HTML rendering with layered findings."""

    def test_render_html_with_layers_contains_sections(self):
        report = VerificationReport(
            report_id="test-001",
            generated_at="2026-06-26T00:00:00Z",
            project_name="Test Project",
            verification_level="full",
            overall_status="completed",
            role="pi",
            summary={"total_findings": 3, "critical": 1, "warning": 1, "claims_checked": 0},
            artifacts={},
            layer_1=[{
                "id": "f1",
                "title": "High confidence finding",
                "severity": "critical",
                "category": "fixed_ratio",
                "source": "source_data_findings.json",
                "fact": "Test fact",
                "inference": "Test inference",
                "suggestion": "Test suggestion",
            }],
            layer_2=[{
                "id": "f2",
                "title": "Medium confidence finding",
                "severity": "warning",
                "category": "paired_difference",
                "source": "source_data_pair_forensics.json",
                "fact": "Test fact",
                "inference": "Test inference",
                "suggestion": "Test suggestion",
            }],
            layer_3=[{
                "id": "f3",
                "title": "Informational finding",
                "severity": "info",
                "category": "duplicate_row_vector",
                "source": "source_data_pair_forensics.json",
                "fact": "Test fact",
                "inference": "Test inference",
                "suggestion": "Test suggestion",
            }],
        )

        html = render_html(report)

        # Check that all three layer titles are present
        assert "高置信度发现" in html
        assert "需人工判断" in html
        assert "其他信号" in html

        # Check that findings are present
        assert "High confidence finding" in html
        assert "Medium confidence finding" in html
        assert "Informational finding" in html

        # Check layer counts (HTML uses single quotes for class attribute)
        assert "<span class='layer-count'>1</span>" in html

    def test_render_html_layer_3_is_collapsed(self):
        """Layer 3 should be wrapped in <details> (collapsed by default)."""
        report = VerificationReport(
            report_id="test-001",
            generated_at="2026-06-26T00:00:00Z",
            project_name="Test Project",
            verification_level="full",
            overall_status="completed",
            role="pi",
            summary={"total_findings": 1, "critical": 0, "warning": 0, "claims_checked": 0},
            artifacts={},
            layer_1=[],
            layer_2=[],
            layer_3=[{
                "id": "f1",
                "title": "Informational",
                "severity": "info",
                "category": "duplicate_row_vector",
                "source": "source_data_pair_forensics.json",
                "fact": "Test",
                "inference": "Test",
                "suggestion": "Test",
            }],
        )

        html = render_html(report)

        # Layer 3 should be in a <details> block
        assert "<details>" in html
        assert "其他信号" in html

    def test_render_html_without_layers_falls_back_to_findings(self):
        """When layer fields are empty, should fall back to rendering findings list."""
        report = VerificationReport(
            report_id="test-001",
            generated_at="2026-06-26T00:00:00Z",
            project_name="Test Project",
            verification_level="full",
            overall_status="completed",
            role="pi",
            summary={"total_findings": 1, "critical": 1, "warning": 0, "claims_checked": 0},
            artifacts={},
            findings=[
                Finding(
                    id="f1",
                    title="Test Finding",
                    severity="critical",
                    category="fixed_ratio",
                    status="open",
                    fact="Test fact",
                    inference="Test inference",
                    suggestion="Test suggestion",
                    source="test.json",
                )
            ],
        )

        html = render_html(report)

        # Should render the finding
        assert "Test Finding" in html
        # Should NOT have layer sections
        assert "高置信度发现" not in html


# ---------------------------------------------------------------------------
# LAYER_METADATA
# ---------------------------------------------------------------------------


class TestLayerMetadata:
    """Tests for LAYER_METADATA constants."""

    def test_all_three_layers_have_metadata(self):
        assert "layer_1" in LAYER_METADATA
        assert "layer_2" in LAYER_METADATA
        assert "layer_3" in LAYER_METADATA

    def test_layer_1_and_2_default_open(self):
        assert LAYER_METADATA["layer_1"]["default_open"] is True
        assert LAYER_METADATA["layer_2"]["default_open"] is True

    def test_layer_3_default_collapsed(self):
        assert LAYER_METADATA["layer_3"]["default_open"] is False

    def test_layer_titles_are_chinese(self):
        assert LAYER_METADATA["layer_1"]["title"] == "高置信度发现"
        assert LAYER_METADATA["layer_2"]["title"] == "需人工判断"
        assert LAYER_METADATA["layer_3"]["title"] == "其他信号"


# ---------------------------------------------------------------------------
# End-to-end: classify + group + render
# ---------------------------------------------------------------------------


class TestEndToEndLayering:
    """End-to-end: classify findings -> group by layer -> render HTML."""

    def test_classify_group_render_pipeline(self):
        """Real pipeline: classify_finding -> group_findings_by_layer -> render_html."""
        findings = [
            {"finding_id": "f1", "risk_level": "high", "category": "fixed_ratio",
             "source_artifact": "source_data_findings.json"},
            {"finding_id": "f2", "risk_level": "high", "category": "duplicate_row_vector",
             "source_artifact": "source_data_pair_forensics.json"},
            {"finding_id": "f3", "risk_level": "medium", "category": "cross_sheet_duplicate",
             "source_artifact": "source_data_findings.json"},
            {"finding_id": "f4", "risk_level": "high", "category": "paperfraud.fraud_detection",
             "source_artifact": "numeric_forensics.json"},
            {"finding_id": "f5", "risk_level": "low", "category": "numeric_pattern",
             "source_artifact": "numeric_forensics.json"},
        ]

        # Classify each finding
        for f in findings:
            layer = classify_finding(f)
            f["_layer"] = layer

        # Group by layer
        grouped = {"layer_1": [], "layer_2": [], "layer_3": []}
        for f in findings:
            grouped[f["_layer"]].append(f)

        # Verify grouping
        assert len(grouped["layer_1"]) == 1
        assert grouped["layer_1"][0]["finding_id"] == "f1"
        assert len(grouped["layer_2"]) == 2
        assert {f["finding_id"] for f in grouped["layer_2"]} == {"f3", "f4"}
        assert len(grouped["layer_3"]) == 2
        assert {f["finding_id"] for f in grouped["layer_3"]} == {"f2", "f5"}

        # Build report
        report = VerificationReport(
            report_id="test-001",
            generated_at="2026-06-26T00:00:00Z",
            project_name="Test Project",
            verification_level="full",
            overall_status="completed",
            role="pi",
            summary={"total_findings": 5, "critical": 0, "warning": 0, "claims_checked": 0},
            artifacts={},
            layer_1=[{"id": f["finding_id"], "title": f"Finding {f['finding_id']}",
                      "severity": f["risk_level"], "category": f["category"],
                      "source": f["source_artifact"], "fact": "f", "inference": "i",
                      "suggestion": "s"} for f in grouped["layer_1"]],
            layer_2=[{"id": f["finding_id"], "title": f"Finding {f['finding_id']}",
                      "severity": f["risk_level"], "category": f["category"],
                      "source": f["source_artifact"], "fact": "f", "inference": "i",
                      "suggestion": "s"} for f in grouped["layer_2"]],
            layer_3=[{"id": f["finding_id"], "title": f"Finding {f['finding_id']}",
                      "severity": f["risk_level"], "category": f["category"],
                      "source": f["source_artifact"], "fact": "f", "inference": "i",
                      "suggestion": "s"} for f in grouped["layer_3"]],
        )

        # Render HTML
        html = render_html(report)

        # Verify all sections present
        assert "高置信度发现" in html
        assert "需人工判断" in html
        assert "其他信号" in html

        # Verify findings are rendered
        assert "Finding f1" in html
        assert "Finding f3" in html
        assert "Finding f5" in html
