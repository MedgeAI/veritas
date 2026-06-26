from __future__ import annotations

from pathlib import Path

from engine.reporting.layers import group_findings_by_layer
from engine.reporting.models import VerificationReport
from engine.reporting.render_html import render_html
from engine.reporting.render_md import render_markdown


def write_reports(report: VerificationReport, output_dir: str | Path) -> dict[str, str]:
    """Write markdown and HTML reports.

    If the report has findings but no layer grouping, automatically group
    the findings by layer before rendering.
    """
    # Auto-group findings by layer if not already set
    if report.findings and not (report.layer_1 or report.layer_2 or report.layer_3):
        # Convert Finding dataclasses to dicts for layer grouping
        finding_dicts = [
            {
                "id": f.id,
                "title": f.title,
                "severity": f.severity,
                "risk_level": f.severity,  # Map severity to risk_level for classification
                "category": f.category,
                "status": f.status,
                "fact": f.fact,
                "inference": f.inference,
                "suggestion": f.suggestion,
                "source": f.source,
            }
            for f in report.findings
        ]
        layers = group_findings_by_layer(finding_dicts)
        report.layer_1 = layers["layer_1"]
        report.layer_2 = layers["layer_2"]
        report.layer_3 = layers["layer_3"]

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = out_dir / "report.md"
    html_path = out_dir / "report.html"
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    return {"markdown": str(markdown_path), "html": str(html_path)}

