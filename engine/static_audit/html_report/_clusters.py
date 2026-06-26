"""Evidence cluster building, rendering, and shared cross-reference helpers."""
# All f-string interpolations MUST use h() or h_attr() for XSS protection.

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from engine.static_audit.html_report._html_utils import h
from engine.static_audit.html_report._config import (
    MAX_CLUSTER_CLAIM_LENGTH,
    MAX_EVIDENCE_CLUSTERS,
    MAX_CLUSTERS_IN_BRIEF,
    MAX_CLAIMS_PER_CLUSTER,
    MAX_TASKS_PER_CLUSTER,
    MAX_SIGNALS_PER_CLUSTER,
    MAX_SHEETS_IN_HEADLINE,
    MAX_CATEGORIES_IN_HEADLINE,
    DEFAULT_CLUSTER_TASK_ITEMS,
)
from engine.static_audit.html_report._shared import (
    category_label,
    clean_report_text,
    finding_display_score,
    finding_support_value,
    highest_display_risk,
    list_items,
    ref_mentions_finding,
    risk_label,
)
from engine.static_audit.html_report._source_data import (
    evidence_source_text as _evidence_source_text,
)
from engine.static_audit.html_report._benign import (
    _benign_items_to_html,
    cluster_benign_explanations,
)
from engine.static_audit.html_report._findings import (
    source_artifact_for_findings,
    support_text,
)


