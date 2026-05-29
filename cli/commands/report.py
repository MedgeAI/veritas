from __future__ import annotations

from pathlib import Path

from engine.reporting.render_json import load_report_json
from engine.reporting.renderers import write_reports


def handle(report_json: str, output_dir: str) -> int:
    report = load_report_json(report_json)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = write_reports(report, out)
    print(f"Markdown: {paths['markdown']}")
    print(f"HTML: {paths['html']}")
    return 0
