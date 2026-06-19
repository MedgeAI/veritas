"""Tests for visual forensics fixtures."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES_DIR = Path("tests/fixtures/visual")

_OVERLAP_FIXTURE_PREFIXES = ("synthetic_overlap_",)


def _is_overlap_fixture(name: str) -> bool:
    return any(name.startswith(p) for p in _OVERLAP_FIXTURE_PREFIXES)


class TestSyntheticFixtures:
    """Test synthetic fixture validity."""

    def test_all_fixtures_exist(self):
        """All expected synthetic fixtures should exist."""
        expected_fixtures = [
            "synthetic_2x2_clean",
            "synthetic_copy_exact",
            "synthetic_copy_scaled",
            "synthetic_copy_rotated",
            "synthetic_copy_brightness",
            "synthetic_overlap_crop",
            "synthetic_overlap_scale",
            "synthetic_overlap_flip",
            "synthetic_overlap_negative_similar",
            "synthetic_overlap_negative_low_texture",
        ]
        for fixture_name in expected_fixtures:
            fixture_dir = FIXTURES_DIR / fixture_name
            assert fixture_dir.exists(), f"Fixture {fixture_name} does not exist"

    def test_fixture_has_ground_truth(self):
        """Each fixture should have a ground_truth.json file."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and fixture_dir.name.startswith("synthetic_"):
                ground_truth_path = fixture_dir / "ground_truth.json"
                assert ground_truth_path.exists(), (
                    f"Fixture {fixture_dir.name} missing ground_truth.json"
                )

    def test_figure_fixture_has_images(self):
        """Figure-based fixtures (non-overlap) should have Figure1.png and Figure2.png."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and fixture_dir.name.startswith("synthetic_"):
                if _is_overlap_fixture(fixture_dir.name):
                    continue
                images_dir = fixture_dir / "images"
                assert images_dir.exists(), f"Fixture {fixture_dir.name} missing images directory"
                assert (images_dir / "Figure1.png").exists(), (
                    f"Fixture {fixture_dir.name} missing Figure1.png"
                )
                assert (images_dir / "Figure2.png").exists(), (
                    f"Fixture {fixture_dir.name} missing Figure2.png"
                )

    def test_overlap_fixture_has_panel_images(self):
        """Overlap fixtures should have panel_a.png and panel_b.png."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and _is_overlap_fixture(fixture_dir.name):
                images_dir = fixture_dir / "images"
                assert images_dir.exists(), f"Fixture {fixture_dir.name} missing images directory"
                assert (images_dir / "panel_a.png").exists(), (
                    f"Overlap fixture {fixture_dir.name} missing panel_a.png"
                )
                assert (images_dir / "panel_b.png").exists(), (
                    f"Overlap fixture {fixture_dir.name} missing panel_b.png"
                )

    def test_ground_truth_schema_valid(self):
        """Figure-based fixtures should have valid schema."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and fixture_dir.name.startswith("synthetic_"):
                if _is_overlap_fixture(fixture_dir.name):
                    continue
                ground_truth_path = fixture_dir / "ground_truth.json"
                ground_truth = json.loads(ground_truth_path.read_text())

                # Check required fields
                assert "schema_version" in ground_truth
                assert "fixture_type" in ground_truth
                assert "figures" in ground_truth
                assert "expected_relationships" in ground_truth

                # Check figures
                assert len(ground_truth["figures"]) > 0
                for figure in ground_truth["figures"]:
                    assert "figure_id" in figure
                    assert "source_image_path" in figure
                    assert "label" in figure
                    assert "expected_panels" in figure
                    assert "panels" in figure

                # Check relationships
                for rel in ground_truth["expected_relationships"]:
                    assert "source_panel_id" in rel
                    assert "target_panel_id" in rel
                    assert "source_type" in rel

    def test_overlap_ground_truth_schema_valid(self):
        """Overlap fixtures should have valid overlap-specific schema."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and _is_overlap_fixture(fixture_dir.name):
                ground_truth_path = fixture_dir / "ground_truth.json"
                ground_truth = json.loads(ground_truth_path.read_text())

                assert "schema_version" in ground_truth
                assert "fixture_type" in ground_truth
                assert "expected_overlap" in ground_truth
                assert isinstance(ground_truth["expected_overlap"], bool)
                assert "expected_overlap_area_ratio_source" in ground_truth
                assert "expected_overlap_area_ratio_target" in ground_truth
                assert "ground_truth_polygon_source" in ground_truth
                assert "ground_truth_polygon_target" in ground_truth
                assert "panels" in ground_truth
                assert "panel_a" in ground_truth["panels"]
                assert "panel_b" in ground_truth["panels"]

    def test_overlap_positive_fixtures_expect_overlap(self):
        """Positive overlap fixtures (crop/scale/flip) should expect overlap."""
        for name in ("synthetic_overlap_crop", "synthetic_overlap_scale", "synthetic_overlap_flip"):
            gt = json.loads((FIXTURES_DIR / name / "ground_truth.json").read_text())
            assert gt["expected_overlap"] is True, f"{name} should expect overlap"
            assert len(gt["ground_truth_polygon_source"]) > 0
            assert len(gt["ground_truth_polygon_target"]) > 0

    def test_overlap_negative_fixtures_expect_no_overlap(self):
        """Negative overlap fixtures should NOT expect overlap."""
        for name in ("synthetic_overlap_negative_similar", "synthetic_overlap_negative_low_texture"):
            gt = json.loads((FIXTURES_DIR / name / "ground_truth.json").read_text())
            assert gt["expected_overlap"] is False, f"{name} should NOT expect overlap"

    def test_synthetic_fixture_has_expected_panels(self):
        """Each synthetic figure-based fixture should have correct panel count."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and fixture_dir.name.startswith("synthetic_"):
                if _is_overlap_fixture(fixture_dir.name):
                    continue
                ground_truth_path = fixture_dir / "ground_truth.json"
                ground_truth = json.loads(ground_truth_path.read_text())

                for figure in ground_truth["figures"]:
                    assert len(figure["panels"]) == figure["expected_panels"], (
                        f"Fixture {fixture_dir.name} figure {figure['figure_id']} "
                        f"has {len(figure['panels'])} panels, expected {figure['expected_panels']}"
                    )

    def test_synthetic_copy_has_known_relationship(self):
        """Copy fixtures should have at least one expected relationship."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and "copy" in fixture_dir.name and not _is_overlap_fixture(fixture_dir.name):
                ground_truth_path = fixture_dir / "ground_truth.json"
                ground_truth = json.loads(ground_truth_path.read_text())

                assert len(ground_truth["expected_relationships"]) > 0, (
                    f"Copy fixture {fixture_dir.name} should have at least one relationship"
                )

    def test_synthetic_clean_has_no_relationships(self):
        """Clean fixture should have no relationships (negative control)."""
        fixture_dir = FIXTURES_DIR / "synthetic_2x2_clean"
        ground_truth_path = fixture_dir / "ground_truth.json"
        ground_truth = json.loads(ground_truth_path.read_text())

        assert len(ground_truth["expected_relationships"]) == 0, (
            "Clean fixture should have no relationships"
        )

    def test_synthetic_fixture_images_exist(self):
        """All referenced images in ground truth should exist (figure-based fixtures only)."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and fixture_dir.name.startswith("synthetic_"):
                if _is_overlap_fixture(fixture_dir.name):
                    continue
                ground_truth_path = fixture_dir / "ground_truth.json"
                ground_truth = json.loads(ground_truth_path.read_text())

                for figure in ground_truth["figures"]:
                    image_path = fixture_dir / figure["source_image_path"]
                    assert image_path.exists(), (
                        f"Fixture {fixture_dir.name} missing image {figure['source_image_path']}"
                    )

    def test_copy_relationship_references_valid_panels(self):
        """Copy relationships should reference valid panel IDs."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and "copy" in fixture_dir.name and not _is_overlap_fixture(fixture_dir.name):
                ground_truth_path = fixture_dir / "ground_truth.json"
                ground_truth = json.loads(ground_truth_path.read_text())

                # Collect all panel IDs
                all_panel_ids = set()
                for figure in ground_truth["figures"]:
                    for panel in figure["panels"]:
                        all_panel_ids.add(panel["panel_id"])

                # Check relationships reference valid panels
                for rel in ground_truth["expected_relationships"]:
                    assert rel["source_panel_id"] in all_panel_ids, (
                        f"Fixture {fixture_dir.name} relationship references "
                        f"invalid source_panel_id: {rel['source_panel_id']}"
                    )
                    assert rel["target_panel_id"] in all_panel_ids, (
                        f"Fixture {fixture_dir.name} relationship references "
                        f"invalid target_panel_id: {rel['target_panel_id']}"
                    )

    def test_copy_panel_has_copy_source(self):
        """Panels marked as copies should have copy_source field."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and "copy" in fixture_dir.name and not _is_overlap_fixture(fixture_dir.name):
                ground_truth_path = fixture_dir / "ground_truth.json"
                ground_truth = json.loads(ground_truth_path.read_text())

                for figure in ground_truth["figures"]:
                    for panel in figure["panels"]:
                        if panel.get("is_copy"):
                            assert "copy_source" in panel, (
                                f"Fixture {fixture_dir.name} panel {panel['panel_id']} "
                                f"is marked as copy but missing copy_source"
                            )