def claims_for_finding_ids(
    finding_ids: list[str],
    claims: list[dict[str, Any]],
    claim_mappings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    claim_ids: set[str] = set()
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
        if claim_id in claim_ids or any(
            ref_mentions_finding(ref, finding_ids) for ref in refs
        ):
            result.append(claim)
    return result


def tasks_for_finding_ids(
    finding_ids: list[str], tasks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        refs = task.get("evidence_refs") or []
        if any(ref_mentions_finding(ref, finding_ids) for ref in refs):
            result.append(task)
    return result


def cluster_headline(
    sheet: str, findings: list[dict[str, Any]], claims: list[dict[str, Any]]
) -> str:
    """Generate a headline for an evidence cluster."""
    categories = Counter(str(f.get("category", "-")) for f in findings)
    category_text = "、".join(category_label(c) for c, _ in categories.most_common(MAX_CATEGORIES_IN_HEADLINE))
    claim_hint = f"；已关联 {len(claims)} 条论文表述" if claims else ""
    return f"{sheet} 聚集了 {len(findings)} 条高优先级记录，主要类别为 {category_text or '复核记录'}{claim_hint}，建议作为人工复核入口。"


def finding_signal(finding: dict[str, Any]) -> str:
    """Generate a signal description for a finding."""
    category = str(finding.get("category", "-"))
    support = support_text(finding)
    columns = (
        finding.get("columns")
        or finding.get("column_pair")
        or finding.get("column")
        or []
    )
    columns_text = (
        ", ".join(str(i) for i in columns)
        if isinstance(columns, list)
        else str(columns)
    )
    if category == "row_offset_scalar_multiple":
        return f"固定行偏移 {finding.get('row_offset', '-')} 后出现标量关系；列 {columns_text or '-'}；{support}。"
    if category == "long_format_paired_ratio_reuse":
        return f"long-format paired 数据在 pair_id 偏移 {finding.get('pair_id_offset', '-')} 后出现比例复用；列 {columns_text or '-'}；{support}。"
    if category == "duplicate_row_vector":
        return f"低宽度行向量重复；重复行数 {finding.get('duplicate_row_count', '-')}；列 {columns_text or '-'}。"
    if category == "long_format_within_pair_ratio_enrichment":
        return f"paired 数据内部特定比例富集；matched_pair_groups={finding.get('matched_pair_groups', '-')}；列 {columns_text or '-'}。"
    if category == "row_offset_partial_copy_rounding_bias":
        return f"行偏移后出现部分复制与四舍五入偏差；exact_reuse_pairs={finding.get('exact_reuse_pairs', '-')}；{support}。"
    if columns_text:
        return f"{category_label(category)}；{support}；列 {columns_text}。"
    return f"{category_label(category)}；{support}；source={_evidence_source_text(finding)}。"


def build_evidence_clusters(
    findings: list[dict[str, Any]],
    claim_mappings: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    manual_tasks: list[dict[str, Any]],
    source_reviews: dict[str, dict[str, Any]],
    judge_risks: list[dict[str, Any]],
    max_clusters: int = MAX_EVIDENCE_CLUSTERS,
) -> list[dict[str, Any]]:
    """Build evidence clusters grouped by workbook/sheet, ranked by risk and size."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        source = str(
            finding.get("workbook")
            or finding.get("source_path")
            or finding.get("source_artifact")
            or "-"
        )
        anchor = str(
            finding.get("sheet")
            or finding.get("figure")
            or finding.get("panel_id")
            or finding.get("category")
            or "-"
        )
        grouped[(source, anchor)].append(finding)
    ranked_groups = sorted(
        grouped.items(),
        key=lambda item: (
            -max(finding_display_score(f) for f in item[1]),
            -len(item[1]),
            item[0][1],
            item[0][0],
        ),
    )
    clusters = []
    for index, ((source, anchor), group_findings) in enumerate(
        ranked_groups[:max_clusters], start=1
    ):
        group_findings = sorted(
            group_findings,
            key=lambda f: (
                -finding_display_score(f),
                -finding_support_value(f),
                str(f.get("finding_id", "")),
            ),
        )
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
        categories = Counter(str(f.get("category", "-")) for f in group_findings)
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
                "signals": [finding_signal(f) for f in group_findings[:MAX_SIGNALS_PER_CLUSTER]],
                "benign_explanations": cluster_benign_explanations(
                    group_findings, reviews
                ),
                "source_artifact": source_artifact_for_findings(group_findings),
            }
        )
    return clusters


def evidence_cluster_cards(clusters: list[dict[str, Any]]) -> str:
    """Render evidence cluster cards as HTML."""
    if not clusters:
        return "<p class='muted'>未形成主证据簇。请查看技术附录中的原始工具输出。</p>"
    cards = []
    for index, cluster in enumerate(clusters, start=1):
        claims = cluster.get("claims") or []
        claim_items = [
            f"<li><code>{h(claim.get('claim_id', '-'))}</code> {h((claim.get('claim_text') or claim.get('text') or '-')[:MAX_CLUSTER_CLAIM_LENGTH])}</li>"
            for claim in claims[:MAX_CLAIMS_PER_CLUSTER]
        ] or ["<li class='muted'>未自动关联到具体论文表述，需人工补映射。</li>"]
        tasks = cluster.get("manual_tasks") or []
        task_items = [
            clean_report_text(t.get("question", ""))
            for t in tasks[:MAX_TASKS_PER_CLUSTER]
            if t.get("question")
        ]
        if not task_items:
            task_items = DEFAULT_CLUSTER_TASK_ITEMS
        categories = cluster.get("categories") or Counter()
        category_text = ", ".join(
            f"{category_label(k)}×{h(v)}" for k, v in categories.most_common()
        )
        cards.append(f"""
<article class="cluster-card" id="{h(cluster.get("cluster_id"))}">
  <div class="cluster-top">
    <div>
      <div class="cluster-title">
        <span class="rank">{h(index)}</span>
        <span class="badge {h(cluster.get("risk_level"))}">{h(risk_label(cluster.get("risk_level")))}</span>
        <h3>{h(cluster.get("sheet"))} · {h(category_text or "复核记录")}</h3>
      </div>
      <p><strong>为什么先看：</strong>{h(cluster.get("headline"))}</p>
      <ul class="signal-list">{list_items(cluster.get("signals") or [])}</ul>
    </div>
    <aside class="lane">
      <h3>证据定位</h3>
      <div class="kv">
        <div>cluster</div><div><code>{h(cluster.get("cluster_id"))}</code></div>
        <div>source</div><div><code>{h(cluster.get("workbook"))}</code></div>
        <div>anchor</div><div><code>{h(cluster.get("sheet"))}</code></div>
        <div>记录 ID</div><div><code>{h(", ".join(cluster.get("finding_ids") or []))}</code></div>
        <div>artifact</div><div><code>{h(cluster.get("source_artifact"))}</code></div>
      </div>
    </aside>
  </div>
  <div class="grid cols-2 section">
    <div><h3>关联的论文表述</h3><ul>{"".join(claim_items)}</ul></div>
    <div><h3>人工复核动作</h3><ul>{list_items(task_items)}</ul></div>
  </div>
  <details><summary>可能的良性解释与原始记录</summary>
    <div class="grid cols-2 section">
      <div><h3>良性解释</h3>{_benign_items_to_html(cluster.get("benign_explanations") or [])}</div>
      <div><h3>原始记录</h3><ul>{list_items(cluster.get("finding_ids") or [])}</ul></div>
    </div>
  </details>
</article>
""")
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
