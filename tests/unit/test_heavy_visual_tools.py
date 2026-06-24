"""Tests for heavy/optional visual investigation tools.

Merged from: test_image_similarity.py + test_sila_dense.py.
These tools are agent-selectable investigation tools, not baseline.
"""

from __future__ import annotations

from pathlib import Path

from engine.static_audit.tools.image_similarity import generate_similarity_candidates
from engine.static_audit.tools.sila_dense import detect_sila_dense


# =============================================================================
# test_image_similarity.py
# =============================================================================


def test_image_similarity_skips_empty_image_dir(tmp_path) -> None:
    result = generate_similarity_candidates(tmp_path)

    assert result["status"] == "skipped"
    assert result["image_count"] == 0
    assert result["candidate_count"] == 0
    assert result["candidates"] == []


# =============================================================================
# test_sila_dense.py
# =============================================================================


def test_sila_dense_mask_coverage_failure_does_not_create_relationship(
    tmp_path: Path, monkeypatch
) -> None:
    crop_path = tmp_path / "visual" / "panels" / "P1.png"
    crop_path.parent.mkdir(parents=True)
    crop_path.write_bytes(b"not actually used by the monkeypatched runner")
    mask_path = tmp_path / "bad_mask.png"
    mask_path.write_text("not an image", encoding="utf-8")

    def fake_run_single_image_docker(_crop_path: Path, _output_dir: Path) -> dict:
        return {
            "success": True,
            "mask_path": str(mask_path),
            "matches_path": None,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(
        "engine.static_audit.tools.sila_dense._docker_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "engine.static_audit.tools.sila_dense._run_single_image_docker",
        fake_run_single_image_docker,
    )

    result = detect_sila_dense(
        [
            {
                "panel_id": "P1",
                "parent_figure_id": "F1",
                "crop_path": "visual/panels/P1.png",
            }
        ],
        [],
        workdir=tmp_path,
        output_base=tmp_path / "sila",
        min_score=0.05,
    )

    assert result["status"] == "ran"
    assert result["relationship_count"] == 0
    assert result["relationships"] == []
    assert any("mask coverage failed" in error for error in result["errors"])
