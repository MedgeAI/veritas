"""Unit tests for certainty enrichment module."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.static_audit.models import (
    Finding,
    StaticAuditBundle,
)
from engine.static_audit.certainty_enrichment import (
    enrich_certainty_layers,
    save_certainty_data,
)


@pytest.fixture
def sample_consistency_finding() -> Finding:
    """Create a sample consistency finding for testing."""
    return Finding(
        finding_id="F-001",
        category="duplicate_column",
        risk_level="high",
        summary="发现重复列：results/baseline_af2.csv 第 2 行和第 5 行数据完全相同",
        issue_category="consistency",
        evidence_source="file",
        evidence_refs=["E-001", "E-002"],
        claim_refs=["C-001"],
        benign_explanations=["可能是数据录入时的重复粘贴"],
        pressure_test_result="",
        manual_review_note="",
        metadata={"row_numbers": [2, 5], "file": "results/baseline_af2.csv"},
    )


@pytest.fixture
def sample_methodology_finding() -> Finding:
    """Create a sample methodology finding for testing."""
    return Finding(
        finding_id="F-002",
        category="missing_methodology",
        risk_level="medium",
        summary="论文声称使用了双盲实验，但方法部分未描述随机化过程",
        issue_category="completeness",
        evidence_source="text_match",
        evidence_refs=["E-003"],
        claim_refs=["C-002"],
        benign_explanations=["可能在补充材料中描述"],
        pressure_test_result="",
        manual_review_note="",
        metadata={"section": "Methods"},
    )


@pytest.fixture
def sample_bundle(
    sample_consistency_finding: Finding,
    sample_methodology_finding: Finding,
) -> StaticAuditBundle:
    """Create a sample bundle with multiple findings."""
    return StaticAuditBundle(
        case_id="test-case-001",
        inputs={"paper_dir": "/tmp/paper", "source_data_dir": "/tmp/data"},
        findings=[sample_consistency_finding, sample_methodology_finding],
    )


def test_enrich_certainty_layers_generates_all_three_layers(
    sample_bundle: StaticAuditBundle,
) -> None:
    """Test that all three layers (fact, inference, suggestion) are generated."""
    result = enrich_certainty_layers(sample_bundle)

    assert len(result) == 2
    for item in result:
        assert "finding_id" in item
        assert "fact" in item
        assert "inference" in item
        assert "suggestion" in item
        assert item["fact"]
        assert item["inference"]
        assert item["suggestion"]


def test_enrich_certainty_layers_fact_includes_evidence(
    sample_bundle: StaticAuditBundle,
) -> None:
    """Test that FACT layer includes evidence references."""
    result = enrich_certainty_layers(sample_bundle)

    consistency_item = next(item for item in result if item["finding_id"] == "F-001")
    assert "E-001" in consistency_item["fact"] or "C-001" in consistency_item["fact"]
    assert "重复列" in consistency_item["fact"]


def test_enrich_certainty_layers_inference_includes_disclaimer(
    sample_bundle: StaticAuditBundle,
) -> None:
    """Test that INFERENCE layer includes disclaimer."""
    result = enrich_certainty_layers(sample_bundle)

    for item in result:
        assert "此为推断，不构成认证结论" in item["inference"]


def test_enrich_certainty_layers_inference_uses_benign_explanations(
    sample_bundle: StaticAuditBundle,
) -> None:
    """Test that INFERENCE layer uses benign_explanations from finding."""
    result = enrich_certainty_layers(sample_bundle)

    consistency_item = next(item for item in result if item["finding_id"] == "F-001")
    assert "重复粘贴" in consistency_item["inference"]


def test_enrich_certainty_layers_suggestion_is_actionable(
    sample_bundle: StaticAuditBundle,
) -> None:
    """Test that SUGGESTION layer provides actionable recommendations."""
    result = enrich_certainty_layers(sample_bundle)

    consistency_item = next(item for item in result if item["finding_id"] == "F-001")
    assert "核查" in consistency_item["suggestion"] or "确认" in consistency_item["suggestion"]


def test_enrich_certainty_layers_empty_bundle() -> None:
    """Test that empty bundle returns empty list."""
    empty_bundle = StaticAuditBundle(
        case_id="empty-case",
        inputs={},
        findings=[],
    )
    result = enrich_certainty_layers(empty_bundle)
    assert result == []


def test_save_certainty_data_creates_file(
    sample_bundle: StaticAuditBundle,
    tmp_path: Path,
) -> None:
    """Test that save_certainty_data creates JSON file."""
    path = save_certainty_data(sample_bundle, tmp_path)

    assert path.exists()
    assert path.name == "certainty_data.json"

    import json
    data = json.loads(path.read_text())
    assert isinstance(data, list)
    assert len(data) == 2


def test_enrich_certainty_layers_category_specific_suggestions(
    sample_consistency_finding: Finding,
    sample_methodology_finding: Finding,
) -> None:
    """Test that suggestions are tailored to finding categories."""
    bundle = StaticAuditBundle(
        case_id="test-case",
        inputs={},
        findings=[sample_consistency_finding, sample_methodology_finding],
    )
    result = enrich_certainty_layers(bundle)

    consistency_item = next(item for item in result if item["finding_id"] == "F-001")
    methodology_item = next(item for item in result if item["finding_id"] == "F-002")

    # Consistency findings should suggest checking data
    assert "核查" in consistency_item["suggestion"] or "确认" in consistency_item["suggestion"]

    # Methodology findings should suggest supplementing info
    assert "补充" in methodology_item["suggestion"] or "说明" in methodology_item["suggestion"]


def test_enrich_certainty_layers_risk_level_affects_suggestion(
    sample_consistency_finding: Finding,
) -> None:
    """Test that high-risk findings get priority suggestions."""
    high_risk = sample_consistency_finding
    high_risk.risk_level = "critical"

    bundle = StaticAuditBundle(
        case_id="test-case",
        inputs={},
        findings=[high_risk],
    )
    result = enrich_certainty_layers(bundle)

    assert len(result) == 1
    assert "优先" in result[0]["suggestion"] or "高风险" in result[0]["suggestion"]
