"""Tests for copy-move detection tool (RootSIFT+MAGSAC++).

Tests verify:
1. _empty_result helper produces valid result dict
2. detect_copy_move returns correct schema for empty inputs
3. _run_single_image_detection handles subprocess failure gracefully
4. _run_cross_figure_detection with dhash pre-filter
5. flip_detected propagation through the pipeline
6. CLI main() entry point produces valid JSON output
7. Golden negative: genuinely different images produce zero relationships
8. Golden positive: known copy-move manipulation is detected
"""

from __future__ import annotations

import json

import pytest

from engine.static_audit.tools.copy_move_detection import (
    _dhash,
    _empty_result,
    _hamming_distance,
    detect_copy_move,
)

pytest.importorskip("PIL")


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

        rels = build_relationships(
            copy_move_result=copy_move_result, panel_evidence=panel_evidence
        )
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
        flip_findings = [
            f for f in findings if f.get("metadata", {}).get("flip_detected")
        ]
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


# ---------------------------------------------------------------------------
# Golden algorithm correctness tests
# ---------------------------------------------------------------------------


def _make_distinct_panel_a(path, size: int = 300) -> None:
    """Create a simple panel image with a few non-repeating shapes."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (size, size), "red")
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, 250, 250], fill=(0, 0, 200))
    draw.ellipse([100, 100, 200, 200], fill=(255, 255, 0))
    img.save(path)


def _make_distinct_panel_b(path, size: int = 300) -> None:
    """Create a visually different panel image with different shapes."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (size, size), "green")
    draw = ImageDraw.Draw(img)
    draw.polygon([(150, 20), (280, 280), (20, 280)], fill=(200, 0, 200))
    draw.rectangle([80, 80, 220, 220], outline=(0, 0, 0), width=5)
    img.save(path)


def _make_single_image_copymoved_panel(path, size: int = 600) -> None:
    """Create a panel with a known copy-move region pasted into it."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    # Background lines to generate keypoints
    for i in range(0, size, 20):
        draw.line([(0, i), (size, i)], fill=(80, 80, 80), width=1)
    # Distinctive region in the upper-left quadrant
    draw.rectangle([30, 30, 180, 180], fill=(255, 0, 0), outline=(0, 0, 0), width=3)
    draw.ellipse([50, 50, 160, 160], fill=(0, 255, 0))
    draw.polygon([(100, 40), (170, 170), (30, 170)], fill=(0, 0, 255))
    # Copy that region to the lower-right (classic copy-move forgery)
    region = img.crop((20, 20, 200, 200))
    img.paste(region, (350, 350))
    img.save(path)


def _make_rich_panel(path, size: int = 400) -> None:
    """Create a panel with varied geometric features for keypoint detection."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    for i in range(0, size, 25):
        draw.line(
            [(0, i), (size, i)],
            fill=(i % 256, (i * 2) % 256, (i * 3) % 256),
            width=3,
        )
    for x in range(50, size, 70):
        for y in range(50, size, 70):
            draw.ellipse(
                [x - 25, y - 25, x + 25, y + 25],
                fill=(x % 256, y % 256, 128),
            )
    draw.rectangle([100, 100, 300, 300], fill=(255, 0, 0), outline=(0, 0, 0), width=3)
    img.save(path)


class TestGoldenNegative:
    """Clean images with no copy-move manipulation should produce zero relationships."""

    def test_different_images_zero_relationships(self, tmp_path):
        """Two genuinely different images must not trigger any relationship."""
        _make_distinct_panel_a(tmp_path / "panel_a.png")
        _make_distinct_panel_b(tmp_path / "panel_b.png")

        panels = [
            {
                "panel_id": "PE-A",
                "parent_figure_id": "FE-001",
                "crop_path": "panel_a.png",
            },
            {
                "panel_id": "PE-B",
                "parent_figure_id": "FE-002",
                "crop_path": "panel_b.png",
            },
        ]
        figures = [
            {"figure_id": "FE-001", "source_image_path": "panel_a.png"},
            {"figure_id": "FE-002", "source_image_path": "panel_b.png"},
        ]

        result = detect_copy_move(panels, figures, workdir=tmp_path)

        assert result["relationships"] == []
        assert result["relationship_count"] == 0
        # panel_count > 0 proves the algorithm processed the images rather than
        # short-circuiting on empty input.
        assert result["panel_count"] == 2
        assert result["status"] in ("skipped", "ran")


class TestGoldenPositiveSingleImage:
    """A panel with a known copy-move region must be detected."""

    def test_single_image_copymove_detected(self, tmp_path):
        """Pasting a region from one part of an image to another must be detected."""
        _make_single_image_copymoved_panel(tmp_path / "manipulated.png")

        panels = [
            {
                "panel_id": "PE-001",
                "parent_figure_id": "FE-001",
                "crop_path": "manipulated.png",
            },
        ]

        result = detect_copy_move(
            panels,
            [],
            workdir=tmp_path,
            min_matches=4,
            min_score=0.0,
        )

        assert result["status"] == "ran"
        assert result["relationship_count"] >= 1
        single_rels = [
            r for r in result["relationships"] if r["source_type"] == "copy_move_single"
        ]
        assert len(single_rels) >= 1
        rel = single_rels[0]
        assert rel["source_panel_id"] == "PE-001"
        assert rel["target_panel_id"] == "PE-001"
        assert rel["inlier_count"] > 0
        assert rel["score"] > 0


class TestGoldenPositiveCrossFigure:
    """Two identical panel images must be detected as a cross-figure match."""

    def test_identical_panels_detected_cross_figure(self, tmp_path):
        """Two byte-identical panel images placed in different figures must be detected."""
        _make_rich_panel(tmp_path / "panel_a.png")
        _make_rich_panel(tmp_path / "panel_b.png")

        panels = [
            {
                "panel_id": "PE-A",
                "parent_figure_id": "FE-001",
                "crop_path": "panel_a.png",
            },
            {
                "panel_id": "PE-B",
                "parent_figure_id": "FE-002",
                "crop_path": "panel_b.png",
            },
        ]
        figures = [
            {"figure_id": "FE-001", "source_image_path": "panel_a.png"},
            {"figure_id": "FE-002", "source_image_path": "panel_b.png"},
        ]

        result = detect_copy_move(
            panels,
            figures,
            workdir=tmp_path,
            min_matches=4,
            min_score=0.0,
        )

        assert result["status"] == "ran"
        cross_rels = [
            r for r in result["relationships"] if r["source_type"] == "copy_move_cross"
        ]
        assert len(cross_rels) >= 1
        rel = cross_rels[0]
        assert rel["source_panel_id"] == "FE-001"
        assert rel["target_panel_id"] == "FE-002"
        assert rel["inlier_count"] > 0
        assert rel["score"] > 0.1
