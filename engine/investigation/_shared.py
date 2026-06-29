from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.investigation.agent_models import (
    AgentRunResult as _NewAgentRunResult,
)
from engine.investigation.agent_step_runner import AgentStepRunner
from engine.investigation.context_pack import AgentContextPack
from engine.investigation.validators import extract_json
from engine.shared import resolve_artifact_path


@dataclass
class AgentRunResult:
    status: str
    data: dict[str, Any] | None
    detail: str
    command: list[str]
    runtime_seconds: float
    retries: int = 0


def write_agent_result(path: Path, result: AgentRunResult, fallback_kind: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        result.data
        if result.data is not None
        else {
            "schema_version": "1.0",
            "status": "failed",
            "kind": fallback_kind,
            "detail": result.detail,
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def result_metadata(result: AgentRunResult, output_path: Path) -> dict[str, Any]:
    return {
        "status": result.status,
        "detail": result.detail,
        "runtime_seconds": round(result.runtime_seconds, 3),
        "retries": result.retries,
        "command": result.command,
        "output": str(output_path),
    }


def _convert_runner_result(
    new_result: _NewAgentRunResult,
    expected: str,
) -> AgentRunResult:
    """Convert new AgentStepRunner result to legacy AgentRunResult format.

    This adapter enables the Phase 2 migration: the orchestrator still
    consumes the legacy AgentRunResult, while internally we use
    AgentStepRunner for structured error classification.

    PRD3-T7: When error_category is grounding_failure but deterministic evidence
    is intact, status becomes "ok" with grounding metadata embedded in output,
    allowing the audit run to continue with needs_review status instead of failing.
    """
    status = "ok" if new_result.status == "success" else "failed"
    grounding_info = new_result.metadata.get("grounding")

    # PRD3-T7: Grounding failure doesn't fail the audit run if deterministic
    # evidence is intact. Mark status as "ok" but embed grounding info.
    if (
        status == "failed"
        and new_result.error_category == "grounding_failure"
        and grounding_info
        and new_result.output is not None
    ):
        status = "ok"
        detail = f"opencode {expected} ok with grounding warning"
        # Inject grounding info into output so review artifact can render it
        output_with_grounding = dict(new_result.output)
        output_with_grounding["status"] = "needs_review"
        output_with_grounding["grounding"] = grounding_info
        return AgentRunResult(
            status=status,
            data=output_with_grounding,
            detail=detail,
            command=[],
            runtime_seconds=new_result.runtime_seconds,
            retries=max(new_result.metadata.get("attempts", 1) - 1, 0),
        )

    if status == "ok":
        detail = f"opencode {expected} ok"
    else:
        category = new_result.error_category or "non_zero_exit"
        detail = f"opencode {expected} failed: {category}"
        if new_result.metadata.get("last_detail"):
            detail += f": {new_result.metadata['last_detail']}"
    return AgentRunResult(
        status=status,
        data=new_result.output,
        detail=detail,
        command=[],
        runtime_seconds=new_result.runtime_seconds,
        retries=max(new_result.metadata.get("attempts", 1) - 1, 0),
    )


def _run_with_context_pack(
    *,
    role: str,
    prompt: str,
    context_pack: AgentContextPack,
    expected: str,
    workdir: Path,
    project_root: Path,
    env: dict[str, str],
    model: str,
    opencode_bin: str,
    timeout_seconds: int,
    max_retries: int,
    validator: Any,
) -> AgentRunResult:
    """Run opencode via AgentStepRunner with bounded context pack.

    Replaces the ad-hoc --file argument pattern with structured context
    packs that enforce token budgets. The result is converted back to
    the legacy AgentRunResult format for orchestrator compatibility.
    """
    context_pack_path = resolve_artifact_path(workdir, f"context_pack_{role}.json")
    context_pack_path.parent.mkdir(parents=True, exist_ok=True)
    context_pack_path.write_bytes(context_pack.to_json_bytes())

    runner = AgentStepRunner(
        project_root=project_root,
        model=model,
        opencode_bin=opencode_bin,
        env=dict(env),
    )

    log_dir = workdir / "logs"
    new_result = runner.run(
        role=role,
        prompt=prompt,
        output_validator=validator,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        context_pack_path=context_pack_path,
        log_dir=log_dir,
        workdir=workdir,
    )

    return _convert_runner_result(new_result, expected)


def _run_opencode_json(
    *,
    prompt: str,
    expected: str,
    project_root: Path,
    env: dict[str, str],
    model: str,
    opencode_bin: str,
    timeout_seconds: int,
    max_retries: int,
    validator: Any,
    files: list[Path] | None = None,
) -> AgentRunResult:
    command = [
        opencode_bin,
        "run",
        prompt,
        "--format",
        "json",
        "--model",
        model,
        "--dir",
        str(project_root),
    ]
    env.setdefault("XDG_DATA_HOME", str(project_root / ".opencode" / "data"))
    for path in files or []:
        command.extend(["--file", str(path)])

    last_detail = ""
    start_all = time.monotonic()
    for attempt in range(max_retries + 1):
        attempt_prompt = prompt
        if attempt and last_detail:
            attempt_prompt = (
                f"{prompt}\n\nPrevious JSON validation failed: {last_detail}\n"
                "Return corrected JSON only."
            )
            command[2] = attempt_prompt
        start = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=project_root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            last_detail = f"opencode {expected} timed out after {timeout_seconds}s"
            continue
        except OSError as exc:
            last_detail = f"opencode launch failed: {exc}"
            break
        runtime = time.monotonic() - start
        if completed.returncode != 0:
            last_detail = f"opencode exit_code={completed.returncode} stderr_tail={completed.stderr[-1000:]!r}"
            continue
        try:
            parsed = extract_json(completed.stdout)
            data = validator(parsed)
            return AgentRunResult(
                "ok", data, f"opencode {expected} ok", command, runtime, attempt
            )
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            last_detail = f"{type(exc).__name__}: {exc}"
            if completed.stdout:
                last_detail += f" stdout_tail={completed.stdout[-1000:]!r}"
            if completed.stderr:
                last_detail += f" stderr_tail={completed.stderr[-1000:]!r}"
    return AgentRunResult(
        "failed",
        None,
        last_detail or f"opencode {expected} failed",
        command,
        time.monotonic() - start_all,
        max_retries,
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_path(workdir: Path, artifact_name: str) -> Path:
    mapped = resolve_artifact_path(workdir, artifact_name)
    if mapped.exists():
        return mapped
    legacy = workdir / artifact_name
    if legacy.exists():
        return legacy
    return mapped


def _read_json_artifact(workdir: Path, artifact_name: str) -> dict[str, Any] | None:
    return _read_json(_artifact_path(workdir, artifact_name))


def _read_investigation_records(workdir: Path) -> list[dict[str, Any]]:
    path = _artifact_path(workdir, "investigation_rounds.jsonl")
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _compact_priority_finding(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "finding_id": item.get("finding_id"),
        "risk_level": item.get("risk_level"),
        "category": item.get("category"),
        "workbook": item.get("workbook"),
        "sheet": item.get("sheet"),
        "column_pair": item.get("column_pair"),
        "relationship_value": item.get("relationship_value"),
        "support_rows": item.get("support_rows") or item.get("equal_rows"),
        "overlap_rows": item.get("overlap_rows"),
        "benign_explanations": (item.get("benign_explanations") or [])[:3],
    }


def _compact_pair_forensics_finding(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "finding_id": item.get("finding_id"),
        "risk_level": item.get("risk_level"),
        "category": item.get("category"),
        "workbook": item.get("workbook"),
        "sheet": item.get("sheet"),
        "offset": item.get("row_offset") or item.get("pair_id_offset"),
        "columns": item.get("columns") or item.get("column_pair") or item.get("column"),
        "support": item.get("support_rows")
        or item.get("matched_pairs")
        or item.get("matched_pair_groups")
        or item.get("duplicate_row_count")
        or item.get("exact_reuse_pairs"),
        "overlap": item.get("overlap_rows")
        or item.get("overlap_pairs")
        or item.get("overlap_pair_groups"),
        "support_rate": item.get("support_rate"),
        "sample_pairs": (
            item.get("sample_pairs") or item.get("sample_exact_pairs") or []
        )[:5],
    }


def _compact_claim_mapping(item: dict[str, Any]) -> dict[str, Any]:
    claims = item.get("candidate_claims") or []
    first_claim = claims[0] if claims and isinstance(claims[0], dict) else {}
    linked = item.get("linked_priority_findings") or []
    return {
        "mapping_id": item.get("mapping_id"),
        "source_figure_id": item.get("source_figure_id"),
        "workbook": item.get("workbook"),
        "sheet": item.get("sheet"),
        "review_priority": item.get("review_priority"),
        "mapping_confidence": item.get("mapping_confidence"),
        "candidate_claim": {
            "text": str(first_claim.get("text", ""))[:280],
            "location": first_claim.get("location"),
        },
        "linked_priority_findings": [
            linked_item.get("finding_id")
            for linked_item in linked[:6]
            if isinstance(linked_item, dict)
        ],
    }


def _claims_from_mappings(mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for idx, mapping in enumerate(mappings[:12], start=1):
        candidate_claims = mapping.get("candidate_claims") or []
        text = candidate_claims[0].get("text") if candidate_claims else None
        if not text:
            continue
        claims.append(
            {
                "claim_id": f"AC-{idx:03d}",
                "claim_text": text,
                "claim_type": "figure_trace",
                "paper_location": mapping.get("source_figure_id"),
                "evidence_refs": [mapping.get("mapping_id"), mapping.get("sheet")],
                "status": "needs_review",
            }
        )
    return claims


def _review_mappings(mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, mapping in enumerate(mappings[:12], start=1):
        rows.append(
            {
                "claim_id": f"AC-{idx:03d}",
                "mapping_id": mapping.get("mapping_id"),
                "source_data_refs": [mapping.get("workbook"), mapping.get("sheet")],
                "confidence": mapping.get("mapping_confidence", "medium"),
                "needs_human_review": mapping.get("review_priority") == "high",
            }
        )
    return rows


def _role_input_files(role_id: str, workdir: Path) -> list[Path]:
    candidates: dict[str, list[str]] = {
        "claim_extractor": [
            "material_inventory.json",
            "agent_material_plan.json",
            "full.md",
            "evidence_ledger.json",
            "source_data_findings.json",
            "source_data_pair_forensics.json",
        ],
        "source_data_auditor": [
            "material_inventory.json",
            "agent_material_plan.json",
            "source_data_findings.json",
            "source_data_pair_forensics.json",
            "agent_claim_extractor.json",
        ],
        "judge": [
            "material_inventory.json",
            "agent_material_plan.json",
            "agent_claim_extractor.json",
            "agent_source_data_auditor.json",
            "numeric_forensics.json",
            "source_data_findings.json",
            "source_data_pair_forensics.json",
        ],
    }
    return [
        path
        for path in (
            _artifact_path(workdir, name) for name in candidates.get(role_id, [])
        )
        if path.exists()
    ]


def _artifact_summary_material_section(
    material_inventory: dict[str, Any],
    material_plan: dict[str, Any],
) -> dict[str, Any]:
    """Build material inventory and plan summary sections."""
    inventory_summary = material_inventory.get("summary") or {}
    return {
        "material_inventory": {
            "file_count": inventory_summary.get("file_count"),
            "by_material_type": inventory_summary.get("by_material_type", {}),
            "candidate_source_roots": (
                material_inventory.get("candidate_source_roots") or []
            )[:8],
            "limitations": material_inventory.get("limitations", []),
        },
        "material_plan": {
            "status": material_plan.get("status", "ok") if material_plan else "missing",
            "selected_optional_lanes": material_plan.get("selected_optional_lanes", []),
            "missing_materials": material_plan.get("missing_materials", []),
            "unsupported_materials": (material_plan.get("unsupported_materials") or [])[
                :12
            ],
        },
    }


def _artifact_summary_evidence_section(
    ledger: dict[str, Any],
    numeric: dict[str, Any],
) -> dict[str, Any]:
    """Build evidence ledger and numeric forensics summary sections."""
    return {
        "evidence_ledger_stats": ledger.get("stats", {}),
        "evidence_ledger_warnings": [
            {"code": item.get("code"), "message": str(item.get("message", ""))[:220]}
            for item in (ledger.get("warnings") or [])[:10]
            if isinstance(item, dict)
        ],
        "numeric_forensics": {
            "all_number_count": numeric.get("all_number_count"),
            "number_count": numeric.get("number_count"),
            "table_count": numeric.get("table_count"),
            "effective_scope": numeric.get("effective_scope"),
            "benford_applicability": (numeric.get("benford") or {}).get("applicability"),
            "benford_mad": (numeric.get("benford") or {}).get(
                "mad", (numeric.get("benford") or {}).get("mean_absolute_deviation")
            ),
        },
    }


def _artifact_summary_source_data_section(
    source_findings: dict[str, Any],
    pair_forensics: dict[str, Any],
) -> dict[str, Any]:
    """Build source data findings and pair forensics summary sections."""
    return {
        "source_data_findings_summary": source_findings.get("summary", {}),
        "source_data_pair_forensics_summary": pair_forensics.get("summary", {}),
        "source_data_pair_forensics_review_tasks": [
            {
                "task_id": item.get("task_id"),
                "priority": item.get("priority"),
                "cluster_id": item.get("cluster_id"),
                "category": item.get("category"),
                "workbook": item.get("workbook"),
                "sheet": item.get("sheet"),
                "cluster_count": item.get("cluster_count"),
                "finding_count": item.get("finding_count"),
                "question": str(item.get("question", ""))[:280],
                "representative_finding_ids": (
                    item.get("representative_finding_ids") or []
                )[:6],
            }
            for item in (pair_forensics.get("review_tasks") or [])[:12]
            if isinstance(item, dict)
        ],
        "source_data_pair_forensics_clusters": [
            {
                "cluster_id": item.get("cluster_id"),
                "category": item.get("category"),
                "risk_level": item.get("risk_level"),
                "workbook": item.get("workbook"),
                "sheet": item.get("sheet"),
                "pattern_signature": item.get("pattern_signature"),
                "finding_count": item.get("finding_count"),
                "representative_finding_ids": (
                    item.get("representative_finding_ids") or []
                )[:6],
            }
            for item in (pair_forensics.get("finding_clusters") or [])[:12]
            if isinstance(item, dict)
        ],
        "source_data_pair_forensics_priority": [
            _compact_pair_forensics_finding(item)
            for item in (pair_forensics.get("priority_findings") or [])[:12]
            if isinstance(item, dict)
        ],
        "priority_findings": [
            _compact_priority_finding(item)
            for item in (source_findings.get("priority_findings") or [])[:12]
            if isinstance(item, dict)
        ],
        "claim_to_source_data": [
            _compact_claim_mapping(item)
            for item in (source_findings.get("claim_to_source_data") or [])[:18]
            if isinstance(item, dict)
        ],
    }


def _artifact_summary_briefings_section(
    workdir: Path,
) -> dict[str, Any]:
    """Build source data briefings section."""
    briefings_artifact = (
        _read_json_artifact(workdir, "source_data_sheet_briefings.json") or {}
    )
    return {
        "source_data_briefings": [
            {
                "sheet": b.get("sheet"),
                "workbook": b.get("workbook"),
                "finding_count": b.get("finding_count"),
                "structure": b.get("structure", {}),
                "detected_patterns": b.get("detected_patterns", []),
            }
            for b in (briefings_artifact.get("sheets") or [])[:20]
            if isinstance(b, dict)
        ]
    }


def _artifact_summary_image_section(
    image_duplicates: dict[str, Any],
    image_similarity: dict[str, Any],
) -> dict[str, Any]:
    """Build image duplicates and similarity sections."""
    return {
        "image_duplicates": {
            "image_count": image_duplicates.get("image_count"),
            "duplicate_group_count": image_duplicates.get("duplicate_group_count"),
            "duplicate_image_count": image_duplicates.get("duplicate_image_count"),
        },
        "image_similarity_candidates": {
            "status": image_similarity.get("status"),
            "method": image_similarity.get("method"),
            "image_count": image_similarity.get("image_count"),
            "candidate_count": image_similarity.get("candidate_count"),
        },
    }


def _artifact_summary_visual_section(
    visual_findings: dict[str, Any],
) -> dict[str, Any]:
    """Build visual findings sections."""
    visual_summary = {
        "status": visual_findings.get("status"),
        "relationship_count": visual_findings.get("relationship_count"),
        "finding_count": visual_findings.get("finding_count"),
        "finding_cluster_count": visual_findings.get("finding_cluster_count"),
        "review_queue_count": visual_findings.get("review_queue_count"),
    }
    return {
        "visual_findings": visual_summary,
        "visual_review_queue": [
            {
                "task_id": item.get("task_id"),
                "priority": item.get("priority"),
                "cluster_id": item.get("cluster_id"),
                "category": item.get("category"),
                "scope": item.get("scope"),
                "figure_ids": (item.get("figure_ids") or [])[:6],
                "finding_count": item.get("finding_count"),
                "relationship_count": item.get("relationship_count"),
                "panel_extraction_quality": item.get("panel_extraction_quality"),
                "question": str(item.get("question", ""))[:280],
            }
            for item in (visual_findings.get("review_queue") or [])[:12]
            if isinstance(item, dict)
        ],
        "visual_finding_clusters": [
            {
                "cluster_id": item.get("cluster_id"),
                "category": item.get("category"),
                "risk_level": item.get("risk_level"),
                "scope": item.get("scope"),
                "figure_ids": (item.get("figure_ids") or [])[:6],
                "panel_extraction_quality": item.get("panel_extraction_quality"),
                "finding_count": item.get("finding_count"),
                "relationship_count": item.get("relationship_count"),
                "max_score": item.get("max_score"),
                "representative_finding_ids": (
                    item.get("representative_finding_ids") or []
                )[:6],
            }
            for item in (visual_findings.get("finding_clusters") or [])[:12]
            if isinstance(item, dict)
        ],
    }


def _artifact_summary(workdir: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {"workdir": str(workdir)}

    # Load all artifacts
    material_inventory = _read_json_artifact(workdir, "material_inventory.json") or {}
    material_plan = _read_json_artifact(workdir, "agent_material_plan.json") or {}
    ledger = _read_json_artifact(workdir, "evidence_ledger.json") or {}
    numeric = _read_json_artifact(workdir, "numeric_forensics.json") or {}
    source_findings = _read_json_artifact(workdir, "source_data_findings.json") or {}
    pair_forensics = (
        _read_json_artifact(workdir, "source_data_pair_forensics.json") or {}
    )
    image_duplicates = _read_json_artifact(workdir, "exact_image_duplicates.json") or {}
    image_similarity = (
        _read_json_artifact(workdir, "image_similarity_candidates.json") or {}
    )
    visual_findings = _read_json_artifact(workdir, "visual_findings.json") or {}
    investigation_records = _read_investigation_records(workdir)

    # Build sections
    summary.update(_artifact_summary_material_section(material_inventory, material_plan))
    summary.update(_artifact_summary_evidence_section(ledger, numeric))
    summary.update(_artifact_summary_source_data_section(source_findings, pair_forensics))
    summary.update(_artifact_summary_briefings_section(workdir))
    summary.update(_artifact_summary_image_section(image_duplicates, image_similarity))
    summary.update(_artifact_summary_visual_section(visual_findings))
    summary["investigation_records"] = investigation_records[-20:]

    return summary
