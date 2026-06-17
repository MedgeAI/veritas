from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from engine.static_audit.investigation import read_investigation_records
from engine.static_audit.paths import resolve_artifact_path
from engine.tools.registry import TOOL_ID_SILA_DENSE
from web.backend.veritas_web.app import VeritasWebApp


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def setup_case_workdir(app: VeritasWebApp, case_id: str) -> Path:
    case = app.store.create_case(case_id=case_id)
    run = app.store.create_run(case.case_id)
    workdir = Path(app.runner.output_root) / case_id / "research-integrity-audit"
    run.workdir = str(workdir)
    app.store.save_run(run)
    write_json(
        resolve_artifact_path(workdir, "panel_evidence.json"),
        {
            "schema_version": "1.0",
            "panels": [
                {"panel_id": "P1", "parent_figure_id": "F1", "crop_path": "visual/panels/F1/a.png"},
                {"panel_id": "P2", "parent_figure_id": "F1", "crop_path": "visual/panels/F1/b.png"},
            ],
        },
    )
    write_json(
        resolve_artifact_path(workdir, "visual_evidence.json"),
        {"schema_version": "1.0", "figures": [{"figure_id": "F1", "source_image_path": "visual/images/F1.png"}]},
    )
    return workdir


def test_web_investigation_runs_dense_on_selected_panels(tmp_path, monkeypatch) -> None:
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    workdir = setup_case_workdir(app, "case-investigation")
    captured: dict[str, Any] = {}

    def fake_detect(panel_evidence, figure_evidence, **kwargs):
        captured["panel_ids"] = [panel["panel_id"] for panel in panel_evidence]
        captured["output_base"] = kwargs["output_base"]
        return {
            "schema_version": "1.0",
            "created_by": "fake",
            "status": "ran",
            "failure_category": None,
            "panel_count": len(panel_evidence),
            "relationship_count": 1,
            "relationships": [
                {
                    "relationship_id": "IR-SILA-0001",
                    "source_type": "copy_move_single",
                    "source_panel_id": "P1",
                    "target_panel_id": "P1",
                    "score": 0.8,
                    "match_method": "sila_dense_single",
                    "inlier_count": 0,
                    "metadata": {"mask_path": "investigation/web/action/sila_dense/P1/a_mask.png"},
                }
            ],
            "errors": [],
            "limitations": [],
        }

    monkeypatch.setattr("web.backend.veritas_web.investigations.detect_sila_dense", fake_detect)

    result = app.investigations.run_investigation(
        "case-investigation",
        {
            "tool_id": TOOL_ID_SILA_DENSE,
            "panel_ids": ["P1", "P2"],
            "params": {"max_panels": 1, "max_relationships": 10},
        },
    )

    assert captured["panel_ids"] == ["P1"]
    assert "/investigation/web/" in str(captured["output_base"])
    assert result["result"]["metadata"]["selected_panel_ids"] == ["P1"]
    assert Path(workdir / result["artifact"]).exists()
    records = read_investigation_records(workdir)
    assert records[-1]["tool_id"] == TOOL_ID_SILA_DENSE
    assert records[-1]["metadata"]["trigger"] == "web_manual"


def test_web_investigation_rejects_unknown_panel(tmp_path) -> None:
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    setup_case_workdir(app, "case-missing-panel")

    with pytest.raises(ValueError, match="unknown panel_id"):
        app.investigations.run_investigation(
            "case-missing-panel",
            {"tool_id": TOOL_ID_SILA_DENSE, "panel_ids": ["P404"]},
        )


def test_web_investigation_list_loads_result_payload(tmp_path, monkeypatch) -> None:
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    setup_case_workdir(app, "case-list-investigation")

    monkeypatch.setattr(
        "web.backend.veritas_web.investigations.detect_sila_dense",
        lambda panel_evidence, figure_evidence, **kwargs: {
            "schema_version": "1.0",
            "created_by": "fake",
            "status": "ran",
            "failure_category": None,
            "panel_count": len(panel_evidence),
            "relationship_count": 0,
            "relationships": [],
            "errors": [],
            "limitations": ["none"],
        },
    )
    app.investigations.run_investigation("case-list-investigation", {"panel_ids": ["P1"]})

    listing = app.investigations.list_investigations("case-list-investigation")

    assert len(listing["records"]) == 1
    assert len(listing["results"]) == 1
    assert listing["artifact_errors"] == []
    assert listing["results"][0]["result"]["status"] == "ran"


def test_web_investigation_db_write_failure_returns_partial_success(tmp_path, monkeypatch) -> None:
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    workdir = setup_case_workdir(app, "case-db-failure")

    monkeypatch.setattr(
        "web.backend.veritas_web.investigations.detect_sila_dense",
        lambda panel_evidence, figure_evidence, **kwargs: {
            "schema_version": "1.0",
            "created_by": "fake",
            "status": "ran",
            "failure_category": None,
            "panel_count": len(panel_evidence),
            "relationship_count": 0,
            "relationships": [],
            "errors": [],
            "limitations": [],
        },
    )

    class BrokenSession:
        def add(self, _model) -> None:
            pass

        def commit(self) -> None:
            raise RuntimeError("db commit failed")

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(app.store, "_session", lambda: BrokenSession())
    monkeypatch.setattr(app.investigations, "_require_workdir", lambda _case_id: workdir)

    result = app.investigations.run_investigation("case-db-failure", {"panel_ids": ["P1"]})

    assert result["result"]["status"] == "ran"
    assert "failed to persist investigation record" in result["db_sync_error"]
    records = read_investigation_records(workdir)
    assert len(records) == 1


def test_web_investigation_list_reports_missing_result_artifact(tmp_path, monkeypatch) -> None:
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    workdir = setup_case_workdir(app, "case-missing-artifact")

    monkeypatch.setattr(
        "web.backend.veritas_web.investigations.detect_sila_dense",
        lambda panel_evidence, figure_evidence, **kwargs: {
            "schema_version": "1.0",
            "created_by": "fake",
            "status": "ran",
            "failure_category": None,
            "panel_count": len(panel_evidence),
            "relationship_count": 0,
            "relationships": [],
            "errors": [],
            "limitations": [],
        },
    )
    result = app.investigations.run_investigation("case-missing-artifact", {"panel_ids": ["P1"]})
    (workdir / result["artifact"]).unlink()

    listing = app.investigations.list_investigations("case-missing-artifact")

    assert len(listing["records"]) == 1
    assert listing["results"] == []
    assert listing["artifact_errors"][0]["error"] == "artifact_missing"
    assert listing["records"][0]["artifact_errors"][0]["artifact"] == result["artifact"]


def test_web_investigation_list_reports_invalid_json_artifact(tmp_path, monkeypatch) -> None:
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    workdir = setup_case_workdir(app, "case-invalid-artifact")

    monkeypatch.setattr(
        "web.backend.veritas_web.investigations.detect_sila_dense",
        lambda panel_evidence, figure_evidence, **kwargs: {
            "schema_version": "1.0",
            "created_by": "fake",
            "status": "ran",
            "failure_category": None,
            "panel_count": len(panel_evidence),
            "relationship_count": 0,
            "relationships": [],
            "errors": [],
            "limitations": [],
        },
    )
    result = app.investigations.run_investigation("case-invalid-artifact", {"panel_ids": ["P1"]})
    (workdir / result["artifact"]).write_text("{bad json", encoding="utf-8")

    listing = app.investigations.list_investigations("case-invalid-artifact")

    assert listing["results"] == []
    assert listing["artifact_errors"][0]["error"] == "artifact_invalid_json"
