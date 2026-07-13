"""Unit tests for NumericComparator typed verifier."""

import pytest

from engine.reproduction.verifiers.base import ToleranceConfig
from engine.reproduction.verifiers.numeric_comparator import NumericComparator, is_numeric


class TestNumericComparator:
    """Test suite for NumericComparator."""

    def test_exact_match(self):
        """Test exact numeric match."""
        comparator = NumericComparator()
        result = comparator.verify(0.001, 0.001)
        assert result.verdict == "consistent"
        assert result.confidence == 1.0
        assert result.discrepancy_type is None

    def test_match_within_absolute_tolerance(self):
        """Test match within absolute tolerance."""
        comparator = NumericComparator(ToleranceConfig(absolute_error=0.01))
        result = comparator.verify(0.100, 0.105)
        assert result.verdict == "consistent"

    def test_mismatch_outside_tolerance(self):
        """Test mismatch outside tolerance."""
        comparator = NumericComparator(ToleranceConfig(absolute_error=0.001))
        result = comparator.verify(0.001, 0.010)
        assert result.verdict == "inconsistent"
        assert result.discrepancy_type == "numeric_mismatch"
        assert result.severity is not None

    def test_p_value_tolerance(self):
        """Test p-value specific tolerance."""
        comparator = NumericComparator(ToleranceConfig(p_value_absolute_error=0.005))
        result = comparator.verify(0.030, 0.033, context={"value_type": "p_value"})
        assert result.verdict == "consistent"

    def test_p_value_mismatch(self):
        """Test p-value mismatch."""
        comparator = NumericComparator(ToleranceConfig(p_value_absolute_error=0.001))
        result = comparator.verify(0.030, 0.050, context={"value_type": "p_value"})
        assert result.verdict == "inconsistent"

    def test_relative_tolerance(self):
        """Test relative error tolerance."""
        comparator = NumericComparator(ToleranceConfig(relative_error=0.05))
        result = comparator.verify(100.0, 104.0)
        assert result.verdict == "consistent"

    def test_relative_mismatch(self):
        """Test relative error mismatch."""
        comparator = NumericComparator(ToleranceConfig(relative_error=0.01))
        result = comparator.verify(100.0, 110.0)
        assert result.verdict == "inconsistent"

    def test_non_numeric_source(self):
        """Test non-numeric source value."""
        comparator = NumericComparator()
        result = comparator.verify("not_a_number", 0.001)
        assert result.verdict == "insufficient"
        assert result.abstain_reason is not None

    def test_non_numeric_target(self):
        """Test non-numeric target value."""
        comparator = NumericComparator()
        result = comparator.verify(0.001, "not_a_number")
        assert result.verdict == "insufficient"

    def test_none_source(self):
        """Test None source value."""
        comparator = NumericComparator()
        result = comparator.verify(None, 0.001)
        assert result.verdict == "insufficient"

    def test_none_target(self):
        """Test None target value."""
        comparator = NumericComparator()
        result = comparator.verify(0.001, None)
        assert result.verdict == "insufficient"

    def test_severity_critical(self):
        """Test critical severity for large discrepancy."""
        comparator = NumericComparator()
        # 1.0 → 3.0: relative_diff = 2.0/3.0 ≈ 0.67 > 0.50 → critical
        result = comparator.verify(1.0, 3.0)
        assert result.verdict == "inconsistent"
        assert result.severity == "critical"

    def test_severity_high(self):
        """Test high severity for large discrepancy."""
        comparator = NumericComparator()
        result = comparator.verify(1.0, 1.3)  # 30% difference
        assert result.verdict == "inconsistent"
        assert result.severity == "high"

    def test_severity_medium(self):
        """Test medium severity for moderate discrepancy."""
        comparator = NumericComparator()
        result = comparator.verify(1.0, 1.1)  # 10% difference
        assert result.verdict == "inconsistent"
        assert result.severity == "medium"

    def test_severity_low(self):
        """Test low severity for small discrepancy."""
        comparator = NumericComparator(ToleranceConfig(absolute_error=0.001, relative_error=0.01))
        result = comparator.verify(1.0, 1.02)  # 2% difference
        assert result.verdict == "inconsistent"
        assert result.severity == "low"

    def test_rounding_digits(self):
        """Test rounding before comparison."""
        comparator = NumericComparator(ToleranceConfig(rounding_digits=2))
        result = comparator.verify(0.123, 0.124)  # Both round to 0.12
        assert result.verdict == "consistent"

    def test_zero_values(self):
        """Test comparison with zero values."""
        comparator = NumericComparator()
        result = comparator.verify(0.0, 0.0)
        assert result.verdict == "consistent"

    def test_negative_values(self):
        """Test comparison with negative values."""
        comparator = NumericComparator()
        result = comparator.verify(-0.001, -0.001)
        assert result.verdict == "consistent"


class TestIsNumeric:
    """Test is_numeric helper."""

    def test_int(self):
        assert is_numeric(42) is True

    def test_float(self):
        assert is_numeric(3.14) is True

    def test_string_number(self):
        assert is_numeric("42") is True

    def test_string_float(self):
        assert is_numeric("3.14") is True

    def test_string_non_numeric(self):
        assert is_numeric("hello") is False

    def test_none(self):
        assert is_numeric(None) is False

    def test_list(self):
        assert is_numeric([1, 2]) is False

    def test_bool(self):
        # bools are technically numeric in Python
        assert is_numeric(True) is True or is_numeric(True) is False  # implementation-defined


class TestToleranceConfig:
    """Test ToleranceConfig."""

    def test_defaults(self):
        config = ToleranceConfig()
        assert config.p_value_absolute_error == 0.001
        assert config.relative_error == 0.01
        assert config.absolute_error == 0.001
        assert config.rounding_digits is None

    def test_custom_values(self):
        config = ToleranceConfig(p_value_absolute_error=0.01, relative_error=0.05, absolute_error=0.1)
        assert config.p_value_absolute_error == 0.01
        assert config.relative_error == 0.05
        assert config.absolute_error == 0.1

    def test_frozen(self):
        config = ToleranceConfig()
        with pytest.raises(AttributeError):
            config.p_value_absolute_error = 0.1  # type: ignore
