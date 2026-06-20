from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any

from engine.static_audit.html_report._html_utils import h
from engine.static_audit.investigation import read_investigation_records
from engine.static_audit.paths import resolve_artifact_path

MAX_EVIDENCE_CARDS = 8
SOURCE_DATA_FINDINGS_ARTIFACT = "source_data_findings.json"
SOURCE_DATA_PAIR_FORENSICS_ARTIFACT = "source_data_pair_forensics.json"
ROW_VECTOR_SIGNAL_TOKENS = ("drv-", "duplicate_row_vector", "row vector", "行向量重复")
STRONGER_SIGNAL_TOKENS = (
    "dc-",
    "fr-",
    "fd-",
    "prr-",
    "pds-",
    "roe-",
    "vfc-",
    "数值列重复",
    "固定比例",
    "固定差",
    "配对比例",
    "配对差异",
    "区域完整性",
    "trufor",
    "copy",
)
CONF_BADGE_RE = re.compile(
    r"<span\s+class=[\"']conf-badge[^\"']*[\"'][^>]*>.*?</span>",
    re.IGNORECASE | re.DOTALL,
)
HUMAN_TEXT_REPLACEMENTS = (
    ("可疑伪造区域", "区域完整性记录"),
    ("伪造区域", "区域完整性记录"),
    ("伪造检测", "完整性检测"),
    ("非伪造的图像编辑", "常规图像编辑"),
    ("篡改可能性", "完整性差异"),
    ("图像 manipulations", "图像局部复用问题"),
    ("manipulations", "局部复用问题"),
    ("copy-move 伪造", "局部复用记录"),
    ("增加了机械构造的可能性", "需要确认是否由固定公式或导出流程造成"),
    ("机械构造", "固定生成过程"),
    ("极为罕见", "需要重点确认"),
    ("异常模式指向", "记录集中在"),
    ("异常模式", "记录模式"),
    ("异常狭窄", "过窄"),
    ("异常", "偏离预期"),
    ("可疑模式", "集中模式"),
    ("可疑", "需复核"),
    ("疑似人工凑整", "末位数字集中"),
    ("人为凑整信号", "末位数字集中"),
    ("疑似 p 值集中", "p 值集中"),
    ("疑似", "需复核"),
    ("p-hacking", "p 值集中"),
    ("风险较低", "优先级较低"),
    ("初步判断为", "当前记录显示为"),
    ("高 score 表示神经网络认为这些区域存在完整性差异", "score 较高，需查看 heatmap 和原图"),
    ("虽然可能是", "需确认是否为"),
    ("可能表示", "需确认是否为"),
    ("可能反映", "需确认是否反映"),
    ("可能来自", "需确认是否来自"),
    ("可能由", "需确认是否由"),
    ("可能是", "需确认是否为"),
    ("造假", "数据完整性问题"),
    ("学术不端", "最终判断"),
    ("duplicate_numeric_columns", "数值列重复"),
    ("duplicate_row_vector", "行向量重复"),
    ("paired_difference_too_narrow", "配对差异过窄"),
    ("paired_ratio_reuse", "配对比例复用"),
    ("row_offset_exact_reuse", "固定行偏移重复"),
    ("paperfraud.fraud_detection", "数值取证提示"),
    ("paperfraud.methodology_review", "方法学提示"),
    ("fraud_detection", "数值取证提示"),
    ("fraud-pattern", "取证提示"),
    ("PaperFraud", "规则库"),
    ("claim-to-evidence", "论文表述与证据"),
    ("claim-to-code", "论文表述与代码"),
    ("finding reviews", "复核记录"),
    ("finding review", "复核记录"),
    ("manual tasks", "复核任务"),
    ("Agent review output", "复核输出"),
    ("copy-move", "局部相似"),
    ("copy_move", "局部相似"),
    ("support_rate", "支持率"),
    ("findings", "记录"),
    ("finding", "记录"),
    ("claims", "论文表述"),
    ("claim", "论文表述"),
    ("critical", "高优先级"),
    ("clusters", "证据簇"),
    ("cluster", "证据簇"),
    ("visual.局部相似_dense", "visual.copy_move_dense"),
    ("visual.局部相似", "visual.copy_move"),
    ("论文表述_extractor", "claim_extractor"),
    ("opencode Agent", "opencode 复核"),
    ("Agent Investigation Tool", "调查工具"),
    ("AgentInvestigationPlanner", "调查规划器"),
    ("规则库 规则库", "规则库"),
)

ISSUE_CATEGORY_LABELS = {
    "consistency": "一致性问题",
    "matching": "匹配问题",
    "completeness": "完整性问题",
}

CHAPTER_NUMBERS = {
    "consistency": "一",
    "matching": "二",
    "completeness": "三",
}


def render_findings_by_category(
    findings: list[dict[str, Any]],
    linked_mapping_by_finding: dict[str, list],
    source_reviews: dict[str, dict],
    judge_risks: list[dict],
) -> str:
    """Group findings by issue_category and render with chapter headings."""
    if not findings:
        return "<p class='muted'>未生成高优先级复核记录。</p>"

    # Group findings by issue_category
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        category = finding.get("issue_category", "consistency")
        by_category[category].append(finding)

    # Render each category group
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
            f"<h3 class='category-heading'>{chapter}、{label} <span class='category-count'>({count} 条)</span></h3>"
            f"{cards}"
            f"</div>"
        )

    return "\n".join(sections) if sections else "<p class='muted'>未生成高优先级复核记录。</p>"


def paperfraud_rule_section(artifact: dict[str, Any]) -> str:
    summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
    triggered = [item for item in (artifact.get("triggered_rules") or []) if isinstance(item, dict)]
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
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
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


def visual_evidence_section(workdir: Path) -> str:
    """Generate Visual Evidence Package section for the HTML report.

    Reads visual_evidence.json, panel_evidence.json, image_relationships.json,
    and visual_findings.json from workdir. All text must pass language compliance.
    """
    from engine.static_audit.visual_schemas import check_language_compliance

    visual_evidence = read_json(resolve_artifact_path(workdir, "visual_evidence.json")) or {}
    panel_evidence = read_json(resolve_artifact_path(workdir, "panel_evidence.json")) or {}
    relationships = read_json(resolve_artifact_path(workdir, "image_relationships.json")) or {}
    findings = read_json(resolve_artifact_path(workdir, "visual_findings.json")) or {}

    figures = visual_evidence.get("figures") or []
    panels = panel_evidence.get("panels") or []
    rels = relationships.get("relationships") or []
    visual_findings = findings.get("findings") or []
    visual_clusters = findings.get("finding_clusters") or []
    review_queue = findings.get("review_queue") or []

    # Summary metrics
    figure_count = len(figures)
    panel_count = len(panels)
    rel_count = len(rels)
    finding_count = len(visual_findings)
    cluster_count = len(visual_clusters)
    review_queue_count = len(review_queue)

    # Collect manual review questions
    review_questions: list[str] = []
    for task in review_queue:
        if isinstance(task, dict):
            text = str(task.get("question") or "")
            if text and not check_language_compliance(text):
                review_questions.append(text)
    for finding in visual_findings:
        if isinstance(finding, dict):
            for q in (finding.get("manual_review_questions") or []):
                text = str(q)
                if text and not check_language_compliance(text):
                    review_questions.append(text)
    review_questions = dedupe(review_questions)[:10]

    # Figure/Panel grid
    figure_cards = _visual_figure_cards(figures, panels)
    # Relationship table
    relationship_table = _visual_relationship_table(rels)
    review_queue_table = _visual_review_queue_table(review_queue)
    cluster_table = _visual_cluster_table(visual_clusters)
    # Finding cards
    finding_cards_html = _visual_finding_cards(visual_findings, panels)
    # Manual review checklist
    review_checklist = _visual_review_checklist(review_questions)

    return f"""
    <section class="panel section" id="visual-evidence">
      <h2>图像证据</h2>
      <p class="muted">这里展示图像、panel、相似关系和区域级记录。它们只说明需要复核的位置，不直接给出诚信结论。</p>
      <div class="grid cols-4">
        {metric("figures", figure_count)}
        {metric("panels", panel_count)}
        {metric("relationships", rel_count)}
        {metric("图像记录", finding_count)}
        {metric("证据簇", cluster_count)}
        {metric("复核项", review_queue_count)}
      </div>

      <h3 style="margin-top: 24px;">图像与 panel</h3>
      {figure_cards}

      <h3 style="margin-top: 24px;">相似关系</h3>
      <p class="muted">panel 之间的相似或复用关系，按 score 排序。</p>
      {relationship_table}

      <h3 style="margin-top: 24px;">图像复核入口</h3>
      <p class="muted">按 figure、panel 和相似关系聚合后的复核入口；fallback panel 会降级显示。</p>
      {review_queue_table}

      <h3 style="margin-top: 24px;">图像证据簇</h3>
      <p class="muted">聚合后的图像证据簇，保留代表性记录和 relationship refs。</p>
      {cluster_table}

      <h3 style="margin-top: 24px;">图像记录</h3>
      <p class="muted">代表性原始图像记录，包含 panel 比较和可解释原因。</p>
      {finding_cards_html}

      <h3 style="margin-top: 24px;" class="visual-review-checklist">图像复核清单</h3>
      <p class="muted">汇总需要人工确认的图像问题。</p>
      {review_checklist}
    </section>
    """


def _visual_figure_cards(figures: list[dict[str, Any]], panels: list[dict[str, Any]]) -> str:
    """Generate figure cards with panel thumbnails."""
    if not figures:
        return "<p class='muted'>未提取到 figure 级图像证据。</p>"

    panels_by_figure: dict[str, list[dict[str, Any]]] = {}
    for panel in panels:
        if isinstance(panel, dict):
            parent = str(panel.get("parent_figure_id") or "")
            panels_by_figure.setdefault(parent, []).append(panel)

    cards = []
    for figure in figures[:20]:
        if not isinstance(figure, dict):
            continue
        figure_id = str(figure.get("figure_id") or "-")
        label = str(figure.get("label") or "-")
        caption = str(figure.get("caption") or "")[:200]
        image_path = str(figure.get("source_image_path") or "")
        panel_count = figure.get("panel_count", 0)
        figure_panels = panels_by_figure.get(figure_id, [])

        panel_thumbnails = ""
        if figure_panels:
            panel_items = []
            for panel in figure_panels[:12]:
                panel_id = str(panel.get("panel_id") or "-")
                panel_label = str(panel.get("label") or "-")
                panel_crop = str(panel.get("crop_path") or "")
                panel_w = panel.get("width", 0)
                panel_h = panel.get("height", 0)
                confidence = panel.get("extraction_confidence", 0)
                method = str(panel.get("extraction_method") or "-")
                fallback_note = " | fallback" if method == "whole_figure_fallback" else ""
                img_tag = f'<img src="{h(panel_crop)}" alt="panel {h(panel_label)}" loading="lazy" />' if panel_crop else '<div style="height:120px;background:#f4f0e6;border-radius:8px;"></div>'
                panel_items.append(
                    f'<div class="visual-panel-card">'
                    f'{img_tag}'
                    f'<div class="panel-label">{h(panel_label)}</div>'
                    f'<div class="panel-meta">{h(panel_id)} | {h(panel_w)}x{h(panel_h)} | conf={h(f"{confidence:.2f}")} | {h(method)}{h(fallback_note)}</div>'
                    f'</div>'
                )
            panel_thumbnails = '<div class="visual-panel-grid">' + "".join(panel_items) + '</div>'

        img_tag = f'<img src="{h(image_path)}" alt="figure {h(label)}" loading="lazy" />' if image_path else '<div style="height:180px;background:#f4f0e6;border-radius:12px;"></div>'
        cards.append(
            f'<div class="visual-figure-card">'
            f'{img_tag}'
            f'<h4>{h(label)}</h4>'
            f'<p class="muted">{h(caption)}</p>'
            f'<p class="muted" style="font-size:11px;"><code>{h(figure_id)}</code> | panels: {h(panel_count)}</p>'
            f'{panel_thumbnails}'
            f'</div>'
        )

    return '<div class="visual-figure-grid">' + "\n".join(cards) + '</div>'


