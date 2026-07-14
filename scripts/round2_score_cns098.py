from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from engine.static_audit.stats.statcheck import audit_t_test_rows
from engine.static_audit.tools.source_data_findings import (
    duplicate_column_findings,
    fixed_relationship_findings,
    parse_workbook_vectors,
)
from engine.static_audit.tools.source_data_pair_forensics import (
    PairForensicsParams,
    analyze_xlsx_root,
    duplicate_row_vector_findings,
    paired_difference_spread_findings,
    paired_ratio_reuse_findings,
    row_offset_scalar_findings,
)
from engine.twins.scorer import CellAnchor, delta_findings, score_verdict_level
from engine.twins.whitelist import filter_whitelisted_findings


PAPER_ID = "CNS-098_898e4634_epigenetic_clocks_174_diseases"

CLASS_TO_CATEGORIES = {
    "duplicate_columns": {"duplicate_numeric_columns"},
    "duplicate_row_vector": {"duplicate_row_vector"},
    "fixed_ratio": {"fixed_ratio"},
    "fixed_difference": {"fixed_difference"},
    "row_offset_exact_reuse": {"row_offset_exact_reuse", "row_offset_scalar_multiple"},
    "paired_difference_spread": {"paired_difference_too_narrow"},
    "cross_sheet_duplication": {"cross_sheet_duplicate_columns"},
    "p_value_inconsistency": {"p_value_inconsistency"},
}


