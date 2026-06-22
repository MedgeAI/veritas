"""Tests for engine.static_audit.pipeline module — material planning and orchestration helpers."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch, MagicMock

from engine.static_audit.pipeline import (
    material_plan_from_inventory,
    optional_lanes_from_material_plan,
    resolve_selected_source_root,
    selected_xlsx_source_lane,
    source_finding_params_from_lane,
)


# ---------------------------------------------------------------------------
# source_finding_params_from_lane()
# ---------------------------------------------------------------------------


class TestSourceFindingParamsFromLane:
    def test_none_lane_returns_defaults(self) -> None:
        result = source_finding_params_from_lane(None)
        assert "min_overlap" in result
        assert "min_support" in result

    def test_lane_without_params_returns_defaults(self) -> None:
        result = source_finding_params_from_lane({"lane_id": "source_data_xlsx"})
        assert "min_overlap" in result

    def test_lane_without_source_data_findings_params(self) -> None:
        lane = {"params": {"other_tool": {"key": "value"}}}
        result = source_finding_params_from_lane(lane)
        assert "min_overlap" in result

    def test_lane_with_source_data_findings_params(self) -> None:
        lane = {
            "params": {
                "source_data_findings": {
                    "min_overlap": 20,
                    "min_support": 0.95,
                }
            }
        }
        result = source_finding_params_from_lane(lane)
        assert result["min_overlap"] == 20
        assert result["min_support"] == 0.95

    def test_lane_params_partial_override(self) -> None:
        lane = {
            "params": {
                "source_data_findings": {
                    "min_overlap": 30,
                }
            }
        }
        result = source_finding_params_from_lane(lane)
        assert result["min_overlap"] == 30
        # Other params should remain at defaults
        assert "min_support" in result


# ---------------------------------------------------------------------------
# selected_xlsx_source_lane()
# ---------------------------------------------------------------------------


class TestSelectedXlsxSourceLane:
    def test_returns_matching_lane(self) -> None:
        lanes = [
            {"lane_id": "source_data_xlsx", "status": "selected", "root": "data/"},
            {"lane_id": "other", "status": "selected", "root": "other/"},
        ]
        result = selected_xlsx_source_lane(lanes)
        assert result is not None
        assert result["lane_id"] == "source_data_xlsx"

    def test_no_matching_lane(self) -> None:
        lanes = [{"lane_id": "other", "status": "selected", "root": "other/"}]
        assert selected_xlsx_source_lane(lanes) is None

    def test_not_selected(self) -> None:
        lanes = [{"lane_id": "source_data_xlsx", "status": "skipped", "root": "data/"}]
        assert selected_xlsx_source_lane(lanes) is None

    def test_no_root(self) -> None:
        lanes = [{"lane_id": "source_data_xlsx", "status": "selected"}]
        assert selected_xlsx_source_lane(lanes) is None

    def test_empty_lanes(self) -> None:
        assert selected_xlsx_source_lane([]) is None


# ---------------------------------------------------------------------------
# material_plan_from_inventory()
# ---------------------------------------------------------------------------


class TestMaterialPlanFromInventory:
    def test_basic_plan_structure(self) -> None:
        inventory = {
            "files": [
                {"relative_path": "source_data.xlsx", "material_type": "source_data", "status": "selected"}
            ]
        }
        result = material_plan_from_inventory(
            case_id="test-case", inventory=inventory, status="ok", detail="Plan generated",
        )
        assert result["schema_version"] == "1.0"
        assert result["case_id"] == "test-case"
        assert result["status"] == "ok"
        assert "selected_optional_lanes" in result

    def test_unsupported_materials(self) -> None:
        inventory = {
            "files": [
                {"relative_path": "table.html", "material_type": "structured_table_text"},
                {"relative_path": "raw.csv", "material_type": "raw_data"},
            ]
        }
        result = material_plan_from_inventory(
            case_id="test-case", inventory=inventory, status="ok", detail="test",
        )
        unsupported_types = [m["material_type"] for m in result["unsupported_materials"]]
        assert "structured_table_text" in unsupported_types
        assert "raw_data" in unsupported_types

    def test_missing_materials_when_no_selected_lanes(self) -> None:
        inventory = {"files": []}
        result = material_plan_from_inventory(
            case_id="test-case", inventory=inventory, status="ok", detail="test",
        )
        assert "source_data_xlsx" in result["missing_materials"]

    def test_has_agent_rationale(self) -> None:
        result = material_plan_from_inventory(
            case_id="test-case", inventory={"files": []}, status="ok", detail="test",
        )
        assert len(result["agent_rationale"]) >= 1


# ---------------------------------------------------------------------------
# optional_lanes_from_material_plan()
# ---------------------------------------------------------------------------


class TestOptionalLanesFromMaterialPlan:
    def test_uses_material_plan_lanes(self) -> None:
        plan = {"selected_optional_lanes": [{"lane_id": "source_data_xlsx", "status": "selected"}]}
        result = optional_lanes_from_material_plan(plan, {})
        assert len(result) == 1
        assert result[0]["lane_id"] == "source_data_xlsx"

    def test_filters_non_dict_lanes(self) -> None:
        plan = {"selected_optional_lanes": [{"lane_id": "test"}, "invalid", None]}
        result = optional_lanes_from_material_plan(plan, {})
        assert len(result) == 1

    def test_fallback_to_inventory(self) -> None:
        result = optional_lanes_from_material_plan(None, {"files": []})
        assert isinstance(result, list)

    def test_fallback_when_no_selected_lanes(self) -> None:
        result = optional_lanes_from_material_plan({"status": "ok"}, {"files": []})
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# resolve_selected_source_root()
# ---------------------------------------------------------------------------


class TestResolveSelectedSourceRoot:
    def test_valid_absolute_path(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "source_data"
        source_dir.mkdir()
        lane = {"root": str(source_dir)}
        result = resolve_selected_source_root(lane, tmp_path)
        assert result == source_dir.resolve()

    def test_valid_relative_path(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "source_data"
        source_dir.mkdir()
        lane = {"root": "source_data"}
        result = resolve_selected_source_root(lane, tmp_path)
        assert result == source_dir.resolve()

    def test_none_lane(self, tmp_path: Path) -> None:
        assert resolve_selected_source_root(None, tmp_path) is None

    def test_no_root(self, tmp_path: Path) -> None:
        assert resolve_selected_source_root({"lane_id": "test"}, tmp_path) is None

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        lane = {"root": "nonexistent"}
        assert resolve_selected_source_root(lane, tmp_path) is None

    def test_path_outside_paper_dir(self, tmp_path: Path) -> None:
        lane = {"root": "/etc"}
        assert resolve_selected_source_root(lane, tmp_path) is None

    def test_file_not_dir(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("test")
        lane = {"root": "file.txt"}
        assert resolve_selected_source_root(lane, tmp_path) is None


# ---------------------------------------------------------------------------
# _run_static_audit_from_args — basic structure tests
# ---------------------------------------------------------------------------


class TestRunStaticAuditFromArgs:
    """Test the argument parsing and dispatch structure without running full pipeline."""

    def test_invalid_paper_dir_raises(self) -> None:
        from engine.static_audit.pipeline import _run_static_audit_from_args

        args = argparse.Namespace(
            paper_dir="/nonexistent/path",
            case_id="test",
            output_root="outputs",
            fresh=False,
            force=False,
            no_env_file=True,
            agent_mode="off",
            agent_model="test",
            opencode_bin="opencode",
            agent_timeout_seconds=60,
            agent_max_retries=1,
            skip_unavailable_tools=False,
        )
        import pytest
        with pytest.raises(NotADirectoryError):
            _run_static_audit_from_args(args)