def _visual_relationship_table(rels: list[dict[str, Any]]) -> str:
    """Generate relationship table."""
    if not rels:
        return "<p class='muted'>未发现 panel 间相似关系。</p>"

    sorted_rels = sorted(
        [r for r in rels if isinstance(r, dict)],
        key=lambda r: -(r.get("score") or 0),
    )

    rows = []
    for rel in sorted_rels[:30]:
        source = str(rel.get("source_panel_id") or "-")
        target = str(rel.get("target_panel_id") or "-")
        rel_type = str(rel.get("source_type") or "-")
        score = rel.get("score", 0)
        method = str(rel.get("match_method") or "-")
        inliers = rel.get("inlier_count", 0)
        rows.append(
            "<tr>"
            f"<td><code>{h(source)}</code></td>"
            f"<td><code>{h(target)}</code></td>"
            f"<td>{h(rel_type)}</td>"
            f"<td>{h(f'{score:.3f}')}</td>"
            f"<td><code>{h(method)}</code></td>"
            f"<td>{h(inliers)}</td>"
            "</tr>"
        )

    return (
        "<div class='visual-relationship-table'>"
        "<table><thead><tr>"
        "<th>source panel</th><th>target panel</th><th>type</th><th>score</th><th>method</th><th>inliers</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _visual_review_queue_table(tasks: list[dict[str, Any]]) -> str:
    tasks = [task for task in tasks if isinstance(task, dict)]
    if not tasks:
        return "<p class='muted'>未生成图像复核队列。</p>"
    rows = []
    for task in tasks[:20]:
        priority = str(task.get("priority") or "medium")
        quality = str(task.get("panel_extraction_quality") or "unknown")
        quality_note = "fallback 降级" if quality == "whole_figure_fallback" else quality
        rows.append(
            "<tr>"
            f"<td><code>{h(task.get('task_id', '-'))}</code></td>"
            f"<td><span class='badge {h(priority)}'>{h(risk_label(priority))}</span></td>"
            f"<td><code>{h(task.get('cluster_id', '-'))}</code></td>"
            f"<td>{h(task.get('category', '-'))}</td>"
            f"<td>{h(task.get('scope', '-'))}</td>"
            f"<td>{h(', '.join(str(item) for item in (task.get('figure_ids') or [])[:4]) or '-')}</td>"
            f"<td>{h(task.get('finding_count', '-'))}/{h(task.get('relationship_count', '-'))}</td>"
            f"<td>{h(quality_note)}</td>"
            f"<td>{h(clean_report_text(task.get('question', '-')))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>任务</th><th>优先级</th><th>cluster</th><th>类别</th><th>scope</th><th>figures</th><th>记录/关系</th><th>panel quality</th><th>复核问题</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _visual_cluster_table(clusters: list[dict[str, Any]]) -> str:
    clusters = [cluster for cluster in clusters if isinstance(cluster, dict)]
    if not clusters:
        return "<p class='muted'>未生成图像证据簇。</p>"
    rows = []
    for cluster in clusters[:20]:
        risk = str(cluster.get("risk_level") or "medium")
        quality = str(cluster.get("panel_extraction_quality") or "unknown")
        representatives = ", ".join(str(item) for item in (cluster.get("representative_finding_ids") or [])[:5])
        rows.append(
            "<tr>"
            f"<td><code>{h(cluster.get('cluster_id', '-'))}</code></td>"
            f"<td><span class='badge {h(risk)}'>{h(risk_label(risk))}</span></td>"
            f"<td>{h(cluster.get('category', '-'))}</td>"
            f"<td>{h(cluster.get('scope', '-'))}</td>"
            f"<td>{h(', '.join(str(item) for item in (cluster.get('figure_ids') or [])[:4]) or '-')}</td>"
            f"<td>{h(cluster.get('finding_count', '-'))}/{h(cluster.get('relationship_count', '-'))}</td>"
            f"<td>{h(cluster.get('max_score', '-'))}</td>"
            f"<td>{h(quality)}</td>"
            f"<td><code>{h(representatives or '-')}</code></td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>cluster</th><th>优先级</th><th>类别</th><th>scope</th><th>figures</th><th>记录/关系</th><th>max score</th><th>panel quality</th><th>代表记录</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _panel_lookup(panels: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        panel_id = str(panel.get("panel_id") or "")
        if panel_id:
            lookup[panel_id] = panel
        parent = str(panel.get("parent_figure_id") or "")
        if parent:
            lookup.setdefault(parent, panel)
    return lookup


def _resolve_panel(panel_id: str, panels_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if panel_id in panels_by_id:
        return panels_by_id[panel_id]
    if panel_id and not panel_id.endswith("-01"):
        candidate = f"{panel_id}-01"
        if candidate in panels_by_id:
            return panels_by_id[candidate]
    return {}


def _visual_img(path: str, label: str) -> str:
    if not path:
        return '<div class="visual-placeholder">未生成图像</div>'
    return f'<img src="{h(path)}" alt="{h(label)}" loading="lazy" />'


def _visual_finding_cards(visual_findings: list[dict[str, Any]], panels: list[dict[str, Any]]) -> str:
    """Generate visual finding cards with overlay comparison."""
    if not visual_findings:
        return "<p class='muted'>未生成图像记录。</p>"

    from engine.static_audit.visual_schemas import check_language_compliance

    panels_by_id = _panel_lookup(panels)

    cards = []
    for finding in visual_findings[:20]:
        if not isinstance(finding, dict):
            continue

        finding_id = str(finding.get("finding_id") or "-")
        category = str(finding.get("category") or "-")
        risk_level = str(finding.get("risk_level") or "medium")
        raw_summary = str(finding.get("summary") or "")
        summary = clean_report_text(raw_summary)

        # Check language compliance
        violations = check_language_compliance(raw_summary)
        if violations:
            summary = "该图像记录的原始摘要包含报告禁用措辞，已隐藏；请人工复核结构化证据。"

        source_panel_id = str(finding.get("source_panel_id") or "-")
        target_panel_id = str(finding.get("target_panel_id") or "-")
        score = finding.get("score", 0)
        overlay_path = finding.get("overlay_path")
        metadata = finding.get("metadata") if isinstance(finding.get("metadata"), dict) else {}
        quality = str(metadata.get("panel_extraction_quality") or "unknown")
        quality_note = "fallback panel evidence; risk display capped" if quality == "whole_figure_fallback" else quality

        # Get panel crop paths
        source_panel = _resolve_panel(source_panel_id, panels_by_id)
        target_panel = _resolve_panel(target_panel_id, panels_by_id)
        source_crop = str(source_panel.get("crop_path") or "")
        target_crop = str(target_panel.get("crop_path") or "")

        benign = finding.get("benign_explanations") or []
        benign_items = []
        for item in benign[:4]:
            text = str(item)
            if not check_language_compliance(text):
                benign_items.append(f"<li>{h(clean_report_text(text))}</li>")
        benign_html = "<ul>" + "".join(benign_items) + "</ul>" if benign_items else "<p class='muted'>未记录良性解释。</p>"

        # Overlay comparison
        overlay_html = ""
        if overlay_path:
            overlay_html = (
                f'<div class="overlay-compare">'
                f'<div><p class="muted" style="font-size:11px;">source panel: {h(source_panel_id)}</p>'
                f'{_visual_img(source_crop, "source")}</div>'
                f'<div><p class="muted" style="font-size:11px;">target panel: {h(target_panel_id)}</p>'
                f'{_visual_img(target_crop, "target")}</div>'
                f'<div><p class="muted" style="font-size:11px;">overlay / heatmap</p>'
                f'{_visual_img(str(overlay_path), "overlay")}</div>'
                f'</div>'
                f'<p class="muted" style="font-size:11px;margin-top:8px;">overlay: <code>{h(str(overlay_path))}</code></p>'
            )
        elif source_crop and target_crop:
            overlay_html = (
                f'<div class="overlay-compare">'
                f'<div><p class="muted" style="font-size:11px;">source panel: {h(source_panel_id)}</p>'
                f'{_visual_img(source_crop, "source")}</div>'
                f'<div><p class="muted" style="font-size:11px;">target panel: {h(target_panel_id)}</p>'
                f'{_visual_img(target_crop, "target")}</div>'
                f'</div>'
            )
        cap_reason = metadata.get("confidence_adjustment") or metadata.get("risk_cap_reason")
        cap_note = (
            f'<span> | risk note: {h(cap_reason)}</span>'
            if cap_reason
            else ""
        )

        cards.append(
            f'<article class="visual-finding-card">'
            f'<div class="finding-header">'
            f'<span class="badge {h(risk_level)}">{h(risk_label(risk_level))}</span>'
            f'<span class="badge">{h(category)}</span>'
            f'<h3>{h(finding_id)}</h3>'
            f'</div>'
            f'<p><strong>摘要：</strong>{h(summary)}</p>'
            f'<p class="muted" style="font-size:12px;">score: {h(f"{score:.3f}")} | panel quality: {h(quality_note)} | source: <code>{h(source_panel_id)}</code> | target: <code>{h(target_panel_id)}</code>{cap_note}</p>'
            f'<details style="margin-top:12px;">'
            f'<summary>Panel 比较与 overlay</summary>'
            f'{overlay_html}'
            f'</details>'
            f'<details style="margin-top:8px;">'
            f'<summary>良性解释</summary>'
            f'{benign_html}'
            f'</details>'
            f'</article>'
        )

    return "\n".join(cards)


def _visual_review_checklist(questions: list[str]) -> str:
    """Generate manual review checklist."""
    if not questions:
        return "<p class='muted'>未生成视觉复核问题。</p>"

    items = [f"<li>{_confidence_badge('data')}{h(q)}</li>" for q in questions[:10]]
    return "<ul class='visual-review-checklist'>" + "".join(items) + "</ul>"


def render_static_audit_html(workdir: Path, case_id: str) -> str:
    def _load(name: str) -> Any:
        return read_json(resolve_artifact_path(workdir, name)) or {}

    manifest = _load("audit_run_manifest.json")
    bundle = _load("static_audit_bundle.json")
    material_inventory = _load("material_inventory.json")
    material_plan = _load("agent_material_plan.json")
    source_findings = _load("source_data_findings.json")
    pair_forensics = _load("source_data_pair_forensics.json")
    source_profile = _load("source_data_profile.json")
    numeric = _load("numeric_forensics.json")
    ledger = _load("evidence_ledger.json")
    exact_images = _load("exact_image_duplicates.json")
    similarity = _load("image_similarity_candidates.json")
    paperfraud_matches = _load("paperfraud_rule_matches.json")
    agent_judge = _load("agent_judge.json")
    source_auditor = _load("agent_source_data_auditor.json")
    claim_extractor = _load("agent_claim_extractor.json")
    investigation_records = read_investigation_records(workdir)
    verdict_data = _load("source_data_findings_verdict.json")

    # Build LLM verdict lookup: finding_id → verdict info
    verdict_by_id: dict[str, dict[str, Any]] = {}
    for sv in verdict_data.get("sheets", []):
        for fv in sv.get("findings", []):
            fid = fv.get("id")
            if fid:
                verdict_by_id[fid] = fv

    primary_findings = collect_report_findings(source_findings, pair_forensics, bundle)

    # Annotate findings with LLM verdicts, then split into active vs excluded
    excluded_findings: list[dict[str, Any]] = []
    active_findings: list[dict[str, Any]] = []
    for f in primary_findings:
        fid = str(f.get("finding_id", ""))
        vv = verdict_by_id.get(fid)
        if vv:
            f["llm_verdict"] = vv.get("verdict", "uncertain")
            f["llm_verdict_confidence"] = vv.get("confidence", 0.0)
            f["llm_verdict_explanation"] = vv.get("explanation", "")
            f["llm_sheet_pattern"] = verdict_by_id.get(fid, {}).get("benign_pattern")
        if vv and vv.get("verdict") == "false_positive":
            excluded_findings.append(f)
        else:
            active_findings.append(f)

    verdict_summary = verdict_data.get("summary", {})
    mappings = source_findings.get("claim_to_source_data") or []
    canonical_claims = bundle.get("claims") or []
    canonical_mappings = bundle.get("claim_mappings") or []
    linked_mapping_by_finding = map_findings_to_mappings(mappings)
    source_reviews = map_reviews(source_auditor.get("finding_reviews") or [])
    manual_tasks = source_auditor.get("manual_review_tasks") or []
    judge_risks = agent_judge.get("risk_suggestions") or []
    traces = bundle.get("agent_traces") or []
    tool_runs = manifest.get("steps") or bundle.get("tool_runs") or []

    ledger_stats = ledger.get("stats") or {}
    material_summary = material_inventory.get("summary") or {}
    source_summary = source_findings.get("summary") or {}
    pair_summary = pair_forensics.get("summary") or {}
    profile_summary = source_profile.get("summary") or {}
    judge_summary = agent_judge.get("summary") or {}
    bundle_counts = {
        "evidence_items": len(bundle.get("evidence_items") or []),
        "claims": len(bundle.get("claims") or []),
        "findings": len(bundle.get("findings") or []),
        "claim_mappings": len(bundle.get("claim_mappings") or []),
        "agent_traces": len(traces),
    }

    evidence_clusters = build_evidence_clusters(
        active_findings,
        source_auditor.get("claim_to_source_data") or [],
        claim_extractor.get("claims") or canonical_claims,
        manual_tasks,
        source_reviews,
        judge_risks,
    )
    cluster_cards = evidence_cluster_cards(evidence_clusters)
    pattern_findings = dedupe_findings(
        active_findings
        + annotate_findings(
            source_findings.get("formula_derived_columns") or [],
            SOURCE_DATA_FINDINGS_ARTIFACT,
        )
    )
    patterns = build_pattern_groups(
        pattern_findings,
        source_auditor.get("claim_to_source_data") or [],
        claim_extractor.get("claims") or canonical_claims,
        manual_tasks,
        source_reviews,
        judge_risks,
    )
    summarized_patterns = displayable_patterns(patterns)
    pattern_cards = pattern_group_cards(summarized_patterns)
    evidence_ledger_html = irreducible_evidence_ledger(patterns)
    hero_summary = executive_summary(
        summarized_patterns,
        active_findings,
        bundle_counts,
        profile_summary,
        exact_images,
    )
    verdict = report_verdict(active_findings, manual_tasks, tool_runs, bundle)

    card_findings = evidence_card_findings(active_findings)
    priority_record_count = sum(1 for finding in active_findings if finding_display_score(finding) >= risk_score("high"))
    card_title = (
        f"代表性证据卡（展示 {len(card_findings)} / {len(active_findings)} 条）"
        if active_findings
        else "重点人工复核证据卡"
    )
    cards = render_findings_by_category(
        card_findings,
        linked_mapping_by_finding,
        source_reviews,
        judge_risks,
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Veritas 静态审查 Demo · {h(case_id)}</title>
  <style>
    :root {{
      --bg: #f3efe4;
      --paper: #fffdf7;
      --ink: #20241d;
      --muted: #687064;
      --line: #d8d0bf;
      --accent: #1e5c4f;
      --accent2: #a35f26;
      --danger: #9b3d2f;
      --soft: #f8f3e8;
      --green: #dfeee7;
      --amber: #f4e1bf;
      --red: #f2d7d0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 0%, rgba(30, 92, 79, .18), transparent 28rem),
        radial-gradient(circle at 86% 12%, rgba(163, 95, 38, .16), transparent 30rem),
        linear-gradient(180deg, #f6f0e3 0%, #ede6d7 100%);
      font: 15px/1.55 "Alegreya Sans", "Noto Serif SC", "Source Han Serif SC", Georgia, serif;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    code {{ font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace; font-size: 12px; }}
    .wrap {{ max-width: 1440px; margin: 0 auto; padding: 28px; }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.04fr) minmax(420px, .96fr);
      gap: 20px;
      align-items: stretch;
      margin-bottom: 20px;
    }}
    .panel {{
      background: rgba(255, 253, 247, .92);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: 0 22px 60px rgba(54, 45, 28, .10);
      padding: 24px;
    }}
    .hero-brief {{
      display: flex;
      flex-direction: column;
      min-height: 560px;
      color: #fffaf0;
      background:
        radial-gradient(circle at 12% 20%, rgba(244, 225, 191, .20), transparent 18rem),
        linear-gradient(135deg, #18251f 0%, #214f45 56%, #7f4b25 140%);
      border-color: rgba(255, 250, 240, .24);
    }}
    .hero-brief .eyebrow,
    .hero-brief .muted {{
      color: rgba(255, 250, 240, .72);
    }}
    .hero-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-bottom: 28px;
    }}
    .meta-chip {{
      display: inline-flex;
      max-width: 100%;
      align-items: center;
      border: 1px solid rgba(255, 250, 240, .24);
      border-radius: 999px;
      padding: 5px 10px;
      color: rgba(255, 250, 240, .78);
      background: rgba(255, 250, 240, .08);
      font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
      font-size: 11px;
      overflow-wrap: anywhere;
    }}
    .verdict-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 18px;
    }}
    .verdict-badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 8px 12px;
      color: #2b1810;
      background: #f4e1bf;
      border: 1px solid rgba(244, 225, 191, .8);
      font-weight: 900;
      letter-spacing: .02em;
    }}
    .verdict-badge.outline {{
      color: rgba(255, 250, 240, .86);
      background: rgba(255, 250, 240, .06);
      border-color: rgba(255, 250, 240, .28);
    }}
    .hero-brief h1 {{
      max-width: 920px;
      color: #fffdf7;
      font-size: clamp(42px, 5.3vw, 82px);
      letter-spacing: -.055em;
    }}
    .hero-brief .lead {{
      max-width: 980px;
      color: rgba(255, 250, 240, .86);
      font-size: clamp(18px, 1.55vw, 24px);
      line-height: 1.5;
    }}
    .hero-stat-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: auto;
      padding-top: 28px;
    }}
    .hero-stat {{
      border: 1px solid rgba(255, 250, 240, .22);
      border-radius: 18px;
      padding: 14px;
      background: rgba(255, 250, 240, .08);
    }}
    .hero-stat .num {{
      color: #fffdf7;
      font-size: 32px;
      line-height: 1;
      font-weight: 900;
      letter-spacing: -.04em;
    }}
    .hero-stat .label {{
      margin-top: 8px;
      color: rgba(255, 250, 240, .68);
      font-size: 13px;
    }}
    .action-panel {{
      display: flex;
      flex-direction: column;
      gap: 18px;
    }}
    .hero-evidence-list {{
      display: grid;
      gap: 12px;
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .hero-evidence-list li {{
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: #fffaf0;
    }}
    .evidence-kicker {{
      color: var(--accent);
      font-weight: 900;
      font-size: 13px;
    }}
    .action-list {{
      display: grid;
      gap: 8px;
      margin: 0;
      padding-left: 20px;
      color: #3f463c;
    }}
    .pattern-card {{
      border: 1px solid var(--line);
      border-radius: 30px;
      padding: 24px;
      background:
        linear-gradient(135deg, rgba(255,253,247,.96) 0%, rgba(255,247,233,.96) 100%);
      box-shadow: 0 18px 48px rgba(54, 45, 28, .08);
      margin-bottom: 18px;
      content-visibility: auto;
      contain-intrinsic-size: 360px;
    }}
    .pattern-head {{
      display: grid;
      grid-template-columns: 72px minmax(0, 1fr) minmax(220px, .34fr);
      gap: 18px;
      align-items: start;
    }}
    .pattern-id {{
      display: grid;
      place-items: center;
      width: 58px;
      height: 58px;
      border-radius: 18px;
      color: #fffaf0;
      background: var(--accent);
      font-weight: 900;
      letter-spacing: -.03em;
    }}
    .pattern-title {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }}
    .pattern-title h3 {{
      font-size: 24px;
    }}
    .pattern-thesis {{
      font-size: 18px;
      color: #343b31;
      margin: 0;
    }}
    .pattern-facts {{
      display: grid;
      gap: 8px;
      border-left: 4px solid var(--accent);
      padding-left: 14px;
    }}
    .pattern-facts div {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid rgba(216, 208, 191, .65);
      padding-bottom: 6px;
    }}
    .pattern-actions {{
      display: grid;
      gap: 12px;
      margin-top: 18px;
    }}
    .noise-table {{
      margin-top: 12px;
      overflow-x: auto;
    }}
    .noise-cell {{
      max-width: 320px;
      overflow-wrap: anywhere;
    }}
    .eyebrow {{ color: var(--accent); font-weight: 800; letter-spacing: .08em; text-transform: uppercase; font-size: 12px; }}
    h1, h2, h3 {{ margin: 0; line-height: 1.1; }}
    h1 {{ font-size: clamp(34px, 5vw, 68px); letter-spacing: -.04em; margin-top: 10px; }}
    h2 {{ font-size: 26px; margin-bottom: 16px; }}
    h3 {{ font-size: 18px; margin-bottom: 10px; }}
    .lead {{ max-width: 900px; font-size: 19px; color: #3f463c; margin: 18px 0 0; }}
    .muted {{ color: var(--muted); }}
    .grid {{ display: grid; gap: 16px; }}
    .cols-4 {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    .cols-3 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .cols-2 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .metric {{ border: 1px solid var(--line); border-radius: 18px; padding: 16px; background: #fffaf0; }}
    .metric .num {{ font-size: 34px; line-height: 1; font-weight: 900; letter-spacing: -.04em; }}
    .metric .label {{ color: var(--muted); margin-top: 8px; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 800;
      border: 1px solid var(--line);
      background: #fff;
      white-space: nowrap;
    }}
    .badge.critical {{ background: #f4c7bd; color: #6b1e16; border-color: #e4a99d; }}
    .badge.high {{ background: var(--red); color: #6b1e16; border-color: #e4b4aa; }}
    .badge.medium, .badge.warning {{ background: var(--amber); color: #70430f; border-color: #e3c48d; }}
    .badge.low, .badge.info, .badge.context {{ background: #ece7dc; color: #625a4c; }}
    .badge.ran, .badge.reused {{ background: var(--green); color: #214d3e; border-color: #bdd8ca; }}
    .badge.skipped {{ background: #ece7dc; color: #625a4c; }}
    .section {{ margin-top: 20px; }}
    .panel.section, .cluster-card, .compact-details, .finding-card {{
      content-visibility: auto;
      contain-intrinsic-size: 280px;
    }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 18px;
      margin-bottom: 16px;
    }}
    .quick-nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }}
    .quick-nav a {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 7px 12px;
      background: rgba(255,255,255,.62);
      font-weight: 800;
      font-size: 13px;
    }}
    .brief-list {{
      display: grid;
      gap: 10px;
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .brief-list li {{
      display: grid;
      grid-template-columns: 28px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
    }}
    .rank {{
      display: inline-grid;
      place-items: center;
      width: 28px;
      height: 28px;
      border-radius: 999px;
      background: var(--accent);
      color: #fffaf0;
      font-weight: 900;
      font-size: 12px;
    }}
    .cluster-card {{
      border: 1px solid var(--line);
      border-radius: 28px;
      padding: 22px;
      background: linear-gradient(135deg, #fffdf8 0%, #fff4df 100%);
      box-shadow: 0 18px 48px rgba(54, 45, 28, .08);
      margin-bottom: 16px;
    }}
    .cluster-top {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 280px;
      gap: 18px;
    }}
    .cluster-title {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-bottom: 12px;
    }}
    .signal-list {{
      display: grid;
      gap: 8px;
      margin: 12px 0 0;
      padding-left: 18px;
    }}
    .compact-details > summary {{
      list-style: none;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      padding: 4px 0;
    }}
    .compact-details > summary::-webkit-details-marker {{ display: none; }}
    .appendix-grid {{
      display: grid;
      gap: 14px;
    }}
    .finding-card {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      gap: 18px;
      padding: 20px;
      border: 1px solid var(--line);
      border-radius: 24px;
      background: linear-gradient(135deg, #fffdf8 0%, #fff7e9 100%);
      margin-bottom: 16px;
    }}
    .finding-title {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }}
    .kv {{ display: grid; grid-template-columns: 130px minmax(0, 1fr); gap: 8px 12px; font-size: 14px; }}
    .kv div:nth-child(odd) {{ color: var(--muted); }}
    .quote {{ border-left: 4px solid var(--accent); padding: 10px 12px; background: #f4f0e6; border-radius: 0 12px 12px 0; margin: 10px 0; }}
    .samples {{ display: grid; gap: 8px; margin-top: 10px; }}
    .sample-row {{ display: grid; grid-template-columns: 52px 1fr 1fr; gap: 8px; font-family: "JetBrains Mono", monospace; font-size: 12px; }}
    .lane {{ padding: 10px; border: 1px solid var(--line); border-radius: 14px; background: rgba(255,255,255,.72); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 8px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .artifact-list {{ display: grid; gap: 8px; }}
    .artifact {{ display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--line); }}
    details {{ border: 1px solid var(--line); border-radius: 16px; padding: 12px 14px; background: rgba(255,255,255,.65); }}
    summary {{ cursor: pointer; font-weight: 800; }}
    .footer {{ margin: 24px 0 8px; color: var(--muted); text-align: center; }}
    @media (max-width: 980px) {{
      .hero, .finding-card, .cluster-top, .pattern-head, .hero-stat-grid, .cols-4, .cols-3, .cols-2 {{ grid-template-columns: 1fr; }}
      .hero-brief {{ min-height: auto; }}
      .section-head {{ align-items: flex-start; flex-direction: column; }}
      .wrap {{ padding: 14px; }}
      .panel {{ padding: 18px; border-radius: 18px; }}
    }}
    .category-group {{ margin-bottom: 32px; }}
    .category-heading {{
      font-size: 18px;
      font-weight: 700;
      color: var(--ink);
      margin: 0 0 16px 0;
      padding-bottom: 8px;
      border-bottom: 2px solid var(--accent);
    }}
    .category-count {{
      font-size: 14px;
      font-weight: 400;
      color: var(--muted);
      margin-left: 8px;
    }}
    /* Visual Evidence Package styles */
    .visual-figure-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }}
    .visual-figure-card {{
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 16px;
      background: linear-gradient(135deg, #fffdf8 0%, #fff7e9 100%);
      box-shadow: 0 12px 32px rgba(54, 45, 28, .06);
    }}
    .visual-figure-card img {{
      width: 100%;
      height: 180px;
      object-fit: cover;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #f4f0e6;
    }}
    .visual-figure-card h4 {{
      margin: 12px 0 8px;
      font-size: 16px;
    }}
    .visual-figure-card .muted {{
      font-size: 13px;
    }}
    .visual-panel-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}
    .visual-panel-card {{
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px;
      background: #fffaf0;
    }}
    .visual-panel-card img {{
      width: 100%;
      height: 120px;
      object-fit: cover;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #f4f0e6;
    }}
    .visual-panel-card .panel-label {{
      font-weight: 800;
      margin-top: 8px;
      font-size: 14px;
    }}
    .visual-panel-card .panel-meta {{
      font-size: 11px;
      color: var(--muted);
      margin-top: 4px;
    }}
    .visual-relationship-table {{
      margin-top: 16px;
    }}
    .visual-finding-card {{
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 20px;
      background: linear-gradient(135deg, #fffdf8 0%, #fff4df 100%);
      box-shadow: 0 18px 48px rgba(54, 45, 28, .08);
      margin-bottom: 16px;
    }}
    .visual-finding-card .finding-header {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }}
    .visual-finding-card .overlay-compare {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}
    .visual-finding-card .overlay-compare img {{
      width: 100%;
      height: 160px;
      object-fit: cover;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #f4f0e6;
    }}
    .visual-placeholder {{
      display: grid;
      place-items: center;
      width: 100%;
      height: 160px;
      border-radius: 12px;
      border: 1px dashed var(--line);
      background: #f4f0e6;
      color: var(--muted);
      font-size: 12px;
    }}
    .visual-review-checklist {{
      margin-top: 16px;
    }}
    .visual-review-checklist li {{
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255,255,255,.65);
      margin-bottom: 8px;
    }}
    .conf-badge {{ display: inline-flex; align-items: center; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-right: 4px; font-weight: 600; }}
    .conf-rule {{ background: #e8e0d0; color: #5a5040; }}
    .conf-data {{ background: #dfeee7; color: #1e5c4f; }}
    .conf-agent {{ background: #e0e8f4; color: #2c4a7c; }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <div class="panel hero-brief">
        <div class="hero-meta">
          <span class="eyebrow">Veritas 投稿前技术复核</span>
          <span class="meta-chip">case_id: {h(case_id)}</span>
          <span class="meta-chip">静态材料复核</span>
        </div>
        <div class="verdict-row">
          <span class="verdict-badge">{h(verdict["label"])}</span>
          <span class="verdict-badge outline">非科研诚信定论</span>
          <span class="verdict-badge outline">{h(verdict["depth"])}</span>
        </div>
        <h1>投稿前技术复核：<br/>{h(verdict["headline"])}</h1>
        <p class="lead">{_confidence_badge("data")}{h(hero_summary)}</p>
        <div class="hero-stat-grid">
          {hero_metric("重点摘要", len(summarized_patterns))}
          {hero_metric("需优先复核记录", priority_record_count)}
          {hero_metric("表述映射", bundle_counts["claim_mappings"])}
          {hero_metric("Source Data 覆盖", source_coverage_value(profile_summary))}
        </div>
      </div>
      <aside class="panel action-panel">
        <div>
          <div class="eyebrow">先看这里</div>
          <h2>{h("重点事实" if summarized_patterns else "覆盖范围")}</h2>
          <p class="muted">这里只放已经形成摘要的事实；没有摘要的类别只保留原始定位和值。</p>
        </div>
        {hero_pattern_list(summarized_patterns)}
        <div>
          <h3>下一步动作</h3>
          {hero_action_list(manual_tasks)}
        </div>
        <nav class="quick-nav" aria-label="report shortcuts">
          <a href="#top-patterns">重点事实</a>
          <a href="#noise-ledger">原始证据</a>
          <a href="#claim-impact">表述对照</a>
          <a href="#manual-review">人工复核</a>
          <a href="#appendix">技术附录</a>
        </nav>
      </aside>
    </section>

    <section class="section" id="top-patterns">
      <div class="section-head">
        <div>
          <h2>重点事实</h2>
          <p class="muted">这里按相同规律合并展示。没有摘要的类别不进入本区，只在原始证据记录中保留。</p>
        </div>
        <span class="badge high">{h(len(summarized_patterns))} 类</span>
      </div>
      {pattern_cards}
    </section>

    <section class="panel section" id="noise-ledger">
      <h2>原始证据记录</h2>
      <p class="muted">这里不做叙事压缩，只保留每条记录的编号、来源、定位、支持行数、样本值、公式或摘要。</p>
      {evidence_ledger_html}
    </section>

    <section class="panel section" id="claim-impact">
      <h2>论文表述对照</h2>
      <p class="muted">把论文表述、证据引用和复核记录放在一张表里，方便判断哪些表述需要优先核对。</p>
      {claim_impact_matrix(source_auditor.get("claim_to_source_data") or [], claim_extractor.get("claims") or canonical_claims, canonical_mappings)}
    </section>

    <section class="panel section" id="manual-review">
      <h2>人工复核清单</h2>
      <p class="muted">这些问题是报告的行动入口。Veritas 不替代人工判断，只把最值得核对的 workbook、sheet、row/column 和论文表述列出来。</p>
      {manual_tasks_table(manual_tasks)}
    </section>

    <section class="panel section" id="paperfraud-rules">
      {paperfraud_rule_section(paperfraud_matches)}
    </section>

    <section class="panel section" id="coverage">
      <h2>覆盖范围与限制</h2>
      <div class="grid cols-4">
        {metric("证据记录", ledger_stats.get("ledger_items", "-"))}
        {metric("数值单元格", profile_summary.get("numeric_cell_count", "-"))}
        {metric("公式单元格", profile_summary.get("formula_count", "-"))}
        {metric("复核轨迹", bundle_counts["agent_traces"])}
      </div>
      <ul>
        {list_items(collect_limitations(bundle, agent_judge, similarity))}
      </ul>
    </section>

    {visual_evidence_section(workdir)}

    <section class="section" id="appendix">
      <h2>技术附录</h2>
      <div class="appendix-grid">
        <details class="compact-details">
          <summary><span><strong>材料清单与可用数据</strong><br/><span class="muted">输入材料、材料处理计划和可执行的数据通道。</span></span><span class="badge skipped">展开</span></summary>
          {material_plan_panel(material_summary, material_plan)}
        </details>

        <details class="compact-details">
          <summary><span><strong>调查路径</strong><br/><span class="muted">系统选择确定性工具后的调查轨迹。</span></span><span class="badge skipped">展开</span></summary>
          <p class="muted">系统先提出待查方向，再由编排器校验工具、执行检查并记录产物。</p>
          {investigation_table(investigation_records)}
        </details>

        <details class="compact-details">
          <summary><span><strong>论文表述与证据映射</strong><br/><span class="muted">完整表述映射和确定性脚手架。</span></span><span class="badge skipped">展开</span></summary>
          <div class="grid cols-3">
            {metric("论文表述", len(canonical_claims))}
            {metric("映射记录", len(canonical_mappings))}
            {metric("确定性脚手架", len(mappings))}
          </div>
          {canonical_mapping_table(canonical_claims, canonical_mappings)}
        </details>

        <details class="compact-details">
          <summary><span><strong>来源聚类索引</strong><br/><span class="muted">按来源和定位聚类，作为重点事实视图的补充索引。</span></span><span class="badge skipped">展开</span></summary>
          {cluster_cards}
        </details>

        <details class="compact-details">
          <summary><span><strong>{h(card_title)}</strong><br/><span class="muted">单条记录级证据卡，保留给技术复查使用。</span></span><span class="badge skipped">展开</span></summary>
          {cards}
        </details>

        <details class="compact-details">
          <summary><span><strong>Source Data 配对与行偏移检查</strong><br/><span class="muted">配对数据、固定行偏移、低宽度行重复和比例复用记录。</span></span><span class="badge skipped">展开</span></summary>
          <div class="grid cols-4">
            {metric("重点记录", pair_summary.get("priority_findings", 0))}
            {metric("记录簇", pair_summary.get("finding_clusters", 0))}
            {metric("复核项", pair_summary.get("review_tasks", 0))}
            {metric("row-offset scalar", pair_summary.get("row_offset_scalar_findings", 0))}
            {metric("paired ratio reuse", pair_summary.get("paired_ratio_reuse_findings", 0))}
          </div>
          <h3>复核项</h3>
          {pair_forensics_review_tasks_table(pair_forensics.get("review_tasks") or [])}
          <h3>记录簇</h3>
          {pair_forensics_cluster_table(pair_forensics.get("finding_clusters") or [])}
          <h3>代表性原始记录</h3>
          {pair_forensics_table(pair_forensics.get("priority_findings") or [])}
        </details>

        {excluded_findings_section(excluded_findings, verdict_summary)}

        <details class="compact-details">
          <summary><span><strong>运行步骤与复核轨迹</strong><br/><span class="muted">运行步骤、状态和各复核步骤的输出路径。</span></span><span class="badge skipped">展开</span></summary>
          <div class="grid cols-2">
            <div>
              <h3>执行状态</h3>
              {steps_table(tool_runs)}
            </div>
            <div>
              <h3>复核步骤</h3>
              {traces_table(traces)}
            </div>
          </div>
        </details>

        <details class="compact-details">
          <summary><span><strong>确定性检查摘要</strong><br/><span class="muted">Source Data、PDF 数字取证和图像检查的原始摘要。</span></span><span class="badge skipped">展开</span></summary>
          <div class="grid cols-3">
            <div class="lane">
              <h3>Source Data</h3>
              <div class="kv">
                <div>workbook 数</div><div>{h(profile_summary.get("workbook_count", "-"))}</div>
                <div>sheet 数</div><div>{h(profile_summary.get("sheet_count", "-"))}</div>
                <div>重复列记录</div><div>{h(source_summary.get("duplicate_column_findings", "-"))}</div>
                <div>固定关系记录</div><div>{h(source_summary.get("fixed_relationship_findings", "-"))}</div>
                <div>错误数</div><div>{h(source_summary.get("errors", "-"))}</div>
              </div>
            </div>
            <div class="lane">
              <h3>PDF 数字取证</h3>
              <div class="kv">
                <div>提取数字数</div><div>{h(numeric.get("all_number_count", "-"))}</div>
                <div>有效数字数</div><div>{h(numeric.get("number_count", "-"))}</div>
                <div>表格数</div><div>{h(numeric.get("table_count", "-"))}</div>
                <div>Benford MAD</div><div>{h((numeric.get("benford") or {}).get("mad", (numeric.get("benford") or {}).get("mean_absolute_deviation", "-")))}</div>
              </div>
            </div>
            <div class="lane">
              <h3>图像检查</h3>
              <div class="kv">
                <div>图片数</div><div>{h(exact_images.get("image_count", "-"))}</div>
                <div>字节级重复组</div><div>{h(exact_images.get("duplicate_group_count", "-"))}</div>
                <div>近似重复状态</div><div>{h(status_label(similarity.get("status", "-")))}</div>
                <div>方法</div><div>{h(similarity.get("method", "-"))}</div>
              </div>
            </div>
          </div>
        </details>

        <details class="compact-details">
          <summary><span><strong>产物链接与复核摘要</strong><br/><span class="muted">原始 JSON/Markdown 产物和结构化复核摘要。</span></span><span class="badge skipped">展开</span></summary>
          {artifact_links(workdir)}
          <h3>整体复核摘要</h3>
          <p>{h(clean_report_text(judge_summary_text(judge_summary, claim_extractor, source_auditor)))}</p>
          <h3>复核摘要</h3>
          {risks_table(judge_risks)}
          <h3>论文表述抽取摘要</h3>
          <p>表述数：{h(len(claim_extractor.get("claims") or []))}；限制说明数：{h(len(claim_extractor.get("limitations") or []))}</p>
        </details>
      </div>
    </section>
    <div class="footer">生成时间：{h(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))}。报告只展示技术记录和复核入口，关键结论必须人工确认。</div>
  </main>
</body>
</html>
"""


def write_static_audit_html(workdir: Path, case_id: str) -> Path:
    path = resolve_artifact_path(workdir, "final_audit_report.html")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_static_audit_html(workdir, case_id), encoding="utf-8")
    return path


def collect_report_findings(
    source_findings: dict[str, Any],
    pair_forensics: dict[str, Any],
    bundle: dict[str, Any],
) -> list[dict[str, Any]]:
    findings = []
    findings.extend(
        annotate_findings(
            source_findings.get("priority_findings") or [],
            SOURCE_DATA_FINDINGS_ARTIFACT,
        )
    )
    findings.extend(
        annotate_findings(
            pair_forensics.get("priority_findings") or [],
            SOURCE_DATA_PAIR_FORENSICS_ARTIFACT,
        )
    )

    seen = {str(finding.get("finding_id")) for finding in findings if finding.get("finding_id")}
    for item in bundle.get("findings") or []:
        if not isinstance(item, dict):
            continue
        finding_id = str(item.get("finding_id") or "")
        if finding_id and finding_id in seen:
            continue
        normalized = normalize_bundle_finding(item, bundle)
        if finding_id:
            seen.add(finding_id)
        findings.append(normalized)
    return sorted(
        dedupe_findings(findings),
        key=lambda finding: (
            -finding_display_score(finding),
            -finding_support_value(finding),
            str(finding.get("source_artifact", "")),
            str(finding.get("finding_id", "")),
        ),
    )


def annotate_findings(findings: list[dict[str, Any]], source_artifact: str) -> list[dict[str, Any]]:
    annotated = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        item = dict(finding)
        item.setdefault("source_artifact", source_artifact)
        item.setdefault("issue_category", "consistency")
        annotated.append(item)
    return annotated


def normalize_bundle_finding(item: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    finding = dict(metadata)
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
    ):
        if item.get(key) not in (None, "", []):
            finding[key] = item.get(key)
    finding.setdefault("source_artifact", metadata.get("source_artifact") or "static_audit_bundle.json")
    finding.setdefault("issue_category", "consistency")
    if not finding.get("source_path"):
        finding["source_path"] = source_path_for_evidence_refs(finding.get("evidence_refs") or [], bundle)
    return finding


def source_path_for_evidence_refs(evidence_refs: list[Any], bundle: dict[str, Any]) -> str:
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


def report_verdict(
    findings: list[dict[str, Any]],
    manual_tasks: list[dict[str, Any]],
    tool_runs: list[dict[str, Any]],
    bundle: dict[str, Any],
) -> dict[str, str]:
    statuses = {str(step.get("status")) for step in tool_runs if isinstance(step, dict)}
    max_risk = max((finding_display_score(finding) for finding in findings), default=0)
    has_review_work = bool(findings or manual_tasks)
    has_failed_tool = "failed" in statuses
    has_warning_tool = "warning" in statuses

    if max_risk >= risk_score("critical"):
        label = "需优先复核"
        headline = "发现高优先级复核项"
        result = "fail"
    elif has_review_work or has_failed_tool or has_warning_tool:
        label = "需人工复核"
        headline = "发现待核对记录"
        result = "warning"
    else:
        label = "未见高优先级项"
        headline = "未见高优先级复核项"
        result = "pass"

    return {
        "label": label,
        "headline": headline,
        "result": result,
        "depth": audit_depth_label(bundle, tool_runs),
    }


def audit_depth_label(bundle: dict[str, Any], tool_runs: list[dict[str, Any]]) -> str:
    step_keys = {str(step.get("key") or step.get("step_key")) for step in tool_runs if isinstance(step, dict)}
    evidence_count = len(bundle.get("evidence_items") or [])
    claim_mapping_count = len(bundle.get("claim_mappings") or [])
    execution_status = (bundle.get("execution_status") or {}).get("status")
    if not evidence_count and not step_keys:
        return "V0 coverage"
    if execution_status == "ran":
        return "V4 coverage"
    if claim_mapping_count or len(bundle.get("agent_traces") or []):
        return "V3 coverage"
    if {"source_data_profile", "source_data_findings", "source_data_pair_forensics", "exact_image_duplicates"} & step_keys:
        return "V2 coverage"
    return "V1 coverage"


def executive_summary(
    patterns: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    bundle_counts: dict[str, int],
    profile_summary: dict[str, Any],
    exact_images: dict[str, Any],
) -> str:
    source_coverage = source_coverage_text(profile_summary)
    image_count = exact_images.get("image_count", "-")
    workbook_count = profile_summary.get("workbook_count", "-")
    sheet_count = profile_summary.get("sheet_count", "-")
    claim_mapping_count = bundle_counts.get("claim_mappings", 0)
    pattern_clause = summary_pattern_clause(patterns)

    if not findings:
        return (
            "本次静态技术复核未生成高优先级复核记录。"
            f"当前 {source_coverage}、"
            f"{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
            "仍需结合材料完整性和人工抽查确认。"
        )

    has_visual_critical = (
        _has_pattern_type(patterns, "visual_forensics")
        and any(
            str(f.get("risk_level")) in {"critical", "high"}
            for p in patterns
            if "visual_forensics" in str(p.get("pattern_key", ""))
            for f in (p.get("findings") or [])
        )
    )
    sd_keys = {
        "paired_offset_ratio_reuse",
        "row_vector_reuse_rounding",
        "row_vector_reuse",
        "duplicate_numeric_columns",
        "partial_copy_rounding_bias",
        "formula_derivation",
    }
    source_data_pattern_keys = {
        str(p.get("pattern_key", ""))
        for p in patterns
        if str(p.get("pattern_key", "")) in sd_keys
    }
    has_multiple_sd_patterns = len(source_data_pattern_keys) >= 2
    has_source_data_findings = (
        _has_pattern_type(patterns, "paired_offset")
        or _has_pattern_type(patterns, "row_vector")
        or _has_pattern_type(patterns, "duplicate_numeric_columns")
        or _has_pattern_type(patterns, "partial_copy_rounding_bias")
        or _has_pattern_type(patterns, "formula_derivation")
        or _has_pattern_type(patterns, "numeric_forensics")
    )
    has_only_completeness = (
        all(str(p.get("pattern_key", "")) in {"other", "category:source_data_missing"} for p in patterns)
        and patterns
    )

    if has_visual_critical and has_source_data_findings:
        visual_count = _count_pattern_findings(patterns, "visual_forensics")
        sd_count = len(findings) - visual_count
        return (
            f"本次静态技术复核形成 {visual_count} 条图像复核记录、"
            f"{sd_count} 条 Source Data 复核记录，{pattern_clause}"
            f"当前已覆盖 {workbook_count} 个 workbook / {sheet_count} 个 sheet、"
            f"{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
            "这些记录只用于安排人工复核，不作诚信结论。"
        )

    if has_multiple_sd_patterns:
        sd_count = len(findings)
        sheet_set: set[str] = set()
        for p in patterns:
            if str(p.get("pattern_key", "")) in sd_keys:
                sheet_set.update(str(s) for s in (p.get("sheets") or []))
        sheet_text = "、".join(sorted(sheet_set)[:3]) or "多个 sheet"
        return (
            f"本次静态技术复核在 Source Data 中形成 {sd_count} 条复核记录，"
            f"涉及 {len(source_data_pattern_keys)} 类模式，跨 {sheet_text} 等多个 sheet，{pattern_clause}"
            f"当前已覆盖 {workbook_count} 个 workbook / {sheet_count} 个 sheet、"
            f"{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
            "这些记录只用于安排人工复核，不作诚信结论。"
        )

    if has_visual_critical:
        visual_count = _count_pattern_findings(patterns, "visual_forensics")
        return (
            f"本次静态技术复核在图像层面形成 {visual_count} 条复核记录，"
            f"{pattern_clause}"
            f"当前 {source_coverage}、"
            f"{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
            "这些记录只用于安排人工复核，不作诚信结论。"
        )

    if has_source_data_findings:
        return (
            f"本次静态技术复核在 Source Data 层面形成 {len(findings)} 条复核记录，"
            f"{pattern_clause}"
            f"当前 {source_coverage}、"
            f"{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
            "这些记录只用于安排人工复核，不作诚信结论。"
        )

    if has_only_completeness:
        missing_count = sum(1 for f in findings if str(f.get("category")) == "source_data_missing")
        return (
            f"本次静态技术复核主要发现材料完整性问题：{missing_count} 个 figure 缺少对应 Source Data，"
            f"{pattern_clause}"
            f"当前 {source_coverage}、{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
            "材料缺失只说明当前提交包不完整，需先补充材料后再做技术复核。"
        )

    return (
        f"本次静态技术复核生成 {len(findings)} 条高优先级复核记录，"
        f"{pattern_clause}"
        f"当前 {source_coverage}、"
        f"{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
        "这些记录只用于安排人工复核，不作诚信结论。"
    )


def summary_pattern_clause(patterns: list[dict[str, Any]]) -> str:
    pattern_titles = [str(pattern.get("title")) for pattern in patterns[:3] if pattern.get("title")]
    if not pattern_titles:
        return "未形成重点摘要；原始证据记录保留在原始证据记录区。"
    return f"形成 {len(patterns)} 类重点摘要：{'、'.join(pattern_titles)}。"


def source_coverage_value(profile_summary: dict[str, Any]) -> str:
    workbook_count = profile_summary.get("workbook_count")
    sheet_count = profile_summary.get("sheet_count")
    if workbook_count is None and sheet_count is None:
        return "未选择"
    return f"{workbook_count if workbook_count is not None else '-'} / {sheet_count if sheet_count is not None else '-'}"


def source_coverage_text(profile_summary: dict[str, Any]) -> str:
    workbook_count = profile_summary.get("workbook_count")
    sheet_count = profile_summary.get("sheet_count")
    if workbook_count is None and sheet_count is None:
        return "未形成 Source Data workbook/sheet 覆盖指标"
    return f"已覆盖 {workbook_count if workbook_count is not None else '-'} 个 workbook / {sheet_count if sheet_count is not None else '-'} 个 sheet"


def hero_pattern_list(patterns: list[dict[str, Any]]) -> str:
    if not patterns:
        return "<p class='muted'>未形成重点摘要。请查看原始证据记录。</p>"
    rows = []
    for index, pattern in enumerate(patterns[:3], start=1):
        source = str(pattern.get("summary_source") or "rule")
        rows.append(
            "<li>"
            f"<span class='rank'>{h(index)}</span>"
            "<span>"
            f"{_confidence_badge(source)}<span class='evidence-kicker'>{h(pattern.get('title'))}</span><br/>"
            f"{h(clean_report_text(pattern.get('thesis')))}"
            "</span>"
            "</li>"
        )
    return "<ol class='hero-evidence-list'>" + "".join(rows) + "</ol>"


def hero_action_list(tasks: list[dict[str, Any]]) -> str:
    visible_tasks = [
        task
        for task in tasks
        if isinstance(task, dict) and not is_context_only_manual_task(task)
    ]
    visible_tasks = sorted(visible_tasks, key=manual_task_focus_score)
    questions = [
        shorten(clean_report_text(task.get("question", "")), 150)
        for task in visible_tasks[:3]
        if task.get("question")
    ]
    if not questions:
        questions = [
            "核对材料清单、PDF 解析、Source Data、图像和代码材料是否完整。",
            "要求作者补充缺失的原始数据、导出过程、分析脚本或结果文件。",
            "把后续生成的复核记录与论文表述逐条对账，确认是否需要补充材料或说明。",
        ]
    return "<ul class='action-list'>" + list_items(questions) + "</ul>"


def manual_task_focus_score(task: dict[str, Any]) -> int:
    combined = manual_task_text(task)
    has_row_vector = has_row_vector_signal_text(combined)
    has_stronger = has_stronger_signal_text(combined)
    if has_row_vector and has_stronger:
        return 1
    if has_row_vector:
        return 2
    return 0


def is_context_only_manual_task(task: dict[str, Any]) -> bool:
    combined = manual_task_text(task)
    return has_row_vector_signal_text(combined) and not has_stronger_signal_text(combined)


def manual_task_text(task: dict[str, Any]) -> str:
    question = str(task.get("question") or "")
    refs = " ".join(str(ref) for ref in (task.get("evidence_refs") or []))
    return f"{question} {refs}".lower()


def hero_metric(label: str, value: Any) -> str:
    return f"<div class='hero-stat'><div class='num'>{h(value)}</div><div class='label'>{h(label)}</div></div>"


def key_sheets(clusters: list[dict[str, Any]], limit: int) -> list[str]:
    result = []
    for cluster in clusters:
        sheet = str(cluster.get("sheet") or "")
        if sheet and sheet not in result:
            result.append(sheet)
        if len(result) >= limit:
            break
    return result


def build_pattern_groups(
    findings: list[dict[str, Any]],
    claim_mappings: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    manual_tasks: list[dict[str, Any]],
    source_reviews: dict[str, dict[str, Any]],
    judge_risks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        if isinstance(finding, dict):
            grouped[pattern_key_for_finding(finding)].append(finding)

    patterns = []
    for index, (pattern_key, group_findings) in enumerate(sorted(grouped.items(), key=pattern_sort_key), start=1):
        group_findings = sorted(
            group_findings,
            key=lambda finding: (
                -finding_display_score(finding),
                str(finding.get("sheet", "")),
                str(finding.get("finding_id", "")),
            ),
        )
        definition = pattern_definition(pattern_key)
        finding_ids = [str(finding.get("finding_id")) for finding in group_findings if finding.get("finding_id")]
        matched_claims = claims_for_finding_ids(finding_ids, claims, claim_mappings)
        matched_tasks = tasks_for_finding_ids(finding_ids, manual_tasks)
        matched_risks = [risk for risk in judge_risks if any(ref_mentions_finding(ref, finding_ids) for ref in (risk.get("evidence_refs") or []))]
        reviews = [source_reviews[finding_id] for finding_id in finding_ids if finding_id in source_reviews]
        sheets = sorted({str(finding.get("sheet")) for finding in group_findings if finding.get("sheet")})
        workbooks = sorted({str(finding.get("workbook")) for finding in group_findings if finding.get("workbook")})
        categories = Counter(str(finding.get("category", "-")) for finding in group_findings)
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
                "benign_explanations": cluster_benign_explanations(group_findings, reviews),
            }
        )
    return patterns


def displayable_patterns(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        pattern
        for pattern in patterns
        if str(pattern.get("summary_source") or "") != "rule"
        and not is_context_only_pattern(pattern)
    ]


def is_context_only_pattern(pattern: dict[str, Any]) -> bool:
    """Patterns kept in the raw ledger but not promoted to the first screen."""
    if str(pattern.get("pattern_key") or "") != "row_vector_reuse":
        return False
    findings = [finding for finding in pattern.get("findings") or [] if isinstance(finding, dict)]
    if not findings:
        return True
    # Exact row-vector repetition is a weak standalone signal: all-zero rows,
    # low-width vectors, and time/control/template rows are common benign exports.
    # It should support a stronger pattern, not lead the report by itself.
    return all(str(finding.get("category") or "") == "duplicate_row_vector" for finding in findings)


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


def factual_pattern_title(pattern_key: str, findings: list[dict[str, Any]]) -> str:
    categories = Counter(str(finding.get("category") or "") for finding in findings if isinstance(finding, dict))
    category = next((item for item, _count in categories.most_common() if item), "")
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
    return dedupe([sentence for sentence in sentences if sentence])


def first_report_sentence(text: str) -> str:
    text = clean_report_text(text)
    for marker in ("需确认", "需要确认", "：确认", ":确认"):
        if marker in text:
            text = text.split(marker, 1)[0]
    parts = re.split(r"(?<=[。！？])\s*", text, maxsplit=1)
    return (parts[0] if parts else text).rstrip("；;:：,， ")


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
        _manual = [task for task in (pattern.get("manual_tasks") or []) if isinstance(task, dict) and task.get("question")]
        if _manual:
            task_items = [
                f"<li>{_confidence_badge('data')}{h(shorten(clean_report_text(task.get('question', '')), 180))}</li>"
                for task in _manual[:3]
            ]
        else:
            task_items = [
                f"<li>{_confidence_badge('data')}{h(shorten(context_aware_review_question(pattern.get('pattern_key', 'other'), pattern.get('findings') or []), 260))}</li>"
            ]
        categories = pattern.get("categories") or Counter()
        cards.append(
            f"""
<article class="pattern-card" id="{h(pattern.get('pattern_id'))}">
  <div class="pattern-head">
    <div class="pattern-id">{h(pattern.get('pattern_id'))}</div>
    <div>
      <div class="pattern-title">
        <span class="badge {h(pattern.get('risk_level'))}">{h(risk_label(pattern.get('risk_level')))}</span>
        {_confidence_badge(source)}<h3>{h(clean_report_text(pattern.get('title')))}</h3>
      </div>
      <p class="pattern-thesis">{_confidence_badge(source)}{h(clean_report_text(pattern.get('thesis')))}</p>
    </div>
    <aside class="pattern-facts">
      <div><span class="muted">原始记录</span><strong>{h(len(pattern.get('findings') or []))}</strong></div>
      <div><span class="muted">sheets</span><strong>{h(len(pattern.get('sheets') or []))}</strong></div>
      <div><span class="muted">论文表述</span><strong>{h(len(claims))}</strong></div>
    </aside>
  </div>
  <div class="grid cols-2 pattern-actions">
    <div>
      <h3>规律出现在哪里</h3>
      <p>{h(', '.join(pattern.get('sheets') or []) or '-')}</p>
      <p class="muted">{h(', '.join(f'{category_label(key)}×{value}' for key, value in categories.most_common()) or '-')}</p>
    </div>
    <div>
      <h3>人工复核问题</h3>
      <ul>{''.join(task_items)}</ul>
    </div>
  </div>
  <details class="section">
    <summary>展开：关联的论文表述</summary>
    <ul>{''.join(claim_items)}</ul>
  </details>
  <details class="section">
    <summary>展开：可能良性解释</summary>
    {_benign_items_to_html(pattern.get("benign_explanations") or [])}
  </details>
  <details class="section">
    <summary>展开：不可约证据记录</summary>
    {evidence_records_table(pattern.get("findings") or [], compact=True)}
  </details>
</article>
"""
        )
    return "\n".join(cards)


def irreducible_evidence_ledger(patterns: list[dict[str, Any]]) -> str:
    if not patterns:
        return "<p class='muted'>未生成不可约证据记录。</p>"
    sections = []
    for pattern in sorted(patterns, key=lambda item: (is_context_only_pattern(item), str(item.get("pattern_id") or ""))):
        sections.append(
            f"""
<details class="compact-details">
  <summary><span><strong>{h(pattern.get('pattern_id'))} · {h(clean_report_text(pattern.get('title')))}</strong><br/><span class="muted">{h(len(pattern.get('findings') or []))} 条记录 · {h(', '.join(pattern.get('sheets') or []) or '-')}</span></span><span class="badge skipped">展开</span></summary>
  {evidence_records_table(pattern.get("findings") or [])}
</details>
"""
        )
    return "<div class='appendix-grid'>" + "\n".join(sections) + "</div>"


def evidence_records_table(findings: list[dict[str, Any]], compact: bool = False) -> str:
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
        "<div class='noise-table'><table><thead><tr><th>记录 ID</th><th>类别</th><th>来源</th><th>定位</th><th>支持</th><th>样本 / 公式 / 摘要</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def evidence_source_text(finding: dict[str, Any]) -> str:
    workbook = finding.get("workbook")
    sheet = finding.get("sheet")
    if workbook or sheet:
        return " / ".join(str(item) for item in (workbook, sheet) if item)
    for key in ("source_path", "image_path", "figure_path", "artifact_path", "source_artifact"):
        if finding.get(key):
            return str(finding.get(key))
    refs = finding.get("evidence_refs") or []
    if refs:
        return ", ".join(str(ref) for ref in refs[:3])
    return "-"


def evidence_locator(finding: dict[str, Any]) -> str:
    columns = finding.get("columns") or finding.get("column_pair") or finding.get("target_column") or finding.get("column") or []
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
                samples.append(f"row {item.get('row', '-')}: {item.get('left', '-')} -> {item.get('right', '-')}")
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


def pattern_key_for_finding(finding: dict[str, Any]) -> str:
    category = str(finding.get("category", ""))
    source_artifact = str(finding.get("source_artifact", ""))
    if category in {"row_offset_scalar_multiple", "long_format_paired_ratio_reuse", "long_format_within_pair_ratio_enrichment"}:
        return "paired_offset_ratio_reuse"
    if category == "duplicate_row_vector":
        return "row_vector_reuse"
    if category == "row_offset_partial_copy_rounding_bias":
        return "partial_copy_rounding_bias"
    if category == "duplicate_numeric_columns":
        return "duplicate_numeric_columns"
    if category in {"formula_derived_column", "formula_derived_columns", "fixed_ratio", "fixed_difference"}:
        return "formula_derivation"
    category_text = category.lower()
    source_text = source_artifact.lower()
    if any(token in category_text or token in source_text for token in ("image", "visual", "panel", "trufor", "copy_move", "cbir", "similarity", "overlap")):
        return "visual_forensics"
    if any(token in category_text or token in source_text for token in ("numeric", "benford", "number")):
        return "numeric_forensics"
    if any(token in category_text or token in source_text for token in ("execution", "command", "runtime")):
        return "execution_evidence"
    if category:
        return f"category:{category}"
    return "other"


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


def _review_question_paired_offset(findings: list[dict[str, Any]]) -> str:
    sheets = sorted({str(f.get("sheet")) for f in findings if f.get("sheet")})
    offsets = sorted({
        f.get("row_offset") or f.get("pair_id_offset")
        for f in findings
        if f.get("row_offset") is not None or f.get("pair_id_offset") is not None
    })
    ratios: list[str] = []
    for f in findings:
        for k in ("ratio", "support_rate"):
            val = f.get(k)
            if val is not None:
                ratios.append(f"{val:.2f}" if isinstance(val, float) else str(val))
    sheet_text = "、".join(sheets[:3]) or "未记录"
    offset_text = ", ".join(str(o) for o in offsets[:3]) or "未记录"
    ratio_text = ", ".join(dedupe(ratios)[:3]) or "未记录"
    return (
        f"sheet {sheet_text} 在行偏移 {offset_text} 处出现比例/标量关系"
        f"（ratio/support_rate={ratio_text}）：确认这些固定偏移和比例复用是否来自"
        f"合法配对排序、归一化分母或批量派生，而不是同一数据的重复改写。"
    )


def _review_question_row_vector(findings: list[dict[str, Any]]) -> str:
    sheets = sorted({str(f.get("sheet")) for f in findings if f.get("sheet")})
    dup_counts = [
        f.get("duplicate_row_count") or f.get("exact_reuse_pairs")
        for f in findings
        if f.get("duplicate_row_count") or f.get("exact_reuse_pairs")
    ]
    sheet_text = "、".join(sheets[:3]) or "未记录"
    dup_text = ", ".join(str(d) for d in dup_counts[:3]) or "未记录"
    return (
        f"sheet {sheet_text} 出现行向量重复（重复行数/对数: {dup_text}）："
        f"核对重复行是否有实验或统计语义，例如 censoring 模板、分组标签、重复测量，或导出时批量复制。"
    )


def _review_question_duplicate_numeric(findings: list[dict[str, Any]]) -> str:
    sheets = sorted({str(f.get("sheet")) for f in findings if f.get("sheet")})
    col_pairs: list[str] = []
    for f in findings:
        val = f.get("column_pair") or f.get("columns")
        if val:
            col_pairs.append(str(val) if not isinstance(val, list) else ", ".join(str(v) for v in val))
    sheet_text = "、".join(sheets[:3]) or "未记录"
    col_text = "、".join(dedupe(col_pairs)[:4]) or "未记录"
    return (
        f"sheet {sheet_text} 中列 {col_text} 高度相同："
        f"核对这些列是否为索引列、时间/事件设计列、全零矩阵或同一指标的合法重复展示。"
    )


def _review_question_partial_copy(findings: list[dict[str, Any]]) -> str:
    sheets = sorted({str(f.get("sheet")) for f in findings if f.get("sheet")})
    sheet_text = "、".join(sheets[:3]) or "未记录"
    return (
        f"sheet {sheet_text} 出现部分复制或舍入后相似："
        f"核对上游导出、四舍五入、格式化和批量处理过程是否能解释该模式。"
    )


def _review_question_formula_derivation(findings: list[dict[str, Any]]) -> str:
    sheets = sorted({str(f.get("sheet")) for f in findings if f.get("sheet")})
    col_pairs: list[str] = []
    for f in findings:
        for k in ("column_pair", "columns", "column"):
            val = f.get(k)
            if val:
                col_pairs.append(str(val) if not isinstance(val, list) else ", ".join(str(v) for v in val))
    sheet_text = "、".join(sheets[:3]) or "未记录"
    col_text = "、".join(dedupe(col_pairs)[:3]) or "未记录"
    return (
        f"sheet {sheet_text} 列 {col_text} 呈现固定公式派生模式："
        f"确认论文图表引用的是原始测量值还是派生值，并要求作者说明公式来源、单位换算或归一化逻辑。"
    )


def _review_question_visual_forensics(findings: list[dict[str, Any]]) -> str:
    panel_ids: list[str] = []
    scores: list[str] = []
    for f in findings:
        for k in ("source_panel_id", "target_panel_id"):
            val = f.get(k)
            if val:
                panel_ids.append(str(val))
        if f.get("score") is not None:
            scores.append(f"{f['score']:.3f}")
        if f.get("integrity_score") is not None:
            scores.append(f"integrity={f['integrity_score']:.3f}")
    panel_text = "、".join(dedupe(panel_ids)[:4]) or "未记录"
    score_text = ", ".join(scores[:3]) or "未记录"
    return (
        f"panel {panel_text} 检测到视觉相似/复用信号（score={score_text}）："
        f"核对原图、panel、caption、相似方法、分数和最强良性解释，确认是否对应同一主体、合法复用或导出伪影。"
    )


def _review_question_category(pattern_key: str, findings: list[dict[str, Any]]) -> str:
    category = pattern_key.split(":", 1)[1]
    return (
        f"找到 {category_label(category)} 类型记录 {len(findings)} 条："
        f"逐条核对记录的数据语义、生成过程和论文表述影响。"
    )


_REVIEW_QUESTION_HANDLERS: dict[str, Any] = {
    "paired_offset_ratio_reuse": _review_question_paired_offset,
    "row_vector_reuse_rounding": _review_question_row_vector,
    "row_vector_reuse": _review_question_row_vector,
    "duplicate_numeric_columns": _review_question_duplicate_numeric,
    "partial_copy_rounding_bias": _review_question_partial_copy,
    "formula_derivation": _review_question_formula_derivation,
    "visual_forensics": _review_question_visual_forensics,
}


def context_aware_review_question(
    pattern_key: str,
    findings: list[dict[str, Any]],
    clusters: list[dict[str, Any]] | None = None,
) -> str:
    """Generate a specific review question referencing actual finding parameters.

    Dispatches to per-pattern handler functions.  Falls back to the
    hardcoded question from :func:`pattern_definition` when no specific
    handler matches.
    """
    fallback = pattern_definition(pattern_key).get("review_question", "")

    handler = _REVIEW_QUESTION_HANDLERS.get(pattern_key)
    if handler is not None:
        return handler(findings)

    # numeric_forensics / execution_evidence use the pattern_definition fallback
    if pattern_key in {"numeric_forensics", "execution_evidence"}:
        return fallback

    # category:xxx patterns
    if pattern_key.startswith("category:"):
        return _review_question_category(pattern_key, findings)

    return fallback


def build_evidence_clusters(
    findings: list[dict[str, Any]],
    claim_mappings: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    manual_tasks: list[dict[str, Any]],
    source_reviews: dict[str, dict[str, Any]],
    judge_risks: list[dict[str, Any]],
    max_clusters: int = 6,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        source = str(finding.get("workbook") or finding.get("source_path") or finding.get("source_artifact") or "-")
        anchor = str(finding.get("sheet") or finding.get("figure") or finding.get("panel_id") or finding.get("category") or "-")
        grouped[(source, anchor)].append(finding)

    ranked_groups = sorted(
        grouped.items(),
        key=lambda item: (
            -max(finding_display_score(finding) for finding in item[1]),
            -len(item[1]),
            item[0][1],
            item[0][0],
        ),
    )

    clusters = []
    for index, ((source, anchor), group_findings) in enumerate(ranked_groups[:max_clusters], start=1):
        group_findings = sorted(
            group_findings,
            key=lambda finding: (
                -finding_display_score(finding),
                -finding_support_value(finding),
                str(finding.get("finding_id", "")),
            ),
        )
        finding_ids = [str(finding.get("finding_id")) for finding in group_findings if finding.get("finding_id")]
        matched_claims = claims_for_finding_ids(finding_ids, claims, claim_mappings)
        matched_tasks = tasks_for_finding_ids(finding_ids, manual_tasks)
        matched_risks = [risk for risk in judge_risks if any(ref_mentions_finding(ref, finding_ids) for ref in (risk.get("evidence_refs") or []))]
        reviews = [source_reviews[finding_id] for finding_id in finding_ids if finding_id in source_reviews]
        categories = Counter(str(finding.get("category", "-")) for finding in group_findings)
        risk = highest_display_risk(group_findings)
        clusters.append(
            {
                "cluster_id": f"EC-{index:03d}",
                "workbook": source,
                "sheet": anchor,
                "risk_level": risk,
                "finding_ids": finding_ids,
                "findings": group_findings,
                "categories": categories,
                "claims": matched_claims,
                "manual_tasks": matched_tasks,
                "risks": matched_risks,
                "reviews": reviews,
                "headline": cluster_headline(anchor, group_findings, matched_claims),
                "signals": [finding_signal(finding) for finding in group_findings[:4]],
                "benign_explanations": cluster_benign_explanations(group_findings, reviews),
                "source_artifact": source_artifact_for_findings(group_findings),
            }
        )
    return clusters


def evidence_cluster_cards(clusters: list[dict[str, Any]]) -> str:
    if not clusters:
        return "<p class='muted'>未形成主证据簇。请查看技术附录中的原始工具输出。</p>"
    cards = []
    for index, cluster in enumerate(clusters, start=1):
        claims = cluster.get("claims") or []
        claim_items = [
            f"<li><code>{h(claim.get('claim_id', '-'))}</code> {h((claim.get('claim_text') or claim.get('text') or '-')[:260])}</li>"
            for claim in claims[:4]
        ] or ["<li class='muted'>未自动关联到具体论文表述，需人工补映射。</li>"]
        tasks = cluster.get("manual_tasks") or []
        task_items = [clean_report_text(task.get("question", "")) for task in tasks[:3] if task.get("question")]
        if not task_items:
            task_items = [
                "核对 Source Data 的 workbook/sheet/column header、row offset、merged cells 和 figure panel 语义。",
                "要求作者提供原始分析脚本或数据导出过程，解释该结构性模式是否来自合法归一化或批量派生。",
            ]
        categories = cluster.get("categories") or Counter()
        category_text = ", ".join(f"{category_label(key)}×{value}" for key, value in categories.most_common())
        cards.append(
            f"""
<article class="cluster-card" id="{h(cluster.get('cluster_id'))}">
  <div class="cluster-top">
    <div>
      <div class="cluster-title">
        <span class="rank">{h(index)}</span>
        <span class="badge {h(cluster.get('risk_level'))}">{h(risk_label(cluster.get('risk_level')))}</span>
        <h3>{h(cluster.get('sheet'))} · {h(category_text or '复核记录')}</h3>
      </div>
      <p><strong>为什么先看：</strong>{h(cluster.get('headline'))}</p>
      <ul class="signal-list">
        {list_items(cluster.get("signals") or [])}
      </ul>
    </div>
    <aside class="lane">
      <h3>证据定位</h3>
      <div class="kv">
        <div>cluster</div><div><code>{h(cluster.get('cluster_id'))}</code></div>
        <div>source</div><div><code>{h(cluster.get('workbook'))}</code></div>
        <div>anchor</div><div><code>{h(cluster.get('sheet'))}</code></div>
        <div>记录 ID</div><div><code>{h(', '.join(cluster.get('finding_ids') or []))}</code></div>
        <div>artifact</div><div><code>{h(cluster.get('source_artifact'))}</code></div>
      </div>
    </aside>
  </div>
  <div class="grid cols-2 section">
    <div>
      <h3>关联的论文表述</h3>
      <ul>{''.join(claim_items)}</ul>
    </div>
    <div>
      <h3>人工复核动作</h3>
      <ul>{list_items(task_items)}</ul>
    </div>
  </div>
  <details>
    <summary>可能的良性解释与原始记录</summary>
    <div class="grid cols-2 section">
      <div><h3>良性解释</h3>{_benign_items_to_html(cluster.get("benign_explanations") or [])}</div>
      <div><h3>原始记录</h3><ul>{list_items(cluster.get("finding_ids") or [])}</ul></div>
    </div>
  </details>
</article>
"""
        )
    return "\n".join(cards)


def brief_list(clusters: list[dict[str, Any]]) -> str:
    if not clusters:
        return "<p class='muted'>未生成主证据簇。建议先查看覆盖范围和技术附录。</p>"
    rows = []
    for index, cluster in enumerate(clusters[:4], start=1):
        rows.append(
            f"<li><span class='rank'>{h(index)}</span><span><strong>{h(cluster.get('sheet'))}</strong><br/><span class='muted'>{h(cluster.get('headline'))}</span></span></li>"
        )
    return "<ul class='brief-list'>" + "".join(rows) + "</ul>"


def claim_impact_matrix(
    source_mappings: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    canonical_mappings: list[dict[str, Any]],
) -> str:
    claims_by_id = {str(claim.get("claim_id")): claim for claim in claims if isinstance(claim, dict) and claim.get("claim_id")}
    rows = []
    if source_mappings:
        for mapping in source_mappings[:14]:
            if not isinstance(mapping, dict):
                continue
            claim = claims_by_id.get(str(mapping.get("claim_id"))) or {}
            refs = [str(ref) for ref in (mapping.get("source_data_refs") or mapping.get("evidence_refs") or [])]
            finding_refs = [ref for ref in refs if "forensics:" in ref or "finding" in ref.lower()]
            needs_review = mapping.get("needs_human_review")
            rows.append(
                "<tr>"
                f"<td><code>{h(mapping.get('claim_id', '-'))}</code></td>"
                f"<td>{h((claim.get('claim_text') or claim.get('text') or '-')[:260])}</td>"
                f"<td><code>{h(', '.join(refs[:4]) or '-')}</code></td>"
                f"<td><code>{h(', '.join(finding_refs[:6]) or '-')}</code></td>"
                f"<td><span class='badge {'warning' if needs_review is not False else 'low'}'>{h('需人工复核' if needs_review is not False else '低优先级')}</span></td>"
                "</tr>"
            )
    elif canonical_mappings:
        for mapping in canonical_mappings[:14]:
            if not isinstance(mapping, dict):
                continue
            claim = claims_by_id.get(str(mapping.get("claim_id"))) or {}
            refs = [str(ref) for ref in (mapping.get("evidence_refs") or [])]
            finding_refs = [str(ref) for ref in (mapping.get("finding_refs") or refs)]
            metadata = mapping.get("metadata") if isinstance(mapping.get("metadata"), dict) else {}
            needs_review = metadata.get("needs_human_review")
            rows.append(
                "<tr>"
                f"<td><code>{h(mapping.get('claim_id', '-'))}</code></td>"
                f"<td>{h((claim.get('claim_text') or claim.get('text') or '-')[:260])}</td>"
                f"<td><code>{h(', '.join(refs[:4]) or '-')}</code></td>"
                f"<td><code>{h(', '.join(finding_refs[:6]) or '-')}</code></td>"
                f"<td><span class='badge {'warning' if needs_review is not False else 'low'}'>{h('需人工复核' if needs_review is not False else '低优先级')}</span></td>"
                "</tr>"
            )
    if not rows:
        return "<p class='muted'>未生成论文表述对照表。</p>"
    return (
        "<table><thead><tr><th>表述 ID</th><th>论文表述</th><th>证据引用</th><th>记录引用</th><th>状态</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def claims_for_finding_ids(
    finding_ids: list[str],
    claims: list[dict[str, Any]],
    claim_mappings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    claim_ids = set()
    result: list[dict[str, Any]] = []
    for mapping in claim_mappings:
        if not isinstance(mapping, dict):
            continue
        refs = mapping.get("source_data_refs") or mapping.get("evidence_refs") or []
        if any(ref_mentions_finding(ref, finding_ids) for ref in refs):
            claim_id = mapping.get("claim_id")
            if claim_id:
                claim_ids.add(str(claim_id))
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        refs = claim.get("evidence_refs") or []
        claim_id = str(claim.get("claim_id", ""))
        if claim_id in claim_ids or any(ref_mentions_finding(ref, finding_ids) for ref in refs):
            result.append(claim)
    return result


def tasks_for_finding_ids(finding_ids: list[str], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        refs = task.get("evidence_refs") or []
        if any(ref_mentions_finding(ref, finding_ids) for ref in refs):
            result.append(task)
    return result


def ref_mentions_finding(ref: Any, finding_ids: list[str]) -> bool:
    text = json.dumps(ref, ensure_ascii=False) if isinstance(ref, dict) else str(ref)
    return any(finding_id and finding_id in text for finding_id in finding_ids)


def cluster_headline(sheet: str, findings: list[dict[str, Any]], claims: list[dict[str, Any]]) -> str:
    categories = Counter(str(finding.get("category", "-")) for finding in findings)
    category_text = "、".join(category_label(category) for category, _ in categories.most_common(3))
    claim_hint = ""
    if claims:
        claim_hint = f"；已关联 {len(claims)} 条论文表述"
    return f"{sheet} 聚集了 {len(findings)} 条高优先级记录，主要类别为 {category_text or '复核记录'}{claim_hint}，建议作为人工复核入口。"


def finding_signal(finding: dict[str, Any]) -> str:
    category = str(finding.get("category", "-"))
    support = support_text(finding)
    columns = finding.get("columns") or finding.get("column_pair") or finding.get("column") or []
    columns_text = ", ".join(str(item) for item in columns) if isinstance(columns, list) else str(columns)
    if category == "row_offset_scalar_multiple":
        return (
            f"固定行偏移 {finding.get('row_offset', '-')} 后出现标量关系；"
            f"列 {columns_text or '-'}；{support}。"
        )
    if category == "long_format_paired_ratio_reuse":
        return (
            f"long-format paired 数据在 pair_id 偏移 {finding.get('pair_id_offset', '-')} 后出现比例复用；"
            f"列 {columns_text or '-'}；{support}。"
        )
    if category == "duplicate_row_vector":
        return (
            f"低宽度行向量重复；重复行数 {finding.get('duplicate_row_count', '-')}"
            f"；列 {columns_text or '-'}。"
        )
    if category == "long_format_within_pair_ratio_enrichment":
        return (
            f"paired 数据内部特定比例富集；matched_pair_groups={finding.get('matched_pair_groups', '-')}"
            f"；列 {columns_text or '-'}。"
        )
    if category == "row_offset_partial_copy_rounding_bias":
        return (
            f"行偏移后出现部分复制与四舍五入偏差；exact_reuse_pairs={finding.get('exact_reuse_pairs', '-')}"
            f"；{support}。"
        )
    if columns_text:
        return f"{category_label(category)}；{support}；列 {columns_text}。"
    return f"{category_label(category)}；{support}；source={evidence_source_text(finding)}。"


def _collect_source_sheets_cols(findings: list[dict[str, Any]]) -> tuple[str, str]:
    """Return ``(sheet_text, col_text)`` for source-data pattern explanations."""
    sheets = sorted({str(f.get("sheet")) for f in findings if f.get("sheet")})
    sheet_text = "、".join(sheets[:4]) or "未知 sheet"
    col_pairs: list[str] = []
    for f in findings:
        for k in ("column_pair", "columns", "column"):
            val = f.get(k)
            if val:
                col_pairs.append(str(val) if not isinstance(val, list) else ", ".join(str(v) for v in val))
    col_text = "、".join(dedupe(col_pairs)[:4]) or "未记录列对"
    return sheet_text, col_text


def _benign_explanation_paired_offset(findings: list[dict[str, Any]]) -> list[str]:
    sheet_text, col_text = _collect_source_sheets_cols(findings)
    offsets = sorted({
        f.get("row_offset") or f.get("pair_id_offset")
        for f in findings
        if f.get("row_offset") is not None or f.get("pair_id_offset") is not None
    })
    offset_text = ", ".join(str(o) for o in offsets[:4]) or "未记录"
    rates = [f.get("support_rate") or f.get("ratio") for f in findings if f.get("support_rate") is not None]
    rate_text = ", ".join(f"{r:.2f}" if isinstance(r, float) else str(r) for r in rates[:3]) or "未记录"
    items = [
        f"sheet {sheet_text} 中列 {col_text} 在行偏移 {offset_text} 处出现比例/标量关系，"
        f"support_rate={rate_text}，可能来自合法配对排序、归一化分母或批量派生。"
    ]
    all_complete = all(f.get("pattern_strength") == "complete" for f in findings if f.get("pattern_strength"))
    if all_complete and findings:
        items.append("所有匹配行均满足该模式（pattern_strength=complete），无例外行，提示该规律可能是系统性数据处理步骤而非随机编辑。")
    elif rates and all(isinstance(r, (int, float)) and float(r) == 1.0 for r in rates):
        n_offsets = len(offsets)
        if n_offsets > 3:
            items.append(f"support_rate=1.0 且跨 {n_offsets} 个偏移值完美一致，提示可能是模板化导出或固定公式。")
    return items


def _benign_explanation_row_vector(findings: list[dict[str, Any]]) -> list[str]:
    sheet_text, col_text = _collect_source_sheets_cols(findings)
    dup_counts = [
        f.get("duplicate_row_count") or f.get("exact_reuse_pairs")
        for f in findings
        if f.get("duplicate_row_count") or f.get("exact_reuse_pairs")
    ]
    dup_text = ", ".join(str(d) for d in dup_counts[:3]) or "未记录"
    return [
        f"sheet {sheet_text} 中列 {col_text} 出现行向量重复（重复行数/对数: {dup_text}），"
        f"可能来自 censoring 模板、分组标签、重复测量或导出时批量复制。"
    ]


def _benign_explanation_duplicate_numeric(findings: list[dict[str, Any]]) -> list[str]:
    sheet_text, col_text = _collect_source_sheets_cols(findings)
    return [
        f"sheet {sheet_text} 中列 {col_text} 高度相同，"
        f"可能来自索引列、共享时间点、全零矩阵、同一指标重复展示或导出模板。"
    ]


def _benign_explanation_partial_copy(findings: list[dict[str, Any]]) -> list[str]:
    sheet_text, col_text = _collect_source_sheets_cols(findings)
    return [
        f"sheet {sheet_text} 中列 {col_text} 出现部分复用或舍入相似，"
        f"可能来自合法四舍五入、格式化导出或批量处理。"
    ]


def _benign_explanation_formula_derivation(findings: list[dict[str, Any]]) -> list[str]:
    sheet_text, col_text = _collect_source_sheets_cols(findings)
    formulas = sorted({
        str(f.get("dominant_formula_pattern") or f.get("category"))
        for f in findings
        if f.get("dominant_formula_pattern") or f.get("category")
    })
    formula_text = "、".join(formulas[:3]) or "固定公式"
    return [
        f"sheet {sheet_text} 中列 {col_text} 呈现 {formula_text} 模式，"
        f"可能是合法的单位换算、归一化逻辑或公式派生列，需确认论文引用的是原始值还是派生值。"
    ]


_SOURCE_BENIGN_HANDLERS: dict[str, Any] = {
    "paired_offset_ratio_reuse": _benign_explanation_paired_offset,
    "row_vector_reuse_rounding": _benign_explanation_row_vector,
    "row_vector_reuse": _benign_explanation_row_vector,
    "duplicate_numeric_columns": _benign_explanation_duplicate_numeric,
    "partial_copy_rounding_bias": _benign_explanation_partial_copy,
    "formula_derivation": _benign_explanation_formula_derivation,
}


def _benign_explanation_visual_forensics(findings: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    copy_move = [
        f for f in findings
        if str(f.get("category")) in {"copy_move_single", "copy_move_cross"}
    ]
    forged = [f for f in findings if str(f.get("category")) == "forged_region_suspicious"]
    if copy_move:
        panel_ids: list[str] = []
        scores: list[str] = []
        fig_labels: list[str] = []
        for f in copy_move:
            panel_ids.extend([str(f.get("source_panel_id", "-")), str(f.get("target_panel_id", "-"))])
            if f.get("score") is not None:
                scores.append(f"{f['score']:.3f}")
            if f.get("figure_label"):
                fig_labels.append(str(f["figure_label"]))
        panel_text = "、".join(dedupe(panel_ids)[:4]) or "未记录 panel"
        score_text = ", ".join(scores[:3]) or "未记录"
        fig_text = "、".join(dedupe(fig_labels)[:3])
        base = f"panel {panel_text} 检测到局部相似记录（score={score_text}）"
        if fig_text:
            base += f"，涉及 figure {fig_text}"
        base += "，可能来自同一主体多通道成像、合法 control 复用、裁剪导出或压缩伪影。"
        items.append(base)
    if forged:
        fig_ids = sorted({str(f.get("figure_id") or f.get("figure") or "-") for f in forged})
        integrity = [f"{f['integrity_score']:.3f}" for f in forged if f.get("integrity_score") is not None]
        items.append(
            f"figure {'、'.join(fig_ids[:3])} 检测到区域完整性记录"
            f"（integrity_score={', '.join(integrity[:3]) or '未记录'}），"
            f"可能来自图像处理软件伪影、合理标注或后期调整。"
        )
    if not items:
        items.append("图像工具生成了区域或相似关系记录，可能来自同一主体多通道成像、合法 control 复用、裁剪导出或压缩伪影；需结合原图、panel/caption 和实验条件判断。")
    return items


def _benign_explanation_paperfraud(findings: list[dict[str, Any]]) -> list[str]:
    rules = sorted({str(f.get("rule_id") or f.get("category") or "-") for f in findings})
    return [f"PaperFraud 规则 {', '.join(rules[:4])} 命中，属于方法学提示项，需结合原始数据和论文表述判断。"]


def _benign_explanation_other(findings: list[dict[str, Any]]) -> list[str]:
    missing = [f for f in findings if str(f.get("category")) == "source_data_missing"]
    if missing:
        fig_labels = sorted({str(f.get("figure_label") or f.get("figure") or "-") for f in missing})
        return [
            f"figure {'、'.join(fig_labels[:5])} 缺少对应 Source Data，"
            f"可能来自材料未提交、公开仓库另行提供，或该 figure 不要求单独 Source Data。"
        ]
    return []


def _benign_explanation_execution_evidence() -> list[str]:
    return [
        "该模式可能来自环境差异、随机种子、依赖版本或输入材料不完整。",
        "需要结合 runtime manifest、命令日志、结果文件 hash 和表述映射判断。",
    ]


def _benign_explanation_numeric_forensics() -> list[str]:
    return [
        "PDF 或表格数字检查生成统计线索，可能来自 OCR、表格解析、四舍五入和展示层转写造成的伪影。",
        "需回到原始表格、Source Data 或结果文件，确认数字关系是否能由原始数据和统计流程解释。",
    ]


def _benign_explanation_generic() -> list[str]:
    return [
        "该模式可能来自合法的归一化、批量派生、配对样本排序或模板化导出。",
        "需要结合原始 artifact、导出参数、字段定义和论文表述语义判断。",
    ]


def _parameterized_benign_explanation(pattern_key: str, findings: list[dict[str, Any]]) -> list[str]:
    """Generate context-specific benign explanations from actual finding data.

    Dispatches to per-pattern handler functions; each returns a list of
    explanation strings.  Falls back to a generic explanation when no
    specific handler matches.
    """
    handler = _SOURCE_BENIGN_HANDLERS.get(pattern_key)
    if handler is not None:
        return handler(findings)

    if pattern_key == "visual_forensics":
        return _benign_explanation_visual_forensics(findings)
    if pattern_key.startswith("category:paperfraud") or pattern_key == "paperfraud":
        return _benign_explanation_paperfraud(findings)
    if pattern_key == "other":
        result = _benign_explanation_other(findings)
        if result:
            return result
    if pattern_key == "execution_evidence":
        return _benign_explanation_execution_evidence()
    if pattern_key == "numeric_forensics":
        return _benign_explanation_numeric_forensics()

    return _benign_explanation_generic()


def cluster_benign_explanations(findings: list[dict[str, Any]], reviews: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return benign explanations as list of (text, source_type) tuples.

    source_type is one of: 'agent' (from SourceDataAuditor reviews),
    'data' (from parameterized fallback based on actual finding data).
    """
    items: list[tuple[str, str]] = []
    for review in reviews:
        for item in (review.get("benign_explanations") or [])[:3]:
            items.append((str(item), "agent"))
    for finding in findings:
        for item in (finding.get("benign_explanations") or [])[:2]:
            items.append((str(item), "agent"))
    if not items:
        pattern_keys = {pattern_key_for_finding(finding) for finding in findings}
        if pattern_keys:
            dominant_key = max(pattern_keys, key=lambda k: sum(1 for f in findings if pattern_key_for_finding(f) == k))
            for text in _parameterized_benign_explanation(dominant_key, findings):
                items.append((text, "data"))
        else:
            items = [
                ("该模式可能来自合法的归一化、批量派生、配对样本排序或模板化导出。", "data"),
                ("需要结合原始 artifact、导出参数、字段定义和论文 claim 语义判断。", "data"),
            ]
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for text, source_type in items:
        if text and text not in seen:
            seen.add(text)
            deduped.append((text, source_type))
    return deduped[:5]


def source_artifact_for_findings(findings: list[dict[str, Any]]) -> str:
    artifacts = dedupe([source_artifact_for_finding(finding) for finding in findings])
    return ", ".join(artifacts[:3]) or "-"


def source_artifact_for_finding(finding: dict[str, Any]) -> str:
    if finding.get("source_artifact"):
        return str(finding.get("source_artifact"))
    pair_categories = {
        "row_offset_scalar_multiple",
        "long_format_paired_ratio_reuse",
        "duplicate_row_vector",
        "long_format_within_pair_ratio_enrichment",
        "row_offset_partial_copy_rounding_bias",
    }
    if str(finding.get("category")) in pair_categories:
        return SOURCE_DATA_PAIR_FORENSICS_ARTIFACT
    if finding.get("workbook") or finding.get("sheet"):
        return SOURCE_DATA_FINDINGS_ARTIFACT
    return "static_audit_bundle.json"


def finding_support_value(finding: dict[str, Any]) -> int:
    for key in ("support_rows", "matched_pairs", "matched_pair_groups", "duplicate_row_count", "exact_reuse_pairs", "equal_rows"):
        value = finding.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return 0


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
    benign = source_review.get("benign_explanations") or finding.get("benign_explanations") or []
    review_action = review_question(source_review, risk, finding)
    sample_rows = sample_evidence_html(finding)
    claim_text = first_claim(mappings)
    risk_reason = (risk or {}).get("reason", "")
    source_artifact = source_artifact_for_finding(finding)
    mapping_note = mapping_granularity_note(finding)
    risk_badge = _confidence_badge("agent") if risk and risk_reason else ""
    return f"""
<article class="finding-card">
  <div>
    <div class="finding-title">
      <span class="badge {h(review_badge_class)}">{h(review_badge_label)}</span>
      <span class="badge {h(risk_level)}">{h(risk_label(risk_level))}</span>
      <h3>{h(finding_id)} · {h(category_label(category))}</h3>
    </div>
    <p><strong>复核摘要：</strong>{risk_badge}{h(clean_report_text(risk_reason or default_finding_summary(finding)))}</p>
    <div class="quote"><strong>关联论文表述：</strong>{h(claim_text or "未自动抽取到论文表述，需人工补映射。")}</div>
    <div class="grid cols-2">
      <div>
        <h3>为什么值得复核</h3>
        <ul>
          <li>{h(relation)}</li>
          <li>{h(support)}</li>
          <li>{h(mapping_note)}</li>
        </ul>
      </div>
      <div>
        <h3>良性解释</h3>
        <ul>{"".join(f"<li>{_confidence_badge('agent')}{h(clean_report_text(item))}</li>" for item in benign[:4]) or "<li class='muted'>未记录。</li>"}</ul>
      </div>
    </div>
    <h3>人工复核动作</h3>
    <p>{h(review_action)}</p>
    <details>
      <summary>样本行</summary>
      {sample_rows}
    </details>
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
    </aside>
</article>
"""


def evidence_card_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        findings,
        key=lambda item: (
            -finding_display_score(item),
            -int(item.get("support_rows") or item.get("equal_rows") or 0),
            str(item.get("finding_id", "")),
        ),
    )[:MAX_EVIDENCE_CARDS]


def steps_table(steps: list[dict[str, Any]]) -> str:
    rows = []
    for step in steps:
        key = step.get("key") or step.get("step_key") or "-"
        title = step.get("title", key)
        status = step.get("status", "-")
        detail = str(step.get("detail", ""))[:120]
        rows.append(
            f"<tr><td><code>{h(key)}</code></td><td>{h(clean_report_text(title))}</td><td><span class='badge {h(status)}'>{h(status_label(status))}</span></td><td>{h(clean_report_text(detail))}</td></tr>"
        )
    return "<table><thead><tr><th>步骤 key</th><th>步骤</th><th>状态</th><th>说明</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def traces_table(traces: list[dict[str, Any]]) -> str:
    rows = []
    counts = Counter(trace.get("status", "-") for trace in traces)
    for trace in traces:
        status = str(trace.get("status", "-"))
        rows.append(
            f"<tr><td><code>{h(trace.get('role_id', '-'))}</code></td><td><span class='badge {h(status)}'>{h(status_label(status))}</span></td><td>{h(summary_text(trace.get('output_summary') or {}))}</td><td><code>{h(trace.get('output_path', '-'))}</code></td></tr>"
        )
    summary = " ".join(f"<span class='badge {h(k)}'>{h(status_label(k))} {v}</span>" for k, v in sorted(counts.items()))
    return f"<p>{summary}</p><table><thead><tr><th>role</th><th>状态</th><th>摘要</th><th>输出文件</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"


def material_plan_panel(material_summary: dict[str, Any], material_plan: dict[str, Any]) -> str:
    lanes = [lane for lane in (material_plan.get("selected_optional_lanes") or []) if isinstance(lane, dict)]
    lane_rows = []
    for lane in lanes:
        status = str(lane.get("status", "-"))
        lane_rows.append(
            "<tr>"
            f"<td><code>{h(lane.get('lane_id', '-'))}</code></td>"
            f"<td><span class='badge {h(status)}'>{h(status_label(status))}</span></td>"
            f"<td><code>{h(lane.get('root') or '-')}</code></td>"
            f"<td>{h(clean_report_text(lane.get('reason', '-')))}</td>"
            "</tr>"
        )
    if not lane_rows:
        lane_rows.append("<tr><td colspan='4'>未选择 optional lane。</td></tr>")
    material_types = material_summary.get("by_material_type") if isinstance(material_summary.get("by_material_type"), dict) else {}
    unsupported = material_plan.get("unsupported_materials") or []
    unsupported_text = ", ".join(
        str(item.get("path", item)) for item in unsupported[:6] if isinstance(item, dict)
    ) or "-"
    return f"""
<div class="grid cols-2">
  <div class="lane">
    <h3>材料清单</h3>
    <div class="kv">
      <div>文件数</div><div>{h(material_summary.get("file_count", "-"))}</div>
      <div>材料类型</div><div>{h(", ".join(f"{key}={value}" for key, value in material_types.items()) or "-")}</div>
      <div>候选根目录</div><div>{h(material_summary.get("candidate_source_roots", "-"))}</div>
      <div>可执行 lane</div><div>{h(material_summary.get("supported_optional_lanes", "-"))}</div>
    </div>
  </div>
  <div class="lane">
    <h3>材料处理计划</h3>
    <div class="kv">
      <div>状态</div><div>{h(status_label(material_plan.get("status", "ok") if material_plan else "missing"))}</div>
      <div>缺失材料</div><div>{h(", ".join(str(item) for item in (material_plan.get("missing_materials") or [])) or "-")}</div>
      <div>暂不支持材料</div><div>{h(unsupported_text)}</div>
    </div>
  </div>
</div>
<table>
  <thead><tr><th>lane</th><th>状态</th><th>根目录</th><th>选择原因</th></tr></thead>
  <tbody>{''.join(lane_rows)}</tbody>
</table>
"""


def canonical_mapping_table(claims: list[dict[str, Any]], mappings: list[dict[str, Any]]) -> str:
    mappings = [mapping for mapping in mappings if isinstance(mapping, dict)]
    claims = [claim for claim in claims if isinstance(claim, dict)]
    if not mappings:
        return "<p class='muted'>未生成精炼映射；如存在确定性脚手架，请查看对应工具 JSON。</p>"
    claim_by_id = {str(claim.get("claim_id")): claim for claim in claims if claim.get("claim_id")}
    rows = []
    for mapping in mappings[:12]:
        claim = claim_by_id.get(str(mapping.get("claim_id"))) or {}
        metadata = mapping.get("metadata") if isinstance(mapping.get("metadata"), dict) else {}
        source_refs = metadata.get("source_data_refs") or mapping.get("evidence_refs") or []
        needs_review = metadata.get("needs_human_review")
        rows.append(
            "<tr>"
            f"<td><code>{h(mapping.get('mapping_id', '-'))}</code></td>"
            f"<td><code>{h(mapping.get('claim_id', '-'))}</code></td>"
            f"<td>{h(str(claim.get('text', '-'))[:260])}</td>"
            f"<td>{h(mapping.get('confidence', '-'))}</td>"
            f"<td><span class='badge warning'>{h('需人工复核' if needs_review is not False else '低优先级')}</span></td>"
            f"<td><code>{h(', '.join(str(ref) for ref in source_refs[:4]) or '-')}</code></td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>mapping</th><th>表述 ID</th><th>论文表述</th><th>置信度</th><th>复核状态</th><th>证据 refs</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def manual_tasks_table(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "<p class='muted'>未生成独立人工复核任务。</p>"
    rows = []
    visible_tasks = sorted(
        [task for task in tasks if isinstance(task, dict)],
        key=lambda task: (-risk_score(display_priority_for_manual_task(task)), manual_task_focus_score(task)),
    )
    for task in visible_tasks[:10]:
        refs = task.get("evidence_refs") or []
        priority = display_priority_for_manual_task(task)
        rows.append(
            "<tr>"
            f"<td><code>{h(task.get('task_id', '-'))}</code></td>"
            f"<td><span class='badge {h(priority)}'>{h(risk_label(priority))}</span></td>"
            f"<td>{_confidence_badge('data')}{h(clean_report_text(task.get('question', '-')))}</td>"
            f"<td><code>{h(', '.join(str(ref) for ref in refs[:5]) or '-')}</code></td>"
            "</tr>"
        )
    return "<table><thead><tr><th>任务</th><th>优先级</th><th>问题</th><th>证据 refs</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


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
            f"<tr><td><code>{fid}</code></td>"
            f"<td>{cat}</td>"
            f"<td>{wb} / {sh}</td>"
            f"<td>{pattern}</td>"
            f"<td>{conf:.0%}</td>"
            f"<td>{expl}</td></tr>"
        )

    return (
        f'<details class="compact-details">'
        f"<summary><span><strong>LLM 语义裁决排除项（{fp_count} 条假阳性）</strong>"
        f"<br/><span class=\"muted\">"
        f"确定性检测产出 {total} 条 Source Data findings，"
        f"LLM 逐 sheet 裁决后排除 {fp_count} 条假阳性，"
        f"保留 {tp_count + un_count} 条待人工复核（TP={tp_count}, uncertain={un_count}）。"
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


def pair_forensics_table(findings: list[dict[str, Any]]) -> str:
    findings = [finding for finding in findings if isinstance(finding, dict)]
    if not findings:
        return "<p class='muted'>未生成配对/行偏移重点记录。</p>"
    rows = []
    findings = sorted(
        findings,
        key=lambda finding: (-finding_display_score(finding), -finding_support_value(finding), str(finding.get("finding_id", ""))),
    )
    for finding in findings[:12]:
        risk = display_risk_level_for_finding(finding)
        support = (
            finding.get("support_rows")
            or finding.get("matched_pairs")
            or finding.get("matched_pair_groups")
            or finding.get("duplicate_row_count")
            or finding.get("exact_reuse_pairs")
            or "-"
        )
        overlap = finding.get("overlap_rows") or finding.get("overlap_pairs") or finding.get("overlap_pair_groups") or "-"
        columns = finding.get("columns") or finding.get("column_pair") or finding.get("column") or []
        if isinstance(columns, list):
            columns_text = ", ".join(str(item) for item in columns)
        else:
            columns_text = str(columns)
        rows.append(
            "<tr>"
            f"<td><code>{h(finding.get('finding_id', '-'))}</code></td>"
            f"<td><span class='badge {h(risk)}'>{h(risk_label(risk))}</span></td>"
            f"<td>{h(finding.get('category', '-'))}</td>"
            f"<td><code>{h(finding.get('workbook', '-'))}</code></td>"
            f"<td>{h(finding.get('sheet', '-'))}</td>"
            f"<td>{h(finding.get('row_offset') or finding.get('pair_id_offset') or '-')}</td>"
            f"<td>{h(columns_text or '-')}</td>"
            f"<td>{h(support)}/{h(overlap)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>ID</th><th>优先级</th><th>类别</th><th>workbook</th><th>sheet</th><th>offset</th><th>columns</th><th>support</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def pair_forensics_review_tasks_table(tasks: list[dict[str, Any]]) -> str:
    tasks = [task for task in tasks if isinstance(task, dict)]
    if not tasks:
        return "<p class='muted'>未生成配对/行偏移复核项。</p>"
    rows = []
    tasks = sorted(
        tasks,
        key=lambda task: (-risk_score(display_priority_for_pair_task(task)), manual_task_focus_score(task)),
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
    clusters = [cluster for cluster in clusters if isinstance(cluster, dict)]
    if not clusters:
        return "<p class='muted'>未生成配对/行偏移记录簇。</p>"
    rows = []
    clusters = sorted(
        clusters,
        key=lambda cluster: (-risk_score(display_risk_level_for_pair_cluster(cluster)), -int(cluster.get("finding_count") or 0)),
    )
    for cluster in clusters[:12]:
        risk = display_risk_level_for_pair_cluster(cluster)
        representatives = ", ".join(str(item) for item in (cluster.get("representative_finding_ids") or [])[:5])
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


def investigation_table(records: list[dict[str, Any]]) -> str:
    records = [record for record in records if isinstance(record, dict)]
    if not records:
        return "<p class='muted'>本次未生成 investigation round 记录。</p>"
    rows = []
    for record in records[:20]:
        status = str(record.get("status", "skipped"))
        artifacts = record.get("output_artifacts") or []
        rows.append(
            "<tr>"
            f"<td>{h(record.get('round_id', '-'))}</td>"
            f"<td><code>{h(record.get('action_id', '-'))}</code></td>"
            f"<td><code>{h(record.get('tool_id', '-'))}</code></td>"
            f"<td><span class='badge {h(status)}'>{h(risk_label(status))}</span></td>"
            f"<td>{h(shorten(clean_report_text(record.get('hypothesis') or record.get('detail') or '-'), 220))}</td>"
            f"<td>{h(', '.join(str(item) for item in artifacts[:3]) or '-')}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Round</th><th>Action</th><th>Tool</th><th>Status</th><th>Hypothesis / Detail</th><th>Artifact</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def risks_table(risks: list[dict[str, Any]]) -> str:
    rows = []
    for risk in sorted(
        [risk for risk in risks if isinstance(risk, dict)],
        key=lambda item: -risk_score(display_risk_level_for_judge_risk(item)),
    ):
        risk_level = display_risk_level_for_judge_risk(risk)
        rows.append(
            f"<tr><td><span class='badge {h(risk_level)}'>{h(risk_label(risk_level))}</span></td><td>{h(clean_report_text(risk.get('reason', '')))}</td><td>{h(', '.join(str(item) for item in (risk.get('evidence_refs') or [])[:8]))}</td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='3'>未生成复核摘要。</td></tr>")
    return "<table><thead><tr><th>优先级</th><th>原因</th><th>证据 refs</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def judge_summary_text(
    judge_summary: dict[str, Any],
    claim_extractor: dict[str, Any],
    source_auditor: dict[str, Any],
) -> str:
    text = str(judge_summary.get("technical_risk_summary") or "未生成整体摘要。")
    claim_count = len(claim_extractor.get("claims") or [])
    mapping_count = len(source_auditor.get("claim_to_source_data") or [])
    review_count = len(source_auditor.get("finding_reviews") or [])
    task_count = len(source_auditor.get("manual_review_tasks") or [])
    if claim_count or mapping_count or review_count or task_count:
        stale_markers = (
            "未产出",
            "无法进行 claim-to-evidence",
            "无法进行 claim-to",
            "均未产出",
        )
        if any(marker in text for marker in stale_markers):
            return (
                "整体摘要与已生成结构化产物存在不一致；HTML 已按产物计数校正。"
                f"论文表述={claim_count}；Source Data 映射={mapping_count}、"
                f"复核记录={review_count}、复核任务={task_count}。"
            )
    return text


def artifact_links(workdir: Path) -> str:
    names = [
        "final_audit_report.md",
        "static_audit_bundle.json",
        "audit_run_manifest.json",
        "material_inventory.json",
        "agent_material_plan.json",
        "source_data_findings.json",
        "source_data_pair_forensics.json",
        "agent_claim_extractor.json",
        "agent_source_data_auditor.json",
        "agent_judge.json",
        "evidence_ledger.json",
        "numeric_forensics.json",
        "paperfraud_rule_matches.json",
        "exact_image_duplicates.json",
        "image_similarity_candidates.json",
        "investigation_rounds.jsonl",
    ]
    rows = []
    for name in names:
        path = resolve_artifact_path(workdir, name)
        status = "present" if path.exists() else "missing"
        size = path.stat().st_size if path.exists() else "-"
        rows.append(
            f"<div class='artifact'><span><code>{h(name)}</code></span><span><span class='badge {status}'>{status_label(status)}</span> {h(size)} 字节</span></div>"
        )
    return "<div class='artifact-list'>" + "".join(rows) + "</div>"


def collect_limitations(bundle: dict[str, Any], agent_judge: dict[str, Any], similarity: dict[str, Any]) -> list[str]:
    limitations = ["本报告不做最终科研诚信判定，只展示技术记录和人工复核入口。"]
    if bundle.get("claim_mappings"):
        limitations.append("论文表述与证据之间的映射仍需按原始 artifact 和 locator 人工确认。")
    else:
        limitations.append("本次未生成稳定的论文表述与证据映射，表述影响需要人工补齐。")
    execution_status = (bundle.get("execution_status") or {}).get("status")
    if execution_status in {None, "", "not_provided", "not_run", "missing_material"}:
        limitations.append(f"代码执行审查未形成可用执行证据，execution_status={execution_status or 'unknown'}。")
    if similarity.get("status") == "not_available":
        limitations.append("近似图像相似度未运行；只能说明 exact duplicate 未发现。")
    limitations.extend(str(item) for item in (bundle.get("limitations") or [])[:5])
    limitations.extend(str(item) for item in (agent_judge.get("limitations") or [])[:5])
    return dedupe(limitations)


def dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        key = str(finding.get("finding_id") or json.dumps(finding, sort_keys=True, ensure_ascii=False))
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return result


def map_findings_to_mappings(mappings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for mapping in mappings:
        for finding in mapping.get("linked_priority_findings") or []:
            finding_id = finding.get("finding_id") if isinstance(finding, dict) else None
            if finding_id:
                result.setdefault(str(finding_id), []).append(mapping)
    return result


def map_reviews(reviews: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("finding_id")): item for item in reviews if item.get("finding_id")}


def risk_for_finding(risks: list[dict[str, Any]], finding_id: Any) -> dict[str, Any] | None:
    if finding_id is None:
        return None
    for risk in risks:
        if str(finding_id) in {str(item) for item in (risk.get("evidence_refs") or [])}:
            return risk
    return None


def paper_refs(mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for mapping in mappings:
        refs.extend(ref for ref in (mapping.get("matched_paper_references") or []) if isinstance(ref, dict))
    return refs


def best_paper_ref(refs: list[dict[str, Any]]) -> dict[str, Any]:
    for ref in refs:
        text = str(ref.get("text", ""))
        if "See next page" not in text and len(text) > 40:
            return ref
    return refs[0] if refs else {}


def source_locator(finding: dict[str, Any], paper_ref: dict[str, Any]) -> dict[str, str]:
    line_start = paper_ref.get("line_start")
    line_end = paper_ref.get("line_end")
    if line_start and line_end and line_start != line_end:
        line = f"full.md:{line_start}-{line_end}"
    elif line_start:
        line = f"full.md:{line_start}"
    else:
        line = "未定位"
    return {
        "figure": str(paper_ref.get("match_label") or "-"),
        "line": line,
    }


def first_claim(mappings: list[dict[str, Any]]) -> str:
    for mapping in mappings:
        claims = mapping.get("candidate_claims") or []
        if claims and isinstance(claims[0], dict):
            return str(claims[0].get("text", ""))[:700]
        refs = mapping.get("matched_paper_references") or []
        if refs and isinstance(refs[0], dict):
            return str(refs[0].get("text", ""))[:700]
    return ""


def relation_text(finding: dict[str, Any]) -> str:
    if finding.get("category") == "fixed_difference":
        return f"固定差关系：{finding.get('relationship_value')}，列 {', '.join(finding.get('column_pair') or [])}。"
    if finding.get("category") == "duplicate_numeric_columns":
        return f"数值列完全重复：列 {', '.join(finding.get('column_pair') or [])}。"
    if finding.get("category") == "row_offset_scalar_multiple":
        return f"固定行偏移 {finding.get('row_offset', '-')} 后存在标量关系，列 {', '.join(str(item) for item in (finding.get('columns') or [])) or '-'}。"
    if finding.get("category") == "long_format_paired_ratio_reuse":
        return f"pair_id 偏移 {finding.get('pair_id_offset', '-')} 后出现配对两组比例复用，列 {', '.join(str(item) for item in (finding.get('columns') or [])) or '-'}。"
    if finding.get("category") == "duplicate_row_vector":
        return f"低宽度行向量重复，重复行数 {finding.get('duplicate_row_count', '-')}。"
    return str(finding.get("category", "-"))


def support_text(finding: dict[str, Any]) -> str:
    support = (
        finding.get("support_rows")
        or finding.get("matched_pairs")
        or finding.get("matched_pair_groups")
        or finding.get("duplicate_row_count")
        or finding.get("exact_reuse_pairs")
        or finding.get("equal_rows")
    )
    overlap = finding.get("overlap_rows") or finding.get("overlap_pairs") or finding.get("overlap_pair_groups")
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


def default_finding_summary(finding: dict[str, Any]) -> str:
    columns = finding.get("column_pair") or finding.get("columns") or finding.get("column") or []
    columns_text = ", ".join(str(item) for item in columns) if isinstance(columns, list) else str(columns)
    if finding.get("workbook") or finding.get("sheet"):
        return (
            f"{finding.get('workbook', '-')} / {finding.get('sheet', '-')} 中 "
            f"{columns_text or evidence_locator(finding)} 出现 {finding.get('category', '-')}。"
        )
    source = evidence_source_text(finding)
    locator = evidence_locator(finding)
    if source != "-" or locator != "-":
        return f"{source} / {locator} 出现 {finding.get('category', '-')}。"
    return str(finding.get("summary") or finding.get("category") or "技术记录。")


def review_question(source_review: dict[str, Any], risk: dict[str, Any] | None, finding: dict[str, Any]) -> str:
    if risk and risk.get("requires_human_review"):
        return str(risk.get("reason", "请人工复核该记录的证据定位、论文表述影响和良性解释。"))
    refs = source_review.get("evidence_refs") if isinstance(source_review.get("evidence_refs"), dict) else {}
    linked = refs.get("linked_claims") if refs else None
    linked_text = f"关联论文表述: {', '.join(linked)}。" if linked else ""
    if finding.get("workbook") or finding.get("sheet"):
        return f"请核对 workbook/sheet/column header、merged cells、figure panel 和原始实验语义。{linked_text}"
    return f"请核对原始 artifact、locator、论文表述影响、工具输出参数和最强良性解释。{linked_text}"


def mapping_granularity_note(finding: dict[str, Any]) -> str:
    source_artifact = source_artifact_for_finding(finding)
    if source_artifact in {SOURCE_DATA_FINDINGS_ARTIFACT, SOURCE_DATA_PAIR_FORENSICS_ARTIFACT}:
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
    if not samples:
        return "<p class='muted'>没有可展示的样本行。</p>"
    rows = [
        f"<div class='sample-row'><div>行 {h(item.get('row', '-'))}</div><div>{h(item.get('left', '-'))}</div><div>{h(item.get('right', '-'))}</div></div>"
        for item in samples[:8]
    ]
    return "<div class='samples'><div class='sample-row muted'><div>行</div><div>左列</div><div>右列</div></div>" + "".join(rows) + "</div>"


def metric(label: str, value: Any) -> str:
    return f"<div class='metric'><div class='num'>{h(value)}</div><div class='label'>{h(label)}</div></div>"


def list_items(items: list[Any]) -> str:
    if not items:
        return "<li class='muted'>未记录。</li>"
    return "".join(f"<li>{h(clean_report_text(item))}</li>" for item in items)


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def summary_text(summary: dict[str, Any]) -> str:
    parts = []
    for key, value in summary.items():
        if isinstance(value, (str, int, float)):
            parts.append(f"{key}={str(value)[:90]}")
    return "; ".join(parts[:4]) or "-"


def status_label(status: Any) -> str:
    labels = {
        "ran": "已执行",
        "reused": "已复用",
        "skipped": "已跳过",
        "warning": "警告",
        "failed": "失败",
        "not_run": "未运行",
        "not_provided": "未提供",
        "missing_material": "材料缺失",
        "selected": "已选择",
        "unsupported": "暂不支持",
        "present": "已生成",
        "missing": "缺失",
        "ok": "正常",
        "not_available": "不可用",
    }
    return labels.get(str(status), str(status))


def risk_label(risk: Any) -> str:
    labels = {
        "critical": "最高优先级",
        "high": "高优先级",
        "medium": "中优先级",
        "low": "低优先级",
        "info": "提示",
        "context": "上下文记录",
    }
    return labels.get(str(risk), str(risk))


def risk_score(risk: Any) -> int:
    return {
        "critical": 4,
        "high": 3,
        "medium": 2,
        "low": 1,
        "info": 0,
        "context": 0,
    }.get(str(risk), 0)


def has_row_vector_signal_text(text: Any) -> bool:
    normalized = str(text or "").lower()
    return any(token in normalized for token in ROW_VECTOR_SIGNAL_TOKENS)


def has_stronger_signal_text(text: Any) -> bool:
    normalized = str(text or "").lower()
    return any(token in normalized for token in STRONGER_SIGNAL_TOKENS)


def is_context_only_finding(finding: dict[str, Any]) -> bool:
    return str(finding.get("category") or "") == "duplicate_row_vector"


def display_risk_level_for_finding(finding: dict[str, Any]) -> str:
    if is_context_only_finding(finding):
        return "context"
    return str(finding.get("risk_level") or "medium")


def finding_display_score(finding: dict[str, Any]) -> int:
    return risk_score(display_risk_level_for_finding(finding))


def highest_display_risk(findings: list[dict[str, Any]]) -> str:
    levels = [display_risk_level_for_finding(finding) for finding in findings if isinstance(finding, dict)]
    return max(levels, key=risk_score, default="medium")


def display_priority_for_manual_task(task: dict[str, Any]) -> str:
    if is_context_only_manual_task(task):
        return "context"
    return str(task.get("priority") or "medium")


def display_priority_for_pair_task(task: dict[str, Any]) -> str:
    if str(task.get("category") or "") == "duplicate_row_vector" or is_context_only_manual_task(task):
        return "context"
    return str(task.get("priority") or "medium")


def display_risk_level_for_pair_cluster(cluster: dict[str, Any]) -> str:
    if str(cluster.get("category") or "") == "duplicate_row_vector":
        return "context"
    return str(cluster.get("risk_level") or "medium")


def display_risk_level_for_judge_risk(risk: dict[str, Any]) -> str:
    refs = " ".join(str(ref) for ref in (risk.get("evidence_refs") or []))
    combined = f"{risk.get('reason') or ''} {refs}"
    if has_row_vector_signal_text(combined) and not has_stronger_signal_text(combined):
        return "context"
    return str(risk.get("risk_level") or "medium")


def category_label(category: Any) -> str:
    labels = {
        "duplicate_numeric_columns": "数值列重复",
        "fixed_difference": "固定差关系",
        "fixed_ratio": "固定比例关系",
        "formula_derived_columns": "公式派生列",
        "row_offset_scalar_multiple": "固定行偏移标量关系",
        "long_format_paired_ratio_reuse": "配对比例复用",
        "duplicate_row_vector": "行向量重复",
        "long_format_within_pair_ratio_enrichment": "配对内部比例富集",
        "row_offset_partial_copy_rounding_bias": "行偏移复制/舍入偏差",
        "copy_move_single": "单图内局部相似",
        "copy_move_cross": "跨图局部相似",
        "exact_duplicate": "字节级完全重复",
        "dhash_similar": "感知哈希相似",
        "overlap_reuse_cross_panel": "跨 Panel 局部重叠",
        "forged_region_suspicious": "区域完整性记录",
        "paperfraud.methodology_review": "方法学提示",
        "paperfraud.fraud_detection": "数值取证提示",
    }
    return labels.get(str(category), str(category))


def dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
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


def _confidence_badge(source_type: str) -> str:
    """Return HTML for a small badge indicating the source of an explanation/text element."""
    badges = {
        "rule": '<span class="conf-badge conf-rule">仅原始记录</span>',
        "data": '<span class="conf-badge conf-data">证据记录</span>',
        "agent": '<span class="conf-badge conf-agent">复核摘要</span>',
    }
    return badges.get(source_type, "")


def _has_pattern_type(patterns: list[dict[str, Any]], key_substring: str) -> bool:
    """Check if any pattern in the list has a pattern_key containing the given substring."""
    return any(key_substring in str(pattern.get("pattern_key", "")) for pattern in patterns)


def _count_pattern_findings(patterns: list[dict[str, Any]], key_substring: str) -> int:
    """Count total findings across patterns whose pattern_key contains the given substring."""
    total = 0
    for pattern in patterns:
        if key_substring in str(pattern.get("pattern_key", "")):
            total += len(pattern.get("findings") or [])
    return total


def _pattern_keys_present(patterns: list[dict[str, Any]], keys: set[str]) -> bool:
    """Check if any pattern has a pattern_key in the given set."""
    return any(str(pattern.get("pattern_key", "")) in keys for pattern in patterns)


def _benign_items_to_html(items: list) -> str:
    """Render benign explanation items (strings or (text, source_type) tuples) as badge HTML."""
    if not items:
        return "<p class='muted'>未记录。</p>"
    parts = []
    for item in items:
        if isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[1], str):
            text, source_type = item
            parts.append(f"<li>{_confidence_badge(source_type)}{h(clean_report_text(text))}</li>")
        else:
            parts.append(f"<li>{h(clean_report_text(item))}</li>")
    return "<ul>" + "".join(parts) + "</ul>"
