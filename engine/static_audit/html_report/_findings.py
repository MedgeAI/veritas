"""Finding collection, normalisation, card rendering, and display helpers."""
# All f-string interpolations MUST use h() or h_attr() for XSS protection.

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from engine.static_audit.html_report._html_utils import h
from engine.static_audit.html_report._config import (
    MAX_SAMPLE_ROWS,
    MAX_CLAIMS_PER_GROUP,
    MAX_CLAIM_TEXT_LENGTH,
    PAIR_FORENSICS_CATEGORIES,
)
from engine.static_audit.html_report._shared import (
    _confidence_badge,
    category_label,
    clean_report_text,
    dedupe,
    display_risk_level_for_finding,
    finding_display_score,
    finding_support_value,
    risk_label,
    SOURCE_DATA_FINDINGS_ARTIFACT,
    SOURCE_DATA_PAIR_FORENSICS_ARTIFACT,
    ISSUE_CATEGORY_LABELS,
    CHAPTER_NUMBERS,
    MAX_EVIDENCE_CARDS,
)
from engine.static_audit.html_report._source_data import (
    evidence_locator,
    evidence_sample_text,
    evidence_source_text,
    support_text,
)

# ---------------------------------------------------------------------------
# Finding data helpers
# ---------------------------------------------------------------------------


def source_artifact_for_finding(finding: dict[str, Any]) -> str:
    """Determine which artifact file a finding came from."""
    if finding.get("source_artifact"):
        return str(finding.get("source_artifact"))
    if str(finding.get("category")) in PAIR_FORENSICS_CATEGORIES:
        return SOURCE_DATA_PAIR_FORENSICS_ARTIFACT
    if finding.get("workbook") or finding.get("sheet"):
        return SOURCE_DATA_FINDINGS_ARTIFACT
    return "static_audit_bundle.json"


def source_artifact_for_findings(findings: list[dict[str, Any]]) -> str:
    artifacts = dedupe([source_artifact_for_finding(f) for f in findings])
    return ", ".join(artifacts[:3]) or "-"


def relation_text(finding: dict[str, Any]) -> str:
    llm_text = finding.get("llm_text") or {}
    if llm_text.get("relation_text"):
        return llm_text["relation_text"]
    return f"{finding.get('category', '未知模式')}（LLM 描述未生成）"


def default_finding_summary(finding: dict[str, Any]) -> str:
    columns = (
        finding.get("column_pair")
        or finding.get("columns")
        or finding.get("column")
        or []
    )
    columns_text = (
        ", ".join(str(i) for i in columns)
        if isinstance(columns, list)
        else str(columns)
    )
    if finding.get("workbook") or finding.get("sheet"):
        return f"{finding.get('workbook', '-')} / {finding.get('sheet', '-')} 中 {columns_text or evidence_locator(finding)} 出现 {finding.get('category', '-')}。"
    source = evidence_source_text(finding)
    loc = evidence_locator(finding)
    if source != "-" or loc != "-":
        return f"{source} / {loc} 出现 {finding.get('category', '-')}。"
    return str(finding.get("summary") or finding.get("category") or "技术记录。")


# ---------------------------------------------------------------------------
# Finding collection / normalisation
# ---------------------------------------------------------------------------


def annotate_findings(
    findings: list[dict[str, Any]], source_artifact: str
) -> list[dict[str, Any]]:
    annotated = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        item = dict(f)
        item.setdefault("source_artifact", source_artifact)
        item.setdefault("issue_category", "consistency")
        annotated.append(item)
    return annotated


def source_path_for_evidence_refs(
    evidence_refs: list[Any], bundle: dict[str, Any]
) -> str:
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in (bundle.get("evidence_items") or [])
        if isinstance(item, dict) and item.get("evidence_id")
    }
    paths = []
    for ref in evidence_refs:
        evidence = evidence_by_id.get(str(ref))
        if evidence and evidence.get("source_path"):
            paths.append(str(evidence.get("source_path")))
    return ", ".join(dedupe(paths)[:3])


