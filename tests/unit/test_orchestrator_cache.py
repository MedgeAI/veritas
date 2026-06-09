"""Unit tests for orchestrator cache-invalidation helpers."""

from __future__ import annotations

import json
import time
from pathlib import Path

from engine.static_audit.orchestrator import (
    _compute_input_hashes,
    _input_hashes_match,
    _sha256_file,
    _sha256_str,
    _upstream_fresh,
)


def test_compute_input_hashes_file(tmp_path: Path) -> None:
    """Single file artifact produces a valid SHA-256 hex digest."""
    f = tmp_path / "full.md"
    f.write_text("hello", encoding="utf-8")
    hashes = _compute_input_hashes(tmp_path, ("full.md",))
    assert "full.md" in hashes
    assert len(hashes["full.md"]) == 64  # SHA-256 hex


def test_compute_input_hashes_missing(tmp_path: Path) -> None:
    """Missing artifact gets '<missing>' sentinel."""
    hashes = _compute_input_hashes(tmp_path, ("nonexistent.md",))
    assert hashes["nonexistent.md"] == "<missing>"


def test_compute_input_hashes_directory(tmp_path: Path) -> None:
    """Directory artifact hashes all children."""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    (img_dir / "a.png").write_bytes(b"\x89PNG")
    (img_dir / "b.png").write_bytes(b"\x89PNG2")
    hashes = _compute_input_hashes(tmp_path, ("images/",))
    assert "images/" in hashes
    assert len(hashes["images/"]) == 64


def test_input_hashes_match_empty_stored() -> None:
    """Empty stored dict means legacy trace — force re-run."""
    assert not _input_hashes_match({}, {"a": "abc"})


def test_input_hashes_match_identical() -> None:
    assert _input_hashes_match({"a": "abc"}, {"a": "abc"})


def test_input_hashes_match_changed() -> None:
    assert not _input_hashes_match({"a": "abc"}, {"a": "xyz"})


def test_input_hashes_match_extra_computed_keys_ok() -> None:
    """Extra keys in computed (new artifacts) don't invalidate."""
    assert _input_hashes_match({"a": "abc"}, {"a": "abc", "b": "new"})


def test_upstream_fresh_no_output(tmp_path: Path) -> None:
    """Missing output is never fresh."""
    assert not _upstream_fresh(tmp_path / "missing.json", [])


def test_upstream_fresh_newer_upstream(tmp_path: Path) -> None:
    """Output older than upstream is stale."""
    out = tmp_path / "out.json"
    out.write_text("{}")
    time.sleep(0.05)
    upstream = tmp_path / "input.json"
    upstream.write_text("{}")
    assert not _upstream_fresh(out, [upstream])


def test_upstream_fresh_output_newer(tmp_path: Path) -> None:
    """Output newer than all upstreams is fresh."""
    upstream = tmp_path / "input.json"
    upstream.write_text("{}")
    time.sleep(0.05)
    out = tmp_path / "out.json"
    out.write_text("{}")
    assert _upstream_fresh(out, [upstream])


def test_sha256_file_deterministic(tmp_path: Path) -> None:
    f = tmp_path / "test.txt"
    f.write_text("deterministic", encoding="utf-8")
    assert _sha256_file(f) == _sha256_file(f)


def test_sha256_str_deterministic() -> None:
    assert _sha256_str("hello") == _sha256_str("hello")
    assert _sha256_str("hello") != _sha256_str("world")
