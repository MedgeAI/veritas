from __future__ import annotations

import pytest

from engine.tools.registry import (
    IMAGE_SIMILARITY_TOOL_ID,
    PAPER_STATIC_AUDIT_TOOL_IDS,
    SOURCE_DATA_FINDINGS_TOOL_ID,
    SOURCE_DATA_PAIR_FORENSICS_TOOL_ID,
    STATIC_AUDIT_V1_TOOL_IDS,
    tool_catalog_for_investigation,
    source_data_findings_params_from_plan,
    tool_catalog_for_agent,
    TOOLS,
    validate_investigation_tool_action,
    validate_plan_tools,
)


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
    assert "agent.material_plan" in STATIC_AUDIT_V1_TOOL_IDS
    assert "agent.role.judge" in STATIC_AUDIT_V1_TOOL_IDS
    assert "report.render_static_html" in STATIC_AUDIT_V1_TOOL_IDS


def test_tool_catalog_for_investigation_only_exposes_deterministic_selectable_tools() -> None:
    catalog = tool_catalog_for_investigation()
    exposed = {item["tool_id"] for item in catalog}

    assert IMAGE_SIMILARITY_TOOL_ID in exposed
    assert SOURCE_DATA_FINDINGS_TOOL_ID in exposed
    assert "agent.review" not in exposed
    assert "mineru.parse_pdf" not in exposed
    assert all(item["param_schema"] is not None for item in catalog)


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
        validate_plan_tools({"selected_tools": [{"tool_id": "unknown.tool", "params": {}}]})
