"""Tests for the /api/verify public verification endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.static_audit.verify_store import save_verification_summary
from web.backend.veritas_web.routers.verify import router


@pytest.fixture()
def verify_dir(tmp_path: Path, monkeypatch):
    """Set up a temporary verification directory."""
    directory = tmp_path / "verifications"
    directory.mkdir()
    monkeypatch.setenv("VERITAS_VERIFY_DIR", str(directory))
    return directory


class TestVerifyEndpoints:
    """Test verification store operations used by the API."""

    def test_save_and_load_verification(self, verify_dir):
        """Test saving and loading a verification summary."""
        report_id = "VRT-202606-A1B2C3"
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
        save_verification_summary(
            case_id=case_id,
            report_id=report_id,
            paper_title=paper_title,
            grade_data=grade_data,
            verify_dir=verify_dir,
        )

        # Verify file was created
        verify_file = verify_dir / f"{report_id}.json"
        assert verify_file.exists()

        # Load and verify content
        with open(verify_file) as f:
            data = json.load(f)

        assert data["report_id"] == report_id
        assert data["case_id"] == case_id
        assert data["paper_title"] == paper_title
        assert data["grade"] == "A"
        assert data["grade_label"] == "完全通过"
        assert len(data["dimensions"]) == 1

    def test_verify_nonexistent_returns_none(self, verify_dir):
        """Test that loading non-existent verification returns None."""
        from engine.static_audit.verify_store import load_verification_summary

        result = load_verification_summary(
            "VRT-202606-DEADBEEF", verify_dir=verify_dir
        )
        assert result is None

    def test_verify_invalid_format(self):
        """Test that invalid report ID format is rejected."""
        from engine.static_audit.report_id import validate_report_id

        assert not validate_report_id("INVALID-ID")
        assert not validate_report_id("VRT-202606-GGGGGG")  # non-hex
        assert not validate_report_id("VRT-2026-A1B2C3")  # wrong format

    def test_verify_valid_format(self):
        """Test that valid report ID format is accepted."""
        from engine.static_audit.report_id import validate_report_id

        assert validate_report_id("VRT-202606-A1B2C3")
        assert validate_report_id("VRT-202501-FFFFFF")
        assert validate_report_id("VRT-202412-000000")

    def test_router_endpoints_exist(self):
        """Test that router has the expected endpoints."""
        routes = [route.path for route in router.routes]
        assert "/api/verify/{report_id}" in routes
        assert "/api/verify" in routes  # query endpoint

    def test_router_has_no_auth_requirement(self):
        """Test that verify router doesn't require authentication."""
        # The router should be accessible without auth dependencies
        for route in router.routes:
            if hasattr(route, "dependencies"):
                assert len(route.dependencies) == 0, f"Route {route.path} has auth dependencies"
