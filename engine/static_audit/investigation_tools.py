"""Investigation tool adapters — registry-based dispatch for Agent investigation tools.

This module eliminates the 600+ line elif chain in investigation_dispatch.py by
mapping each tool_id to an adapter function. Adding a new investigation tool now
means adding one function and one registry entry — no changes to the dispatcher.

Architecture:
    investigation_dispatch.py  →  investigation_tools.py (this file)  →  tool modules
        (orchestration)              (adapter registry)                  (actual execution)

Each adapter function:
    - Receives: (action, workdir, source_data_dir, env, force, progress, key, action_dir, output)
    - Returns: (StepResult, output_artifacts_list)
    - Is responsible for its own precondition checks and error handling
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from engine.shared.types import InvestigationAction
from engine.tools.registry import (
    IMAGE_SIMILARITY_TOOL_ID,
    SOURCE_DATA_CROSS_SHEET_TOOL_ID,
    SOURCE_DATA_FINDINGS_TOOL_ID,
    SOURCE_DATA_PAIR_FORENSICS_TOOL_ID,
    TOOL_ID_COPY_MOVE,
    TOOL_ID_OVERLAP_REUSE,
    TOOL_ID_SILA_DENSE,
)

# Re-imported for adapter convenience (avoids circular import with opencode_agent)
from engine.investigation.validators import DEFAULT_SOURCE_FINDING_PARAMS

from engine.static_audit._shared import (
    StepResult,
    emit_step_result,
    resolve_artifact_path,
    run_command,
    PROJECT_ROOT,
)

logger = logging.getLogger(__name__)

# Type alias for adapter functions
AdapterFn = Callable[
    [
        InvestigationAction,  # action
        Path,                 # workdir
        Path | None,          # source_data_dir
        dict[str, str],       # env
        bool,                 # force
        Any,                  # progress (ProgressCallback | None)
        str,                  # step_key
        Path,                 # action_dir
        Path,                 # output_path
    ],
    tuple[StepResult, list[str]],
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SKIP_TITLE = "Agent Investigation Tool"


def _skip(key: str, detail: str, progress: Any) -> tuple[StepResult, list[str]]:
    """Create a 'skipped' step result and emit it."""
    step = StepResult(key, _SKIP_TITLE, "skipped", detail)
    emit_step_result(progress, step)
    return step, []


def _require_source_data_dir(
    source_data_dir: Path | None,
    key: str,
    progress: Any,
) -> bool:
    """Return True if source_data_dir is missing (caller should skip)."""
    return not source_data_dir or not source_data_dir.is_dir()


def _load_panels_and_figures(
    workdir: Path,
) -> tuple[list[Any], list[Any]]:
    """Load panel_evidence.json and visual evidence figures for visual tools.

    Returns (panels_list, figures_list). Both default to empty lists if
    artifacts are missing or have unexpected structure.
    """
    panel_json = resolve_artifact_path(workdir, "panel_evidence.json")
    if not panel_json.exists():
        return [], []

    panels_data = json.loads(panel_json.read_text())
    panels_list = (
        panels_data.get("panels", panels_data)
        if isinstance(panels_data, dict)
        else panels_data
    )

    figures: list[Any] = []
    visual_path = resolve_artifact_path(workdir, "visual_evidence.json")
    if visual_path.exists():
        figures_data = json.loads(visual_path.read_text())
        figures = (
            figures_data.get("figures", figures_data)
            if isinstance(figures_data, dict)
            else figures_data
        )

    return panels_list, figures


def _direct_tool_result(
    result: dict[str, Any],
    output: Path,
    key: str,
    progress: Any,
) -> tuple[StepResult, list[str]]:
    """Build StepResult from a direct-execution tool's result dict."""
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    status = result.get("status", "failed")
    detail = (
        f"panels={result.get('panel_count', 0)} "
        f"rels={result.get('relationship_count', 0)}"
    )
    step = StepResult(
        key,
        _SKIP_TITLE,
        "ran" if status == "ran" else "failed",
        detail,
    )
    emit_step_result(progress, step)
    return step, [str(output)]


# ---------------------------------------------------------------------------
# Adapter functions — one per investigation tool
# ---------------------------------------------------------------------------


def _adapt_source_data_profile(
    action: InvestigationAction,
    workdir: Path,
    source_data_dir: Path | None,
    env: dict[str, str],
    force: bool,
    progress: Any,
    key: str,
    action_dir: Path,
    output: Path,
) -> tuple[StepResult, list[str]]:
    if _require_source_data_dir(source_data_dir, key, progress):
        return _skip(key, "No selected Source Data directory.", progress)
    command = [
        sys.executable, "-m",
        "engine.static_audit.tools.source_data_profile",
        str(source_data_dir),
        "--output", str(output),
    ]
    step = run_command(
        key, f"Agent Investigation Tool: {action.tool_id}",
        command, [output], cwd=PROJECT_ROOT, env=env, force=force, progress=progress,
    )
    return step, [str(output)]


