"""Tests for html_report appendix (_appendix)."""

from __future__ import annotations

from pathlib import Path

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


