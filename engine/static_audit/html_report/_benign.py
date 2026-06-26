"""Benign explanations and context-aware review questions.
# All f-string interpolations MUST use h() or h_attr() for XSS protection.

Contains the parameterized benign explanation dispatchers and the
review-question handlers that generate finding-specific review text
from actual data rather than hardcoded templates.
"""

from __future__ import annotations

from typing import Any

from engine.static_audit.html_report._html_utils import h
from engine.static_audit.html_report._config import (
    MAX_AGENT_BENIGN_FROM_REVIEWS,
    MAX_AGENT_BENIGN_FROM_FINDINGS,
    MAX_BENIGN_EXPLANATIONS_PER_CLUSTER,
)
from engine.static_audit.html_report._shared import (
    _confidence_badge,
    category_label,
    clean_report_text,
    dedupe,
)



def cluster_benign_explanations(
    findings: list[dict[str, Any]], reviews: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    """Return benign explanations as list of (text, source_type) tuples."""
    items: list[tuple[str, str]] = []
    # 1. Agent-generated benign explanations (from investigation)
    for review in reviews:
        for item in (review.get("benign_explanations") or [])[:MAX_AGENT_BENIGN_FROM_REVIEWS]:
            items.append((str(item), "agent"))
    for finding in findings:
        for item in (finding.get("benign_explanations") or [])[:MAX_AGENT_BENIGN_FROM_FINDINGS]:
            items.append((str(item), "agent"))
    # 2. LLM-generated benign explanations
    for finding in findings:
        llm_text = finding.get("llm_text") or {}
        for text in (llm_text.get("benign_explanations") or []):
            items.append((str(text), "llm"))
    # 3. Fallback: LLM failure message
    if not items:
        has_error = any((f.get("llm_text") or {}).get("error") for f in findings)
        if has_error:
            items.append(("LLM 良性解释生成失败，请人工核对原始证据。", "error"))
        else:
            items.append(("LLM 良性解释未生成，请人工核对原始证据。", "info"))
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for text, source_type in items:
        if text and text not in seen:
            seen.add(text)
            deduped.append((text, source_type))
    return deduped[:MAX_BENIGN_EXPLANATIONS_PER_CLUSTER]


def context_aware_review_question(
    pattern_key: str,
    findings: list[dict[str, Any]],
    clusters: list[dict[str, Any]] | None = None,
) -> str:
    """Generate a review question from LLM-enriched finding data."""
    # Find first finding with LLM-generated review question
    for finding in findings:
        llm_text = finding.get("llm_text") or {}
        if llm_text.get("review_question"):
            return llm_text["review_question"]
    # Fallback: LLM failure or not generated
    has_error = any((f.get("llm_text") or {}).get("error") for f in findings)
    if has_error:
        return "LLM 审查问题生成失败，请人工核对该模式的原始记录。"
    return "LLM 审查问题未生成，请人工核对该模式的原始记录。"


def _benign_items_to_html(items: list) -> str:
    """Render benign explanation items (strings or (text, source_type) tuples) as badge HTML."""
    if not items:
        return "<p class='muted'>未记录。</p>"
    parts = []
    for item in items:
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and isinstance(item[1], str)
        ):
            text, source_type = item
            parts.append(
                f"<li>{_confidence_badge(source_type)}{h(clean_report_text(text))}</li>"
            )
        else:
            parts.append(f"<li>{h(clean_report_text(item))}</li>")
    return "<ul>" + "".join(parts) + "</ul>"
