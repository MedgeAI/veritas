"""Shared helper functions for Veritas audit engine.

This module contains utility functions used across engine.static_audit and
engine.investigation modules.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.investigation.agent_models import PROGRESS_EVENT_SUMMARY_MAX_CHARS
from engine.investigation.validators import DEFAULT_SOURCE_FINDING_PARAMS
from engine.shared.constants import ARTIFACT_PATH_MAP, OUTPUT_DIRS
from engine.shared.types import InvestigationAction, ProgressCallback, StepResult
from engine.static_audit.paths import (
    artifact_path_candidates,
    existing_artifact_path,
    resolve_artifact_path,
)

# ---------------------------------------------------------------------------
# Expected evidence types for investigation actions
# ---------------------------------------------------------------------------
EXPECTED_EVIDENCE_TYPES = {
    "material_gap",
    "figure_mapping",
    "numeric_pattern",
    "image_similarity",
    "claim_mapping",
    "source_data_pattern",
}


def normalize_expected_evidence_type(value: str) -> str:
    """Normalize evidence type to one of the expected types.

    Args:
        value: The evidence type to normalize.

    Returns:
        One of EXPECTED_EVIDENCE_TYPES if valid, otherwise "source_data_pattern".
    """
    value = str(value or "").strip()
    if value in EXPECTED_EVIDENCE_TYPES:
        return value
    return "source_data_pattern"
from engine.tools.registry import (
    PAPERFRAUD_RULE_MATCH_TOOL_ID,
    SOURCE_DATA_VERDICT_TOOL_ID,
    TOOLS,
    TOOL_ID_COPY_MOVE,
    TOOL_ID_FINDING_PIPELINE,
    TOOL_ID_IMAGE_QUALITY,
    TOOL_ID_PANEL_EXTRACTION,
    TOOL_ID_PROVENANCE_GRAPH,
    TOOL_ID_SILA_DENSE,
    TOOL_ID_TRU_FOR,
    source_data_findings_params_from_plan,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON file and return its contents, or None if file doesn't exist."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_artifact(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON artifact to disk, creating parent directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Artifact path helpers
# ---------------------------------------------------------------------------
def artifact_exists(workdir: Path, artifact: str) -> bool:
    """Check if an artifact exists in the workdir."""
    cleaned = artifact.rstrip("/")
    if not cleaned:
        return False
    return any(path.exists() for path in artifact_path_candidates(workdir, cleaned))


# ---------------------------------------------------------------------------
# Progress / event emission
# ---------------------------------------------------------------------------
# Keys that must never appear in a progress event sent to the Web stream.
_STRIP_KEYS = ("stdout", "stderr", "traceback", "full_output")


def _write_long_text_to_log(workdir: Path, step_key: str, text: str) -> str | None:
    """Write long text to a log artifact and return the relative path (log_ref).

    Returns None if text is empty.
    Creates agents/logs/ directory under workdir if needed.
    """
    if not text:
        return None
    logs_dir = resolve_artifact_path(workdir, "logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{step_key}_{ts}.log"
    log_path = logs_dir / filename
    log_path.write_text(text, encoding="utf-8")
    # Return path relative to workdir for portability.
    return str(log_path.relative_to(workdir))


def enforce_event_contract(
    event: dict[str, Any], workdir: Path | None = None
) -> dict[str, Any]:
    """Enforce the ProgressEvent contract on a raw event dict.

    - Truncates ``detail`` / ``summary`` to ``PROGRESS_EVENT_SUMMARY_MAX_CHARS``.
    - Writes overflow text to a log artifact when *workdir* is provided.
    - Sets ``log_ref`` for failed events whose detail was truncated.
    - Strips keys that must never reach the Web event stream.
    - Emits both ``detail`` (backward compat) and ``summary`` (alias).

    Returns the cleaned event dict (mutates *event* in place as well).
    """
    # --- Strip forbidden keys ------------------------------------------------
    for key in _STRIP_KEYS:
        event.pop(key, None)

    # --- Determine the text payload ------------------------------------------
    raw_text = str(event.get("detail", "") or "")
    step_key = str(event.get("key", event.get("step", "unknown")))
    max_chars = PROGRESS_EVENT_SUMMARY_MAX_CHARS

    # --- Truncate and optionally spill to log --------------------------------
    log_ref: str | None = event.get("log_ref")  # preserve if already set
    if len(raw_text) > max_chars:
        summary = raw_text[:max_chars]
        if workdir is not None:
            log_ref = _write_long_text_to_log(workdir, step_key, raw_text)
    else:
        summary = raw_text

    event["detail"] = summary
    event["summary"] = summary
    if log_ref is not None:
        event["log_ref"] = log_ref

    # --- Failed events should always have a log_ref when possible ------------
    if (
        event.get("status") == "failed"
        and log_ref is None
        and workdir is not None
        and summary
    ):
        log_ref = _write_long_text_to_log(workdir, step_key, summary)
        event["log_ref"] = log_ref

    return event


def emit_progress(
    progress: ProgressCallback | None,
    event: str,
    workdir: Path | None = None,
    **payload: Any,
) -> None:
    """Emit a progress event to the callback if provided."""
    if progress is None:
        return
    raw_event: dict[str, Any] = {
        "event": event,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **payload,
    }
    enforce_event_contract(raw_event, workdir=workdir)
    progress(raw_event)


def command_preview(command: list[str] | None) -> str | None:
    """Generate a preview string for a command."""
    if not command:
        return None
    if (
        len(command) >= 2
        and Path(command[0]).name == "opencode"
        and command[1] == "run"
    ):
        model = None
        if "--model" in command:
            index = command.index("--model")
            if index + 1 < len(command):
                model = command[index + 1]
        return f"opencode run --format json --model {model or '<unknown>'} ..."
    preview = [
        Path(part).name if index == 0 else part
        for index, part in enumerate(command[:6])
    ]
    suffix = " ..." if len(command) > 6 else ""
    return " ".join(preview) + suffix


def emit_step_start(
    progress: ProgressCallback | None,
    key: str,
    title: str,
    detail: str = "",
    command: list[str] | None = None,
    workdir: Path | None = None,
) -> None:
    """Emit a step_start progress event."""
    emit_progress(
        progress,
        "step_start",
        workdir=workdir,
        key=key,
        title=title,
        status="running",
        detail=detail,
        command_preview=command_preview(command),
    )


def emit_step_result(
    progress: ProgressCallback | None,
    step: StepResult,
    workdir: Path | None = None,
) -> None:
    """Emit a step_result progress event."""
    emit_progress(
        progress,
        "step_result",
        workdir=workdir,
        key=step.key,
        title=step.title,
        status=step.status,
        detail=step.detail,
        command_preview=command_preview(step.command),
    )


def record_step(
    steps: list[StepResult],
    step: StepResult,
    progress: ProgressCallback | None,
    workdir: Path | None = None,
) -> StepResult:
    """Record a step result and emit progress event."""
    steps.append(step)
    log_fn = logger.info if step.status in ("ran", "reused") else logger.warning
    log_fn(
        "pipeline step [%s] %s — %s (%s)",
        step.key,
        step.title,
        step.status,
        step.detail[:120],
    )
    emit_step_result(progress, step, workdir=workdir)
    return step


# ---------------------------------------------------------------------------
# Investigation helpers
# ---------------------------------------------------------------------------
def agent_step_status(status: str) -> str:
    """Convert agent step status to pipeline step status."""
    return "ran" if status == "ok" else "warning"


def safe_action_dir_name(action_id: str) -> str:
    """Generate a safe directory name from an action ID."""
    return (
        "".join(ch.lower() if ch.isalnum() else "_" for ch in action_id).strip("_")
        or "action"
    )


def investigation_action_from_dict(
    round_id: int, action: dict[str, Any]
) -> InvestigationAction:
    """Create an InvestigationAction from a dictionary."""
    tool_id = str(action.get("tool_id"))
    # Get output_artifacts from tool registry if available
    tool_def = TOOLS.get(tool_id)
    output_artifacts = (
        list(tool_def.output_artifacts)
        if tool_def and tool_def.output_artifacts
        else []
    )
    return InvestigationAction(
        round_id=round_id,
        action_id=str(action.get("action_id") or f"IR-{round_id:02d}-A001"),
        tool_id=tool_id,
        params=action.get("params") if isinstance(action.get("params"), dict) else {},
        hypothesis=str(action.get("hypothesis") or ""),
        depends_on_artifacts=[
            str(item) for item in (action.get("depends_on_artifacts") or [])
        ],
        expected_evidence_type=normalize_expected_evidence_type(
            str(action.get("expected_evidence_type") or "")
        ),
        stop_if_no_new_evidence=bool(action.get("stop_if_no_new_evidence", True)),
        output_artifacts=output_artifacts,
    )


# ---------------------------------------------------------------------------
# Source data helpers
# ---------------------------------------------------------------------------
def source_finding_params_from_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Get source finding parameters from a plan."""
    return source_data_findings_params_from_plan(plan)


