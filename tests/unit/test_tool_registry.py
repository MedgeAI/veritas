"""Tests for engine.tools.registry module.

Merged from: test_tool_registry.py + test_tool_registry_enhanced.py.
"""

from __future__ import annotations

import pytest

from engine.tools.registry import (
    ExecutionPhase,
    ToolDefinition,
    TOOLS,
    SOURCE_DATA_FINDINGS_TOOL_ID,
    IMAGE_SIMILARITY_TOOL_ID,
    TOOL_ID_OVERLAP_REUSE,
    TOOL_ID_COPY_MOVE,
    TOOL_ID_TRU_FOR,
    coerce_tool_params,
    selected_tool_ids_from_plan,
    source_data_findings_params_from_plan,
    tool_ids_to_step_keys,
    validate_investigation_tool_action,
    validate_plan_tools,
    _bounded_float,
    _bounded_int,
)
from engine.tools.registry import (
    PAPER_STATIC_AUDIT_TOOL_IDS,
    SOURCE_DATA_PAIR_FORENSICS_TOOL_ID,
    SOURCE_DATA_VERDICT_TOOL_ID,
    STATIC_AUDIT_V1_TOOL_IDS,
    tool_catalog_for_investigation,
    tool_catalog_for_agent,
)


# ===========================================================================
# test_tool_registry.py
# ===========================================================================


def test_tool_catalog_exposes_static_audit_tools() -> None:
    catalog = tool_catalog_for_agent()

    assert [item["tool_id"] for item in catalog] == list(PAPER_STATIC_AUDIT_TOOL_IDS)
    assert "material.inventory" in {item["tool_id"] for item in catalog}
    assert SOURCE_DATA_FINDINGS_TOOL_ID in {item["tool_id"] for item in catalog}
    assert SOURCE_DATA_PAIR_FORENSICS_TOOL_ID in {item["tool_id"] for item in catalog}
    assert "agent.material_plan" in TOOLS
    assert "image.similarity_candidates" in TOOLS
    assert "static_audit.bundle" in TOOLS
    assert "agent.role.claim_extractor" in TOOLS
    assert "agent.role.source_data_auditor" in TOOLS
    assert "agent.role.judge" in TOOLS
    assert "report.render_static_html" in TOOLS
    assert "image.similarity_candidates" in STATIC_AUDIT_V1_TOOL_IDS
    assert SOURCE_DATA_PAIR_FORENSICS_TOOL_ID in STATIC_AUDIT_V1_TOOL_IDS
    assert SOURCE_DATA_VERDICT_TOOL_ID in STATIC_AUDIT_V1_TOOL_IDS
    assert "agent.material_plan" in STATIC_AUDIT_V1_TOOL_IDS
    assert "agent.role.judge" in STATIC_AUDIT_V1_TOOL_IDS
    assert "report.render_static_html" in STATIC_AUDIT_V1_TOOL_IDS


def test_tool_catalog_for_investigation_only_exposes_deterministic_selectable_tools() -> (
    None
):
    catalog = tool_catalog_for_investigation()
    exposed = {item["tool_id"] for item in catalog}

    assert IMAGE_SIMILARITY_TOOL_ID in exposed
    assert SOURCE_DATA_FINDINGS_TOOL_ID not in exposed
    assert "agent.review" not in exposed
    assert "mineru.parse_pdf" not in exposed
    assert all(item["param_schema"] is not None for item in catalog)


def test_source_data_verdict_tool_contract() -> None:
    tool = TOOLS[SOURCE_DATA_VERDICT_TOOL_ID]

    assert tool.execution_phase == ExecutionPhase.CONDITIONAL_BASELINE
    assert tool.agent_selectable is False
    assert tool.deterministic is False
    assert tool.input_artifacts == (
        "source_data/findings.json",
        "source_data/pair_forensics.json",
        "source_data/profile.json",
    )
    assert tool.output_artifacts == ("source_data/findings_verdict.json",)


def test_validate_investigation_tool_action_bounds_params() -> None:
    action = validate_investigation_tool_action(
        {
            "action_id": "IR-01-A001",
            "tool_id": IMAGE_SIMILARITY_TOOL_ID,
            "params": {"max_distance": "7", "max_candidates": "50"},
            "hypothesis": "check near duplicate image candidates",
            "depends_on_artifacts": ["images/", "exact_image_duplicates.json"],
            "expected_evidence_type": "image_similarity",
        }
    )

    assert action["params"] == {"max_distance": 7, "max_candidates": 50}


