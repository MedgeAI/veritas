from __future__ import annotations

from pathlib import Path

from engine.reporting.render_json import save_report_json
from engine.reporting.renderers import write_reports
from engine.workflows.execution_verify import run_verification


def handle(manifest: str, output_dir: str, role: str) -> int:
    report = run_verification(manifest, role=role)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "report.json"
    save_report_json(report, json_path)
    paths = write_reports(report, out)

    print(f"Report ID: {report.report_id}")
    print(f"Project: {report.project_name}")
    print(f"Verification Level: {report.verification_level}")
    print(f"Overall Status: {report.overall_status}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {paths['markdown']}")
    print(f"HTML: {paths['html']}")
    return 0
