"""Tests for visual forensics fixtures."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES_DIR = Path("tests/fixtures/visual")


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

    def test_fixture_has_images(self):
        """Each fixture should have images directory with Figure1.png and Figure2.png."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and fixture_dir.name.startswith("synthetic_"):
                images_dir = fixture_dir / "images"
                assert images_dir.exists(), f"Fixture {fixture_dir.name} missing images directory"
                assert (images_dir / "Figure1.png").exists(), (
                    f"Fixture {fixture_dir.name} missing Figure1.png"
                )
                assert (images_dir / "Figure2.png").exists(), (
                    f"Fixture {fixture_dir.name} missing Figure2.png"
                )

    def test_ground_truth_schema_valid(self):
        """Ground truth should have valid schema."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and fixture_dir.name.startswith("synthetic_"):
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

    def test_synthetic_fixture_has_expected_panels(self):
        """Each synthetic fixture should have correct panel count."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and fixture_dir.name.startswith("synthetic_"):
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
            if fixture_dir.is_dir() and "copy" in fixture_dir.name:
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
        """All referenced images in ground truth should exist."""
        for fixture_dir in FIXTURES_DIR.iterdir():
            if fixture_dir.is_dir() and fixture_dir.name.startswith("synthetic_"):
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
            if fixture_dir.is_dir() and "copy" in fixture_dir.name:
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
            if fixture_dir.is_dir() and "copy" in fixture_dir.name:
                ground_truth_path = fixture_dir / "ground_truth.json"
                ground_truth = json.loads(ground_truth_path.read_text())

                for figure in ground_truth["figures"]:
                    for panel in figure["panels"]:
                        if panel.get("is_copy"):
                            assert "copy_source" in panel, (
                                f"Fixture {fixture_dir.name} panel {panel['panel_id']} "
                                f"is marked as copy but missing copy_source"
                            )
