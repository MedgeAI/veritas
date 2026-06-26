"""Shared types, constants, and helpers for Veritas audit engine.

This package contains shared types, constants, and helper functions used
across engine.static_audit and engine.investigation modules to eliminate
circular imports.
"""

from engine.shared.constants import (  # noqa: F401
    ARTIFACT_PATH_MAP,
    AUDITOR_ROOT,
    MAX_INVESTIGATION_ROUNDS,
    OUTPUT_DIRS,
    PROJECT_ROOT,
    STEP_TOOL_IDS,
)
from engine.shared.helpers import (  # noqa: F401
    _write_long_text_to_log,
    EXPECTED_EVIDENCE_TYPES,
    agent_step_status,
    artifact_exists,
    classify_finding,
    command_preview,
    emit_progress,
    emit_step_result,
    emit_step_start,
    enforce_event_contract,
    existing_artifact_path,
    filter_judge_input,
    investigation_action_from_dict,
    normalize_expected_evidence_type,
    read_json,
    record_step,
    resolve_artifact_path,
    safe_action_dir_name,
    source_finding_params_from_lane,
    source_finding_params_from_plan,
    write_json_artifact,
)
from engine.shared.types import (  # noqa: F401
    InvestigationAction,
    ProgressCallback,
    StepResult,
)

__all__ = [
    # Types
    "InvestigationAction",
    "ProgressCallback",
    "StepResult",
    # Constants
    "ARTIFACT_PATH_MAP",
    "AUDITOR_ROOT",
    "EXPECTED_EVIDENCE_TYPES",
    "MAX_INVESTIGATION_ROUNDS",
    "OUTPUT_DIRS",
    "PROJECT_ROOT",
    "STEP_TOOL_IDS",
    # Helpers
    "_write_long_text_to_log",
    "agent_step_status",
    "artifact_exists",
    "classify_finding",
    "command_preview",
    "emit_progress",
    "emit_step_result",
    "emit_step_start",
    "enforce_event_contract",
    "existing_artifact_path",
    "filter_judge_input",
    "investigation_action_from_dict",
    "normalize_expected_evidence_type",
    "read_json",
    "record_step",
    "resolve_artifact_path",
    "safe_action_dir_name",
    "source_finding_params_from_lane",
    "source_finding_params_from_plan",
    "write_json_artifact",
]
