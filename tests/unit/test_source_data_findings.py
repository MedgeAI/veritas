"""Tests for source_data_findings pattern_strength field."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from engine.static_audit.tools.source_data_findings import relationship_record


@dataclass
class MockSheetVectors:
    """Mock SheetVectors for testing."""
    workbook: str
    sheet: str
    numeric_columns: dict[int, list[Decimal]]
    text_columns: dict[int, list[tuple[int, str]]] = field(default_factory=dict)
    formulas: dict[int, list[tuple[int, str]]] = field(default_factory=dict)


def test_pattern_strength_complete_35_of_35():
    """Test pattern_strength='complete' when 35/35 rows have fixed_difference=0.3 (FD-0001 scenario)."""
    # Create mock data: 35 rows with fixed_difference=0.3
    left_col_data = [Decimal("0")] * 40  # 40 rows total
    right_col_data = [Decimal("0")] * 40

    # Fill rows 5-39 (35 rows) with fixed difference = 0.3
    for i in range(5, 40):
        left_col_data[i] = Decimal("1.0") + Decimal(str((i - 5) * 0.1))
        right_col_data[i] = left_col_data[i] - Decimal("0.3")

    sheet = MockSheetVectors(
        workbook="test_workbook.xlsx",
        sheet="Source Data Fig.4",
        numeric_columns={0: left_col_data, 1: right_col_data},
    )

    result = relationship_record(
        sheet=sheet,
        relationship="fixed_difference",
        left_col=0,
        right_col=1,
        value="0.3",
        support_rows=35,
        overlap_rows=35,
        rows=list(range(5, 40)),
        formula_cols=set(),
    )

    assert result["pattern_strength"] == "complete"
    assert result["pattern_strength_reason"] == "fixed_difference=0.3 covers 35/35 overlapping rows"
    assert result["support_rate"] == 1.0
    assert result["risk_level"] == "medium"  # 35 < 100, so medium


def test_pattern_strength_strong_80_percent():
    """Test pattern_strength='strong' when 80% of rows have fixed relationship."""
    left_col_data = [Decimal("0")] * 100
    right_col_data = [Decimal("0")] * 100

    # 80 rows with fixed difference, 20 rows without
    for i in range(100):
        left_col_data[i] = Decimal("1.0") + Decimal(str(i * 0.1))
        if i < 80:
            right_col_data[i] = left_col_data[i] - Decimal("0.5")
        else:
            right_col_data[i] = left_col_data[i] - Decimal("999")  # Different pattern

    sheet = MockSheetVectors(
        workbook="test_workbook.xlsx",
        sheet="Test Sheet",
        numeric_columns={0: left_col_data, 1: right_col_data},
    )

    result = relationship_record(
        sheet=sheet,
        relationship="fixed_difference",
        left_col=0,
        right_col=1,
        value="0.5",
        support_rows=80,
        overlap_rows=100,
        rows=list(range(100)),
        formula_cols=set(),
    )

    assert result["pattern_strength"] == "strong"
    assert result["pattern_strength_reason"] == "fixed_difference=0.5 covers 80/100 overlapping rows"
    assert result["support_rate"] == 0.8
    assert result["risk_level"] == "medium"  # 80 < 100, so medium


def test_pattern_strength_high_when_support_rows_ge_100():
    """Test risk_level='high' when support_rows >= 100, regardless of pattern_strength."""
    left_col_data = [Decimal("0")] * 150
    right_col_data = [Decimal("0")] * 150

    # 100 rows with fixed difference
    for i in range(150):
        left_col_data[i] = Decimal("1.0") + Decimal(str(i * 0.1))
        if i < 100:
            right_col_data[i] = left_col_data[i] - Decimal("0.2")
        else:
            right_col_data[i] = left_col_data[i] - Decimal("999")

    sheet = MockSheetVectors(
        workbook="test_workbook.xlsx",
        sheet="Test Sheet",
        numeric_columns={0: left_col_data, 1: right_col_data},
    )

    result = relationship_record(
        sheet=sheet,
        relationship="fixed_difference",
        left_col=0,
        right_col=1,
        value="0.2",
        support_rows=100,
        overlap_rows=150,
        rows=list(range(150)),
        formula_cols=set(),
    )

    assert result["pattern_strength"] == "moderate"  # 100/150 = 66.7% -> moderate
    assert result["risk_level"] == "high"  # 100 >= 100, so high
    assert result["support_rate"] == round(100 / 150, 4)


def test_pattern_strength_with_formula_column():
    """Test pattern_strength when formula column is involved (risk_level='low')."""
    left_col_data = [Decimal("0")] * 50
    right_col_data = [Decimal("0")] * 50

    # 50 rows with fixed difference
    for i in range(50):
        left_col_data[i] = Decimal("1.0") + Decimal(str(i * 0.1))
        right_col_data[i] = left_col_data[i] - Decimal("0.4")

    sheet = MockSheetVectors(
        workbook="test_workbook.xlsx",
        sheet="Test Sheet",
        numeric_columns={0: left_col_data, 1: right_col_data},
    )

    result = relationship_record(
        sheet=sheet,
        relationship="fixed_difference",
        left_col=0,
        right_col=1,
        value="0.4",
        support_rows=50,
        overlap_rows=50,
        rows=list(range(50)),
        formula_cols={1},  # right_col (1) is a formula column
    )

    assert result["pattern_strength"] == "complete"  # 50/50 = 100%
    assert result["risk_level"] == "low"  # formula_involved -> low
    assert result["formula_column_involved"] is True
    assert result["artifact_likelihood"] == "medium"


def test_pattern_strength_moderate_and_weak():
    """Test pattern_strength='moderate' and 'weak' scenarios."""
    # Moderate: 60% coverage
    sheet = MockSheetVectors(
        workbook="test_workbook.xlsx",
        sheet="Test Sheet",
        numeric_columns={0: [Decimal("0")] * 100, 1: [Decimal("0")] * 100},
    )

    result = relationship_record(
        sheet=sheet,
        relationship="fixed_ratio",
        left_col=0,
        right_col=1,
        value="1.5",
        support_rows=60,
        overlap_rows=100,
        rows=list(range(100)),
        formula_cols=set(),
    )

    assert result["pattern_strength"] == "moderate"
    assert result["support_rate"] == 0.6

    # Weak: 30% coverage
    result = relationship_record(
        sheet=sheet,
        relationship="fixed_ratio",
        left_col=0,
        right_col=1,
        value="1.5",
        support_rows=30,
        overlap_rows=100,
        rows=list(range(100)),
        formula_cols=set(),
    )

    assert result["pattern_strength"] == "weak"
    assert result["support_rate"] == 0.3
