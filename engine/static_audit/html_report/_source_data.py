"""Source data evidence text, records tables, pair forensics, and paperfraud section."""
# All f-string interpolations MUST use h() or h_attr() for XSS protection.

from __future__ import annotations

import json
from typing import Any

from engine.static_audit.html_report._html_utils import h
from engine.static_audit.html_report._shared import (
    category_label,
    clean_report_text,
    finding_display_score,
    finding_support_value,
    metric,
    risk_label,
    risk_score,
    shorten,
)


# ---------------------------------------------------------------------------
# Evidence text extraction
# ---------------------------------------------------------------------------


def evidence_source_text(finding: dict[str, Any]) -> str:
    workbook = finding.get("workbook")
    sheet = finding.get("sheet")
    if workbook or sheet:
        return " / ".join(str(item) for item in (workbook, sheet) if item)
    for key in (
        "source_path",
        "image_path",
        "figure_path",
        "artifact_path",
        "source_artifact",
    ):
        if finding.get(key):
            return str(finding.get(key))
    refs = finding.get("evidence_refs") or []
    if refs:
        return ", ".join(str(ref) for ref in refs[:3])
    return "-"


def evidence_locator(finding: dict[str, Any]) -> str:
    columns = (
        finding.get("columns")
        or finding.get("column_pair")
        or finding.get("target_column")
        or finding.get("column")
        or []
    )
    if isinstance(columns, list):
        columns_text = ",".join(str(item) for item in columns)
    else:
        columns_text = str(columns)
    parts = []
    if columns_text:
        parts.append(f"cols={columns_text}")
    if finding.get("row_offset") is not None:
        parts.append(f"row_offset={finding.get('row_offset')}")
    if finding.get("pair_id_offset") is not None:
        parts.append(f"pair_id_offset={finding.get('pair_id_offset')}")
    if finding.get("target_column_label"):
        parts.append(f"label={finding.get('target_column_label')}")
    if finding.get("dominant_formula_pattern"):
        parts.append(f"formula={finding.get('dominant_formula_pattern')}")
    for key in ("figure", "panel_id", "bbox", "page", "line", "cell", "range"):
        if finding.get(key):
            parts.append(f"{key}={finding.get(key)}")
    return "; ".join(parts) or "-"


def evidence_sample_text(finding: dict[str, Any], limit: int = 3) -> str:
    formulas = finding.get("sample_formulas") or []
    if formulas:
        samples = []
        for item in formulas[:limit]:
            if isinstance(item, dict):
                samples.append(f"{item.get('ref', '-')}: {item.get('formula', '-')}")
        return "; ".join(samples) or "-"
    pairs = finding.get("sample_pairs") or []
    if pairs:
        samples = []
        for item in pairs[:limit]:
            if isinstance(item, dict):
                samples.append(
                    f"row {item.get('row', '-')}: {item.get('left', '-')} -> {item.get('right', '-')}"
                )
        return "; ".join(samples) or "-"
    for key in ("sample_rows", "examples", "sample_values"):
        values = finding.get(key) or []
        if values:
            return shorten(json.dumps(values[:limit], ensure_ascii=False), 220)
    if finding.get("dominant_formula_support"):
        return f"{finding.get('dominant_formula_pattern', '-')} ({finding.get('dominant_formula_support')})"
    if finding.get("summary"):
        return shorten(clean_report_text(finding.get("summary")), 220)
    return "-"


def support_text(finding: dict[str, Any]) -> str:
    support = (
        finding.get("support_rows")
        or finding.get("matched_pairs")
        or finding.get("matched_pair_groups")
        or finding.get("duplicate_row_count")
        or finding.get("exact_reuse_pairs")
        or finding.get("equal_rows")
    )
    overlap = (
        finding.get("overlap_rows")
        or finding.get("overlap_pairs")
        or finding.get("overlap_pair_groups")
    )
    pattern_strength = finding.get("pattern_strength")
    if support and overlap:
        base = f"支持行数 {support}/{overlap}，support_rate={finding.get('support_rate', '-')}"
        if pattern_strength:
            return f"{base}，pattern_strength={pattern_strength}"
        return base
    if support:
        base = f"支持行数 {support}"
        if pattern_strength:
            return f"{base}，pattern_strength={pattern_strength}"
        return base
    if pattern_strength:
        return f"support 未记录，pattern_strength={pattern_strength}"
    return "support 未记录"


# ---------------------------------------------------------------------------
# Evidence records table
# ---------------------------------------------------------------------------


