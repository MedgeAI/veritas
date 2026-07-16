from __future__ import annotations

import json
from pathlib import Path

from engine.static_audit.run_diagnostics import build_run_diagnostics
from engine.static_audit.paths import resolve_artifact_path


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_build_run_diagnostics_flags_agent_timeout_and_panel_fallback(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "case-1" / "research-integrity-audit"
    manifest = {
        "case_id": "case-1",
        "agent": {
            "roles": [
                {
                    "role_id": "source_data_auditor",
                    "status": "failed",
                    "detail": "opencode timed out after 300s",
                    "metadata": {
                        "failure_type": "timeout",
                        "timeout_seconds": 300,
                    },
                }
            ]
        },
        "steps": [
            {
                "key": "agent_role_source_data_auditor",
                "status": "warning",
                "detail": "timeout",
            }
        ],
    }
    _write_json(
        resolve_artifact_path(workdir, "panel_extraction_quality.json"),
        {
            "summary": {
                "figures": 3,
                "panels": 3,
                "fallbacks": 3,
                "fallback_rate": 1.0,
                "status": "degraded",
            }
        },
    )

    result = build_run_diagnostics(
        workdir,
        case_id="case-1",
        manifest=manifest,
        mirror_to_web_data=False,
    )

    flags = {item["flag"] for item in result["quality_flags"]}
    assert "agent_timeout" in flags
    assert "panel_extraction_all_fallback" in flags
    latest = json.loads(
        resolve_artifact_path(workdir, "run_diagnostics.json").read_text(
            encoding="utf-8"
        )
    )
    assert latest["status"] == "completed_with_warnings"
