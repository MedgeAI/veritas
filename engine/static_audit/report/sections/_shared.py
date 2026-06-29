"""Shared data container and report section builders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from engine.tools.registry import selected_tool_ids_from_plan

from engine.static_audit._shared import (
    StepResult,
    resolve_artifact_path,
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

from engine.static_audit.report.claims import (
    brief_list,
    investigation_record_rows,
)


# ---------------------------------------------------------------------------
# Shared data container
# ---------------------------------------------------------------------------


@dataclass
class ReportData:
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


# ---------------------------------------------------------------------------
# Header / scope / pipeline sections
# ---------------------------------------------------------------------------


def header_section(data: ReportData) -> list[str]:
    lines: list[str] = []
    lines.append(f"# Veritas Paper Audit Report: {data.case_id}")
    lines.append("")
    lines.append("## 结论先行")
    lines.append("")
    lines.append("- 本报告由本地 orchestrator 汇总确定性脚本产物生成。")
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


def scope_section(data: ReportData) -> list[str]:
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


def pipeline_section(data: ReportData) -> list[str]:
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


def artifact_manifest_section(data: ReportData) -> list[str]:
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


# ---------------------------------------------------------------------------
# Investigation / agent sections
# ---------------------------------------------------------------------------


def investigation_section(data: ReportData) -> list[str]:
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


def agent_plan_section(data: ReportData) -> list[str]:
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


def judge_section(data: ReportData) -> list[str]:
    """Judge 综合评估：展示 risk_suggestions 和综合判断。"""
    if not data.agent_judge:
        return []
    lines: list[str] = []
    lines.append("## Judge 综合评估")
    lines.append("")

    summary = data.agent_judge.get("summary")
    if summary:
        lines.append(f"**综合判断**: {summary}")
        lines.append("")

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

    notes = data.agent_judge.get("report_notes") or []
    if notes:
        lines.append("")
        lines.append("### Judge 报告备注")
        lines.append("")
        for item in notes[:8]:
            lines.append(f"- {item}")

    limitations = data.agent_judge.get("limitations") or []
    if limitations:
        lines.append("")
        lines.append("### Judge 局限性说明")
        lines.append("")
        for item in limitations[:6]:
            lines.append(f"- {item}")

    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Claim mapping / ledger / numeric / profile sections
# ---------------------------------------------------------------------------


def claim_mapping_section(data: ReportData) -> list[str]:
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


def ledger_section(data: ReportData) -> list[str]:
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


def numeric_section(data: ReportData) -> list[str]:
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


def profile_section(data: ReportData) -> list[str]:
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


# ---------------------------------------------------------------------------
# Findings / pair forensics sections
# ---------------------------------------------------------------------------


def findings_section(data: ReportData) -> list[str]:
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


def pair_forensics_section(data: ReportData) -> list[str]:
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


# ---------------------------------------------------------------------------
# Image / visual / bundle / limitation sections
# ---------------------------------------------------------------------------


def duplicates_section(data: ReportData) -> list[str]:
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


def similarity_section(data: ReportData) -> list[str]:
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


def bundle_section(data: ReportData) -> list[str]:
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


def vlm_section(data: ReportData) -> list[str]:
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


def limitations_section(data: ReportData) -> list[str]:
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
