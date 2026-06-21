"""Report generation and static audit bundle assembly for Veritas static audit.

Extracted from orchestrator.py to reduce God Object complexity.
All public names are re-exported via orchestrator for backward compatibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.static_audit.models import (
    Claim,
    ClaimMapping,
    EvidenceItem,
    ExecutionStatus,
    Finding,
    Status,
    StaticAuditBundle,
    ToolRun,
)
from engine.static_audit.investigation import (
    read_investigation_records,
)
from engine.static_audit.tools.paperfraud_rules import (
    paperfraud_findings_from_matches,
)
from engine.static_audit.visual_schemas import check_language_compliance
from engine.tools.registry import selected_tool_ids_from_plan

# ---------------------------------------------------------------------------
# Shared utilities (previously in orchestrator.py, now in _shared.py).
# ---------------------------------------------------------------------------
from engine.static_audit._shared import (
    STEP_TOOL_IDS,
    StepResult,
    resolve_artifact_path,
    read_json,
    fmt_int,
    fmt_float,
    markdown_table,
    priority_row,
    claim_mapping_rows,
    pair_forensics_rows,
    pair_forensics_cluster_rows,
    pair_forensics_review_task_rows,
    canonical_claim_mapping_rows,
    source_finding_params_from_plan,
)


def brief_list(items: Any, limit: int = 8) -> str:
    if not isinstance(items, list) or not items:
        return "-"
    return ", ".join(str(item) for item in items[:limit])


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def agent_manual_review_rows(
    tasks: list[dict[str, Any]], limit: int = 12
) -> list[list[str]]:
    rows = []
    for task in tasks[:limit]:
        refs = task.get("evidence_refs") or []
        rows.append(
            [
                task.get("task_id", "-"),
                task.get("priority", "-"),
                str(task.get("question", "-"))[:220],
                ", ".join(str(item) for item in refs if item) or "-",
            ]
        )
    return rows


def agent_finding_review_rows(
    reviews: list[dict[str, Any]], limit: int = 12
) -> list[list[str]]:
    rows = []
    for review in reviews[:limit]:
        rows.append(
            [
                review.get("finding_id", "-"),
                review.get("assessment", "-"),
                review.get("residual_risk", "-"),
                brief_list(review.get("benign_explanations"), 3),
            ]
        )
    return rows


def investigation_record_rows(
    records: list[dict[str, Any]], limit: int = 20
) -> list[list[str]]:
    rows = []
    for record in records[:limit]:
        artifacts = record.get("output_artifacts") or []
        rows.append(
            [
                record.get("round_id", "-"),
                record.get("action_id", "-"),
                record.get("tool_id", "-"),
                record.get("status", "-"),
                str(record.get("hypothesis") or record.get("detail") or "-")[:180],
                brief_list(artifacts, 3),
            ]
        )
    return rows


@dataclass
class _ReportData:
    """Loaded artifacts and parameters for report generation."""

    workdir: Path
    case_id: str
    paper_dir: Path
    paper_pdf: Path
    source_data_dir: Path | None
    agent_mode: str
    steps: list[StepResult]
    mineru_manifest: dict | None
    material_inventory: dict | None
    material_plan: dict | None
    ledger: dict | None
    numeric: dict | None
    profile: dict | None
    findings: dict | None
    pair_forensics: dict | None
    duplicates: dict | None
    similarity: dict | None
    investigation_records: list
    static_bundle: dict | None
    vlm: dict | None
    agent_plan: dict | None
    agent_review: dict | None
    agent_judge: dict | None = None
    agent_source_data_auditor: dict | None = None


# ---- Section builders -------------------------------------------------------


def _header_section(data: _ReportData) -> list[str]:
    lines: list[str] = []
    lines.append(f"# Veritas Paper Audit Report: {data.case_id}")
    lines.append("")
    lines.append("## 结论先行")
    lines.append("")
    lines.append("- 本报告由本地 orchestrator 汇总确定性脚本产物生成。")
    if data.agent_mode != "off":
        lines.append(
            "- opencode Agent 作为编排与结构化审阅层参与：前置选择/参数填充，后置 claim/finding 复核。"
        )
    lines.append(
        "- 当前不做最终科研诚信判定，只报告技术事实候选、材料缺口和人工复核入口。"
    )
    lines.append(
        "- PDF 是发表呈现层；Source Data、代码、环境和结果文件才是更高价值证据层。"
    )
    if not data.source_data_dir:
        lines.append(
            "- 当前未选择可执行 XLSX/XLSM Source Data optional lane，Source Data 审查被标记为材料缺口或暂不支持。"
        )
    if not data.vlm:
        lines.append("- 当前未执行批量 VLM 视觉审查；视觉结论仅限已有抽样或未覆盖。")
    lines.append("")
    return lines


def _scope_section(data: _ReportData) -> list[str]:
    lines: list[str] = []
    lines.append("## Scope")
    lines.append("")
    lines.append(
        markdown_table(
            ["Item", "Value"],
            [
                ["case_id", data.case_id],
                ["paper_dir", data.paper_dir],
                ["paper_pdf", data.paper_pdf],
                ["selected_source_data_dir", data.source_data_dir or "not_selected"],
                [
                    "material_inventory",
                    resolve_artifact_path(data.workdir, "material_inventory.json"),
                ],
                [
                    "agent_material_plan",
                    resolve_artifact_path(data.workdir, "agent_material_plan.json"),
                ],
                ["workdir", data.workdir],
                ["agent_mode", data.agent_mode],
                ["generated_at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")],
            ],
        )
    )
    lines.append("")
    return lines


def _pipeline_section(data: _ReportData) -> list[str]:
    lines: list[str] = []
    lines.append("## Pipeline Execution")
    lines.append("")
    lines.append(
        markdown_table(
            ["Step", "Status", "Detail"],
            [
                [step.title, step.status, step.detail.replace("\n", " ")[:240]]
                for step in data.steps
            ],
        )
    )
    lines.append("")
    return lines


def _artifact_manifest_section(data: _ReportData) -> list[str]:
    lines: list[str] = []
    lines.append("## Artifact Manifest")
    lines.append("")
    artifact_rows = []
    for name in [
        "mineru_manifest.json",
        "full.md",
        "material_inventory.json",
        "agent_material_plan.json",
        "evidence_ledger.json",
        "numeric_forensics.json",
        "source_data_profile.json",
        "source_data_findings.json",
        "source_data_pair_forensics.json",
        "exact_image_duplicates.json",
        "vlm_triage_selected.json",
        "agent_audit_plan.json",
        "agent_review.json",
        "agent_claim_extractor.json",
        "agent_source_data_auditor.json",
        "agent_visual_triage.json",
        "agent_digit_pattern.json",
        "agent_math_consistency.json",
        "agent_domain_sanity.json",
        "agent_defense.json",
        "agent_judge.json",
        "image_similarity_candidates.json",
        "investigation_rounds.jsonl",
        "static_audit_bundle.json",
    ]:
        p = resolve_artifact_path(data.workdir, name)
        artifact_rows.append(
            [
                name,
                "present" if p.exists() else "missing",
                p.stat().st_size if p.exists() else "-",
            ]
        )
    artifact_rows.append(["final_audit_report.html", "generated_after_markdown", "-"])
    lines.append(markdown_table(["Artifact", "Status", "Bytes"], artifact_rows))
    lines.append("")
    return lines


def _material_section(data: _ReportData) -> list[str]:
    if not (data.material_inventory or data.material_plan):
        return []
    inventory_summary = (data.material_inventory or {}).get("summary", {})
    material_by_type = (
        inventory_summary.get("by_material_type")
        if isinstance(inventory_summary.get("by_material_type"), dict)
        else {}
    )
    selected_lanes = (
        (data.material_plan or {}).get("selected_optional_lanes")
        if isinstance((data.material_plan or {}).get("selected_optional_lanes"), list)
        else []
    )
    selected_lane_text = brief_list(
        [
            f"{lane.get('lane_id')}:{lane.get('status')}:{lane.get('root') or '-'}"
            for lane in selected_lanes
            if isinstance(lane, dict)
        ],
        limit=5,
    )
    lines: list[str] = []
    lines.append("## Material Inventory and Optional Lanes")
    lines.append("")
    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                ["material_files", fmt_int(inventory_summary.get("file_count"))],
                [
                    "material_types",
                    ", ".join(
                        f"{key}={value}" for key, value in material_by_type.items()
                    )
                    or "-",
                ],
                [
                    "candidate_source_roots",
                    fmt_int(inventory_summary.get("candidate_source_roots")),
                ],
                [
                    "supported_optional_lanes",
                    fmt_int(inventory_summary.get("supported_optional_lanes")),
                ],
                [
                    "material_plan_status",
                    (data.material_plan or {}).get("status", "ok"),
                ],
                ["selected_optional_lanes", selected_lane_text],
                [
                    "missing_materials",
                    brief_list((data.material_plan or {}).get("missing_materials")),
                ],
            ],
        )
    )
    unsupported = (data.material_plan or {}).get("unsupported_materials") or []
    if unsupported:
        lines.append("")
        lines.append("Unsupported optional materials detected:")
        for item in unsupported[:8]:
            if isinstance(item, dict):
                lines.append(
                    f"- `{item.get('path', '-')}` ({item.get('material_type', '-')})"
                )
    lines.append("")
    return lines


def _investigation_section(data: _ReportData) -> list[str]:
    if not data.investigation_records:
        return []
    lines: list[str] = []
    lines.append("## Agent Investigation Path")
    lines.append("")
    lines.append(
        "- 本节展示 AgentInvestigationPlanner 的受控调查路径；Agent 只选择 Tool Registry 允许的确定性工具，实际执行由 orchestrator 完成。"
    )
    lines.append(
        markdown_table(
            ["Round", "Action", "Tool", "Status", "Hypothesis", "Artifacts"],
            investigation_record_rows(data.investigation_records),
        )
    )
    lines.append("")
    return lines


def _agent_plan_section(data: _ReportData) -> list[str]:
    if not data.agent_plan:
        return []
    params = source_finding_params_from_plan(data.agent_plan)
    selected_tool_ids = selected_tool_ids_from_plan(data.agent_plan)
    lines: list[str] = []
    lines.append("## Agent Audit Plan Summary")
    lines.append("")
    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                ["status", data.agent_plan.get("status", "ok")],
                ["selected_tools", brief_list(selected_tool_ids)],
                ["selected_steps", brief_list(data.agent_plan.get("selected_steps"))],
                [
                    "missing_materials",
                    brief_list(data.agent_plan.get("missing_materials")),
                ],
                [
                    "source_data_findings.min_overlap",
                    fmt_int(params.get("min_overlap")),
                ],
                [
                    "source_data_findings.min_support",
                    fmt_float(params.get("min_support"), 3),
                ],
                [
                    "source_data_findings.max_findings_per_category",
                    fmt_int(params.get("max_findings_per_category")),
                ],
            ],
        )
    )
    rationale = data.agent_plan.get("agent_rationale") or []
    if rationale:
        lines.append("")
        lines.append("Agent rationale:")
        for item in rationale[:6]:
            lines.append(f"- {item}")
    lines.append("")
    return lines


def _judge_section(data: _ReportData) -> list[str]:
    """Judge 综合评估：展示 risk_suggestions 和综合判断。"""
    if not data.agent_judge:
        return []
    lines: list[str] = []
    lines.append("## Judge 综合评估")
    lines.append("")

    # 展示 summary
    summary = data.agent_judge.get("summary")
    if summary:
        lines.append(f"**综合判断**: {summary}")
        lines.append("")

    # 展示 risk_suggestions
    risk_suggestions = data.agent_judge.get("risk_suggestions") or []
    if risk_suggestions:
        lines.append("### 风险评估建议")
        lines.append("")
        lines.append(
            markdown_table(
                ["Risk Level", "Reason", "Evidence Refs", "Requires Human Review"],
                [
                    [
                        rs.get("risk_level", "unknown"),
                        rs.get("reason", ""),
                        ", ".join(rs.get("evidence_refs", [])[:3]),
                        "Yes" if rs.get("requires_human_review") else "No",
                    ]
                    for rs in risk_suggestions[:8]
                ],
            )
        )

    # 展示 report_notes
    notes = data.agent_judge.get("report_notes") or []
    if notes:
        lines.append("")
        lines.append("### Judge 报告备注")
        lines.append("")
        for item in notes[:8]:
            lines.append(f"- {item}")

    # 展示 limitations
    limitations = data.agent_judge.get("limitations") or []
    if limitations:
        lines.append("")
        lines.append("### Judge 局限性说明")
        lines.append("")
        for item in limitations[:6]:
            lines.append(f"- {item}")

    lines.append("")
    return lines


def _agent_review_section(data: _ReportData) -> list[str]:
    # 优先从新版 agent_source_data_auditor 读取数据
    source_auditor_data = data.agent_source_data_auditor
    legacy_review_data = data.agent_review

    # 如果两者都没有，返回空
    if not source_auditor_data and not legacy_review_data:
        return []

    lines: list[str] = []
    lines.append("## Agent Review")
    lines.append("")

    # 优先使用新版 source_data_auditor 的数据
    if source_auditor_data:
        candidate_claims = (
            source_auditor_data.get("claims")
            or source_auditor_data.get("candidate_claims")
            or []
        )
        mapping_reviews = (
            source_auditor_data.get("claim_mappings")
            or source_auditor_data.get("claim_to_source_data")
            or []
        )
        finding_reviews = source_auditor_data.get("finding_reviews") or []
        manual_tasks = source_auditor_data.get("manual_review_tasks") or []
        status = source_auditor_data.get("status", "ok")
    elif legacy_review_data:
        candidate_claims = legacy_review_data.get("candidate_claims") or []
        mapping_reviews = legacy_review_data.get("claim_to_source_data") or []
        finding_reviews = legacy_review_data.get("finding_reviews") or []
        manual_tasks = legacy_review_data.get("manual_review_tasks") or []
        status = legacy_review_data.get("status", "ok")
    else:
        return []

    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                ["status", status],
                ["candidate_claims", fmt_int(len(candidate_claims))],
                ["claim_to_source_data_reviews", fmt_int(len(mapping_reviews))],
                ["finding_reviews", fmt_int(len(finding_reviews))],
                ["manual_review_tasks", fmt_int(len(manual_tasks))],
            ],
        )
    )
    if manual_tasks:
        lines.append("")
        lines.append("### Agent Manual Review Tasks")
        lines.append("")
        lines.append(
            markdown_table(
                ["Task", "Priority", "Question", "Evidence Refs"],
                agent_manual_review_rows(manual_tasks),
            )
        )
    if finding_reviews:
        lines.append("")
        lines.append("### Agent Finding Reviews")
        lines.append("")
        lines.append(
            markdown_table(
                ["Finding", "Assessment", "Residual Risk", "Benign Explanations"],
                agent_finding_review_rows(finding_reviews),
            )
        )

    # 展示 report_notes（优先新版）
    notes = []
    if source_auditor_data:
        notes = source_auditor_data.get("report_notes") or []
    elif legacy_review_data:
        notes = legacy_review_data.get("report_notes") or []

    if notes:
        lines.append("")
        lines.append("Agent report notes:")
        for item in notes[:8]:
            lines.append(f"- {item}")
    lines.append("")
    return lines


def _claim_mapping_section(data: _ReportData) -> list[str]:
    if not (data.static_bundle and (data.static_bundle.get("claim_mappings") or [])):
        return []
    bundle_claims = data.static_bundle.get("claims") or []
    bundle_mappings = data.static_bundle.get("claim_mappings") or []
    mapping_policy = (data.static_bundle.get("metadata") or {}).get(
        "claim_mapping_policy"
    ) or {}
    lines: list[str] = []
    lines.append("## Canonical Claim-to-source-data Mapping")
    lines.append("")
    lines.append(
        "- 该表优先展示 Agent refined mapping；确定性 Source Data mapping 保留为 provenance scaffolding。"
    )
    lines.append(
        f"- canonical_preference: `{mapping_policy.get('canonical_preference', 'agent_refined')}`; "
        f"fallback: `{mapping_policy.get('fallback', 'deterministic_scaffolding')}`。"
    )
    lines.append("")
    lines.append(
        markdown_table(
            [
                "Mapping",
                "Claim",
                "Claim Text",
                "Confidence",
                "Status",
                "Source Data Refs",
            ],
            canonical_claim_mapping_rows(bundle_claims, bundle_mappings),
        )
    )
    lines.append("")
    return lines


def _ledger_section(data: _ReportData) -> list[str]:
    if not data.ledger:
        return []
    stats = data.ledger.get("stats", {})
    lines: list[str] = []
    lines.append("## Evidence Ledger Summary")
    lines.append("")
    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                ["pages", fmt_int(stats.get("pages"))],
                ["markdown_lines", fmt_int(stats.get("markdown_lines"))],
                ["content_blocks", fmt_int(stats.get("content_blocks"))],
                ["tables", fmt_int(stats.get("tables"))],
                ["figures", fmt_int(stats.get("figures"))],
                ["images", fmt_int(stats.get("images"))],
                ["captions", fmt_int(stats.get("captions"))],
                ["cells", fmt_int(stats.get("cells"))],
                ["ledger_items", fmt_int(stats.get("ledger_items"))],
            ],
        )
    )
    warnings = data.ledger.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in warnings:
            lines.append(f"- `{warning.get('code')}`: {warning.get('message')}")
    lines.append("")
    return lines


def _numeric_section(data: _ReportData) -> list[str]:
    if not data.numeric:
        return []
    benford = data.numeric.get("benford", {})
    lines: list[str] = []
    lines.append("## Numeric Forensics Summary")
    lines.append("")
    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                ["all_number_count", fmt_int(data.numeric.get("all_number_count"))],
                ["effective_number_count", fmt_int(data.numeric.get("number_count"))],
                ["table_count", fmt_int(data.numeric.get("table_count"))],
                ["effective_scope", data.numeric.get("effective_scope", "-")],
                ["benford_applicability", benford.get("applicability", "-")],
                [
                    "benford_mad",
                    fmt_float(
                        benford.get("mad", benford.get("mean_absolute_deviation")),
                        4,
                    ),
                ],
            ],
        )
    )
    lines.append("")
    lines.append(
        "Interpretation: PDF numeric forensics is treated as audit leads, not as final evidence. OCR/table extraction artifacts must be excluded before escalation."
    )
    lines.append("")
    return lines


def _profile_section(data: _ReportData) -> list[str]:
    if not data.profile:
        return []
    summary = data.profile.get("summary", {})
    lines: list[str] = []
    lines.append("## Source Data Profile")
    lines.append("")
    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                ["workbook_count", fmt_int(summary.get("workbook_count"))],
                ["sheet_count", fmt_int(summary.get("sheet_count"))],
                ["cell_count", fmt_int(summary.get("cell_count"))],
                ["numeric_cell_count", fmt_int(summary.get("numeric_cell_count"))],
                ["formula_count", fmt_int(summary.get("formula_count"))],
                [
                    "terminal_0_or_5_rate",
                    fmt_float(summary.get("terminal_0_or_5_rate"), 3),
                ],
                [
                    "workbooks_with_errors",
                    ", ".join(summary.get("workbooks_with_errors") or []) or "-",
                ],
            ],
        )
    )
    lines.append("")
    return lines


def _findings_section(data: _ReportData) -> list[str]:
    if not data.findings:
        return []
    summary = data.findings.get("summary", {})
    priority = data.findings.get("priority_findings") or []
    lines: list[str] = []
    lines.append("## Source Data Findings")
    lines.append("")
    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                [
                    "duplicate_column_findings",
                    fmt_int(summary.get("duplicate_column_findings")),
                ],
                [
                    "fixed_relationship_findings",
                    fmt_int(summary.get("fixed_relationship_findings")),
                ],
                [
                    "formula_derived_columns",
                    fmt_int(summary.get("formula_derived_columns")),
                ],
                [
                    "claim_to_source_data_mappings",
                    fmt_int(summary.get("claim_to_source_data_mappings")),
                ],
                ["priority_findings", fmt_int(summary.get("priority_findings"))],
                ["errors", fmt_int(summary.get("errors"))],
            ],
        )
    )
    lines.append("")
    if priority:
        lines.append("### Priority Findings")
        lines.append("")
        lines.append(
            markdown_table(
                ["ID", "Risk", "Workbook", "Sheet", "Columns", "Relation", "Support"],
                [priority_row(item) for item in priority],
            )
        )
        lines.append("")
        lines.append("These are manual-review candidates, not misconduct conclusions.")
        lines.append("")
    mappings = data.findings.get("claim_to_source_data") or []
    if mappings:
        lines.append("### Deterministic Claim-to-source-data Scaffolding")
        lines.append("")
        lines.append(
            "该表由脚本按 Source Data sheet 名称和论文 figure 引用生成，用作 Agent 复核的候选脚手架，不作为最终主视图。"
        )
        lines.append("")
        lines.append(
            markdown_table(
                [
                    "Mapping",
                    "Figure",
                    "Workbook",
                    "Sheet",
                    "Priority",
                    "Linked Findings",
                    "Candidate Claim",
                ],
                claim_mapping_rows(mappings),
            )
        )
        lines.append("")
    return lines


def _pair_forensics_section(data: _ReportData) -> list[str]:
    if not data.pair_forensics:
        return []
    summary = data.pair_forensics.get("summary", {})
    priority = data.pair_forensics.get("priority_findings") or []
    clusters = data.pair_forensics.get("finding_clusters") or []
    review_tasks = data.pair_forensics.get("review_tasks") or []
    lines: list[str] = []
    lines.append("## Source Data Pair / Row-Offset Forensics")
    lines.append("")
    lines.append(
        "该工具检查通用的 paired cohort、前后半区、固定行偏移、低宽度行重复和比例复用模式；它不依赖特定论文或 PubPeer 评论。"
    )
    lines.append("")
    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                ["findings", fmt_int(summary.get("findings"))],
                ["priority_findings", fmt_int(summary.get("priority_findings"))],
                ["finding_clusters", fmt_int(summary.get("finding_clusters"))],
                ["review_tasks", fmt_int(summary.get("review_tasks"))],
                [
                    "row_offset_scalar_findings",
                    fmt_int(summary.get("row_offset_scalar_findings")),
                ],
                [
                    "paired_ratio_reuse_findings",
                    fmt_int(summary.get("paired_ratio_reuse_findings")),
                ],
                [
                    "duplicate_row_vector_findings",
                    fmt_int(summary.get("duplicate_row_vector_findings")),
                ],
                [
                    "rounding_bias_findings",
                    fmt_int(summary.get("rounding_bias_findings")),
                ],
                ["errors", fmt_int(summary.get("errors"))],
            ],
        )
    )
    lines.append("")
    if review_tasks:
        lines.append("### Pair Forensics Review Tasks")
        lines.append("")
        lines.append(
            markdown_table(
                [
                    "Task",
                    "Priority",
                    "Primary Cluster",
                    "Category",
                    "Workbook",
                    "Sheet",
                    "Clusters",
                    "Raw Count",
                    "Question",
                ],
                pair_forensics_review_task_rows(review_tasks),
            )
        )
        lines.append("")
    if clusters:
        lines.append("### Pair Forensics Finding Clusters")
        lines.append("")
        lines.append(
            markdown_table(
                [
                    "Cluster",
                    "Risk",
                    "Category",
                    "Workbook",
                    "Sheet",
                    "Signature",
                    "Raw Count",
                    "Representative Findings",
                ],
                pair_forensics_cluster_rows(clusters),
            )
        )
        lines.append("")
    if priority:
        lines.append("### Representative Raw Pair Findings")
        lines.append("")
        lines.append(
            markdown_table(
                [
                    "ID",
                    "Risk",
                    "Category",
                    "Workbook",
                    "Sheet",
                    "Offset",
                    "Columns",
                    "Support",
                ],
                pair_forensics_rows(priority, limit=8),
            )
        )
        lines.append("")
        lines.append(
            "上表仅展示代表性 raw findings；人工复核应优先从 review tasks 和 finding clusters 开始。"
        )
        lines.append("")
    return lines


def _duplicates_section(data: _ReportData) -> list[str]:
    if not data.duplicates:
        return []
    lines: list[str] = []
    lines.append("## Image Duplicate Check")
    lines.append("")
    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                ["image_count", fmt_int(data.duplicates.get("image_count"))],
                [
                    "duplicate_group_count",
                    fmt_int(data.duplicates.get("duplicate_group_count")),
                ],
                [
                    "duplicate_image_count",
                    fmt_int(data.duplicates.get("duplicate_image_count")),
                ],
            ],
        )
    )
    lines.append("")
    lines.append(
        "Byte-identical duplicate checking cannot detect crops, rescaling, rotations, contrast changes, or local reuse."
    )
    lines.append("")
    return lines


def _similarity_section(data: _ReportData) -> list[str]:
    if not data.similarity:
        return []
    lines: list[str] = []
    lines.append("## Image Similarity Candidates")
    lines.append("")
    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                ["status", data.similarity.get("status", "-")],
                ["method", data.similarity.get("method", "-")],
                ["image_count", fmt_int(data.similarity.get("image_count"))],
                ["candidate_count", fmt_int(data.similarity.get("candidate_count"))],
            ],
        )
    )
    if data.similarity.get("status") == "not_available":
        lines.append("")
        lines.append(
            "Near-duplicate image triage was not available in this environment; deterministic exact duplicate checking still ran."
        )
    lines.append("")
    return lines


def _bundle_section(data: _ReportData) -> list[str]:
    if not data.static_bundle:
        return []
    traces = data.static_bundle.get("agent_traces") or []
    evidence_items = data.static_bundle.get("evidence_items") or []
    lines: list[str] = []
    lines.append("## Static Audit Bundle")
    lines.append("")
    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                ["protocol_version", data.static_bundle.get("protocol_version", "-")],
                ["evidence_items", fmt_int(len(evidence_items))],
                ["claims", fmt_int(len(data.static_bundle.get("claims") or []))],
                ["findings", fmt_int(len(data.static_bundle.get("findings") or []))],
                [
                    "claim_mappings",
                    fmt_int(len(data.static_bundle.get("claim_mappings") or [])),
                ],
                ["agent_traces", fmt_int(len(traces))],
                [
                    "execution_status",
                    (data.static_bundle.get("execution_status") or {}).get(
                        "status", "-"
                    ),
                ],
            ],
        )
    )
    if traces:
        lines.append("")
        lines.append("### Role Trace Summary")
        lines.append("")
        lines.append(
            markdown_table(
                ["Role", "Status", "Output", "Detail"],
                [
                    [
                        trace.get("role_id", "-"),
                        trace.get("status", "-"),
                        trace.get("output_path", "-"),
                        str(trace.get("detail", "-"))[:160],
                    ]
                    for trace in traces
                ],
            )
        )
    lines.append("")
    return lines


def _vlm_section(data: _ReportData) -> list[str]:
    if not data.vlm:
        return []
    lines: list[str] = []
    lines.append("## VLM Triage")
    lines.append("")
    lines.append("- Existing VLM triage artifact detected: `vlm_triage_selected.json`.")
    lines.append(
        "- Current orchestrator does not run batch VLM review yet; existing VLM output is treated as non-primary triage evidence."
    )
    lines.append("")
    return lines


def _limitations_section(data: _ReportData) -> list[str]:
    lines: list[str] = []
    lines.append("## Limitations")
    lines.append("")
    limitations = [
        "This run does not make a final research-integrity judgment.",
        "Claim-to-source-data mapping is currently sheet/figure level unless manually refined to panel/column-block level.",
        "VLM image review is not yet a complete batch pipeline.",
        "Code-execution verification is not connected for this paper directory unless a code repo and manifest are supplied.",
    ]
    if data.mineru_manifest and not any(data.workdir.glob("*_middle.json")):
        limitations.append(
            "MinerU middle JSON may be missing; layout/bbox confidence should be lowered."
        )
    if data.agent_mode in {"plan", "full"} and not data.agent_plan:
        limitations.append(
            "opencode Agent plan artifact is missing; deterministic defaults were used."
        )
    if data.material_plan and data.material_plan.get("status") in {
        "fallback",
        "deterministic_fallback",
    }:
        limitations.append(
            f"Material optional-lane planning used fallback mode: {data.material_plan.get('detail', '-')}"
        )
    if data.material_plan and data.material_plan.get("unsupported_materials"):
        limitations.append(
            "Some submitted materials were inventoried but not executable in this MVP optional-lane set."
        )
    if data.agent_mode in {"review", "full"} and not data.agent_review:
        limitations.append(
            "opencode Agent review artifact is missing; claim/finding interpretation is deterministic-only."
        )
    if data.agent_plan and data.agent_plan.get("status") == "failed":
        limitations.append(
            f"opencode Agent plan failed: {data.agent_plan.get('detail', '-')}"
        )
    if data.agent_review and data.agent_review.get("status") == "failed":
        limitations.append(
            f"opencode Agent review failed: {data.agent_review.get('detail', '-')}"
        )
    for item in (data.agent_review or {}).get("limitations", [])[:6]:
        limitations.append(f"Agent review limitation: {item}")
    for item in limitations:
        lines.append(f"- {item}")
    lines.append("")
    return lines


def generate_report(
    *,
    paper_dir: Path,
    paper_pdf: Path,
    source_data_dir: Path | None,
    workdir: Path,
    case_id: str,
    agent_mode: str,
    steps: list[StepResult],
) -> Path:
    data = _ReportData(
        workdir=workdir,
        case_id=case_id,
        paper_dir=paper_dir,
        paper_pdf=paper_pdf,
        source_data_dir=source_data_dir,
        agent_mode=agent_mode,
        steps=steps,
        mineru_manifest=read_json(
            resolve_artifact_path(workdir, "mineru_manifest.json")
        ),
        material_inventory=read_json(
            resolve_artifact_path(workdir, "material_inventory.json")
        ),
        material_plan=read_json(
            resolve_artifact_path(workdir, "agent_material_plan.json")
        ),
        ledger=read_json(resolve_artifact_path(workdir, "evidence_ledger.json")),
        numeric=read_json(resolve_artifact_path(workdir, "numeric_forensics.json")),
        profile=read_json(resolve_artifact_path(workdir, "source_data_profile.json")),
        findings=read_json(resolve_artifact_path(workdir, "source_data_findings.json")),
        pair_forensics=read_json(
            resolve_artifact_path(workdir, "source_data_pair_forensics.json")
        ),
        duplicates=read_json(
            resolve_artifact_path(workdir, "exact_image_duplicates.json")
        ),
        similarity=read_json(
            resolve_artifact_path(workdir, "image_similarity_candidates.json")
        ),
        investigation_records=read_investigation_records(workdir),
        static_bundle=read_json(
            resolve_artifact_path(workdir, "static_audit_bundle.json")
        ),
        vlm=read_json(resolve_artifact_path(workdir, "vlm_triage_selected.json")),
        agent_plan=read_json(resolve_artifact_path(workdir, "agent_audit_plan.json"))
        if agent_mode in {"plan", "full"}
        else None,
        agent_review=read_json(resolve_artifact_path(workdir, "agent_review.json"))
        if agent_mode in {"review", "full"}
        else None,
        agent_judge=read_json(resolve_artifact_path(workdir, "agent_judge.json"))
        if agent_mode in {"review", "full"}
        else None,
        agent_source_data_auditor=read_json(
            resolve_artifact_path(workdir, "agent_source_data_auditor.json")
        )
        if agent_mode in {"review", "full"}
        else None,
    )
    lines: list[str] = []
    for section_fn in [
        _header_section,
        _scope_section,
        _pipeline_section,
        _artifact_manifest_section,
        _material_section,
        _investigation_section,
        _agent_plan_section,
        _judge_section,
        _agent_review_section,
        _claim_mapping_section,
        _ledger_section,
        _numeric_section,
        _profile_section,
        _findings_section,
        _pair_forensics_section,
        _duplicates_section,
        _similarity_section,
        _bundle_section,
        _vlm_section,
        _limitations_section,
    ]:
        lines.extend(section_fn(data))
    report_path = resolve_artifact_path(workdir, "final_audit_report.md")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _parse_sheet_figure_keys(sheet_name: str) -> list[tuple[str, str, str | None]]:
    """Extract (kind, figure_number, panel_letter) from a source data sheet name.

    Handles formats beyond what figure_keys_from_sheet_name covers, such as
    comma-separated panels ("fig.7j,k") and ranges ("fig.5 l-n").
    """
    text = re.sub(r"[\s ]+", " ", sheet_name).strip()
    text_lower = text.lower()
    is_extended = "extended data" in text_lower
    kind = "extended_data" if is_extended else "main_figure"
    if is_extended:
        m = re.search(r"extended\s+data\s+fig\.?\s*(\d+)([a-z]?)", text_lower)
    else:
        m = re.search(r"fig\.?\s*(\d+)([a-z]?)", text_lower)
    if not m:
        return []
    fig_num = m.group(1)
    first_panel = m.group(2) or None
    keys: list[tuple[str, str, str | None]] = []
    if first_panel:
        keys.append((kind, fig_num, first_panel))
    else:
        keys.append((kind, fig_num, None))
    rest = text_lower[m.end() :]
    for pm in re.finditer(r"[,]\s*([a-z])", rest):
        keys.append((kind, fig_num, pm.group(1)))
    for pm in re.finditer(r"\band\s+([a-z])", rest):
        keys.append((kind, fig_num, pm.group(1)))
    for pm in re.finditer(r"([a-z])\s*[-–]\s*([a-z])", rest):
        s, e = ord(pm.group(1)), ord(pm.group(2))
        if 0 < e - s < 10:
            for i in range(s, e + 1):
                keys.append((kind, fig_num, chr(i)))
    return keys


def _panels_from_caption_body(body: str) -> set[str]:
    """Extract single-letter panel references from a figure caption body.

    Matches the standard format "a, description. b, description." where panel
    labels appear after sentence-ending punctuation followed by whitespace.
    """
    panels: set[str] = set()
    for m in re.finditer(r"(?<=[\.\;]\s)([a-z](?:\s*,\s*[a-z])*)\s*,", body):
        for letter in re.findall(r"[a-z]", m.group(1)):
            panels.add(letter)
    for m in re.finditer(r"(?<=[\.\;]\s)([a-z])\s*[-–]\s*([a-z])\s*,", body):
        s, e = ord(m.group(1)), ord(m.group(2))
        if 0 < e - s < 10:
            for i in range(s, e + 1):
                panels.add(chr(i))
    return panels


def _find_missing_source_data_findings(workdir: Path) -> list[Finding]:
    """Generate completeness findings for figure panels without source data sheets."""
    profile = read_json(resolve_artifact_path(workdir, "source_data_profile.json"))
    if not profile or not profile.get("workbooks"):
        return []

    # Collect figure keys covered by source data sheets.
    covered: set[tuple[str, str, str | None]] = set()
    for wb in profile["workbooks"]:
        for sheet in wb.get("sheets", []):
            for key in _parse_sheet_figure_keys(sheet.get("name", "")):
                covered.add(key)

    # Collect figure panel references from the evidence ledger.
    ledger = read_json(resolve_artifact_path(workdir, "evidence_ledger.json"))
    if not ledger:
        return []
    captions = ledger.get("captions", [])

    # Map: (kind, fig_num) -> set of panel letters
    paper_panels: dict[tuple[str, str], set[str]] = {}

    for cap in captions:
        raw = cap.get("raw_label", "") or ""
        text = cap.get("text", "") or ""

        # Main figure caption: raw_label = "Fig. N" (no panel letter), text has "|"
        main_fig_match = re.match(r"(?:Extended Data )?Fig\.\s*(\d+)$", raw)
        if main_fig_match and "|" in text and "See next page" not in text:
            fig_num = main_fig_match.group(1)
            is_ext = "Extended Data" in raw
            kind = "extended_data" if is_ext else "main_figure"
            body = text.split("|", 1)[-1].strip()
            panels = _panels_from_caption_body(body)
            paper_panels.setdefault((kind, fig_num), set()).update(panels)

        # Body text reference: raw_label = "Fig. 7d" (with panel letter)
        panel_ref_match = re.match(r"(Extended Data )?Fig\.\s*(\d+)([a-z])$", raw)
        if panel_ref_match:
            is_ext = bool(panel_ref_match.group(1))
            kind = "extended_data" if is_ext else "main_figure"
            fig_num = panel_ref_match.group(2)
            panel = panel_ref_match.group(3)
            paper_panels.setdefault((kind, fig_num), set()).add(panel)

    # Also scan the full paper markdown for "Fig. Xy" references.
    # This catches panels mentioned in body text that are not in ledger captions.
    full_md_path = resolve_artifact_path(workdir, "full.md")
    if full_md_path.exists():
        try:
            full_text = full_md_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            full_text = ""
        for m in re.finditer(r"(?:Extended\s+Data\s+)?Fig\.\s*(\d+)([a-z])", full_text):
            prefix = full_text[max(0, m.start() - 20) : m.start()]
            is_ext = "Extended Data" in prefix or "extended data" in prefix.lower()
            kind = "extended_data" if is_ext else "main_figure"
            fig_num = m.group(1)
            panel = m.group(2)
            paper_panels.setdefault((kind, fig_num), set()).add(panel)

    # Generate findings for paper panels not covered by source data.
    raw_findings: list[Finding] = []
    counter = 1
    for (kind, fig_num), panels in sorted(paper_panels.items()):
        for panel in sorted(panels):
            if (kind, fig_num, panel) not in covered:
                if kind == "extended_data":
                    fig_id = f"Extended Data Fig. {fig_num}{panel}"
                else:
                    fig_id = f"Fig. {fig_num}{panel}"
                raw_findings.append(
                    Finding(
                        finding_id=f"COMP-SRC-{counter:03d}",
                        category="source_data_missing",
                        risk_level="medium",
                        summary=f"Figure {fig_id} has no corresponding source data sheet",
                        issue_category="completeness",
                        metadata={
                            "figure_id": fig_id,
                            "kind": kind,
                            "figure_number": fig_num,
                            "panel": panel,
                            "covered_sheets": sorted(
                                f"{k[1]}.{k[2]}" if k[2] else k[1]
                                for k in covered
                                if k[0] == kind and k[1] == fig_num and k[2] is not None
                            ),
                        },
                    )
                )
                counter += 1

    # Group by figure (kind + fig_num) and create summary findings.
    findings: list[Finding] = []
    grouped: dict[tuple[str, str], list[Finding]] = {}
    for f in raw_findings:
        key = (f.metadata["kind"], f.metadata["figure_number"])
        grouped.setdefault(key, []).append(f)

    summary_idx = 1
    for (kind, fig_num), group in sorted(grouped.items()):
        panels = [f.metadata["panel"] for f in group]
        if kind == "extended_data":
            fig_label = f"Extended Data Fig. {fig_num}"
        else:
            fig_label = f"Fig. {fig_num}"
        summary_id = f"SDM-SUMMARY-{summary_idx:03d}"
        findings.append(
            Finding(
                finding_id=summary_id,
                category="source_data_missing",
                risk_level="low",
                summary=f"Figure {fig_label} 缺失 {len(panels)} 个 panel 的 source data: {', '.join(panels)}",
                issue_category="completeness",
                metadata={
                    "figure_label": fig_label,
                    "kind": kind,
                    "figure_number": fig_num,
                    "missing_panels": panels,
                    "original_finding_ids": [f.finding_id for f in group],
                },
            )
        )
        # Mark original findings as suppressed.
        for f in group:
            f.metadata["suppressed_by"] = summary_id
        findings.extend(group)
        summary_idx += 1

    return findings


def build_static_audit_bundle(
    *,
    paper_dir: Path,
    paper_pdf: Path,
    source_data_dir: Path | None,
    workdir: Path,
    case_id: str,
    steps: list[StepResult],
    agent_manifest: dict[str, Any],
) -> StaticAuditBundle:
    evidence_items = collect_evidence_items(workdir)
    claims, claim_mappings, findings = collect_claims_and_findings(
        workdir, evidence_items
    )
    from engine.static_audit.investigation_dispatch import collect_agent_traces

    traces = collect_agent_traces(workdir, agent_manifest)

    material_plan = (
        read_json(resolve_artifact_path(workdir, "agent_material_plan.json")) or {}
    )
    if material_plan.get("missing_materials"):
        findings.append(
            Finding(
                finding_id="COMP-MAT-001",
                category="material_missing",
                risk_level="medium",
                summary=f"提交材料缺少: {', '.join(material_plan['missing_materials'])}",
                issue_category="completeness",
                metadata={
                    "missing_items": material_plan["missing_materials"],
                    "material_plan_status": material_plan.get("status"),
                },
            )
        )

    execution_status = ExecutionStatus(status="not_provided")
    if execution_status.status in {"not_provided", "not_run", "missing_material"}:
        findings.append(
            Finding(
                finding_id="COMP-EXEC-001",
                category="execution_status_not_available",
                risk_level="low",
                summary=f"代码执行审查未连接: execution_status={execution_status.status}",
                issue_category="completeness",
                metadata={
                    "execution_status": execution_status.status,
                    "runtime_backend": execution_status.runtime_backend,
                },
            )
        )

    findings.extend(_find_missing_source_data_findings(workdir))

    return StaticAuditBundle(
        case_id=case_id,
        inputs={
            "paper_dir": str(paper_dir),
            "paper_pdf": str(paper_pdf),
            "source_data_dir": str(source_data_dir) if source_data_dir else None,
            "material_inventory": str(
                resolve_artifact_path(workdir, "material_inventory.json")
            ),
            "agent_material_plan": str(
                resolve_artifact_path(workdir, "agent_material_plan.json")
            ),
            "optional_lanes": agent_manifest.get("optional_lanes", []),
            "workdir": str(workdir),
        },
        tool_runs=[
            ToolRun(
                tool_id=STEP_TOOL_IDS.get(step.key, step.key),
                step_key=step.key,
                status=step.status,  # type: ignore[arg-type]
                title=step.title,
                command=step.command,
                outputs=[],
                detail=step.detail,
            )
            for step in steps
        ],
        evidence_items=evidence_items,
        claims=claims,
        findings=findings,
        claim_mappings=claim_mappings,
        agent_traces=traces,
        limitations=[
            "Static audit bundle v1 is generated from deterministic artifacts and current Agent review output.",
            "Code execution audit is not connected in this static-audit run.",
        ],
        execution_status=execution_status,
        metadata={
            "agent": agent_manifest,
            "investigation_records": read_investigation_records(workdir),
            "material_plan": read_json(
                resolve_artifact_path(workdir, "agent_material_plan.json")
            )
            or {},
            "claim_mapping_policy": {
                "canonical_preference": "agent_refined",
                "fallback": "deterministic_scaffolding",
                "deterministic_scaffolding_artifact": str(
                    resolve_artifact_path(workdir, "source_data_findings.json")
                ),
                "agent_claim_artifact": str(
                    resolve_artifact_path(workdir, "agent_claim_extractor.json")
                ),
                "agent_source_data_artifact": str(
                    resolve_artifact_path(workdir, "agent_source_data_auditor.json")
                ),
            },
            "deterministic_claim_mappings": (
                (
                    read_json(
                        resolve_artifact_path(workdir, "source_data_findings.json")
                    )
                    or {}
                ).get("claim_to_source_data")
                or []
            ),
        },
    )


def collect_evidence_items(workdir: Path) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for name, kind in [
        ("full.md", "output_artifact"),
        ("material_inventory.json", "output_artifact"),
        ("agent_material_plan.json", "output_artifact"),
        ("evidence_ledger.json", "output_artifact"),
        ("numeric_forensics.json", "output_artifact"),
        ("paperfraud_rule_matches.json", "output_artifact"),
        ("source_data_profile.json", "output_artifact"),
        ("source_data_findings.json", "output_artifact"),
        ("source_data_pair_forensics.json", "output_artifact"),
        ("exact_image_duplicates.json", "output_artifact"),
        ("image_similarity_candidates.json", "output_artifact"),
        ("visual_evidence.json", "output_artifact"),
        ("panel_evidence.json", "output_artifact"),
        ("visual_copy_move.json", "output_artifact"),
        ("image_relationships.json", "output_artifact"),
        ("visual_findings.json", "output_artifact"),
        ("forged_region_evidence.json", "output_artifact"),
        ("investigation_rounds.jsonl", "output_artifact"),
    ]:
        path = resolve_artifact_path(workdir, name)
        if path.exists():
            items.append(
                EvidenceItem(
                    evidence_id=f"EV-ART-{len(items) + 1:04d}",
                    kind=kind,  # type: ignore[arg-type]
                    source_path=str(path),
                    summary=f"Audit artifact: {name}",
                    metadata={"bytes": path.stat().st_size, "artifact_name": name},
                )
            )

    visual_evidence = (
        read_json(resolve_artifact_path(workdir, "visual_evidence.json")) or {}
    )
    for figure in visual_evidence.get("figures") or []:
        if not isinstance(figure, dict):
            continue
        figure_id = str(figure.get("figure_id") or "")
        if not figure_id:
            continue
        items.append(
            EvidenceItem(
                evidence_id=f"EV-FIG-{len(items) + 1:04d}",
                kind="figure",
                source_path=str(figure.get("source_image_path") or ""),
                locator={
                    "figure_id": figure_id,
                    "label": figure.get("label"),
                    "page_number": figure.get("page_number"),
                    "bbox": figure.get("bbox"),
                },
                summary=f"Canonical figure evidence {figure_id}",
                metadata={"figure_id": figure_id, "source": "visual_evidence.json"},
            )
        )

    panel_evidence = (
        read_json(resolve_artifact_path(workdir, "panel_evidence.json")) or {}
    )
    for panel in panel_evidence.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        panel_id = str(panel.get("panel_id") or "")
        if not panel_id:
            continue
        items.append(
            EvidenceItem(
                evidence_id=f"EV-PANEL-{len(items) + 1:04d}",
                kind="panel",
                source_path=str(panel.get("crop_path") or ""),
                locator={
                    "panel_id": panel_id,
                    "parent_figure_id": panel.get("parent_figure_id"),
                    "label": panel.get("label"),
                    "bbox": panel.get("bbox"),
                },
                summary=f"Canonical panel evidence {panel_id}",
                metadata={
                    "panel_id": panel_id,
                    "parent_figure_id": panel.get("parent_figure_id"),
                    "source": "panel_evidence.json",
                },
            )
        )

    source_findings = (
        read_json(resolve_artifact_path(workdir, "source_data_findings.json")) or {}
    )
    for finding in (source_findings.get("priority_findings") or [])[:100]:
        items.append(
            EvidenceItem(
                evidence_id=f"EV-SD-{len(items) + 1:04d}",
                kind="sheet",
                source_path=str(finding.get("workbook", "")),
                locator={
                    "sheet": finding.get("sheet"),
                    "columns": finding.get("column_pair"),
                    "support_rows": finding.get("support_rows")
                    or finding.get("equal_rows"),
                    "overlap_rows": finding.get("overlap_rows"),
                },
                summary=f"Source Data priority finding {finding.get('finding_id')}",
                metadata={"finding_id": finding.get("finding_id")},
            )
        )
    pair_forensics = (
        read_json(resolve_artifact_path(workdir, "source_data_pair_forensics.json"))
        or {}
    )
    for finding in (pair_forensics.get("priority_findings") or [])[:100]:
        items.append(
            EvidenceItem(
                evidence_id=f"EV-PF-{len(items) + 1:04d}",
                kind="sheet",
                source_path=str(finding.get("workbook", "")),
                locator={
                    "sheet": finding.get("sheet"),
                    "row_offset": finding.get("row_offset"),
                    "columns": finding.get("columns")
                    or finding.get("column_pair")
                    or finding.get("column"),
                    "support_rows": finding.get("support_rows")
                    or finding.get("matched_pairs")
                    or finding.get("duplicate_row_count"),
                    "overlap_rows": finding.get("overlap_rows")
                    or finding.get("overlap_pairs"),
                },
                summary=f"Source Data pair-forensics finding {finding.get('finding_id')}",
                metadata={
                    "finding_id": finding.get("finding_id"),
                    "source": "source_data_pair_forensics",
                },
            )
        )
    return items


def _load_claim_artifacts(workdir: Path) -> dict[str, Any]:
    """Read all JSON artifacts needed for claim and finding collection."""
    return {
        "source_findings": read_json(
            resolve_artifact_path(workdir, "source_data_findings.json")
        )
        or {},
        "pair_forensics": read_json(
            resolve_artifact_path(workdir, "source_data_pair_forensics.json")
        )
        or {},
        "agent_claims": read_json(
            resolve_artifact_path(workdir, "agent_claim_extractor.json")
        )
        or {},
        "agent_source": read_json(
            resolve_artifact_path(workdir, "agent_source_data_auditor.json")
        )
        or {},
        "paperfraud_matches": read_json(
            resolve_artifact_path(workdir, "paperfraud_rule_matches.json")
        )
        or {},
        "visual_findings": read_json(
            resolve_artifact_path(workdir, "visual_findings.json")
        )
        or {},
    }


def _build_evidence_indices(
    evidence_items: list[EvidenceItem],
) -> tuple[dict[Any, str], dict[Any, str], dict[Any, str]]:
    """Build evidence lookup maps by finding_id, panel_id, and artifact_name."""
    evidence_by_finding = {
        item.metadata.get("finding_id"): item.evidence_id
        for item in evidence_items
        if item.metadata.get("finding_id")
    }
    evidence_by_panel = {
        item.metadata.get("panel_id"): item.evidence_id
        for item in evidence_items
        if item.metadata.get("panel_id")
    }
    evidence_by_artifact = {
        item.metadata.get("artifact_name"): item.evidence_id
        for item in evidence_items
        if item.metadata.get("artifact_name")
    }
    return evidence_by_finding, evidence_by_panel, evidence_by_artifact


def _collect_core_claims_and_mappings(
    artifacts: dict[str, Any],
    evidence_by_finding: dict[Any, str],
) -> tuple[list[Claim], list[ClaimMapping]]:
    """Merge agent-refined and deterministic claim mappings."""
    source_findings = artifacts["source_findings"]
    agent_claims = artifacts["agent_claims"]
    agent_source = artifacts["agent_source"]
    deterministic_mappings = source_findings.get("claim_to_source_data") or []

    claims, mappings = collect_agent_refined_claim_mappings(
        agent_claims=agent_claims,
        agent_source=agent_source,
        deterministic_mappings=deterministic_mappings,
    )
    if not claims and not mappings:
        return collect_deterministic_claim_mappings(
            source_findings=source_findings,
            evidence_by_finding=evidence_by_finding,
        )

    # Merge: supplement agent-refined results with any deterministic
    # mappings not already covered.
    extra_claims, extra_mappings = _merge_deterministic_mappings(
        agent_claims=claims,
        agent_mappings=mappings,
        source_findings=source_findings,
        evidence_by_finding=evidence_by_finding,
    )
    claims.extend(extra_claims)
    mappings.extend(extra_mappings)
    return claims, mappings


def _collect_paperfraud_findings(
    artifacts: dict[str, Any],
    evidence_by_finding: dict[Any, str],
) -> list[Finding]:
    """Convert PaperFraud rule matches to canonical findings."""
    return paperfraud_findings_from_matches(artifacts["paperfraud_matches"])


def _collect_source_data_findings(
    artifacts: dict[str, Any],
    evidence_by_finding: dict[Any, str],
) -> list[Finding]:
    """Build findings from source_data priority_findings."""
    source_findings = artifacts["source_findings"]
    findings: list[Finding] = []
    for item in source_findings.get("priority_findings") or []:
        finding_id = str(item.get("finding_id"))
        findings.append(
            Finding(
                finding_id=finding_id,
                category=str(item.get("category", "")),
                risk_level=str(item.get("risk_level", "medium")),  # type: ignore[arg-type]
                summary=f"{item.get('category')} in {item.get('workbook')} / {item.get('sheet')}",
                evidence_refs=[evidence_by_finding[finding_id]]
                if finding_id in evidence_by_finding
                else [],
                benign_explanations=[
                    str(value) for value in (item.get("benign_explanations") or [])
                ],
                pressure_test_result=str(item.get("pressure_test_result", "")),
                manual_review_note=str(item.get("manual_review_note", "")),
                metadata=item,
            )
        )
    return findings


def _collect_pair_forensics_findings(
    artifacts: dict[str, Any],
    evidence_by_finding: dict[Any, str],
) -> list[Finding]:
    """Build findings from pair_forensics priority_findings."""
    pair_forensics = artifacts["pair_forensics"]
    findings: list[Finding] = []
    for item in pair_forensics.get("priority_findings") or []:
        finding_id = str(item.get("finding_id"))
        evidence_id = evidence_by_finding.get(finding_id)
        findings.append(
            Finding(
                finding_id=finding_id,
                category=str(item.get("category", "")),
                risk_level=str(item.get("risk_level", "medium")),  # type: ignore[arg-type]
                summary=(
                    f"{item.get('category')} in {item.get('workbook')} / {item.get('sheet')} "
                    f"offset={item.get('row_offset', '-')}"
                ),
                evidence_refs=[evidence_id] if evidence_id else [],
                benign_explanations=[
                    str(value) for value in (item.get("benign_explanations") or [])
                ],
                pressure_test_result=str(item.get("pressure_test_result", "")),
                manual_review_note="Pair/row-offset Source Data pattern requires sample-independence review.",
                metadata={**item, "source_artifact": "source_data_pair_forensics.json"},
            )
        )
    return findings


def _collect_visual_findings(
    artifacts: dict[str, Any],
    evidence_by_panel: dict[Any, str],
    evidence_by_artifact: dict[Any, str],
) -> list[Finding]:
    """Build findings from visual_findings artifact."""
    visual_findings = artifacts["visual_findings"]
    findings: list[Finding] = []
    for item in visual_findings.get("findings") or []:
        if not isinstance(item, dict):
            continue
        finding_id = str(item.get("finding_id") or "")
        if not finding_id:
            continue
        summary = str(item.get("summary") or "Visual finding requires manual review.")
        if check_language_compliance(summary):
            summary = "Visual finding summary was hidden because it contained report-forbidden wording; inspect source artifacts manually."
        evidence_refs = [
            evidence_by_panel[panel_id]
            for panel_id in [item.get("source_panel_id"), item.get("target_panel_id")]
            if panel_id in evidence_by_panel
        ]
        category = str(item.get("category") or "visual_finding")
        if category == "forged_region_suspicious":
            tru_for_artifact = evidence_by_artifact.get("forged_region_evidence.json")
            if tru_for_artifact:
                evidence_refs.append(tru_for_artifact)
        else:
            relationship_artifact = evidence_by_artifact.get("image_relationships.json")
            if relationship_artifact:
                evidence_refs.append(relationship_artifact)
        questions = [
            str(value)
            for value in (item.get("manual_review_questions") or [])
            if not check_language_compliance(str(value))
        ]
        findings.append(
            Finding(
                finding_id=finding_id,
                category=category,
                risk_level=str(item.get("risk_level") or "medium"),  # type: ignore[arg-type]
                summary=summary,
                issue_category="consistency",
                evidence_refs=dedupe(evidence_refs),
                benign_explanations=[
                    str(value)
                    for value in (item.get("benign_explanations") or [])
                    if not check_language_compliance(str(value))
                ],
                manual_review_note=questions[0]
                if questions
                else "Visual finding requires manual review against the original figure and raw image.",
                metadata={**item, "source_artifact": "visual_findings.json"},
            )
        )
    return findings


def _deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    """Remove duplicate findings by finding_id, keeping first occurrence."""
    seen: set[str] = set()
    unique: list[Finding] = []
    for finding in findings:
        if finding.finding_id not in seen:
            seen.add(finding.finding_id)
            unique.append(finding)
    return unique


def _group_similar_findings(findings: list[Finding]) -> list[Finding]:
    """Group similar findings into summary findings to reduce noise.

    Groups paired_ratio_reuse by workbook+sheet and copy_move by figure pair.
    Creates summary findings and marks original findings as suppressed.
    """
    # Group paired_ratio_reuse by workbook+sheet
    paired_groups: dict[tuple[str, str], list[Finding]] = {}
    for finding in findings:
        if finding.category == "long_format_paired_ratio_reuse":
            metadata = finding.metadata or {}
            key = (str(metadata.get("workbook") or ""), str(metadata.get("sheet") or ""))
            paired_groups.setdefault(key, []).append(finding)

    # Group copy_move by figure pair
    copy_move_groups: dict[tuple[str, str], list[Finding]] = {}
    for finding in findings:
        if finding.category in ("copy_move_single", "copy_move_cross"):
            metadata = finding.metadata or {}
            src = str(metadata.get("source_parent_figure_id") or metadata.get("source_panel_id") or "")
            tgt = str(metadata.get("target_parent_figure_id") or metadata.get("target_panel_id") or "")
            key = (src, tgt)
            copy_move_groups.setdefault(key, []).append(finding)

    # Create summary findings for paired_ratio_reuse groups
    for (workbook, sheet), group in paired_groups.items():
        if len(group) < 2:
            continue
        summary_id = f"GRP-PRR-{workbook}-{sheet}".replace(".", "_").replace(" ", "_")
        summary = Finding(
            finding_id=summary_id,
            category="long_format_paired_ratio_reuse",
            risk_level=group[0].risk_level,
            summary=f"Paired ratio reuse group: {len(group)} findings in {workbook}/{sheet}",
            issue_category=group[0].issue_category,
            evidence_refs=dedupe([ref for f in group for ref in f.evidence_refs]),
            benign_explanations=group[0].benign_explanations,
            manual_review_note=f"{len(group)} paired ratio reuse patterns detected in workbook '{workbook}', sheet '{sheet}'. Review column semantics and data generation process.",
            metadata={"group_type": "paired_ratio_reuse", "workbook": workbook, "sheet": sheet, "member_count": len(group), "member_ids": [f.finding_id for f in group]},
        )
        findings.append(summary)
        for f in group:
            f.suppressed_by = summary_id

    # Create summary findings for copy_move groups
    for (src, tgt), group in copy_move_groups.items():
        if len(group) < 2:
            continue
        summary_id = f"GRP-CM-{src}-{tgt}".replace(".", "_").replace(" ", "_")
        summary = Finding(
            finding_id=summary_id,
            category=group[0].category,
            risk_level=group[0].risk_level,
            summary=f"Copy-move group: {len(group)} findings for figure pair {src} -> {tgt}",
            issue_category=group[0].issue_category,
            evidence_refs=dedupe([ref for f in group for ref in f.evidence_refs]),
            benign_explanations=group[0].benign_explanations,
            manual_review_note=f"{len(group)} copy-move patterns detected between figures '{src}' and '{tgt}'. Review image processing pipeline and raw data.",
            metadata={"group_type": "copy_move", "source_figure": src, "target_figure": tgt, "member_count": len(group), "member_ids": [f.finding_id for f in group]},
        )
        findings.append(summary)
        for f in group:
            f.suppressed_by = summary_id

    return findings


def collect_claims_and_findings(
    workdir: Path,
    evidence_items: list[EvidenceItem],
) -> tuple[list[Claim], list[ClaimMapping], list[Finding]]:
    """Collect claims from multiple sources and build findings from all evidence types.

    Coordinates artifact loading, evidence indexing, claim/mapping collection,
    and finding construction from PaperFraud rules, source data, pair forensics,
    and visual findings.
    """
    artifacts = _load_claim_artifacts(workdir)
    evidence_by_finding, evidence_by_panel, evidence_by_artifact = (
        _build_evidence_indices(evidence_items)
    )
    claims, mappings = _collect_core_claims_and_mappings(artifacts, evidence_by_finding)

    findings: list[Finding] = []
    findings.extend(_collect_paperfraud_findings(artifacts, evidence_by_finding))
    findings.extend(_collect_source_data_findings(artifacts, evidence_by_finding))
    findings.extend(_collect_pair_forensics_findings(artifacts, evidence_by_finding))
    findings.extend(
        _collect_visual_findings(artifacts, evidence_by_panel, evidence_by_artifact)
    )
    findings = _deduplicate_findings(findings)
    findings = _group_similar_findings(findings)

    return claims, mappings, findings


def collect_agent_refined_claim_mappings(
    *,
    agent_claims: dict[str, Any],
    agent_source: dict[str, Any],
    deterministic_mappings: list[dict[str, Any]],
) -> tuple[list[Claim], list[ClaimMapping]]:
    claim_items = [
        item for item in (agent_claims.get("claims") or []) if isinstance(item, dict)
    ]
    source_items = [
        item
        for item in (agent_source.get("claim_to_source_data") or [])
        if isinstance(item, dict)
    ]
    if not claim_items and not source_items:
        return [], []

    deterministic_by_id = {
        str(item.get("mapping_id")): item
        for item in deterministic_mappings
        if isinstance(item, dict) and item.get("mapping_id")
    }

    claims: list[Claim] = []
    claims_by_id: dict[str, Claim] = {}
    for index, item in enumerate(claim_items[:200], start=1):
        claim_text = item.get("claim_text") or item.get("text")
        if not claim_text:
            continue
        claim_id = str(item.get("claim_id") or f"AC-{index:03d}")
        claim = Claim(
            claim_id=claim_id,
            text=str(claim_text),
            claim_type=str(item.get("claim_type", "figure_trace")),
            source=str(item.get("paper_location", "")),
            evidence_refs=[str(ref) for ref in (item.get("evidence_refs") or [])],
            status=normalize_claim_status(item.get("status")),
            metadata={
                "source_role": "claim_extractor",
                "canonical_source": "agent_refined",
                "agent_status": item.get("status"),
                "raw": item,
            },
        )
        claims.append(claim)
        claims_by_id[claim_id] = claim

    mappings: list[ClaimMapping] = []
    for index, item in enumerate(source_items[:200], start=1):
        claim_id = str(item.get("claim_id") or f"ACM-{index:03d}")
        if claim_id not in claims_by_id:
            claim = Claim(
                claim_id=claim_id,
                text="Agent SourceDataAuditor 生成了映射，但 ClaimExtractor 未提供对应 claim 文本。",
                claim_type="figure_trace",
                source="agent_source_data_auditor",
                evidence_refs=[
                    str(ref) for ref in (item.get("source_data_refs") or [])
                ],
                status="warning",
                metadata={
                    "source_role": "source_data_auditor",
                    "canonical_source": "agent_refined_placeholder",
                    "raw": item,
                },
            )
            claims.append(claim)
            claims_by_id[claim_id] = claim
        deterministic_mapping_id = item.get("mapping_id")
        deterministic_mapping = (
            deterministic_by_id.get(str(deterministic_mapping_id))
            if deterministic_mapping_id
            else None
        )
        mappings.append(
            ClaimMapping(
                mapping_id=str(item.get("mapping_id") or f"ACM-{index:03d}"),
                claim_id=claim_id,
                evidence_refs=[
                    str(ref) for ref in (item.get("source_data_refs") or [])
                ],
                confidence=str(item.get("confidence", "medium")),
                status="agent_refined_mapping",
                rationale="SourceDataAuditor refined deterministic Source Data scaffolding into a review-oriented claim mapping.",
                metadata={
                    "source_role": "source_data_auditor",
                    "canonical_source": "agent_refined",
                    "needs_human_review": bool(item.get("needs_human_review", True)),
                    "source_data_refs": [
                        str(ref) for ref in (item.get("source_data_refs") or [])
                    ],
                    "deterministic_mapping": deterministic_mapping,
                    "raw": item,
                },
            )
        )
    return claims, mappings


def normalize_claim_status(value: Any) -> Status:
    allowed = {
        "pending",
        "ran",
        "reused",
        "skipped",
        "warning",
        "failed",
        "not_run",
        "not_provided",
        "missing_material",
    }
    status = str(value or "pending")
    return status if status in allowed else "pending"  # type: ignore[return-value]


def collect_deterministic_claim_mappings(
    *,
    source_findings: dict[str, Any],
    evidence_by_finding: dict[Any, str],
) -> tuple[list[Claim], list[ClaimMapping]]:
    claims: list[Claim] = []
    mappings: list[ClaimMapping] = []
    for index, mapping in enumerate(
        (source_findings.get("claim_to_source_data") or [])[:200], start=1
    ):
        claim_items = mapping.get("candidate_claims") or []
        claim_text = (
            claim_items[0].get("text")
            if claim_items and isinstance(claim_items[0], dict)
            else ""
        )
        if not claim_text:
            continue
        claim_id = f"CL-{index:04d}"
        linked = [
            item.get("finding_id")
            for item in (mapping.get("linked_priority_findings") or [])
            if isinstance(item, dict) and item.get("finding_id")
        ]
        refs = [
            evidence_by_finding[item] for item in linked if item in evidence_by_finding
        ]
        claims.append(
            Claim(
                claim_id=claim_id,
                text=claim_text,
                claim_type="figure_trace",
                source=str(mapping.get("source_figure_id", "")),
                evidence_refs=refs,
                status="pending",
                metadata={
                    "mapping_id": mapping.get("mapping_id"),
                    "canonical_source": "deterministic_scaffolding_fallback",
                },
            )
        )
        mappings.append(
            ClaimMapping(
                mapping_id=str(mapping.get("mapping_id") or f"CM-{index:04d}"),
                claim_id=claim_id,
                evidence_refs=refs,
                confidence=str(mapping.get("mapping_confidence", "medium")),
                finding_refs=linked,
                rationale=str(mapping.get("manual_review_note", "")),
                metadata={
                    "canonical_source": "deterministic_scaffolding_fallback",
                    "source_figure_id": mapping.get("source_figure_id"),
                    "workbook": mapping.get("workbook"),
                    "sheet": mapping.get("sheet"),
                    "review_priority": mapping.get("review_priority"),
                    "raw": mapping,
                },
            )
        )
    return claims, mappings


def _merge_deterministic_mappings(
    *,
    agent_claims: list[Claim],
    agent_mappings: list[ClaimMapping],
    source_findings: dict[str, Any],
    evidence_by_finding: dict[Any, str],
) -> tuple[list[Claim], list[ClaimMapping]]:
    """Supplement agent-refined claim mappings with uncovered deterministic ones.

    The agent path (SourceDataAuditor) may refine only a subset of the
    deterministic claim_to_source_data mappings produced by the Source Data
    findings tool.  This function adds the remaining deterministic mappings
    so the bundle captures the full mapping coverage.
    """
    covered_ids: set[str] = {str(m.mapping_id) for m in agent_mappings}

    extra_claims: list[Claim] = []
    extra_mappings: list[ClaimMapping] = []
    counter = len(agent_claims) + 1

    for mapping in (source_findings.get("claim_to_source_data") or [])[:200]:
        mapping_id = str(mapping.get("mapping_id", ""))
        if not mapping_id or mapping_id in covered_ids:
            continue

        # Try candidate_claims first, then matched_paper_references as fallback
        claim_items = mapping.get("candidate_claims") or []
        claim_text = ""
        if claim_items and isinstance(claim_items[0], dict):
            claim_text = claim_items[0].get("text", "")
        if not claim_text:
            paper_refs = mapping.get("matched_paper_references") or []
            if paper_refs and isinstance(paper_refs[0], dict):
                claim_text = paper_refs[0].get("text", "")

        if not claim_text:
            continue

        claim_id = f"CL-{counter:04d}"
        counter += 1

        linked = [
            item.get("finding_id")
            for item in (mapping.get("linked_priority_findings") or [])
            if isinstance(item, dict) and item.get("finding_id")
        ]
        refs = [
            evidence_by_finding[item] for item in linked if item in evidence_by_finding
        ]

        extra_claims.append(
            Claim(
                claim_id=claim_id,
                text=claim_text,
                claim_type="figure_trace",
                source=str(mapping.get("source_figure_id", "")),
                evidence_refs=refs,
                status="pending",
                metadata={
                    "mapping_id": mapping_id,
                    "canonical_source": "deterministic_supplement",
                },
            )
        )
        extra_mappings.append(
            ClaimMapping(
                mapping_id=mapping_id,
                claim_id=claim_id,
                evidence_refs=refs,
                confidence=str(mapping.get("mapping_confidence", "medium")),
                finding_refs=linked,
                rationale=str(mapping.get("manual_review_note", "")),
                metadata={
                    "canonical_source": "deterministic_supplement",
                    "source_figure_id": mapping.get("source_figure_id"),
                    "workbook": mapping.get("workbook"),
                    "sheet": mapping.get("sheet"),
                    "review_priority": mapping.get("review_priority"),
                    "raw": mapping,
                },
            )
        )
    return extra_claims, extra_mappings
