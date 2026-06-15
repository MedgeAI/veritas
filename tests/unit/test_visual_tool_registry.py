"""Test visual forensics tool registration in Tool Registry."""

from __future__ import annotations

import pytest

from engine.tools.registry import (
    STATIC_AUDIT_V1_TOOL_IDS,
    TOOLS,
    TOOL_ID_COPY_MOVE,
    TOOL_ID_FINDING_PIPELINE,
    TOOL_ID_PANEL_EXTRACTION,
    coerce_tool_params,
    validate_investigation_tool_action,
)


class TestVisualToolConstants:
    """Verify visual tool ID constants are defined."""

    def test_tool_id_panel_extraction_defined(self):
        assert TOOL_ID_PANEL_EXTRACTION == "visual.panel_extraction"

    def test_tool_id_copy_move_defined(self):
        assert TOOL_ID_COPY_MOVE == "visual.copy_move"

    def test_tool_id_finding_pipeline_defined(self):
        assert TOOL_ID_FINDING_PIPELINE == "visual.finding_pipeline"


class TestVisualToolRegistration:
    """Verify visual tools are registered in TOOLS dict."""

    def test_panel_extraction_registered(self):
        assert TOOL_ID_PANEL_EXTRACTION in TOOLS

    def test_copy_move_registered(self):
        assert TOOL_ID_COPY_MOVE in TOOLS

    def test_finding_pipeline_registered(self):
        assert TOOL_ID_FINDING_PIPELINE in TOOLS

    def test_tools_in_static_audit_v1(self):
        assert TOOL_ID_PANEL_EXTRACTION in STATIC_AUDIT_V1_TOOL_IDS
        assert TOOL_ID_COPY_MOVE in STATIC_AUDIT_V1_TOOL_IDS
        assert TOOL_ID_FINDING_PIPELINE in STATIC_AUDIT_V1_TOOL_IDS


class TestVisualToolProperties:
    """Verify visual tool properties match specifications."""

    def test_panel_extraction_is_mandatory_bootstrap(self):
        tool = TOOLS[TOOL_ID_PANEL_EXTRACTION]
        assert tool.execution_phase == "mandatory_bootstrap"
        assert tool.agent_selectable is False
        assert tool.deterministic is True
        assert tool.step_key == "visual_panel_extraction"

    def test_copy_move_is_agent_selectable(self):
        tool = TOOLS[TOOL_ID_COPY_MOVE]
        assert tool.agent_selectable is True
        assert tool.deterministic is True
        assert tool.step_key == "visual_copy_move"
        assert "min_matches" in tool.parameter_defaults
        assert "min_score" in tool.parameter_defaults

    def test_finding_pipeline_is_report_only(self):
        tool = TOOLS[TOOL_ID_FINDING_PIPELINE]
        assert tool.execution_phase == "report_only"
        assert tool.agent_selectable is False
        assert tool.deterministic is True
        assert tool.step_key == "visual_finding_pipeline"

    def test_panel_extraction_input_output_artifacts(self):
        tool = TOOLS[TOOL_ID_PANEL_EXTRACTION]
        assert "visual/images/" in tool.input_artifacts
        assert "visual/evidence.json" in tool.output_artifacts
        assert "visual/panel_evidence.json" in tool.output_artifacts

    def test_copy_move_input_output_artifacts(self):
        tool = TOOLS[TOOL_ID_COPY_MOVE]
        assert "visual/panel_evidence.json" in tool.input_artifacts
        assert "visual/evidence.json" in tool.input_artifacts
        assert "visual/copy_move.json" in tool.output_artifacts

    def test_finding_pipeline_input_output_artifacts(self):
        tool = TOOLS[TOOL_ID_FINDING_PIPELINE]
        assert "visual/panel_evidence.json" in tool.input_artifacts
        assert "visual/copy_move.json" in tool.input_artifacts
        assert "visual/relationships.json" in tool.output_artifacts
        assert "visual/findings.json" in tool.output_artifacts


class TestVisualToolParamCoercion:
    """Verify coerce_tool_params handles visual tools correctly."""

    def test_panel_extraction_params_empty(self):
        params = coerce_tool_params(TOOL_ID_PANEL_EXTRACTION, {})
        assert params == {}

    def test_copy_move_params_defaults(self):
        params = coerce_tool_params(TOOL_ID_COPY_MOVE, {})
        assert params["method"] == "rootsift_magsac"
        assert params["min_matches"] == 20
        assert params["min_score"] == 0.05
        assert params["max_relationships"] == 500

    def test_copy_move_params_custom(self):
        params = coerce_tool_params(
            TOOL_ID_COPY_MOVE,
            {"method": "rootsift_magsac", "min_matches": 30, "min_score": 0.1},
        )
        assert params["method"] == "rootsift_magsac"
        assert params["min_matches"] == 30
        assert params["min_score"] == 0.1

    def test_copy_move_params_accept_legacy_aliases(self):
        params = coerce_tool_params(
            TOOL_ID_COPY_MOVE,
            {"min_keypoints": 25},
        )
        assert params["min_matches"] == 25

    def test_copy_move_params_validation_min_keypoints(self):
        with pytest.raises(ValueError, match="min_matches"):
            coerce_tool_params(TOOL_ID_COPY_MOVE, {"min_matches": 2})

        with pytest.raises(ValueError, match="min_matches"):
            coerce_tool_params(TOOL_ID_COPY_MOVE, {"min_matches": 250})

    def test_copy_move_params_validation_method(self):
        with pytest.raises(ValueError, match="method"):
            coerce_tool_params(TOOL_ID_COPY_MOVE, {"method": "orb"})

    def test_finding_pipeline_params_empty(self):
        params = coerce_tool_params(TOOL_ID_FINDING_PIPELINE, {})
        assert params == {}


class TestVisualToolInvestigationValidation:
    """Verify validate_investigation_tool_action handles visual tools."""

    def test_copy_move_is_selectable_for_investigation(self):
        """copy_move should be selectable for investigation rounds."""
        action = {
            "tool_id": TOOL_ID_COPY_MOVE,
            "params": {"min_matches": 25},
            "hypothesis": "Test hypothesis",
            "depends_on_artifacts": ["panel_evidence.json"],
            "expected_evidence_type": "image_similarity",
        }
        validated = validate_investigation_tool_action(action)
        assert validated["tool_id"] == TOOL_ID_COPY_MOVE
        assert validated["params"]["min_matches"] == 25

    def test_panel_extraction_not_selectable_for_investigation(self):
        """panel_extraction should not be selectable for investigation."""
        action = {
            "tool_id": TOOL_ID_PANEL_EXTRACTION,
            "params": {},
            "hypothesis": "Test hypothesis",
            "depends_on_artifacts": ["images/"],
            "expected_evidence_type": "image_similarity",
        }
        with pytest.raises(ValueError, match="not agent-selectable"):
            validate_investigation_tool_action(action)

    def test_finding_pipeline_not_selectable_for_investigation(self):
        """finding_pipeline should not be selectable for investigation."""
        action = {
            "tool_id": TOOL_ID_FINDING_PIPELINE,
            "params": {},
            "hypothesis": "Test hypothesis",
            "depends_on_artifacts": ["panel_evidence.json"],
            "expected_evidence_type": "image_similarity",
        }
        with pytest.raises(ValueError, match="not agent-selectable"):
            validate_investigation_tool_action(action)
