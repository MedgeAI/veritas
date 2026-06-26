"""Tests for html_report evidence clusters (_clusters)."""

from __future__ import annotations

from engine.static_audit.html_report._clusters import (
    build_evidence_clusters,
    brief_list,
    claims_for_finding_ids,
    cluster_headline,
    evidence_cluster_cards,
    finding_signal,
    tasks_for_finding_ids,
)

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