def _adapt_source_data_findings(
    action: InvestigationAction,
    workdir: Path,
    source_data_dir: Path | None,
    env: dict[str, str],
    force: bool,
    progress: Any,
    key: str,
    action_dir: Path,
    output: Path,
) -> tuple[StepResult, list[str]]:
    if _require_source_data_dir(source_data_dir, key, progress):
        return _skip(key, "No selected Source Data directory.", progress)
    profile = resolve_artifact_path(workdir, "source_data_profile.json")
    if not profile.exists():
        return _skip(key, "source_data_profile.json missing.", progress)
    params = dict(DEFAULT_SOURCE_FINDING_PARAMS)
    params.update(action.params)
    command = [
        sys.executable, "-m",
        "engine.static_audit.tools.source_data_findings",
        str(source_data_dir),
        "--profile", str(profile),
        "--output", str(output),
        "--min-overlap", str(params["min_overlap"]),
        "--min-support", str(params["min_support"]),
        "--max-findings-per-category", str(params["max_findings_per_category"]),
    ]
    full_md = resolve_artifact_path(workdir, "full.md")
    if full_md.exists():
        command.extend(["--full-md", str(full_md)])
    step = run_command(
        key, f"Agent Investigation Tool: {action.tool_id}",
        command, [output], cwd=PROJECT_ROOT, env=env, force=force, progress=progress,
    )
    return step, [str(output)]


def _adapt_source_data_pair_forensics(
    action: InvestigationAction,
    workdir: Path,
    source_data_dir: Path | None,
    env: dict[str, str],
    force: bool,
    progress: Any,
    key: str,
    action_dir: Path,
    output: Path,
) -> tuple[StepResult, list[str]]:
    if _require_source_data_dir(source_data_dir, key, progress):
        return _skip(key, "No selected Source Data directory.", progress)
    params = action.params
    command = [
        sys.executable, "-m",
        "engine.static_audit.tools.source_data_pair_forensics",
        str(source_data_dir),
        "--output", str(output),
        "--min-pairs", str(params.get("min_pairs", 8)),
        "--min-support", str(params.get("min_support", 0.95)),
        "--ratio-places", str(params.get("ratio_places", 4)),
        "--max-offset", str(params.get("max_offset", 80)),
        "--max-findings-per-category", str(params.get("max_findings_per_category", 50)),
        "--min-duplicate-row-width", str(params.get("min_duplicate_row_width", 2)),
    ]
    step = run_command(
        key, f"Agent Investigation Tool: {action.tool_id}",
        command, [output], cwd=PROJECT_ROOT, env=env, force=force, progress=progress,
    )
    return step, [str(output)]


def _adapt_source_data_cross_sheet(
    action: InvestigationAction,
    workdir: Path,
    source_data_dir: Path | None,
    env: dict[str, str],
    force: bool,
    progress: Any,
    key: str,
    action_dir: Path,
    output: Path,
) -> tuple[StepResult, list[str]]:
    params = action.params
    command = [
        sys.executable, "-m",
        "engine.static_audit.tools.source_data_cross_sheet",
        str(source_data_dir),
        "--output", str(output),
        "--min-overlap", str(params.get("min_overlap", 10)),
        "--min-support", str(params.get("min_support", 0.95)),
        "--max-findings", str(params.get("max_findings", 50)),
    ]
    step = run_command(
        key, f"Agent Investigation Tool: {action.tool_id}",
        command, [output], cwd=PROJECT_ROOT, env=env, force=force, progress=progress,
    )
    return step, [str(output)]


def _adapt_image_similarity(
    action: InvestigationAction,
    workdir: Path,
    source_data_dir: Path | None,
    env: dict[str, str],
    force: bool,
    progress: Any,
    key: str,
    action_dir: Path,
    output: Path,
) -> tuple[StepResult, list[str]]:
    images_dir = resolve_artifact_path(workdir, "images")
    if not images_dir.is_dir():
        return _skip(key, "images directory missing.", progress)
    params = action.params
    command = [
        sys.executable, "-m",
        "engine.static_audit.tools.image_similarity",
        str(images_dir),
        "--output", str(output),
        "--max-distance", str(params.get("max_distance", 8)),
        "--max-candidates", str(params.get("max_candidates", 200)),
    ]
    panel_evidence_json = resolve_artifact_path(workdir, "panel_evidence.json")
    if panel_evidence_json.exists():
        command.extend(["--panel-evidence", str(panel_evidence_json)])
    step = run_command(
        key, f"Agent Investigation Tool: {action.tool_id}",
        command, [output], cwd=PROJECT_ROOT, env=env, force=force, progress=progress,
    )
    return step, [str(output)]


