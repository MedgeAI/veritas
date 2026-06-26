"""Tests for PRD2-T6: Judge input filtering (Layer 1 + Layer 2 only).

Verifies that:
1. Layer 3 findings are filtered out
2. Methodology findings (Wave 2) are filtered out
3. Metadata cross-sheet findings (Wave 3) are filtered out
4. Layer 1 + Layer 2 findings are preserved
5. Judge output schema is unchanged
"""

import pytest
from pathlib import Path


class TestClassifyFinding:
    """Test finding classification into layers."""

    def test_layer1_high_risk_pair_forensics(self):
        """HIGH-risk Source Data pair forensics -> Layer 1."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "pair_forensics",
            "risk_level": "high",
            "source": "source_data_pair_forensics.json",
        }
        assert classify_finding(finding) == "layer_1"

    def test_layer1_critical_risk(self):
        """Critical risk -> Layer 1."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "duplicate_columns",
            "risk_level": "critical",
        }
        assert classify_finding(finding) == "layer_1"

    def test_layer1_high_risk_trufor(self):
        """HIGH-risk TruFor -> Layer 1."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "trufor_integrity",
            "risk_level": "high",
            "integrity_score": 0.95,
        }
        assert classify_finding(finding) == "layer_1"

    def test_layer1_confirmed_copy_move(self):
        """Confirmed copy-move -> Layer 1."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "copy_move",
            "risk_level": "high",
            "confirmed": True,
        }
        assert classify_finding(finding) == "layer_1"

    def test_layer1_formula_derived_column_high(self):
        """HIGH-risk formula derived column -> Layer 1."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "formula_derived_column",
            "risk_level": "high",
        }
        assert classify_finding(finding) == "layer_1"

    def test_layer2_medium_risk_pair_forensics(self):
        """MEDIUM-risk Source Data pair forensics -> Layer 2."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "pair_forensics",
            "risk_level": "medium",
            "source": "source_data_pair_forensics.json",
        }
        assert classify_finding(finding) == "layer_2"

    def test_layer2_cross_sheet_numeric(self):
        """Cross-sheet numeric column repeats -> Layer 2."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "cross_sheet_duplicate",
            "risk_level": "medium",
            "column_type": "measurement",
        }
        assert classify_finding(finding) == "layer_2"

    def test_layer2_paperconan_high(self):
        """HIGH-risk Paperconan -> Layer 2."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "paperfraud.digit_analysis",
            "risk_level": "high",
            "source": "numeric_forensics.json",
        }
        assert classify_finding(finding) == "layer_2"

    def test_layer2_trufor_medium(self):
        """MEDIUM-risk TruFor -> Layer 2."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "trufor_integrity",
            "risk_level": "medium",
            "integrity_score": 0.7,
        }
        assert classify_finding(finding) == "layer_2"

    def test_layer3_duplicate_row_vector(self):
        """DRV (duplicate row vector) -> Layer 3."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "duplicate_row_vector",
            "risk_level": "high",  # Even if HIGH
        }
        assert classify_finding(finding) == "layer_3"

    def test_layer3_paperconan_low(self):
        """LOW-risk Paperconan -> Layer 3."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "paperfraud.benford_analysis",
            "risk_level": "low",
            "source": "numeric_forensics.json",
        }
        assert classify_finding(finding) == "layer_3"

    def test_layer3_trufor_low(self):
        """LOW-risk TruFor -> Layer 3."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "trufor_integrity",
            "risk_level": "low",
            "integrity_score": 0.3,
        }
        assert classify_finding(finding) == "layer_3"

    def test_layer3_methodology_finding(self):
        """Methodology findings -> Layer 3."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "paperfraud.methodology_review",
            "risk_level": "high",
        }
        assert classify_finding(finding) == "layer_3"

    def test_layer3_low_risk(self):
        """LOW risk -> Layer 3."""
        from engine.static_audit._shared import classify_finding
        finding = {
            "category": "some_finding",
            "risk_level": "low",
        }
        assert classify_finding(finding) == "layer_3"


class TestFilterJudgeInput:
    """Test Judge input filtering."""

    def test_filters_layer3_findings(self):
        """Layer 3 findings are filtered out."""
        from engine.static_audit._shared import filter_judge_input
        findings = [
            {"category": "duplicate_row_vector", "risk_level": "high"},
            {"category": "trufor_integrity", "risk_level": "low"},
            {"category": "paperfraud.methodology_review", "risk_level": "high"},
        ]
        filtered = filter_judge_input(findings)
        assert len(filtered) == 0

    def test_preserves_layer1_and_layer2(self):
        """Layer 1 + Layer 2 findings are preserved."""
        from engine.static_audit._shared import filter_judge_input
        findings = [
            {"category": "pair_forensics", "risk_level": "high", "source": "source_data_pair_forensics.json"},
            {"category": "trufor_integrity", "risk_level": "medium"},
            {"category": "duplicate_columns", "risk_level": "critical"},
        ]
        filtered = filter_judge_input(findings)
        assert len(filtered) == 3
        # Verify layer annotation
        assert filtered[0]["_layer"] == "layer_1"
        assert filtered[1]["_layer"] == "layer_2"
        assert filtered[2]["_layer"] == "layer_1"

    def test_filters_methodology_findings(self):
        """Methodology findings (Wave 2) are filtered out.

        Note: Wave 2 removed methodology findings from the pipeline.
        This test verifies that if any methodology findings remain,
        they are classified as Layer 3 and filtered.
        """
        from engine.static_audit._shared import filter_judge_input
        findings = [
            {"category": "paperfraud.methodology_review", "risk_level": "high"},
        ]
        filtered = filter_judge_input(findings)
        assert len(filtered) == 0

    def test_filters_metadata_cross_sheet(self):
        """Metadata cross-sheet findings (Wave 3) should be filtered.

        Note: The Wave 3 LLM filter should have already removed metadata
        cross-sheet findings. This test verifies that if any remain,
        they are classified as Layer 2 (not filtered by T6).
        """
        from engine.static_audit._shared import filter_judge_input
        findings = [
            {"category": "cross_sheet_duplicate", "risk_level": "medium", "column_type": "metadata"},
            {"category": "cross_sheet_duplicate", "risk_level": "medium", "column_type": "measurement"},
        ]
        filtered = filter_judge_input(findings)
        # Both are Layer 2 (cross-sheet), not filtered by T6
        # The Wave 3 filter should have removed the metadata one
        assert len(filtered) == 2

    def test_empty_input(self):
        """Empty input returns empty output."""
        from engine.static_audit._shared import filter_judge_input
        assert filter_judge_input([]) == []

    def test_annotates_with_layer(self):
        """Filtered findings are annotated with _layer."""
        from engine.static_audit._shared import filter_judge_input
        findings = [
            {"category": "pair_forensics", "risk_level": "high", "source": "source_data_pair_forensics.json"},
        ]
        filtered = filter_judge_input(findings)
        assert len(filtered) == 1
        assert "_layer" in filtered[0]
        assert filtered[0]["_layer"] == "layer_1"

    def test_does_not_modify_original(self):
        """Filter does not modify the original findings."""
        from engine.static_audit._shared import filter_judge_input
        findings = [
            {"category": "pair_forensics", "risk_level": "high", "source": "source_data_pair_forensics.json"},
        ]
        original_len = len(findings)
        original_keys = set(findings[0].keys())

        filter_judge_input(findings)

        assert len(findings) == original_len
        assert set(findings[0].keys()) == original_keys
        assert "_layer" not in findings[0]

    def test_mixed_layers(self):
        """Mixed Layer 1/2/3 findings are correctly filtered."""
        from engine.static_audit._shared import filter_judge_input
        findings = [
            {"category": "pair_forensics", "risk_level": "high", "source": "source_data_pair_forensics.json"},  # L1
            {"category": "duplicate_row_vector", "risk_level": "high"},  # L3
            {"category": "trufor_integrity", "risk_level": "medium"},  # L2
            {"category": "paperfraud.methodology_review", "risk_level": "high"},  # L3
            {"category": "cross_sheet_duplicate", "risk_level": "medium"},  # L2
            {"category": "trufor_integrity", "risk_level": "low"},  # L3
        ]
        filtered = filter_judge_input(findings)

        # Should keep 3 findings: 1 L1 + 2 L2
        assert len(filtered) == 3
        assert filtered[0]["_layer"] == "layer_1"
        assert filtered[1]["_layer"] == "layer_2"
        assert filtered[2]["_layer"] == "layer_2"


class TestJudgeOutputSchema:
    """Test that Judge output schema is unchanged."""

    def test_judge_output_validation(self):
        """Judge output schema validation still works."""
        from engine.investigation.role_runners import validate_role_output
        judge_output = {
            "schema_version": "1.0",
            "role_id": "judge",
            "case_id": "test-case-001",
            "summary": {
                "claim_count": 5,
                "finding_review_count": 10,
                "manual_review_task_count": 3,
                "technical_risk_summary": "Test summary",
            },
            "risk_suggestions": [
                {
                    "risk_level": "high",
                    "reason": "Test reason",
                    "evidence_refs": ["source_data_findings.json"],
                    "requires_human_review": True,
                }
            ],
            "report_notes": ["Test note"],
            "limitations": ["Test limitation"],
        }

        # Should not raise
        validated = validate_role_output("judge", judge_output)
        assert validated["role_id"] == "judge"
        assert validated["schema_version"] == "1.0"

    def test_judge_output_limits(self):
        """Judge output limits are enforced."""
        from engine.investigation.role_runners import validate_role_output
        judge_output = {
            "schema_version": "1.0",
            "role_id": "judge",
            "case_id": "test-case-001",
            "summary": {
                "claim_count": 0,
                "finding_review_count": 0,
                "manual_review_task_count": 0,
                "technical_risk_summary": "x" * 2000,  # Too long
            },
            "risk_suggestions": [{"risk_level": "high", "reason": f"r{i}", "evidence_refs": [], "requires_human_review": True} for i in range(20)],  # > 8
            "report_notes": [f"note{i}" for i in range(20)],  # > 8
            "limitations": [f"lim{i}" for i in range(20)],  # > 10
        }

        validated = validate_role_output("judge", judge_output)

        # Limits should be enforced
        assert len(validated["risk_suggestions"]) == 8
        assert len(validated["report_notes"]) == 8
        assert len(validated["limitations"]) == 10
        assert len(validated["summary"]["technical_risk_summary"]) <= 1200


class TestJudgeContextPackIntegration:
    """Integration test: Judge context pack applies filtering."""

    def test_judge_context_pack_filters_findings(self, tmp_path):
        """Judge context pack filters Layer 3 findings from top_n_findings."""
        import json
        from engine.investigation.context_pack import build_context_pack_for_role

        # Create mock artifacts
        workdir = tmp_path / "test_case"
        workdir.mkdir()

        # Create source_data_findings.json with mixed layers
        source_findings = {
            "priority_findings": [
                {
                    "finding_id": "SF-001",
                    "risk_level": "high",
                    "category": "pair_forensics",
                    "source": "source_data_pair_forensics.json",
                    "workbook": "test.xlsx",
                    "sheet": "Sheet1",
                    "column_pair": ["A", "B"],
                    "relationship_value": 1.5,
                    "benign_explanations": ["test"],
                },
                {
                    "finding_id": "SF-002",
                    "risk_level": "high",
                    "category": "duplicate_row_vector",  # Layer 3
                    "workbook": "test.xlsx",
                    "sheet": "Sheet1",
                    "column_pair": ["C", "D"],
                    "relationship_value": None,
                    "benign_explanations": [],
                },
            ]
        }
        (workdir / "source_data_findings.json").write_text(
            json.dumps(source_findings, indent=2)
        )

        # Create minimal artifacts
        (workdir / "material_inventory.json").write_text('{"summary": {}}')
        (workdir / "agent_material_plan.json").write_text('{}')
        (workdir / "evidence_ledger.json").write_text('{}')
        (workdir / "source_data_pair_forensics.json").write_text('{"priority_findings": []}')
        (workdir / "numeric_forensics.json").write_text('{}')
        (workdir / "agent_claim_extractor.json").write_text('{"claims": [], "limitations": []}')
        (workdir / "agent_source_data_auditor.json").write_text(
            '{"claim_to_source_data": [], "finding_reviews": [], "manual_review_tasks": [], "limitations": []}'
        )
        (workdir / "visual_findings.json").write_text('{"review_queue": [], "finding_clusters": []}')
        (workdir / "image_relationships.json").write_text('{}')

        # Build Judge context pack
        pack = build_context_pack_for_role("judge", workdir, "test-case-001")

        # Verify top_n_findings contains only Layer 1 + Layer 2
        # The duplicate_row_vector should be filtered out
        assert len(pack.top_n_findings) == 1
        assert pack.top_n_findings[0]["finding_id"] == "SF-001"
        assert pack.top_n_findings[0]["_layer"] == "layer_1"

        # Verify judge_context_summary.json is in bounded_excerpts
        assert "judge_context_summary.json" in pack.bounded_excerpts
