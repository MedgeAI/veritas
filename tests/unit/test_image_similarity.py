from __future__ import annotations

from engine.static_audit.tools.image_similarity import generate_similarity_candidates


def test_image_similarity_skips_empty_image_dir(tmp_path) -> None:
    result = generate_similarity_candidates(tmp_path)

    assert result["status"] == "skipped"
    assert result["image_count"] == 0
    assert result["candidate_count"] == 0
    assert result["candidates"] == []
