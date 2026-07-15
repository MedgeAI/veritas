"""Read-only QC verifier for the VeritasBench span/extractability contract.

Independent delivery gate the data window can run before handing cases over: for each case it checks
the Round-2 contract WITHOUT modifying anything. Complements scripts/validate_veritasbench.py (which
checks structure/hashes) by adding the one thing structure checks can't: that every deterministically
addressable observation value actually equals the cell it cites in the raw artifact.

Seven checks per case:
  1. mirror validator RESULT: PASS (optional — set VBENCH_MIRROR or --mirror; skipped if absent).
  2. ★ extractability: each obs is re-read from its artifact and asserted == obs["value"]. Three
     address dialects: xlsx `Sheet!A1`, CSV `row k=v[,k2=v2], column C` (compound keys ok), and the
     line contract `L<file_line>:<column>`. Non-addressable obs (computed/aggregate reproduction
     metrics, pdf#image) are LISTED, not failed (contract check 7).
  3. each xlsx L1 claim carries source_a1_range + target_a1_range (CSV/code_output claims exempt).
  4. consistent/inconsistent claims carry an evidence_span (insufficient may omit it).
  5. every artifact's recorded sha256 == the file's real digest.
  6. dual-version cases: >=2 source_data artifacts, distinct hashes, inconsistent anchored pre-fix.
  7. non-addressable obs surfaced for human review (never a hard FAIL).

Usage:
  PYTHONPATH=. uv run python scripts/qc_veritasbench.py            # scan the whole corpus
  PYTHONPATH=. uv run python scripts/qc_veritasbench.py ncb_lgr4 rep_mediator [--json]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import openpyxl

DEFAULT_BASE = Path("benchmarks/veritasbench/cases")
DUAL_VERSION = {"ncb_neurexin", "ncb_teneurin", "ncb_clonalfish"}

_CELL = re.compile(r"^(?P<sheet>.+)!(?P<col>[A-Z]+)(?P<row>\d+)$")
_RANGE = re.compile(r"^(?P<sheet>.+)!(?P<rng>[A-Z]+\d+:[A-Z]+\d+)$")
_LINE = re.compile(r"^L(?P<line>\d+):(?P<col>.+)$")
_CSV_ROWKEYS = re.compile(r"([\w.]+)=('[^']*'|[^,&]+)")
_CSV_COL = re.compile(r"column\s+([\w.]+)")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _num_eq(a, b) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-6)
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def _load_csv_rows(path: Path) -> list[dict]:
    opener = gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else open(path, encoding="utf-8")
    with opener as f:
        text = f.read()
    delim = "\t" if ".tsv" in path.name else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delim))


def _csv_lines(path: Path) -> list[list[str]]:
    opener = gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else open(path, encoding="utf-8")
    with opener as f:
        return list(csv.reader(f))


def _parse_csv_span(span: str):
    """(row filters, target column) from 'row k=v[,k2=v2], column C'; None if not addressable."""
    col = _CSV_COL.search(span or "")
    if not col:
        return None
    pairs = [(k, v.strip().strip("'")) for k, v in _CSV_ROWKEYS.findall(span[:col.start()]) if k != "row"]
    return (pairs, col.group(1)) if pairs else None


def run_mirror(case_dir: Path, mirror: str | None) -> tuple[bool | None, int]:
    if not mirror or not Path(mirror).is_file():
        return None, 0
    try:
        out = subprocess.run([sys.executable, mirror, str(case_dir)],
                             capture_output=True, text=True, timeout=120).stdout
    except Exception:  # noqa: BLE001
        return False, -1
    m = re.search(r"ERRORS \((\d+)\)", out)
    return ("RESULT: PASS" in out), (int(m.group(1)) if m else 1)


def _extract_obs(cdir: Path, okey: str, o: dict, wb_cache: dict, csv_cache: dict, line_cache: dict) -> str:
    """Return 'ok' / 'nonaddr:<why>' / 'fail:<detail>' for one observation."""
    relpath, loc = okey.split("#", 1)
    val = o["value"]
    art = cdir / relpath
    low = relpath.lower()

    if low.endswith(".xlsx"):
        m = _CELL.match(loc) or _RANGE.match(loc)
        if not m:
            return "nonaddr:obs key not Sheet!A1"
        if art not in wb_cache:
            wb_cache[art] = openpyxl.load_workbook(art, read_only=True, data_only=True)
        wb = wb_cache[art]
        sheet = m.group("sheet")
        if sheet not in wb.sheetnames:
            return f"fail:sheet {sheet!r} missing"
        ws = wb[sheet]
        if "col" in m.groupdict() and m.groupdict().get("col"):
            got = ws[f"{m.group('col')}{m.group('row')}"].value
            return "ok" if _num_eq(got, val) else f"fail:xlsx={got} vs obs={val}"
        cells = [c.value for row in ws[m.group("rng")] for c in row]
        return ("ok" if isinstance(val, list) and len(val) == len(cells)
                and all(_num_eq(x, y) for x, y in zip(val, cells)) else f"fail:xlsx={cells} vs obs={val}")

    if low.endswith((".csv", ".csv.gz", ".tsv", ".tsv.gz")):
        lm = _LINE.match(loc)
        if lm:  # L<file_line>:<column> contract
            if art not in line_cache:
                line_cache[art] = _csv_lines(art)
            lines = line_cache[art]
            ln, col = int(lm.group("line")), lm.group("col")
            if ln > len(lines):
                return f"fail:line {ln} beyond EOF"
            header = lines[0]
            if col not in header:
                return f"fail:col {col!r} absent"
            got = lines[ln - 1][header.index(col)]
            return "ok" if _num_eq(got, val) else f"fail:csv[{col}]={got!r} vs obs={val!r}"
        parsed = _parse_csv_span(o.get("source_span", ""))
        if not parsed:
            return "nonaddr:CSV span not row/col-addressable (computed metric?)"
        filters, col = parsed
        if art not in csv_cache:
            csv_cache[art] = _load_csv_rows(art)
        rows = csv_cache[art]
        if rows and not all(k in rows[0] for k, _ in filters):
            return f"nonaddr:span cols {[k for k, _ in filters]} not in {art.name}"
        hit = [r for r in rows if all(str(r.get(k, "")).strip() == v for k, v in filters)]
        if not hit:
            return f"fail:no CSV row {filters}"
        if col not in hit[0]:
            return f"nonaddr:col {col!r} not a real column (derived span)"
        return "ok" if _num_eq(hit[0][col], val) else f"fail:csv[{col}]={hit[0][col]!r} vs obs={val!r}"

    return f"nonaddr:{relpath.split('.')[-1]} — human review"


def check_case(cid: str, base: Path, mirror: str | None) -> dict:
    cdir = base / cid
    doc = json.loads((cdir / "case.json").read_text(encoding="utf-8"))
    arts, obs, claims = doc.get("artifacts", {}), doc.get("observations", {}), doc.get("claims", [])
    r = {"case": cid, "ok": 0, "total": 0, "fails": [], "nonaddr": [], "hash_fail": [],
         "a1_missing": [], "evspan_missing": [], "notes": []}

    r["mirror_pass"], r["mirror_errors"] = run_mirror(cdir, mirror)

    for name, a in arts.items():
        p = cdir / a["path"]
        if not p.is_file():
            r["hash_fail"].append(f"{name}: file missing")
        elif _sha256(p) != a.get("sha256"):
            r["hash_fail"].append(f"{name}: sha256 mismatch")

    wb_cache, csv_cache, line_cache = {}, {}, {}
    for okey, o in obs.items():
        r["total"] += 1
        try:
            verdict = _extract_obs(cdir, okey, o, wb_cache, csv_cache, line_cache)
        except Exception as e:  # noqa: BLE001
            verdict = f"fail:ERR {str(e)[:50]}"
        if verdict == "ok":
            r["ok"] += 1
        elif verdict.startswith("nonaddr:"):
            r["nonaddr"].append(f"{okey} ({verdict[8:]})")
        else:
            r["fails"].append(f"{okey}: {verdict[5:]}")

    for cl in claims:
        if str(cl.get("relation_type")) != "L1":
            continue
        cida = cl.get("claim_id", "?")
        is_csv = any(".csv" in cl.get(role, "") or ".tsv" in cl.get(role, "")
                     for role in ("source_artifact", "target_artifact"))
        if not is_csv:
            for f in ("source_a1_range", "target_a1_range"):
                if not cl.get(f):
                    r["a1_missing"].append(f"{cida}:{f}")
        if cl.get("verdict") in ("consistent", "inconsistent") and not cl.get("evidence_span"):
            r["evspan_missing"].append(cida)

    if cid in DUAL_VERSION:
        sd = [a for a in arts.values() if a.get("kind") == "source_data"]
        hashes = {a["sha256"] for a in sd}
        anchors = {c.get("source_artifact", "").split("#")[0].lower()
                   for c in claims if c.get("verdict") == "inconsistent"}
        pre = any(any(t in a for t in ("orig", "-v1", "-v3", "pre", "uncorrect")) for a in anchors)
        r["notes"].append(f"dual:{len(sd)}sd/{len(hashes)}hash/incon_pre={pre}")

    r["fail"] = bool((r["mirror_pass"] is False) or r["fails"] or r["hash_fail"]
                     or r["a1_missing"] or r["evspan_missing"])
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VeritasBench read-only QC (span/extractability contract).")
    ap.add_argument("cases", nargs="*", help="case ids (default: scan all under --base-path)")
    ap.add_argument("--base-path", type=Path, default=DEFAULT_BASE)
    ap.add_argument("--mirror", default=os.environ.get("VBENCH_MIRROR"), help="mirror_validate.py path (optional)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    cases = args.cases or sorted(d.name for d in args.base_path.iterdir()
                                 if d.is_dir() and (d / "case.json").is_file())
    reports = [check_case(c, args.base_path, args.mirror) for c in cases]
    need_fix = [r["case"] for r in reports if r["fail"]]

    if args.json:
        print(json.dumps({"cases": reports, "need_fix": need_fix}, ensure_ascii=False, indent=2))
    else:
        print(f"{'case':22} {'mirror':8} {'extract':>9} {'a1':>5} {'hash':>5}  notes")
        print("-" * 92)
        for r in reports:
            mp = "n/a" if r["mirror_pass"] is None else ("PASS" if r["mirror_pass"] else f"FAIL{r['mirror_errors']}")
            a1 = "ok" if not r["a1_missing"] else f"MISS{len(r['a1_missing'])}"
            h = "ok" if not r["hash_fail"] else "FAIL"
            note = ([f"{len(r['nonaddr'])}non-addr"] if r["nonaddr"] else []) + r["notes"]
            print(f"{r['case']:22} {mp:8} {r['ok']:>3}/{r['total']:<5} {a1:>5} {h:>5}  {'; '.join(note)}")
            for e in r["fails"][:6] + [f"hash {x}" for x in r["hash_fail"]] + [f"a1 {x}" for x in r["a1_missing"][:4]]:
                print(f"    x {e}")
        print("-" * 92)
        print(f"need data-window fix ({len(need_fix)}): {need_fix or 'none — all clean'}")
    return 1 if need_fix else 0


if __name__ == "__main__":
    raise SystemExit(main())
