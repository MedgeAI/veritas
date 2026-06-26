"""Shared constants and small utility functions for HTML report generation.

This module is the lowest-level dependency in the html_report package.
All other sub-modules may import from here; this module must not import
from sibling sub-modules (except _html_utils).

Most configurable constants are defined in _config.py and re-exported here
for backward compatibility.
"""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any

from engine.static_audit.html_report._html_utils import h

# Re-export configurable constants from _config for backward compatibility
from engine.static_audit.html_report._config import (
    MAX_EVIDENCE_CARDS,
    RISK_LABELS,
    RISK_SCORES,
    STATUS_LABELS,
    CATEGORY_LABELS,
    CONFIDENCE_BADGES,
    ISSUE_CATEGORY_LABELS,
    CHAPTER_NUMBERS,
    HUMAN_TEXT_REPLACEMENTS,
    ROW_VECTOR_SIGNAL_TOKENS,
    STRONGER_SIGNAL_TOKENS,
    SOURCE_DATA_PATTERN_KEYS,
    CONTEXT_ONLY_CATEGORIES,
    PAIR_FORENSICS_CATEGORIES,
)

# ---------------------------------------------------------------------------
# Artifact names (not configurable, used as constants throughout)
# ---------------------------------------------------------------------------

SOURCE_DATA_FINDINGS_ARTIFACT = "source_data_findings.json"
SOURCE_DATA_PAIR_FORENSICS_ARTIFACT = "source_data_pair_forensics.json"

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

CONF_BADGE_RE = re.compile(
    r"<span\s+class=[\"']conf-badge[^\"']*[\"'][^>]*>.*?</span>",
    re.IGNORECASE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Small utility functions
# ---------------------------------------------------------------------------


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def clean_report_text(value: Any) -> str:
    """Strip internal HTML badges if they accidentally enter text artifacts."""
    text = unescape(str(value or ""))
    text = CONF_BADGE_RE.sub("", text)
    text = " ".join(text.split())
    for source, target in HUMAN_TEXT_REPLACEMENTS:
        text = text.replace(source, target)
    return text


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def metric(label: str, value: Any) -> str:
    return f"<div class='metric'><div class='num'>{h(value)}</div><div class='label'>{h(label)}</div></div>"


def list_items(items: list[Any]) -> str:
    if not items:
        return "<li class='muted'>未记录。</li>"
    return "".join(f"<li>{h(clean_report_text(item))}</li>" for item in items)


def status_label(status: Any) -> str:
    """Return human-readable label for a tool/artifact status."""
    return STATUS_LABELS.get(str(status), str(status))


def risk_label(risk: Any) -> str:
    """Return human-readable label for a risk level."""
    return RISK_LABELS.get(str(risk), str(risk))


def risk_score(risk: Any) -> int:
    """Return numeric score for a risk level (for sorting/comparison)."""
    return RISK_SCORES.get(str(risk), 0)


def category_label(category: Any) -> str:
    """Return human-readable label for a finding category."""
    return CATEGORY_LABELS.get(str(category), str(category))


def summary_text(summary: dict[str, Any]) -> str:
    parts = []
    for key, value in summary.items():
        if isinstance(value, (str, int, float)):
            parts.append(f"{key}={str(value)[:90]}")
    return "; ".join(parts[:4]) or "-"


def _confidence_badge(source_type: str) -> str:
    """Return HTML for a small badge indicating the source of an explanation/text element."""
    return CONFIDENCE_BADGES.get(source_type, "")


def has_row_vector_signal_text(text: Any) -> bool:
    normalized = str(text or "").lower()
    return any(token in normalized for token in ROW_VECTOR_SIGNAL_TOKENS)


def has_stronger_signal_text(text: Any) -> bool:
    normalized = str(text or "").lower()
    return any(token in normalized for token in STRONGER_SIGNAL_TOKENS)


def ref_mentions_finding(ref: Any, finding_ids: list[str]) -> bool:
    text = json.dumps(ref, ensure_ascii=False) if isinstance(ref, dict) else str(ref)
    return any(finding_id and finding_id in text for finding_id in finding_ids)


# ---------------------------------------------------------------------------
# Pattern key mapping (placed here to break circular import between
# _patterns.py and _benign.py).
# ---------------------------------------------------------------------------


def pattern_key_for_finding(finding: dict[str, Any]) -> str:
    """Map a finding to its pattern key for grouping and display."""
    category = str(finding.get("category", ""))
    source_artifact = str(finding.get("source_artifact", ""))
    if category in {
        "row_offset_scalar_multiple",
        "long_format_paired_ratio_reuse",
        "long_format_within_pair_ratio_enrichment",
    }:
        return "paired_offset_ratio_reuse"
    if category == "duplicate_row_vector":
        return "row_vector_reuse"
    if category == "row_offset_partial_copy_rounding_bias":
        return "partial_copy_rounding_bias"
    if category == "duplicate_numeric_columns":
        return "duplicate_numeric_columns"
    if category in {
        "formula_derived_column",
        "formula_derived_columns",
        "fixed_ratio",
        "fixed_difference",
    }:
        return "formula_derivation"
    category_text = category.lower()
    source_text = source_artifact.lower()
    if any(
        token in category_text or token in source_text
        for token in (
            "image",
            "visual",
            "panel",
            "trufor",
            "copy_move",
            "cbir",
            "similarity",
            "overlap",
        )
    ):
        return "visual_forensics"
    if any(
        token in category_text or token in source_text
        for token in ("numeric", "benford", "number")
    ):
        return "numeric_forensics"
    if any(
        token in category_text or token in source_text
        for token in ("execution", "command", "runtime")
    ):
        return "execution_evidence"
    if category:
        return f"category:{category}"
    return "other"


# ---------------------------------------------------------------------------
# Finding display helpers (placed here so that _source_data.py and
# _findings.py both import from _shared without circular dependency).
# ---------------------------------------------------------------------------


def is_context_only_finding(finding: dict[str, Any]) -> bool:
    """Check if a finding should be displayed as context-only (lower priority)."""
    return str(finding.get("category") or "") in CONTEXT_ONLY_CATEGORIES


def display_risk_level_for_finding(finding: dict[str, Any]) -> str:
    if is_context_only_finding(finding):
        return "context"
    return str(finding.get("risk_level") or "medium")


def finding_display_score(finding: dict[str, Any]) -> int:
    return risk_score(display_risk_level_for_finding(finding))


def highest_display_risk(findings: list[dict[str, Any]]) -> str:
    levels = [
        display_risk_level_for_finding(finding)
        for finding in findings
        if isinstance(finding, dict)
    ]
    return max(levels, key=risk_score, default="medium")


def finding_support_value(finding: dict[str, Any]) -> int:
    for key in (
        "support_rows",
        "matched_pairs",
        "matched_pair_groups",
        "duplicate_row_count",
        "exact_reuse_pairs",
        "equal_rows",
    ):
        value = finding.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return 0
