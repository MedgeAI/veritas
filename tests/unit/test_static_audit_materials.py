from __future__ import annotations

from engine.static_audit.materials import build_material_inventory, fallback_optional_lanes


def test_material_inventory_selects_xlsx_source_data_lane(tmp_path) -> None:
    paper_pdf = tmp_path / "paper.pdf"
    paper_pdf.write_bytes(b"%PDF-1.4\n")
    source_dir = tmp_path / "Source Data"
    source_dir.mkdir()
    (source_dir / "fig1.xlsx").write_bytes(b"not a real workbook")

    inventory = build_material_inventory(tmp_path, paper_pdf)
    lanes = fallback_optional_lanes(inventory)

    assert inventory["summary"]["file_count"] == 1
    assert inventory["summary"]["by_material_type"] == {"structured_table_xlsx": 1}
    assert lanes[0]["lane_id"] == "source_data_xlsx"
    assert lanes[0]["status"] == "selected"
    assert lanes[0]["root"] == str(source_dir)


def test_material_inventory_records_unsupported_csv_without_executable_lane(tmp_path) -> None:
    paper_pdf = tmp_path / "paper.pdf"
    paper_pdf.write_bytes(b"%PDF-1.4\n")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "counts.csv").write_text("gene,value\nA,1\n", encoding="utf-8")

    inventory = build_material_inventory(tmp_path, paper_pdf)
    lanes = fallback_optional_lanes(inventory)

    assert inventory["summary"]["by_material_type"] == {"structured_table_text": 1}
    assert inventory["candidate_source_roots"][0]["executable_in_mvp"] is False
    assert lanes[0]["status"] == "missing_material"
    assert "XLSX" in lanes[0]["reason"]
