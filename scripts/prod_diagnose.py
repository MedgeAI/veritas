#!/usr/bin/env python3
"""Collect an agent-friendly production diagnostic bundle.

The collector is intentionally read-only. It gathers Docker Compose state,
recent logs, health endpoints, host bind-mount readiness, and the latest audit
artifacts into JSON and Markdown files under web_data/diagnostics/.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_TEXT_CHARS = 12000
MAX_LOG_LINES = 80
DEFAULT_SERVICES = (
    "veritas",
    "celery-worker",
    "sila-dense",
    "elis-forensic",
    "cloudflared",
)

ERROR_RE = re.compile(
    r"(traceback|exception|error|warning|warn|wrn|failed|failure|fatal|panic|"
    r"eacces|enoent|permission denied|segmentation|degraded| 5\d\d | 4\d\d )",
    re.IGNORECASE,
)

SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(Authorization:\s*Bearer\s+)[^\s]+"), r"\1<redacted>"),
    (
        re.compile(
            r"(?i)\b("
            r"api[_-]?key|token|secret|password|passwd|pwd|"
            r"cloudflare_tunnel_token|dashscope_api_key|mineru_api_token|"
            r"postgres_password|admin_api_key"
            r")([=:]\s*)([^\s,;]+)"
        ),
        r"\1\2<redacted>",
    ),
    (
        re.compile(r"(?i)((?:postgresql|postgres|mysql|redis)://[^:\s/@]+:)[^@\s]+@"),
        r"\1<redacted>@",
    ),
)


def redact_text(value: str) -> str:
    redacted = value
    for pattern, replacement in SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def truncate_text(value: str, limit: int = MAX_TEXT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n...[truncated {len(value) - limit} chars]"


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_command(
    args: list[str],
    *,
    cwd: Path,
    timeout: float = 10.0,
    max_chars: int = MAX_TEXT_CHARS,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            errors="replace",
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "duration_ms": duration_ms,
            "args": [redact_text(a) for a in args],
            "stdout": truncate_text(redact_text(result.stdout), max_chars),
            "stderr": truncate_text(redact_text(result.stderr), max_chars),
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "ok": False,
            "exit_code": None,
            "duration_ms": duration_ms,
            "args": [redact_text(a) for a in args],
            "stdout": truncate_text(redact_text(stdout), max_chars),
            "stderr": truncate_text(redact_text(stderr), max_chars),
            "error": f"timeout after {timeout}s",
        }
    except OSError as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "ok": False,
            "exit_code": None,
            "duration_ms": duration_ms,
            "args": [redact_text(a) for a in args],
            "stdout": "",
            "stderr": redact_text(str(exc)),
            "error": exc.__class__.__name__,
        }


def compose_args(root: Path, *, cloudflare: bool = True) -> list[str]:
    args = ["docker", "compose"]
    for env_file in (root / ".env", root / "deploy" / ".env"):
        if env_file.exists():
            args.extend(["--env-file", str(env_file)])
    args.extend(["-p", "vdeploy", "-f", str(root / "deploy" / "docker-compose.yml")])
    cloudflare_file = root / "deploy" / "docker-compose.cloudflare.yml"
    if cloudflare and cloudflare_file.exists():
        args.extend(["-f", str(cloudflare_file)])
    return args


def parse_json_lines(raw: str) -> list[Any]:
    parsed: list[Any] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            return []
    return parsed


def parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_error_lines(raw: str, *, max_lines: int = MAX_LOG_LINES) -> list[str]:
    matches = [line for line in raw.splitlines() if ERROR_RE.search(line)]
    return matches[-max_lines:]


def path_info(path: Path) -> dict[str, Any]:
    exists = path.exists()
    info: dict[str, Any] = {
        "path": str(path),
        "exists": exists,
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
        "is_symlink": path.is_symlink(),
        "readable": os.access(path, os.R_OK),
        "writable": os.access(path, os.W_OK),
    }
    if path.is_symlink():
        info["target"] = os.readlink(path)
        info["resolved_path"] = str(path.resolve(strict=False))
    if exists:
        stat = path.stat()
        info.update(
            {
                "mode": oct(stat.st_mode & 0o777),
                "uid": stat.st_uid,
                "gid": stat.st_gid,
                "size_bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        )
    return info


def safe_load_json(path: Path, *, max_bytes: int = 2_000_000) -> Any | None:
    if not path.is_file() or path.stat().st_size > max_bytes:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def collect_problem_nodes(value: Any, *, prefix: str = "", limit: int = 80) -> list[dict[str, Any]]:
    problems: list[dict[str, Any]] = []

    def walk(node: Any, path: str) -> None:
        if len(problems) >= limit:
            return
        if isinstance(node, dict):
            status = str(node.get("status") or node.get("state") or "").lower()
            ok = node.get("ok")
            has_error_key = any(
                key in node
                for key in ("error", "exception", "traceback", "stderr", "failed_reason")
            )
            if status in {"failed", "warning", "degraded", "error"} or ok is False or has_error_key:
                problems.append(
                    {
                        "path": path or "$",
                        "status": status or None,
                        "keys": sorted(str(k) for k in node.keys())[:20],
                        "summary": truncate_text(redact_text(json.dumps(node, ensure_ascii=False, default=str)), 900),
                    }
                )
            for key, child in node.items():
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, child in enumerate(node[:200]):
                walk(child, f"{path}[{index}]")

    walk(value, prefix)
    return problems


def collect_latest_artifacts(root: Path) -> dict[str, Any]:
    outputs = root / "outputs"
    manifests = sorted(
        outputs.glob("case-*/research-integrity-audit/reports/audit_run_manifest.json"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    latest: list[dict[str, Any]] = []
    for manifest_path in manifests[:5]:
        manifest = safe_load_json(manifest_path)
        report_dir = manifest_path.parent
        workdir = report_dir.parent
        item: dict[str, Any] = {
            "manifest": path_info(manifest_path),
            "workdir": str(workdir),
            "final_report": path_info(report_dir / "final_audit_report.md"),
            "final_html_report": path_info(report_dir / "final_audit_report.html"),
            "static_audit_bundle": path_info(report_dir / "static_audit_bundle.json"),
        }
        diagnostics_path = workdir / "diagnostics" / "latest.json"
        if diagnostics_path.exists():
            diagnostics = safe_load_json(diagnostics_path)
            item["run_diagnostics"] = {
                "path": path_info(diagnostics_path),
                "summary": {
                    key: diagnostics.get(key)
                    for key in ("schema_version", "case_id", "run_id", "status")
                    if isinstance(diagnostics, dict) and key in diagnostics
                }
                if isinstance(diagnostics, dict)
                else {},
                "quality_flags": (diagnostics.get("quality_flags") or [])[:20]
                if isinstance(diagnostics, dict)
                else [],
            }
        if isinstance(manifest, dict):
            item["manifest_top_level"] = {
                key: manifest.get(key)
                for key in ("case_id", "run_id", "status", "created_at", "completed_at")
                if key in manifest
            }
            item["problem_nodes"] = collect_problem_nodes(manifest)
        latest.append(item)
    return {"latest_manifests": latest}


def collect_host_readiness(root: Path) -> dict[str, Any]:
    paths = {
        "web_data": root / "web_data",
        "opencode_data": root / "web_data" / ".opencode" / "data",
        "outputs": root / "outputs",
        "models": root / "models",
        "panel_extraction_weights": root / "models" / "panel_extraction" / "model_5_class.pt",
        "trufor_weights": root / "models" / "trufor" / "weights" / "trufor.pth.tar",
    }
    return {name: path_info(path) for name, path in paths.items()}


def collect_git(root: Path) -> dict[str, Any]:
    head = run_command(["git", "rev-parse", "--short", "HEAD"], cwd=root, timeout=3)
    branch = run_command(["git", "branch", "--show-current"], cwd=root, timeout=3)
    status = run_command(["git", "status", "--short"], cwd=root, timeout=5, max_chars=20000)
    return {
        "head": head.get("stdout", "").strip(),
        "branch": branch.get("stdout", "").strip(),
        "dirty": bool(status.get("stdout", "").strip()),
        "status_short": status.get("stdout", "").splitlines(),
    }


def collect_compose(root: Path, *, tail: int, services: tuple[str, ...], skip_docker: bool) -> dict[str, Any]:
    if skip_docker:
        return {"skipped": True, "reason": "--skip-docker"}

    base = compose_args(root)
    result: dict[str, Any] = {
        "ps": run_command([*base, "ps", "--format", "json"], cwd=root, timeout=15, max_chars=20000),
        "health": {},
        "logs": {},
    }
    ps_stdout = result["ps"].get("stdout", "")
    parsed_ps = parse_json_lines(ps_stdout)
    if parsed_ps:
        result["ps_parsed"] = parsed_ps

    result["health"]["api_health"] = run_command(
        [*base, "exec", "-T", "veritas", "curl", "-sS", "http://localhost:8765/api/health"],
        cwd=root,
        timeout=8,
        max_chars=8000,
    )
    result["health"]["api_health_deep"] = run_command(
        [*base, "exec", "-T", "veritas", "curl", "-sS", "http://localhost:8765/api/health/deep"],
        cwd=root,
        timeout=15,
        max_chars=20000,
    )

    for service in services:
        log_result = run_command(
            [*base, "logs", "--no-color", "--tail", str(tail), service],
            cwd=root,
            timeout=20,
            max_chars=60000,
        )
        stdout = str(log_result.get("stdout") or "")
        stderr = str(log_result.get("stderr") or "")
        result["logs"][service] = {
            "command": {k: v for k, v in log_result.items() if k not in {"stdout", "stderr"}},
            "error_lines": extract_error_lines(stdout + "\n" + stderr),
            "tail": truncate_text(stdout, 20000),
            "stderr": truncate_text(stderr, 6000),
        }
    return result


def summarize(bundle: dict[str, Any]) -> dict[str, Any]:
    signals: list[str] = []
    compose = bundle.get("compose", {})
    host = bundle.get("host_readiness", {})

    for name, info in host.items():
        if name in {"opencode_data", "panel_extraction_weights", "trufor_weights"} and not info.get("exists"):
            signals.append(f"missing host path: {name} -> {info.get('path')}")

    health = compose.get("health", {}) if isinstance(compose, dict) else {}
    for name, command in health.items():
        stdout = command.get("stdout", "")
        if command and not command.get("ok"):
            signals.append(f"{name} command failed")
        health_payload = parse_json_object(stdout) if isinstance(stdout, str) else None
        if health_payload:
            status = health_payload.get("status")
            if status and status != "ok":
                signals.append(f"{name} reports {status}")
            checks = health_payload.get("checks")
            if isinstance(checks, dict):
                for check_name, check in checks.items():
                    if isinstance(check, dict) and check.get("ok") is False:
                        detail = check.get("detail") or check.get("path") or "failed"
                        signals.append(f"{name}.{check_name} failed: {detail}")
        elif isinstance(stdout, str) and '"degraded"' in stdout:
            signals.append(f"{name} reports degraded")

    for service in compose.get("ps_parsed", []) if isinstance(compose, dict) else []:
        if not isinstance(service, dict):
            continue
        health_state = str(service.get("Health") or "")
        state = str(service.get("State") or "")
        name = service.get("Service") or service.get("Name")
        if state and state != "running":
            signals.append(f"compose service {name} state={state}")
        if health_state and not health_state.startswith(("healthy", "running")):
            signals.append(f"compose service {name} health={health_state}")

    logs = compose.get("logs", {}) if isinstance(compose, dict) else {}
    for service, payload in logs.items():
        count = len(payload.get("error_lines") or [])
        if count:
            signals.append(f"{service} has {count} recent error/warning log lines")

    artifacts = bundle.get("artifacts", {})
    for item in artifacts.get("latest_manifests", [])[:1]:
        run_diag = item.get("run_diagnostics") or {}
        quality_flags = run_diag.get("quality_flags") or []
        if quality_flags:
            signals.append(
                f"latest run diagnostics contains {len(quality_flags)} quality flag(s)"
            )
        problem_count = len(item.get("problem_nodes") or [])
        if problem_count:
            signals.append(f"latest audit manifest contains {problem_count} problem nodes")

    return {
        "status": "needs_attention" if signals else "ok",
        "signals": signals[:30],
    }


def render_markdown(bundle: dict[str, Any]) -> str:
    summary = bundle.get("summary", {})
    generated_at = bundle.get("generated_at", "")
    output_json = bundle.get("output_json", "")
    output_md = bundle.get("output_markdown", "")
    lines = [
        "# Veritas Production Diagnostic",
        "",
        f"- Generated: `{generated_at}`",
        f"- Status: `{summary.get('status', 'unknown')}`",
        f"- JSON: `{output_json}`",
        f"- Markdown: `{output_md}`",
        "",
        "## Agent Handoff",
        "",
        "Give the JSON file to the coding agent and ask it to diagnose and patch the issue.",
        "",
        "```text",
        f"Read {output_json}, identify the root cause, patch the repo, and run targeted verification.",
        "```",
        "",
        "## Signals",
        "",
    ]
    signals = summary.get("signals") or []
    if signals:
        lines.extend(f"- {signal}" for signal in signals)
    else:
        lines.append("- No critical signals detected in the collected surface.")

    lines.extend(["", "## Host Readiness", ""])
    for name, info in bundle.get("host_readiness", {}).items():
        state = "ok" if info.get("exists") else "missing"
        lines.append(f"- `{name}`: {state} `{info.get('path')}`")

    lines.extend(["", "## Recent Error Lines", ""])
    logs = bundle.get("compose", {}).get("logs", {}) if isinstance(bundle.get("compose"), dict) else {}
    for service, payload in logs.items():
        error_lines = payload.get("error_lines") or []
        lines.append(f"### {service}")
        if not error_lines:
            lines.append("")
            lines.append("No matched error/warning lines in the collected tail.")
            lines.append("")
            continue
        lines.append("")
        lines.append("```text")
        lines.extend(error_lines[-40:])
        lines.append("```")
        lines.append("")

    lines.extend(["## Latest Audit Artifacts", ""])
    latest = bundle.get("artifacts", {}).get("latest_manifests", [])
    if not latest:
        lines.append("- No audit manifests found under `outputs/`.")
    for item in latest[:3]:
        manifest = item.get("manifest", {})
        top = item.get("manifest_top_level", {})
        lines.append(f"- Manifest: `{manifest.get('path')}`")
        if top:
            lines.append(f"  Summary: `{json.dumps(top, ensure_ascii=False)}`")
        problems = item.get("problem_nodes") or []
        if problems:
            lines.append(f"  Problem nodes: `{len(problems)}`")

    lines.append("")
    return "\n".join(lines)


def collect_bundle(root: Path, *, tail: int, skip_docker: bool) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "project_root": str(root),
        "host": {
            "hostname": socket.gethostname(),
            "user": getpass.getuser(),
            "cwd": str(Path.cwd()),
            "python": sys.version.split()[0],
        },
        "git": collect_git(root),
        "host_readiness": collect_host_readiness(root),
        "compose": collect_compose(root, tail=tail, services=DEFAULT_SERVICES, skip_docker=skip_docker),
        "artifacts": collect_latest_artifacts(root),
    }
    bundle["summary"] = summarize(bundle)
    return bundle


def write_outputs(bundle: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"diagnostic-{stamp}.json"
    md_path = output_dir / f"diagnostic-{stamp}.md"
    latest_json = output_dir / "latest.json"
    latest_md = output_dir / "latest.md"

    bundle["output_json"] = str(json_path)
    bundle["output_markdown"] = str(md_path)
    bundle["summary"] = summarize(bundle)
    markdown = render_markdown(bundle)

    json_text = json.dumps(bundle, indent=2, ensure_ascii=False, default=str)
    json_path.write_text(json_text + "\n", encoding="utf-8")
    latest_json.write_text(json_text + "\n", encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")
    return json_path, md_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--tail", type=int, default=500)
    parser.add_argument("--skip-docker", action="store_true")
    parser.add_argument("--json", action="store_true", help="print the collected bundle")
    parser.add_argument("--fail-on-attention", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    output_dir = args.output_dir or root / "web_data" / "diagnostics"
    bundle = collect_bundle(root, tail=args.tail, skip_docker=args.skip_docker)
    json_path, md_path = write_outputs(bundle, output_dir)

    if args.json:
        print(json.dumps(bundle, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"Diagnostic JSON: {json_path}")
        print(f"Diagnostic Markdown: {md_path}")
        print(f"Latest JSON: {output_dir / 'latest.json'}")
        print(f"Latest Markdown: {output_dir / 'latest.md'}")
        print(f"Status: {bundle['summary']['status']}")
        for signal in bundle["summary"].get("signals", [])[:10]:
            print(f"- {signal}")

    if args.fail_on_attention and bundle["summary"]["status"] != "ok":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