def test_validate_investigation_tool_action_rejects_agent_tools() -> None:
    with pytest.raises(ValueError, match="not agent-selectable"):
        validate_investigation_tool_action(
            {
                "tool_id": "agent.review",
                "params": {},
                "hypothesis": "ask another agent",
                "depends_on_artifacts": ["source_data_findings.json"],
                "expected_evidence_type": "claim_mapping",
            }
        )


def test_source_data_findings_params_are_bounded() -> None:
    plan = {
        "selected_tools": [
            {
                "tool_id": SOURCE_DATA_FINDINGS_TOOL_ID,
                "params": {
                    "min_overlap": "14",
                    "min_support": "0.97",
                    "max_findings_per_category": "80",
                },
            }
        ]
    }

    assert source_data_findings_params_from_plan(plan) == {
        "min_overlap": 14,
        "min_support": 0.97,
        "max_findings_per_category": 80,
    }


def test_validate_plan_tools_rejects_unknown_tool_id() -> None:
    with pytest.raises(ValueError, match="unsupported tool_id"):
        validate_plan_tools(
            {"selected_tools": [{"tool_id": "unknown.tool", "params": {}}]}
        )


# ===========================================================================
# test_tool_registry_enhanced.py
# ===========================================================================


# ---------------------------------------------------------------------------
# ToolDefinition
# ---------------------------------------------------------------------------


class TestToolDefinition:
    def test_agent_selectable_from_execution_phase(self) -> None:
        tool = ToolDefinition(
            tool_id="test.tool",
            step_key="test",
            title="Test",
            source="test",
            description="Test tool",
            execution_phase=ExecutionPhase.AGENT_SELECTABLE,
        )
        assert tool.agent_selectable is True

    def test_not_agent_selectable_for_baseline(self) -> None:
        tool = ToolDefinition(
            tool_id="test.tool",
            step_key="test",
            title="Test",
            source="test",
            description="Test tool",
            execution_phase=ExecutionPhase.MANDATORY_BASELINE,
        )
        assert tool.agent_selectable is False

    def test_not_agent_selectable_for_conditional(self) -> None:
        tool = ToolDefinition(
            tool_id="test.tool",
            step_key="test",
            title="Test",
            source="test",
            description="Test tool",
            execution_phase=ExecutionPhase.CONDITIONAL_BASELINE,
        )
        assert tool.agent_selectable is False

    def test_not_agent_selectable_for_report_only(self) -> None:
        tool = ToolDefinition(
            tool_id="test.tool",
            step_key="test",
            title="Test",
            source="test",
            description="Test tool",
            execution_phase=ExecutionPhase.REPORT_ONLY,
        )
        assert tool.agent_selectable is False

    def test_frozen_dataclass(self) -> None:
        tool = ToolDefinition(
            tool_id="test.tool",
            step_key="test",
            title="Test",
            source="test",
            description="Test tool",
        )
        with pytest.raises(AttributeError):
            tool.tool_id = "modified"


# ---------------------------------------------------------------------------
# ExecutionPhase enum
# ---------------------------------------------------------------------------


class TestExecutionPhase:
    def test_string_values(self) -> None:
        assert ExecutionPhase.MANDATORY_BASELINE == "mandatory_baseline"
        assert ExecutionPhase.CONDITIONAL_BASELINE == "conditional_baseline"
        assert ExecutionPhase.AGENT_SELECTABLE == "agent_selectable"
        assert ExecutionPhase.REPORT_ONLY == "report_only"

    def test_is_string(self) -> None:
        assert isinstance(ExecutionPhase.MANDATORY_BASELINE, str)


# ---------------------------------------------------------------------------
# TOOLS registry completeness
# ---------------------------------------------------------------------------


