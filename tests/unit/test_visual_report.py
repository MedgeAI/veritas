"""Tests for visual_evidence_section in HTML report."""

from __future__ import annotations

import json

from engine.static_audit.html_report._core import visual_evidence_section


def write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_visual_evidence_section_empty(tmp_path) -> None:
    """When no visual artifacts exist, section should render gracefully."""
    html = visual_evidence_section(tmp_path)
    assert "Visual Evidence Package" in html
    assert "figures" in html
    assert "panels" in html
    assert "relationships" in html
    assert "visual findings" in html
    assert "未提取到 figure 级图像证据" in html
    assert "未发现 panel 间相似关系" in html
    assert "未生成 visual finding" in html
    assert "未生成视觉复核问题" in html


def test_visual_evidence_section_with_figures(tmp_path) -> None:
    """When visual_evidence.json has figures, they should appear in the section."""
    write_json(
        tmp_path / "visual_evidence.json",
        {
            "version": "1.0",
            "figures": [
                {
                    "figure_id": "FE-0001",
                    "source_image_path": "images/Figure1.png",
                    "label": "Figure 1",
                    "caption": "Test figure caption",
                    "page_number": 3,
                    "bbox": [100, 200, 400, 300],
                    "width": 800,
                    "height": 600,
                    "panel_count": 2,
                }
            ],
        },
    )
    write_json(
        tmp_path / "panel_evidence.json",
        {
            "version": "1.0",
            "panels": [
                {
                    "panel_id": "PE-0001-01",
                    "parent_figure_id": "FE-0001",
                    "label": "a",
                    "bbox": [0, 0, 200, 300],
                    "crop_path": "panels/PE-0001-01.png",
                    "width": 200,
                    "height": 300,
                    "extraction_confidence": 0.85,
                    "extraction_method": "contour_edge_detection",
                },
                {
                    "panel_id": "PE-0001-02",
                    "parent_figure_id": "FE-0001",
                    "label": "b",
                    "bbox": [200, 0, 200, 300],
                    "crop_path": "panels/PE-0001-02.png",
                    "width": 200,
                    "height": 300,
                    "extraction_confidence": 0.92,
                    "extraction_method": "contour_edge_detection",
                },
            ],
        },
    )

    html = visual_evidence_section(tmp_path)
    assert "FE-0001" in html
    assert "Figure 1" in html
    assert "Test figure caption" in html
    assert "PE-0001-01" in html
    assert "PE-0001-02" in html


def test_visual_evidence_section_with_relationships(tmp_path) -> None:
    """When image_relationships.json has relationships, they should appear in the table."""
    write_json(
        tmp_path / "image_relationships.json",
        {
            "version": "1.0",
            "relationships": [
                {
                    "relationship_id": "IR-0001",
                    "source_type": "copy_move_single",
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-02",
                    "score": 0.85,
                    "match_method": "orb_ransac",
                    "inlier_count": 42,
                }
            ],
        },
    )

    html = visual_evidence_section(tmp_path)
    # Check for relationship data (not relationship_id, which isn't shown in table)
    assert "copy_move_single" in html
    assert "PE-0001-01" in html
    assert "PE-0001-02" in html
    assert "0.850" in html
    assert "orb_ransac" in html


def test_visual_evidence_section_with_findings(tmp_path) -> None:
    """When visual_findings.json has findings, they should appear in cards."""
    write_json(
        tmp_path / "visual_findings.json",
        {
            "version": "1.0",
            "findings": [
                {
                    "finding_id": "VF-0001",
                    "category": "copy_move_single",
                    "risk_level": "high",
                    "summary": "Test visual finding summary",
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-02",
                    "relationship_id": "IR-0001",
                    "score": 0.85,
                    "benign_explanations": ["合法的实验对照"],
                    "manual_review_questions": ["验证匹配的 panel 是否描绘同一实验主体"],
                }
            ],
        },
    )

    html = visual_evidence_section(tmp_path)
    assert "VF-0001" in html
    assert "Test visual finding summary" in html
    assert "合法的实验对照" in html
    assert "验证匹配的 panel 是否描绘同一实验主体" in html
    assert "Manual Review Checklist" in html


