from __future__ import annotations

import json
from pathlib import Path

from scripts.prod_diagnose import (
    DEFAULT_SERVICES,
    collect_latest_artifacts,
    extract_error_lines,
    redact_text,
    summarize,
)


def test_redact_text_removes_tokens_and_dsn_password() -> None:
    raw = (
        "CLOUDFLARE_TUNNEL_TOKEN:eyJsecret "
        "Authorization: Bearer abc.def "
        "postgresql://user:plainpass@postgres:5432/db"
    )

    redacted = redact_text(raw)

    assert "eyJsecret" not in redacted
    assert "abc.def" not in redacted
    assert "plainpass" not in redacted
    assert "<redacted>" in redacted


def test_extract_error_lines_keeps_recent_matching_lines() -> None:
    raw = "\n".join(
        [
            "INFO ok",
            "WARNING opencode failed",
            "INFO still ok",
            "Traceback (most recent call last)",
            "GET /api/cases -> 500 (4ms)",
        ]
    )

    assert extract_error_lines(raw) == [
        "WARNING opencode failed",
        "Traceback (most recent call last)",
        "GET /api/cases -> 500 (4ms)",
    ]


def test_default_services_include_production_forensics() -> None:
    assert "sila-dense" in DEFAULT_SERVICES
    assert "elis-forensic" in DEFAULT_SERVICES


def test_collect_latest_artifacts_extracts_problem_nodes(tmp_path: Path) -> None:
    report_dir = (
        tmp_path
        / "outputs"
        / "case-1"
        / "research-integrity-audit"
        / "reports"
    )
    report_dir.mkdir(parents=True)
    manifest = {
        "case_id": "case-1",
        "run_id": "run-1",
        "steps": [{"id": "agent_plan", "status": "warning", "error": "failed"}],
    }
    (report_dir / "audit_run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = collect_latest_artifacts(tmp_path)

    latest = result["latest_manifests"][0]
    assert latest["manifest_top_level"] == {"case_id": "case-1", "run_id": "run-1"}
    assert latest["problem_nodes"]


def test_summarize_expands_health_deep_failed_checks() -> None:
    bundle = {
        "host_readiness": {},
        "compose": {
            "health": {
                "api_health_deep": {
                    "ok": True,
                    "stdout": json.dumps(
                        {
                            "status": "degraded",
                            "checks": {
                                "trufor_weights": {
                                    "ok": False,
                                    "detail": "missing",
                                }
                            },
                        }
                    ),
                }
            },
            "logs": {},
        },
        "artifacts": {},
    }

    summary = summarize(bundle)

    assert summary["status"] == "needs_attention"
    assert "api_health_deep reports degraded" in summary["signals"]
    assert "api_health_deep.trufor_weights failed: missing" in summary["signals"]
