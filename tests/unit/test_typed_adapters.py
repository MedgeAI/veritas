"""Tests for typed adapters covering pair-forensics, source-data, and visual findings.

Validates:
- Backward-compatible parsing of historical fixtures.
- Field-name alias resolution.
- Safe defaults for missing fields (no exceptions).
- Lossless access via the ``raw`` attribute.
- Loading helpers (load_*_artifact, iter_*_findings).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.static_audit.typed_adapters import (
    PairForensicsArtifact,
    PairForensicsFinding,
    SourceDataFinding,
    SourceDataFindingsArtifact,
    VisualFinding,
    VisualFindingsArtifact,
    iter_priority_findings,
    iter_source_data_findings,
    iter_visual_findings,
    load_pair_forensics_artifact,
    load_source_data_findings_artifact,
    load_visual_findings_artifact,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "pair_forensics"


# ---------------------------------------------------------------------------
# Historical fixture tests
# ---------------------------------------------------------------------------


class TestHistoricalFixtures:
    """All 3 historical fixture versions must parse without exceptions."""

    @pytest.fixture()
    def v1(self) -> PairForensicsArtifact:
        artifact = load_pair_forensics_artifact(FIXTURES_DIR / "pair_forensics_v1.json")
        assert artifact is not None
        return artifact

    @pytest.fixture()
    def v2(self) -> PairForensicsArtifact:
        artifact = load_pair_forensics_artifact(FIXTURES_DIR / "pair_forensics_v2.json")
        assert artifact is not None
        return artifact

    @pytest.fixture()
    def v3(self) -> PairForensicsArtifact:
        artifact = load_pair_forensics_artifact(FIXTURES_DIR / "pair_forensics_v3.json")
        assert artifact is not None
        return artifact

    # -- v1: oldest, column_pair + matched_pairs, no finding_id ----------

    def test_v1_finds_two_priority_findings(self, v1: PairForensicsArtifact) -> None:
        assert len(v1.priority_findings) == 2

    def test_v1_column_pair_alias_resolved(self, v1: PairForensicsArtifact) -> None:
        finding = v1.priority_findings[0]
        assert finding.columns == ("C", "D")

    def test_v1_matched_pairs_alias_resolved(self, v1: PairForensicsArtifact) -> None:
        finding = v1.priority_findings[0]
        assert finding.support_rows == 45

    def test_v1_overlap_pairs_alias_resolved(self, v1: PairForensicsArtifact) -> None:
        finding = v1.priority_findings[0]
        assert finding.overlap_rows == 50

    def test_v1_no_finding_id_defaults_to_none(self, v1: PairForensicsArtifact) -> None:
        finding = v1.priority_findings[0]
        assert finding.finding_id is None

    def test_v1_no_support_rate_defaults_to_none(self, v1: PairForensicsArtifact) -> None:
        finding = v1.priority_findings[0]
        assert finding.support_rate is None

    def test_v1_category_not_empty(self, v1: PairForensicsArtifact) -> None:
        for finding in v1.priority_findings:
            assert finding.category != ""

    def test_v1_raw_preserved(self, v1: PairForensicsArtifact) -> None:
        finding = v1.priority_findings[0]
        assert finding.raw["column_pair"] == ["C", "D"]
        assert finding.raw["matched_pairs"] == 45

    # -- v2: middle, columns + support_rows + finding_id, no support_rate --

    def test_v2_finding_id_present(self, v2: PairForensicsArtifact) -> None:
        assert v2.priority_findings[0].finding_id == "ROE-0001"

    def test_v2_columns_direct(self, v2: PairForensicsArtifact) -> None:
        finding = v2.priority_findings[0]
        assert finding.columns == ("A", "B")

    def test_v2_support_rows_direct(self, v2: PairForensicsArtifact) -> None:
        assert v2.priority_findings[0].support_rows == 120

    def test_v2_overlap_rows_direct(self, v2: PairForensicsArtifact) -> None:
        assert v2.priority_findings[0].overlap_rows == 130

    def test_v2_no_support_rate_defaults_to_none(self, v2: PairForensicsArtifact) -> None:
        assert v2.priority_findings[0].support_rate is None

    # -- v3: current, all fields present -----------------------------------

    def test_v3_all_fields_present(self, v3: PairForensicsArtifact) -> None:
        finding = v3.priority_findings[0]
        assert finding.finding_id == "BAR-0002"
        assert finding.category == "binary_arithmetic_relation"
        assert finding.risk_level == "high"
        assert finding.workbook == "clinical_trial.xlsx"
        assert finding.sheet == "Biomarkers"
        assert finding.columns == ("concentration_ng_ml", "dose_mg", "body_weight_kg")
        assert finding.support_rows == 200
        assert finding.overlap_rows == 210
        assert finding.support_rate == pytest.approx(0.9524)
        assert finding.row_offset is None  # explicitly null in fixture

    def test_v3_raw_contains_extra_fields(self, v3: PairForensicsArtifact) -> None:
        finding = v3.priority_findings[0]
        assert finding.raw["relationship_value"] == "A*B=C"
        assert "benign_explanations" in finding.raw


# ---------------------------------------------------------------------------
# from_dict backward compatibility
# ---------------------------------------------------------------------------


class TestFromDictBackwardCompat:
    """from_dict MUST never raise on missing fields."""

    def test_empty_dict_gives_safe_defaults(self) -> None:
        finding = PairForensicsFinding.from_dict({})
        assert finding.finding_id is None
        assert finding.category == ""
        assert finding.risk_level == "info"
        assert finding.workbook == ""
        assert finding.sheet is None
        assert finding.columns == ()
        assert finding.support_rows == 0
        assert finding.overlap_rows is None
        assert finding.support_rate is None
        assert finding.row_offset is None

    def test_raw_preserves_original_dict(self) -> None:
        data = {"category": "test", "extra_field": 42}
        finding = PairForensicsFinding.from_dict(data)
        assert finding.raw is data
        assert finding.raw["extra_field"] == 42

    def test_column_string_becomes_single_tuple(self) -> None:
        finding = PairForensicsFinding.from_dict({"column": "A"})
        assert finding.columns == ("A",)

    def test_support_rows_from_equal_rows(self) -> None:
        finding = PairForensicsFinding.from_dict({"equal_rows": 99})
        assert finding.support_rows == 99

    def test_support_rows_from_matched_pairs(self) -> None:
        finding = PairForensicsFinding.from_dict({"matched_pairs": 77})
        assert finding.support_rows == 77

    def test_overlap_rows_from_overlap_pair_groups(self) -> None:
        finding = PairForensicsFinding.from_dict({"overlap_pair_groups": 11})
        assert finding.overlap_rows == 11

    def test_row_offset_from_pair_id_offset(self) -> None:
        finding = PairForensicsFinding.from_dict({"pair_id_offset": 5})
        assert finding.row_offset == 5

    def test_invalid_support_rows_coerced_to_zero(self) -> None:
        finding = PairForensicsFinding.from_dict({"support_rows": "not-a-number"})
        assert finding.support_rows == 0

    def test_priority_order_columns_wins_over_column_pair(self) -> None:
        data = {"columns": ["X", "Y"], "column_pair": ["A", "B"]}
        finding = PairForensicsFinding.from_dict(data)
        assert finding.columns == ("X", "Y")

    def test_priority_order_support_rows_wins_over_matched_pairs(self) -> None:
        data = {"support_rows": 10, "matched_pairs": 20}
        finding = PairForensicsFinding.from_dict(data)
        assert finding.support_rows == 10


# ---------------------------------------------------------------------------
# load_pair_forensics_artifact edge cases
# ---------------------------------------------------------------------------


class TestLoadArtifact:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert load_pair_forensics_artifact(tmp_path / "nonexistent.json") is None

    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{invalid", encoding="utf-8")
        assert load_pair_forensics_artifact(bad) is None

    def test_non_dict_root_returns_none(self, tmp_path: Path) -> None:
        arr = tmp_path / "array.json"
        arr.write_text("[1,2,3]", encoding="utf-8")
        assert load_pair_forensics_artifact(arr) is None

    def test_empty_priority_findings_parses(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.json"
        f.write_text(json.dumps({"priority_findings": []}), encoding="utf-8")
        artifact = load_pair_forensics_artifact(f)
        assert artifact is not None
        assert len(artifact.priority_findings) == 0


# ---------------------------------------------------------------------------
# iter_priority_findings
# ---------------------------------------------------------------------------


class TestIterPriorityFindings:
    def test_iter_returns_all_findings(self) -> None:
        artifact = load_pair_forensics_artifact(FIXTURES_DIR / "pair_forensics_v3.json")
        assert artifact is not None
        findings = list(iter_priority_findings(artifact))
        assert len(findings) == 2
        assert all(isinstance(f, PairForensicsFinding) for f in findings)


# ---------------------------------------------------------------------------
# Field coverage: typed object vs raw dict
# ---------------------------------------------------------------------------


class TestFieldCoverage:
    """Typed adapter must not lose information available through raw dict."""

    def test_typed_fields_cover_public_contract(self) -> None:
        """All public contract fields are accessible on the typed object."""
        data = {
            "finding_id": "TEST-001",
            "category": "row_offset_exact_reuse",
            "risk_level": "high",
            "workbook": "test.xlsx",
            "sheet": "Sheet1",
            "columns": ["A", "B"],
            "support_rows": 50,
            "overlap_rows": 60,
            "support_rate": 0.8333,
            "row_offset": 12,
        }
        finding = PairForensicsFinding.from_dict(data)
        assert finding.finding_id == "TEST-001"
        assert finding.category == "row_offset_exact_reuse"
        assert finding.risk_level == "high"
        assert finding.workbook == "test.xlsx"
        assert finding.sheet == "Sheet1"
        assert finding.columns == ("A", "B")
        assert finding.support_rows == 50
        assert finding.overlap_rows == 60
        assert finding.support_rate == pytest.approx(0.8333)
        assert finding.row_offset == 12

    def test_raw_retains_extra_fields_not_in_typed_contract(self) -> None:
        """Fields outside the typed contract remain accessible via raw."""
        data = {
            "category": "binary_arithmetic_relation",
            "relationship_value": "A*B=C",
            "pattern_strength": "strong",
            "benign_explanations": ["Valid formula"],
        }
        finding = PairForensicsFinding.from_dict(data)
        assert finding.raw["relationship_value"] == "A*B=C"
        assert finding.raw["pattern_strength"] == "strong"
        assert finding.raw["benign_explanations"] == ["Valid formula"]


# ===================================================================
# SourceDataFinding tests
# ===================================================================


class TestSourceDataFindingBackwardCompat:
    """from_dict MUST never raise on missing fields."""

    def test_empty_dict_gives_safe_defaults(self) -> None:
        finding = SourceDataFinding.from_dict({})
        assert finding.finding_id is None
        assert finding.category == ""
        assert finding.risk_level == "info"
        assert finding.workbook == ""
        assert finding.sheet is None
        assert finding.columns == ()
        assert finding.support_rows == 0
        assert finding.overlap_rows is None
        assert finding.support_rate is None
        assert finding.equal_rows == 0
        assert finding.confidence is None
        assert finding.artifact_likelihood is None
        assert finding.benign_explanations == ()
        assert finding.pressure_test_result is None
        assert finding.manual_review_note is None

    def test_raw_preserves_original_dict(self) -> None:
        data = {"category": "test", "extra_field": 42}
        finding = SourceDataFinding.from_dict(data)
        assert finding.raw is data
        assert finding.raw["extra_field"] == 42

    def test_column_pair_alias_resolved(self) -> None:
        finding = SourceDataFinding.from_dict({"column_pair": ["A", "B"]})
        assert finding.columns == ("A", "B")

    def test_columns_direct(self) -> None:
        finding = SourceDataFinding.from_dict({"columns": ["X", "Y"]})
        assert finding.columns == ("X", "Y")

    def test_column_string_becomes_single_tuple(self) -> None:
        finding = SourceDataFinding.from_dict({"column": "A"})
        assert finding.columns == ("A",)

    def test_support_rows_alias_from_matched_pairs(self) -> None:
        finding = SourceDataFinding.from_dict({"matched_pairs": 77})
        assert finding.support_rows == 77

    def test_equal_rows_direct(self) -> None:
        finding = SourceDataFinding.from_dict({"equal_rows": 99})
        assert finding.equal_rows == 99

    def test_priority_columns_over_column_pair(self) -> None:
        data = {"columns": ["X", "Y"], "column_pair": ["A", "B"]}
        finding = SourceDataFinding.from_dict(data)
        assert finding.columns == ("X", "Y")

    def test_priority_support_rows_over_matched_pairs(self) -> None:
        data = {"support_rows": 10, "matched_pairs": 20}
        finding = SourceDataFinding.from_dict(data)
        assert finding.support_rows == 10

    def test_benign_explanations_tuple(self) -> None:
        data = {"benign_explanations": ["Valid formula", "Unit conversion"]}
        finding = SourceDataFinding.from_dict(data)
        assert finding.benign_explanations == ("Valid formula", "Unit conversion")

    def test_invalid_support_rows_coerced_to_zero(self) -> None:
        finding = SourceDataFinding.from_dict({"support_rows": "not-a-number"})
        assert finding.support_rows == 0


class TestSourceDataFindingsArtifact:
    def test_from_dict_parses_both_lists(self) -> None:
        data = {
            "priority_findings": [
                {"finding_id": "PF-001", "category": "duplicate_numeric_columns"},
            ],
            "findings": [
                {"finding_id": "F-001", "category": "duplicate_numeric_columns"},
                {"finding_id": "F-002", "category": "fixed_difference"},
            ],
        }
        artifact = SourceDataFindingsArtifact.from_dict(data)
        assert len(artifact.priority_findings) == 1
        assert len(artifact.findings) == 2
        assert artifact.priority_findings[0].finding_id == "PF-001"
        assert artifact.findings[1].finding_id == "F-002"

    def test_empty_lists(self) -> None:
        artifact = SourceDataFindingsArtifact.from_dict({})
        assert len(artifact.priority_findings) == 0
        assert len(artifact.findings) == 0

    def test_raw_preserved(self) -> None:
        data = {
            "priority_findings": [],
            "claim_to_source_data": [{"claim": "Fig 1"}],
            "summary": {"priority_findings": 0},
        }
        artifact = SourceDataFindingsArtifact.from_dict(data)
        assert artifact.raw["claim_to_source_data"] == [{"claim": "Fig 1"}]
        assert artifact.raw["summary"]["priority_findings"] == 0

    def test_non_dict_items_skipped(self) -> None:
        data = {"priority_findings": [42, "bad", None, {"finding_id": "OK"}]}
        artifact = SourceDataFindingsArtifact.from_dict(data)
        assert len(artifact.priority_findings) == 1
        assert artifact.priority_findings[0].finding_id == "OK"


class TestLoadSourceDataFindingsArtifact:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert load_source_data_findings_artifact(tmp_path / "nope.json") is None

    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{invalid", encoding="utf-8")
        assert load_source_data_findings_artifact(bad) is None

    def test_non_dict_root_returns_none(self, tmp_path: Path) -> None:
        arr = tmp_path / "array.json"
        arr.write_text("[1,2]", encoding="utf-8")
        assert load_source_data_findings_artifact(arr) is None

    def test_valid_file_parses(self, tmp_path: Path) -> None:
        f = tmp_path / "source_data_findings.json"
        f.write_text(
            json.dumps({"priority_findings": [{"category": "dup"}]}),
            encoding="utf-8",
        )
        artifact = load_source_data_findings_artifact(f)
        assert artifact is not None
        assert len(artifact.priority_findings) == 1


class TestIterSourceDataFindings:
    def test_iter_returns_priority_findings(self) -> None:
        data = {
            "priority_findings": [
                {"finding_id": "A"},
                {"finding_id": "B"},
            ],
            "findings": [{"finding_id": "C"}],
        }
        artifact = SourceDataFindingsArtifact.from_dict(data)
        results = list(iter_source_data_findings(artifact))
        assert len(results) == 2
        assert results[0].finding_id == "A"
        assert results[1].finding_id == "B"


# ===================================================================
# VisualFinding tests
# ===================================================================


class TestVisualFindingBackwardCompat:
    """from_dict MUST never raise on missing fields."""

    def test_empty_dict_gives_safe_defaults(self) -> None:
        finding = VisualFinding.from_dict({})
        assert finding.finding_id is None
        assert finding.category == "visual_finding"
        assert finding.risk_level == "medium"
        assert finding.summary == ""
        assert finding.source_panel_id is None
        assert finding.target_panel_id is None
        assert finding.score is None
        assert finding.overlay_path is None
        assert finding.relationship_id is None
        assert finding.benign_explanations == ()
        assert finding.manual_review_questions == ()

    def test_raw_preserves_original_dict(self) -> None:
        data = {"finding_id": "VF-001", "extra": True}
        finding = VisualFinding.from_dict(data)
        assert finding.raw is data
        assert finding.raw["extra"] is True

    def test_full_finding_parses(self) -> None:
        data = {
            "finding_id": "VF-0042",
            "category": "exact_duplicate",
            "risk_level": "high",
            "summary": "Panel A1 is an exact duplicate of Panel B2.",
            "source_panel_id": "panel-a1",
            "target_panel_id": "panel-b2",
            "score": 0.95,
            "overlay_path": "/overlays/vf-0042.png",
            "relationship_id": "REL-0010",
            "benign_explanations": ["Same experiment repeated."],
            "manual_review_questions": ["Are these independent samples?"],
        }
        finding = VisualFinding.from_dict(data)
        assert finding.finding_id == "VF-0042"
        assert finding.category == "exact_duplicate"
        assert finding.risk_level == "high"
        assert finding.summary == "Panel A1 is an exact duplicate of Panel B2."
        assert finding.source_panel_id == "panel-a1"
        assert finding.target_panel_id == "panel-b2"
        assert finding.score == pytest.approx(0.95)
        assert finding.overlay_path == "/overlays/vf-0042.png"
        assert finding.relationship_id == "REL-0010"
        assert finding.benign_explanations == ("Same experiment repeated.",)
        assert finding.manual_review_questions == ("Are these independent samples?",)

    def test_invalid_score_coerced_to_none(self) -> None:
        finding = VisualFinding.from_dict({"score": "not-a-number"})
        assert finding.score is None


class TestVisualFindingsArtifact:
    def test_from_dict_parses_findings(self) -> None:
        data = {
            "findings": [
                {"finding_id": "VF-001", "category": "exact_duplicate"},
                {"finding_id": "VF-002", "category": "copy_move"},
            ],
            "finding_clusters": [{"cluster_id": "C1"}],
        }
        artifact = VisualFindingsArtifact.from_dict(data)
        assert len(artifact.findings) == 2
        assert artifact.findings[0].finding_id == "VF-001"
        assert artifact.raw["finding_clusters"] == [{"cluster_id": "C1"}]

    def test_empty_findings(self) -> None:
        artifact = VisualFindingsArtifact.from_dict({})
        assert len(artifact.findings) == 0

    def test_non_dict_items_skipped(self) -> None:
        data = {"findings": [42, "bad", None, {"finding_id": "OK"}]}
        artifact = VisualFindingsArtifact.from_dict(data)
        assert len(artifact.findings) == 1
        assert artifact.findings[0].finding_id == "OK"


class TestLoadVisualFindingsArtifact:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert load_visual_findings_artifact(tmp_path / "nope.json") is None

    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{invalid", encoding="utf-8")
        assert load_visual_findings_artifact(bad) is None

    def test_non_dict_root_returns_none(self, tmp_path: Path) -> None:
        arr = tmp_path / "array.json"
        arr.write_text("[1,2]", encoding="utf-8")
        assert load_visual_findings_artifact(arr) is None

    def test_valid_file_parses(self, tmp_path: Path) -> None:
        f = tmp_path / "visual_findings.json"
        f.write_text(
            json.dumps({"findings": [{"finding_id": "VF-001"}]}),
            encoding="utf-8",
        )
        artifact = load_visual_findings_artifact(f)
        assert artifact is not None
        assert len(artifact.findings) == 1


class TestIterVisualFindings:
    def test_iter_returns_all_findings(self) -> None:
        data = {
            "findings": [
                {"finding_id": "VF-001"},
                {"finding_id": "VF-002"},
                {"finding_id": "VF-003"},
            ],
        }
        artifact = VisualFindingsArtifact.from_dict(data)
        results = list(iter_visual_findings(artifact))
        assert len(results) == 3
        assert results[2].finding_id == "VF-003"
