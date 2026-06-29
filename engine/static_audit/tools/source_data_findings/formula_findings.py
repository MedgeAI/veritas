"""Formula-pattern detection in source-data columns."""

from __future__ import annotations

import re
from collections import Counter

from ._shared import (
    FORMULA_REF_RE,
    SheetVectors,
    col_to_name,
    column_label,
)


def formula_pattern(formula: str) -> str:
    return FORMULA_REF_RE.sub(lambda match: f"{match.group(1)}<row>", formula)


def referenced_columns(formulas: list[str]) -> list[str]:
    columns = []
    for formula in formulas:
        for match in FORMULA_REF_RE.finditer(formula):
            name = match.group(1)
            if name not in columns:
                columns.append(name)
    return columns


def _adjacent_row_rate(col: int, formulas: list[dict]) -> float:
    """Fraction of formulas that reference the same column at an adjacent row.

    For example, B25=B24*0.9 references column B at row 24, which is adjacent
    to the cell's own row 25.  A high rate indicates chained derivation.
    """
    if not formulas:
        return 0.0
    col_name = col_to_name(col)
    adjacent = 0
    for item in formulas:
        ref = item.get("ref", "")
        formula_text = item.get("formula", "")
        ref_match = re.match(r"\$?([A-Z]+)\$?(\d+)", ref)
        if not ref_match:
            continue
        target_row = int(ref_match.group(2))
        for match in FORMULA_REF_RE.finditer(formula_text):
            if (
                match.group(1) == col_name
                and abs(int(match.group(2)) - target_row) == 1
            ):
                adjacent += 1
                break
    return adjacent / len(formulas)


def formula_findings(sheet: SheetVectors, limit: int) -> list[dict]:
    findings = []
    for col, formulas in sorted(sheet.formulas_by_column.items()):
        patterns = Counter(formula_pattern(item["formula"]) for item in formulas)
        top_pattern, top_count = patterns.most_common(1)[0]
        refs = referenced_columns([item["formula"] for item in formulas])
        formula_count = len(formulas)
        adjacent_rate = _adjacent_row_rate(col, formulas)
        if formula_count >= 5 and adjacent_rate >= 0.5:
            risk = "high"
        elif formula_count >= 3:
            risk = "medium"
        else:
            risk = "low"
        findings.append(
            {
                "finding_id": None,
                "category": "formula_derived_column",
                "risk_level": risk,
                "confidence": "high",
                "workbook": sheet.workbook,
                "sheet": sheet.sheet,
                "target_column": col_to_name(col),
                "target_column_label": column_label(sheet, col),
                "formula_count": len(formulas),
                "dominant_formula_pattern": top_pattern,
                "dominant_formula_support": f"{top_count}/{len(formulas)}",
                "referenced_columns": refs,
                "sample_formulas": formulas[:10],
                "benign_explanations": [
                    "公式列通常是派生指标或单位换算，不应直接视为异常。",
                    "需要确认论文图表是否引用公式结果还是原始测量值。",
                ],
                "pressure_test_result": "traceability_item_not_anomaly",
                "next_steps": [
                    "将目标列映射到 figure panel 和论文 claim。",
                    "复算公式并核对图表展示值。",
                ],
            }
        )
    return findings[:limit]
