"""Tests for visual web endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.helpers.asgi_client import LocalASGITestClient as TestClient
from web.backend.veritas_web.app import create_app


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def setup_case_with_visual_artifacts(tmp_path: Path, case_id: str) -> tuple[TestClient, Path]:
    """Create a case with visual artifacts and return (client, workdir)."""
    app = create_app(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    client = TestClient(app, raise_server_exceptions=False)

    # Create case and run
    resp = client.post("/api/cases", json={"case_id": case_id, "paper_title": "Test"})
    assert resp.status_code == 201

    deps = app.state.dependencies
    run = deps.store.create_run(case_id)
    workdir = Path(deps.runner.output_root) / case_id / "research-integrity-audit"
    run.workdir = str(workdir)
    deps.store.save_run(run)
    workdir.mkdir(parents=True, exist_ok=True)

    # Write visual artifacts
    write_json(workdir / "visual_evidence.json", {
        "version": "1.0",
        "figures": [{
            "figure_id": "FE-0001", "source_image_path": "images/Figure1.png",
            "label": "Figure 1", "caption": "Test figure", "page_number": 1,
            "bbox": None, "width": 100, "height": 100, "panel_count": 2,
        }],
    })
    write_json(workdir / "panel_evidence.json", {
        "version": "1.0",
        "panels": [{
            "panel_id": "PE-0001-01", "parent_figure_id": "FE-0001", "label": "a",
            "bbox": [0, 0, 50, 100], "crop_path": "panels/PE-0001-01.png",
            "width": 50, "height": 100, "extraction_confidence": 0.85,
            "extraction_method": "contour_edge_detection",
        }],
    })
    write_json(workdir / "image_relationships.json", {
        "version": "1.0",
        "relationships": [{
            "relationship_id": "IR-0001", "source_type": "copy_move_single",
            "source_panel_id": "PE-0001-01", "target_panel_id": "PE-0001-02",
            "score": 0.85, "match_method": "orb_ransac", "inlier_count": 42,
        }],
    })
    write_json(workdir / "visual_findings.json", {
        "version": "1.0",
        "findings": [{
            "finding_id": "VF-0001", "category": "copy_move_single",
            "risk_level": "high", "summary": "Test visual finding",
            "source_panel_id": "PE-0001-01", "target_panel_id": "PE-0001-02",
            "relationship_id": "IR-0001", "score": 0.85,
        }],
    })
    return client, workdir


def test_visual_figures_endpoint(tmp_path: Path) -> None:
    client, _ = setup_case_with_visual_artifacts(tmp_path, "visual-case-1")
    resp = client.get("/api/cases/visual-case-1/visual/figures")
    assert resp.status_code == 200
    data = resp.json()
    assert "figures" in data
    assert len(data["figures"]) == 1
    assert data["figures"][0]["figure_id"] == "FE-0001"


def test_visual_panels_endpoint(tmp_path: Path) -> None:
    client, _ = setup_case_with_visual_artifacts(tmp_path, "visual-case-2")
    resp = client.get("/api/cases/visual-case-2/visual/panels")
    assert resp.status_code == 200
    data = resp.json()
    assert "panels" in data
    assert len(data["panels"]) == 1
    assert data["panels"][0]["panel_id"] == "PE-0001-01"


def test_visual_relationships_endpoint(tmp_path: Path) -> None:
    client, _ = setup_case_with_visual_artifacts(tmp_path, "visual-case-3")
    resp = client.get("/api/cases/visual-case-3/visual/relationships")
    assert resp.status_code == 200
    data = resp.json()
    assert "relationships" in data
    assert len(data["relationships"]) == 1
    assert data["relationships"][0]["relationship_id"] == "IR-0001"


def test_visual_findings_endpoint(tmp_path: Path) -> None:
    client, _ = setup_case_with_visual_artifacts(tmp_path, "visual-case-4")
    resp = client.get("/api/cases/visual-case-4/visual/findings")
    assert resp.status_code == 200
    data = resp.json()
    assert "findings" in data
    assert len(data["findings"]) == 1
    assert data["findings"][0]["finding_id"] == "VF-0001"


def test_visual_unknown_type_returns_error(tmp_path: Path) -> None:
    client, _ = setup_case_with_visual_artifacts(tmp_path, "visual-case-5")
    resp = client.get("/api/cases/visual-case-5/visual/unknown")
    assert resp.status_code == 404


def test_visual_image_endpoint(tmp_path: Path) -> None:
    client, workdir = setup_case_with_visual_artifacts(tmp_path, "visual-case-6")
    image_dir = workdir / "panels"
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / "PE-0001-01.png").write_bytes(b"\x89PNG\r\n\x1a\nfake_image_data")

    resp = client.get("/api/cases/visual-case-6/visual/images/panels/PE-0001-01.png")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG\r\n\x1a\nfake_image_data"
    assert "image/png" in resp.headers.get("content-type", "")


def test_visual_image_prevents_path_traversal(tmp_path: Path) -> None:
    """Image endpoint should prevent path traversal attacks.

    Note: httpx (used by TestClient) normalizes URL paths, so ``../``
    sequences are resolved before reaching the server.  We test the
    server-side protection directly via ArtifactService.
    """
    from web.backend.veritas_web.artifacts import ArtifactService
    from web.backend.veritas_web.case_store import CaseStore

    store = CaseStore(tmp_path / "web_data")
    store.create_case(case_id="traversal-case")
    artifacts = ArtifactService(store)

    # Attempt path traversal — should return None
    result = artifacts.visual_image_path("traversal-case", "../../../etc/passwd")
    assert result is None


def test_visual_artifacts_in_known_artifacts() -> None:
    from web.backend.veritas_web.artifacts import KNOWN_ARTIFACTS
    artifact_ids = [a[0] for a in KNOWN_ARTIFACTS]
    assert "visual_evidence" in artifact_ids
    assert "panel_evidence" in artifact_ids
    assert "image_relationships" in artifact_ids
    assert "visual_findings" in artifact_ids
