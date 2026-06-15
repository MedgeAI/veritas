"""Tests for visual web endpoints in VeritasWebApp."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from web.backend.veritas_web.app import VeritasRequestHandler, VeritasWebApp
from web.backend.veritas_web.auth import AuthContext


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def setup_case_with_visual_artifacts(app: VeritasWebApp, case_id: str) -> Path:
    """Create a case with visual artifacts and return the workdir."""
    case = app.store.create_case(case_id=case_id)
    run = app.store.create_run(case.case_id)
    workdir = Path(app.runner.output_root) / case_id / "research-integrity-audit"
    run.workdir = str(workdir)
    app.store.save_run(run)

    workdir.mkdir(parents=True, exist_ok=True)

    # Write visual artifacts
    write_json(
        workdir / "visual_evidence.json",
        {
            "version": "1.0",
            "figures": [
                {
                    "figure_id": "FE-0001",
                    "source_image_path": "images/Figure1.png",
                    "label": "Figure 1",
                    "caption": "Test figure",
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
        workdir / "panel_evidence.json",
        {
            "version": "1.0",
            "panels": [
                {
                    "panel_id": "PE-0001-01",
                    "parent_figure_id": "FE-0001",
                    "label": "a",
                    "bbox": [0, 0, 50, 100],
                    "crop_path": "panels/PE-0001-01.png",
                    "width": 50,
                    "height": 100,
                    "extraction_confidence": 0.85,
                    "extraction_method": "contour_edge_detection",
                }
            ],
        },
    )
    write_json(
        workdir / "image_relationships.json",
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
    write_json(
        workdir / "visual_findings.json",
        {
            "version": "1.0",
            "findings": [
                {
                    "finding_id": "VF-0001",
                    "category": "copy_move_single",
                    "risk_level": "high",
                    "summary": "Test visual finding",
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-02",
                    "relationship_id": "IR-0001",
                    "score": 0.85,
                }
            ],
        },
    )
    return workdir


def make_authenticated_handler(app: VeritasWebApp, path: str) -> VeritasRequestHandler:
    handler = VeritasRequestHandler.__new__(VeritasRequestHandler)
    handler.app = app
    handler.auth_context = AuthContext(user_id="operator", roles=frozenset({"admin"}))
    handler.path = path
    return handler


def test_visual_figures_endpoint(tmp_path) -> None:
    """GET /api/cases/{case_id}/visual/figures returns visual_evidence.json."""
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    setup_case_with_visual_artifacts(app, "visual-case-1")
    case_id = "visual-case-1"

    handler = make_authenticated_handler(app, f"/api/cases/{case_id}/visual/figures")
    captured: list[dict[str, Any]] = []
    handler._send_json = lambda payload, status=None: captured.append(payload)

    handler._route_get()

    assert len(captured) == 1
    data = captured[0]
    assert "figures" in data
    assert len(data["figures"]) == 1
    assert data["figures"][0]["figure_id"] == "FE-0001"


def test_visual_panels_endpoint(tmp_path) -> None:
    """GET /api/cases/{case_id}/visual/panels returns panel_evidence.json."""
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    setup_case_with_visual_artifacts(app, "visual-case-2")
    case_id = "visual-case-2"

    handler = make_authenticated_handler(app, f"/api/cases/{case_id}/visual/panels")
    captured: list[dict[str, Any]] = []
    handler._send_json = lambda payload, status=None: captured.append(payload)

    handler._route_get()

    assert len(captured) == 1
    data = captured[0]
    assert "panels" in data
    assert len(data["panels"]) == 1
    assert data["panels"][0]["panel_id"] == "PE-0001-01"


def test_visual_relationships_endpoint(tmp_path) -> None:
    """GET /api/cases/{case_id}/visual/relationships returns image_relationships.json."""
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    setup_case_with_visual_artifacts(app, "visual-case-3")
    case_id = "visual-case-3"

    handler = make_authenticated_handler(app, f"/api/cases/{case_id}/visual/relationships")
    captured: list[dict[str, Any]] = []
    handler._send_json = lambda payload, status=None: captured.append(payload)

    handler._route_get()

    assert len(captured) == 1
    data = captured[0]
    assert "relationships" in data
    assert len(data["relationships"]) == 1
    assert data["relationships"][0]["relationship_id"] == "IR-0001"


def test_visual_findings_endpoint(tmp_path) -> None:
    """GET /api/cases/{case_id}/visual/findings returns visual_findings.json."""
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    setup_case_with_visual_artifacts(app, "visual-case-4")
    case_id = "visual-case-4"

    handler = make_authenticated_handler(app, f"/api/cases/{case_id}/visual/findings")
    captured: list[dict[str, Any]] = []
    handler._send_json = lambda payload, status=None: captured.append(payload)

    handler._route_get()

    assert len(captured) == 1
    data = captured[0]
    assert "findings" in data
    assert len(data["findings"]) == 1
    assert data["findings"][0]["finding_id"] == "VF-0001"


def test_visual_unknown_type_returns_error(tmp_path) -> None:
    """GET /api/cases/{case_id}/visual/unknown returns error."""
    import pytest
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    setup_case_with_visual_artifacts(app, "visual-case-5")
    case_id = "visual-case-5"

    handler = make_authenticated_handler(app, f"/api/cases/{case_id}/visual/unknown")
    handler._send_json = lambda payload, status=None: None

    with pytest.raises(FileNotFoundError, match="unknown visual artifact type"):
        handler._route_get()


def test_visual_image_endpoint(tmp_path) -> None:
    """GET /api/cases/{case_id}/visual/images/{path} serves image files."""
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    workdir = setup_case_with_visual_artifacts(app, "visual-case-6")
    case_id = "visual-case-6"

    # Create a fake image file
    image_dir = workdir / "panels"
    image_dir.mkdir(parents=True, exist_ok=True)
    image_path = image_dir / "PE-0001-01.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake_image_data")

    handler = make_authenticated_handler(app, f"/api/cases/{case_id}/visual/images/panels/PE-0001-01.png")
    captured: list[tuple[bytes, str]] = []
    handler._send_bytes = lambda data, status=None, content_type="": captured.append((data, content_type))

    handler._route_get()

    assert len(captured) == 1
    data, content_type = captured[0]
    assert data == b"\x89PNG\r\n\x1a\nfake_image_data"
    assert "image/png" in content_type


def test_visual_image_prevents_path_traversal(tmp_path) -> None:
    """Image endpoint should prevent path traversal attacks."""
    import pytest
    app = VeritasWebApp(data_root=tmp_path / "web_data", output_root=tmp_path / "outputs")
    setup_case_with_visual_artifacts(app, "visual-case-7")
    case_id = "visual-case-7"

    # Attempt path traversal
    handler = make_authenticated_handler(app, f"/api/cases/{case_id}/visual/images/../../../etc/passwd")
    handler._send_bytes = lambda data, status=None, content_type="": None

    with pytest.raises(FileNotFoundError, match="image not found"):
        handler._route_get()


def test_visual_artifacts_in_known_artifacts(tmp_path) -> None:
    """Visual artifacts should be listed in the artifacts endpoint."""
    from web.backend.veritas_web.artifacts import KNOWN_ARTIFACTS

    artifact_ids = [a[0] for a in KNOWN_ARTIFACTS]
    assert "visual_evidence" in artifact_ids
    assert "panel_evidence" in artifact_ids
    assert "image_relationships" in artifact_ids
    assert "visual_findings" in artifact_ids
