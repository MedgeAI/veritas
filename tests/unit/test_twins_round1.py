from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from engine.static_audit.stats.grim import grim_mean_is_possible
from engine.static_audit.stats.statcheck import audit_t_test_rows, two_sided_t_p_value
from engine.twins.injector import inject_duplicate_columns


def test_statcheck_recomputes_cns098_t_p_identity() -> None:
    p_value = two_sided_t_p_value(t_stat=-4.5299, df=2249)

    assert p_value == pytest.approx(6.2107e-6, rel=1e-3)

    findings = audit_t_test_rows(
        [
            {
                "row": 2,
                "t": -4.5299,
                "df": 2249,
                "P": 6.2107e-5,
            }
        ],
        t_column="t",
        df_column="df",
        p_column="P",
    )

    assert findings[0]["row"] == 2
    assert findings[0]["category"] == "p_value_inconsistency"
    assert findings[0]["log10_delta"] > 0.5


def test_grim_mean_requires_integer_total_at_reported_decimals() -> None:
    assert grim_mean_is_possible(mean="1.23", n=100, decimals=2)
    assert not grim_mean_is_possible(mean="1.23", n=6, decimals=2)


def test_duplicate_column_injection_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    output = tmp_path / "twin.xlsx"
    log_path = tmp_path / "injection_log.json"

    wb = Workbook()
    ws = wb.active
    ws.title = "s1"
    ws.append(["label", "A", "B"])
    for idx in range(1, 7):
        ws.append([f"row-{idx}", idx * 1.5, idx * 10.0])
    wb.save(source)

    operation = inject_duplicate_columns(
        source_path=source,
        output_path=output,
        sheet_name="s1",
        source_column="B",
        target_column="C",
        start_row=2,
        end_row=7,
        seed=42,
        log_path=log_path,
    )

    assert operation.claim_type == "source_data.duplicate_columns"
    twin_wb = load_workbook(output, data_only=False)
    twin_ws = twin_wb["s1"]
    assert [twin_ws[f"C{row}"].value for row in range(2, 8)] == [
        twin_ws[f"B{row}"].value for row in range(2, 8)
    ]
    twin_wb.close()

    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert log["seed"] == 42
    assert log["class"] == "duplicate_columns"
    assert log["cells"][0] == {"ref": "C2", "orig": 10, "new": 1.5}