class TestToolsRegistry:
    def test_all_tools_have_required_fields(self) -> None:
        for tool_id, tool in TOOLS.items():
            assert tool.tool_id == tool_id
            assert tool.step_key
            assert tool.title
            assert tool.source
            assert tool.description

    def test_overlap_reuse_is_agent_selectable(self) -> None:
        tool = TOOLS[TOOL_ID_OVERLAP_REUSE]
        assert tool.agent_selectable is True
        assert tool.execution_phase == ExecutionPhase.AGENT_SELECTABLE

    def test_image_similarity_is_agent_selectable(self) -> None:
        tool = TOOLS[IMAGE_SIMILARITY_TOOL_ID]
        assert tool.agent_selectable is True

    def test_source_data_findings_not_agent_selectable(self) -> None:
        tool = TOOLS[SOURCE_DATA_FINDINGS_TOOL_ID]
        assert tool.agent_selectable is False

    def test_copy_move_is_agent_selectable(self) -> None:
        tool = TOOLS[TOOL_ID_COPY_MOVE]
        assert tool.agent_selectable is True

    def test_tru_for_not_agent_selectable(self) -> None:
        tool = TOOLS[TOOL_ID_TRU_FOR]
        assert tool.agent_selectable is False


# ---------------------------------------------------------------------------
# coerce_tool_params()
# ---------------------------------------------------------------------------


class TestCoerceToolParams:
    def test_image_similarity_coercion(self) -> None:
        params = {"max_distance": "7", "max_candidates": "50"}
        result = coerce_tool_params(IMAGE_SIMILARITY_TOOL_ID, params)
        assert result["max_distance"] == 7
        assert result["max_candidates"] == 50

    def test_unknown_tool_returns_params_unchanged(self) -> None:
        params = {"key": "value"}
        result = coerce_tool_params("unknown.tool", params)
        assert result == params

    def test_empty_params_returns_defaults(self) -> None:
        result = coerce_tool_params(IMAGE_SIMILARITY_TOOL_ID, {})
        assert "max_distance" in result
        assert "max_candidates" in result


# ---------------------------------------------------------------------------
# tool_ids_to_step_keys()
# ---------------------------------------------------------------------------


class TestToolIdsToStepKeys:
    def test_maps_to_step_keys(self) -> None:
        result = tool_ids_to_step_keys([SOURCE_DATA_FINDINGS_TOOL_ID])
        assert len(result) == 1
        assert isinstance(result[0], str)

    def test_empty_list(self) -> None:
        assert tool_ids_to_step_keys([]) == []

    def test_unknown_tool_id_skipped(self) -> None:
        result = tool_ids_to_step_keys(["unknown.tool"])
        assert len(result) == 0


# ---------------------------------------------------------------------------
# selected_tool_ids_from_plan()
# ---------------------------------------------------------------------------


class TestSelectedToolIdsFromPlan:
    def test_extracts_tool_ids(self) -> None:
        plan = {
            "selected_tools": [
                {"tool_id": "source_data.findings", "params": {}},
                {"tool_id": "image.similarity_candidates", "params": {}},
            ]
        }
        result = selected_tool_ids_from_plan(plan)
        assert "source_data.findings" in result
        assert "image.similarity_candidates" in result

    def test_none_plan_returns_all_tools(self) -> None:
        result = selected_tool_ids_from_plan(None)
        assert len(result) > 0
        assert isinstance(result, list)

    def test_empty_selected_tools_returns_all_tools(self) -> None:
        result = selected_tool_ids_from_plan({"selected_tools": []})
        assert len(result) > 0

    def test_no_selected_tools_key_returns_all_tools(self) -> None:
        result = selected_tool_ids_from_plan({})
        assert len(result) > 0


# ---------------------------------------------------------------------------
# _bounded_int() / _bounded_float()
# ---------------------------------------------------------------------------


class TestBoundedInt:
    def test_valid_int(self) -> None:
        assert _bounded_int("10", "test", 1, 100) == 10

    def test_below_minimum_raises(self) -> None:
        with pytest.raises(ValueError, match="must be between"):
            _bounded_int("0", "test", 1, 100)

    def test_above_maximum_raises(self) -> None:
        with pytest.raises(ValueError, match="must be between"):
            _bounded_int("200", "test", 1, 100)

    def test_int_passthrough(self) -> None:
        assert _bounded_int(50, "test", 1, 100) == 50


class TestBoundedFloat:
    def test_valid_float(self) -> None:
        assert _bounded_float("0.5", "test", 0.0, 1.0) == 0.5

    def test_below_minimum_raises(self) -> None:
        with pytest.raises(ValueError, match="must be between"):
            _bounded_float("-0.1", "test", 0.0, 1.0)

    def test_above_maximum_raises(self) -> None:
        with pytest.raises(ValueError, match="must be between"):
            _bounded_float("1.5", "test", 0.0, 1.0)