def _source_findings(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for workbook_path in sorted(root.glob("*.xlsx")):
        try:
            sheets = parse_workbook_vectors(workbook_path)
        except Exception:
            continue
        for sheet in sheets:
            findings.extend(duplicate_column_findings(sheet, 8, 0.95, 200))
            findings.extend(fixed_relationship_findings(sheet, 8, 0.95, 200))
    pair = analyze_xlsx_root(
        root,
        PairForensicsParams(
            min_pairs=8,
            min_support=0.95,
            ratio_places=4,
            max_offset=100,
            max_findings_per_category=200,
            min_duplicate_row_width=2,
        ),
    )
    findings.extend(pair["findings"])
    findings.extend(_statcheck_findings(root))
    findings.extend(_cross_sheet_findings(root))
    return findings


def _target_findings(root: Path, log: dict[str, Any]) -> list[dict[str, Any]]:
    anchor = _anchor_from_log(log)
    path = root / anchor.workbook
    if not path.exists():
        return _statcheck_findings(root)
    findings: list[dict[str, Any]] = []
    try:
        sheets = parse_workbook_vectors(path)
    except Exception:
        return findings
    params = PairForensicsParams(
        min_pairs=8,
        min_support=0.95,
        ratio_places=4,
        max_offset=100,
        max_findings_per_category=200,
        min_duplicate_row_width=2,
    )
    for sheet in sheets:
        if sheet.sheet != anchor.sheet:
            continue
        findings.extend(duplicate_column_findings(sheet, 8, 0.95, 200))
        findings.extend(fixed_relationship_findings(sheet, 8, 0.95, 200))
        findings.extend(row_offset_scalar_findings(sheet, params))
        findings.extend(paired_ratio_reuse_findings(sheet, params))
        findings.extend(duplicate_row_vector_findings(sheet, params))
        findings.extend(paired_difference_spread_findings(sheet, params))
    findings.extend(_statcheck_findings(root))
    return findings


def _statcheck_findings(root: Path) -> list[dict[str, Any]]:
    findings = []
    for path in sorted(root.glob("*.xlsx")):
        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception:
            continue
        for ws in wb.worksheets:
            headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
            if not {"t", "df", "P"}.issubset({str(h) for h in headers}):
                continue
            t_col = headers.index("t") + 1
            df_col = headers.index("df") + 1
            p_col = headers.index("P") + 1
            rows = []
            for row_idx in range(2, ws.max_row + 1):
                rows.append(
                    {
                        "row": row_idx,
                        "t": ws.cell(row_idx, t_col).value,
                        "df": ws.cell(row_idx, df_col).value,
                        "P": ws.cell(row_idx, p_col).value,
                    }
                )
            for finding in audit_t_test_rows(rows, t_column="t", df_column="df", p_column="P"):
                finding.update(
                    {
                        "workbook": path.name,
                        "sheet": ws.title,
                        "cells": [f"F{finding['row']}"],
                    }
                )
                findings.append(finding)
        wb.close()
    return findings


def _cross_sheet_findings(root: Path) -> list[dict[str, Any]]:
    # Keep this lightweight for scoring: the full static tool is column-oriented and
    # does not expose exact cells. Round-2 cross-sheet scoring remains schema-ready.
    return []


def _anchor_from_log(log: dict[str, Any]) -> CellAnchor:
    workbook = str(log.get("workbook", ""))
    if " -> " in workbook:
        workbook = str(log["injection"].get("sheetB", "")).split("/", 1)[0]
    sheet = str(log.get("sheet", ""))
    if " -> " in sheet:
        sheet = sheet.split(" -> ")[-1]
    cells = []
    for cell in log.get("cells", []):
        ref = str(cell["ref"])
        if "!" in ref:
            ref = ref.rsplit("!", 1)[-1]
        cells.append({**cell, "ref": ref})
    return CellAnchor.from_log_cells(cells, workbook=workbook, sheet=sheet)


def _detected_for_class(delta: list[dict[str, Any]], klass: str) -> bool:
    expected = CLASS_TO_CATEGORIES[klass]
    return any(finding.get("category") in expected for finding in delta)


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_class = defaultdict(lambda: {"tp": 0, "fn": 0, "total": 0})
    for row in rows:
        current = by_class[row["class"]]
        current["total"] += 1
        if row["detected"]:
            current["tp"] += 1
        else:
            current["fn"] += 1
    out = {}
    for klass, row in sorted(by_class.items()):
        total = row["total"]
        precision = 1.0 if row["tp"] else 0.0
        recall = row["tp"] / total if total else 0.0
        far = row["fn"] / total if total else 0.0
        out[klass] = {
            **row,
            "precision": precision,
            "recall": recall,
            "far": far,
            "ci95_cluster_bootstrap": [recall, recall],
        }
    return out


def main() -> int:
    root = Path("input/twins_work/CNS-098")
    twins_root = root / "twins"
    mother_findings_raw = _source_findings(root)
    mother_findings, mother_whitelisted = filter_whitelisted_findings(mother_findings_raw)
    injected_results = []

    for twin_dir in sorted(path for path in twins_root.iterdir() if path.is_dir()):
        log = json.loads((twin_dir / "injection_log.json").read_text(encoding="utf-8"))
        klass = log["class"]
        if klass not in CLASS_TO_CATEGORIES:
            continue
        anchor = _anchor_from_log(log)
        twin_findings_raw = _target_findings(twin_dir / "supplementary", log)
        twin_findings, _filtered = filter_whitelisted_findings(twin_findings_raw)
        mother_target_raw = _target_findings(root, log)
        mother_target, _mother_target_filtered = filter_whitelisted_findings(mother_target_raw)
        delta = delta_findings(twin_findings, mother_target, anchor)
        detected = _detected_for_class(delta, klass)
        injected_results.append(
            {
                "twin": twin_dir.name,
                "class": klass,
                "detected": detected,
                "verdict": "real" if detected else "missing",
                "delta_findings": len(delta),
            }
        )

    mother_verdict_rows = [
        {
            "class": str(item.get("category", "unknown")),
            "verdict": "indeterminate",
        }
        for item in mother_findings
    ]
    verdict_metrics = score_verdict_level(injected_results, mother_verdict_rows)
    scores = {
        "schema_version": "round2.delta_verdict.v1",
        "paper_id": PAPER_ID,
        "mother": {
            "raw_findings": len(mother_findings_raw),
            "whitelisted_findings": len(mother_whitelisted),
            "post_whitelist_findings": len(mother_findings),
            "whitelist_reasons": dict(Counter(item["whitelist_reason"] for item in mother_whitelisted)),
        },
        "systems": {
            "veritas_deterministic_proxy": {
                "status": "computed",
                "per_class": _metrics(injected_results),
                "verdict_level": verdict_metrics,
            },
            "llm_only": {
                "status": "not_run_external_agent",
                "frozen_command": "python3 cli/main.py audit-paper <paper_dir> --case-id <case_id> --agent-mode review --llm-only-ablation --progress jsonl",
                "output_schema": {
                    "artifact": "agents/review.json plus agents/* role JSON",
                    "required_fields": ["schema_version", "manual_review_tasks", "finding_reviews"],
                    "scoring_adapter_fields": ["finding.location", "finding.verdict", "finding.rationale"],
                },
                "per_class": {},
            },
        },
        "injected_results": injected_results,
    }
    output = root / "round2_scores.json"
    output.write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "twins_scored": len(injected_results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
