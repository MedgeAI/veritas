from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from engine.static_audit.investigation import InvestigationAction
from engine.static_audit.orchestrator import (
    StepResult,
    build_static_audit_bundle,
    resolve_artifact_path,
    run_investigation_tool_action,
    run_visual_finding_pipeline,
    run_visual_panel_extraction,
)
from engine.tools.registry import TOOL_ID_COPY_MOVE, coerce_tool_params


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_run_visual_panel_extraction_writes_canonical_artifacts(tmp_path) -> None:
    workdir = tmp_path / "work"
    images_dir = resolve_artifact_path(workdir, "images")
    images_dir.mkdir(parents=True)
    shutil.copyfile(
        Path("tests/fixtures/visual/synthetic_2x2_clean/images/Figure1.png"),
        images_dir / "Figure1.png",
    )

    steps, manifest = run_visual_panel_extraction(
        workdir=workdir,
        images_dir=images_dir,
        force=True,
    )

    visual_evidence = json.loads(
        resolve_artifact_path(workdir, "visual_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    panel_evidence = json.loads(
        resolve_artifact_path(workdir, "panel_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert steps[0].key == "visual_panel_extraction"
    assert steps[0].status == "ran"
    assert manifest["panel_extraction"]["figure_count"] == 1
    assert visual_evidence["figures"][0]["figure_id"] == "FE-0001"
    assert panel_evidence["panel_count"] >= 1
    assert panel_evidence["panels"][0]["parent_figure_id"] == "FE-0001"


def test_run_visual_panel_extraction_records_oversegmentation_fallback(
    tmp_path, monkeypatch
) -> None:
    workdir = tmp_path / "work"
    images_dir = resolve_artifact_path(workdir, "images")
    images_dir.mkdir(parents=True)
    shutil.copyfile(
        Path("tests/fixtures/visual/synthetic_2x2_clean/images/Figure1.png"),
        images_dir / "Figure1.png",
    )

    def fake_extract_panels_batch(figure_path_pairs, *, output_dir, **_kwargs):
        batch_dir = output_dir / "yolov5_batch"
        batch_dir.mkdir(parents=True, exist_ok=True)
        rows = ["FIGNAME,X0,Y0,X1,Y1,LABEL,ID"]
        for index in range(17):
            rows.append(f"Figure1,0,0,10,10,Blots,{index + 1}")
        (batch_dir / "PANELS.csv").write_text("\n".join(rows), encoding="utf-8")
        return {fid: [] for fid, _ in figure_path_pairs}

    monkeypatch.setattr(
        "engine.static_audit.visual_pipeline.extract_panels_batch",
        fake_extract_panels_batch,
    )

    _steps, manifest = run_visual_panel_extraction(
        workdir=workdir,
        images_dir=images_dir,
        force=True,
    )

    panel_evidence = json.loads(
        resolve_artifact_path(workdir, "panel_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    visual_evidence = json.loads(
        resolve_artifact_path(workdir, "visual_evidence.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(manifest["panel_extraction"]["limitations"]) == 1
    assert (
        "FE-0001: YOLOv5 over-segmented into 17 panels (max=16)"
        in manifest["panel_extraction"]["limitations"][0]
    )
    panel_metadata = panel_evidence["panels"][0]["metadata"]
    assert panel_metadata["fallback_reason"] == "yolov5_oversegmentation"
    assert panel_metadata["yolov5_detected_panel_count"] == 17
    assert visual_evidence["figures"][0]["metadata"][
        "panel_extraction_fallback_reason"
    ] == "yolov5_oversegmentation"


def test_visual_finding_pipeline_and_bundle_include_visual_findings(tmp_path) -> None:
    workdir = tmp_path / "work"
    write_json(
        resolve_artifact_path(workdir, "visual_evidence.json"),
        {
            "schema_version": "1.0",
            "status": "ran",
            "figures": [
                {
                    "figure_id": "FE-0001",
                    "source_image_path": "images/Figure1.png",
                    "label": "Figure 1",
                    "caption": "",
                    "page_number": 1,
                    "bbox": None,
                    "width": 100,
                    "height": 100,
                    "panel_count": 2,
                }
            ],
        },
    )
    write_json(
        resolve_artifact_path(workdir, "panel_evidence.json"),
        {
            "schema_version": "1.0",
            "status": "ran",
            "panels": [
                {
                    "panel_id": "FE-0001-01",
                    "parent_figure_id": "FE-0001",
                    "label": "a",
                    "bbox": [0, 0, 50, 100],
                    "crop_path": "panels/FE-0001/a.png",
                    "width": 50,
                    "height": 100,
                    "extraction_confidence": 0.9,
                    "extraction_method": "fixture",
                },
                {
                    "panel_id": "FE-0001-02",
                    "parent_figure_id": "FE-0001",
                    "label": "b",
                    "bbox": [50, 0, 50, 100],
                    "crop_path": "panels/FE-0001/b.png",
                    "width": 50,
                    "height": 100,
                    "extraction_confidence": 0.9,
                    "extraction_method": "fixture",
                },
            ],
        },
    )
    write_json(
        resolve_artifact_path(workdir, "investigation")
        / "round_01"
        / "action_01"
        / "visual_copy_move.json",
        {
            "schema_version": "1.0",
            "status": "ran",
            "relationships": [
                {
                    "relationship_id": "IR-0001",
                    "source_type": "copy_move_single",
                    "source_panel_id": "FE-0001-01",
                    "target_panel_id": "FE-0001-02",
                    "score": 0.8,
                    "match_method": "orb_ransac",
                    "inlier_count": 20,
                }
            ],
            "errors": [],
            "limitations": [],
        },
    )
    write_json(
        resolve_artifact_path(workdir, "agent_material_plan.json"),
        {"status": "ok", "selected_optional_lanes": []},
    )

    steps, manifest = run_visual_finding_pipeline(workdir=workdir, force=True)
    bundle = build_static_audit_bundle(
        paper_dir=tmp_path,
        paper_pdf=tmp_path / "paper.pdf",
        source_data_dir=None,
        workdir=workdir,
        case_id="visual-case",
        steps=[StepResult("visual_finding_pipeline", "视觉证据聚合管线", "ran", "test")]
        + steps,
        agent_manifest={"visual_forensics": manifest},
    )

    relationships = json.loads(
        resolve_artifact_path(workdir, "image_relationships.json").read_text(
            encoding="utf-8"
        )
    )
    findings = json.loads(
        resolve_artifact_path(workdir, "visual_findings.json").read_text(
            encoding="utf-8"
        )
    )
    assert relationships["relationship_count"] == 1
    assert findings["finding_count"] == 1
    assert findings["finding_cluster_count"] == 1
    assert findings["review_queue_count"] == 1
    assert findings["finding_clusters"][0]["cluster_id"] == "VFC-0001"
    assert findings["review_queue"][0]["task_id"] == "VRT-001"
    visual_bundle_findings = [
        finding for finding in bundle.findings if finding.finding_id == "VF-0001"
    ]
    assert visual_bundle_findings
    assert visual_bundle_findings[0].issue_category == "consistency"
    assert visual_bundle_findings[0].evidence_refs
    assert any(item.kind == "panel" for item in bundle.evidence_items)


def test_investigation_tool_action_runs_visual_copy_move(tmp_path) -> None:
    workdir = tmp_path / "work"
    write_json(
        resolve_artifact_path(workdir, "panel_evidence.json"),
        {
            "schema_version": "1.0",
            "panels": [
                {
                    "panel_id": "P1",
                    "crop_path": "missing-a.png",
                    "parent_figure_id": "F1",
                },
                {
                    "panel_id": "P2",
                    "crop_path": "missing-b.png",
                    "parent_figure_id": "F1",
                },
            ],
        },
    )
    write_json(
        resolve_artifact_path(workdir, "visual_evidence.json"),
        {"schema_version": "1.0", "figures": []},
    )
    action = InvestigationAction(
        round_id=1,
        action_id="IR-01-A001",
        tool_id=TOOL_ID_COPY_MOVE,
        params=coerce_tool_params(TOOL_ID_COPY_MOVE, {"min_matches": 4}),
        hypothesis="Check visual copy-move candidates.",
        depends_on_artifacts=["panel_evidence.json"],
        expected_evidence_type="image_similarity",
    )

    step, artifacts = run_investigation_tool_action(
        action=action,
        workdir=workdir,
        source_data_dir=None,
        env=os.environ.copy(),
        force=True,
        progress=None,
    )

    assert step.status == "ran"
    assert artifacts
    output = Path(artifacts[0])
    assert output.name == "visual_copy_move.json"
    assert json.loads(output.read_text(encoding="utf-8"))["status"] in {
        "skipped",
        "not_available",
        "ran",
    }
