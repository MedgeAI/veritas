"""Tests for PRD3-T7 Agent review grounding extension.

Tests canonical finding ID collection, grounding check, and review artifact
schema with needs_review status.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.investigation.context_pack import (
    clear_canonical_ids_cache,
    get_all_canonical_finding_ids,
    get_artifact_backref,
)
from engine.investigation.agent_step_runner import AgentStepRunner


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear canonical IDs cache before each test."""
    clear_canonical_ids_cache()
    yield
    clear_canonical_ids_cache()


def _create_findings_artifact(path: Path, findings: list[dict]) -> None:
    """Helper to create a findings artifact file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"priority_findings": findings}
    path.write_text(json.dumps(data), encoding="utf-8")


def test_canonical_finding_ids_from_source_data_findings(tmp_path: Path) -> None:
    """Test that finding IDs are collected from source_data_findings.json."""
    workdir = tmp_path / "audit"
    findings_path = workdir / "source_data" / "findings.json"
    findings = [
        {"finding_id": "DRV-0001", "risk_level": "high"},
        {"finding_id": "DRV-0002", "risk_level": "medium"},
    ]
    _create_findings_artifact(findings_path, findings)

    ids = get_all_canonical_finding_ids(workdir)

    assert "DRV-0001" in ids
    assert "DRV-0002" in ids
    assert len(ids) == 2


def test_canonical_finding_ids_from_pair_forensics(tmp_path: Path) -> None:
    """Test that finding IDs are collected from source_data_pair_forensics.json."""
    workdir = tmp_path / "audit"
    pair_path = workdir / "source_data" / "pair_forensics.json"
    findings = [
        {"finding_id": "PF-0001", "risk_level": "high"},
    ]
    _create_findings_artifact(pair_path, findings)

    ids = get_all_canonical_finding_ids(workdir)

    assert "PF-0001" in ids


def test_canonical_finding_ids_from_visual_findings(tmp_path: Path) -> None:
    """Test that finding IDs are collected from visual_findings.json."""
    workdir = tmp_path / "audit"
    visual_path = workdir / "visual" / "findings.json"
    visual_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "findings": [
            {"finding_id": "VIS-0001", "risk_level": "high"},
            {"finding_id": "VIS-0002", "risk_level": "medium"},
        ]
    }
    visual_path.write_text(json.dumps(data), encoding="utf-8")

    ids = get_all_canonical_finding_ids(workdir)

    assert "VIS-0001" in ids
    assert "VIS-0002" in ids


def test_canonical_finding_ids_union_across_artifacts(tmp_path: Path) -> None:
    """Test that finding IDs are collected from all canonical artifacts."""
    workdir = tmp_path / "audit"

    # Create multiple artifacts with different findings
    source_findings_path = workdir / "source_data" / "findings.json"
    _create_findings_artifact(
        source_findings_path,
        [{"finding_id": "DRV-0001", "risk_level": "high"}],
    )

    pair_forensics_path = workdir / "source_data" / "pair_forensics.json"
    _create_findings_artifact(
        pair_forensics_path,
        [{"finding_id": "PF-0001", "risk_level": "medium"}],
    )

    visual_path = workdir / "visual" / "findings.json"
    visual_path.parent.mkdir(parents=True, exist_ok=True)
    visual_path.write_text(
        json.dumps({"findings": [{"finding_id": "VIS-0001", "risk_level": "high"}]}),
        encoding="utf-8",
    )

    ids = get_all_canonical_finding_ids(workdir)

    assert "DRV-0001" in ids
    assert "PF-0001" in ids
    assert "VIS-0001" in ids
    assert len(ids) == 3


def test_canonical_finding_ids_from_investigation_artifacts(tmp_path: Path) -> None:
    """Test that finding IDs are collected from investigation artifacts."""
    workdir = tmp_path / "audit"

    # Create investigation_rounds.jsonl with artifact references
    investigation_dir = workdir / "investigation"
    investigation_dir.mkdir(parents=True, exist_ok=True)
    rounds_path = investigation_dir / "investigation_rounds.jsonl"

    # Create a referenced artifact at workdir level (not in investigation subdir)
    investigation_artifact_path = workdir / "extra_findings.json"
    investigation_artifact_path.write_text(
        json.dumps({"findings": [{"finding_id": "INV-0001", "risk_level": "high"}]}),
        encoding="utf-8",
    )

    # Create rounds file referencing the artifact
    rounds_path.write_text(
        json.dumps({
            "round_id": 1,
            "output_artifacts": ["extra_findings.json"],
        }),
        encoding="utf-8",
    )

    ids = get_all_canonical_finding_ids(workdir)

    assert "INV-0001" in ids


def test_get_artifact_backref_returns_correct_path(tmp_path: Path) -> None:
    """Test that get_artifact_backref returns the correct artifact path."""
    workdir = tmp_path / "audit"
    findings_path = workdir / "source_data" / "findings.json"
    findings = [
        {"finding_id": "DRV-0001", "risk_level": "high"},
    ]
    _create_findings_artifact(findings_path, findings)

    backref = get_artifact_backref("DRV-0001", workdir)

    assert backref == "source_data/findings.json"


def test_get_artifact_backref_returns_none_for_unknown_id(tmp_path: Path) -> None:
    """Test that get_artifact_backref returns None for unknown finding_id."""
    workdir = tmp_path / "audit"
    findings_path = workdir / "source_data" / "findings.json"
    findings = [
        {"finding_id": "DRV-0001", "risk_level": "high"},
    ]
    _create_findings_artifact(findings_path, findings)

    backref = get_artifact_backref("UNKNOWN-0001", workdir)

    assert backref is None


def test_grounding_check_passes_for_valid_id(tmp_path: Path) -> None:
    """Test that grounding check passes when agent cites a valid finding_id."""
    workdir = tmp_path / "audit"
    findings_path = workdir / "source_data" / "findings.json"
    findings = [
        {"finding_id": "DRV-0001", "risk_level": "high"},
        {"finding_id": "DRV-0002", "risk_level": "medium"},
    ]
    _create_findings_artifact(findings_path, findings)

    runner = AgentStepRunner(project_root=tmp_path)
    output = {
        "finding_reviews": [
            {"finding_id": "DRV-0001", "assessment": "manual_review_required"},
        ]
    }

    grounding = runner._run_grounding_check(output, workdir)

    assert grounding["all_passed"] is True
    assert grounding["unknown_finding_ids"] == []


def test_grounding_check_passes_for_id_not_in_top_n(tmp_path: Path) -> None:
    """Test that grounding check passes for finding_id present in artifact but
    not in context_pack top_n_findings (PRD3-T7 core scenario)."""
    workdir = tmp_path / "audit"

    # Create artifact with 10 findings (DRV-0001 to DRV-0010)
    findings_path = workdir / "source_data" / "findings.json"
    findings = [
        {"finding_id": f"DRV-{i:04d}", "risk_level": "high"}
        for i in range(1, 11)
    ]
    _create_findings_artifact(findings_path, findings)

    runner = AgentStepRunner(project_root=tmp_path)
    # Agent cites DRV-0005 which is in the artifact but might not be in top_n
    output = {
        "finding_reviews": [
            {"finding_id": "DRV-0005", "assessment": "manual_review_required"},
        ]
    }

    grounding = runner._run_grounding_check(output, workdir)

    assert grounding["all_passed"] is True
    assert "DRV-0005" not in grounding.get("unknown_finding_ids", [])


def test_grounding_check_fails_for_unknown_id(tmp_path: Path) -> None:
    """Test that grounding check fails when agent cites an unknown finding_id."""
    workdir = tmp_path / "audit"
    findings_path = workdir / "source_data" / "findings.json"
    findings = [
        {"finding_id": "DRV-0001", "risk_level": "high"},
    ]
    _create_findings_artifact(findings_path, findings)

    runner = AgentStepRunner(project_root=tmp_path)
    output = {
        "finding_reviews": [
            {"finding_id": "UNKNOWN-0001", "assessment": "manual_review_required"},
        ]
    }

    grounding = runner._run_grounding_check(output, workdir)

    assert grounding["all_passed"] is False
    assert "UNKNOWN-0001" in grounding["unknown_finding_ids"]


def test_grounding_check_includes_backrefs(tmp_path: Path) -> None:
    """Test that grounding check includes artifact_backrefs for known IDs."""
    workdir = tmp_path / "audit"
    findings_path = workdir / "source_data" / "findings.json"
    findings = [
        {"finding_id": "DRV-0001", "risk_level": "high"},
    ]
    _create_findings_artifact(findings_path, findings)

    runner = AgentStepRunner(project_root=tmp_path)
    output = {
        "finding_reviews": [
            {"finding_id": "DRV-0001", "assessment": "manual_review_required"},
            {"finding_id": "UNKNOWN-0001", "assessment": "needs_more_evidence"},
        ]
    }

    grounding = runner._run_grounding_check(output, workdir)

    assert grounding["all_passed"] is False
    assert "UNKNOWN-0001" in grounding["unknown_finding_ids"]
    assert "DRV-0001" in grounding["artifact_backrefs"]
    assert grounding["artifact_backrefs"]["DRV-0001"] == "source_data/findings.json"


def test_grounding_check_handles_empty_output(tmp_path: Path) -> None:
    """Test that grounding check handles output with no finding_ids."""
    workdir = tmp_path / "audit"
    runner = AgentStepRunner(project_root=tmp_path)
    output = {"status": "ok", "limitations": []}

    grounding = runner._run_grounding_check(output, workdir)

    assert grounding["all_passed"] is True
    assert grounding["unknown_finding_ids"] == []


def test_grounding_check_handles_mixed_known_and_unknown(tmp_path: Path) -> None:
    """Test grounding check with mix of known and unknown finding_ids."""
    workdir = tmp_path / "audit"
    findings_path = workdir / "source_data" / "findings.json"
    findings = [
        {"finding_id": "DRV-0001", "risk_level": "high"},
        {"finding_id": "DRV-0002", "risk_level": "medium"},
    ]
    _create_findings_artifact(findings_path, findings)

    runner = AgentStepRunner(project_root=tmp_path)
    output = {
        "finding_reviews": [
            {"finding_id": "DRV-0001", "assessment": "manual_review_required"},
            {"finding_id": "DRV-0002", "assessment": "needs_more_evidence"},
            {"finding_id": "UNKNOWN-0001", "assessment": "manual_review_required"},
        ]
    }

    grounding = runner._run_grounding_check(output, workdir)

    assert grounding["all_passed"] is False
    assert len(grounding["unknown_finding_ids"]) == 1
    assert "UNKNOWN-0001" in grounding["unknown_finding_ids"]
    assert len(grounding["artifact_backrefs"]) == 2
    assert "DRV-0001" in grounding["artifact_backrefs"]
    assert "DRV-0002" in grounding["artifact_backrefs"]
