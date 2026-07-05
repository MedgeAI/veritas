"""Tests for the PaperConan Translator (WP2).

Verifies that:
- translate_paperconan_scan produces correct NumericSignals for each detector family
- Every signal has a valid raw_payload_ref tracing back to the original scan
- The translation ledger records all decisions (translated and skipped)
- Scan errors are translated into diagnostic signals
- All coverage matrix kinds are covered by the translator
- Synthetic fixtures exercise all translation paths
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.static_audit.adapters.paperconan_adapter.translator import (
    TranslationResult,
    translate_paperconan_scan,
)
from engine.static_audit.numeric_signal_schema import (
    validate_numeric_signal,
)


def _make_synthetic_scan_result() -> dict:
    """Create a synthetic paperconan scan result covering all translation paths.

    This fixture exercises:
    - relations_blocks with relations, progressions, equal_pairs, row_pairs,
      within_col, identical_after_rounding, grim
    - cross_sheet_findings
    - digit_distribution
    - decimal_endings
    - scan_errors
    """
    return {
        "tool": "paperconan",
        "tool_version": "0.9.0-test",
        "profile": "review",
        "relations_blocks": [
            {
                "file": "SourceData.xlsx",
                "sheet": "Sheet1",
                "block": {"rows": "1-20", "cols": "A-C"},
                "relations": [
                    {
                        "kind": "identical_column",
                        "severity": "high",
                        "rule": "col[1] == col[2] in 18/20 rows",
                        "n": 20,
                        "col_a": "Control",
                        "col_b": "Treatment",
                        "evidence_confidence": 0.95,
                        "profile_action": "kept",
                        "false_positive_context": [],
                        "prefilter_reason": "",
                    },
                    {
                        "kind": "constant_offset",
                        "severity": "medium",
                        "rule": "col[1] - col[2] = 5.0 constant",
                        "n": 15,
                        "col_a": "A",
                        "col_b": "B",
                        "evidence_confidence": 0.8,
                        "profile_action": "demoted",
                        "false_positive_context": ["unit_conversion"],
                        "prefilter_reason": "deterministic unit conversion relation",
                    },
                ],
                "progressions": [
                    {
                        "kind": "arithmetic_progression",
                        "severity": "medium",
                        "rule": "col[0]: 1,2,3,...,10 perfect progression",
                        "n": 10,
                        "col": "Time",
                        "profile_action": "kept",
                    },
                ],
                "equal_pairs": [
                    {
                        "kind": "many_equal_pairs",
                        "severity": "high",
                        "rule": "col[1] == col[3] in 12/15 rows",
                        "n": 15,
                        "equal": 12,
                        "col_a": "X",
                        "col_b": "Y",
                        "profile_action": "kept",
                    },
                ],
                "row_pairs": [
                    {
                        "kind": "row_pair_digit_coupling",
                        "severity": "high",
                        "rule": "rows 3,5 share low-order digits in 14/16 cells",
                        "n": 16,
                        "profile_action": "kept",
                    },
                ],
                "within_col": [
                    {
                        "kind": "within_col_value_duplication",
                        "severity": "high",
                        "rule": "col[2]: value 3.14 appears 15/20 times",
                        "n": 20,
                        "col": "Measurement",
                        "profile_action": "kept",
                        "false_positive_context": [],
                    },
                    {
                        "kind": "within_col_decimal_repetition",
                        "severity": "high",
                        "rule": "col[2]: .23 appears 14/18 times",
                        "n": 18,
                        "col": "Value",
                        "profile_action": "kept",
                    },
                ],
                "identical_after_rounding": [
                    {
                        "kind": "identical_after_rounding",
                        "severity": "medium",
                        "rule": "8 cells round to 4.3 but have 5 distinct values",
                        "n_cells": 8,
                        "profile_action": "kept",
                    },
                ],
                "grim": [
                    {
                        "kind": "grim_inconsistent",
                        "severity": "high",
                        "rule": "reported mean 3.45 not achievable for n=7 integers",
                        "n": 7,
                        "profile_action": "kept",
                        "false_positive_context": [],
                    },
                ],
            },
        ],
        "cross_sheet_findings": [
            {
                "kind": "cross_sheet_position_identical",
                "severity": "high",
                "file": "SourceData.xlsx",
                "sheet_a": "Sheet1",
                "sheet_b": "Sheet2",
                "rule": "25 identical values at same positions across sheets",
                "n": 25,
                "profile_action": "kept",
            },
            {
                "kind": "cross_sheet_decimal_tail_reuse",
                "severity": "medium",
                "file": "SourceData.xlsx",
                "sheet_a": "Table1",
                "sheet_b": "Table3",
                "rule": "12 values share last-2 decimals .47 across sheets",
                "n": 12,
                "profile_action": "kept",
            },
        ],
        "digit_distribution": [
            {
                "label": "Sheet1::Measurement",
                "n": 200,
                "chi2": 25.3,
                "p": 0.001,
                "p_adj": 0.005,
                "fdr_significant": True,
                "counts": {"0": 20, "1": 25, "2": 22, "3": 18, "4": 30, "5": 15, "6": 28, "7": 12, "8": 10, "9": 20},
                "top": [["4", 30], ["6", 28], ["1", 25]],
            },
            {
                "label": "Sheet1::Noise",
                "n": 100,
                "chi2": 5.2,
                "p": 0.73,
                "p_adj": 0.95,
                "fdr_significant": False,
                "counts": {"0": 11, "1": 12, "2": 10, "3": 11, "4": 9, "5": 12, "6": 11, "7": 10, "8": 7, "9": 7},
                "top": [["1", 12], ["5", 12], ["0", 11]],
            },
        ],
        "decimal_endings": [
            {
                "label": "Sheet1::Value",
                "n": 150,
                "n_unique": 25,
                "top": [["23", 45], ["67", 30], ["45", 10]],
            },
            {
                "label": "Sheet2::Control",
                "n": 80,
                "n_unique": 40,
                "top": [],
            },
        ],
        "scan_errors": [
            {"file": "broken_file.xlsx", "error": "Unable to parse sheet 'Corrupted'"},
        ],
    }


class TestTranslatePaperconanScan:
    def test_basic_translation(self) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        assert isinstance(result, TranslationResult)
        assert len(result.signals) > 0
        assert len(result.ledger) > 0

    def test_all_block_finding_keys_translated(self) -> None:
        """Every finding key in relations_blocks should produce signals."""
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)

        families = {s.detector_family for s in result.signals}
        assert "column_relations" in families
        assert "progressions" in families or any(s.raw_kind == "arithmetic_progression" for s in result.signals)
        assert "copy_tweak_fingerprints" in families
        assert "within_column" in families
        assert "statistical_impossibility" in families

    def test_cross_sheet_translated(self) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        cross_sheet_signals = [s for s in result.signals if s.detector_family == "cross_sheet"]
        assert len(cross_sheet_signals) == 2
        kinds = {s.raw_kind for s in cross_sheet_signals}
        assert "cross_sheet_position_identical" in kinds
        assert "cross_sheet_decimal_tail_reuse" in kinds

    def test_digit_distribution_translated(self) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan, profile="review")
        digit_signals = [s for s in result.signals if s.raw_kind == "last_digit_chi_square"]
        # Only the significant one (p=0.001) should be translated in review profile
        assert len(digit_signals) == 1
        assert digit_signals[0].extra.get("p") == 0.001
        assert digit_signals[0].extra.get("fdr_significant") is True

    def test_digit_distribution_forensic_keeps_all(self) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan, profile="forensic")
        digit_signals = [s for s in result.signals if s.raw_kind == "last_digit_chi_square"]
        # Forensic profile should keep all entries
        assert len(digit_signals) == 2

    def test_decimal_endings_translated(self) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        decimal_signals = [s for s in result.signals if s.raw_kind == "repeated_two_decimal_endings"]
        # Only the one with top repetitions
        assert len(decimal_signals) == 1

    def test_scan_errors_translated(self) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        error_signals = [s for s in result.signals if s.detector_family == "scan_errors"]
        assert len(error_signals) == 1
        assert error_signals[0].extra.get("file") == "broken_file.xlsx"
        assert result.scan_errors == [{"file": "broken_file.xlsx", "error": "Unable to parse sheet 'Corrupted'"}]

    def test_all_signals_have_raw_payload_ref(self) -> None:
        """Every signal must have a raw_payload_ref pointing to the scan."""
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        for signal in result.signals:
            assert signal.raw_payload_ref, f"Signal {signal.signal_id} missing raw_payload_ref"
            # raw_payload_ref should be a path-like string
            assert "/" in signal.raw_payload_ref or signal.raw_payload_ref.startswith("scan_errors/")

    def test_all_signals_pass_validation(self) -> None:
        """Every translated signal must pass the schema validator."""
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        for signal in result.signals:
            errors = validate_numeric_signal(signal)
            assert not errors, f"Signal {signal.signal_id} failed validation: {errors}"

    def test_ledger_records_all_decisions(self) -> None:
        """Ledger should have an entry for every finding encountered."""
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        # Count: 2 relations + 1 progression + 1 equal_pairs + 1 row_pairs +
        #        2 within_col + 1 identical_after_rounding + 1 grim +
        #        2 cross_sheet + 2 digit_distribution + 2 decimal_endings + 1 scan_error
        # = 16 total entries
        translated = sum(1 for e in result.ledger if e.action == "translated")
        skipped = sum(1 for e in result.ledger if e.action == "skipped")
        total = translated + skipped
        assert total == len(result.ledger)
        assert translated > 0
        # At least the non-significant digit_distribution and empty-top decimal_endings should be skipped
        assert skipped > 0

    def test_ledger_entries_have_required_fields(self) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        for entry in result.ledger:
            assert entry.raw_payload_ref
            assert entry.action in ("translated", "skipped")
            if entry.action == "translated":
                assert entry.signal_id
            d = entry.to_dict()
            assert "raw_payload_ref" in d
            assert "action" in d

    def test_profile_action_preserved(self) -> None:
        """Profile actions from paperconan should be preserved in signals."""
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        # The constant_offset finding had profile_action="demoted"
        demoted = [s for s in result.signals if s.profile_action == "demoted"]
        assert len(demoted) >= 1

    def test_false_positive_context_preserved(self) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        # The constant_offset finding had false_positive_context=["unit_conversion"]
        fp_signals = [s for s in result.signals if "unit_conversion" in s.false_positive_context]
        assert len(fp_signals) >= 1

    def test_prefilter_reason_preserved(self) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        reason_signals = [s for s in result.signals if s.prefilter_reason]
        assert len(reason_signals) >= 1

    def test_evidence_locator_built(self) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        block_signals = [
            s for s in result.signals
            if s.detector_family in ("column_relations", "progressions", "within_column", "statistical_impossibility")
        ]
        for signal in block_signals:
            assert signal.evidence_locator is not None
            assert signal.evidence_locator.source_path == "SourceData.xlsx"
            assert signal.evidence_locator.sheet == "Sheet1"
            assert signal.evidence_locator.rows == "1-20"

    def test_applicability_premise_for_grim(self) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        grim_signals = [s for s in result.signals if s.raw_kind == "grim_inconsistent"]
        assert len(grim_signals) == 1
        premise = grim_signals[0].applicability_premise
        assert premise is not None
        assert premise.requires_integer_valued_items is True
        assert premise.requires_independent_rows is True

    def test_empty_scan_result(self) -> None:
        scan = {
            "tool": "paperconan",
            "tool_version": "0.9.0",
            "relations_blocks": [],
            "cross_sheet_findings": [],
            "digit_distribution": [],
            "decimal_endings": [],
            "scan_errors": [],
        }
        result = translate_paperconan_scan(scan)
        assert len(result.signals) == 0
        assert len(result.ledger) == 0
        assert result.scan_errors == []

    def test_missing_sections_handled(self) -> None:
        """Missing sections should not crash; treated as empty."""
        scan = {"tool": "paperconan", "tool_version": "0.9.0"}
        result = translate_paperconan_scan(scan)
        assert len(result.signals) == 0

    def test_finding_with_empty_kind_skipped(self) -> None:
        scan = {
            "tool": "paperconan",
            "tool_version": "0.9.0",
            "relations_blocks": [
                {
                    "file": "test.xlsx",
                    "sheet": "Sheet1",
                    "block": {"rows": "1-10", "cols": "A-B"},
                    "relations": [
                        {"kind": "", "severity": "high", "rule": "no kind"},
                    ],
                    "progressions": [],
                    "equal_pairs": [],
                    "row_pairs": [],
                    "within_col": [],
                    "identical_after_rounding": [],
                    "grim": [],
                },
            ],
            "cross_sheet_findings": [],
            "digit_distribution": [],
            "decimal_endings": [],
            "scan_errors": [],
        }
        result = translate_paperconan_scan(scan)
        assert len(result.signals) == 0
        skipped = [e for e in result.ledger if e.action == "skipped"]
        assert len(skipped) == 1
        assert "empty kind" in skipped[0].reason


class TestTranslationResult:
    def test_write_artifacts(self, tmp_path: Path) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        signals_path, ledger_path = result.write_artifacts(tmp_path)

        assert signals_path.exists()
        assert ledger_path.exists()

        # Verify JSON validity
        signals_data = json.loads(signals_path.read_text())
        ledger_data = json.loads(ledger_path.read_text())

        assert "signals" in signals_data
        assert "entries" in ledger_data
        assert signals_data["total_signals"] == len(result.signals)

    def test_to_dict(self) -> None:
        scan = _make_synthetic_scan_result()
        result = translate_paperconan_scan(scan)
        d = result.to_dict()
        assert d["schema_version"] == "1.0"
        assert d["total_signals"] == len(result.signals)
        assert d["translated_count"] > 0
        assert "ledger" in d
        assert "signals" in d


class TestKindCoverage:
    """Verify the translator handles all kinds from the coverage matrix."""

    def test_all_relations_block_kinds(self) -> None:
        """Test each relations_block finding key produces correct family."""
        for finding_key, expected_kind in [
            ("relations", "identical_column"),
            ("progressions", "arithmetic_progression"),
            ("equal_pairs", "many_equal_pairs"),
            ("row_pairs", "row_pair_digit_coupling"),
            ("within_col", "within_col_value_duplication"),
            ("identical_after_rounding", "identical_after_rounding"),
            ("grim", "grim_inconsistent"),
        ]:
            scan = {
                "tool": "paperconan",
                "tool_version": "test",
                "relations_blocks": [
                    {
                        "file": "test.xlsx",
                        "sheet": "Sheet1",
                        "block": {"rows": "1-10", "cols": "A-B"},
                        "relations": [],
                        "progressions": [],
                        "equal_pairs": [],
                        "row_pairs": [],
                        "within_col": [],
                        "identical_after_rounding": [],
                        "grim": [],
                        finding_key: [
                            {
                                "kind": expected_kind,
                                "severity": "high",
                                "rule": f"test rule for {expected_kind}",
                                "n": 10,
                                "profile_action": "kept",
                            },
                        ],
                    },
                ],
                "cross_sheet_findings": [],
                "digit_distribution": [],
                "decimal_endings": [],
                "scan_errors": [],
            }
            result = translate_paperconan_scan(scan)
            signals = [s for s in result.signals if s.raw_kind == expected_kind]
            assert len(signals) == 1, (
                f"finding_key={finding_key}, kind={expected_kind}: "
                f"expected 1 signal, got {len(signals)}"
            )
            assert signals[0].raw_payload_ref == f"relations_blocks/0/{finding_key}/0"

    def test_cross_sheet_kinds(self) -> None:
        for kind in [
            "cross_sheet_position_identical",
            "cross_sheet_value_overlap",
            "cross_sheet_decimal_tail_reuse",
            "cross_sheet_column_duplicate",
        ]:
            scan = {
                "tool": "paperconan",
                "tool_version": "test",
                "relations_blocks": [],
                "cross_sheet_findings": [
                    {
                        "kind": kind,
                        "severity": "high",
                        "file": "test.xlsx",
                        "sheet_a": "S1",
                        "sheet_b": "S2",
                        "rule": f"test {kind}",
                        "n": 10,
                        "profile_action": "kept",
                    },
                ],
                "digit_distribution": [],
                "decimal_endings": [],
                "scan_errors": [],
            }
            result = translate_paperconan_scan(scan)
            signals = [s for s in result.signals if s.raw_kind == kind]
            assert len(signals) == 1, f"kind={kind}: expected 1 signal, got {len(signals)}"