def normalize_bundle_finding(
    item: dict[str, Any], bundle: dict[str, Any]
) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    finding: dict[str, Any] = dict(metadata) if metadata else {}
    for key in (
        "finding_id",
        "category",
        "risk_level",
        "summary",
        "evidence_refs",
        "claim_refs",
        "benign_explanations",
        "pressure_test_result",
        "manual_review_note",
        "issue_category",
        "suppressed_by",
    ):
        if item.get(key) not in (None, "", []):
            finding[key] = item.get(key)
    finding.setdefault(
        "source_artifact", metadata.get("source_artifact") or "static_audit_bundle.json"
    )
    finding.setdefault("issue_category", "consistency")
    if not finding.get("source_path"):
        finding["source_path"] = source_path_for_evidence_refs(
            finding.get("evidence_refs") or [], bundle
        )
    return finding


def dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        key = str(
            f.get("finding_id") or json.dumps(f, sort_keys=True, ensure_ascii=False)
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(f)
    return result


def collect_report_findings(
    source_findings: dict[str, Any],
    pair_forensics: dict[str, Any],
    bundle: dict[str, Any],
) -> list[dict[str, Any]]:
    suppressed_ids: set[str] = set()
    for item in bundle.get("findings") or []:
        if isinstance(item, dict) and item.get("suppressed_by"):
            suppressed_ids.add(str(item.get("finding_id") or ""))
    findings: list[dict[str, Any]] = []
    findings.extend(
        annotate_findings(
            [
                f
                for f in (source_findings.get("priority_findings") or [])
                if str(f.get("finding_id") or "") not in suppressed_ids
            ],
            SOURCE_DATA_FINDINGS_ARTIFACT,
        )
    )
    findings.extend(
        annotate_findings(
            [
                f
                for f in (pair_forensics.get("priority_findings") or [])
                if str(f.get("finding_id") or "") not in suppressed_ids
            ],
            SOURCE_DATA_PAIR_FORENSICS_ARTIFACT,
        )
    )
    seen = {str(f.get("finding_id")) for f in findings if f.get("finding_id")}
    for item in bundle.get("findings") or []:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("finding_id") or "")
        if fid and fid in seen:
            continue
        normalized = normalize_bundle_finding(item, bundle)
        if fid:
            seen.add(fid)
        findings.append(normalized)
    return sorted(
        dedupe_findings([f for f in findings if not f.get("suppressed_by")]),
        key=lambda f: (
            -finding_display_score(f),
            -finding_support_value(f),
            str(f.get("source_artifact", "")),
            str(f.get("finding_id", "")),
        ),
    )


# ---------------------------------------------------------------------------
# Finding -> mapping / review helpers
# ---------------------------------------------------------------------------


def map_findings_to_mappings(
    mappings: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for mapping in mappings:
        for finding in mapping.get("linked_priority_findings") or []:
            fid = finding.get("finding_id") if isinstance(finding, dict) else None
            if fid:
                result.setdefault(str(fid), []).append(mapping)
    return result


def map_reviews(reviews: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("finding_id")): item for item in reviews if item.get("finding_id")
    }


def risk_for_finding(
    risks: list[dict[str, Any]], finding_id: Any
) -> dict[str, Any] | None:
    if finding_id is None:
        return None
    for risk in risks:
        if str(finding_id) in {str(item) for item in (risk.get("evidence_refs") or [])}:
            return risk
    return None


