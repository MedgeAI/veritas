"""Investigation runner and agent role execution for Veritas static audit.

Extracted from orchestrator.py to reduce God Object complexity.
All public names are re-exported via orchestrator for backward compatibility.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any

from engine.static_audit.models import AgentTrace
from engine.static_audit.investigation import (
    InvestigationAction,
    InvestigationRecord,
    append_investigation_record,
    read_investigation_records,
)
from engine.static_audit.roles import ROLE_DEFINITIONS, RoleDefinition, skipped_trace
from engine.investigation.opencode_agent import (
    AgentRunResult,
    result_metadata,
    run_agent_investigation_plan,
    run_agent_role,
    write_agent_result,
)
from engine.static_audit.investigation_tools import ADAPTERS, tool_output_filename

# ---------------------------------------------------------------------------
# Shared utilities (previously in orchestrator.py, now in _shared.py).
# ---------------------------------------------------------------------------
from engine.static_audit._shared import (
    MAX_INVESTIGATION_ROUNDS,
    ProgressCallback,
    StepResult,
    agent_step_status,
    artifact_exists,
    emit_step_result,
    emit_step_start,
    investigation_action_from_dict,
    read_json,
    record_step,
    resolve_artifact_path,
    safe_action_dir_name,
)


def run_investigation_rounds(
    *,
    case_id: str,
    workdir: Path,
    source_data_dir: Path | None,
    agent_enabled: bool,
    agent_mode: str,
    force: bool,
    project_root: Path,
    env: dict[str, str],
    model: str,
    opencode_bin: str,
    timeout_seconds: int,
    max_retries: int,
    progress: ProgressCallback | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    steps: list[StepResult] = []
    manifest: dict[str, Any] = {
        "enabled": agent_enabled,
        "max_rounds": MAX_INVESTIGATION_ROUNDS,
        "rounds_artifact": str(
            resolve_artifact_path(workdir, "investigation_rounds.jsonl")
        ),
        "plans": [],
    }
    if not agent_enabled:
        step = StepResult(
            "agent_investigation",
            "opencode Agent 调查规划",
            "skipped",
            f"agent_mode={agent_mode} does not run AgentInvestigationPlanner.",
        )
        record_step(steps, step, progress)
        return steps, manifest

    seen_signatures = {
        str((record.get("metadata") or {}).get("signature"))
        for record in read_investigation_records(workdir)
        if (record.get("metadata") or {}).get("signature")
    }
    stop_reason = ""
    for round_id in range(1, MAX_INVESTIGATION_ROUNDS + 1):
        plan_path = workdir / f"agent_investigation_plan_round_{round_id:02d}.json"
        previous_records = read_investigation_records(workdir)
        emit_step_start(
            progress,
            f"agent_investigation_plan_round_{round_id:02d}",
            "opencode Agent 调查规划",
            f"Calling opencode investigation planner round {round_id}.",
        )
        plan_result = run_agent_investigation_plan(
            case_id=case_id,
            workdir=workdir,
            round_id=round_id,
            previous_records=previous_records,
            project_root=project_root,
            env=env,
            model=model,
            opencode_bin=opencode_bin,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        write_agent_result(plan_path, plan_result, "investigation_plan")
        manifest["plans"].append(result_metadata(plan_result, plan_path))
        plan_step = StepResult(
            f"agent_investigation_plan_round_{round_id:02d}",
            "opencode Agent 调查规划",
            agent_step_status(plan_result.status),
            plan_result.detail,
            plan_result.command,
        )
        record_step(steps, plan_step, progress)
        if not plan_result.data:
            append_investigation_record(
                workdir,
                InvestigationRecord(
                    round_id=round_id,
                    action_id=f"IR-{round_id:02d}-PLAN",
                    tool_id="agent.investigation_plan",
                    status="failed",
                    validation_status="failed",
                    detail=plan_result.detail,
                    metadata={"plan_artifact": str(plan_path)},
                ),
            )
            stop_reason = "planner_failed"
            break

        actions = [
            investigation_action_from_dict(round_id, action)
            for action in (plan_result.data.get("actions") or [])
            if isinstance(action, dict)
        ]
        if not actions:
            stop_reason = str(plan_result.data.get("stop_reason") or "no_more_tools")
            append_investigation_record(
                workdir,
                InvestigationRecord(
                    round_id=round_id,
                    action_id=f"IR-{round_id:02d}-STOP",
                    tool_id="none",
                    status="skipped",
                    validation_status="accepted",
                    detail=stop_reason,
                    metadata={
                        "plan_artifact": str(plan_path),
                        "agent_rationale": plan_result.data.get("agent_rationale")
                        or [],
                    },
                ),
            )
            break

        new_artifact_count = 0
        new_findings_count = 0

        # Strategy 6: Run independent actions in parallel within a round
        # Actions are independent if they don't depend on each other's outputs
        def _run_action(action):
            signature = action.signature()
            record_base = {
                "round_id": round_id,
                "action_id": action.action_id,
                "tool_id": action.tool_id,
                "hypothesis": action.hypothesis,
                "expected_evidence_type": action.expected_evidence_type,
                "params": action.params,
                "depends_on_artifacts": action.depends_on_artifacts,
                "metadata": {
                    "signature": signature,
                    "plan_artifact": str(plan_path),
                    "agent_rationale": plan_result.data.get("agent_rationale") or [],
                },
            }
            if signature in seen_signatures:
                return (
                    record_base,
                    InvestigationRecord(
                        **record_base,
                        status="skipped",
                        validation_status="rejected",
                        detail="Duplicate tool_id + params + depends_on_artifacts action.",
                    ),
                    0,
                    0,
                )

            missing_artifacts = [
                artifact
                for artifact in action.depends_on_artifacts
                if not artifact_exists(workdir, artifact)
            ]
            if missing_artifacts:
                seen_signatures.add(signature)
                return (
                    record_base,
                    InvestigationRecord(
                        **record_base,
                        status="skipped",
                        validation_status="rejected",
                        detail=f"Missing depends_on_artifacts: {missing_artifacts}",
                    ),
                    0,
                    0,
                )

            step, output_artifacts = run_investigation_tool_action(
                action=action,
                workdir=workdir,
                source_data_dir=source_data_dir,
                env=env,
                force=force,
                progress=progress,
            )
            seen_signatures.add(signature)
            artifact_count = sum(
                1 for artifact in output_artifacts if Path(artifact).exists()
            )

            # Count new findings produced
            findings_count = 0
            for artifact in output_artifacts:
                artifact_path = Path(artifact)
                if artifact_path.exists() and "findings" in artifact_path.name:
                    try:
                        with open(artifact_path) as f:
                            data = json.load(f)
                        if isinstance(data, dict):
                            findings_count = len(data.get("findings", []))
                        elif isinstance(data, list):
                            findings_count = len(data)
                    except (json.JSONDecodeError, OSError):
                        pass

            record = InvestigationRecord(
                **record_base,
                status=step.status,
                validation_status="accepted",
                output_artifacts=output_artifacts,
                detail=step.detail,
                command=step.command,
            )
            steps.append(step)
            return record_base, record, artifact_count, findings_count

        # Run actions - parallel if multiple, sequential if single or dependent
        if len(actions) > 1:
            # Check for dependencies between actions
            has_deps = False
            for i, a1 in enumerate(actions):
                for a2 in actions[i + 1 :]:
                    if any(
                        out in a2.depends_on_artifacts for out in a1.output_artifacts
                    ):
                        has_deps = True
                        break
                if has_deps:
                    break

            if has_deps:
                # Sequential execution for dependent actions
                results = [_run_action(action) for action in actions]
            else:
                # Parallel execution for independent actions (Strategy 6)
                with ThreadPoolExecutor(max_workers=min(len(actions), 4)) as executor:
                    futures = {
                        executor.submit(_run_action, action): action
                        for action in actions
                    }
                    results = []
                    for future in as_completed(futures):
                        results.append(future.result())
        else:
            results = [_run_action(action) for action in actions]

        for _record_base, record, artifact_count, findings_count in results:
            append_investigation_record(workdir, record)
            new_artifact_count += artifact_count
            new_findings_count += findings_count

        # Strategy 2: Enhanced early termination
        # Stop if no new artifacts OR no new findings produced
        if new_artifact_count == 0:
            stop_reason = "no_new_artifacts"
            break
        if new_findings_count == 0 and round_id > 1:
            # Only stop after round 1 if no new findings (round 1 might set up context)
            stop_reason = "no_new_findings"
            break

    manifest["stop_reason"] = stop_reason or "max_rounds_reached"
    manifest["records"] = read_investigation_records(workdir)
    return steps, manifest


def run_investigation_tool_action(
    *,
    action: InvestigationAction,
    workdir: Path,
    source_data_dir: Path | None,
    env: dict[str, str],
    force: bool,
    progress: ProgressCallback | None,
) -> tuple[StepResult, list[str]]:
    """Dispatch an investigation tool action to its registered adapter.

    Each tool_id maps to an adapter function in investigation_tools.ADAPTERS.
    Adding a new tool = adding one adapter function + one registry entry.
    No changes needed here.
    """
    action_dir = (
        resolve_artifact_path(workdir, "investigation")
        / f"round_{action.round_id:02d}"
        / safe_action_dir_name(action.action_id)
    )
    action_dir.mkdir(parents=True, exist_ok=True)
    key = (
        f"investigation_{action.round_id:02d}_{safe_action_dir_name(action.action_id)}"
    )

    adapter = ADAPTERS.get(action.tool_id)
    if adapter is None:
        step = StepResult(
            key,
            "Agent Investigation Tool",
            "skipped",
            f"Tool '{action.tool_id}' is registered but not yet implemented.",
        )
        emit_step_result(progress, step)
        return step, []

    output = action_dir / tool_output_filename(action.tool_id)
    return adapter(
        action, workdir, source_data_dir, env, force, progress, key, action_dir, output,
    )


def _build_dependency_layers(roles_to_run: list[tuple]) -> list[list[tuple]]:
    """根据 input_artifacts 构建依赖分层，确保前置角色先执行。

    例如：
    - claim_extractor 无依赖 → Layer 1
    - source_data_auditor 依赖 agent_claim_extractor.json → Layer 2
    - judge 依赖 agent_claim_extractor.json + agent_source_data_auditor.json → Layer 3

    返回按层级排序的列表，每层内部可并行执行。
    """
    # 构建角色名称到 role_data 的映射
    role_map = {rd[0].role_id: rd for rd in roles_to_run}

    # 构建 artifact → 生产者 role_id 索引，将 O(R²×A) 降为 O(R×A)
    artifact_producer: dict[str, str] = {}
    for role, _, _ in roles_to_run:
        if role.output_artifact:
            artifact_producer[role.output_artifact] = role.role_id

    # 构建依赖图：role_id -> 依赖的 role_ids
    deps = {}
    for role, _, _ in roles_to_run:
        role_deps = []
        for artifact in role.input_artifacts:
            producer_id = artifact_producer.get(artifact)
            if producer_id:
                role_deps.append(producer_id)
        deps[role.role_id] = set(role_deps)

    # 分层：每次取出无依赖的角色组成一层，然后从依赖图中移除
    layers = []
    remaining = set(deps.keys())

    while remaining:
        # 找出所有依赖都已满足的角色
        layer = []
        for role_id in remaining:
            if all(dep not in remaining for dep in deps[role_id]):
                layer.append(role_id)

        if not layer:
            # 防止死循环：如果有循环依赖，把所有剩余角色放在最后一层
            layer = list(remaining)

        # 添加到层级列表
        layers.append([role_map[rid] for rid in layer])

        # 从剩余集合中移除已分层的角色
        remaining -= set(layer)

    return layers


def run_agent_roles(
    *,
    case_id: str,
    workdir: Path,
    agent_enabled: bool,
    agent_mode: str,
    force: bool,
    project_root: Path,
    env: dict[str, str],
    model: str,
    opencode_bin: str,
    timeout_seconds: int,
    max_retries: int,
    progress: ProgressCallback | None = None,
) -> tuple[list[StepResult], list[dict[str, Any]]]:
    steps: list[StepResult] = []
    role_manifest: list[dict[str, Any]] = []

    # Phase 1: Quick checks (reuse/skip) - sequential, fast
    roles_to_run = []
    for role in ROLE_DEFINITIONS:
        output_path = resolve_artifact_path(workdir, role.output_artifact)
        trace_path = (
            resolve_artifact_path(workdir, "agent_traces") / f"{role.role_id}.json"
        )
        existing_trace = read_agent_trace(trace_path)
        if (
            not force
            and output_path.exists()
            and existing_trace is not None
            and existing_trace.status in {"ran", "skipped"}
        ):
            role_manifest.append(
                {
                    "role_id": role.role_id,
                    "status": "reused",
                    "output": str(output_path),
                    "trace": str(trace_path),
                    "previous_status": existing_trace.status,
                }
            )
            if role.real_in_v1:
                record_step(
                    steps,
                    StepResult(
                        f"agent_role_{role.role_id}",
                        f"opencode Agent role: {role.title}",
                        "reused",
                        "Existing successful role output and trace found.",
                    ),
                    progress,
                )
            continue
        if not role.real_in_v1:
            trace = skipped_trace(
                role, "Role schema reserved; not executed in static_audit_protocol.v1."
            )
            trace.output_path = str(output_path)
            write_reserved_role_output(workdir, role, trace)
            write_role_trace(workdir, trace)
            role_manifest.append(
                {
                    "role_id": role.role_id,
                    "status": trace.status,
                    "output": str(output_path),
                }
            )
            continue

        step_key = f"agent_role_{role.role_id}"
        if not agent_enabled:
            trace = AgentTrace(
                role_id=role.role_id,
                status="not_run",
                input_artifacts=list(role.input_artifacts),
                output_path=str(output_path),
                output_summary={},
                model=model,
                detail=f"agent_mode={agent_mode} does not run static-audit role agents.",
            )
            write_reserved_role_output(workdir, role, trace)
            write_role_trace(workdir, trace)
            record_step(
                steps,
                StepResult(
                    step_key,
                    f"opencode Agent role: {role.title}",
                    "skipped",
                    trace.detail,
                ),
                progress,
            )
            role_manifest.append(
                {
                    "role_id": role.role_id,
                    "status": trace.status,
                    "output": str(output_path),
                }
            )
            continue

        roles_to_run.append((role, output_path, trace_path))

    # Phase 2: Run roles in dependency order (respecting input_artifacts)
    if roles_to_run:

        def _run_single_role(role_data):
            role, output_path, _trace_path = role_data
            step_key = f"agent_role_{role.role_id}"
            emit_step_start(
                progress,
                step_key,
                f"opencode Agent role: {role.title}",
                f"Calling opencode role agent {role.role_id}.",
            )
            result = run_agent_role(
                role_id=role.role_id,
                case_id=case_id,
                workdir=workdir,
                project_root=project_root,
                env=env,
                model=model,
                opencode_bin=opencode_bin,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
            payload = write_role_agent_result(output_path, role, case_id, result)
            trace = trace_from_role_result(role, output_path, result, payload, model)
            write_role_trace(workdir, trace)
            metadata = result_metadata(result, output_path)
            metadata["role_id"] = role.role_id
            step = StepResult(
                step_key,
                f"opencode Agent role: {role.title}",
                agent_step_status(result.status),
                result.detail,
                result.command,
            )
            return step, metadata

        # 根据 input_artifacts 构建依赖分层，按层级顺序执行
        layers = _build_dependency_layers(roles_to_run)
        for layer in layers:
            # 每层内部并行执行，层间顺序执行
            with ThreadPoolExecutor(max_workers=len(layer)) as executor:
                futures = {executor.submit(_run_single_role, rd): rd[0] for rd in layer}
                for future in as_completed(futures):
                    step, metadata = future.result()
                    record_step(steps, step, progress)
                    role_manifest.append(metadata)

    return steps, role_manifest


def collect_agent_traces(
    workdir: Path, _agent_manifest: dict[str, Any]
) -> list[AgentTrace]:
    traces: list[AgentTrace] = []
    for role in ROLE_DEFINITIONS:
        trace_path = (
            resolve_artifact_path(workdir, "agent_traces") / f"{role.role_id}.json"
        )
        trace = read_agent_trace(trace_path)
        if trace is None:
            trace = skipped_trace(
                role, "Role trace was missing and has been backfilled."
            )
            trace.output_path = str(workdir / role.output_artifact)
            write_reserved_role_output(workdir, role, trace)
            write_role_trace(workdir, trace)
        traces.append(trace)
    return traces


def trace_from_role_result(
    role: RoleDefinition,
    output_path: Path,
    result: AgentRunResult,
    payload: dict[str, Any],
    model: str,
) -> AgentTrace:
    status = "ran" if result.status == "ok" else "failed"
    return AgentTrace(
        role_id=role.role_id,
        status=status,  # type: ignore[arg-type]
        input_artifacts=list(role.input_artifacts),
        output_path=str(output_path),
        output_summary=role_output_summary(role.role_id, payload),
        model=model,
        detail=result.detail,
        error=None if status == "ran" else result.detail,
        metadata={
            "retries": result.retries,
            "runtime_seconds": round(result.runtime_seconds, 3),
        },
    )


def write_role_agent_result(
    output_path: Path,
    role: RoleDefinition,
    case_id: str,
    result: AgentRunResult,
) -> dict[str, Any]:
    if result.data is None:
        payload = role_failure_payload(role.role_id, case_id, result.detail)
    else:
        payload = dict(result.data)
        payload.setdefault("schema_version", "1.0")
        payload.setdefault("role_id", role.role_id)
        payload.setdefault("case_id", case_id)
        payload["status"] = "ran"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def role_failure_payload(role_id: str, case_id: str, detail: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "role_id": role_id,
        "case_id": case_id,
        "status": "failed",
        "detail": detail,
    }
    if role_id == "claim_extractor":
        base.update({"claims": [], "limitations": [detail]})
    elif role_id == "source_data_auditor":
        base.update(
            {
                "claim_to_source_data": [],
                "finding_reviews": [],
                "manual_review_tasks": [],
                "limitations": [detail],
            }
        )
    elif role_id == "judge":
        base.update(
            {
                "summary": {},
                "risk_suggestions": [],
                "report_notes": [],
                "limitations": [detail],
            }
        )
    return base


def role_output_summary(role_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if role_id == "claim_extractor":
        return {
            "claims": len(payload.get("claims") or []),
            "limitations": len(payload.get("limitations") or []),
        }
    if role_id == "source_data_auditor":
        return {
            "claim_to_source_data": len(payload.get("claim_to_source_data") or []),
            "finding_reviews": len(payload.get("finding_reviews") or []),
            "manual_review_tasks": len(payload.get("manual_review_tasks") or []),
        }
    if role_id == "judge":
        summary = (
            payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        )
        return {
            **summary,
            "risk_suggestions": len(payload.get("risk_suggestions") or []),
            "report_notes": len(payload.get("report_notes") or []),
        }
    return {}


def write_reserved_role_output(
    workdir: Path, role: RoleDefinition, trace: AgentTrace
) -> None:
    output_path = resolve_artifact_path(workdir, role.output_artifact)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "role_id": role.role_id,
        "status": trace.status,
        "detail": trace.detail,
        "input_artifacts": list(role.input_artifacts),
        "reserved_for": "static_audit_protocol.v1",
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_role_trace(workdir: Path, trace: AgentTrace) -> None:
    role_dir = resolve_artifact_path(workdir, "agent_traces")
    role_dir.mkdir(parents=True, exist_ok=True)
    path = role_dir / f"{trace.role_id}.json"
    path.write_text(
        json.dumps(asdict(trace), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_agent_trace(path: Path) -> AgentTrace | None:
    data = read_json(path)
    if not data:
        return None
    return AgentTrace(
        role_id=str(data.get("role_id", "")),
        status=str(data.get("status", "failed")),  # type: ignore[arg-type]
        input_artifacts=[str(item) for item in (data.get("input_artifacts") or [])],
        output_path=data.get("output_path"),
        output_summary=data.get("output_summary")
        if isinstance(data.get("output_summary"), dict)
        else {},
        model=data.get("model"),
        detail=str(data.get("detail", "")),
        error=data.get("error"),
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
    )
