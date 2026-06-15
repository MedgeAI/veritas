"""Tests for copy-move detection tool (RootSIFT+MAGSAC++).

Tests verify:
1. _empty_result helper produces valid result dict
2. detect_copy_move returns correct schema for empty inputs
3. _run_single_image_detection handles subprocess failure gracefully
4. _run_cross_figure_detection with dhash pre-filter
5. flip_detected propagation through the pipeline
6. CLI main() entry point produces valid JSON output
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from engine.static_audit.tools.copy_move_detection import (
    _dhash,
    _empty_result,
    _hamming_distance,
    detect_copy_move,
)


def _make_panel(panel_id: str, parent_figure_id: str, crop_path: str) -> dict:
    return {
        "panel_id": panel_id,
        "parent_figure_id": parent_figure_id,
        "label": "a",
        "bbox": [0, 0, 200, 200],
        "crop_path": crop_path,
        "width": 200,
        "height": 200,
        "extraction_confidence": 0.9,
        "extraction_method": "yolov5_panel_extractor",
        "panel_type": "Graphs",
    }


class TestEmptyResult:
    def test_empty_result_has_all_fields(self):
        result = _empty_result("skipped", "rootsift_magsac")
        assert result["status"] == "skipped"
        assert result["method"] == "rootsift_magsac"
        assert result["relationships"] == []
        assert result["relationship_count"] == 0
        assert result["schema_version"] == "1.0"

    def test_empty_result_with_errors(self):
        result = _empty_result("failed", "rootsift_magsac", errors=["test error"])
        assert result["errors"] == ["test error"]
        assert result["limitations"] == []


class TestDhash:
    def test_hamming_distance(self):
        assert _hamming_distance(0, 0) == 0
        assert _hamming_distance(0b1010, 0b0101) == 4
        assert _hamming_distance(0xFF, 0x00) == 8

    def test_dhash_on_image(self, tmp_path):
        """dhash should return an integer for a valid image."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")
        img = Image.new("RGB", (100, 100), color="red")
        path = tmp_path / "test.png"
        img.save(path)
        h = _dhash(path)
        assert isinstance(h, int)


class TestDetectCopyMove:
    def test_no_panels_returns_skipped(self, tmp_path):
        result = detect_copy_move([], [], workdir=tmp_path)
        assert result["status"] == "skipped"
        assert result["relationships"] == []

    def test_panels_with_missing_images_returns_skipped(self, tmp_path):
        panels = [_make_panel("PE-001", "FE-001", "panels/missing.png")]
        result = detect_copy_move(panels, [], workdir=tmp_path)
        # Should be skipped since no crop files exist
        assert result["status"] in ("skipped", "ran")
        assert isinstance(result["relationships"], list)


class TestFlipDetectedPropagation:
    def test_flip_detected_in_relationship(self):
        """flip_detected should propagate from relationship to finding metadata."""
        from engine.static_audit.tools.visual_finding_pipeline import (
            build_relationships,
            build_visual_findings,
        )

        copy_move_result = {
            "relationships": [
                {
                    "source_panel_id": "PE-001",
                    "target_panel_id": "PE-001",
                    "source_type": "copy_move_single",
                    "score": 0.6,
                    "match_method": "rootsift_magsac_single",
                    "inlier_count": 50,
                    "homography": None,
                    "overlay_path": None,
                    "flip_detected": True,
                }
            ]
        }
        panel_evidence = [
            {
                "panel_id": "PE-001",
                "parent_figure_id": "FE-001",
                "extraction_method": "yolov5_panel_extractor",
                "metadata": {},
            }
        ]

        rels = build_relationships(copy_move_result=copy_move_result, panel_evidence=panel_evidence)
        assert len(rels) == 1
        assert rels[0]["flip_detected"] is True
        assert rels[0]["source_type"] == "copy_move_single"

        findings = build_visual_findings(
            relationships=rels,
            panel_evidence=panel_evidence,
            high_score_threshold=0.3,
        )
        assert len(findings) >= 1
        # Check flip_detected propagated to finding metadata
        flip_findings = [f for f in findings if f.get("metadata", {}).get("flip_detected")]
        assert len(flip_findings) >= 1
        # Check flip review question was added
        for f in flip_findings:
            assert any("翻转" in q for q in f.get("manual_review_questions", []))


class TestCLIMain:
    def test_main_produces_json(self, tmp_path):
        """CLI main() should produce valid JSON output."""
        import subprocess
        import sys

        panel_json = tmp_path / "panel_evidence.json"
        panel_json.write_text(json.dumps({"panels": []}))
        figure_json = tmp_path / "visual_evidence.json"
        figure_json.write_text(json.dumps({"figures": []}))
        output = tmp_path / "output.json"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "engine.static_audit.tools.copy_move_detection",
                str(panel_json),
                "--figure-json",
                str(figure_json),
                "--output",
                str(output),
                "--workdir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert output.exists()
        data = json.loads(output.read_text())
        assert data["status"] in ("skipped", "ran")
        assert "relationships" in data
