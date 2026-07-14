"""Coordinate-level scoring for injected twin findings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Anchor:
    claim_type: str
    workbook: str | None = None
    sheet: str | None = None
    rows: frozenset[int] = frozenset()
    cols: frozenset[str] = frozenset()


@dataclass(frozen=True)
class CellAnchor:
    workbook: str
    sheet: str
    cells: frozenset[str]

    @classmethod
    def from_log_cells(
        cls,
        cells: Iterable[dict],
        *,
        workbook: str,
        sheet: str,
    ) -> "CellAnchor":
        return cls(
            workbook=workbook,
            sheet=sheet,
            cells=frozenset(str(cell["ref"]) for cell in cells if cell.get("ref")),
        )


def iou(left: set, right: set) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def finding_matches_anchor(
    finding: dict,
    anchor: Anchor,
    *,
    min_iou: float = 0.5,
) -> bool:
    if finding.get("claim_type", finding.get("category")) != anchor.claim_type:
        return False
    if anchor.workbook and finding.get("workbook") not in (None, anchor.workbook):
        return False
    if anchor.sheet and finding.get("sheet") != anchor.sheet:
        return False
    finding_rows = set(finding.get("rows", finding.get("sample_rows", [])))
    finding_cols = set(finding.get("cols", finding.get("columns", [])))
    row_ok = not anchor.rows or iou(finding_rows, set(anchor.rows)) >= min_iou
    col_ok = not anchor.cols or iou(finding_cols, set(anchor.cols)) >= min_iou
    return row_ok and col_ok


def score_findings(findings: Iterable[dict], anchors: Iterable[Anchor]) -> dict:
    findings_list = list(findings)
    anchors_list = list(anchors)
    matched = [
        anchor
        for anchor in anchors_list
        if any(finding_matches_anchor(finding, anchor) for finding in findings_list)
    ]
    tp = len(matched)
    fn = len(anchors_list) - tp
    return {
        "tp": tp,
        "fn": fn,
        "recall": tp / len(anchors_list) if anchors_list else 0.0,
        "far": fn / len(anchors_list) if anchors_list else 0.0,
    }


def finding_cell_set(finding: dict) -> frozenset[str]:
    cells = finding.get("cells") or finding.get("cell_refs") or []
    if cells:
        return frozenset(str(cell) for cell in cells)
    refs = []
    rows = list(finding.get("rows", finding.get("sample_rows", [])) or [])
    for pair in finding.get("sample_pairs", []) or []:
        for key in ("row", "left_row", "right_row"):
            if key in pair:
                rows.append(pair[key])
    cols = list(
        finding.get(
            "cols",
            finding.get("columns", finding.get("column_pair", [])),
        )
        or []
    )
    for row in rows:
        for col in cols:
            refs.append(f"{col}{row}")
    return frozenset(refs)


def finding_overlaps_cell_anchor(finding: dict, anchor: CellAnchor) -> bool:
    if finding.get("workbook") not in (None, anchor.workbook):
        return False
    if finding.get("sheet") not in (None, anchor.sheet):
        return False
    finding_cells = finding_cell_set(finding)
    return bool(finding_cells & anchor.cells)


def delta_findings(
    twin_findings: Iterable[dict],
    mother_findings: Iterable[dict],
    anchor: CellAnchor,
) -> list[dict]:
    """Return twin findings at anchor cells excluding mother findings at same cells."""
    mother_signatures = {
        (
            finding.get("category"),
            finding.get("workbook"),
            finding.get("sheet"),
            finding_cell_set(finding) & anchor.cells,
        )
        for finding in mother_findings
        if finding_overlaps_cell_anchor(finding, anchor)
    }
    delta = []
    for finding in twin_findings:
        if not finding_overlaps_cell_anchor(finding, anchor):
            continue
        signature = (
            finding.get("category"),
            finding.get("workbook"),
            finding.get("sheet"),
            finding_cell_set(finding) & anchor.cells,
        )
        if signature not in mother_signatures:
            delta.append(finding)
    return delta


def score_verdict_level(
    injected_results: Iterable[dict],
    mother_results: Iterable[dict],
) -> dict:
    """Compute v1.1 verdict-level FAR and hallucination after benign triage."""
    by_class: dict[str, dict] = {}
    for item in injected_results:
        klass = str(item.get("class", "unknown"))
        row = by_class.setdefault(
            klass,
            {"tp": 0, "fn_or_benign": 0, "total": 0, "far": 0.0, "recall": 0.0},
        )
        row["total"] += 1
        if item.get("detected") and item.get("verdict") == "real":
            row["tp"] += 1
        else:
            row["fn_or_benign"] += 1
    for row in by_class.values():
        total = row["total"]
        row["far"] = row["fn_or_benign"] / total if total else 0.0
        row["recall"] = row["tp"] / total if total else 0.0

    mother_list = list(mother_results)
    hallucinated = sum(1 for item in mother_list if item.get("verdict") == "real")
    return {
        "by_class": by_class,
        "mother_real_fp": hallucinated,
        "mother_total": len(mother_list),
        "hallucination_rate": hallucinated / len(mother_list) if mother_list else 0.0,
    }
