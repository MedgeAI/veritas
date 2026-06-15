"""Tests for layered output directory structure."""
from __future__ import annotations

from pathlib import Path

from engine.static_audit.orchestrator import (
    ARTIFACT_PATH_MAP,
    OUTPUT_DIRS,
    ensure_output_subdirs,
    output_subdir,
    resolve_artifact_path,
)


def test_output_dirs_has_expected_categories() -> None:
    """Verify OUTPUT_DIRS defines all expected categories."""
    expected = {"inputs", "mineru", "materials", "source_data", "visual", "numeric", "agents", "reports"}
    assert set(OUTPUT_DIRS.keys()) == expected


def test_ensure_output_subdirs_creates_all(tmp_path: Path) -> None:
    """Verify ensure_output_subdirs creates all subdirectories."""
    workdir = tmp_path / "audit"
    workdir.mkdir()

    ensure_output_subdirs(workdir)

    for category, subdir in OUTPUT_DIRS.items():
        path = workdir / subdir
        assert path.is_dir(), f"Missing subdirectory for category {category}: {path}"


def test_output_subdir_valid() -> None:
    """Verify output_subdir returns correct path for valid categories."""
    workdir = Path("/tmp/test")
    assert output_subdir(workdir, "mineru") == Path("/tmp/test/mineru")
    assert output_subdir(workdir, "visual") == Path("/tmp/test/visual")
    assert output_subdir(workdir, "reports") == Path("/tmp/test/reports")


def test_output_subdir_invalid() -> None:
    """Verify output_subdir raises ValueError for invalid category."""
    import pytest
    with pytest.raises(ValueError, match="Unknown output category"):
        output_subdir(Path("/tmp/test"), "nonexistent")


def test_resolve_artifact_path_mapped() -> None:
    """Verify resolve_artifact_path maps known artifacts to subdirectories."""
    workdir = Path("/tmp/test")

    # MinerU artifacts
    assert resolve_artifact_path(workdir, "full.md") == Path("/tmp/test/mineru/full.md")
    assert resolve_artifact_path(workdir, "evidence_ledger.json") == Path("/tmp/test/mineru/evidence_ledger.json")

    # Source Data artifacts
    assert resolve_artifact_path(workdir, "source_data_profile.json") == Path("/tmp/test/source_data/profile.json")
    assert resolve_artifact_path(workdir, "source_data_findings.json") == Path("/tmp/test/source_data/findings.json")

    # Visual artifacts
    assert resolve_artifact_path(workdir, "visual_evidence.json") == Path("/tmp/test/visual/evidence.json")
    assert resolve_artifact_path(workdir, "images") == Path("/tmp/test/visual/images")

    # Numeric artifacts
    assert resolve_artifact_path(workdir, "numeric_forensics.json") == Path("/tmp/test/numeric/forensics.json")

    # Agent artifacts
    assert resolve_artifact_path(workdir, "agent_review.json") == Path("/tmp/test/agents/review.json")

    # Report artifacts
    assert resolve_artifact_path(workdir, "final_audit_report.html") == Path("/tmp/test/reports/final_audit_report.html")
    assert resolve_artifact_path(workdir, "static_audit_bundle.json") == Path("/tmp/test/reports/static_audit_bundle.json")


def test_resolve_artifact_path_fallback() -> None:
    """Verify resolve_artifact_path returns flat path for unknown artifacts."""
    workdir = Path("/tmp/test")
    # Unknown artifact should fall back to flat path
    assert resolve_artifact_path(workdir, "unknown_file.json") == Path("/tmp/test/unknown_file.json")


def test_artifact_path_map_consistency() -> None:
    """Verify ARTIFACT_PATH_MAP maps all expected artifacts."""
    # Key artifacts that must be mapped
    required_mappings = [
        "full.md",
        "evidence_ledger.json",
        "source_data_profile.json",
        "source_data_findings.json",
        "visual_evidence.json",
        "panel_evidence.json",
        "numeric_forensics.json",
        "agent_review.json",
        "final_audit_report.html",
        "static_audit_bundle.json",
        "audit_run_manifest.json",
    ]
    for artifact in required_mappings:
        assert artifact in ARTIFACT_PATH_MAP, f"Missing mapping for {artifact}"
        # Verify the mapped path contains a subdirectory
        mapped = ARTIFACT_PATH_MAP[artifact]
        assert "/" in mapped, f"Mapping for {artifact} should contain subdirectory: {mapped}"