def paper_refs(mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for mapping in mappings:
        refs.extend(
            ref
            for ref in (mapping.get("matched_paper_references") or [])
            if isinstance(ref, dict)
        )
    return refs


def best_paper_ref(refs: list[dict[str, Any]]) -> dict[str, Any]:
    """Select the best paper reference to display (prefer longer, non-generic refs)."""
    for ref in refs:
        text = str(ref.get("text", ""))
        if "See next page" not in text and len(text) > 40:
            return ref
    return refs[0] if refs else {}


def source_locator(
    finding: dict[str, Any], paper_ref: dict[str, Any]
) -> dict[str, str]:
    """Extract source location info from a paper reference."""
    line_start = paper_ref.get("line_start")
    line_end = paper_ref.get("line_end")
    if line_start and line_end and line_start != line_end:
        line = f"full.md:{line_start}-{line_end}"
    elif line_start:
        line = f"full.md:{line_start}"
    else:
        line = "未定位"
    return {"figure": str(paper_ref.get("match_label") or "-"), "line": line}


def first_claim(mappings: list[dict[str, Any]]) -> str:
    """Extract the first claim text from mappings (truncated to max length)."""
    for mapping in mappings:
        claims = mapping.get("candidate_claims") or []
        if claims and isinstance(claims[0], dict):
            return str(claims[0].get("text", ""))[:MAX_CLAIM_TEXT_LENGTH]
        refs = mapping.get("matched_paper_references") or []
        if refs and isinstance(refs[0], dict):
            return str(refs[0].get("text", ""))[:MAX_CLAIM_TEXT_LENGTH]
    return ""


def review_question(
    source_review: dict[str, Any], risk: dict[str, Any] | None, finding: dict[str, Any]
) -> str:
    llm_text = finding.get("llm_text") or {}
    if llm_text.get("review_question"):
        return llm_text["review_question"]
    if llm_text.get("error"):
        return "LLM 审查问题生成失败，请人工核对原始证据。"
    return "LLM 审查问题未生成，请人工核对原始证据。"


def mapping_granularity_note(finding: dict[str, Any]) -> str:
    sa = source_artifact_for_finding(finding)
    if sa in {SOURCE_DATA_FINDINGS_ARTIFACT, SOURCE_DATA_PAIR_FORENSICS_ARTIFACT}:
        return "当前映射多为 figure/sheet 级，panel/column-block 级仍需人工确认。"
    return "当前映射需要回到原始 artifact、locator 和论文表述逐条确认。"


def pdf_locator_html(paper_ref: dict[str, Any]) -> str:
    page = paper_ref.get("page") or paper_ref.get("page_number")
    bbox = paper_ref.get("bbox")
    if page or bbox:
        parts = []
        if page:
            parts.append(f"page={page}")
        if bbox:
            parts.append(f"bbox={bbox}")
        return f"<code>{h('; '.join(parts))}</code>"
    return '<span class="badge skipped">page/bbox 未记录</span>'


def sample_evidence_html(finding: dict[str, Any]) -> str:
    pairs = finding.get("sample_pairs") or []
    if pairs:
        return sample_pairs_html(pairs)
    sample = evidence_sample_text(finding)
    if sample == "-":
        return "<p class='muted'>没有可展示的样本值、公式或摘要。</p>"
    return f"<p>{h(sample)}</p>"


def sample_pairs_html(samples: list[dict[str, Any]]) -> str:
    """Render sample pairs as HTML rows."""
    if not samples:
        return "<p class='muted'>没有可展示的样本行。</p>"
    rows = [
        f"<div class='sample-row'><div>行 {h(item.get('row', '-'))}</div><div>{h(item.get('left', '-'))}</div><div>{h(item.get('right', '-'))}</div></div>"
        for item in samples[:MAX_SAMPLE_ROWS]
    ]
    return (
        "<div class='samples'><div class='sample-row muted'><div>行</div><div>左列</div><div>右列</div></div>"
        + "".join(rows)
        + "</div>"
    )


# ---------------------------------------------------------------------------
# Finding card rendering
# ---------------------------------------------------------------------------


def evidence_card_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        findings,
        key=lambda item: (
            -finding_display_score(item),
            -int(item.get("support_rows") or item.get("equal_rows") or 0),
            str(item.get("finding_id", "")),
        ),
    )[:MAX_EVIDENCE_CARDS]


