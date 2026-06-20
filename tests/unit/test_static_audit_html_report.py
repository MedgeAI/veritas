from __future__ import annotations

import json

from engine.static_audit.html_report import render_static_audit_html
from engine.static_audit.paths import resolve_artifact_path


def write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _path(tmp_path, name: str):
    return resolve_artifact_path(tmp_path, name)


def test_static_audit_html_report_renders_priority_evidence_card(tmp_path) -> None:
    write_json(
        _path(tmp_path, "source_data_findings.json"),
        {
            "summary": {"priority_findings": 1, "claim_to_source_data_mappings": 1},
            "priority_findings": [
                {
                    "finding_id": "F-TEST-001",
                    "category": "fixed_difference",
                    "risk_level": "medium",
                    "workbook": "case_source.xlsx",
                    "sheet": "Source Data Fig.2",
                    "column_pair": ["D", "E"],
                    "overlap_rows": 35,
                    "support_rows": 35,
                    "support_rate": 1.0,
                    "relationship_value": "0.3",
                    "sample_pairs": [{"row": 5, "left": "0.45", "right": "0.15"}],
                    "benign_explanations": ["formula-derived column"],
                }
            ],
            "claim_to_source_data": [
                {
                    "mapping_id": "CM-TEST-001",
                    "source_figure_id": "Fig.2",
                    "linked_priority_findings": [{"finding_id": "F-TEST-001"}],
                    "candidate_claims": [{"text": "Treatment changes the measured endpoint."}],
                    "matched_paper_references": [
                        {"line_start": 729, "line_end": 730, "match_label": "Fig. 2"}
                    ],
                }
            ],
        },
    )
    write_json(_path(tmp_path, "source_data_profile.json"), {"summary": {"workbook_count": 1}})
    write_json(_path(tmp_path, "static_audit_bundle.json"), {"agent_traces": [], "claim_mappings": [1]})
    write_json(_path(tmp_path, "agent_judge.json"), {"summary": {"technical_risk_summary": "Review needed."}})

    html = render_static_audit_html(tmp_path, "case-a")

    assert "final_audit_report.html" not in html
    assert "F-TEST-001" in html
    assert "full.md:729-730" in html
    assert "case_source.xlsx" in html
    assert "formula-derived column" in html


def test_static_audit_html_report_pattern_view_is_case_agnostic(tmp_path) -> None:
    write_json(
        _path(tmp_path, "source_data_pair_forensics.json"),
        {
            "summary": {"priority_findings": 2},
            "priority_findings": [
                {
                    "finding_id": "GEN-ROW-001",
                    "category": "row_offset_scalar_multiple",
                    "risk_level": "high",
                    "workbook": "generic_source.xlsx",
                    "sheet": "Assay Alpha",
                    "columns": ["value"],
                    "row_offset": 12,
                    "support_rows": 12,
                    "overlap_rows": 12,
                    "support_rate": 1.0,
                },
                {
                    "finding_id": "GEN-RATIO-001",
                    "category": "long_format_paired_ratio_reuse",
                    "risk_level": "high",
                    "workbook": "generic_source.xlsx",
                    "sheet": "Assay Beta",
                    "columns": ["group_a", "group_b"],
                    "pair_id_offset": 6,
                    "matched_pair_groups": 6,
                },
            ],
        },
    )
    write_json(
        _path(tmp_path, "agent_claim_extractor.json"),
        {
            "claims": [
                {
                    "claim_id": "AC-GENERIC-001",
                    "claim_text": "The paired assay differs between two study groups.",
                    "evidence_refs": ["source_data_pair_forensics:GEN-ROW-001"],
                }
            ]
        },
    )
    write_json(
        _path(tmp_path, "agent_source_data_auditor.json"),
        {
            "claim_to_source_data": [
                {
                    "claim_id": "AC-GENERIC-001",
                    "source_data_refs": ["source_data_pair_forensics:GEN-ROW-001"],
                    "needs_human_review": True,
                }
            ],
            "manual_review_tasks": [
                {
                    "task_id": "MR-GENERIC-001",
                    "priority": "high",
                    "question": "Check whether the row offset is a valid paired export convention.",
                    "evidence_refs": ["source_data_pair_forensics:GEN-ROW-001"],
                }
            ],
        },
    )
    write_json(_path(tmp_path, "source_data_findings.json"), {"summary": {}, "priority_findings": []})
    write_json(_path(tmp_path, "source_data_profile.json"), {"summary": {"workbook_count": 1, "sheet_count": 2}})
    write_json(_path(tmp_path, "static_audit_bundle.json"), {"agent_traces": [], "claim_mappings": [1]})

    html = render_static_audit_html(tmp_path, "case-generic")

    assert "Check whether the row offset is a valid paired export convention." in html
    assert '<span class="conf-badge conf-agent">复核摘要</span>' in html
    assert "GEN-ROW-001" in html
    assert "Assay Alpha" in html
    assert "generic_source.xlsx" in html
    assert "Fig.7d" not in html
    assert "ROS-0001" not in html
    assert "PT/RT" not in html


