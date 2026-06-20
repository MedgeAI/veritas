"""HTML report generation for static audit."""

from engine.static_audit.html_report._core import (
    render_static_audit_html,
    write_static_audit_html,
)

__all__ = ["render_static_audit_html", "write_static_audit_html"]
