"""Tests for the Canonical Numeric Signal Schema (WP1).

Verifies that:
- NumericSignal frozen dataclass can be constructed with all required fields
- validate_numeric_signal catches missing required fields
- NumericSignalSet supports add, iterate, count, serialize
- Signal IDs follow the NUM-SIG-NNNN pattern
- Evidence locator and applicability premise serialize correctly
"""

from __future__ import annotations

import json

import pytest

from engine.static_audit.numeric_signal_schema import (
    ApplicabilityPremise,
    EvidenceLocator,
    NumericSignal,
    NumericSignalSet,
    generate_signal_id,
    validate_numeric_signal,
)


def _make_valid_signal(**overrides: object) -> NumericSignal:
    """Create a valid NumericSignal for testing."""
    defaults = dict(
        signal_id="NUM-SIG-0001",
        source_tool="paperconan",
        detector_id="paperconan.identical_column",
        detector_family="column_relations",
        raw_kind="identical_column",
        canonical_category="identical_column",
        rule="columns A and B are identical",
        n=20,
        risk_level_raw="high",
        raw_payload_ref="relations_blocks/0/relations/0",
    )
    defaults.update(overrides)
    return NumericSignal(**defaults)  # type: ignore[arg-type]


class TestNumericSignal:
    def test_construct_valid_signal(self) -> None:
        signal = _make_valid_signal()
        assert signal.signal_id == "NUM-SIG-0001"
        assert signal.source_tool == "paperconan"
        assert signal.risk_level_raw == "high"

    def test_frozen_dataclass(self) -> None:
        signal = _make_valid_signal()
        with pytest.raises(AttributeError):
            signal.signal_id = "changed"  # type: ignore[misc]

    def test_to_dict(self) -> None:
        signal = _make_valid_signal()
        d = signal.to_dict()
        assert d["schema_version"] == "1.0"
        assert d["signal_id"] == "NUM-SIG-0001"
        assert d["source_tool"] == "paperconan"
        assert d["raw_payload_ref"] == "relations_blocks/0/relations/0"

    def test_to_dict_with_evidence_locator(self) -> None:
        locator = EvidenceLocator(
            source_path="SourceData.xlsx",
            source_sha256="abc123",
            sheet="Sheet1",
            rows="1-20",
            cols="A-C",
            highlight_rows=[1, 2, 3],
            highlight_cols=["A", "B"],
        )
        signal = _make_valid_signal(evidence_locator=locator)
        d = signal.to_dict()
        assert "evidence_locator" in d
        assert d["evidence_locator"]["source_path"] == "SourceData.xlsx"
        assert d["evidence_locator"]["source_sha256"] == "abc123"
        assert d["evidence_locator"]["highlight_rows"] == [1, 2, 3]

    def test_to_dict_with_applicability_premise(self) -> None:
        premise = ApplicabilityPremise(
            requires_integer_valued_items=True,
            requires_independent_rows=True,
        )
        signal = _make_valid_signal(applicability_premise=premise)
        d = signal.to_dict()
        assert "applicability_premise" in d
        assert d["applicability_premise"]["requires_integer_valued_items"] is True

    def test_to_dict_json_serializable(self) -> None:
        signal = _make_valid_signal(
            evidence_locator=EvidenceLocator(source_path="test.xlsx"),
            applicability_premise=ApplicabilityPremise(requires_raw_measurement=True),
            extra={"chi2": 15.3, "top": [[1, 5], [2, 3]]},
        )
        d = signal.to_dict()
        # Must be JSON-serializable
        serialized = json.dumps(d)
        assert "NUM-SIG-0001" in serialized


class TestValidateNumericSignal:
    def test_valid_signal_no_errors(self) -> None:
        signal = _make_valid_signal()
        errors = validate_numeric_signal(signal)
        assert errors == []

    def test_invalid_signal_id_format(self) -> None:
        signal = _make_valid_signal(signal_id="bad-id")
        errors = validate_numeric_signal(signal)
        assert any("signal_id" in e for e in errors)

    def test_missing_source_tool(self) -> None:
        signal = _make_valid_signal(source_tool="")
        errors = validate_numeric_signal(signal)
        assert any("source_tool" in e for e in errors)

    def test_invalid_source_tool(self) -> None:
        signal = _make_valid_signal(source_tool="unknown_tool")  # type: ignore[arg-type]
        errors = validate_numeric_signal(signal)
        assert any("source_tool" in e for e in errors)

    def test_missing_detector_id(self) -> None:
        signal = _make_valid_signal(detector_id="")
        errors = validate_numeric_signal(signal)
        assert any("detector_id" in e for e in errors)

    def test_missing_raw_kind(self) -> None:
        signal = _make_valid_signal(raw_kind="")
        errors = validate_numeric_signal(signal)
        assert any("raw_kind" in e for e in errors)

    def test_missing_canonical_category(self) -> None:
        signal = _make_valid_signal(canonical_category="")
        errors = validate_numeric_signal(signal)
        assert any("canonical_category" in e for e in errors)

    def test_missing_raw_payload_ref(self) -> None:
        signal = _make_valid_signal(raw_payload_ref="")
        errors = validate_numeric_signal(signal)
        assert any("raw_payload_ref" in e for e in errors)

    def test_mechanical_confidence_out_of_range(self) -> None:
        signal = _make_valid_signal(mechanical_confidence=1.5)
        errors = validate_numeric_signal(signal)
        assert any("mechanical_confidence" in e for e in errors)

    def test_mechanical_confidence_negative(self) -> None:
        signal = _make_valid_signal(mechanical_confidence=-0.1)
        errors = validate_numeric_signal(signal)
        assert any("mechanical_confidence" in e for e in errors)

    def test_negative_n(self) -> None:
        signal = _make_valid_signal(n=-5)
        errors = validate_numeric_signal(signal)
        assert any("n" in e and "non-negative" in e for e in errors)

    def test_evidence_locator_missing_source_path(self) -> None:
        signal = _make_valid_signal(
            evidence_locator=EvidenceLocator(source_path="")
        )
        errors = validate_numeric_signal(signal)
        assert any("source_path" in e for e in errors)

    def test_valid_signal_with_all_optional_fields(self) -> None:
        signal = _make_valid_signal(
            n=35,
            effect_size=0.75,
            mechanical_confidence=0.9,
            false_positive_context=["derived_or_unit_conversion"],
            prefilter_reason="deterministic relation prefilter matched",
            applicability_premise=ApplicabilityPremise(
                requires_integer_valued_items=True,
                requires_independent_rows=True,
                requires_raw_measurement=True,
            ),
            evidence_locator=EvidenceLocator(
                source_path="SourceData.xlsx",
                source_sha256="deadbeef",
                sheet="Source Data Fig.4",
                rows="5-39",
                cols="2-4",
            ),
        )
        errors = validate_numeric_signal(signal)
        assert errors == []