def test_visual_evidence_section_with_review_queue_and_clusters(tmp_path) -> None:
    write_json(
        tmp_path / "panel_evidence.json",
        {
            "version": "1.0",
            "panels": [
                {
                    "panel_id": "PE-0001-01",
                    "parent_figure_id": "FE-0001",
                    "label": "a",
                    "bbox": [0, 0, 100, 100],
                    "crop_path": "panels/a.png",
                    "width": 100,
                    "height": 100,
                    "extraction_confidence": 0.5,
                    "extraction_method": "whole_figure_fallback",
                }
            ],
        },
    )
    write_json(
        tmp_path / "visual_findings.json",
        {
            "version": "1.0",
            "finding_count": 1,
            "finding_cluster_count": 1,
            "review_queue_count": 1,
            "findings": [
                {
                    "finding_id": "VF-0001",
                    "category": "copy_move_cross",
                    "risk_level": "medium",
                    "summary": "跨图 copy-move 检测发现 panel 存在相似区域",
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0002-01",
                    "relationship_id": "IR-0001",
                    "score": 0.39,
                    "metadata": {"panel_extraction_quality": "whole_figure_fallback"},
                }
            ],
            "finding_clusters": [
                {
                    "cluster_id": "VFC-0001",
                    "category": "copy_move_cross",
                    "risk_level": "medium",
                    "scope": "cross_figure",
                    "figure_ids": ["FE-0001", "FE-0002"],
                    "finding_count": 1,
                    "relationship_count": 1,
                    "max_score": 0.39,
                    "panel_extraction_quality": "whole_figure_fallback",
                    "representative_finding_ids": ["VF-0001"],
                }
            ],
            "review_queue": [
                {
                    "task_id": "VRT-001",
                    "priority": "medium",
                    "cluster_id": "VFC-0001",
                    "category": "copy_move_cross",
                    "scope": "cross_figure",
                    "figure_ids": ["FE-0001", "FE-0002"],
                    "finding_count": 1,
                    "relationship_count": 1,
                    "panel_extraction_quality": "whole_figure_fallback",
                    "question": "复核 fallback panel 的 visual cluster。",
                }
            ],
        },
    )

    html = visual_evidence_section(tmp_path)

    assert "Visual Review Queue" in html
    assert "VRT-001" in html
    assert "Visual Finding Clusters" in html
    assert "VFC-0001" in html
    assert "fallback 降级" in html
    assert "fallback panel evidence; risk display capped" in html


def test_visual_evidence_section_language_compliance(tmp_path) -> None:
    """Findings with forbidden phrases should not render the forbidden text."""
    write_json(
        tmp_path / "visual_findings.json",
        {
            "version": "1.0",
            "findings": [
                {
                    "finding_id": "VF-0002",
                    "category": "copy_move_cross",
                    "risk_level": "medium",
                    "summary": "确认造假 finding",
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-02",
                    "relationship_id": "IR-0001",
                    "score": 0.5,
                }
            ],
        },
    )

    html = visual_evidence_section(tmp_path)
    assert "确认造假" not in html
    assert "报告禁用措辞" in html


def test_visual_evidence_section_in_full_report(tmp_path) -> None:
    """Visual evidence section should be included in the full HTML report."""
    from engine.static_audit.html_report._core import render_static_audit_html

    # Write minimal required artifacts
    write_json(tmp_path / "audit_run_manifest.json", {"steps": []})
    write_json(tmp_path / "static_audit_bundle.json", {"agent_traces": [], "claim_mappings": []})
    write_json(tmp_path / "visual_evidence.json", {
        "version": "1.0",
        "figures": [{"figure_id": "FE-0001", "source_image_path": "images/Figure1.png", "label": "Figure 1", "caption": "Test", "page_number": 1, "bbox": None, "width": 100, "height": 100, "panel_count": 0}],
    })

    html = render_static_audit_html(tmp_path, "test-case")

    # The visual evidence section should be present
    assert "Visual Evidence Package" in html
    assert "id=\"visual-evidence\"" in html
    assert "FE-0001" in html
