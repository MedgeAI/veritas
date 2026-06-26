"""Appendix tables: steps, traces, material plan, mappings, investigation, risks, artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.static_audit.html_report._html_utils import h
from engine.static_audit.html_report._config import (
    MAX_STEP_DETAIL_LENGTH,
    MAX_INVESTIGATION_RECORDS,
    MAX_INVESTIGATION_DETAIL_LENGTH,
    MAX_CANONICAL_MAPPINGS,
    MAX_CLAIM_TEXT_IN_MAPPING,
    MAX_SOURCE_MAPPINGS,
)
from engine.static_audit.html_report._shared import (
    clean_report_text,
    risk_label,
    risk_score,
    shorten,
    status_label,
    summary_text,
)
from engine.static_audit.html_report._manual_tasks import (
    display_risk_level_for_judge_risk,
)
from engine.static_audit.paths import resolve_artifact_path


def steps_table(steps: list[dict[str, Any]]) -> str:
    """Render execution steps as an HTML table."""
    rows = []
    for step in steps:
        key = step.get("key") or step.get("step_key") or "-"
        title = step.get("title", key)
        status = step.get("status", "-")
        detail = str(step.get("detail", ""))[:MAX_STEP_DETAIL_LENGTH]
        rows.append(
            f"<tr><td><code>{h(key)}</code></td><td>{h(clean_report_text(title))}</td>"
            f"<td><span class='badge {h(status)}'>{h(status_label(status))}</span></td>"
            f"<td>{h(clean_report_text(detail))}</td></tr>"
        )
    return (
        "<table><thead><tr><th>步骤 key</th><th>步骤</th><th>状态</th><th>说明</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def traces_table(traces: list[dict[str, Any]]) -> str:
    from collections import Counter

    rows = []
    counts = Counter(trace.get("status", "-") for trace in traces)
    for trace in traces:
        status = str(trace.get("status", "-"))
        rows.append(
            f"<tr><td><code>{h(trace.get('role_id', '-'))}</code></td>"
            f"<td><span class='badge {h(status)}'>{h(status_label(status))}</span></td>"
            f"<td>{h(summary_text(trace.get('output_summary') or {}))}</td>"
            f"<td><code>{h(trace.get('output_path', '-'))}</code></td></tr>"
        )
    summary = " ".join(
        f"<span class='badge {h(k)}'>{h(status_label(k))} {v}</span>"
        for k, v in sorted(counts.items())
    )
    return f"<p>{summary}</p><table><thead><tr><th>role</th><th>状态</th><th>摘要</th><th>输出文件</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"


def material_plan_panel(
    material_summary: dict[str, Any], material_plan: dict[str, Any]
) -> str:
    lanes = [
        lane
        for lane in (material_plan.get("selected_optional_lanes") or [])
        if isinstance(lane, dict)
    ]
    lane_rows = []
    for lane in lanes:
        status = str(lane.get("status", "-"))
        lane_rows.append(
            "<tr>"
            f"<td><code>{h(lane.get('lane_id', '-'))}</code></td>"
            f"<td><span class='badge {h(status)}'>{h(status_label(status))}</span></td>"
            f"<td><code>{h(lane.get('root') or '-')}</code></td>"
            f"<td>{h(clean_report_text(lane.get('reason', '-')))}</td></tr>"
        )
    if not lane_rows:
        lane_rows.append("<tr><td colspan='4'>未选择 optional lane。</td></tr>")
    material_types = (
        material_summary.get("by_material_type")
        if isinstance(material_summary.get("by_material_type"), dict)
        else {}
    )
    unsupported = material_plan.get("unsupported_materials") or []
    unsupported_text = (
        ", ".join(
            str(item.get("path", item))
            for item in unsupported[:6]
            if isinstance(item, dict)
        )
        or "-"
    )
    return f"""
