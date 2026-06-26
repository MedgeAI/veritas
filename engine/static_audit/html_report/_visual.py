"""Visual evidence section for the HTML report.
# All f-string interpolations MUST use h() or h_attr() for XSS protection.

Renders the Visual Evidence Package: figures, panels, relationships,
finding cards and review checklists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.static_audit.html_report._html_utils import h
from engine.static_audit.html_report._config import (
    MAX_VISUAL_FIGURES,
    MAX_VISUAL_FINDINGS,
    MAX_VISUAL_REVIEW_QUEUE,
    MAX_VISUAL_CLUSTERS,
    MAX_VISUAL_PANELS_PER_FIGURE,
    MAX_VISUAL_RELATIONSHIPS,
    MAX_FIGURE_CAPTION_LENGTH,
)
from engine.static_audit.html_report._shared import (
    _confidence_badge,
    clean_report_text,
    dedupe,
    metric,
    read_json,
    risk_label,
)
from engine.static_audit.paths import resolve_artifact_path


def visual_evidence_section(workdir: Path) -> str:
    """Generate Visual Evidence Package section for the HTML report."""
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

    figure_count = len(figures)
    panel_count = len(panels)
    rel_count = len(rels)
    finding_count = len(visual_findings)
    cluster_count = len(visual_clusters)
    review_queue_count = len(review_queue)

    review_questions: list[str] = []
    for task in review_queue:
        if isinstance(task, dict):
            text = str(task.get("question") or "")
            if text and not check_language_compliance(text):
                review_questions.append(text)
    for finding in visual_findings:
        if isinstance(finding, dict):
            for q in finding.get("manual_review_questions") or []:
                text = str(q)
                if text and not check_language_compliance(text):
                    review_questions.append(text)
    review_questions = dedupe(review_questions)[:10]

    figure_cards = _visual_figure_cards(figures, panels)
    relationship_table = _visual_relationship_table(rels)
    review_queue_table = _visual_review_queue_table(review_queue)
    cluster_table = _visual_cluster_table(visual_clusters)
    finding_cards_html = _visual_finding_cards(visual_findings, panels)
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


def _visual_figure_cards(
    figures: list[dict[str, Any]], panels: list[dict[str, Any]]
) -> str:
    """Generate figure cards with panel thumbnails."""
    if not figures:
        return "<p class='muted'>未提取到 figure 级图像证据。</p>"

    panels_by_figure: dict[str, list[dict[str, Any]]] = {}
    for panel in panels:
        if isinstance(panel, dict):
            parent = str(panel.get("parent_figure_id") or "")
            panels_by_figure.setdefault(parent, []).append(panel)

    cards = []
    for figure in figures[:MAX_VISUAL_FIGURES]:
        if not isinstance(figure, dict):
            continue
        figure_id = str(figure.get("figure_id") or "-")
        label = str(figure.get("label") or "-")
        caption = str(figure.get("caption") or "")[:MAX_FIGURE_CAPTION_LENGTH]
        image_path = str(figure.get("source_image_path") or "")
        panel_count = figure.get("panel_count", 0)
        figure_panels = panels_by_figure.get(figure_id, [])

        panel_thumbnails = ""
        if figure_panels:
            panel_items = []
            for panel in figure_panels[:MAX_VISUAL_PANELS_PER_FIGURE]:
                panel_id = str(panel.get("panel_id") or "-")
                panel_label = str(panel.get("label") or "-")
                panel_crop = str(panel.get("crop_path") or "")
                panel_w = panel.get("width", 0)
                panel_h = panel.get("height", 0)
                confidence = panel.get("extraction_confidence", 0)
                method = str(panel.get("extraction_method") or "-")
                fallback_note = (
                    " | fallback" if method == "whole_figure_fallback" else ""
                )
                img_tag = (
                    f'<img src="{h(panel_crop)}" alt="panel {h(panel_label)}" loading="lazy" />'
                    if panel_crop
                    else '<div style="height:120px;background:#f4f0e6;border-radius:8px;"></div>'
                )
                panel_items.append(
                    f'<div class="visual-panel-card">'
                    f"{img_tag}"
                    f'<div class="panel-label">{h(panel_label)}</div>'
                    f'<div class="panel-meta">{h(panel_id)} | {h(panel_w)}x{h(panel_h)} | conf={h(f"{confidence:.2f}")} | {h(method)}{h(fallback_note)}</div>'
                    f"</div>"
                )
            panel_thumbnails = (
                '<div class="visual-panel-grid">' + "".join(panel_items) + "</div>"
            )

        img_tag = (
            f'<img src="{h(image_path)}" alt="figure {h(label)}" loading="lazy" />'
            if image_path
            else '<div style="height:180px;background:#f4f0e6;border-radius:12px;"></div>'
        )
        cards.append(
            f'<div class="visual-figure-card">'
            f"{img_tag}"
            f"<h4>{h(label)}</h4>"
            f'<p class="muted">{h(caption)}</p>'
            f'<p class="muted" style="font-size:11px;"><code>{h(figure_id)}</code> | panels: {h(panel_count)}</p>'
            f"{panel_thumbnails}"
            f"</div>"
        )

    return '<div class="visual-figure-grid">' + "\n".join(cards) + "</div>"


def _visual_relationship_table(rels: list[dict[str, Any]]) -> str:
    if not rels:
        return "<p class='muted'>未发现 panel 间相似关系。</p>"
    sorted_rels = sorted(
        [r for r in rels if isinstance(r, dict)],
        key=lambda r: -(r.get("score") or 0),
    )
    rows = []
    for rel in sorted_rels[:MAX_VISUAL_RELATIONSHIPS]:
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
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _visual_review_queue_table(tasks: list[dict[str, Any]]) -> str:
    tasks = [task for task in tasks if isinstance(task, dict)]
    if not tasks:
        return "<p class='muted'>未生成图像复核队列。</p>"
    rows = []
    for task in tasks[:MAX_VISUAL_REVIEW_QUEUE]:
        priority = str(task.get("priority") or "medium")
        quality = str(task.get("panel_extraction_quality") or "unknown")
        quality_note = (
            "fallback 降级" if quality == "whole_figure_fallback" else quality
        )
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
    for cluster in clusters[:MAX_VISUAL_CLUSTERS]:
        risk = str(cluster.get("risk_level") or "medium")
        quality = str(cluster.get("panel_extraction_quality") or "unknown")
        representatives = ", ".join(
            str(item) for item in (cluster.get("representative_finding_ids") or [])[:5]
        )
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


def _resolve_panel(
    panel_id: str, panels_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
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


def _visual_finding_cards(
    visual_findings: list[dict[str, Any]], panels: list[dict[str, Any]]
) -> str:
    """Generate visual finding cards with overlay comparison."""
    if not visual_findings:
        return "<p class='muted'>未生成图像记录。</p>"

    from engine.static_audit.visual_schemas import check_language_compliance

    panels_by_id = _panel_lookup(panels)

    cards = []
    for finding in visual_findings[:MAX_VISUAL_FINDINGS]:
        if not isinstance(finding, dict):
            continue

        finding_id = str(finding.get("finding_id") or "-")
        category = str(finding.get("category") or "-")
        risk_level = str(finding.get("risk_level") or "medium")
        raw_summary = str(finding.get("summary") or "")
        summary = clean_report_text(raw_summary)

        violations = check_language_compliance(raw_summary)
        if violations:
            summary = (
                "该图像记录的原始摘要包含报告禁用措辞，已隐藏；请人工复核结构化证据。"
            )

        source_panel_id = str(finding.get("source_panel_id") or "-")
        target_panel_id = str(finding.get("target_panel_id") or "-")
        score = finding.get("score", 0)
        overlay_path = finding.get("overlay_path")
        metadata = (
            finding.get("metadata") if isinstance(finding.get("metadata"), dict) else {}
        )
        quality = str(metadata.get("panel_extraction_quality") or "unknown")
        quality_note = (
            "fallback panel evidence; risk display capped"
            if quality == "whole_figure_fallback"
            else quality
        )

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
        benign_html = (
            "<ul>" + "".join(benign_items) + "</ul>"
            if benign_items
            else "<p class='muted'>未记录良性解释。</p>"
        )

        overlay_html = ""
        if overlay_path:
            overlay_html = (
                f'<div class="overlay-compare">'
                f'<div><p class="muted" style="font-size:11px;">source panel: {h(source_panel_id)}</p>'
                f"{_visual_img(source_crop, 'source')}</div>"
                f'<div><p class="muted" style="font-size:11px;">target panel: {h(target_panel_id)}</p>'
                f"{_visual_img(target_crop, 'target')}</div>"
                f'<div><p class="muted" style="font-size:11px;">overlay / heatmap</p>'
                f"{_visual_img(str(overlay_path), 'overlay')}</div>"
                f"</div>"
                f'<p class="muted" style="font-size:11px;margin-top:8px;">overlay: <code>{h(str(overlay_path))}</code></p>'
            )
        elif source_crop and target_crop:
            overlay_html = (
                f'<div class="overlay-compare">'
                f'<div><p class="muted" style="font-size:11px;">source panel: {h(source_panel_id)}</p>'
                f"{_visual_img(source_crop, 'source')}</div>"
                f'<div><p class="muted" style="font-size:11px;">target panel: {h(target_panel_id)}</p>'
                f"{_visual_img(target_crop, 'target')}</div>"
                f"</div>"
            )
        cap_reason = metadata.get("confidence_adjustment") or metadata.get(
            "risk_cap_reason"
        )
        cap_note = f"<span> | risk note: {h(cap_reason)}</span>" if cap_reason else ""

        anchor_id = f"finding-{finding_id.replace('.', '-').replace(' ', '-')}"
        cards.append(
            f'<article class="visual-finding-card" id="{h(anchor_id)}">'
            f'<div class="finding-header">'
            f'<span class="badge {h(risk_level)}">{h(risk_label(risk_level))}</span>'
            f'<span class="badge">{h(category)}</span>'
            f"<h3>{h(finding_id)}</h3>"
            f"</div>"
            f"<p><strong>摘要：</strong>{h(summary)}</p>"
            f'<p class="muted" style="font-size:12px;">score: {h(f"{score:.3f}")} | panel quality: {h(quality_note)} | source: <code>{h(source_panel_id)}</code> | target: <code>{h(target_panel_id)}</code>{cap_note}</p>'
            f'<details style="margin-top:12px;">'
            f"<summary>Panel 比较与 overlay</summary>"
            f"{overlay_html}"
            f"</details>"
            f'<details style="margin-top:8px;">'
            f"<summary>良性解释</summary>"
            f"{benign_html}"
            f"</details>"
            f"</article>"
        )

    return "\n".join(cards)


def _visual_review_checklist(questions: list[str]) -> str:
    """Generate manual review checklist."""
    if not questions:
        return "<p class='muted'>未生成视觉复核问题。</p>"
    items = [f"<li>{_confidence_badge('data')}{h(q)}</li>" for q in questions[:10]]
    return "<ul class='visual-review-checklist'>" + "".join(items) + "</ul>"