def finding_card(
    finding: dict[str, Any],
    mappings: list[dict[str, Any]],
    source_review: dict[str, Any],
    risk: dict[str, Any] | None,
) -> str:
    finding_id = str(finding.get("finding_id", "-"))
    category = str(finding.get("category", "-"))
    risk_level = display_risk_level_for_finding(finding)
    review_badge_class = "context" if risk_level == "context" else "high"
    review_badge_label = "上下文记录" if risk_level == "context" else "人工复核候选"
    relation = relation_text(finding)
    support = support_text(finding)
    refs = paper_refs(mappings)
    first_ref = best_paper_ref(refs)
    locator = source_locator(finding, first_ref)
    benign = (
        source_review.get("benign_explanations")
        or finding.get("benign_explanations")
        or []
    )
    review_action = review_question(source_review, risk, finding)
    sample_rows = sample_evidence_html(finding)
    claim_text = first_claim(mappings)
    risk_reason = (risk or {}).get("reason", "")
    source_artifact = source_artifact_for_finding(finding)
    mapping_note = mapping_granularity_note(finding)
    risk_badge = _confidence_badge("agent") if risk and risk_reason else ""
    anchor_id = f"finding-{finding_id.replace('.', '-').replace(' ', '-')}"

    # Three-layer certainty model
    certainty_layers = _certainty_layers(finding)

    return f"""
<article class="finding-card" id="{h(anchor_id)}">
  <div>
    <div class="finding-title">
      <span class="badge {h(review_badge_class)}">{h(review_badge_label)}</span>
      <span class="badge {h(risk_level)}">{h(risk_label(risk_level))}</span>
      <h3>{h(finding_id)} · {h(category_label(category))}</h3>
    </div>
    <p><strong>复核摘要：</strong>{risk_badge}{h(clean_report_text(risk_reason or default_finding_summary(finding)))}</p>
    {certainty_layers}
    <div class="quote"><strong>关联论文表述：</strong>{h(claim_text or "未自动抽取到论文表述，需人工补映射。")}</div>
    <div class="grid cols-2">
      <div><h3>为什么值得复核</h3><ul><li>{h(relation)}</li><li>{h(support)}</li><li>{h(mapping_note)}</li></ul></div>
      <div><h3>良性解释</h3><ul>{"".join(f"<li>{_confidence_badge('agent')}{h(clean_report_text(item))}</li>" for item in benign[:4]) or "<li class='muted'>未记录。</li>"}</ul></div>
    </div>
    <h3>人工复核动作</h3><p>{h(review_action)}</p>
    <details><summary>样本行</summary>{sample_rows}</details>
    <div class="finding-actions author-only">
      <a href="#manual-review">查看建议与修复</a>
      <button type="button">申诉 / 说明</button>
    </div>
  </div>
  <aside class="lane">
    <h3>证据定位</h3>
    <div class="kv">
      <div>记录 ID</div><div><code>{h(finding_id)}</code></div>
      <div>source</div><div><code>{h(evidence_source_text(finding))}</code></div>
      <div>locator</div><div><code>{h(evidence_locator(finding))}</code></div>
      <div>support</div><div>{h(support)}</div>
      <div>论文 figure</div><div>{h(locator["figure"])}</div>
      <div>full.md 行号</div><div>{h(locator["line"])}</div>
      <div>PDF 定位</div><div>{pdf_locator_html(first_ref)}</div>
      <div>artifact</div><div><code>{h(source_artifact)}</code></div>
    </div>
    <div class="gatekeeper-only" style="margin-top:10px">
      <a class="evidence-link" href="#noise-ledger">查看证据链 &rarr;</a>
    </div>
  </aside>
</article>
"""


