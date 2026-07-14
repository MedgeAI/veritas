"""Independent value cross-check: re-read every observation value from the raw xlsx cell.

The structural preflight (validate_veritasbench.py, guide §6) confirms hashes and cross-references
but NOT that `observations[k].value` actually equals the cell it cites — the one thing that would
catch a value reverse-engineered from a verdict (guide §4.2 forbids exactly this). This script is
that independent audit: it opens each source_data workbook and recomputes the cited cell.

It is deliberately NOT a hard gate folded into the official validator — the cell-addressing in
`source_span` is human prose with several dialects, and a brittle parser baked into the gate would
false-fail future deliveries. Here it runs as a separate evidence artifact and reports coverage
honestly (matched / mismatched / unparseable), never silently dropping observations.

Address dialects handled (extend as new ones appear — unparseable ones are COUNTED, not hidden):
  * A1 in the observation key:      "...xlsx#<sheet>!<A1>"        e.g. "#Fig1!B3"
  * literal row/col in the key:     "...xlsx#r<row>_c<col>"       e.g. "#r3_c2"
  * prose span with letter columns: "... row <N>, col <A-Z> ..."  (column-offset auto-detected)

Usage:
  uv run python scripts/crosscheck_veritasbench_values.py \
      --base-path benchmarks/veritasbench --suite veritasbench_trial5 [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import openpyxl

_A1_KEY = re.compile(r"#(?P<sheet>.+)!(?P<a1>[A-Za-z]+\d+)$")
_RC_KEY = re.compile(r"#r(?P<row>\d+)_c(?P<col>\d+)$")
_PROSE = re.compile(r"row\s+(?P<row>\d+),\s*col\s+(?P<col>[A-Z])")


def _approx(a: Any, b: Any) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-4)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _grid(xlsx: Path, sheet: str, cache: dict) -> list[tuple] | None:
    key = (str(xlsx), sheet)
    if key not in cache:
        wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
        cache[key] = list(wb[sheet].iter_rows(values_only=True)) if sheet in wb.sheetnames else None
        wb.close()
    return cache[key]


def _prose_col_offset(grid: list[tuple], obs: dict, span_row: int, span_col_letter: str) -> int | None:
    """Find where a prose 'row N, col A' value actually sits, to derive the letter->column offset."""
    if not (0 <= span_row - 1 < len(grid)):
        return None
    row = grid[span_row - 1]
    for j, v in enumerate(row):
        if v is not None and _approx(v, obs["value"]):
            return j - (ord(span_col_letter) - ord("A"))
    return None


def crosscheck_case(case_dir: Path) -> dict[str, Any]:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    observations = case.get("observations") or {}
    cache: dict = {}
    offset_cache: dict[str, int] = {}
    matched = mismatched = 0
    unparseable = 0
    samples: list[str] = []

    for okey, obs in observations.items():
        art = obs.get("source_artifact", "")
        xlsx = case_dir / "artifacts" / art.split("/")[-1]
        cell = _sentinel = object()

        m = _A1_KEY.search(okey)
        if m:
            grid = _grid(xlsx, m["sheet"], cache)
            if grid is not None:
                ws_cell = openpyxl.utils.cell.coordinate_to_tuple(m["a1"])
                r, c = ws_cell[0] - 1, ws_cell[1] - 1
                cell = grid[r][c] if 0 <= r < len(grid) and 0 <= c < len(grid[r]) else None
        elif _RC_KEY.search(okey):
            rc = _RC_KEY.search(okey)
            # literal 1-indexed row/col on the workbook's first data sheet cited in the span
            sheet = re.search(r"sheet '([^']+)'", obs.get("source_span", ""))
            grid = _grid(xlsx, sheet.group(1), cache) if sheet else None
            if grid is not None:
                r, c = int(rc["row"]) - 1, int(rc["col"]) - 1
                cell = grid[r][c] if 0 <= r < len(grid) and 0 <= c < len(grid[r]) else None
        else:
            p = _PROSE.search(obs.get("source_span", ""))
            sheet = re.search(r"sheet '([^']+)'", obs.get("source_span", ""))
            if p and sheet:
                grid = _grid(xlsx, sheet.group(1), cache)
                if grid is not None:
                    span_row, col_letter = int(p["row"]), p["col"]
                    ck = f"{sheet.group(1)}"
                    if ck not in offset_cache:
                        off = _prose_col_offset(grid, obs, span_row, col_letter)
                        if off is not None:
                            offset_cache[ck] = off
                    if ck in offset_cache:
                        c = offset_cache[ck] + (ord(col_letter) - ord("A"))
                        r = span_row - 1
                        cell = grid[r][c] if 0 <= r < len(grid) and 0 <= c < len(grid[r]) else None

        if cell is _sentinel:
            unparseable += 1
            continue
        if _approx(cell, obs["value"]):
            matched += 1
        else:
            mismatched += 1
            if len(samples) < 5:
                samples.append(f"{okey.split('#')[-1]}: obs={obs['value']} xlsx={cell}")

    return {
        "ok": mismatched == 0, "matched": matched, "mismatched": mismatched,
        "unparseable": unparseable, "total": len(observations), "mismatch_samples": samples,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Independent observation-value cross-check vs raw xlsx.")
    ap.add_argument("--base-path", default="benchmarks/veritasbench", type=Path)
    ap.add_argument("--suite", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    suite = json.loads((args.base_path / "suites" / f"{args.suite}.json").read_text(encoding="utf-8"))
    cases = {}
    for cid in suite["case_ids"]:
        cases[cid] = crosscheck_case(args.base_path / "cases" / cid)

    tot_m = sum(c["matched"] for c in cases.values())
    tot_x = sum(c["mismatched"] for c in cases.values())
    tot_u = sum(c["unparseable"] for c in cases.values())
    result = {
        "ok": tot_x == 0, "suite": args.suite,
        "total_matched": tot_m, "total_mismatched": tot_x, "total_unparseable": tot_u,
        "cases": cases,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"value cross-check: ok={result['ok']} matched={tot_m} mismatched={tot_x} unparseable={tot_u}")
        for cid, c in cases.items():
            mark = "OK" if c["ok"] else "MISMATCH"
            note = f" | unparseable {c['unparseable']}" if c["unparseable"] else ""
            extra = "" if c["ok"] else " :: " + "; ".join(c["mismatch_samples"])
            print(f"  [{mark}] {cid}: {c['matched']}/{c['matched'] + c['mismatched']}{note}{extra}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
