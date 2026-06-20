from __future__ import annotations

import json
import zipfile
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from engine.static_audit.tools.source_data_findings import SheetVectors
from engine.static_audit.tools.source_data_pair_forensics import (
    PairForensicsParams,
    analyze_xlsx_root,
    cluster_pair_forensics_findings,
    duplicate_row_vector_findings,
    paired_ratio_reuse_findings,
    pair_forensics_review_tasks,
)


def write_minimal_xlsx(path: Path, rows: list[list[float | int | None]]) -> None:
    sheet_rows = []
    for row_index, values in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(values, start=1):
            if value is None:
                continue
            col = chr(64 + col_index)
            cells.append(f'<c r="{col}{row_index}"><v>{value}</v></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        "</worksheet>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Fig.1a" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def write_mixed_xlsx(path: Path, rows: list[list[float | int | str | None]]) -> None:
    sheet_rows = []
    for row_index, values in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(values, start=1):
            if value is None:
                continue
            col = chr(64 + col_index)
            if isinstance(value, str):
                cells.append(
                    f'<c r="{col}{row_index}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
                )
            else:
                cells.append(f'<c r="{col}{row_index}"><v>{value}</v></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        "</worksheet>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Fig.1a" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def test_pair_forensics_detects_row_offset_ratio_and_scalar_patterns(tmp_path) -> None:
    # Rows 1-4 and 5-8 are not paper-specific. They model the generic pattern:
    # a second block reuses the first block's paired ratios and scalar-multiplies
    # the underlying columns at a fixed row offset.
    write_minimal_xlsx(
        tmp_path / "source.xlsx",
        [
            [1, 2],
            [2, 6],
            [3, 12],
            [4, 20],
            [10, 20],
            [20, 60],
            [30, 120],
            [40, 200],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [7, 8],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [None, None],
            [7, 8],
        ],
    )

    result = analyze_xlsx_root(
        tmp_path,
        PairForensicsParams(min_pairs=4, min_support=1.0, max_offset=8),
    )
    categories = {item["category"] for item in result["findings"]}

    assert "paired_ratio_reuse" in categories
    assert "row_offset_scalar_multiple" in categories
    assert "duplicate_row_vector" in categories
    assert result["summary"]["priority_findings"] >= 3
    assert result["summary"]["finding_clusters"] >= 1
    assert result["summary"]["review_tasks"] >= 1
    assert result["finding_clusters"]
    assert result["review_tasks"]


def test_pair_forensics_detects_long_format_paired_ratio_reuse(tmp_path) -> None:
    # Long-format source data is common in biomedical papers: one column stores
    # pair/sample id and another stores the measurement for two consecutive rows.
    write_minimal_xlsx(
        tmp_path / "long_format.xlsx",
        [
            [None, 1, 1],
            [None, 1, 2],
            [None, 2, 2],
            [None, 2, 6],
            [None, 3, 3],
            [None, 3, 12],
            [None, 4, 4],
            [None, 4, 20],
            [None, 5, 10],
            [None, 5, 20],
            [None, 6, 20],
            [None, 6, 60],
            [None, 7, 30],
            [None, 7, 120],
            [None, 8, 40],
            [None, 8, 200],
        ],
    )

    result = analyze_xlsx_root(
        tmp_path,
        PairForensicsParams(min_pairs=4, min_support=1.0, max_offset=4),
    )
    categories = {item["category"] for item in result["findings"]}

    assert "long_format_paired_ratio_reuse" in categories


def test_pair_forensics_detects_cross_block_paired_diff_too_narrow(tmp_path) -> None:
    write_mixed_xlsx(
        tmp_path / "cross_block.xlsx",
        [
            [10.00, 100.00],
            [20.00, 200.00],
            [30.00, 300.00],
            [40.00, 400.00],
            ["Treatment B", "Treatment B"],
            [10.01, 100.01],
            [20.01, 200.01],
            [30.01, 300.01],
            [40.01, 400.01],
        ],
    )

    result = analyze_xlsx_root(
        tmp_path,
        PairForensicsParams(min_pairs=3, max_findings_per_category=20),
    )

    findings = [
        item
        for item in result["findings"]
        if item["category"] == "cross_block_paired_diff_too_narrow"
    ]
    assert findings
    assert result["summary"]["cross_block_paired_diff_too_narrow_findings"] == len(findings)
    assert any(item["finding_id"].startswith("CBD-") for item in findings)
    assert "cross_block_paired_diff_too_narrow" in {item["category"] for item in result["priority_findings"]}
    assert any(
        task["category"] == "cross_block_paired_diff_too_narrow"
        for task in result["review_tasks"]
    )


def test_pair_forensics_cross_block_requires_real_separator_and_narrow_diffs(tmp_path) -> None:
    write_mixed_xlsx(
        tmp_path / "single_cell_separator.xlsx",
        [
            [10.00, 100.00],
            [20.00, 200.00],
            [30.00, 300.00],
            [40.00, 400.00],
            ["Treatment B", None],
            [10.01, 100.01],
            [20.01, 200.01],
            [30.01, 300.01],
            [40.01, 400.01],
        ],
    )
    write_mixed_xlsx(
        tmp_path / "wide_diffs.xlsx",
        [
            [10.00, 100.00],
            [20.00, 200.00],
            [30.00, 300.00],
            [40.00, 400.00],
            ["Treatment B", "Treatment B"],
            [15.00, 80.00],
            [18.00, 260.00],
            [45.00, 330.00],
            [62.00, 390.00],
        ],
    )

    result = analyze_xlsx_root(
        tmp_path,
        PairForensicsParams(min_pairs=3, max_findings_per_category=20),
    )

    assert "cross_block_paired_diff_too_narrow" not in {
        item["category"] for item in result["findings"]
    }


def test_pair_forensics_cli_outputs_empty_summary(tmp_path) -> None:
    output = tmp_path / "pair_forensics.json"
    result = analyze_xlsx_root(tmp_path, PairForensicsParams())
    output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"]["workbook_count"] == 0
    assert data["summary"]["findings"] == 0
    assert data["summary"]["finding_clusters"] == 0
    assert data["summary"]["review_tasks"] == 0


def test_pair_forensics_clusters_repeated_same_sheet_offset_findings() -> None:
    findings = [
        {
            "finding_id": f"PRR-{idx:04d}",
            "category": "paired_ratio_reuse",
            "risk_level": "high",
            "confidence": "high",
            "workbook": "source.xlsx",
            "sheet": "Fig1",
            "row_offset": 8,
            "column_pair": [f"A{idx}", f"B{idx}"],
            "matched_pairs": 12,
            "overlap_pairs": 12,
            "support_rate": 1.0,
            "benign_explanations": ["可能是合法派生。"],
            "next_steps": ["核对原始记录。"],
        }
        for idx in range(1, 6)
    ]

    clusters = cluster_pair_forensics_findings(findings)
    tasks = pair_forensics_review_tasks(clusters)

    assert len(clusters) == 1
    assert clusters[0]["finding_count"] == 5
    assert clusters[0]["pattern_signature"] == "offset=8"
    assert len(clusters[0]["representative_finding_ids"]) == 5
    assert len(tasks) == 1
    assert tasks[0]["cluster_id"] == clusters[0]["cluster_id"]
    assert tasks[0]["cluster_count"] == 1
    assert tasks[0]["finding_count"] == 5


def test_pair_forensics_downgrades_mean_sum_ratio_reuse() -> None:
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

    findings = paired_ratio_reuse_findings(
        sheet,
        PairForensicsParams(min_pairs=4, min_support=1.0, max_offset=4),
    )

    assert findings
    assert {finding["risk_level"] for finding in findings} == {"low"}
    assert {finding["artifact_likelihood"] for finding in findings} == {"high"}
    assert {
        finding["pressure_test_result"] for finding in findings
    } == {"likely_summary_statistic_derivation"}


def test_duplicate_row_vector_downgrades_zero_inflated_matrix() -> None:
    rows = list(range(1, 41))
    numeric_columns: dict[int, dict[int, Decimal]] = {}
    for col in range(2, 18):
        numeric_columns[col] = {}
        for row in rows:
            if row <= 35:
                numeric_columns[col][row] = Decimal("0")
            else:
                numeric_columns[col][row] = Decimal(col * 100 + row)

    sheet = SheetVectors(
        workbook="source.xlsx",
        workbook_path="source.xlsx",
        sheet="Zero inflated matrix",
        sheet_path="xl/worksheets/sheet1.xml",
        numeric_columns=numeric_columns,
        text_columns={col: [(1, f"Endpoint {col}")] for col in numeric_columns},
        formulas_by_column={},
        cell_count=640,
        numeric_cell_count=640,
    )

    findings = duplicate_row_vector_findings(
        sheet,
        PairForensicsParams(min_duplicate_row_width=2),
    )

    finding = next(item for item in findings if item["duplicate_row_count"] == 35)
    assert finding["risk_level"] == "medium"
    assert finding["artifact_likelihood"] == "high"
    assert finding["pressure_test_result"] == "likely_zero_inflated_matrix_artifact"