# ---------------------------------------------------------------------------
# validate_plan_tools()
# ---------------------------------------------------------------------------


class TestValidatePlanTools:
    def test_valid_plan(self) -> None:
        plan = {
            "selected_tools": [{"tool_id": SOURCE_DATA_FINDINGS_TOOL_ID, "params": {}}]
        }
        result = validate_plan_tools(plan)
        assert isinstance(result, dict)

    def test_unknown_tool_rejected(self) -> None:
        with pytest.raises(ValueError, match="unsupported tool_id"):
            validate_plan_tools(
                {"selected_tools": [{"tool_id": "nonexistent.tool", "params": {}}]}
            )

    def test_empty_plan(self) -> None:
        result = validate_plan_tools({})
        assert isinstance(result, dict)

    def test_none_selected_tools(self) -> None:
        result = validate_plan_tools({"selected_tools": None})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# validate_investigation_tool_action() — additional edge cases
# ---------------------------------------------------------------------------


class TestValidateInvestigationToolAction:
    def test_rejects_non_selectable_tool(self) -> None:
        with pytest.raises(ValueError, match="not agent-selectable"):
            validate_investigation_tool_action(
                {
                    "tool_id": SOURCE_DATA_FINDINGS_TOOL_ID,
                    "params": {},
                    "hypothesis": "test",
                    "depends_on_artifacts": ["images/"],
                }
            )

    def test_accepts_agent_selectable_tool(self) -> None:
        action = validate_investigation_tool_action(
            {
                "action_id": "IR-01-A001",
                "tool_id": IMAGE_SIMILARITY_TOOL_ID,
                "params": {"max_distance": "5"},
                "hypothesis": "test similarity",
                "depends_on_artifacts": ["images/"],
                "expected_evidence_type": "image_similarity",
            }
        )
        assert action["tool_id"] == IMAGE_SIMILARITY_TOOL_ID
        assert action["params"]["max_distance"] == 5

    def test_hypothesis_required(self) -> None:
        with pytest.raises(ValueError, match="hypothesis"):
            validate_investigation_tool_action(
                {
                    "tool_id": IMAGE_SIMILARITY_TOOL_ID,
                    "params": {},
                    "hypothesis": "",
                    "depends_on_artifacts": ["images/"],
                }
            )

    def test_depends_on_artifacts_required(self) -> None:
        with pytest.raises(ValueError, match="depends_on_artifacts"):
            validate_investigation_tool_action(
                {
                    "tool_id": IMAGE_SIMILARITY_TOOL_ID,
                    "params": {},
                    "hypothesis": "test",
                    "depends_on_artifacts": [],
                }
            )


# ---------------------------------------------------------------------------
# source_data_findings_params_from_plan() — additional edge cases
# ---------------------------------------------------------------------------


class TestSourceDataFindingsParamsFromPlan:
    def test_none_plan(self) -> None:
        result = source_data_findings_params_from_plan(None)
        assert "min_overlap" in result

    def test_empty_plan(self) -> None:
        result = source_data_findings_params_from_plan({})
        assert "min_overlap" in result

    def test_invalid_overlap_raises(self) -> None:
        plan = {
            "selected_tools": [
                {
                    "tool_id": SOURCE_DATA_FINDINGS_TOOL_ID,
                    "params": {"min_overlap": "0"},
                }
            ]
        }
        with pytest.raises(ValueError):
            source_data_findings_params_from_plan(plan)

    def test_invalid_support_raises(self) -> None:
        plan = {
            "selected_tools": [
                {
                    "tool_id": SOURCE_DATA_FINDINGS_TOOL_ID,
                    "params": {"min_support": "2.0"},
                }
            ]
        }
        with pytest.raises(ValueError):
            source_data_findings_params_from_plan(plan)

    def test_valid_override(self) -> None:
        plan = {
            "selected_tools": [
                {
                    "tool_id": SOURCE_DATA_FINDINGS_TOOL_ID,
                    "params": {"min_overlap": "20", "min_support": "0.95"},
                }
            ]
        }
        result = source_data_findings_params_from_plan(plan)
        assert result["min_overlap"] == 20
        assert result["min_support"] == 0.95
