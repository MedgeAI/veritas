#!/usr/bin/env python3
"""Backward-compat entry point for the static audit pipeline.

All public symbols are re-exported from their actual modules. This file exists
solely so that existing ``from engine.static_audit.orchestrator import X``
statements continue to work without changes.

New code should import directly from the specific module:

* ``engine.static_audit.pipeline`` – run_static_audit, core orchestration
* ``engine.static_audit.cli_driver`` – CLI parsing, main()
* ``engine.static_audit._shared`` – StepResult, ProgressCallback, helpers
* ``engine.static_audit.report`` – generate_report, build_static_audit_bundle
* ``engine.static_audit.investigation_dispatch`` – run_investigation_rounds
* ``engine.static_audit.visual_pipeline`` – visual tool wrappers
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Re-exports from _shared.py
# ---------------------------------------------------------------------------
from engine.static_audit._shared import (
    ARTIFACT_PATH_MAP,
    AUDITOR_ROOT,
    MAX_INVESTIGATION_ROUNDS,
    OUTPUT_DIRS,
    PROJECT_ROOT,
    STEP_TOOL_IDS,
    ProgressCallback,
    StepResult,
    _write_long_text_to_log,
    agent_step_status,
    artifact_exists,
    artifact_path_candidates,
    emit_progress,
    emit_step_result,
    emit_step_start,
    enforce_event_contract,
    ensure_output_subdirs,
    existing_artifact_path,
    investigation_action_from_dict,
    output_subdir,
    read_json,
    record_step,
    resolve_artifact_path,
    run_command,
    safe_action_dir_name,
    source_finding_params_from_plan,
)

# ---------------------------------------------------------------------------
# Re-exports from pipeline.py (core orchestration)
# ---------------------------------------------------------------------------
from engine.static_audit.pipeline import (
    _run_static_audit_from_args,
    material_plan_from_inventory,
    optional_lanes_from_material_plan,
    resolve_selected_source_root,
    run_static_audit,
    selected_xlsx_source_lane,
    source_finding_params_from_lane,
)

# ---------------------------------------------------------------------------
# Re-exports from cli_driver.py (CLI entry)
# ---------------------------------------------------------------------------
from engine.static_audit.cli_driver import (
    discover_pdf,
    exists_all,
    load_env,
    main,
    parse_args,
    safe_remove_workdir,
    text_tail,
)

# ---------------------------------------------------------------------------
# Lazy re-exports for modules that may form circular dependencies at load time.
# ---------------------------------------------------------------------------
_LAZY_REEXPORTS: dict[str, str] = {
    # report.py
    "generate_report": "engine.static_audit.report",
    "build_static_audit_bundle": "engine.static_audit.report",
    "collect_claims_and_findings": "engine.static_audit.report",
    "collect_evidence_items": "engine.static_audit.report",
    "collect_agent_refined_claim_mappings": "engine.static_audit.report",
    "collect_deterministic_claim_mappings": "engine.static_audit.report",
    "normalize_claim_status": "engine.static_audit.report",
    "brief_list": "engine.static_audit.report",
    "dedupe": "engine.static_audit.report",
    "agent_manual_review_rows": "engine.static_audit.report",
    "agent_finding_review_rows": "engine.static_audit.report",
    "investigation_record_rows": "engine.static_audit.report",
    # visual_pipeline.py
    "run_visual_panel_extraction": "engine.static_audit.visual_pipeline",
    "run_visual_finding_pipeline": "engine.static_audit.visual_pipeline",
    "run_tru_for_detection": "engine.static_audit.visual_pipeline",
    "run_image_quality_detection": "engine.static_audit.visual_pipeline",
    "run_overlap_reuse_detection": "engine.static_audit.visual_pipeline",
    "run_provenance_graph": "engine.static_audit.visual_pipeline",
    "run_sila_dense_detection": "engine.static_audit.visual_pipeline",
    # investigation_dispatch.py
    "run_investigation_rounds": "engine.static_audit.investigation_dispatch",
    "run_investigation_tool_action": "engine.static_audit.investigation_dispatch",
    "run_agent_roles": "engine.static_audit.investigation_dispatch",
    "collect_agent_traces": "engine.static_audit.investigation_dispatch",
    "trace_from_role_result": "engine.static_audit.investigation_dispatch",
    "write_role_agent_result": "engine.static_audit.investigation_dispatch",
    "role_failure_payload": "engine.static_audit.investigation_dispatch",
    "role_output_summary": "engine.static_audit.investigation_dispatch",
    "write_reserved_role_output": "engine.static_audit.investigation_dispatch",
    "write_role_trace": "engine.static_audit.investigation_dispatch",
    "read_agent_trace": "engine.static_audit.investigation_dispatch",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_REEXPORTS:
        import importlib

        module = importlib.import_module(_LAZY_REEXPORTS[name])
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # _shared
    "ARTIFACT_PATH_MAP",
    "AUDITOR_ROOT",
    "MAX_INVESTIGATION_ROUNDS",
    "OUTPUT_DIRS",
    "PROJECT_ROOT",
    "STEP_TOOL_IDS",
    "ProgressCallback",
    "StepResult",
    "_write_long_text_to_log",
    "agent_step_status",
    "artifact_exists",
    "artifact_path_candidates",
    "emit_progress",
    "emit_step_result",
    "emit_step_start",
    "enforce_event_contract",
    "ensure_output_subdirs",
    "existing_artifact_path",
    "investigation_action_from_dict",
    "output_subdir",
    "read_json",
    "record_step",
    "resolve_artifact_path",
    "run_command",
    "safe_action_dir_name",
    "source_finding_params_from_plan",
    # pipeline
    "_run_static_audit_from_args",
    "material_plan_from_inventory",
    "optional_lanes_from_material_plan",
    "resolve_selected_source_root",
    "run_static_audit",
    "selected_xlsx_source_lane",
    "source_finding_params_from_lane",
    # cli_driver
    "discover_pdf",
    "exists_all",
    "load_env",
    "main",
    "parse_args",
    "safe_remove_workdir",
    "text_tail",
    # lazy re-exports (report / visual_pipeline / investigation_dispatch)
    "generate_report",
    "build_static_audit_bundle",
    "collect_claims_and_findings",
    "collect_evidence_items",
    "collect_agent_refined_claim_mappings",
    "collect_deterministic_claim_mappings",
    "normalize_claim_status",
    "brief_list",
    "dedupe",
    "agent_manual_review_rows",
    "agent_finding_review_rows",
    "investigation_record_rows",
    "run_visual_panel_extraction",
    "run_visual_finding_pipeline",
    "run_tru_for_detection",
    "run_image_quality_detection",
    "run_overlap_reuse_detection",
    "run_provenance_graph",
    "run_sila_dense_detection",
    "run_investigation_rounds",
    "run_investigation_tool_action",
    "run_agent_roles",
    "collect_agent_traces",
    "trace_from_role_result",
    "write_role_agent_result",
    "role_failure_payload",
    "role_output_summary",
    "write_reserved_role_output",
    "write_role_trace",
    "read_agent_trace",
]


if __name__ == "__main__":
    raise SystemExit(main())
