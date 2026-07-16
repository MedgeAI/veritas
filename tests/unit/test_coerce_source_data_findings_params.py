"""Characterization tests for source_data.findings parameter coercion.

These tests lock the contract of _coerce_source_data_findings_params before WP3
sinks it into ToolDefinition.param_coercer. Each case asserts that the old
(function-based) and new (tool.param_coercer-based) paths produce identical output.
"""

from __future__ import annotations

import pytest

from engine.tools.registry import (
    SOURCE_DATA_FINDINGS_TOOL_ID,
    TOOLS,
    _coerce_source_data_findings_params,
    coerce_tool_params,
)


def _old_path(params: dict) -> dict:
    """Pre-WP3 path: direct call to the module-level helper."""
    return _coerce_source_data_findings_params(params)


def _new_path(params: dict) -> dict:
    """Post-WP3 path: dispatch via coerce_tool_params -> tool.param_coercer."""
    return coerce_tool_params(SOURCE_DATA_FINDINGS_TOOL_ID, params)


def _assert_equivalent(params: dict, expected: dict | None = None) -> None:
    """Assert old and new paths produce identical output, optionally matching expected."""
    old_result = _old_path(params)
    new_result = _new_path(params)
    assert old_result == new_result, f"old={old_result!r} != new={new_result!r}"
    if expected is not None:
        assert old_result == expected


class TestSourceDataFindingsCoercionCharacterization:
    """10 input cases from PRD §WP3 契约."""

    def test_empty_input_returns_defaults(self) -> None:
        _assert_equivalent(
            {},
            {"min_overlap": 12, "min_support": 0.98, "max_findings_per_category": 200},
        )

    def test_full_valid_input(self) -> None:
        _assert_equivalent(
            {"min_overlap": 20, "min_support": 0.95, "max_findings_per_category": 100},
            {"min_overlap": 20, "min_support": 0.95, "max_findings_per_category": 100},
        )

    def test_boundary_min(self) -> None:
        """All parameters at their documented minimum."""
        _assert_equivalent(
            {"min_overlap": 8, "min_support": 0.90, "max_findings_per_category": 20},
            {"min_overlap": 8, "min_support": 0.90, "max_findings_per_category": 20},
        )

    def test_boundary_max(self) -> None:
        """All parameters at their documented maximum."""
        _assert_equivalent(
            {"min_overlap": 50, "min_support": 1.0, "max_findings_per_category": 500},
            {"min_overlap": 50, "min_support": 1.0, "max_findings_per_category": 500},
        )

    def test_below_bounds_raises(self) -> None:
        """Each parameter one step below its minimum must raise ValueError."""
        for bad_params in [
            {"min_overlap": 7},
            {"min_support": 0.89},
            {"max_findings_per_category": 19},
        ]:
            with pytest.raises(ValueError, match="must be between"):
                _old_path(bad_params)
            with pytest.raises(ValueError, match="must be between"):
                _new_path(bad_params)

    def test_above_bounds_raises(self) -> None:
        """Each parameter one step above its maximum must raise ValueError."""
        for bad_params in [
            {"min_overlap": 51},
            {"min_support": 1.01},
            {"max_findings_per_category": 501},
        ]:
            with pytest.raises(ValueError, match="must be between"):
                _old_path(bad_params)
            with pytest.raises(ValueError, match="must be between"):
                _new_path(bad_params)

    def test_string_to_numeric_coercion(self) -> None:
        """String representations of numbers are coerced to int/float."""
        _assert_equivalent(
            {
                "min_overlap": "14",
                "min_support": "0.97",
                "max_findings_per_category": "80",
            },
            {"min_overlap": 14, "min_support": 0.97, "max_findings_per_category": 80},
        )

    def test_invalid_type_raises(self) -> None:
        """Non-numeric strings cannot be coerced and must raise ValueError."""
        for bad_params in [
            {"min_overlap": "abc"},
            {"min_support": "not-a-number"},
            {"max_findings_per_category": None},
        ]:
            with pytest.raises(ValueError):
                _old_path(bad_params)
            with pytest.raises(ValueError):
                _new_path(bad_params)

    def test_partial_input_fills_defaults(self) -> None:
        """Providing only one field leaves the other two at their defaults."""
        _assert_equivalent(
            {"min_overlap": 30},
            {"min_overlap": 30, "min_support": 0.98, "max_findings_per_category": 200},
        )
        _assert_equivalent(
            {"min_support": 0.93},
            {"min_overlap": 12, "min_support": 0.93, "max_findings_per_category": 200},
        )
        _assert_equivalent(
            {"max_findings_per_category": 50},
            {"min_overlap": 12, "min_support": 0.98, "max_findings_per_category": 50},
        )

    def test_float_to_int_truncation(self) -> None:
        """Floats passed to integer fields are truncated (Python int() semantics)."""
        _assert_equivalent(
            {"min_overlap": 14.9, "max_findings_per_category": 79.1},
            {"min_overlap": 14, "min_support": 0.98, "max_findings_per_category": 79},
        )


class TestParamCoercerFieldContract:
    """Lock the contract that tool.param_coercer is wired after WP3."""

    def test_param_coercer_field_exists(self) -> None:
        tool = TOOLS[SOURCE_DATA_FINDINGS_TOOL_ID]
        assert hasattr(tool, "param_coercer"), "ToolDefinition must have param_coercer field"

    def test_param_coercer_is_callable(self) -> None:
        tool = TOOLS[SOURCE_DATA_FINDINGS_TOOL_ID]
        assert tool.param_coercer is not None, "source_data.findings must have a param_coercer"
        assert callable(tool.param_coercer)

    def test_param_coercer_matches_helper(self) -> None:
        """After WP3, tool.param_coercer must produce identical output to the old helper."""
        tool = TOOLS[SOURCE_DATA_FINDINGS_TOOL_ID]
        params = {"min_overlap": "25", "min_support": "0.96", "max_findings_per_category": "150"}
        assert tool.param_coercer(params) == _coerce_source_data_findings_params(params)