def test_static_audit_html_report_uses_specific_pattern_titles_and_does_not_escape_badges(tmp_path) -> None:
    write_json(
        _path(tmp_path, "source_data_findings.json"),
        {
            "summary": {"priority_findings": 1},
            "priority_findings": [
                {
                    "finding_id": "DC-TEST-001",
                    "category": "duplicate_numeric_columns",
                    "risk_level": "medium",
                    "workbook": "source.xlsx",
                    "sheet": "Assay Matrix",
                    "column_pair": ["B", "C"],
                    "overlap_rows": 40,
                    "equal_rows": 39,
                    "support_rate": 0.975,
                }
            ],
        },
    )
    write_json(
        _path(tmp_path, "agent_source_data_auditor.json"),
        {
            "manual_review_tasks": [
                {
                    "task_id": "MR-DC-001",
                    "priority": "medium",
                    "question": (
                        '<span class="conf-badge conf-data">数据关联</span>'
                        "Check duplicated columns against the source workbook."
                    ),
                    "evidence_refs": ["source_data_findings:DC-TEST-001"],
                }
            ],
        },
    )
    write_json(_path(tmp_path, "source_data_profile.json"), {"summary": {"workbook_count": 1, "sheet_count": 1}})
    write_json(_path(tmp_path, "static_audit_bundle.json"), {"agent_traces": [], "claim_mappings": []})

    html = render_static_audit_html(tmp_path, "case-duplicate-columns")

    assert "低维行向量重复与舍入偏差" not in html
    assert "&lt;span class=&quot;conf-badge" not in html
    assert '<span class="conf-badge conf-agent">复核摘要</span>' in html
    assert "Check duplicated columns against the source workbook." in html
    assert '<span class="conf-badge conf-data">证据记录</span>Check duplicated columns' in html


def test_static_audit_html_report_does_not_truncate_fig_abbreviation_in_agent_pattern_title(tmp_path) -> None:
    write_json(
        _path(tmp_path, "source_data_findings.json"),
        {
            "summary": {"priority_findings": 1},
            "priority_findings": [
                {
                    "finding_id": "DC-FIG-001",
                    "category": "duplicate_numeric_columns",
                    "risk_level": "medium",
                    "workbook": "source.xlsx",
                    "sheet": "Fig. 6i",
                    "column_pair": ["Liver_sc4", "Liver_sc5"],
                    "overlap_rows": 50,
                    "equal_rows": 49,
                    "support_rate": 0.98,
                }
            ],
        },
    )
    write_json(
        _path(tmp_path, "agent_source_data_auditor.json"),
        {
            "finding_reviews": [
                {
                    "finding_id": "DC-FIG-001",
                    "benign_explanations": [
                        (
                            "Fig. 6i sheet 中 Liver_sc4 和 Liver_sc5 在 50 行中 49 行相等。"
                            "需确认两列是否来自独立 single-cell 样本。"
                        )
                    ],
                }
            ],
        },
    )
    write_json(_path(tmp_path, "source_data_profile.json"), {"summary": {"workbook_count": 1, "sheet_count": 1}})
    write_json(_path(tmp_path, "static_audit_bundle.json"), {"agent_traces": [], "claim_mappings": []})

    html = render_static_audit_html(tmp_path, "case-fig-title")

    assert "<span class='evidence-kicker'>Fig. 6i sheet" in html
    assert "<h3>Fig. 6i sheet" in html
    assert "<span class='evidence-kicker'>Fig.</span>" not in html
    assert "<h3>Fig.</h3>" not in html


