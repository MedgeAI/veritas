from __future__ import annotations

import json

from engine.static_audit.orchestrator import run_static_audit, resolve_artifact_path


def test_audit_paper_writes_static_bundle_with_fake_agent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VERITAS_FAKE_OPENCODE", "1")
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n% minimal test fixture\n")

    summary = run_static_audit(
        paper_dir,
        case_id="case-static-test",
        output_root=str(tmp_path / "outputs"),
        fresh=True,
        force=True,
        no_env_file=True,
        agent_mode="review",
    )

    assert summary["exit_code"] == 0
    workdir = tmp_path / "outputs" / "case-static-test" / "research-integrity-audit"
    bundle_path = resolve_artifact_path(workdir, "static_audit_bundle.json")
    material_inventory_path = resolve_artifact_path(workdir, "material_inventory.json")
    material_plan_path = resolve_artifact_path(workdir, "agent_material_plan.json")
    investigation_path = resolve_artifact_path(workdir, "investigation_rounds.jsonl")
    html_path = resolve_artifact_path(workdir, "final_audit_report.html")
    markdown_path = resolve_artifact_path(workdir, "final_audit_report.md")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    traces = {trace["role_id"]: trace for trace in bundle["agent_traces"]}

    assert material_inventory_path.exists()
    assert material_plan_path.exists()
    assert investigation_path.exists()
    assert html_path.exists()

    # Check material plan content
    material_plan = json.loads(material_plan_path.read_text(encoding="utf-8"))
    assert "source_data_xlsx" in material_plan["missing_materials"]

    html = html_path.read_text(encoding="utf-8")
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Veritas 静态审查 Demo" in html
    assert "Agent Investigation Path" in html
    assert "| final_audit_report.html | generated_after_markdown | - |" in markdown
    assert "| final_audit_report.html | missing |" not in markdown
    assert bundle["protocol_version"] == "static_audit_protocol.v1"
    assert bundle["metadata"]["investigation_records"]
    assert len(traces) == 8
    assert traces["claim_extractor"]["status"] == "ran"
    assert traces["source_data_auditor"]["status"] == "ran"
    assert traces["judge"]["status"] == "ran"
    assert traces["visual_triage"]["status"] == "skipped"
