"""Backward-compatible re-export layer for split modules."""

from engine.investigation._shared import (
    AgentRunResult,
    result_metadata,
    write_agent_result,
)
from engine.investigation.planner import (
    build_investigation_plan_prompt,
    build_plan_prompt,
    fake_investigation_plan,
    fake_plan,
    run_agent_investigation_plan,
    run_agent_plan,
    validate_investigation_plan,
    validate_plan,
)
from engine.investigation.review_material import (
    build_material_plan_prompt,
    build_review_prompt,
    fake_material_plan,
    fake_review,
    run_agent_material_plan,
    run_agent_review,
    validate_material_plan,
    validate_review,
)
from engine.investigation.role_runners import (
    REAL_STATIC_AUDIT_ROLE_IDS,
    build_role_prompt,
    fake_role_output,
    run_agent_role,
    validate_role_output,
)
from engine.investigation.validators import (
    DEFAULT_SOURCE_FINDING_PARAMS,
    extract_json,
)

__all__ = [
    "AgentRunResult",
    "DEFAULT_SOURCE_FINDING_PARAMS",
    "REAL_STATIC_AUDIT_ROLE_IDS",
    "build_investigation_plan_prompt",
    "build_material_plan_prompt",
    "build_plan_prompt",
    "build_review_prompt",
    "build_role_prompt",
    "extract_json",
    "fake_investigation_plan",
    "fake_material_plan",
    "fake_plan",
    "fake_review",
    "fake_role_output",
    "result_metadata",
    "run_agent_investigation_plan",
    "run_agent_material_plan",
    "run_agent_plan",
    "run_agent_review",
    "run_agent_role",
    "validate_investigation_plan",
    "validate_material_plan",
    "validate_plan",
    "validate_review",
    "validate_role_output",
    "write_agent_result",
]