def test_static_audit_html_report_merges_source_and_pair_priority_findings(tmp_path) -> None:
    write_json(
        _path(tmp_path, "source_data_findings.json"),
        {
            "summary": {"priority_findings": 1},
            "priority_findings": [
                {
                    "finding_id": "SRC-001",
                    "category": "fixed_difference",
                    "risk_level": "medium",
                    "workbook": "source.xlsx",
                    "sheet": "Endpoint A",
                    "column_pair": ["B", "C"],
                    "support_rows": 18,
                    "overlap_rows": 18,
                }
            ],
        },
    )
    write_json(
        _path(tmp_path, "source_data_pair_forensics.json"),
        {
            "summary": {"priority_findings": 1},
            "priority_findings": [
                {
                    "finding_id": "PAIR-001",
                    "category": "row_offset_scalar_multiple",
                    "risk_level": "high",
                    "workbook": "source.xlsx",
                    "sheet": "Endpoint B",
                    "columns": ["value"],
                    "row_offset": 8,
                    "support_rows": 8,
                    "overlap_rows": 8,
                }
            ],
        },
    )
    write_json(_path(tmp_path, "static_audit_bundle.json"), {"agent_traces": [], "claim_mappings": []})

    html = render_static_audit_html(tmp_path, "case-merged")

    assert "代表性证据卡（展示 2 / 2 条）" in html
    assert "SRC-001" in html
    assert "PAIR-001" in html


def test_static_audit_html_report_uses_pass_verdict_without_findings(tmp_path) -> None:
    write_json(
        _path(tmp_path, "audit_run_manifest.json"),
        {"steps": [{"key": "evidence_ledger", "title": "Evidence ledger", "status": "ran"}]},
    )
    write_json(
        _path(tmp_path, "static_audit_bundle.json"),
        {
            "evidence_items": [{"evidence_id": "EV-001"}],
            "claims": [],
            "findings": [],
            "claim_mappings": [],
            "agent_traces": [],
            "execution_status": {"status": "not_provided"},
        },
    )

    html = render_static_audit_html(tmp_path, "case-clean")

    assert "Needs Human Review" not in html
    assert "未见高优先级复核项" in html


def test_static_audit_html_report_renders_canonical_non_source_data_finding(tmp_path) -> None:
    write_json(
        _path(tmp_path, "static_audit_bundle.json"),
        {
            "evidence_items": [
                {
                    "evidence_id": "EV-IMG-001",
                    "kind": "image",
                    "source_path": "images/figure_1.png",
                    "locator": {"figure": "Fig. 1"},
                }
            ],
            "claims": [
                {
                    "claim_id": "CL-IMG-001",
                    "text": "The image panels represent independent conditions.",
                    "claim_type": "figure_trace",
                }
            ],
            "findings": [
                {
                    "finding_id": "VF-001",
                    "category": "near_duplicate_image",
                    "risk_level": "medium",
                    "summary": "Near-duplicate image candidate requires visual review.",
                    "evidence_refs": ["EV-IMG-001"],
                    "metadata": {"source_artifact": "image_relationships.json"},
                }
            ],
            "claim_mappings": [
                {
                    "mapping_id": "CM-IMG-001",
                    "claim_id": "CL-IMG-001",
                    "evidence_refs": ["EV-IMG-001"],
                    "confidence": "medium",
                    "finding_refs": ["VF-001"],
                }
            ],
            "agent_traces": [],
            "execution_status": {"status": "not_provided"},
        },
    )

    html = render_static_audit_html(tmp_path, "case-visual")

    assert "VF-001" in html
    assert "near_duplicate_image" in html
    assert "证据引用" in html


def test_static_audit_html_report_keeps_rule_fallback_out_of_top_patterns(tmp_path) -> None:
    write_json(
        _path(tmp_path, "static_audit_bundle.json"),
        {
            "evidence_items": [{"evidence_id": "EV-RUN-001", "kind": "execution", "source_path": "run.log"}],
            "claims": [],
            "findings": [
                {
                    "finding_id": "RUN-001",
                    "category": "execution_status",
                    "risk_level": "medium",
                    "summary": "Execution evidence was not available.",
                    "evidence_refs": ["EV-RUN-001"],
                    "metadata": {"source_artifact": "runtime_manifest.json"},
                }
            ],
            "claim_mappings": [],
            "agent_traces": [],
            "execution_status": {"status": "not_provided"},
        },
    )

    html = render_static_audit_html(tmp_path, "case-rule-fallback")

    assert "未形成重点摘要" in html
    assert "执行证据与 claim 对账候选" not in html
    assert "运行命令、日志或结果文件与论文 claim" not in html
    assert "规则定义" not in html
    assert "RUN-001" in html
    assert "execution_status：1 条原始记录" in html


