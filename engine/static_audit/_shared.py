"""Shared utilities for engine.static_audit submodules.

This module breaks the circular-dependency pattern where
investigation_dispatch.py, visual_pipeline.py, and report.py all imported
helper functions from orchestrator.py (which was becoming a God Object).

Dependency direction:
    orchestrator.py        → _shared.py
    investigation_dispatch → _shared.py
    visual_pipeline.py     → _shared.py
    report.py              → _shared.py

_shared.py only imports from:
    engine.investigation.agent_models   (PROGRESS_EVENT_SUMMARY_MAX_CHARS)
    engine.investigation.opencode_agent (DEFAULT_SOURCE_FINDING_PARAMS, source_data_findings_params_from_plan)
    engine.static_audit.investigation   (InvestigationAction, normalize_expected_evidence_type)
    engine.static_audit.paths           (artifact path contract)
    engine.tools.registry               (TOOLS and tool-id constants)

None of those modules import from _shared.py, so no cycles are formed.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project root (must be on sys.path before engine.* imports).
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AUDITOR_ROOT = PROJECT_ROOT / "third_party" / "research-integrity-auditor"
MAX_INVESTIGATION_ROUNDS = 3


# ---------------------------------------------------------------------------
# Imports from engine.* (after PROJECT_ROOT is on sys.path).
# ---------------------------------------------------------------------------
from engine.investigation.agent_models import PROGRESS_EVENT_SUMMARY_MAX_CHARS  # noqa: E402
from engine.investigation.opencode_agent import (  # noqa: E402
    DEFAULT_SOURCE_FINDING_PARAMS,
)
from engine.static_audit.investigation import (  # noqa: E402
    InvestigationAction,
    normalize_expected_evidence_type,
)
from engine.static_audit.paths import (  # noqa: E402,F401
    ARTIFACT_PATH_MAP,
    OUTPUT_DIRS,
    artifact_path_candidates,
    ensure_output_subdirs,
    existing_artifact_path,
    output_subdir,
    resolve_artifact_path,
)
from engine.tools.registry import (  # noqa: E402
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

STEP_TOOL_IDS = {
    "mineru": "mineru.parse_pdf",
    "evidence_ledger": "paper.evidence_ledger",
    "numeric_forensics": "paper.numeric_forensics",
    "paperfraud_rule_match": PAPERFRAUD_RULE_MATCH_TOOL_ID,
    "material_inventory": "material.inventory",
    "agent_material_plan": "agent.material_plan",
    "source_data_profile": "source_data.profile",
    "source_data_findings": "source_data.findings",
    "source_data_pair_forensics": "source_data.pair_forensics",
    "source_data_cross_sheet": "source_data.cross_sheet",
    "source_data_verdict": SOURCE_DATA_VERDICT_TOOL_ID,
    "exact_image_duplicates": "image.exact_duplicates",
    "image_similarity_candidates": "image.similarity_candidates",
    "visual_panel_extraction": TOOL_ID_PANEL_EXTRACTION,
    "visual_copy_move": TOOL_ID_COPY_MOVE,
    "visual_finding_pipeline": TOOL_ID_FINDING_PIPELINE,
    "visual_tru_for": TOOL_ID_TRU_FOR,
    "visual_provenance_graph": TOOL_ID_PROVENANCE_GRAPH,
    "visual_copy_move_dense": TOOL_ID_SILA_DENSE,
    "visual_image_quality": TOOL_ID_IMAGE_QUALITY,
    "agent_plan": "agent.plan",
    "agent_review": "agent.review",
    "agent_role_claim_extractor": "agent.role.claim_extractor",
    "agent_role_source_data_auditor": "agent.role.source_data_auditor",
    "agent_role_judge": "agent.role.judge",
    "static_audit_bundle": "static_audit.bundle",
    "report": "report.render_markdown",
    "html_report": "report.render_static_html",
}


def artifact_exists(workdir: Path, artifact: str) -> bool:
    cleaned = artifact.rstrip("/")
    if not cleaned:
        return False
    return any(path.exists() for path in artifact_path_candidates(workdir, cleaned))


# ---------------------------------------------------------------------------
# Step tracking types
# ---------------------------------------------------------------------------
@dataclass
class StepResult:
    key: str
    title: str
    status: str
    detail: str
    command: list[str] | None = None


ProgressCallback = Callable[[dict[str, Any]], None]


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
# Command execution
# ---------------------------------------------------------------------------
def exists_all(paths: list[Path]) -> bool:
    return all(path.exists() for path in paths)


def text_tail(value: str, limit: int = 1000) -> str:
    value = value.strip()
    if not value:
        return ""
    return value[-limit:]


def run_command(
    key: str,
    title: str,
    command: list[str],
    expected_outputs: list[Path],
    *,
    cwd: Path,
    env: dict[str, str],
    force: bool,
    attempts: int = 1,
    retry_delay_seconds: float = 0.0,
    progress: ProgressCallback | None = None,
    stream_output: bool = False,
) -> StepResult:
    if expected_outputs and exists_all(expected_outputs) and not force:
        result = StepResult(
            key=key,
            title=title,
            status="reused",
            detail="Expected outputs already exist.",
            command=command,
        )
        emit_step_result(progress, result)
        return result

    last_detail = ""
    attempts = max(1, attempts)
    emit_step_start(progress, key, title, "Running deterministic command.", command)
    for attempt in range(1, attempts + 1):
        emit_progress(
            progress,
            "step_attempt",
            key=key,
            title=title,
            attempt=attempt,
            attempts=attempts,
            command_preview=command_preview(command),
        )
        if stream_output and progress is not None:
            completed = run_command_streaming(
                key=key,
                title=title,
                command=command,
                cwd=cwd,
                env=env,
                progress=progress,
            )
        else:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        if completed.returncode != 0:
            last_detail = (
                f"attempt={attempt}/{attempts} exit_code={completed.returncode}"
            )
            if completed.stderr:
                last_detail += f" stderr_tail={completed.stderr[-1000:]!r}"
            stdout_tail = text_tail(completed.stdout)
            if stdout_tail:
                last_detail += f" stdout_tail={stdout_tail!r}"
            if attempt < attempts and retry_delay_seconds > 0:
                delay = retry_delay_seconds * attempt
                emit_progress(
                    progress,
                    "command_output",
                    key=key,
                    title=title,
                    line=f"retrying after {delay:.0f}s because previous attempt failed",
                    command_preview=command_preview(command),
                )
                time.sleep(delay)
            continue
        if expected_outputs and not exists_all(expected_outputs):
            missing = [str(path) for path in expected_outputs if not path.exists()]
            last_detail = f"attempt={attempt}/{attempts} command succeeded but outputs missing: {missing}"
            stdout_tail = text_tail(completed.stdout)
            if stdout_tail:
                last_detail += f" stdout_tail={stdout_tail!r}"
            if attempt < attempts and retry_delay_seconds > 0:
                delay = retry_delay_seconds * attempt
                emit_progress(
                    progress,
                    "command_output",
                    key=key,
                    title=title,
                    line=f"retrying after {delay:.0f}s because expected outputs were missing",
                    command_preview=command_preview(command),
                )
                time.sleep(delay)
            continue
        detail = "Command completed successfully."
        if attempt > 1:
            detail = f"Command completed successfully after {attempt} attempts."
        result = StepResult(key, title, "ran", detail, command)
        emit_step_result(progress, result)
        return result
    result = StepResult(key, title, "failed", last_detail, command)
    emit_step_result(progress, result)
    return result


def run_command_streaming(
    *,
    key: str,
    title: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    progress: ProgressCallback,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            output_lines.append(line)
            emit_progress(
                progress,
                "command_output",
                key=key,
                title=title,
                line=line[-500:],
                command_preview=command_preview(command),
            )
    return_code = process.wait()
    return subprocess.CompletedProcess(
        command, return_code, "\n".join(output_lines), ""
    )


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_artifact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def fmt_int(value: Any) -> str:
    return "-" if value is None else str(value)


def fmt_float(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report row builders
# ---------------------------------------------------------------------------
def priority_row(finding: dict[str, Any]) -> list[str]:
    relation = finding.get("relationship_value")
    if relation is not None:
        relation_text = f"{finding.get('category')}={relation}"
    else:
        relation_text = finding.get("category", "-")
    support = finding.get("support_rows") or finding.get("equal_rows")
    overlap = finding.get("overlap_rows")
    support_text = f"{support}/{overlap}" if support and overlap else fmt_int(support)
    # Append pattern_strength if available
    pattern_strength = finding.get("pattern_strength")
    if pattern_strength:
        support_text = f"{support_text} ({pattern_strength})"
    return [
        finding.get("finding_id", "-"),
        finding.get("risk_level", "-"),
        finding.get("workbook", "-"),
        finding.get("sheet", "-"),
        ", ".join(finding.get("column_pair") or []),
        relation_text,
        support_text,
    ]


def claim_mapping_rows(
    mappings: list[dict[str, Any]], limit: int = 12
) -> list[list[str]]:
    rows = []
    for mapping in mappings[:limit]:
        linked = mapping.get("linked_priority_findings") or []
        claim = "-"
        claims = mapping.get("candidate_claims") or []
        if claims:
            claim = claims[0].get("text", "-")[:160]
        rows.append(
            [
                mapping.get("mapping_id", "-"),
                mapping.get("source_figure_id", "-"),
                mapping.get("workbook", "-"),
                mapping.get("sheet", "-"),
                mapping.get("review_priority", "-"),
                ", ".join(item.get("finding_id", "-") for item in linked) or "-",
                claim,
            ]
        )
    return rows


def pair_forensics_rows(
    findings: list[dict[str, Any]], limit: int = 12
) -> list[list[str]]:
    rows = []
    for finding in findings[:limit]:
        support = (
            finding.get("support_rows")
            or finding.get("matched_pairs")
            or finding.get("matched_pair_groups")
            or finding.get("duplicate_row_count")
            or finding.get("exact_reuse_pairs")
            or "-"
        )
        overlap = (
            finding.get("overlap_rows")
            or finding.get("overlap_pairs")
            or finding.get("overlap_pair_groups")
            or "-"
        )
        columns = (
            finding.get("columns")
            or finding.get("column_pair")
            or finding.get("column")
            or []
        )
        if isinstance(columns, list):
            columns_text = ", ".join(str(item) for item in columns)
        else:
            columns_text = str(columns)
        rows.append(
            [
                finding.get("finding_id", "-"),
                finding.get("risk_level", "-"),
                finding.get("category", "-"),
                finding.get("workbook", "-"),
                finding.get("sheet", "-"),
                finding.get("row_offset") or finding.get("pair_id_offset") or "-",
                columns_text or "-",
                f"{support}/{overlap}",
            ]
        )
    return rows


def pair_forensics_cluster_rows(
    clusters: list[dict[str, Any]], limit: int = 12
) -> list[list[str]]:
    rows = []
    for cluster in clusters[:limit]:
        rows.append(
            [
                cluster.get("cluster_id", "-"),
                cluster.get("risk_level", "-"),
                cluster.get("category", "-"),
                cluster.get("workbook", "-"),
                cluster.get("sheet", "-"),
                cluster.get("pattern_signature", "-"),
                fmt_int(cluster.get("finding_count")),
                ", ".join(
                    str(item)
                    for item in (cluster.get("representative_finding_ids") or [])[:5]
                )
                or "-",
            ]
        )
    return rows


def pair_forensics_review_task_rows(
    tasks: list[dict[str, Any]], limit: int = 12
) -> list[list[str]]:
    rows = []
    for task in tasks[:limit]:
        rows.append(
            [
                task.get("task_id", "-"),
                task.get("priority", "-"),
                task.get("cluster_id", "-"),
                task.get("category", "-"),
                task.get("workbook", "-"),
                task.get("sheet", "-"),
                fmt_int(task.get("cluster_count")),
                fmt_int(task.get("finding_count")),
                str(task.get("question", "-"))[:220],
            ]
        )
    return rows


def canonical_claim_mapping_rows(
    claims: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    limit: int = 12,
) -> list[list[str]]:
    claim_by_id = {
        str(claim.get("claim_id")): claim for claim in claims if claim.get("claim_id")
    }
    rows = []
    for mapping in mappings[:limit]:
        claim = claim_by_id.get(str(mapping.get("claim_id"))) or {}
        metadata = (
            mapping.get("metadata") if isinstance(mapping.get("metadata"), dict) else {}
        )
        source_refs = (
            metadata.get("source_data_refs") or mapping.get("evidence_refs") or []
        )
        rows.append(
            [
                mapping.get("mapping_id", "-"),
                mapping.get("claim_id", "-"),
                str(claim.get("text", "-"))[:180],
                mapping.get("confidence", "-"),
                mapping.get("status", "-"),
                ", ".join(str(ref) for ref in source_refs[:4]) or "-",
            ]
        )
    return rows


# ---------------------------------------------------------------------------
# Investigation helpers
# ---------------------------------------------------------------------------
def agent_step_status(status: str) -> str:
    return "ran" if status == "ok" else "warning"


def safe_action_dir_name(action_id: str) -> str:
    return (
        "".join(ch.lower() if ch.isalnum() else "_" for ch in action_id).strip("_")
        or "action"
    )


def investigation_action_from_dict(
    round_id: int, action: dict[str, Any]
) -> InvestigationAction:
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
    return source_data_findings_params_from_plan(plan)


def source_finding_params_from_lane(lane: dict[str, Any] | None) -> dict[str, Any]:
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
