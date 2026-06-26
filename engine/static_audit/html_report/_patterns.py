"""Pattern grouping, definitions, and display logic."""
# All f-string interpolations MUST use h() or h_attr() for XSS protection.

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from engine.static_audit.html_report._html_utils import h
from engine.static_audit.html_report._config import (
    PATTERN_DEFINITIONS,
    PATTERN_SORT_ORDER,
    SOURCE_DATA_PATTERN_KEYS,
    MAX_PRIMARY_PATTERNS,
    MAX_PATTERN_TITLE_LENGTH,
    MAX_PATTERN_THESIS_LENGTH,
    MAX_CLAIMS_PER_GROUP,
    MAX_TASKS_PER_PATTERN,
)
from engine.static_audit.html_report._shared import (
    _confidence_badge,
    category_label,
    clean_report_text,
    dedupe,
    finding_display_score,
    highest_display_risk,
    pattern_key_for_finding,
    ref_mentions_finding,
    risk_label,
    shorten,
)
from engine.static_audit.html_report._benign import (
    _benign_items_to_html,
    cluster_benign_explanations,
    context_aware_review_question,
)


def pattern_sort_key(item: tuple[str, list[dict[str, Any]]]) -> tuple[int, int, str]:
    """Return sort key for pattern groups (lower = higher priority)."""
    key, findings = item
    order = PATTERN_SORT_ORDER.get(key, 7)
    return (order, -len(findings), key)


def pattern_definition(pattern_key: str) -> dict[str, str]:
    """Return the definition (title, thesis, review_question) for a pattern key."""
    definitions = PATTERN_DEFINITIONS
    if pattern_key.startswith("category:"):
        category = pattern_key.split(":", 1)[1]
        label = category_label(category)
        return {
            "title": label,
            "thesis": f"{label} 生成了可复核技术事实候选；报告保留原始定位和证据引用，避免把未知类别压扁成单一 demo 叙事。",
            "review_question": "回到原始 artifact、locator、claim mapping 和人工复核任务，确认该类别在当前论文材料中的真实语义。",
        }
    return definitions.get(pattern_key, definitions["other"])


def key_sheets(clusters: list[dict[str, Any]], limit: int) -> list[str]:
    result: list[str] = []
    for cluster in clusters:
        sheet = str(cluster.get("sheet") or "")
        if sheet and sheet not in result:
            result.append(sheet)
        if len(result) >= limit:
            break
    return result


def factual_pattern_title(pattern_key: str, findings: list[dict[str, Any]]) -> str:
    categories = Counter(
        str(f.get("category") or "") for f in findings if isinstance(f, dict)
    )
    category = next((item for item, _ in categories.most_common() if item), "")
    if category:
        label = category_label(category)
    elif pattern_key.startswith("category:"):
        label = category_label(pattern_key.split(":", 1)[1])
    else:
        label = pattern_key.replace("_", " ")
    return f"{label}：{len(findings)} 条原始记录"


