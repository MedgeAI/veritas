"""Tests for the PaperConan detector coverage matrix (WP0).

Verifies that configs/paperconan_detector_coverage.yaml:
- Is valid YAML
- Contains all required PaperConan detector kinds
- Has valid status tags for every entry
- Covers all families listed in the PRD
"""

from __future__ import annotations

from pathlib import Path

import yaml

_COVERAGE_PATH = Path(__file__).parents[2] / "configs" / "paperconan_detector_coverage.yaml"

_VALID_STATUSES = frozenset({
    "translated",
    "native_equivalent",
    "native_superset",
    "planned",
    "not_applicable",
})

# All PaperConan detector kinds that must appear in the coverage matrix.
# Derived from paperconan source code (grep for kind= in _audit.py).
_REQUIRED_KINDS = frozenset({
    # column_relations
    "identical_column",
    "constant_offset",
    "constant_ratio",
    "exact_linear",
    "sum_constant",
    "small_diff_set",
    "partial_constant_offset",
    # copy_tweak_fingerprints
    "integer_diff_shared_fraction",
    "row_pair_digit_coupling",
    "many_equal_pairs",
    "identical_after_rounding",
    # within_column
    "within_col_value_duplication",
    "within_col_decimal_repetition",
    "rounded_to_half_or_int",
    "missing_last_digits",
    "repeated_two_decimal_endings",
    # cross_sheet
    "cross_sheet_position_identical",
    "cross_sheet_value_overlap",
    "cross_sheet_decimal_tail_reuse",
    "cross_sheet_column_duplicate",
    # matrix_vector_reuse
    "within_table_fraction_reuse",
    "recurring_row_vector",
    # statistical_impossibility
    "grim_inconsistent",
    "grimmer_inconsistent",
    # digit_statistics
    "last_digit_chi_square",
    # progressions
    "arithmetic_progression",
    # scan_errors
    "scan_error",
})


def _load_coverage() -> dict:
    assert _COVERAGE_PATH.exists(), f"Coverage matrix not found at {_COVERAGE_PATH}"
    with open(_COVERAGE_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), "Coverage matrix must be a YAML dict"
    return data


def _collect_all_kinds(data: dict) -> list[str]:
    """Extract all kind values from the coverage matrix."""
    kinds = []
    for family_name, family_entries in data.items():
        if family_name == "schema_version":
            continue
        if isinstance(family_entries, list):
            for entry in family_entries:
                if isinstance(entry, dict) and "kind" in entry:
                    kinds.append(entry["kind"])
    return kinds


def test_coverage_matrix_exists() -> None:
    """Coverage matrix YAML file must exist."""
    assert _COVERAGE_PATH.exists()


def test_coverage_matrix_has_schema_version() -> None:
    """Coverage matrix must declare a schema_version."""
    data = _load_coverage()
    assert "schema_version" in data


def test_all_required_kinds_present() -> None:
    """Every PaperConan detector kind must appear in the coverage matrix."""
    data = _load_coverage()
    found_kinds = set(_collect_all_kinds(data))
    missing = _REQUIRED_KINDS - found_kinds
    assert not missing, f"Missing kinds in coverage matrix: {sorted(missing)}"


def test_all_entries_have_valid_status() -> None:
    """Every entry in the coverage matrix must have a valid status tag."""
    data = _load_coverage()
    for family_name, family_entries in data.items():
        if family_name == "schema_version":
            continue
        if not isinstance(family_entries, list):
            continue
        for entry in family_entries:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("kind", "?")
            status = entry.get("status")
            assert status in _VALID_STATUSES, (
                f"Kind {kind!r} in family {family_name!r} has invalid status {status!r}; "
                f"expected one of {sorted(_VALID_STATUSES)}"
            )


def test_all_entries_have_required_fields() -> None:
    """Every entry must have kind, family, status, and veritas_target."""
    data = _load_coverage()
    for family_name, family_entries in data.items():
        if family_name == "schema_version":
            continue
        if not isinstance(family_entries, list):
            continue
        for entry in family_entries:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("kind")
            assert kind, f"Entry in {family_name!r} missing 'kind' field"
            assert "family" in entry, f"Kind {kind!r} missing 'family' field"
            assert "status" in entry, f"Kind {kind!r} missing 'status' field"
            assert "veritas_target" in entry, f"Kind {kind!r} missing 'veritas_target' field"


def test_translated_kinds_have_notes() -> None:
    """All translated kinds should have explanatory notes."""
    data = _load_coverage()
    for family_name, family_entries in data.items():
        if family_name == "schema_version":
            continue
        if not isinstance(family_entries, list):
            continue
        for entry in family_entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("status") == "translated":
                kind = entry.get("kind", "?")
                assert entry.get("notes"), (
                    f"Translated kind {kind!r} in {family_name!r} missing notes"
                )


def test_no_duplicate_kinds() -> None:
    """No kind should appear more than once in the coverage matrix."""
    data = _load_coverage()
    all_kinds = _collect_all_kinds(data)
    duplicates = [k for k in all_kinds if all_kinds.count(k) > 1]
    assert not duplicates, f"Duplicate kinds in coverage matrix: {sorted(set(duplicates))}"