def _certainty_layers(finding: dict[str, Any]) -> str:
    """Render the three-layer certainty model HTML for a finding.

    Layers:
      - Fact (always shown if fact text exists): dark background, monospace
      - Inference (if text exists): purple background, italic, with disclaimer
      - Suggestion (if text exists): green background
    Returns empty string if no layer data is present.
    """
    fact = str(finding.get("fact") or "").strip()
    inference = str(finding.get("inference") or "").strip()
    suggestion = str(finding.get("suggestion") or "").strip()

    if not fact and not inference and not suggestion:
        return ""

    parts: list[str] = []
    if fact:
        parts.append(
            f'<div class="certainty-fact">'
            f'<span class="layer-label">事实 · Fact</span>'
            f"<div>{h(fact)}</div>"
            f"</div>"
        )
    if inference:
        parts.append(
            f'<div class="certainty-inference">'
            f'<span class="layer-label">AI 推断 · Inference</span>'
            f"<div>{h(inference)}</div>"
            f'<span class="layer-disclaimer">此为推断，不构成认证结论</span>'
            f"</div>"
        )
    if suggestion:
        parts.append(
            f'<div class="certainty-suggestion">'
            f'<span class="layer-label">建议 · Suggestion</span>'
            f"<div>{h(suggestion)}</div>"
            f"</div>"
        )
    return "".join(parts)


def render_findings_by_category(
    findings: list[dict[str, Any]],
    linked_mapping_by_finding: dict[str, list],
    source_reviews: dict[str, dict],
    judge_risks: list[dict],
) -> str:
    """Group findings by issue_category and render with chapter headings."""
    if not findings:
        return "<p class='muted'>未生成高优先级复核记录。</p>"
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        by_category[finding.get("issue_category", "consistency")].append(finding)
    sections = []
    for category in ["consistency", "matching", "completeness"]:
        category_findings = by_category.get(category, [])
        if not category_findings:
            continue
        chapter = CHAPTER_NUMBERS[category]
        label = ISSUE_CATEGORY_LABELS[category]
        count = len(category_findings)
        cards = "\n".join(
            finding_card(
                finding,
                linked_mapping_by_finding.get(finding.get("finding_id"), []),
                source_reviews.get(finding.get("finding_id"), {}),
                risk_for_finding(judge_risks, finding.get("finding_id")),
            )
            for finding in category_findings
        )
        sections.append(
            f"<div class='category-group'>"
            f"<h3 class='category-heading'>{chapter}、{label} <span class='category-count'>({h(count)} 条)</span></h3>"
            f"{cards}</div>"
        )
    return (
        "\n".join(sections)
        if sections
        else "<p class='muted'>未生成高优先级复核记录。</p>"
    )


def render_findings_by_layer(
    findings: list[dict[str, Any]],
    linked_mapping_by_finding: dict[str, list],
    source_reviews: dict[str, dict],
    judge_risks: list[dict],
) -> str:
    """Group findings by layer (layer_1/layer_2/layer_3) and render with layer headings.

    PRD2-T7: Report layer grouping — Layer 1 = HIGH severity, Layer 2 = MEDIUM, Layer 3 = LOW.
    """
    if not findings:
        return "<p class='muted'>未生成高优先级复核记录。</p>"

    # Group by layer (default to layer_2 if not specified)
    by_layer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        layer = finding.get("_layer", finding.get("layer", "layer_2"))
        by_layer[layer].append(finding)

    layer_labels = {
        "layer_1": ("高置信度发现", "layer-1-high"),
        "layer_2": ("需人工判断", "layer-2-medium"),
        "layer_3": ("其他信号", "layer-3-low"),
    }

    sections = []
    for layer_key in ["layer_1", "layer_2", "layer_3"]:
        layer_findings = by_layer.get(layer_key, [])
        if not layer_findings:
            continue
        label, css_class = layer_labels[layer_key]
        count = len(layer_findings)
        cards = "\n".join(
            finding_card(
                finding,
                linked_mapping_by_finding.get(finding.get("finding_id"), []),
                source_reviews.get(finding.get("finding_id"), {}),
                risk_for_finding(judge_risks, finding.get("finding_id")),
            )
            for finding in layer_findings
        )
        sections.append(
            f'<div class="findings-layer {css_class}">'
            f"<h3>{label} ({h(count)})</h3>"
            f"{cards}</div>"
        )

    return (
        "\n".join(sections)
        if sections
        else "<p class='muted'>未生成高优先级复核记录。</p>"
    )
