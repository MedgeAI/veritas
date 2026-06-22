"""Tests for engine.static_audit.html_report._clusters, _manual_tasks, _source_data, _appendix."""

from __future__ import annotations

from pathlib import Path

from engine.static_audit.html_report._clusters import (
    build_evidence_clusters,
    brief_list,
    claims_for_finding_ids,
    cluster_headline,
    evidence_cluster_cards,
    finding_signal,
    tasks_for_finding_ids,
)
from engine.static_audit.html_report._manual_tasks import (
    display_priority_for_manual_task,
    display_priority_for_pair_task,
    display_risk_level_for_judge_risk,
    is_context_only_manual_task,
    manual_task_focus_score,
    manual_task_text,
    manual_tasks_table,
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
