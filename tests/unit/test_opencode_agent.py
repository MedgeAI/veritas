from __future__ import annotations

from pathlib import Path

from engine.investigation.opencode_agent import (
    extract_json,
    fake_investigation_plan,
    fake_material_plan,
    fake_role_output,
    validate_investigation_plan,
    validate_material_plan,
    validate_plan,
    validate_review,
    validate_role_output,
)


def test_extract_json_prefers_opencode_text_event() -> None:
    raw = "\n".join(
        [
            '{"type":"step_start","part":{"id":"ignored"}}',
            '{"type":"text","part":{"text":"{\\"schema_version\\":\\"1.0\\",\\"case_id\\":\\"case-a\\"}"}}',
            '{"type":"step_finish","part":{"reason":"stop"}}',
        ]
    )

    assert extract_json(raw) == {"schema_version": "1.0", "case_id": "case-a"}


def test_validate_plan_bounds_source_data_params() -> None:
    data = validate_plan(
        {
            "schema_version": "1.0",
            "case_id": "case-a",
            "material_inventory": {},
            "selected_tools": [
                {"tool_id": "mineru.parse_pdf", "params": {}, "reason": "parse pdf"},
                {
                    "tool_id": "source_data.findings",
                    "params": {
                        "min_overlap": "16",
                        "min_support": "0.95",
                        "max_findings_per_category": "120",
                    },
                    "reason": "source data checks",
                },
                {"tool_id": "report.render_markdown", "params": {}, "reason": "render"},
            ],
        }
    )

    params = data["script_parameters"]["source_data_findings"]
    assert data["selected_steps"] == ["mineru", "source_data_findings", "report"]
    assert params == {
        "min_overlap": 16,
        "min_support": 0.95,
        "max_findings_per_category": 120,
    }


def test_validate_plan_accepts_legacy_selected_steps() -> None:
    data = validate_plan(
        {
            "schema_version": "1.0",
            "case_id": "case-a",
            "material_inventory": {},
            "selected_steps": ["mineru", "source_data_findings", "report"],
            "script_parameters": {
                "source_data_findings": {
                    "min_overlap": "16",
                    "min_support": "0.95",
                    "max_findings_per_category": "120",
                }
            },
        }
    )

    params = data["script_parameters"]["source_data_findings"]
    assert [item["tool_id"] for item in data["selected_tools"]] == [
        "mineru.parse_pdf",
        "source_data.findings",
        "report.render_markdown",
    ]
    assert params == {
        "min_overlap": 16,
        "min_support": 0.95,
        "max_findings_per_category": 120,
    }


def test_validate_review_accepts_required_lists() -> None:
    data = validate_review(
        {
            "schema_version": "1.0",
            "case_id": "case-a",
            "candidate_claims": [],
            "claim_to_source_data": [],
            "finding_reviews": [],
            "manual_review_tasks": [],
            "report_notes": [],
            "limitations": [],
        }
    )

    assert data["case_id"] == "case-a"


def test_validate_material_plan_accepts_selected_xlsx_lane(tmp_path) -> None:
    source_root = tmp_path / "Source Data"
    source_root.mkdir()

    data = validate_material_plan(
        {
            "schema_version": "1.0",
            "case_id": "case-a",
            "selected_optional_lanes": [
                {
                    "lane_id": "source_data_xlsx",
                    "status": "selected",
                    "tool_ids": ["source_data.profile", "source_data.findings", "source_data.pair_forensics"],
                    "root": str(source_root),
                    "reason": "xlsx source data detected",
                    "params": {
                        "source_data_findings": {
                            "min_overlap": "16",
                            "min_support": "0.95",
                            "max_findings_per_category": "120",
                        }
                    },
                }
            ],
            "missing_materials": [],
            "unsupported_materials": [],
            "agent_rationale": [],
        }
    )

    lane = data["selected_optional_lanes"][0]
    assert lane["status"] == "selected"
    assert lane["params"]["source_data_findings"] == {
        "min_overlap": 16,
        "min_support": 0.95,
        "max_findings_per_category": 120,
    }


def test_validate_investigation_plan_accepts_selectable_tool_action() -> None:
    data = validate_investigation_plan(
        {
            "schema_version": "1.0",
            "case_id": "case-a",
            "round_id": 1,
            "actions": [
                {
                    "action_id": "IR-01-A001",
                    "tool_id": "image.similarity_candidates",
                    "params": {"max_distance": "6", "max_candidates": "20"},
                    "hypothesis": "补充近似图片重复候选。",
                    "depends_on_artifacts": ["images/", "exact_image_duplicates.json"],
                    "expected_evidence_type": "image_similarity",
                }
            ],
            "stop_reason": "",
            "agent_rationale": [],
        },
        round_id=1,
    )

    assert data["actions"][0]["params"] == {"max_distance": 6, "max_candidates": 20}


def test_validate_investigation_plan_rejects_wrong_round_id() -> None:
    try:
        validate_investigation_plan(
            {
                "schema_version": "1.0",
                "case_id": "case-a",
                "round_id": 2,
                "actions": [],
                "agent_rationale": [],
            },
            round_id=1,
        )
    except ValueError as exc:
        assert "round_id must be 1" in str(exc)
    else:
        raise AssertionError("expected wrong round_id to be rejected")


def test_fake_investigation_plan_selects_image_similarity_when_images_exist(tmp_path) -> None:
    (tmp_path / "images").mkdir()

    plan = fake_investigation_plan(case_id="case-a", workdir=Path(tmp_path), round_id=1)

    assert plan["actions"][0]["tool_id"] == "image.similarity_candidates"


def test_fake_material_plan_reports_missing_source_data_without_inventory(tmp_path) -> None:
    plan = fake_material_plan(case_id="case-a", workdir=Path(tmp_path))

    assert plan["selected_optional_lanes"] == []
    assert plan["missing_materials"] == ["source_data_xlsx"]


def test_validate_role_output_accepts_three_real_roles(tmp_path) -> None:
    for role_id in ["claim_extractor", "source_data_auditor", "judge"]:
        data = fake_role_output(role_id=role_id, case_id="case-a", workdir=Path(tmp_path))

        validated = validate_role_output(role_id, data)

        assert validated["role_id"] == role_id
        assert validated["case_id"] == "case-a"