def source_finding_params_from_lane(lane: dict[str, Any] | None) -> dict[str, Any]:
    """Get source finding parameters from a lane."""
    params = dict(DEFAULT_SOURCE_FINDING_PARAMS)
    if not lane:
        return params
    lane_params = lane.get("params")
    if not isinstance(lane_params, dict):
        return params
    source_params = lane_params.get("source_data_findings")
    if isinstance(source_params, dict):
        for key in params:
            if key in source_params:
                params[key] = source_params[key]
    return params


# ---------------------------------------------------------------------------
# Finding layer classification (PRD2-T7)
# ---------------------------------------------------------------------------
# Categories that are always informational (Layer 3), regardless of risk_level.
_LAYER3_CATEGORIES = frozenset({
    "duplicate_row_vector",
    "paperfraud.methodology_review",
})

# Tokens that identify Paperconan/numeric-forensics findings.
# Paperconan HIGH-risk goes to Layer 2, not Layer 1 (per PRD section 5).
_PAPERCONAN_TOKENS = ("paperfraud", "numeric_forensics", "benford", "digit")


def classify_finding(finding: dict[str, Any]) -> str:
    """Classify a finding into one of three report layers.

    Layer assignment rules (PRD section 5):
        Layer 1 (high confidence): risk_level in {critical, high},
            except duplicate_row_vector and paperfraud.methodology_review.
        Layer 2 (needs human judgment): risk_level == medium,
            OR high-risk paperfraud/numeric-forensics findings.
        Layer 3 (informational): risk_level in {low, info, context},
            OR duplicate_row_vector, OR paperfraud.methodology_review.

    Args:
        finding: A finding dict with at least 'risk_level' and optionally
            'category' and 'source_artifact' keys.

    Returns:
        One of 'layer_1', 'layer_2', or 'layer_3'.
    """
    risk_level = str(finding.get("risk_level") or "medium").lower()
    category = str(finding.get("category") or "").lower()
    source_artifact = str(finding.get("source_artifact") or "").lower()

    # Duplicate row vectors and methodology review are always Layer 3
    if category in _LAYER3_CATEGORIES:
        return "layer_3"

    # Check if this is a Paperconan/numeric-forensics finding
    is_paperconan = any(
        token in category or token in source_artifact
        for token in _PAPERCONAN_TOKENS
    )

    if risk_level in ("critical", "high"):
        # Paperconan HIGH-risk goes to Layer 2 (per PRD section 5)
        if is_paperconan:
            return "layer_2"
        return "layer_1"

    if risk_level == "medium":
        return "layer_2"

    # low, info, context
    return "layer_3"


def filter_judge_input(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter findings for Judge input: only Layer 1 + Layer 2.

    Filters out:
    - Layer 3 findings (DRV, Paperconan MEDIUM/LOW, TruFor LOW)
    - PaperFraud methodology findings (Wave 2 removed, verified here)
    - Metadata column cross-sheet findings (Wave 3 filtered, verified here)

    Args:
        findings: List of finding dicts from various audit artifacts.

    Returns:
        Filtered list containing only Layer 1 + Layer 2 findings,
        annotated with ``_layer`` for transparency.
    """
    if not findings:
        return []

    filtered = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        layer = classify_finding(finding)
        if layer in ("layer_1", "layer_2"):
            annotated = dict(finding)
            annotated["_layer"] = layer
            filtered.append(annotated)

    return filtered
