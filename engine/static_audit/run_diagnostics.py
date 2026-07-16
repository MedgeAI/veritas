from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.shared import PROJECT_ROOT
from engine.static_audit._shared import read_json, resolve_artifact_path, write_json_artifact

try:
    from scripts.prod_diagnose import redact_text, truncate_text
except ImportError:  # pragma: no cover - scripts package is available in repo runs.
    def redact_text(value: str) -> str:
        return value

    def truncate_text(value: str, limit: int = 12000) -> str:
        return value[:limit]


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_load(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _rel(workdir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workdir))
    except ValueError:
        return str(path)


def _artifact_info(workdir: Path, artifact_name: str) -> dict[str, Any]:
    path = resolve_artifact_path(workdir, artifact_name)
    info: dict[str, Any] = {
        "path": _rel(workdir, path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }
    data = _safe_load(path)
    if isinstance(data, dict):
        for key in (
            "status",
            "finding_count",
            "relationship_count",
            "review_queue_count",
            "panel_count",
            "figure_count",
        ):
            if key in data:
                info[key] = data.get(key)
        summary = data.get("summary")
        if isinstance(summary, dict):
            info["summary"] = {
                key: summary.get(key)
                for key in sorted(summary)
                if isinstance(summary.get(key), str | int | float | bool | type(None))
            }
    return info


def _manifest_agent_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    agent = manifest.get("agent") if isinstance(manifest.get("agent"), dict) else {}
    entries: list[dict[str, Any]] = []
    for key, value in agent.items():
        if key == "roles" and isinstance(value, list):
            for role in value:
                if isinstance(role, dict):
                    item = dict(role)
                    item.setdefault("agent_step", f"agent_role_{role.get('role_id')}")
                    entries.append(item)
        elif isinstance(value, dict):
            item = dict(value)
            item.setdefault("agent_step", f"agent_{key}")
            entries.append(item)
    return entries


def _collect_agent_debug(workdir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    entries = _manifest_agent_entries(manifest)
    logs_dir = resolve_artifact_path(workdir, "logs")
    validation_files = sorted(logs_dir.glob("*.validation.json")) if logs_dir.exists() else []
    validations = []
    for path in validation_files[-30:]:
        payload = _safe_load(path)
        if isinstance(payload, dict):
            payload["path"] = _rel(workdir, path)
            if payload.get("last_detail"):
                payload["last_detail"] = truncate_text(
                    redact_text(str(payload["last_detail"])), 1200
                )
            validations.append(payload)

    debug_entries: list[dict[str, Any]] = []
    for entry in entries:
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        failure_type = metadata.get("failure_type")
        detail = str(entry.get("detail") or metadata.get("last_detail") or "")
        if not failure_type and "timed out" in detail.lower():
            failure_type = "timeout"
        if entry.get("status") in {"failed", "warning"} or failure_type:
            debug_entries.append(
                {
                    "agent_step": entry.get("agent_step"),
                    "role_id": entry.get("role_id"),
                    "status": entry.get("status"),
                    "failure_type": failure_type,
                    "timeout_seconds": metadata.get("timeout_seconds"),
                    "detail": truncate_text(redact_text(detail), 1200),
                    "retry_attempts": entry.get("retries")
                    or metadata.get("repair_attempts"),
                    "raw_output_path": metadata.get("raw_output_path"),
                    "validation_error_path": metadata.get("validation_error_path"),
                    "repair_history": metadata.get("repair_history") or [],
                    "suggested_action": _agent_suggested_action(
                        str(entry.get("role_id") or entry.get("agent_step") or ""),
                        str(failure_type or ""),
                    ),
                }
            )

    return {
        "schema_version": "agent_debug.v1",
        "generated_at": _utc_now(),
        "agents": debug_entries,
        "validation_artifacts": validations,
    }


def _agent_suggested_action(role: str, failure_type: str) -> str | None:
    if failure_type == "timeout" and "source_data_auditor" in role:
        return "reduce_context_pack_to_review_tasks"
    if failure_type == "timeout":
        return "increase_role_timeout_or_reduce_context"
    if failure_type == "schema_validation":
        return "inspect_raw_output_and_schema_error"
    if failure_type:
        return "inspect_agent_trace_and_retry"
    return None


def _collect_quality_flags(
    workdir: Path,
    manifest: dict[str, Any],
    agent_debug: dict[str, Any],
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for step in manifest.get("steps") or []:
        if not isinstance(step, dict):
            continue
        status = str(step.get("status") or "")
        if status in {"failed", "warning", "degraded"}:
            flags.append(
                {
                    "flag": "step_not_clean",
                    "severity": "high" if status == "failed" else "medium",
                    "step": step.get("key") or step.get("id"),
                    "detail": truncate_text(redact_text(str(step.get("detail") or "")), 600),
                    "action": "inspect_step_artifacts",
                }
            )

    for item in agent_debug.get("agents") or []:
        if item.get("failure_type") == "timeout":
            flags.append(
                {
                    "flag": "agent_timeout",
                    "severity": "medium",
                    "step": item.get("agent_step"),
                    "action": item.get("suggested_action")
                    or "increase_role_timeout_or_reduce_context",
                }
            )
        elif item.get("failure_type") == "schema_validation":
            flags.append(
                {
                    "flag": "agent_schema_failure",
                    "severity": "medium",
                    "step": item.get("agent_step"),
                    "action": "inspect_raw_output_and_schema_error",
                }
            )

    panel_quality = read_json(resolve_artifact_path(workdir, "panel_extraction_quality.json")) or {}
    panel_summary = panel_quality.get("summary") if isinstance(panel_quality, dict) else {}
    if isinstance(panel_summary, dict):
        fallback_rate = float(panel_summary.get("fallback_rate") or 0)
        if fallback_rate >= 1:
            flags.append(
                {
                    "flag": "panel_extraction_all_fallback",
                    "severity": "high",
                    "step": "visual_panel_extraction",
                    "action": "inspect panel_extraction_quality.json",
                }
            )
        elif fallback_rate > 0.8:
            flags.append(
                {
                    "flag": "panel_extraction_degraded",
                    "severity": "medium",
                    "step": "visual_panel_extraction",
                    "action": "inspect panel_extraction_quality.json",
                }
            )

    provenance_filter = read_json(resolve_artifact_path(workdir, "provenance_edge_filtered.json")) or {}
    if (
        isinstance(provenance_filter, dict)
        and (provenance_filter.get("total_edges") or 0) > 0
        and (provenance_filter.get("emitted_findings") or 0) == 0
    ):
        flags.append(
            {
                "flag": "provenance_edges_filtered",
                "severity": "medium",
                "step": "visual_finding_pipeline",
                "action": "review provenance_edge_threshold in configs/audit_roles.yaml",
            }
        )

    verdict = read_json(resolve_artifact_path(workdir, "source_data_findings_verdict.json")) or {}
    failed_sheets = (verdict.get("summary") or {}).get("failed_sheets") if isinstance(verdict, dict) else 0
    if failed_sheets:
        flags.append(
            {
                "flag": "source_data_verdict_failed_sheets",
                "severity": "medium",
                "step": "source_data_verdict",
                "action": "inspect source_data/findings_verdict.json",
            }
        )
    return flags


def _collect_performance(workdir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    agent_entries = _manifest_agent_entries(manifest)
    agent_runtime = [
        {
            "agent_step": entry.get("agent_step"),
            "role_id": entry.get("role_id"),
            "runtime_seconds": entry.get("runtime_seconds"),
            "status": entry.get("status"),
        }
        for entry in agent_entries
        if entry.get("runtime_seconds") is not None
    ]
    panel_quality = read_json(resolve_artifact_path(workdir, "panel_extraction_quality.json")) or {}
    return {
        "schema_version": "performance.v1",
        "agent_runtime": sorted(
            agent_runtime,
            key=lambda item: float(item.get("runtime_seconds") or 0),
            reverse=True,
        ),
        "panel_extraction": (panel_quality.get("summary") or {})
        if isinstance(panel_quality, dict)
        else {},
        "llm_enrichment": manifest.get("llm_enrichment") or {},
        "step_count": len(manifest.get("steps") or []),
    }


def _collect_model_calls(workdir: Path) -> dict[str, Any]:
    logs_dir = resolve_artifact_path(workdir, "logs")
    traces = sorted(logs_dir.glob("step_trace_*.json")) if logs_dir.exists() else []
    calls = []
    for path in traces[-50:]:
        trace = _safe_load(path)
        if not isinstance(trace, dict):
            continue
        token_usage = trace.get("token_usage") or {}
        calls.append(
            {
                "path": _rel(workdir, path),
                "role": trace.get("role"),
                "status": trace.get("status"),
                "model": trace.get("model"),
                "runtime_seconds": trace.get("runtime_seconds"),
                "token_usage": {
                    "total": token_usage.get("total"),
                    "input": token_usage.get("input"),
                    "output": token_usage.get("output"),
                    "reasoning": token_usage.get("reasoning"),
                }
                if isinstance(token_usage, dict)
                else {},
            }
        )
    return {"schema_version": "model_calls.v1", "calls": calls}


def _recommended_actions(flags: list[dict[str, Any]]) -> str:
    lines = ["# Recommended Next Actions", ""]
    if not flags:
        lines.append("- No diagnostic quality flags were emitted.")
        return "\n".join(lines) + "\n"
    for flag in flags[:20]:
        lines.append(
            f"- `{flag.get('flag')}` at `{flag.get('step')}`: {flag.get('action')}"
        )
    return "\n".join(lines) + "\n"


def build_run_diagnostics(
    workdir: Path,
    *,
    case_id: str | None = None,
    run_id: str | None = None,
    manifest: dict[str, Any] | None = None,
    mirror_to_web_data: bool = True,
) -> dict[str, Any]:
    """Build per-run diagnostics under outputs/<case>/.../diagnostics/."""
    manifest = manifest or read_json(resolve_artifact_path(workdir, "audit_run_manifest.json")) or {}
    case_id = case_id or str(manifest.get("case_id") or workdir.parent.name)
    run_id = run_id or manifest.get("run_id")

    artifact_summary = {
        "schema_version": "artifact_summary.v1",
        "artifacts": {
            name: _artifact_info(workdir, name)
            for name in [
                "source_data_findings.json",
                "source_data_pair_forensics.json",
                "source_data_findings_verdict.json",
                "panel_extraction_quality.json",
                "provenance_graph.json",
                "provenance_edge_filtered.json",
                "visual_relationship_findings.json",
                "visual_findings.json",
                "static_audit_bundle.json",
                "audit_run_manifest.json",
            ]
        },
    }
    agent_debug = _collect_agent_debug(workdir, manifest)
    flags = _collect_quality_flags(workdir, manifest, agent_debug)
    run_quality = {
        "schema_version": "veritas_run_diagnostics.v1",
        "case_id": case_id,
        "run_id": run_id,
        "generated_at": _utc_now(),
        "status": "completed_with_warnings" if flags else "completed",
        "quality_flags": flags,
        "artifact_summary": artifact_summary["artifacts"],
    }
    performance = _collect_performance(workdir, manifest)
    model_calls = _collect_model_calls(workdir)

    paths = {
        "agent_debug": resolve_artifact_path(workdir, "agent_debug.json"),
        "run_quality": resolve_artifact_path(workdir, "run_quality.json"),
        "artifact_summary": resolve_artifact_path(workdir, "artifact_summary.json"),
        "performance": resolve_artifact_path(workdir, "performance.json"),
        "model_calls": resolve_artifact_path(workdir, "model_calls.json"),
        "latest": resolve_artifact_path(workdir, "run_diagnostics.json"),
    }
    write_json_artifact(paths["agent_debug"], agent_debug)
    write_json_artifact(paths["run_quality"], run_quality)
    write_json_artifact(paths["artifact_summary"], artifact_summary)
    write_json_artifact(paths["performance"], performance)
    write_json_artifact(paths["model_calls"], model_calls)

    actions_path = resolve_artifact_path(workdir, "recommended_next_actions.md")
    actions_path.parent.mkdir(parents=True, exist_ok=True)
    actions_path.write_text(_recommended_actions(flags), encoding="utf-8")

    latest = {
        **run_quality,
        "agent_debug": agent_debug,
        "performance": performance,
        "model_calls": model_calls,
        "recommended_next_actions": _rel(workdir, actions_path),
    }
    write_json_artifact(paths["latest"], latest)

    if mirror_to_web_data:
        web_diag_dir = PROJECT_ROOT / "web_data" / "diagnostics"
        try:
            web_diag_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(paths["latest"], web_diag_dir / "latest.json")
            shutil.copyfile(actions_path, web_diag_dir / "latest.md")
        except OSError:
            pass

    return {
        "status": run_quality["status"],
        "quality_flags": flags,
        "paths": {key: str(path) for key, path in paths.items()},
        "recommended_next_actions": str(actions_path),
    }
