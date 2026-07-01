from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from web.backend.veritas_web.models import AuditRunRecord, CaseRecord
from web.backend.veritas_web.runner import AuditRunner


def _fake_audit_func(paper_dir: Path, **kwargs: Any) -> dict[str, Any]:
    case_id = kwargs["case_id"]
    output_root = Path(kwargs["output_root"])
    workdir = output_root / case_id / "research-integrity-audit"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "audit_run_manifest.json").write_text('{"steps":[]}\n', encoding="utf-8")
    (workdir / "static_audit_bundle.json").write_text(
        '{"protocol_version":"test"}\n', encoding="utf-8"
    )
    (workdir / "final_audit_report.html").write_text(
        "<html>Veritas static audit</html>", encoding="utf-8"
    )
    return {
        "exit_code": 0,
        "case_id": case_id,
        "workdir": str(workdir),
        "final_html_report": str(workdir / "final_audit_report.html"),
        "run_manifest": str(workdir / "audit_run_manifest.json"),
        "static_audit_bundle": str(workdir / "static_audit_bundle.json"),
        "failed_steps": [],
    }


def test_runner_passes_reproducibility_tier_to_audit_function(tmp_path) -> None:
    captured_kwargs: dict[str, Any] = {}

    def audit_func(paper_dir: Path, **kwargs: Any) -> dict[str, Any]:
        captured_kwargs.update(kwargs)
        return _fake_audit_func(paper_dir, **kwargs)

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "paper.pdf").write_bytes(b"%PDF-1.4\n")

    case = CaseRecord(case_id="tier-case", paper_title="Tier Case")
    run = AuditRunRecord(run_id="run-1", case_id=case.case_id)
    store = MagicMock()
    store.inputs_dir.return_value = inputs
    store.get_run.return_value = run
    store.get_case.return_value = case
    runner = AuditRunner(store, audit_func=audit_func, output_root=tmp_path / "outputs")

    completed = runner.run_sync(
        case.case_id,
        run.run_id,
        {"agent_mode": "review", "reproducibility_tier": "static"},
    )

    assert completed.status == "completed"
    assert captured_kwargs["reproducibility_tier"] == "static"
