"""Tests for the numeric forensics adapter boundary.

Validates:
- Adapter enriches upstream output with limitations metadata.
- Typed adapter parses raw and enriched artifacts with backward-compatible defaults.
- Legacy field-name aliases (``benford.mad``) are resolved correctly.
- Missing fields get safe defaults (no exceptions).
- The ``raw`` attribute preserves lossless access.
- Loading helpers handle missing files and parse errors gracefully.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.static_audit.adapters.numeric_forensics_adapter import (
    NUMERIC_FORENSICS_ARTIFACT_NAME,
    enrich_numeric_forensics_artifact,
    invoke_numeric_forensics,
)
from engine.static_audit.typed_adapters import (
    NumericForensicsArtifact,
    load_numeric_forensics_artifact,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "numeric_forensics"


# ---------------------------------------------------------------------------
# Adapter enrichment tests
# ---------------------------------------------------------------------------


class TestAdapterEnrichment:
    """Adapter must add limitations and schema version to upstream data."""

    def test_enrich_adds_schema_version(self) -> None:
        upstream = {"all_number_count": 100, "benford": {"applicability": "applicable"}}
        enriched = enrich_numeric_forensics_artifact(upstream)
        assert enriched["_veritas_schema_version"] == 1

    def test_enrich_adds_limitations(self) -> None:
        upstream = {"all_number_count": 100}
        enriched = enrich_numeric_forensics_artifact(upstream)
        assert isinstance(enriched["limitations"], list)
        assert len(enriched["limitations"]) > 0
        assert all(isinstance(lim, str) for lim in enriched["limitations"])

    def test_enrich_preserves_upstream_data(self) -> None:
        upstream = {
            "all_number_count": 342,
            "number_count": 187,
            "benford": {"applicability": "applicable", "mean_absolute_deviation": 0.0123},
        }
        enriched = enrich_numeric_forensics_artifact(upstream)
        # Original keys preserved at top level.
        assert enriched["all_number_count"] == 342
        assert enriched["number_count"] == 187
        assert enriched["benford"]["applicability"] == "applicable"
        # Original data preserved in ``upstream`` key.
        assert enriched["upstream"] is upstream

    def test_enrich_limitations_contain_isolation_note(self) -> None:
        enriched = enrich_numeric_forensics_artifact({"all_number_count": 1})
        isolation_notes = [
            lim for lim in enriched["limitations"] if "typed adapter" in lim.lower() or "NumericForensicsArtifact" in lim
        ]
        assert len(isolation_notes) > 0


class TestInvokeNumericForensics:
    """invoke_numeric_forensics must write enriched artifact to disk."""

    def test_invoke_writes_enriched_file(self, tmp_path: Path) -> None:
        output = tmp_path / "numeric_forensics.json"
        upstream_data = {
            "all_number_count": 100,
            "number_count": 50,
            "benford": {"applicability": "applicable", "mean_absolute_deviation": 0.02},
        }
        result = invoke_numeric_forensics(output, upstream_data=upstream_data)
        assert output.exists()
        assert result["limitations"]
        assert result["_veritas_schema_version"] == 1
        # Written file matches returned dict.
        on_disk = json.loads(output.read_text(encoding="utf-8"))
        assert on_disk == result

    def test_invoke_loads_from_disk_when_no_upstream_data(self, tmp_path: Path) -> None:
        output = tmp_path / "numeric_forensics.json"
        upstream_data = {"all_number_count": 42}
        output.write_text(json.dumps(upstream_data), encoding="utf-8")
        result = invoke_numeric_forensics(output)
        assert result["all_number_count"] == 42
        assert result["limitations"]

    def test_invoke_raises_on_missing_file(self, tmp_path: Path) -> None:
        output = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError):
            invoke_numeric_forensics(output)

    def test_invoke_raises_on_non_dict(self, tmp_path: Path) -> None:
        output = tmp_path / "bad.json"
        with pytest.raises(ValueError, match="root must be a dict"):
            invoke_numeric_forensics(output, upstream_data=[1, 2, 3])


# ---------------------------------------------------------------------------
# Typed adapter: historical fixtures
# ---------------------------------------------------------------------------


class TestHistoricalFixtures:
    """All fixture versions must parse without exceptions."""

    def test_v1_raw_upstream_parses(self) -> None:
        artifact = load_numeric_forensics_artifact(FIXTURES_DIR / "numeric_forensics_v1.json")
        assert artifact is not None
        assert artifact.all_number_count == 342
        assert artifact.number_count == 187
        assert artifact.table_count == 8
        assert artifact.effective_scope == "tables"
        assert artifact.benford_applicability == "applicable"
        assert artifact.benford_mad == pytest.approx(0.0123)
        assert artifact.benford_mean_absolute_deviation == pytest.approx(0.0123)

    def test_v2_enriched_parses(self) -> None:
        artifact = load_numeric_forensics_artifact(
            FIXTURES_DIR / "numeric_forensics_v2_enriched.json"
        )
        assert artifact is not None
        assert artifact.all_number_count == 342
        assert artifact.benford_applicability == "applicable"
        assert artifact.benford_mad == pytest.approx(0.0123)
        assert len(artifact.limitations) == 2

    def test_v3_legacy_mad_alias_resolved(self) -> None:
        artifact = load_numeric_forensics_artifact(
            FIXTURES_DIR / "numeric_forensics_v3_legacy_mad.json"
        )
        assert artifact is not None
        # Legacy ``mad`` alias is resolved to ``benford_mad``.
        assert artifact.benford_mad == pytest.approx(0.0567)
        assert artifact.benford_mean_absolute_deviation == pytest.approx(0.0567)
        assert artifact.benford_applicability == "not_applicable"


# ---------------------------------------------------------------------------
# Typed adapter: backward compatibility
# ---------------------------------------------------------------------------


class TestFromDictBackwardCompat:
    """from_dict MUST never raise on missing fields."""

    def test_empty_dict_gives_safe_defaults(self) -> None:
        artifact = NumericForensicsArtifact.from_dict({})
        assert artifact.all_number_count is None
        assert artifact.number_count is None
        assert artifact.table_count is None
        assert artifact.effective_scope is None
        assert artifact.benford_mad is None
        assert artifact.benford_mean_absolute_deviation is None
        assert artifact.benford_applicability is None
        assert artifact.benford_reason is None
        assert artifact.benford_sample_size is None
        assert artifact.benford_orders_of_magnitude is None
        assert artifact.limitations == ()

    def test_raw_preserved(self) -> None:
        data = {"all_number_count": 99, "extra_field": "hello"}
        artifact = NumericForensicsArtifact.from_dict(data)
        assert artifact.raw is data
        assert artifact.raw["extra_field"] == "hello"

    def test_mean_absolute_deviation_preferred_over_mad(self) -> None:
        data = {"benford": {"mean_absolute_deviation": 0.01, "mad": 0.99}}
        artifact = NumericForensicsArtifact.from_dict(data)
        assert artifact.benford_mad == pytest.approx(0.01)

    def test_mad_fallback_when_no_mean_absolute_deviation(self) -> None:
        data = {"benford": {"mad": 0.042}}
        artifact = NumericForensicsArtifact.from_dict(data)
        assert artifact.benford_mad == pytest.approx(0.042)

    def test_enriched_upstream_unwrapped(self) -> None:
        data = {
            "_veritas_schema_version": 1,
            "limitations": ["test limitation"],
            "upstream": {
                "all_number_count": 100,
                "benford": {"applicability": "applicable", "mean_absolute_deviation": 0.05},
            },
            # Top-level keys also present (as the adapter writes them).
            "all_number_count": 100,
            "benford": {"applicability": "applicable", "mean_absolute_deviation": 0.05},
        }
        artifact = NumericForensicsArtifact.from_dict(data)
        assert artifact.all_number_count == 100
        assert artifact.benford_applicability == "applicable"
        assert artifact.benford_mad == pytest.approx(0.05)
        assert artifact.limitations == ("test limitation",)

    def test_invalid_benford_value_coerced_to_none(self) -> None:
        data = {"benford": {"mean_absolute_deviation": "not-a-number"}}
        artifact = NumericForensicsArtifact.from_dict(data)
        assert artifact.benford_mad is None

    def test_benford_missing_entirely(self) -> None:
        data = {"all_number_count": 10}
        artifact = NumericForensicsArtifact.from_dict(data)
        assert artifact.benford_applicability is None
        assert artifact.benford_mad is None

    def test_benford_is_none(self) -> None:
        data = {"benford": None}
        artifact = NumericForensicsArtifact.from_dict(data)
        assert artifact.benford_applicability is None
        assert artifact.benford_mad is None


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


class TestLoadArtifact:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert load_numeric_forensics_artifact(tmp_path / "nonexistent.json") is None

    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{invalid", encoding="utf-8")
        assert load_numeric_forensics_artifact(bad) is None

    def test_non_dict_root_returns_none(self, tmp_path: Path) -> None:
        arr = tmp_path / "array.json"
        arr.write_text("[1,2,3]", encoding="utf-8")
        assert load_numeric_forensics_artifact(arr) is None

    def test_enriched_fixture_loads_with_limitations(self) -> None:
        artifact = load_numeric_forensics_artifact(
            FIXTURES_DIR / "numeric_forensics_v2_enriched.json"
        )
        assert artifact is not None
        assert "PDF numeric forensics" in artifact.limitations[0]


# ---------------------------------------------------------------------------
# Artifact name constant
# ---------------------------------------------------------------------------


class TestConstants:
    def test_artifact_name_constant(self) -> None:
        assert NUMERIC_FORENSICS_ARTIFACT_NAME == "numeric_forensics.json"


# ---------------------------------------------------------------------------
# Field coverage: typed object vs raw dict
# ---------------------------------------------------------------------------


class TestFieldCoverage:
    """Typed adapter must not lose information available through raw dict."""

    def test_typed_fields_cover_public_contract(self) -> None:
        """All public contract fields are accessible on the typed object."""
        data = {
            "all_number_count": 500,
            "number_count": 250,
            "table_count": 12,
            "effective_scope": "tables",
            "benford": {
                "applicability": "applicable",
                "reason": "n=250",
                "sample_size": 250,
                "orders_of_magnitude": 4.5,
                "mean_absolute_deviation": 0.008,
            },
        }
        artifact = NumericForensicsArtifact.from_dict(data)
        assert artifact.all_number_count == 500
        assert artifact.number_count == 250
        assert artifact.table_count == 12
        assert artifact.effective_scope == "tables"
        assert artifact.benford_applicability == "applicable"
        assert artifact.benford_reason == "n=250"
        assert artifact.benford_sample_size == 250
        assert artifact.benford_orders_of_magnitude == pytest.approx(4.5)
        assert artifact.benford_mad == pytest.approx(0.008)

    def test_raw_retains_extra_fields_not_in_typed_contract(self) -> None:
        """Fields outside the typed contract remain accessible via raw."""
        data = {
            "all_number_count": 10,
            "duplicates": {"repeated_values": [{"value": "1", "count": 3}]},
            "digits": {"terminal_0_or_5_rate": 0.3},
            "table_relationships": [{"table_index": 1}],
            "records_sample": [{"raw": "42"}],
        }
        artifact = NumericForensicsArtifact.from_dict(data)
        assert artifact.raw["duplicates"]["repeated_values"][0]["count"] == 3
        assert artifact.raw["digits"]["terminal_0_or_5_rate"] == 0.3
        assert artifact.raw["table_relationships"][0]["table_index"] == 1
