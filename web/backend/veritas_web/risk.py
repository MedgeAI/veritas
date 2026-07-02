"""Thin HTTP adapter for risk-related endpoints.

All domain logic (risk ranking, bundle loading, finding summarization)
lives in :mod:`engine.reporting.risk`.  This module re-exports pure
functions and wraps the path-resolving functions so that HTTP callers
can keep their original signatures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.reporting.risk import (
    ISSUE_CATEGORY_ORDER,
    RISK_LEVELS,
    RISK_ORDER,
    issue_category_rank,
    normalize_risk_level,
    risk_rank,
    summarize_findings,
)
from engine.reporting.risk import (
    load_static_audit_bundle as _engine_load_bundle,
)
from engine.reporting.risk import (
    static_audit_bundle_path as _engine_bundle_path,
)

from .path_mapping import normalize_workdir_path

# ---------------------------------------------------------------------------
# Path-resolving wrappers (HTTP-layer adapters)
# ---------------------------------------------------------------------------


def static_audit_bundle_path(
    workdir: str | Path | None, *, output_root: str | Path | None = None
) -> Path | None:
    if not workdir:
        return None
    root = normalize_workdir_path(workdir, output_root=output_root)
    return _engine_bundle_path(root)


def load_static_audit_bundle(
    workdir: str | Path | None, *, output_root: str | Path | None = None
) -> dict[str, Any] | None:
    if not workdir:
        return None
    root = normalize_workdir_path(workdir, output_root=output_root)
    return _engine_load_bundle(root)


__all__ = [
    "ISSUE_CATEGORY_ORDER",
    "RISK_LEVELS",
    "RISK_ORDER",
    "issue_category_rank",
    "load_static_audit_bundle",
    "normalize_risk_level",
    "risk_rank",
    "static_audit_bundle_path",
    "summarize_findings",
]