def test_static_audit_html_report_keeps_duplicate_row_vector_out_of_top_patterns(tmp_path) -> None:
    write_json(
        _path(tmp_path, "source_data_pair_forensics.json"),
        {
            "summary": {"priority_findings": 1},
            "priority_findings": [
                {
                    "finding_id": "DRV-LOW-001",
                    "category": "duplicate_row_vector",
                    "risk_level": "high",
                    "workbook": "source.xlsx",
                    "sheet": "Fig. 6i",
                    "rows": [2, 3, 4, 5],
                    "duplicate_row_count": 4,
                    "width": 2,
                    "columns": ["Days", "Control"],
                    "values": ["13", "0"],
                    "artifact_likelihood": "high",
                    "artifact_reason": "low-cardinality time/event or grouped endpoint rows",
                }
            ],
        },
    )
    write_json(
        _path(tmp_path, "agent_source_data_auditor.json"),
        {
            "manual_review_tasks": [
                {
                    "task_id": "MR-DRV-001",
                    "priority": "high",
                    "question": "Check whether repeated row vectors are template rows.",
                    "evidence_refs": ["source_data_pair_forensics:DRV-LOW-001"],
                }
            ],
        },
    )
    write_json(_path(tmp_path, "source_data_profile.json"), {"summary": {"workbook_count": 1, "sheet_count": 1}})
    write_json(_path(tmp_path, "static_audit_bundle.json"), {"agent_traces": [], "claim_mappings": []})

    html = render_static_audit_html(tmp_path, "case-row-vector-context")
    top_patterns = html.split('<section class="panel section" id="noise-ledger">', 1)[0]

    assert "未形成重点事实摘要" in top_patterns
    assert "DRV-LOW-001" not in top_patterns
    assert "Check whether repeated row vectors are template rows." not in top_patterns
    assert "DRV-LOW-001" in html
    assert "Check whether repeated row vectors are template rows." in html
    assert "上下文记录" in html
    assert "高优先级</span></td><td>duplicate_row_vector" not in html


def test_static_audit_html_report_moves_verdict_false_positive_to_excluded_section_and_escapes_text(tmp_path) -> None:
    write_json(
        _path(tmp_path, "source_data_findings.json"),
        {
            "summary": {"priority_findings": 2},
            "priority_findings": [
                {
                    "finding_id": "DC-FP-001",
                    "category": "duplicate_numeric_columns",
                    "risk_level": "high",
                    "workbook": "source.xlsx",
                    "sheet": "Stats",
                    "column_pair": ["Mean", "Sum"],
                    "overlap_rows": 20,
                    "equal_rows": 20,
                    "support_rate": 1.0,
                },
                {
                    "finding_id": "DC-UN-001",
                    "category": "duplicate_numeric_columns",
                    "risk_level": "high",
                    "workbook": "source.xlsx",
                    "sheet": "Measurements",
                    "column_pair": ["A", "B"],
                    "overlap_rows": 20,
                    "equal_rows": 20,
                    "support_rate": 1.0,
                },
            ],
        },
    )
    write_json(
        _path(tmp_path, "source_data_findings_verdict.json"),
        {
            "sheets": [
                {
                    "workbook": "source.xlsx",
                    "sheet": "Stats",
                    "findings": [
                        {
                            "id": "DC-FP-001",
                            "verdict": "false_positive",
                            "confidence": 0.91,
                            "benign_pattern": "descriptive_statistics_table",
                            "explanation": "<script>alert('x')</script> Mean/Sum/N derivation.",
                        }
                    ],
                },
                {
                    "workbook": "source.xlsx",
                    "sheet": "Measurements",
                    "findings": [
                        {
                            "id": "DC-UN-001",
                            "verdict": "uncertain",
                            "confidence": 0.55,
                            "explanation": "Independent measurement columns still need review.",
                        }
                    ],
                },
            ],
            "summary": {
                "total_findings": 2,
                "true_positive": 0,
                "false_positive": 1,
                "uncertain": 1,
            },
        },
    )
    write_json(_path(tmp_path, "source_data_profile.json"), {"summary": {"workbook_count": 1, "sheet_count": 2}})
    write_json(_path(tmp_path, "static_audit_bundle.json"), {"agent_traces": [], "claim_mappings": []})

    html = render_static_audit_html(tmp_path, "case-verdict-filter")
    before_excluded = html.split("LLM 语义裁决排除项", 1)[0]
    excluded = html.split("LLM 语义裁决排除项", 1)[1]

    assert "DC-FP-001" not in before_excluded
    assert "DC-UN-001" in before_excluded
    assert "DC-FP-001" in excluded
    assert "<script>alert('x')</script>" not in html
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; Mean/Sum/N derivation." in html