def _adapt_copy_move(
    action: InvestigationAction,
    workdir: Path,
    source_data_dir: Path | None,
    env: dict[str, str],
    force: bool,
    progress: Any,
    key: str,
    action_dir: Path,
    output: Path,
) -> tuple[StepResult, list[str]]:
    panel_json = resolve_artifact_path(workdir, "panel_evidence.json")
    if not panel_json.exists():
        return _skip(key, "panel_evidence.json missing.", progress)
    params = action.params
    command = [
        sys.executable, "-m",
        "engine.static_audit.tools.copy_move_detection",
        str(panel_json),
        "--figure-json", str(resolve_artifact_path(workdir, "visual_evidence.json")),
        "--output", str(output),
        "--workdir", str(workdir),
        "--method", str(params.get("method", "rootsift_magsac")),
        "--min-matches", str(params.get("min_matches", 20)),
        "--min-score", str(params.get("min_score", 0.05)),
        "--max-relationships", str(params.get("max_relationships", 500)),
    ]
    step = run_command(
        key, f"Agent Investigation Tool: {action.tool_id}",
        command, [output], cwd=PROJECT_ROOT, env=env, force=force, progress=progress,
    )
    return step, [str(output)]


def _adapt_overlap_reuse(
    action: InvestigationAction,
    workdir: Path,
    source_data_dir: Path | None,
    env: dict[str, str],
    force: bool,
    progress: Any,
    key: str,
    action_dir: Path,
    output: Path,
) -> tuple[StepResult, list[str]]:
    panels_list, figures = _load_panels_and_figures(workdir)
    if not panels_list:
        return _skip(key, "panel_evidence.json missing.", progress)
    try:
        from engine.static_audit.tools.overlap_reuse import detect_overlap_reuse

        params = action.params
        result = detect_overlap_reuse(
            panels_list,
            figures,
            workdir=workdir,
            tile_size=int(params.get("tile_size", 128)),
            tile_stride=int(params.get("tile_stride", 64)),
            max_candidate_pairs=int(params.get("max_candidate_pairs", 500)),
            min_inliers=int(params.get("min_inliers", 10)),
            min_overlap_area=float(params.get("min_overlap_area", 0.01)),
            max_relationships=int(params.get("max_relationships", 500)),
        )
    except Exception as exc:
        result = {"status": "failed", "relationships": [], "errors": [str(exc)]}
    return _direct_tool_result(result, output, key, progress)


def _adapt_sila_dense(
    action: InvestigationAction,
    workdir: Path,
    source_data_dir: Path | None,
    env: dict[str, str],
    force: bool,
    progress: Any,
    key: str,
    action_dir: Path,
    output: Path,
) -> tuple[StepResult, list[str]]:
    panels_list, figures = _load_panels_and_figures(workdir)
    if not panels_list:
        return _skip(key, "panel_evidence.json missing.", progress)
    try:
        from engine.static_audit.tools.sila_dense import detect_sila_dense

        params = action.params
        result = detect_sila_dense(
            panels_list,
            figures,
            workdir=workdir,
            min_score=float(params.get("min_score", 0.05)),
            max_relationships=int(params.get("max_relationships", 500)),
        )
    except Exception as exc:
        result = {"status": "failed", "relationships": [], "errors": [str(exc)]}
    return _direct_tool_result(result, output, key, progress)


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------

ADAPTERS: dict[str, AdapterFn] = {
    "source_data.profile": _adapt_source_data_profile,
    SOURCE_DATA_FINDINGS_TOOL_ID: _adapt_source_data_findings,
    SOURCE_DATA_PAIR_FORENSICS_TOOL_ID: _adapt_source_data_pair_forensics,
    SOURCE_DATA_CROSS_SHEET_TOOL_ID: _adapt_source_data_cross_sheet,
    IMAGE_SIMILARITY_TOOL_ID: _adapt_image_similarity,
    TOOL_ID_COPY_MOVE: _adapt_copy_move,
    TOOL_ID_OVERLAP_REUSE: _adapt_overlap_reuse,
    TOOL_ID_SILA_DENSE: _adapt_sila_dense,
}

# Default output filenames for each registered tool — used by the dispatcher
# to construct the output path before invoking the adapter.
_OUTPUT_FILENAMES: dict[str, str] = {
    "source_data.profile": "source_data_profile.json",
    SOURCE_DATA_FINDINGS_TOOL_ID: "source_data_findings.json",
    SOURCE_DATA_PAIR_FORENSICS_TOOL_ID: "source_data_pair_forensics.json",
    SOURCE_DATA_CROSS_SHEET_TOOL_ID: "source_data_cross_sheet.json",
    IMAGE_SIMILARITY_TOOL_ID: "image_similarity_candidates.json",
    TOOL_ID_COPY_MOVE: "visual_copy_move.json",
    TOOL_ID_OVERLAP_REUSE: "overlap_reuse.json",
    TOOL_ID_SILA_DENSE: "visual_copy_move_dense.json",
}


def tool_output_filename(tool_id: str) -> str:
    """Return the default output filename for a registered investigation tool."""
    return _OUTPUT_FILENAMES.get(tool_id, f"{tool_id.replace('.', '_')}.json")
