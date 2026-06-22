"""Entry point for HTML report generation.

This module was split from a 4300+ line God File.  All rendering logic
now lives in sibling sub-modules; this file only orchestrates data
loading and assembles the final HTML document.

Backward-compatible re-exports are provided at the bottom so that
existing ``from engine.static_audit.html_report._core import ...``
imports continue to work.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.static_audit.html_report._html_utils import h
from engine.static_audit.html_report._styles import REPORT_CSS
from engine.static_audit.html_report._shared import (
    _confidence_badge,
    clean_report_text,
    list_items,
    metric,
    read_json,
    status_label,
)
from engine.static_audit.html_report._appendix import (
    artifact_links,
    canonical_mapping_table,
    claim_impact_matrix,
    investigation_table,
    judge_summary_text,
    material_plan_panel,
    risks_table,
    steps_table,
    traces_table,
)
from engine.static_audit.html_report._clusters import (
    build_evidence_clusters,
    evidence_cluster_cards,
)
from engine.static_audit.html_report._executive import (
    collect_limitations,
    executive_summary,
    hero_action_list,
    hero_metric,
    hero_pattern_list,
    report_verdict,
    source_coverage_value,
)
from engine.static_audit.html_report._findings import (
    annotate_findings,
    collect_report_findings,
    dedupe_findings,
    evidence_card_findings,
    finding_display_score,
    map_findings_to_mappings,
    map_reviews,
    render_findings_by_category,
)
from engine.static_audit.html_report._manual_tasks import manual_tasks_table
from engine.static_audit.html_report._patterns import (
    build_pattern_groups,
    displayable_patterns,
    irreducible_evidence_ledger,
    pattern_group_cards,
    tier_patterns,
)
from engine.static_audit.html_report._shared import (
    SOURCE_DATA_FINDINGS_ARTIFACT,
    risk_score,
)
from engine.static_audit.html_report._source_data import (
    excluded_findings_section,
    pair_forensics_cluster_table,
    pair_forensics_review_tasks_table,
    pair_forensics_table,
    paperfraud_rule_section,
)
from engine.static_audit.html_report._visual import visual_evidence_section
from engine.static_audit.investigation import read_investigation_records
from engine.static_audit.paths import resolve_artifact_path


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

    verdict_by_id: dict[str, dict[str, Any]] = {}
    for sv in verdict_data.get("sheets", []):
        for fv in sv.get("findings", []):
            fid = fv.get("id")
            if fid:
                verdict_by_id[fid] = fv

    primary_findings = collect_report_findings(source_findings, pair_forensics, bundle)

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
        active_findings, source_auditor.get("claim_to_source_data") or [],
        claim_extractor.get("claims") or canonical_claims, manual_tasks,
        source_reviews, judge_risks,
    )
    cluster_cards = evidence_cluster_cards(evidence_clusters)
    pattern_findings = dedupe_findings(
        active_findings + annotate_findings(
            source_findings.get("formula_derived_columns") or [],
            SOURCE_DATA_FINDINGS_ARTIFACT,
        )
    )
    patterns = build_pattern_groups(
        pattern_findings, source_auditor.get("claim_to_source_data") or [],
        claim_extractor.get("claims") or canonical_claims, manual_tasks,
        source_reviews, judge_risks,
    )
    summarized_patterns = displayable_patterns(patterns)
    primary_patterns, secondary_patterns = tier_patterns(summarized_patterns)
    pattern_cards_primary = pattern_group_cards(primary_patterns)
    pattern_cards_secondary = pattern_group_cards(secondary_patterns)
    evidence_ledger_html = irreducible_evidence_ledger(patterns)
    hero_summary = executive_summary(
        summarized_patterns, active_findings, bundle_counts, profile_summary, exact_images,
    )
    verdict = report_verdict(active_findings, manual_tasks, tool_runs, bundle)

    card_findings = evidence_card_findings(active_findings)
    priority_record_count = sum(
        1 for f in active_findings if finding_display_score(f) >= risk_score("high")
    )
    card_title = (
        f"代表性证据卡（展示 {len(card_findings)} / {len(active_findings)} 条）"
        if active_findings else "重点人工复核证据卡"
    )
    cards = render_findings_by_category(
        card_findings, linked_mapping_by_finding, source_reviews, judge_risks,
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Veritas 静态审查 Demo · {h(case_id)}</title>
  <style>
{REPORT_CSS}
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
        <div><div class="eyebrow">先看这里</div><h2>{h("重点事实" if summarized_patterns else "覆盖范围")}</h2>
        <p class="muted">这里只放已经形成摘要的事实；没有摘要的类别只保留原始定位和值。</p></div>
        {hero_pattern_list(summarized_patterns)}
        <div><h3>下一步动作</h3>{hero_action_list(manual_tasks)}</div>
        <nav class="quick-nav" aria-label="report shortcuts">
          <a href="#top-patterns">重点事实</a><a href="#noise-ledger">原始证据</a>
          <a href="#claim-impact">表述对照</a><a href="#manual-review">人工复核</a>
          <a href="#appendix">技术附录</a>
        </nav>
      </aside>
    </section>

    <section class="section" id="top-patterns">
      <div class="section-head"><div><h2>必须立即追问</h2>
        <p class="muted">risk_level ∈ {{critical, high}} 且 issue_category == consistency 的 top 20 记录</p></div>
        <span class="badge high">{h(len(primary_patterns))} 类</span></div>
      {pattern_cards_primary}
    </section>

    <section class="section" id="secondary-patterns">
      <h2>提示性记录</h2>
      <details><summary>展开 {h(len(secondary_patterns))} 条提示性记录</summary>{pattern_cards_secondary}</details>
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

    <section class="panel section" id="paperfraud-rules">{paperfraud_rule_section(paperfraud_matches)}</section>

    <section class="panel section" id="coverage">
      <h2>覆盖范围与限制</h2>
      <div class="grid cols-4">
        {metric("证据记录", ledger_stats.get("ledger_items", "-"))}
        {metric("数值单元格", profile_summary.get("numeric_cell_count", "-"))}
        {metric("公式单元格", profile_summary.get("formula_count", "-"))}
        {metric("复核轨迹", bundle_counts["agent_traces"])}
      </div>
      <ul>{list_items(collect_limitations(bundle, agent_judge, similarity))}</ul>
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
          <h3>复核项</h3>{pair_forensics_review_tasks_table(pair_forensics.get("review_tasks") or [])}
          <h3>记录簇</h3>{pair_forensics_cluster_table(pair_forensics.get("finding_clusters") or [])}
          <h3>代表性原始记录</h3>{pair_forensics_table(pair_forensics.get("priority_findings") or [])}
        </details>
        {excluded_findings_section(excluded_findings, verdict_summary)}
        <details class="compact-details">
          <summary><span><strong>运行步骤与复核轨迹</strong><br/><span class="muted">运行步骤、状态和各复核步骤的输出路径。</span></span><span class="badge skipped">展开</span></summary>
          <div class="grid cols-2"><div><h3>执行状态</h3>{steps_table(tool_runs)}</div>
          <div><h3>复核步骤</h3>{traces_table(traces)}</div></div>
        </details>
        <details class="compact-details">
          <summary><span><strong>确定性检查摘要</strong><br/><span class="muted">Source Data、PDF 数字取证和图像检查的原始摘要。</span></span><span class="badge skipped">展开</span></summary>
          <div class="grid cols-3">
            <div class="lane"><h3>Source Data</h3><div class="kv">
              <div>workbook 数</div><div>{h(profile_summary.get("workbook_count", "-"))}</div>
              <div>sheet 数</div><div>{h(profile_summary.get("sheet_count", "-"))}</div>
              <div>重复列记录</div><div>{h(source_summary.get("duplicate_column_findings", "-"))}</div>
              <div>固定关系记录</div><div>{h(source_summary.get("fixed_relationship_findings", "-"))}</div>
              <div>错误数</div><div>{h(source_summary.get("errors", "-"))}</div>
            </div></div>
            <div class="lane"><h3>PDF 数字取证</h3><div class="kv">
              <div>提取数字数</div><div>{h(numeric.get("all_number_count", "-"))}</div>
              <div>有效数字数</div><div>{h(numeric.get("number_count", "-"))}</div>
              <div>表格数</div><div>{h(numeric.get("table_count", "-"))}</div>
              <div>Benford MAD</div><div>{h((numeric.get("benford") or {}).get("mad", (numeric.get("benford") or {}).get("mean_absolute_deviation", "-")))}</div>
            </div></div>
            <div class="lane"><h3>图像检查</h3><div class="kv">
              <div>图片数</div><div>{h(exact_images.get("image_count", "-"))}</div>
              <div>字节级重复组</div><div>{h(exact_images.get("duplicate_group_count", "-"))}</div>
              <div>近似重复状态</div><div>{h(status_label(similarity.get("status", "-")))}</div>
              <div>方法</div><div>{h(similarity.get("method", "-"))}</div>
            </div></div>
          </div>
        </details>
        <details class="compact-details">
          <summary><span><strong>产物链接与复核摘要</strong><br/><span class="muted">原始 JSON/Markdown 产物和结构化复核摘要。</span></span><span class="badge skipped">展开</span></summary>
          {artifact_links(workdir)}
          <h3>整体复核摘要</h3>
          <p>{h(clean_report_text(judge_summary_text(judge_summary, claim_extractor, source_auditor)))}</p>
          <h3>复核摘要</h3>{risks_table(judge_risks)}
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
