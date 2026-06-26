"""Pattern grouping, definitions, and display logic."""
# All f-string interpolations MUST use h() or h_attr() for XSS protection.

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from engine.static_audit.html_report._html_utils import h
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
    key, findings = item
    order = {
        "paired_offset_ratio_reuse": 0,
        "row_vector_reuse": 1,
        "duplicate_numeric_columns": 2,
        "partial_copy_rounding_bias": 3,
        "row_vector_reuse_rounding": 4,
        "formula_derivation": 5,
        "visual_forensics": 6,
        "numeric_forensics": 7,
        "execution_evidence": 8,
        "other": 9,
    }
    return (order.get(key, 7), -len(findings), key)


def pattern_definition(pattern_key: str) -> dict[str, str]:
    definitions = {
        "paired_offset_ratio_reuse": {
            "title": "配对样本固定行偏移与比例复用",
            "thesis": "多个 Source Data sheet 中，配对样本在固定行偏移后反复出现标量关系或两组比例复用；规律只在这里描述一次，具体 sheet/行/列作为证据记录保留。",
            "review_question": "确认这些固定偏移和比例复用是否来自合法配对排序、归一化分母或批量派生，而不是同一数据的重复改写。",
        },
        "row_vector_reuse_rounding": {
            "title": "低维行向量重复与舍入偏差",
            "thesis": "若干 figure 的 Source Data 出现行向量重复、部分复制或四舍五入偏差；该规律可能是模板行、censoring 行或真实重复，也可能提示需要追溯导出过程。",
            "review_question": "核对重复行是否有实验或统计语义，例如 censoring 模板、分组标签、重复测量，或导出时批量复制。",
        },
        "row_vector_reuse": {
            "title": "行向量重复候选",
            "thesis": "Source Data 中存在多行共享相同数值向量；该信号需要结合样本 ID、分组标签、零值矩阵和导出模板判断，不能直接推定为异常。",
            "review_question": "核对重复行是否有实验或统计语义，例如 censoring 模板、分组标签、重复测量、全零矩阵，或导出时批量复制。",
        },
        "duplicate_numeric_columns": {
            "title": "数值列重复候选",
            "thesis": "Source Data 中存在数值列高度相同；需要确认这些列是否为索引列、设计列、共享时间点、全零矩阵或同一指标的合法重复展示。",
            "review_question": "核对重复列的列标题、单位、sheet 注释和对应 figure panel，确认是否为合法索引/设计列、派生列或数据复制。",
        },
        "partial_copy_rounding_bias": {
            "title": "部分复制或舍入偏差候选",
            "thesis": "Source Data 中出现行偏移后的部分复用或舍入后相似；需要追溯导出、四舍五入、格式化和上游计算过程。",
            "review_question": "核对这些相似行/列是否由合法四舍五入、格式化导出或批量处理产生，并要求提供上游原始表格或脚本。",
        },
        "formula_derivation": {
            "title": "公式派生列与固定倍数转换",
            "thesis": "部分列由相邻单元格或同列历史值按固定公式派生。公式本身不是异常，但它会改变 claim 对“原始测量值”的可追溯性。",
            "review_question": "确认论文图表引用的是原始测量值还是派生值，并要求作者说明公式来源、单位换算或归一化逻辑。",
        },
        "visual_forensics": {
            "title": "视觉证据相似或复用候选",
            "thesis": "视觉工具生成了需要人工确认的图像、panel、相似关系或区域级候选；这些信号只能作为复核入口，不能直接作为诚信结论。",
            "review_question": "核对原图、panel、caption、相似方法、分数和最强良性解释，确认是否对应同一主体、合法复用或导出伪影。",
        },
        "numeric_forensics": {
            "title": "PDF 数字取证候选",
            "thesis": "PDF 或表格数字检查生成了统计线索；需要排除 OCR、表格解析、四舍五入和展示层转写造成的伪影。",
            "review_question": "回到原始表格、Source Data 或结果文件，确认数字关系是否能由原始数据和统计流程解释。",
        },
        "execution_evidence": {
            "title": "执行证据与 claim 对账候选",
            "thesis": "运行命令、日志或结果文件与论文 claim 之间存在待核对项；该类 finding 需要回到 runtime manifest 和输出产物验证。",
            "review_question": "核对命令、环境、stdout/stderr、exit code、结果文件 hash 和表述映射是否一致。",
        },
        "other": {
            "title": "其他未归类技术异常",
            "thesis": "这些证据尚未被归入稳定领域规律，需保留原始记录后人工判断。",
            "review_question": "逐条核对 finding 的数据语义、生成过程和论文 claim 影响。",
        },
    }
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
    agent_sentences = pattern_agent_sentences(manual_tasks, risks, reviews)
    if agent_sentences:
        return {
            "title": shorten(first_report_sentence(agent_sentences[0]), 78),
            "thesis": shorten("；".join(agent_sentences[:3]), 260),
            "source": "agent",
        }
    data_sentence = context_aware_review_question(pattern_key, findings)
    if data_sentence and data_sentence != definition.get("review_question"):
        return {
            "title": shorten(first_report_sentence(data_sentence), 78),
            "thesis": shorten(data_sentence, 260),
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
    patterns: list[dict[str, Any]], top_n: int = 20
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
