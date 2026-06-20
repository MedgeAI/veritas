"""Tests for the visual.overlap_reuse detection tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.static_audit.tools.overlap_reuse import (
    _compute_overlap_polygon,
    _dhash_image,
    _generate_tiles,
    _hamming_distance,
    _is_valid_panel,
    _merge_to_panel_pairs,
    _polygon_area,
    detect_overlap_reuse,
)
from engine.tools.registry import TOOLS, TOOL_ID_OVERLAP_REUSE

FIXTURES_DIR = Path("tests/fixtures/visual")


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestOverlapReuseRegistry:
    def test_tool_registered(self):
        assert TOOL_ID_OVERLAP_REUSE in TOOLS

    def test_tool_definition_fields(self):
        tool = TOOLS[TOOL_ID_OVERLAP_REUSE]
        assert tool.tool_id == "visual.overlap_reuse"
        assert tool.step_key == "visual_overlap_reuse"
        assert tool.output_artifacts == ("visual/overlap_reuse.json",)

    def test_tool_not_in_mandatory_baseline(self):
        from engine.tools.registry import (
            PAPER_STATIC_AUDIT_TOOL_IDS,
            STATIC_AUDIT_V1_TOOL_IDS,
        )

        assert TOOL_ID_OVERLAP_REUSE not in PAPER_STATIC_AUDIT_TOOL_IDS
        assert TOOL_ID_OVERLAP_REUSE not in STATIC_AUDIT_V1_TOOL_IDS


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_is_valid_panel_skips_whole_figure_fallback(self):
        assert _is_valid_panel({"panel_id": "p1"}) is True
        assert _is_valid_panel({"panel_id": "p1", "metadata": {}}) is True
        assert (
            _is_valid_panel(
                {
                    "panel_id": "p1",
                    "metadata": {"extraction_method": "whole_figure_fallback"},
                }
            )
            is False
        )

    def test_dhash_image_deterministic(self):
        from PIL import Image

        img = Image.new("RGB", (64, 64), (100, 150, 200))
        h1 = _dhash_image(img)
        h2 = _dhash_image(img)
        assert h1 == h2

    def test_hamming_distance(self):
        assert _hamming_distance(0, 0) == 0
        assert _hamming_distance(0, 1) == 1
        assert _hamming_distance(0xFF, 0x00) == 8

    def test_generate_tiles_count(self):
        from PIL import Image
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "panel.png"
            Image.new("RGB", (300, 240), (100, 150, 200)).save(img_path)
            tiles = _generate_tiles("p1", img_path, tile_size=64, tile_stride=32)
            assert len(tiles) > 0
            for t in tiles:
                assert "tile_id" in t
                assert "bbox" in t
                assert "dhash" in t
                assert len(t["bbox"]) == 4

    def test_generate_tiles_skips_small_images(self):
        from PIL import Image
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "small.png"
            Image.new("RGB", (32, 32), (100, 150, 200)).save(img_path)
            tiles = _generate_tiles("p1", img_path, tile_size=64, tile_stride=32)
            assert len(tiles) == 0

    def test_merge_to_panel_pairs(self):
        tile_a1 = {
            "tile_id": "a_t1",
            "panel_id": "a",
            "dhash": 100,
            "bbox": [0, 0, 64, 64],
        }
        tile_a2 = {
            "tile_id": "a_t2",
            "panel_id": "a",
            "dhash": 200,
            "bbox": [64, 0, 128, 64],
        }
        tile_b1 = {
            "tile_id": "b_t1",
            "panel_id": "b",
            "dhash": 101,
            "bbox": [0, 0, 64, 64],
        }
        cands = [
            {"tile_a": tile_a1, "tile_b": tile_b1, "distance": 2},
            {"tile_a": tile_a2, "tile_b": tile_b1, "distance": 5},
        ]
        pairs = _merge_to_panel_pairs(cands)
        assert len(pairs) == 1
        assert pairs[0]["source_panel_id"] == "a"
        assert pairs[0]["target_panel_id"] == "b"
        assert pairs[0]["tile_candidate_count"] == 2


# ---------------------------------------------------------------------------
# Overlap polygon computation
# ---------------------------------------------------------------------------


class TestOverlapPolygon:
    def test_polygon_area_square(self):
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        assert _polygon_area(square) == pytest.approx(100.0)

    def test_overlap_identical_panels(self):
        result = _compute_overlap_polygon(
            100, 100, 100, 100, [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        )
        assert result is not None
        src_ratio, tgt_ratio = result
        assert src_ratio == pytest.approx(1.0, abs=0.01)
        assert tgt_ratio == pytest.approx(1.0, abs=0.01)

    def test_overlap_no_homography(self):
        assert _compute_overlap_polygon(100, 100, 100, 100, None) is None
        assert _compute_overlap_polygon(100, 100, 100, 100, []) is None


# ---------------------------------------------------------------------------
# Fixture-based tests
# ---------------------------------------------------------------------------


class TestDetectOverlapReuse:
    def test_empty_panel_list(self):
        result = detect_overlap_reuse([], [], workdir=Path("/nonexistent"))
        assert result["status"] == "skipped"
        assert result["panel_count"] == 0

    def test_single_panel_skipped(self):
        result = detect_overlap_reuse(
            [{"panel_id": "p1", "crop_path": "x.png"}],
            [],
            workdir=Path("/nonexistent"),
        )
        assert result["status"] == "skipped"

    def test_positive_fixture_runs(self, tmp_path):
        """Crop fixture should produce tile candidates (even if ELIS can't verify)."""
        fixture = FIXTURES_DIR / "synthetic_overlap_crop"
        panels = [
            {"panel_id": "panel_a", "crop_path": "images/panel_a.png"},
            {"panel_id": "panel_b", "crop_path": "images/panel_b.png"},
        ]
        result = detect_overlap_reuse(
            panels, [], workdir=fixture, tile_size=64, tile_stride=32, min_inliers=4
        )
        assert result["status"] == "ran"
        assert result["panel_count"] == 2
        assert result["tile_count"] > 0
        assert result["candidate_pair_count"] > 0

    def test_negative_similar_fixture_no_high_risk(self):
        """Negative similar fixture should not produce high-risk findings."""
        fixture = FIXTURES_DIR / "synthetic_overlap_negative_similar"
        panels = [
            {"panel_id": "panel_a", "crop_path": "images/panel_a.png"},
            {"panel_id": "panel_b", "crop_path": "images/panel_b.png"},
        ]
        result = detect_overlap_reuse(
            panels, [], workdir=fixture, tile_size=64, tile_stride=32, min_inliers=4
        )
        for rel in result.get("relationships", []):
            assert rel["score"] < 0.4, (
                "Negative fixture should not produce high-score relationships"
            )


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    def test_overlap_relationship_loaded_by_finding_pipeline(self):
        """build_relationships should consume overlap_reuse output."""
        from engine.static_audit.tools.visual_finding_pipeline import (
            build_relationships,
        )

        overlap_result = {
            "relationships": [
                {
                    "source_panel_id": "p1",
                    "target_panel_id": "p2",
                    "score": 0.6,
                    "verification_method": "rootsift_magsac",
                    "inlier_count": 50,
                    "overlay_path": None,
                    "flip_detected": False,
                }
            ]
        }
        rels = build_relationships(overlap_reuse_result=overlap_result)
        overlap_rels = [
            r for r in rels if r["source_type"] == "overlap_reuse_cross_panel"
        ]
        assert len(overlap_rels) == 1
        assert overlap_rels[0]["score"] == 0.6
        assert overlap_rels[0]["inlier_count"] == 50

    def test_overlap_dedup_with_copy_move(self):
        """If copy_move and overlap_reuse both find the same pair, copy_move wins."""
        from engine.static_audit.tools.visual_finding_pipeline import (
            build_relationships,
        )

        cm_result = {
            "relationships": [
                {
                    "source_panel_id": "p1",
                    "target_panel_id": "p2",
                    "score": 0.8,
                    "source_type": "copy_move_cross",
                    "match_method": "rootsift_magsac",
                    "inlier_count": 100,
                }
            ]
        }
        overlap_result = {
            "relationships": [
                {
                    "source_panel_id": "p1",
                    "target_panel_id": "p2",
                    "score": 0.6,
                    "verification_method": "rootsift_magsac",
                    "inlier_count": 50,
                }
            ]
        }
        rels = build_relationships(
            copy_move_result=cm_result, overlap_reuse_result=overlap_result
        )
        pair_rels = [
            r
            for r in rels
            if frozenset({r["source_panel_id"], r["target_panel_id"]})
            == frozenset({"p1", "p2"})
        ]
        assert len(pair_rels) == 1
        assert pair_rels[0]["source_type"] == "copy_move_cross"

    def test_overlap_findings_risk_capped_at_high(self):
        """Overlap findings should never have risk_level=critical."""
        from engine.static_audit.tools.visual_finding_pipeline import (
            build_visual_findings,
        )

        rels = [
            {
                "source_panel_id": "p1",
                "target_panel_id": "p2",
                "score": 0.95,
                "source_type": "overlap_reuse_cross_panel",
                "match_method": "rootsift_magsac",
                "inlier_count": 200,
            }
        ]
        findings = build_visual_findings(rels)
        for f in findings:
            if f["category"] == "overlap_reuse_cross_panel":
                assert f["risk_level"] in ("info", "low", "medium", "high")
                assert f["risk_level"] != "critical"