<div class="grid cols-2">
  <div class="lane"><h3>材料清单</h3><div class="kv">
    <div>文件数</div><div>{h(material_summary.get("file_count", "-"))}</div>
    <div>材料类型</div><div>{h(", ".join(f"{k}={v}" for k, v in material_types.items()) or "-")}</div>
    <div>候选根目录</div><div>{h(material_summary.get("candidate_source_roots", "-"))}</div>
    <div>可执行 lane</div><div>{h(material_summary.get("supported_optional_lanes", "-"))}</div>
  </div></div>
  <div class="lane"><h3>材料处理计划</h3><div class="kv">
    <div>状态</div><div>{h(status_label(material_plan.get("status", "ok") if material_plan else "missing"))}</div>
    <div>缺失材料</div><div>{h(", ".join(str(i) for i in (material_plan.get("missing_materials") or [])) or "-")}</div>
    <div>暂不支持材料</div><div>{h(unsupported_text)}</div>
  </div></div>
</div>
<table><thead><tr><th>lane</th><th>状态</th><th>根目录</th><th>选择原因</th></tr></thead><tbody>{"".join(lane_rows)}</tbody></table>
"""


def canonical_mapping_table(
    claims: list[dict[str, Any]], mappings: list[dict[str, Any]]
) -> str:
    mappings = [m for m in mappings if isinstance(m, dict)]
    claims = [c for c in claims if isinstance(c, dict)]
    if not mappings:
        return "<p class='muted'>未生成精炼映射；如存在确定性脚手架，请查看对应工具 JSON。</p>"
    claim_by_id = {str(c.get("claim_id")): c for c in claims if c.get("claim_id")}
    rows = []
    for mapping in mappings[:MAX_CANONICAL_MAPPINGS]:
        claim = claim_by_id.get(str(mapping.get("claim_id"))) or {}
        metadata = (
            mapping.get("metadata") if isinstance(mapping.get("metadata"), dict) else {}
        )
        source_refs = (
            metadata.get("source_data_refs") or mapping.get("evidence_refs") or []
        )
        needs_review = metadata.get("needs_human_review")
        rows.append(
            "<tr>"
            f"<td><code>{h(mapping.get('mapping_id', '-'))}</code></td>"
            f"<td><code>{h(mapping.get('claim_id', '-'))}</code></td>"
            f"<td>{h(str(claim.get('text', '-'))[:MAX_CLAIM_TEXT_IN_MAPPING])}</td>"
            f"<td>{h(mapping.get('confidence', '-'))}</td>"
            f"<td><span class='badge warning'>{h('需人工复核' if needs_review is not False else '低优先级')}</span></td>"
            f"<td><code>{h(', '.join(str(r) for r in source_refs[:4]) or '-')}</code></td></tr>"
        )
    return (
        "<table><thead><tr><th>mapping</th><th>表述 ID</th><th>论文表述</th><th>置信度</th><th>复核状态</th><th>证据 refs</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def investigation_table(records: list[dict[str, Any]]) -> str:
    """Render investigation rounds as an HTML table."""
    records = [r for r in records if isinstance(r, dict)]
    if not records:
        return "<p class='muted'>本次未生成 investigation round 记录。</p>"
    rows = []
    for record in records[:MAX_INVESTIGATION_RECORDS]:
        status = str(record.get("status", "skipped"))
        artifacts = record.get("output_artifacts") or []
        rows.append(
            "<tr>"
            f"<td>{h(record.get('round_id', '-'))}</td>"
            f"<td><code>{h(record.get('action_id', '-'))}</code></td>"
            f"<td><code>{h(record.get('tool_id', '-'))}</code></td>"
            f"<td><span class='badge {h(status)}'>{h(risk_label(status))}</span></td>"
            f"<td>{h(shorten(clean_report_text(record.get('hypothesis') or record.get('detail') or '-'), MAX_INVESTIGATION_DETAIL_LENGTH))}</td>"
            f"<td>{h(', '.join(str(i) for i in artifacts[:3]) or '-')}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Round</th><th>Action</th><th>Tool</th><th>Status</th><th>Hypothesis / Detail</th><th>Artifact</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def risks_table(risks: list[dict[str, Any]]) -> str:
    rows = []
    for risk in sorted(
        [r for r in risks if isinstance(r, dict)],
        key=lambda r: -risk_score(display_risk_level_for_judge_risk(r)),
    ):
        risk_level = display_risk_level_for_judge_risk(risk)
        rows.append(
            f"<tr><td><span class='badge {h(risk_level)}'>{h(risk_label(risk_level))}</span></td>"
            f"<td>{h(clean_report_text(risk.get('reason', '')))}</td>"
            f"<td>{h(', '.join(str(i) for i in (risk.get('evidence_refs') or [])[:8]))}</td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='3'>未生成复核摘要。</td></tr>")
    return (
        "<table><thead><tr><th>优先级</th><th>原因</th><th>证据 refs</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


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
            f"<div class='artifact'><span><code>{h(name)}</code></span>"
            f"<span><span class='badge {status}'>{status_label(status)}</span> {h(size)} 字节</span></div>"
        )
    return "<div class='artifact-list'>" + "".join(rows) + "</div>"


def claim_impact_matrix(
    source_mappings: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    canonical_mappings: list[dict[str, Any]],
) -> str:
    claims_by_id = {
        str(c.get("claim_id")): c
        for c in claims
        if isinstance(c, dict) and c.get("claim_id")
    }
    rows = []
    if source_mappings:
        for mapping in source_mappings[:MAX_SOURCE_MAPPINGS]:
            if not isinstance(mapping, dict):
                continue
            claim = claims_by_id.get(str(mapping.get("claim_id"))) or {}
            refs = [
                str(r)
                for r in (
                    mapping.get("source_data_refs")
                    or mapping.get("evidence_refs")
                    or []
                )
            ]
            finding_refs = [
                r for r in refs if "forensics:" in r or "finding" in r.lower()
            ]
            needs_review = mapping.get("needs_human_review")
            rows.append(
                "<tr>"
                f"<td><code>{h(mapping.get('claim_id', '-'))}</code></td>"
                f"<td>{h((claim.get('claim_text') or claim.get('text') or '-')[:MAX_CLAIM_TEXT_IN_MAPPING])}</td>"
                f"<td><code>{h(', '.join(refs[:4]) or '-')}</code></td>"
                f"<td><code>{h(', '.join(finding_refs[:6]) or '-')}</code></td>"
                f"<td><span class='badge {'warning' if needs_review is not False else 'low'}'>{h('需人工复核' if needs_review is not False else '低优先级')}</span></td></tr>"
            )
    elif canonical_mappings:
        for mapping in canonical_mappings[:MAX_SOURCE_MAPPINGS]:
            if not isinstance(mapping, dict):
                continue
            claim = claims_by_id.get(str(mapping.get("claim_id"))) or {}
            refs = [str(r) for r in (mapping.get("evidence_refs") or [])]
            finding_refs = [str(r) for r in (mapping.get("finding_refs") or refs)]
            metadata = (
                mapping.get("metadata")
                if isinstance(mapping.get("metadata"), dict)
                else {}
            )
            needs_review = metadata.get("needs_human_review")
            rows.append(
                "<tr>"
                f"<td><code>{h(mapping.get('claim_id', '-'))}</code></td>"
                f"<td>{h((claim.get('claim_text') or claim.get('text') or '-')[:MAX_CLAIM_TEXT_IN_MAPPING])}</td>"
                f"<td><code>{h(', '.join(refs[:4]) or '-')}</code></td>"
                f"<td><code>{h(', '.join(finding_refs[:6]) or '-')}</code></td>"
                f"<td><span class='badge {'warning' if needs_review is not False else 'low'}'>{h('需人工复核' if needs_review is not False else '低优先级')}</span></td></tr>"
            )
    if not rows:
        return "<p class='muted'>未生成论文表述对照表。</p>"
    return (
        "<table><thead><tr><th>表述 ID</th><th>论文表述</th><th>证据引用</th><th>记录引用</th><th>状态</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
