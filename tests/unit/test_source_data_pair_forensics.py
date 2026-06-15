from __future__ import annotations

import json
import zipfile
from pathlib import Path

from engine.static_audit.tools.source_data_pair_forensics import (
    PairForensicsParams,
    analyze_xlsx_root,
    cluster_pair_forensics_findings,
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
