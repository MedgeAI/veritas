from __future__ import annotations

import json

from engine.static_audit.html_report import render_static_audit_html


def write_json(path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_static_audit_html_report_renders_priority_evidence_card(tmp_path) -> None:
    write_json(
        tmp_path / "source_data_findings.json",
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
    write_json(tmp_path / "source_data_profile.json", {"summary": {"workbook_count": 1}})
    write_json(tmp_path / "static_audit_bundle.json", {"agent_traces": [], "claim_mappings": [1]})
    write_json(tmp_path / "agent_judge.json", {"summary": {"technical_risk_summary": "Review needed."}})

    html = render_static_audit_html(tmp_path, "case-a")

    assert "final_audit_report.html" not in html
    assert "F-TEST-001" in html
    assert "full.md:729-730" in html
    assert "case_source.xlsx" in html
    assert "formula-derived column" in html


def test_static_audit_html_report_pattern_view_is_case_agnostic(tmp_path) -> None:
    write_json(
        tmp_path / "source_data_pair_forensics.json",
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
        tmp_path / "agent_claim_extractor.json",
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
        tmp_path / "agent_source_data_auditor.json",
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
    write_json(tmp_path / "source_data_findings.json", {"summary": {}, "priority_findings": []})
    write_json(tmp_path / "source_data_profile.json", {"summary": {"workbook_count": 1, "sheet_count": 2}})
    write_json(tmp_path / "static_audit_bundle.json", {"agent_traces": [], "claim_mappings": [1]})

    html = render_static_audit_html(tmp_path, "case-generic")

    assert "配对样本固定行偏移与比例复用" in html
    assert "GEN-ROW-001" in html
    assert "Assay Alpha" in html
    assert "generic_source.xlsx" in html
    assert "Fig.7d" not in html
    assert "ROS-0001" not in html
    assert "PT/RT" not in html