class TestNumericSignalSet:
    def test_empty_set(self) -> None:
        s = NumericSignalSet()
        assert len(s) == 0
        assert list(s) == []

    def test_add_and_iterate(self) -> None:
        s = NumericSignalSet()
        sig1 = _make_valid_signal(signal_id="NUM-SIG-0001")
        sig2 = _make_valid_signal(signal_id="NUM-SIG-0002")
        s.add(sig1)
        s.add(sig2)
        assert len(s) == 2
        assert s[0].signal_id == "NUM-SIG-0001"
        assert s[1].signal_id == "NUM-SIG-0002"

    def test_duplicate_id_raises(self) -> None:
        s = NumericSignalSet()
        s.add(_make_valid_signal(signal_id="NUM-SIG-0001"))
        with pytest.raises(ValueError, match="Duplicate signal_id"):
            s.add(_make_valid_signal(signal_id="NUM-SIG-0001"))

    def test_count_by_family(self) -> None:
        s = NumericSignalSet()
        s.add(_make_valid_signal(
            signal_id="NUM-SIG-0001",
            detector_family="column_relations",
        ))
        s.add(_make_valid_signal(
            signal_id="NUM-SIG-0002",
            detector_family="column_relations",
        ))
        s.add(_make_valid_signal(
            signal_id="NUM-SIG-0003",
            detector_family="statistical_impossibility",
        ))
        counts = s.count_by_family()
        assert counts["column_relations"] == 2
        assert counts["statistical_impossibility"] == 1

    def test_count_by_category(self) -> None:
        s = NumericSignalSet()
        s.add(_make_valid_signal(
            signal_id="NUM-SIG-0001",
            canonical_category="identical_column",
        ))
        s.add(_make_valid_signal(
            signal_id="NUM-SIG-0002",
            canonical_category="grim_inconsistent",
        ))
        counts = s.count_by_category()
        assert counts["identical_column"] == 1
        assert counts["grim_inconsistent"] == 1

    def test_count_by_risk(self) -> None:
        s = NumericSignalSet()
        s.add(_make_valid_signal(signal_id="NUM-SIG-0001", risk_level_raw="high"))
        s.add(_make_valid_signal(signal_id="NUM-SIG-0002", risk_level_raw="medium"))
        s.add(_make_valid_signal(signal_id="NUM-SIG-0003", risk_level_raw="high"))
        counts = s.count_by_risk()
        assert counts["high"] == 2
        assert counts["medium"] == 1

    def test_to_dict(self) -> None:
        s = NumericSignalSet()
        s.add(_make_valid_signal(signal_id="NUM-SIG-0001"))
        d = s.to_dict()
        assert d["schema_version"] == "1.0"
        assert d["total_signals"] == 1
        assert len(d["signals"]) == 1
        assert "counts_by_family" in d
        assert "counts_by_category" in d
        assert "counts_by_risk" in d

    def test_to_json_bytes(self) -> None:
        s = NumericSignalSet()
        s.add(_make_valid_signal(signal_id="NUM-SIG-0001"))
        raw = s.to_json_bytes()
        assert isinstance(raw, bytes)
        parsed = json.loads(raw)
        assert parsed["total_signals"] == 1

    def test_signals_property_returns_copy(self) -> None:
        s = NumericSignalSet()
        s.add(_make_valid_signal(signal_id="NUM-SIG-0001"))
        signals = s.signals
        assert len(signals) == 1
        # Modifying the returned list should not affect the set
        signals.clear()
        assert len(s) == 1

    def test_construct_with_initial_signals(self) -> None:
        sigs = [
            _make_valid_signal(signal_id="NUM-SIG-0001"),
            _make_valid_signal(signal_id="NUM-SIG-0002"),
        ]
        s = NumericSignalSet(sigs)
        assert len(s) == 2


class TestGenerateSignalId:
    def test_format(self) -> None:
        assert generate_signal_id(1) == "NUM-SIG-0001"
        assert generate_signal_id(42) == "NUM-SIG-0042"
        assert generate_signal_id(1234) == "NUM-SIG-1234"

    def test_large_counter(self) -> None:
        result = generate_signal_id(99999)
        assert result == "NUM-SIG-99999"
        assert result.startswith("NUM-SIG-")
