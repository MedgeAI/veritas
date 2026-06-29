from __future__ import annotations

import json
import sys
from typing import Any, Callable, TextIO

from engine.static_audit.orchestrator import run_static_audit


ProgressReporter = Callable[[dict[str, Any]], None]


def make_progress_reporter(
    mode: str, stream: TextIO | None = None
) -> ProgressReporter | None:
    stream = stream or sys.stderr
    resolved_mode = mode
    if mode == "auto":
        resolved_mode = "plain" if stream.isatty() else "off"
    if resolved_mode == "off":
        return None
    if resolved_mode == "jsonl":
        return lambda event: print(
            json.dumps(event, ensure_ascii=False), file=stream, flush=True
        )
    if resolved_mode != "plain":
        raise ValueError(f"Unsupported progress mode: {mode}")

    def report(event: dict[str, Any]) -> None:
        print(format_plain_progress(event), file=stream, flush=True)

    return report


def format_plain_progress(event: dict[str, Any]) -> str:
    timestamp = event.get("timestamp", "")
    event_type = event.get("event", "")
    if event_type == "audit_start":
        return (
            f"[{timestamp}] AUDIT start | case_id={event.get('case_id')} "
            f"| agent_mode={event.get('agent_mode')} | workdir={event.get('workdir')}"
        )
    if event_type == "audit_end":
        failed_steps = event.get("failed_steps") or []
        suffix = f" | failed_steps={','.join(failed_steps)}" if failed_steps else ""
        return f"[{timestamp}] AUDIT {event.get('status')} | final_html={event.get('final_html_report')}{suffix}"
    if event_type == "step_start":
        detail = f" | {event.get('detail')}" if event.get("detail") else ""
        command = (
            f" | cmd={event.get('command_preview')}"
            if event.get("command_preview")
            else ""
        )
        return f"[{timestamp}] START {event.get('key')} | {event.get('title')}{detail}{command}"
    if event_type == "step_attempt":
        return f"[{timestamp}] TRY   {event.get('key')} | attempt={event.get('attempt')}/{event.get('attempts')}"
    if event_type == "command_output":
        line = str(event.get("line", ""))
        return f"[{timestamp}] OUT   {event.get('key')} | {line}"
    if event_type == "step_result":
        status = str(event.get("status", "")).upper()
        detail = f" | {event.get('detail')}" if event.get("detail") else ""
        return f"[{timestamp}] {status:<5} {event.get('key')} | {event.get('title')}{detail}"
    return f"[{timestamp}] {event_type} | {json.dumps(event, ensure_ascii=False)}"


def handle(
    paper_dir: str,
    case_id: str | None,
    output_root: str,
    force: bool,
    fresh: bool,
    no_env_file: bool,
    agent_mode: str,
    agent_model: str,
    opencode_bin: str,
    agent_timeout_seconds: int,
    agent_max_retries: int,
    skip_unavailable_tools: bool = False,
    profile: str = "full",
    progress_mode: str = "auto",
) -> int:
    summary = run_static_audit(
        paper_dir,
        case_id=case_id,
        output_root=output_root,
        fresh=fresh,
        force=force,
        no_env_file=no_env_file,
        agent_mode=agent_mode,
        agent_model=agent_model,
        opencode_bin=opencode_bin,
        agent_timeout_seconds=agent_timeout_seconds,
        agent_max_retries=agent_max_retries,
        skip_unavailable_tools=skip_unavailable_tools,
        audit_profile=profile,
        progress=make_progress_reporter(progress_mode),
    )
    exit_code = int(summary.pop("exit_code"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return exit_code
