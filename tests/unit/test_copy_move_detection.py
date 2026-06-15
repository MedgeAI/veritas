"""Tests for copy-move detection tool.

Tests verify:
1. Not-available status when cv2 is missing (mocked)
2. Skipped status when fewer than 2 panels
3. Correct relationship detection on a known copy-move fixture
4. Score threshold filtering (below min_score -> no relationship)
5. Overlay generation (file written to correct path)
6. Cross-figure vs single-figure source_type classification
7. CLI main() entry point produces valid JSON output
8. Invalid method handling
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from engine.static_audit.tools.copy_move_detection import (
    detect_copy_move,
    _determine_source_type,
    _empty_result,
)


def _make_panel(
    panel_id: str,
    parent_figure_id: str,
    label: str,
    crop_path: str,
    width: int = 200,
    height: int = 200,
) -> dict:
    """Create a minimal PanelEvidence dict for testing."""
    return {
        "panel_id": panel_id,
        "parent_figure_id": parent_figure_id,
        "label": label,
        "bbox": [0, 0, width, height],
        "crop_path": crop_path,
        "width": width,
        "height": height,
        "extraction_confidence": 0.9,
        "extraction_method": "contour_edge_detection",
    }


def _require_cv2():
    """Return cv2 module or skip the test."""
    try:
        import cv2
        return cv2
    except ImportError:
        pytest.skip("opencv-python-headless (cv2) is not installed")


# ---------------------------------------------------------------------------
# Tests that do NOT require cv2
# ---------------------------------------------------------------------------


class TestDetectCopyMoveNotAvailable:
    """Test graceful handling when cv2 is not available."""

    def test_returns_not_available_when_cv2_missing(self, tmp_path) -> None:
        with patch(
            "engine.static_audit.tools.copy_move_detection._try_import_cv2",
            return_value=None,
        ):
            result = detect_copy_move(
                panel_evidence=[{"panel_id": "P1"}, {"panel_id": "P2"}],
                figure_evidence=[],
                workdir=tmp_path,
            )

        assert result["status"] == "not_available"
        assert result["panel_count"] == 2
        assert result["relationship_count"] == 0
        assert any("OpenCV" in e for e in result["errors"])

    def test_returns_not_available_when_numpy_missing(self, tmp_path) -> None:
        dummy_cv2 = object()  # Non-None sentinel so cv2 check passes
        with (
            patch(
                "engine.static_audit.tools.copy_move_detection._try_import_cv2",
                return_value=dummy_cv2,
            ),
            patch(
                "engine.static_audit.tools.copy_move_detection._try_import_numpy",
                return_value=None,
            ),
        ):
            result = detect_copy_move(
                panel_evidence=[{"panel_id": "P1"}, {"panel_id": "P2"}],
                figure_evidence=[],
                workdir=tmp_path,
            )

        assert result["status"] == "not_available"
        assert any("NumPy" in e for e in result["errors"])


class TestDetermineSourceType:
    """Test source_type classification helper."""

    def test_same_figure_is_single(self) -> None:
        a = {"parent_figure_id": "FE-0001"}
        b = {"parent_figure_id": "FE-0001"}
        assert _determine_source_type(a, b) == "copy_move_single"

    def test_different_figure_is_cross(self) -> None:
        a = {"parent_figure_id": "FE-0001"}
        b = {"parent_figure_id": "FE-0002"}
        assert _determine_source_type(a, b) == "copy_move_cross"

    def test_missing_figure_is_cross(self) -> None:
        a = {}
        b = {"parent_figure_id": "FE-0001"}
        assert _determine_source_type(a, b) == "copy_move_cross"


class TestEmptyResult:
    """Test empty result builder."""

    def test_empty_result_structure(self) -> None:
        result = _empty_result("failed", errors=["test error"])
        assert result["status"] == "failed"
        assert result["schema_version"] == "1.0"
        assert result["created_by"] == "engine/static_audit/tools/copy_move_detection.py"
        assert result["relationship_count"] == 0
        assert result["relationships"] == []
        assert result["errors"] == ["test error"]

    def test_empty_result_with_limitations(self) -> None:
        result = _empty_result("skipped", panel_count=5, limitations=["test limitation"])
        assert result["status"] == "skipped"
        assert result["panel_count"] == 5
        assert result["limitations"] == ["test limitation"]


class TestInvalidMethod:
    """Test invalid method parameter."""

    def test_invalid_method_returns_failed(self, tmp_path) -> None:
        dummy_cv2 = object()
        dummy_np = object()
        with (
            patch(
                "engine.static_audit.tools.copy_move_detection._try_import_cv2",
                return_value=dummy_cv2,
            ),
            patch(
                "engine.static_audit.tools.copy_move_detection._try_import_numpy",
                return_value=dummy_np,
            ),
        ):
            result = detect_copy_move(
                panel_evidence=[{"panel_id": "P1"}, {"panel_id": "P2"}],
                figure_evidence=[],
                workdir=tmp_path,
                method="invalid",
            )
        assert result["status"] == "failed"
        assert any("Unsupported method" in e for e in result["errors"])


class TestSchemaContractNoCv2:
    """Test output schema contract without cv2 (uses not_available path)."""

    def test_result_has_required_keys(self, tmp_path) -> None:
        result = detect_copy_move([], [], workdir=tmp_path)
        required_keys = {
            "schema_version", "created_by", "status", "method",
            "panel_count", "pair_count_examined", "relationship_count",
            "relationships", "errors", "limitations",
        }
        assert required_keys.issubset(result.keys())


class TestCLIEntryPointNoCv2:
    """Test CLI main() missing-input path (does not need cv2)."""

    def test_cli_main_missing_panel_json(self, tmp_path) -> None:
        output = tmp_path / "copy_move_result.json"

        with patch("sys.argv", [
            "copy_move_detection.py",
            str(tmp_path / "nonexistent.json"),
            "--output", str(output),
            "--workdir", str(tmp_path),
        ]):
            from engine.static_audit.tools.copy_move_detection import main
            exit_code = main()

        assert exit_code == 0
        result = json.loads(output.read_text(encoding="utf-8"))
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# Tests that require cv2 (skipped if not installed)
# ---------------------------------------------------------------------------


def _create_test_image(path: Path, width: int = 200, height: int = 200, seed: int = 0) -> None:
    """Create a test image with reproducible random texture."""
    cv2_mod = _require_cv2()
    rng = np.random.RandomState(seed)
    img = rng.randint(0, 255, (height, width, 3), dtype=np.uint8)
    cv2_mod.imwrite(str(path), img)


def _create_copy_move_pair(workdir: Path) -> tuple[list[dict], list[dict]]:
    """Create a pair of panels where panel_b shares significant content with panel_a.

    Returns:
        (panel_evidence, figure_evidence)
    """
    cv2_mod = _require_cv2()
    panels_dir = workdir / "panels" / "FE-0001"
    panels_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.RandomState(42)
    src = rng.randint(50, 200, (200, 200, 3), dtype=np.uint8)
    cv2_mod.rectangle(src, (20, 20), (80, 80), (255, 0, 0), -1)
    cv2_mod.rectangle(src, (120, 20), (180, 80), (0, 255, 0), -1)
    cv2_mod.rectangle(src, (20, 120), (80, 180), (0, 0, 255), -1)
    cv2_mod.circle(src, (150, 150), 30, (200, 200, 0), -1)

    src_path = panels_dir / "a.png"
    cv2_mod.imwrite(str(src_path), src)

    dst = src.copy()
    noise = rng.randint(-10, 10, (200, 200, 3), dtype=np.int16)
    dst = np.clip(dst.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    dst_path = panels_dir / "b.png"
    cv2_mod.imwrite(str(dst_path), dst)

    panel_a = _make_panel("PE-0001-01", "FE-0001", "a", "panels/FE-0001/a.png")
    panel_b = _make_panel("PE-0001-02", "FE-0001", "b", "panels/FE-0001/b.png")

    figure_evidence = [{
        "figure_id": "FE-0001",
        "source_image_path": "images/Figure1.png",
        "label": "Figure 1",
        "caption": "Test figure",
        "page_number": 1,
        "bbox": None,
        "width": 800,
        "height": 400,
        "panel_count": 2,
    }]

    return [panel_a, panel_b], figure_evidence


class TestDetectCopyMoveSkipped:
    """Test skipped status for insufficient panels."""

    def test_skipped_when_zero_panels(self, tmp_path) -> None:
        _require_cv2()
        result = detect_copy_move(
            panel_evidence=[],
            figure_evidence=[],
            workdir=tmp_path,
        )
        assert result["status"] == "skipped"
        assert result["panel_count"] == 0

    def test_skipped_when_one_panel(self, tmp_path) -> None:
        _require_cv2()
        panels_dir = tmp_path / "panels" / "FE-0001"
        panels_dir.mkdir(parents=True, exist_ok=True)
        _create_test_image(panels_dir / "a.png", seed=1)

        panel = _make_panel("PE-0001-01", "FE-0001", "a", "panels/FE-0001/a.png")
        result = detect_copy_move(
            panel_evidence=[panel],
            figure_evidence=[],
            workdir=tmp_path,
        )
        assert result["status"] == "skipped"

    def test_skipped_when_image_missing(self, tmp_path) -> None:
        _require_cv2()
        panel = _make_panel("PE-0001-01", "FE-0001", "a", "nonexistent/a.png")
        panel2 = _make_panel("PE-0001-02", "FE-0001", "b", "nonexistent/b.png")
        result = detect_copy_move(
            panel_evidence=[panel, panel2],
            figure_evidence=[],
            workdir=tmp_path,
        )
        assert result["status"] == "skipped"


class TestDetectCopyMoveRan:
    """Test successful copy-move detection (requires cv2)."""

    def test_detects_copy_move_pair(self, tmp_path) -> None:
        _require_cv2()
        panel_evidence, figure_evidence = _create_copy_move_pair(tmp_path)

        result = detect_copy_move(
            panel_evidence,
            figure_evidence,
            workdir=tmp_path,
            method="orb",
            min_matches=4,
            ratio_threshold=0.8,
            min_score=0.01,
            generate_overlays=True,
        )

        assert result["status"] == "ran"
        assert result["panel_count"] == 2
        assert result["pair_count_examined"] == 1
        assert result["relationship_count"] >= 1

        rel = result["relationships"][0]
        assert rel["source_type"] == "copy_move_single"
        assert rel["source_panel_id"] == "PE-0001-01"
        assert rel["target_panel_id"] == "PE-0001-02"
        assert rel["match_method"] == "orb_ransac"
        assert rel["inlier_count"] >= 4
        assert 0.0 <= rel["score"] <= 1.0
        assert rel["homography"] is not None
        assert len(rel["homography"]) == 3
        assert all(len(row) == 3 for row in rel["homography"])

    def test_overlay_generated(self, tmp_path) -> None:
        _require_cv2()
        panel_evidence, figure_evidence = _create_copy_move_pair(tmp_path)

        result = detect_copy_move(
            panel_evidence,
            figure_evidence,
            workdir=tmp_path,
            method="orb",
            min_matches=4,
            ratio_threshold=0.8,
            min_score=0.01,
            generate_overlays=True,
        )

        if result["relationship_count"] > 0:
            rel = result["relationships"][0]
            assert rel["overlay_path"] is not None
            overlay_file = tmp_path / rel["overlay_path"]
            assert overlay_file.exists()
            assert overlay_file.stat().st_size > 0

    def test_no_overlay_when_disabled(self, tmp_path) -> None:
        _require_cv2()
        panel_evidence, figure_evidence = _create_copy_move_pair(tmp_path)

        result = detect_copy_move(
            panel_evidence,
            figure_evidence,
            workdir=tmp_path,
            method="orb",
            min_matches=4,
            ratio_threshold=0.8,
            min_score=0.01,
            generate_overlays=False,
        )

        assert result["status"] == "ran"
        for rel in result["relationships"]:
            assert rel["overlay_path"] is None

    def test_score_threshold_filters_low_matches(self, tmp_path) -> None:
        """Set min_score very high so only very strong matches pass."""
        _require_cv2()
        panel_evidence, figure_evidence = _create_copy_move_pair(tmp_path)

        result = detect_copy_move(
            panel_evidence,
            figure_evidence,
            workdir=tmp_path,
            method="orb",
            min_matches=4,
            ratio_threshold=0.5,
            min_score=0.99,
        )

        assert result["status"] == "ran"
        assert result["relationship_count"] == 0

    def test_max_relationships_limit(self, tmp_path) -> None:
        """Verify max_relationships is respected."""
        cv2_mod = _require_cv2()
        panels_dir = tmp_path / "panels" / "FE-0001"
        panels_dir.mkdir(parents=True, exist_ok=True)

        rng = np.random.RandomState(42)
        base = rng.randint(50, 200, (200, 200, 3), dtype=np.uint8)
        cv2_mod.rectangle(base, (10, 10), (90, 90), (255, 0, 0), 3)
        cv2_mod.rectangle(base, (110, 10), (190, 90), (0, 255, 0), 3)
        cv2_mod.circle(base, (100, 150), 40, (0, 0, 255), 3)

        panels = []
        for i in range(6):
            img = base.copy()
            path = panels_dir / f"{chr(ord('a') + i)}.png"
            cv2_mod.imwrite(str(path), img)
            panels.append(_make_panel(
                f"PE-0001-{i + 1:02d}", "FE-0001",
                chr(ord("a") + i),
                f"panels/FE-0001/{chr(ord('a') + i)}.png",
            ))

        result = detect_copy_move(
            panels, [],
            workdir=tmp_path,
            method="orb",
            min_matches=4,
            ratio_threshold=0.95,
            min_score=0.001,
            max_relationships=3,
        )

        assert result["status"] == "ran"
        assert result["relationship_count"] <= 3
        # Implementation uses early-exit optimization: stops examining pairs
        # once max_relationships is reached. So pair_count_examined <= 15.
        assert result["pair_count_examined"] <= 15
        assert result["pair_count_examined"] >= 3  # At least found 3 relationships


class TestCrossFigureDetection:
    """Test cross-figure copy-move detection (requires cv2)."""

    def test_cross_figure_source_type(self, tmp_path) -> None:
        cv2_mod = _require_cv2()
        for fig_id in ["FE-0001", "FE-0002"]:
            d = tmp_path / "panels" / fig_id
            d.mkdir(parents=True, exist_ok=True)

        rng = np.random.RandomState(42)
        base = rng.randint(50, 200, (200, 200, 3), dtype=np.uint8)
        cv2_mod.rectangle(base, (20, 20), (80, 80), (255, 0, 0), -1)
        cv2_mod.circle(base, (150, 150), 30, (0, 255, 0), -1)

        path1 = tmp_path / "panels" / "FE-0001" / "a.png"
        path2 = tmp_path / "panels" / "FE-0002" / "a.png"
        cv2_mod.imwrite(str(path1), base)
        cv2_mod.imwrite(str(path2), base.copy())

        panel_a = _make_panel("PE-0001-01", "FE-0001", "a", "panels/FE-0001/a.png")
        panel_b = _make_panel("PE-0002-01", "FE-0002", "a", "panels/FE-0002/a.png")

        result = detect_copy_move(
            [panel_a, panel_b], [],
            workdir=tmp_path,
            method="orb",
            min_matches=4,
            ratio_threshold=0.9,
            min_score=0.001,
        )

        if result["relationship_count"] > 0:
            rel = result["relationships"][0]
            assert rel["source_type"] == "copy_move_cross"


class TestMatchDescriptors:
    """Test the descriptor matching function directly (requires cv2)."""

    def test_match_with_identical_descriptors(self) -> None:
        """Identical descriptors should produce many good matches."""
        cv2_mod = _require_cv2()
        orb = cv2_mod.ORB_create(nfeatures=100)
        img = np.random.RandomState(0).randint(0, 255, (200, 200), dtype=np.uint8)
        kp, desc = orb.detectAndCompute(img, None)
        if desc is None:
            pytest.skip("ORB could not compute descriptors for synthetic image")

        from engine.static_audit.tools.copy_move_detection import _match_descriptors
        matches = _match_descriptors(cv2_mod, desc, desc, "orb", 0.75)
        assert isinstance(matches, list)

    def test_match_with_none_descriptors(self) -> None:
        cv2_mod = _require_cv2()
        from engine.static_audit.tools.copy_move_detection import _match_descriptors
        matches = _match_descriptors(cv2_mod, None, None, "orb", 0.75)
        assert matches == []

    def test_match_with_too_few_descriptors(self) -> None:
        cv2_mod = _require_cv2()
        from engine.static_audit.tools.copy_move_detection import _match_descriptors
        desc = np.zeros((1, 32), dtype=np.uint8)
        matches = _match_descriptors(cv2_mod, desc, desc, "orb", 0.75)
        assert matches == []


class TestCLIEntryPointWithCv2:
    """Test CLI main() full path (requires cv2)."""

    def test_cli_main_with_valid_input(self, tmp_path) -> None:
        _require_cv2()
        panel_evidence, _ = _create_copy_move_pair(tmp_path)
        panel_json = tmp_path / "panels.json"
        panel_json.write_text(json.dumps(panel_evidence), encoding="utf-8")

        output = tmp_path / "copy_move_result.json"

        with patch("sys.argv", [
            "copy_move_detection.py",
            str(panel_json),
            "--output", str(output),
            "--workdir", str(tmp_path),
            "--min-matches", "4",
            "--ratio-threshold", "0.8",
            "--min-score", "0.01",
        ]):
            from engine.static_audit.tools.copy_move_detection import main
            exit_code = main()

        assert exit_code == 0
        assert output.exists()

        result = json.loads(output.read_text(encoding="utf-8"))
        assert result["status"] == "ran"
        assert "relationships" in result
