"""Tests for version tracking in verify_store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.static_audit import verify_store


@pytest.fixture
def verify_dir(tmp_path: Path) -> Path:
    """Create a temporary verify directory."""
    return tmp_path / "verifications"


def test_save_verification_with_version(verify_dir: Path) -> None:
    """Test saving a verification summary with version number."""
    grade_data = {
        "grade": "A",
        "label": "优秀",
        "dimensions": [],
        "summary": "测试摘要",
        "total_findings": 0,
    }

    path = verify_store.save_verification_summary(
        case_id="test-case-1",
        report_id="VRT-202606-ABC123",
        paper_title="测试论文",
        grade_data=grade_data,
        report_version=1,
        verify_dir=verify_dir,
    )

    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["report_id"] == "VRT-202606-ABC123"
    assert data["case_id"] == "test-case-1"
    assert data["report_version"] == 1
    assert data["version_history"] == []  # First version, no history


def test_version_history_accumulation(verify_dir: Path) -> None:
    """Test that version history accumulates across multiple saves."""
    grade_data = {
        "grade": "B",
        "label": "良好",
        "dimensions": [],
        "summary": "测试",
        "total_findings": 2,
    }

    # Save v1
    verify_store.save_verification_summary(
        case_id="test-case-2",
        report_id="VRT-202606-V1",
        paper_title="测试论文",
        grade_data=grade_data,
        report_version=1,
        verify_dir=verify_dir,
    )

    # Save v2
    path_v2 = verify_store.save_verification_summary(
        case_id="test-case-2",
        report_id="VRT-202606-V2",
        paper_title="测试论文（修订版）",
        grade_data={**grade_data, "grade": "A"},
        report_version=2,
        verify_dir=verify_dir,
    )

    data_v2 = json.loads(path_v2.read_text(encoding="utf-8"))
    assert data_v2["report_version"] == 2
    assert len(data_v2["version_history"]) == 1
    assert data_v2["version_history"][0]["version"] == 1
    assert data_v2["version_history"][0]["report_id"] == "VRT-202606-V1"

    # Save v3
    path_v3 = verify_store.save_verification_summary(
        case_id="test-case-2",
        report_id="VRT-202606-V3",
        paper_title="测试论文（最终版）",
        grade_data={**grade_data, "grade": "A"},
        report_version=3,
        verify_dir=verify_dir,
    )

    data_v3 = json.loads(path_v3.read_text(encoding="utf-8"))
    assert data_v3["report_version"] == 3
    assert len(data_v3["version_history"]) == 2
    assert data_v3["version_history"][0]["version"] == 1
    assert data_v3["version_history"][1]["version"] == 2


def test_list_version_history(verify_dir: Path) -> None:
    """Test listing version history for a case."""
    grade_data = {
        "grade": "C",
        "label": "一般",
        "dimensions": [],
        "summary": "测试",
        "total_findings": 5,
    }

    # Save multiple versions
    verify_store.save_verification_summary(
        case_id="test-case-3",
        report_id="VRT-202606-H1",
        paper_title="测试论文",
        grade_data=grade_data,
        report_version=1,
        verify_dir=verify_dir,
    )

    verify_store.save_verification_summary(
        case_id="test-case-3",
        report_id="VRT-202606-H2",
        paper_title="测试论文",
        grade_data={**grade_data, "grade": "B"},
        report_version=2,
        verify_dir=verify_dir,
    )

    verify_store.save_verification_summary(
        case_id="test-case-3",
        report_id="VRT-202606-H3",
        paper_title="测试论文",
        grade_data={**grade_data, "grade": "A"},
        report_version=3,
        verify_dir=verify_dir,
    )

    history = verify_store.list_version_history("test-case-3", verify_dir=verify_dir)

    assert len(history) == 3
    assert history[0]["version"] == 1
    assert history[0]["report_id"] == "VRT-202606-H1"
    assert history[1]["version"] == 2
    assert history[1]["report_id"] == "VRT-202606-H2"
    assert history[2]["version"] == 3
    assert history[2]["report_id"] == "VRT-202606-H3"


def test_list_version_history_empty(verify_dir: Path) -> None:
    """Test listing version history for non-existent case."""
    history = verify_store.list_version_history("non-existent", verify_dir=verify_dir)
    assert history == []


def test_version_history_different_cases(verify_dir: Path) -> None:
    """Test that version history is isolated per case."""
    grade_data = {
        "grade": "A",
        "label": "优秀",
        "dimensions": [],
        "summary": "测试",
        "total_findings": 0,
    }

    # Save for case A
    verify_store.save_verification_summary(
        case_id="case-A",
        report_id="VRT-202606-A1",
        paper_title="论文A",
        grade_data=grade_data,
        report_version=1,
        verify_dir=verify_dir,
    )

    # Save for case B
    verify_store.save_verification_summary(
        case_id="case-B",
        report_id="VRT-202606-B1",
        paper_title="论文B",
        grade_data=grade_data,
        report_version=1,
        verify_dir=verify_dir,
    )

    history_a = verify_store.list_version_history("case-A", verify_dir=verify_dir)
    history_b = verify_store.list_version_history("case-B", verify_dir=verify_dir)

    assert len(history_a) == 1
    assert len(history_b) == 1
    assert history_a[0]["report_id"] == "VRT-202606-A1"
    assert history_b[0]["report_id"] == "VRT-202606-B1"