def evidence_records_table(
    findings: list[dict[str, Any]], compact: bool = False
) -> str:
    if not findings:
        return "<p class='muted'>该规律下没有可展示证据记录。</p>"
    rows = []
    for finding in findings:
        rows.append(
            "<tr>"
            f"<td><code>{h(finding.get('finding_id', '-'))}</code></td>"
            f"<td>{h(category_label(finding.get('category', '-')))}</td>"
            f"<td class='noise-cell'><code>{h(evidence_source_text(finding))}</code></td>"
            f"<td class='noise-cell'><code>{h(evidence_locator(finding))}</code></td>"
            f"<td>{h(support_text(finding))}</td>"
            f"<td class='noise-cell'>{h(evidence_sample_text(finding, limit=1 if compact else 3))}</td>"
            "</tr>"
        )
    return (
        "<div class='noise-table'><table><thead><tr>"
        "<th>记录 ID</th><th>类别</th><th>来源</th><th>定位</th><th>支持</th><th>样本 / 公式 / 摘要</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


# ---------------------------------------------------------------------------
# PaperFraud rule section
# ---------------------------------------------------------------------------


def paperfraud_rule_section(artifact: dict[str, Any]) -> str:
    summary = (
        artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
    )
    triggered = [
        item
        for item in (artifact.get("triggered_rules") or [])
        if isinstance(item, dict)
    ]
    rows = []
    for item in triggered[:12]:
        rows.append(
            "<tr>"
            f"<td><code>{h(item.get('rule_id', '-'))}</code></td>"
            f"<td>{h(item.get('severity', '-'))}</td>"
            f"<td>{h(clean_report_text(item.get('rule_type', '-')))}</td>"
            f"<td>{h(clean_report_text(item.get('title', '-')))}</td>"
            f"<td>{h(clean_report_text(item.get('evidence', '-')))}</td>"
            f"<td>{h(clean_report_text(item.get('human_review', '-')))}</td>"
            "</tr>"
        )
    table = (
        "<table><thead><tr>"
        "<th>rule_id</th><th>severity</th><th>type</th><th>title</th><th>evidence</th><th>human review</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        if rows
        else "<p class='muted'>未命中规则库提示项，或尚未生成 paperfraud_rule_matches.json。</p>"
    )
    return f"""
      <h2>规则库提示</h2>
      <p class="muted">这些命中是方法学和取证规则提示，只用于整理人工复核问题，不作最终判断。</p>
      <div class="grid cols-4">
        {metric("规则数", summary.get("total_rules_loaded", "-"))}
        {metric("命中数", summary.get("total_triggered", "-"))}
        {metric("methodology", summary.get("methodology_review_triggered", "-"))}
        {metric("取证提示", summary.get("fraud_detection_triggered", "-"))}
      </div>
      {table}
    """


# ---------------------------------------------------------------------------
# Pair forensics tables
# ---------------------------------------------------------------------------


def display_risk_level_for_pair_cluster(cluster: dict[str, Any]) -> str:
    if str(cluster.get("category") or "") == "duplicate_row_vector":
        return "context"
    return str(cluster.get("risk_level") or "medium")


def pair_forensics_table(findings: list[dict[str, Any]]) -> str:
    findings = [f for f in findings if isinstance(f, dict)]
    if not findings:
        return "<p class='muted'>未生成配对/行偏移重点记录。</p>"
    rows = []
    findings = sorted(
        findings,
        key=lambda f: (
            -finding_display_score(f),
            -finding_support_value(f),
            str(f.get("finding_id", "")),
        ),
    )
    for finding in findings[:12]:
        from engine.static_audit.html_report._shared import (
            display_risk_level_for_finding,
        )

        risk_level = display_risk_level_for_finding(finding)
        sup = (
            finding.get("support_rows")
            or finding.get("matched_pairs")
            or finding.get("matched_pair_groups")
            or finding.get("duplicate_row_count")
            or finding.get("exact_reuse_pairs")
            or "-"
        )
        overlap = (
            finding.get("overlap_rows")
            or finding.get("overlap_pairs")
            or finding.get("overlap_pair_groups")
            or "-"
        )
        columns = (
            finding.get("columns")
            or finding.get("column_pair")
            or finding.get("column")
            or []
        )
        columns_text = (
            ", ".join(str(item) for item in columns)
            if isinstance(columns, list)
            else str(columns)
        )
        rows.append(
            "<tr>"
            f"<td><code>{h(finding.get('finding_id', '-'))}</code></td>"
            f"<td><span class='badge {h(risk_level)}'>{h(risk_label(risk_level))}</span></td>"
            f"<td>{h(finding.get('category', '-'))}</td>"
            f"<td><code>{h(finding.get('workbook', '-'))}</code></td>"
            f"<td>{h(finding.get('sheet', '-'))}</td>"
            f"<td>{h(finding.get('row_offset') or finding.get('pair_id_offset') or '-')}</td>"
            f"<td>{h(columns_text or '-')}</td>"
            f"<td>{h(sup)}/{h(overlap)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>ID</th><th>优先级</th><th>类别</th><th>workbook</th><th>sheet</th><th>offset</th><th>columns</th><th>support</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def pair_forensics_review_tasks_table(tasks: list[dict[str, Any]]) -> str:
    from engine.static_audit.html_report._manual_tasks import (
        display_priority_for_pair_task,
        manual_task_focus_score,
    )

    tasks = [t for t in tasks if isinstance(t, dict)]
    if not tasks:
        return "<p class='muted'>未生成配对/行偏移复核项。</p>"
    rows = []
    tasks = sorted(
        tasks,
        key=lambda t: (
            -risk_score(display_priority_for_pair_task(t)),
            manual_task_focus_score(t),
        ),
    )
    for task in tasks[:12]:
        priority = display_priority_for_pair_task(task)
        rows.append(
            "<tr>"
            f"<td><code>{h(task.get('task_id', '-'))}</code></td>"
            f"<td><span class='badge {h(priority)}'>{h(risk_label(priority))}</span></td>"
            f"<td><code>{h(task.get('cluster_id', '-'))}</code></td>"
            f"<td>{h(task.get('category', '-'))}</td>"
            f"<td><code>{h(task.get('workbook', '-'))}</code></td>"
            f"<td>{h(task.get('sheet', '-'))}</td>"
            f"<td>{h(task.get('cluster_count', '-'))}</td>"
            f"<td>{h(task.get('finding_count', '-'))}</td>"
            f"<td>{h(clean_report_text(task.get('question', '-')))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>task</th><th>优先级</th><th>primary cluster</th><th>类别</th><th>workbook</th><th>sheet</th><th>clusters</th><th>raw count</th><th>复核问题</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def pair_forensics_cluster_table(clusters: list[dict[str, Any]]) -> str:
    clusters = [c for c in clusters if isinstance(c, dict)]
    if not clusters:
        return "<p class='muted'>未生成配对/行偏移记录簇。</p>"
    rows = []
    clusters = sorted(
        clusters,
        key=lambda c: (
            -risk_score(display_risk_level_for_pair_cluster(c)),
            -int(c.get("finding_count") or 0),
        ),
    )
    for cluster in clusters[:12]:
        risk = display_risk_level_for_pair_cluster(cluster)
        representatives = ", ".join(
            str(item) for item in (cluster.get("representative_finding_ids") or [])[:5]
        )
        rows.append(
            "<tr>"
            f"<td><code>{h(cluster.get('cluster_id', '-'))}</code></td>"
            f"<td><span class='badge {h(risk)}'>{h(risk_label(risk))}</span></td>"
            f"<td>{h(cluster.get('category', '-'))}</td>"
            f"<td><code>{h(cluster.get('workbook', '-'))}</code></td>"
            f"<td>{h(cluster.get('sheet', '-'))}</td>"
            f"<td>{h(cluster.get('pattern_signature', '-'))}</td>"
            f"<td>{h(cluster.get('finding_count', '-'))}</td>"
            f"<td><code>{h(representatives or '-')}</code></td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>cluster</th><th>优先级</th><th>类别</th><th>workbook</th><th>sheet</th><th>signature</th><th>raw count</th><th>representatives</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Excluded findings section
# ---------------------------------------------------------------------------


def excluded_findings_section(
    excluded: list[dict[str, Any]],
    verdict_summary: dict[str, Any],
) -> str:
    """Render a collapsible section for LLM-excluded false-positive findings."""
    if not excluded:
        return ""
    total = verdict_summary.get("total_findings", 0)
    fp_count = verdict_summary.get("false_positive", 0)
    tp_count = verdict_summary.get("true_positive", 0)
    un_count = verdict_summary.get("uncertain", 0)
    rows = []
    for f in excluded:
        fid = h(str(f.get("finding_id", "")))
        cat = h(str(f.get("category", "")))
        wb = h(str(f.get("workbook", "")))
        sh = h(str(f.get("sheet", "")))
        conf = f.get("llm_verdict_confidence", 0.0)
        expl = h(str(f.get("llm_verdict_explanation", "")))
        pattern = h(str(f.get("llm_sheet_pattern") or ""))
        rows.append(
            f"<tr><td><code>{fid}</code></td><td>{cat}</td><td>{wb} / {sh}</td>"
            f"<td>{pattern}</td><td>{h(f'{conf:.0%}')}</td><td>{expl}</td></tr>"
        )
    return (
        f'<details class="compact-details">'
        f"<summary><span><strong>LLM 语义裁决排除项（{h(fp_count)} 条假阳性）</strong>"
        f'<br/><span class="muted">'
        f"确定性检测产出 {h(total)} 条 Source Data findings，"
        f"LLM 逐 sheet 裁决后排除 {h(fp_count)} 条假阳性，"
        f"保留 {h(tp_count + un_count)} 条待人工复核（TP={h(tp_count)}, uncertain={h(un_count)}）。"
        f"</span></span>"
        f'<span class="badge skipped">展开</span></summary>'
        f'<table class="report-table">'
        f"<thead><tr>"
        f"<th>Finding</th><th>类型</th><th>位置</th>"
        f"<th>良性模式</th><th>置信度</th><th>排除理由</th>"
        f"</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        f"</table>"
        f"</details>"
    )