def pattern_agent_sentences(
    manual_tasks: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> list[str]:
    sentences: list[str] = []
    for risk in risks:
        if isinstance(risk, dict) and risk.get("reason"):
            sentences.append(clean_report_text(risk.get("reason")))
    for review in reviews:
        if not isinstance(review, dict):
            continue
        for item in review.get("benign_explanations") or []:
            sentences.append(clean_report_text(item))
            break
    for task in manual_tasks:
        if isinstance(task, dict) and task.get("question"):
            sentences.append(clean_report_text(task.get("question")))
    return dedupe([s for s in sentences if s])


def first_report_sentence(text: str) -> str:
    text = clean_report_text(text)
    for marker in ("需确认", "需要确认", "：确认", ":确认"):
        if marker in text:
            text = text.split(marker, 1)[0]
    parts = re.split(r"(?<=[。！？])\s*", text, maxsplit=1)
    return (parts[0] if parts else text).rstrip("；;:：,， ")


def pattern_display_text(
    pattern_key: str,
    findings: list[dict[str, Any]],
    manual_tasks: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    definition: dict[str, str],
) -> dict[str, str]:
    """Generate display text (title, thesis, source) for a pattern."""
    agent_sentences = pattern_agent_sentences(manual_tasks, risks, reviews)
    if agent_sentences:
        return {
            "title": shorten(first_report_sentence(agent_sentences[0]), MAX_PATTERN_TITLE_LENGTH),
            "thesis": shorten("；".join(agent_sentences[:3]), MAX_PATTERN_THESIS_LENGTH),
            "source": "agent",
        }
    data_sentence = context_aware_review_question(pattern_key, findings)
    if data_sentence and data_sentence != definition.get("review_question"):
        return {
            "title": shorten(first_report_sentence(data_sentence), MAX_PATTERN_TITLE_LENGTH),
            "thesis": shorten(data_sentence, MAX_PATTERN_THESIS_LENGTH),
            "source": "data",
        }
    return {
        "title": factual_pattern_title(pattern_key, findings),
        "thesis": f"该类别未生成摘要；仅保留 {len(findings)} 条原始证据记录。",
        "source": "rule",
    }


def displayable_patterns(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        p
        for p in patterns
        if str(p.get("summary_source") or "") != "rule"
        and not is_context_only_pattern(p)
    ]


def is_context_only_pattern(pattern: dict[str, Any]) -> bool:
    if str(pattern.get("pattern_key") or "") != "row_vector_reuse":
        return False
    findings = [f for f in (pattern.get("findings") or []) if isinstance(f, dict)]
    if not findings:
        return True
    return all(str(f.get("category") or "") == "duplicate_row_vector" for f in findings)


def is_primary_pattern(pattern: dict[str, Any]) -> bool:
    risk = str(pattern.get("risk_level") or "low")
    if risk not in ("critical", "high"):
        return False
    findings = [f for f in (pattern.get("findings") or []) if isinstance(f, dict)]
    return any(str(f.get("issue_category") or "") == "consistency" for f in findings)


def tier_patterns(
    patterns: list[dict[str, Any]], top_n: int = MAX_PRIMARY_PATTERNS
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split patterns into primary (high priority) and secondary tiers."""
    primary = [p for p in patterns if is_primary_pattern(p)][:top_n]
    primary_keys = {
        p.get("pattern_id") if p.get("pattern_id") is not None else id(p)
        for p in primary
    }
    secondary = [
        p
        for p in patterns
        if (p.get("pattern_id") if p.get("pattern_id") is not None else id(p))
        not in primary_keys
    ]
    return primary, secondary


def build_pattern_groups(
    findings: list[dict[str, Any]],
    claim_mappings: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    manual_tasks: list[dict[str, Any]],
    source_reviews: dict[str, dict[str, Any]],
    judge_risks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from engine.static_audit.html_report._clusters import (
        claims_for_finding_ids,
        tasks_for_finding_ids,
    )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        if isinstance(finding, dict):
            grouped[pattern_key_for_finding(finding)].append(finding)
    patterns = []
    for index, (pattern_key, group_findings) in enumerate(
        sorted(grouped.items(), key=pattern_sort_key), start=1
    ):
        group_findings = sorted(
            group_findings,
            key=lambda f: (
                -finding_display_score(f),
                str(f.get("sheet", "")),
                str(f.get("finding_id", "")),
            ),
        )
        definition = pattern_definition(pattern_key)
        finding_ids = [
            str(f.get("finding_id")) for f in group_findings if f.get("finding_id")
        ]
        matched_claims = claims_for_finding_ids(finding_ids, claims, claim_mappings)
        matched_tasks = tasks_for_finding_ids(finding_ids, manual_tasks)
        matched_risks = [
            r
            for r in judge_risks
            if any(
                ref_mentions_finding(ref, finding_ids)
                for ref in (r.get("evidence_refs") or [])
            )
        ]
        reviews = [source_reviews[fid] for fid in finding_ids if fid in source_reviews]
        sheets = sorted({str(f.get("sheet")) for f in group_findings if f.get("sheet")})
        workbooks = sorted(
            {str(f.get("workbook")) for f in group_findings if f.get("workbook")}
        )
        categories = Counter(str(f.get("category", "-")) for f in group_findings)
        risk = highest_display_risk(group_findings)
        display = pattern_display_text(
            pattern_key,
            group_findings,
            matched_tasks,
            matched_risks,
            reviews,
            definition,
        )
        patterns.append(
            {
                "pattern_id": f"P-{index:03d}",
                "pattern_key": pattern_key,
                "title": display["title"],
                "thesis": display["thesis"],
                "summary_source": display["source"],
                "fallback_title": definition["title"],
                "fallback_thesis": definition["thesis"],
                "review_question": definition["review_question"],
                "risk_level": risk,
                "findings": group_findings,
                "finding_ids": finding_ids,
                "sheets": sheets,
                "workbooks": workbooks,
                "categories": categories,
                "claims": matched_claims,
                "manual_tasks": matched_tasks,
                "risks": matched_risks,
                "reviews": reviews,
                "benign_explanations": cluster_benign_explanations(
                    group_findings, reviews
                ),
            }
        )
    return patterns


def pattern_group_cards(patterns: list[dict[str, Any]]) -> str:
    if not patterns:
        return "<p class='muted'>未形成重点事实摘要。请查看原始证据记录。</p>"
    cards = []
    for pattern in patterns:
        source = str(pattern.get("summary_source") or "rule")
        claims = pattern.get("claims") or []
        claim_items = [
            f"<li><code>{h(claim.get('claim_id', '-'))}</code> {h(shorten(claim.get('claim_text') or claim.get('text') or '-', 220))}</li>"
            for claim in claims[:5]
        ] or ["<li class='muted'>未自动关联到具体论文表述，需人工补映射。</li>"]
        _manual = [
            t
            for t in (pattern.get("manual_tasks") or [])
            if isinstance(t, dict) and t.get("question")
        ]
        if _manual:
            task_items = [
                f"<li>{_confidence_badge('data')}{h(shorten(clean_report_text(t.get('question', '')), 180))}</li>"
                for t in _manual[:3]
            ]
        else:
            task_items = [
                f"<li>{_confidence_badge('data')}{h(shorten(context_aware_review_question(pattern.get('pattern_key', 'other'), pattern.get('findings') or []), 260))}</li>"
            ]
        categories = pattern.get("categories") or Counter()
        cards.append(f"""
<article class="pattern-card" id="{h(pattern.get("pattern_id"))}">
  <div class="pattern-head">
    <div class="pattern-id">{h(pattern.get("pattern_id"))}</div>
    <div>
      <div class="pattern-title">
        <span class="badge {h(pattern.get("risk_level"))}">{h(risk_label(pattern.get("risk_level")))}</span>
        {_confidence_badge(source)}<h3>{h(clean_report_text(pattern.get("title")))}</h3>
      </div>
      <p class="pattern-thesis">{_confidence_badge(source)}{h(clean_report_text(pattern.get("thesis")))}</p>
    </div>
    <aside class="pattern-facts">
      <div><span class="muted">原始记录</span><strong>{h(len(pattern.get("findings") or []))}</strong></div>
      <div><span class="muted">sheets</span><strong>{h(len(pattern.get("sheets") or []))}</strong></div>
      <div><span class="muted">论文表述</span><strong>{h(len(claims))}</strong></div>
    </aside>
  </div>
  <div class="grid cols-2 pattern-actions">
    <div><h3>规律出现在哪里</h3><p>{h(", ".join(pattern.get("sheets") or []) or "-")}</p>
    <p class="muted">{h(", ".join(f"{category_label(k)}×{h(v)}" for k, v in categories.most_common()) or "-")}</p></div>
    <div><h3>人工复核问题</h3><ul>{"".join(task_items)}</ul></div>
  </div>
  <details class="section"><summary>展开：关联的论文表述</summary><ul>{"".join(claim_items)}</ul></details>
  <details class="section"><summary>展开：可能良性解释</summary>{_benign_items_to_html(pattern.get("benign_explanations") or [])}</details>
  <details class="section"><summary>展开：不可约证据记录</summary>{_evidence_records_table_import()(pattern.get("findings") or [], compact=True)}</details>
</article>
""")
    return "\n".join(cards)


def _evidence_records_table_import():
    from engine.static_audit.html_report._source_data import evidence_records_table

    return evidence_records_table


def irreducible_evidence_ledger(patterns: list[dict[str, Any]]) -> str:
    if not patterns:
        return "<p class='muted'>未生成不可约证据记录。</p>"
    from engine.static_audit.html_report._source_data import evidence_records_table

    sections = []
    for pattern in sorted(
        patterns,
        key=lambda p: (is_context_only_pattern(p), str(p.get("pattern_id") or "")),
    ):
        sections.append(f"""
<details class="compact-details">
  <summary><span><strong>{h(pattern.get("pattern_id"))} · {h(clean_report_text(pattern.get("title")))}</strong><br/><span class="muted">{h(len(pattern.get("findings") or []))} 条记录 · {h(", ".join(pattern.get("sheets") or []) or "-")}</span></span><span class="badge skipped">展开</span></summary>
  {evidence_records_table(pattern.get("findings") or [])}
</details>
""")
    return "<div class='appendix-grid'>" + "\n".join(sections) + "</div>"
