"""Tests for source_data_findings pattern_strength field."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from engine.static_audit.tools.source_data_findings import (
    SheetVectors,
    duplicate_column_findings,
    fixed_relationship_findings,
    relationship_record,
)


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
    assert (
        result["pattern_strength_reason"]
        == "fixed_difference=0.3 covers 35/35 overlapping rows"
    )
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
    assert (
        result["pattern_strength_reason"]
        == "fixed_difference=0.5 covers 80/100 overlapping rows"
    )
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


def test_mean_sum_n_relationship_is_artifact_not_priority_signal() -> None:
    rows = list(range(10, 20))
    sheet = SheetVectors(
        workbook="source.xlsx",
        workbook_path="source.xlsx",
        sheet="Extended Data Fig. 3d",
        sheet_path="xl/worksheets/sheet1.xml",
        numeric_columns={
            4: {row: Decimal("100") for row in rows},
            5: {row: Decimal(row) for row in rows},
            7: {row: Decimal(row * 100) for row in rows},
        },
        text_columns={
            4: [(6, "N total")],
            5: [(6, "Mean"), (9, "Output voltage (V)")],
            7: [(6, "Sum"), (9, "Voltage (V)")],
        },
        formulas_by_column={},
        cell_count=30,
        numeric_cell_count=30,
    )

    findings = fixed_relationship_findings(
        sheet,
        min_overlap=8,
        min_support=0.98,
        limit=20,
    )
    finding = next(item for item in findings if item["category"] == "fixed_ratio")

    assert finding["risk_level"] == "low"
    assert finding["artifact_likelihood"] == "high"
    assert finding["artifact_reason"] == "Mean/Sum/N summary-statistics relationship"
    assert finding["pressure_test_result"] == "likely_summary_statistic_derivation"


def test_zero_inflated_duplicate_columns_are_downgraded() -> None:
    rows = list(range(1, 51))
    sheet = SheetVectors(
        workbook="source.xlsx",
        workbook_path="source.xlsx",
        sheet="Tumor free animals",
        sheet_path="xl/worksheets/sheet1.xml",
        numeric_columns={
            2: {row: Decimal("0") for row in rows},
            3: {row: Decimal("0") for row in rows},
        },
        text_columns={
            2: [(1, "Group A response")],
            3: [(1, "Group B response")],
        },
        formulas_by_column={},
        cell_count=100,
        numeric_cell_count=100,
    )
    sheet.numeric_columns[2][50] = Decimal("1")
    sheet.numeric_columns[3][50] = Decimal("2")

    findings = duplicate_column_findings(
        sheet,
        min_overlap=20,
        min_support=0.98,
        limit=20,
    )

    assert len(findings) == 1
    assert findings[0]["risk_level"] == "low"
    assert findings[0]["artifact_likelihood"] == "high"
    assert findings[0]["pressure_test_result"] == "likely_zero_inflated_matrix_artifact"


def test_mean_sum_labels_without_integer_n_relationship_are_not_downgraded() -> None:
    rows = list(range(10, 20))
    sheet = SheetVectors(
        workbook="source.xlsx",
        workbook_path="source.xlsx",
        sheet="Independent endpoint summary",
        sheet_path="xl/worksheets/sheet1.xml",
        numeric_columns={
            5: {row: Decimal(row) for row in rows},
            7: {row: Decimal(row) * Decimal("2.5") for row in rows},
        },
        text_columns={
            5: [(6, "Mean response")],
            7: [(6, "Sum response")],
        },
        formulas_by_column={},
        cell_count=20,
        numeric_cell_count=20,
    )

    findings = fixed_relationship_findings(
        sheet,
        min_overlap=8,
        min_support=0.98,
        limit=20,
    )
    finding = next(item for item in findings if item["category"] == "fixed_ratio")

    assert finding["risk_level"] == "medium"
    assert finding["artifact_likelihood"] == "unknown"
    assert finding["pressure_test_result"] == "needs_semantics_and_formula_review"


def test_duplicate_columns_below_zero_inflation_threshold_are_not_downgraded() -> None:
    rows = list(range(1, 21))
    sheet = SheetVectors(
        workbook="source.xlsx",
        workbook_path="source.xlsx",
        sheet="Endpoint matrix",
        sheet_path="xl/worksheets/sheet1.xml",
        numeric_columns={
            2: {},
            3: {},
        },
        text_columns={
            2: [(1, "Endpoint A")],
            3: [(1, "Endpoint B")],
        },
        formulas_by_column={},
        cell_count=40,
        numeric_cell_count=40,
    )
    for row in rows:
        value = Decimal("0") if row <= 13 else Decimal(row)
        sheet.numeric_columns[2][row] = value
        sheet.numeric_columns[3][row] = value

    findings = duplicate_column_findings(
        sheet,
        min_overlap=20,
        min_support=0.98,
        limit=20,
    )

    assert len(findings) == 1
    assert findings[0]["risk_level"] == "medium"
    assert findings[0]["artifact_likelihood"] == "unknown"
    assert findings[0]["pressure_test_result"] == "needs_column_semantics_review"
