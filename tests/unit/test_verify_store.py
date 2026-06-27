"""Tests for public verification store."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from engine.static_audit.report_id import generate_report_id, validate_report_id
from engine.static_audit.verify_store import (
    load_verification_summary,
    save_verification_summary,
)


class TestReportIdGeneration:
    """Test report ID generation and validation."""

    def test_generate_report_id_format(self):
        """Generated ID should match VRT-YYYYMM-XXXXXX pattern."""
        report_id = generate_report_id()
        assert report_id.startswith("VRT-")
        parts = report_id.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 6  # YYYYMM
        assert len(parts[2]) == 6  # hex chars

    def test_validate_report_id_valid(self):
        """Valid report IDs should pass validation."""
        assert validate_report_id("VRT-202606-A3F9B2")
        assert validate_report_id("VRT-202501-FFFFFF")
        assert validate_report_id("VRT-202412-000000")

    def test_validate_report_id_invalid_format(self):
        """Invalid formats should fail validation."""
        assert not validate_report_id("VRT-2026-A3F9B2")  # wrong date length
        assert not validate_report_id("VRT-202606-A3F9B")  # too short
        assert not validate_report_id("VRT-202606-A3F9B2C")  # too long
        assert not validate_report_id("INVALID-202606-A3F9B2")  # wrong prefix
        assert not validate_report_id("VRT-202606-GGGGGG")  # non-hex chars
        assert not validate_report_id("")
        assert not validate_report_id("VRT---")


class TestVerificationStore:
    """Test verification store save/load roundtrip."""

    def test_save_load_roundtrip(self, tmp_path):
        """Save and load should return the same data."""
        report_id = "VRT-202606-A3F9B2"
        case_id = "test-case-001"
        paper_title = "Test Paper Title"

        grade_data = {
            "grade": "A",
            "label": "完全通过",
            "summary": "审计完成，未发现风险问题",
            "total_findings": 0,
            "dimensions": [
                {
                    "name": "reproducibility",
                    "label": "可复现性",
                    "status": "pass",
                    "detail": "所有关键流水线步骤成功执行",
                }
            ],
        }

        # Save
        save_path = save_verification_summary(
            case_id=case_id,
            report_id=report_id,
            paper_title=paper_title,
            grade_data=grade_data,
            verify_dir=tmp_path,
        )

        # Verify file was created
        assert save_path.exists()
        assert save_path.name == f"{report_id}.json"

        # Load and verify
        loaded = load_verification_summary(report_id, verify_dir=tmp_path)
        assert loaded is not None
        assert loaded["report_id"] == report_id
        assert loaded["case_id"] == case_id
        assert loaded["paper_title"] == paper_title
        assert loaded["grade"] == "A"
        assert loaded["grade_label"] == "完全通过"
        assert loaded["total_findings"] == 0
        assert len(loaded["dimensions"]) == 1
        assert loaded["dimensions"][0]["name"] == "reproducibility"

    def test_load_nonexistent_returns_none(self, tmp_path):
        """Loading a non-existent report ID should return None."""
        result = load_verification_summary("VRT-202606-DEADBEEF", verify_dir=tmp_path)
        assert result is None

    def test_save_creates_directory(self, tmp_path):
        """Save should create the verification directory if it doesn't exist."""
        verify_dir = tmp_path / "nonexistent" / "verifications"
        assert not verify_dir.exists()

        report_id = "VRT-202606-A1B2C3"
        save_verification_summary(
            case_id="test",
            report_id=report_id,
            paper_title="Test",
            grade_data={"grade": "B", "label": "有条件通过"},
            verify_dir=verify_dir,
        )

        assert verify_dir.exists()
        assert (verify_dir / f"{report_id}.json").exists()

    def test_save_handles_dataclass_dimensions(self, tmp_path):
        """Save should handle DimensionScore dataclass objects."""
        from dataclasses import dataclass

        @dataclass
        class MockDimension:
            name: str
            label: str
            status: str
            detail: str

        report_id = "VRT-202606-AABBCC"
        grade_data = {
            "grade": "C",
            "label": "待修订",
            "dimensions": [
                MockDimension("reproducibility", "可复现性", "warning", "部分步骤失败")
            ],
        }

        save_verification_summary(
            case_id="test",
            report_id=report_id,
            paper_title="Test",
            grade_data=grade_data,
            verify_dir=tmp_path,
        )

        # Load and verify the dataclass was serialized
        loaded = load_verification_summary(report_id, verify_dir=tmp_path)
        assert loaded is not None
        assert len(loaded["dimensions"]) == 1
        assert loaded["dimensions"][0]["name"] == "reproducibility"
        assert loaded["dimensions"][0]["status"] == "warning"