def test_static_audit_html_report_renders_paperfraud_rule_matches(tmp_path) -> None:
    write_json(
        _path(tmp_path, "paperfraud_rule_matches.json"),
        {
            "summary": {
                "total_rules_loaded": 48,
                "total_triggered": 1,
                "methodology_review_triggered": 1,
                "fraud_detection_triggered": 0,
                "red_count": 0,
                "orange_count": 1,
                "yellow_count": 0,
            },
            "triggered_rules": [
                {
                    "rule_id": "statistical_methods.effect_size_missing",
                    "title": "Only p-value reported without effect size",
                    "severity": "orange",
                    "rule_type": "methodology_review",
                    "category": "统计方法审查",
                    "evidence": "Matched p-value language in Methods.",
                    "human_review": "Check whether the manuscript reports effect size and uncertainty.",
                }
            ],
            "reviewer_form": [
                {
                    "rule_id": "statistical_methods.effect_size_missing",
                    "human_review_guide": "Check whether the manuscript reports effect size and uncertainty.",
                }
            ],
        },
    )
    write_json(_path(tmp_path, "static_audit_bundle.json"), {"agent_traces": [], "claim_mappings": []})

    html = render_static_audit_html(tmp_path, "case-paperfraud")

    assert "规则库提示" in html
    assert "statistical_methods.effect_size_missing" in html
    assert "orange" in html
    assert "Check whether the manuscript reports effect size" in html


def test_static_audit_html_report_removes_emoji_badges_and_corrects_stale_judge_summary(tmp_path) -> None:
    write_json(
        _path(tmp_path, "static_audit_bundle.json"),
        {
            "evidence_items": [{"evidence_id": "EV-001"}],
            "claims": [],
            "findings": [],
            "claim_mappings": [],
            "agent_traces": [],
            "execution_status": {"status": "not_provided"},
        },
    )
    write_json(
        _path(tmp_path, "agent_claim_extractor.json"),
        {
            "claims": [
                {
                    "claim_id": "AC-001",
                    "claim_text": "The manuscript reports a measurable endpoint.",
                    "evidence_refs": ["EV-001"],
                }
            ],
            "limitations": ["One figure claim needs manual source-data review."],
        },
    )
    write_json(
        _path(tmp_path, "agent_source_data_auditor.json"),
        {
            "claim_to_source_data": [
                {
                    "claim_id": "AC-001",
                    "source_data_refs": ["source_data_findings:F-001"],
                    "needs_human_review": True,
                }
            ],
            "finding_reviews": [
                {
                    "finding_id": "F-001",
                    "disposition": "needs_human_review",
                }
            ],
            "manual_review_tasks": [
                {
                    "task_id": "MR-001",
                    "priority": "medium",
                    "question": "核对该 claim 的原始 Source Data。",
                    "evidence_refs": ["source_data_findings:F-001"],
                }
            ],
        },
    )
    write_json(
        _path(tmp_path, "agent_judge.json"),
        {
            "summary": {
                "technical_risk_summary": (
                    "claim_extractor 和 source_data_auditor role 均未产出，"
                    "无法进行 claim-to-evidence 复核。"
                )
            }
        },
    )

    html = render_static_audit_html(tmp_path, "case-no-emoji")

    assert "📋" not in html
    assert "📊" not in html
    assert "🤖" not in html
    assert "证据记录" in html
    assert "HTML 已按产物计数校正" in html
    assert "论文表述=1" in html
    assert "Source Data 映射=1" in html
