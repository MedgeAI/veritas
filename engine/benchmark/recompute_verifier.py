"""Generic recompute verifier for rep_ (reproduction) cases — executes the `recompute` contract.

Computed obs (aggregate metrics, not single-cell lookups) can't be checked by reading one cell.
The `recompute` contract (benchmarks/veritasbench/REP_RECOMPUTE_CONTRACT.md) declares, per obs, HOW
to recompute the value and WITH WHAT tolerance; this module is the small executor that runs it. It
does NOT reverse-engineer prose spans — it only executes declared reference functions.

Design (w1 2026-07-15 ruling):
  * families: count / continuous_stat / fraction / ci_bounded_stat / categorical_call / cell_lookup.
  * cell_lookup verifies a deposited-cell (claim value == a code_output cell) — deterministic
    transcription only, NEVER for a discriminator (the contract forbids it; not enforced here).
  * ci_interval is the CI-aware tolerance: value must fall within [lo, hi] (both are sibling obs),
    so bootstrap noise on a genuine reproduction is not mistaken for an inconsistency.
  * method.code_entry (re-run the shipped pipeline) is the heavy path — deferred, returns 'skip'.

Reference fns share the signature fn(inputs, args, base) — `inputs` are the resolved recompute
`inputs` paths; `base` is the case dir, for fns whose args name files directly (e.g. pearson_corr).
Named categorical rules live in RULE_IMPLS (reviewed code, not data-declared logic).
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import math
from pathlib import Path
from typing import Any, Callable

_OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
        "contains": lambda a, b: str(b) in str(a)}


def _rows(path: Path) -> list[dict]:
    opener = gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else open(path, encoding="utf-8")
    with opener as f:
        text = f.read()
    delim = "\t" if ".tsv" in path.name else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delim))


def _lines(path: Path) -> list[list[str]]:
    opener = gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else open(path, encoding="utf-8")
    with opener as f:
        return list(csv.reader(f))


def _tofloat(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _find_row(rows: list[dict], filt: dict) -> dict | None:
    hit = [r for r in rows if all(str(r.get(k, "")).strip() == str(v) for k, v in filt.items())]
    return hit[0] if hit else None


def _cmp(op: str, a, b) -> bool:
    """Compare cell `a` to `b` under `op`; numeric when both parse as numbers, else string."""
    if op == "contains":
        return str(b) in str(a)
    fa, fb = _tofloat(a), _tofloat(b)
    if fa is not None and fb is not None:
        return _OPS[op](fa, fb)
    return _OPS[op](str(a).strip(), str(b).strip())


def _arg_thresh(args: dict):
    return args["value"] if "value" in args else args["thresh"]   # accept either arg name


def _apply_row_filter(rows: list[dict], args: dict) -> list[dict]:
    rf = args.get("row_filter")
    if not rf:
        return rows
    if "in" in rf:  # membership filter: {column, in: [...]}
        allow = {str(v).strip() for v in rf["in"]}
        return [r for r in rows if str(r.get(rf["column"], "")).strip() in allow]
    return [r for r in rows if _cmp(rf["op"], r.get(rf["column"]), _arg_thresh(rf))]


# ---- reference functions: fn(inputs, args, base) -> value ----

def count_where(inputs: list[Path], args: dict, base: Path | None = None) -> int:
    rows = _apply_row_filter(_rows(inputs[0]), args)
    return sum(1 for r in rows if _cmp(args["op"], r.get(args["column"]), _arg_thresh(args)))


def count_rows(inputs: list[Path], args: dict, base: Path | None = None) -> int:
    return len(_apply_row_filter(_rows(inputs[0]), args))


def fraction_where(inputs: list[Path], args: dict, base: Path | None = None) -> float:
    rows = _apply_row_filter(_rows(inputs[0]), args)
    total = sum(1 for r in rows if r.get(args["column"], "") != "")
    hit = sum(1 for r in rows if _cmp(args["op"], r.get(args["column"]), _arg_thresh(args)))
    return hit / total if total else 0.0


def mean(inputs: list[Path], args: dict, base: Path | None = None) -> float:
    vals = [v for v in (_tofloat(r.get(args["column"])) for r in _rows(inputs[0])) if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def _pearson(pairs: list[tuple[float, float]]) -> float:
    n = len(pairs)
    if n < 2:
        return 0.0
    mx, my = sum(x for x, _ in pairs) / n, sum(y for _, y in pairs) / n
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else 0.0


def pearson(inputs: list[Path], args: dict, base: Path | None = None) -> float:
    """Pearson r between two columns of inputs[0]."""
    rows = _rows(inputs[0])
    pairs = [(x, y) for x, y in ((_tofloat(r.get(args["x_column"])), _tofloat(r.get(args["y_column"])))
                                 for r in rows) if x is not None and y is not None]
    return _pearson(pairs)


def pearson_corr(inputs: list[Path], args: dict, base: Path | None = None) -> float:
    """Pearson r after joining pred_file & true_file on id_col (args name the files, resolved vs base)."""
    root = base or Path(".")
    pred = _rows(root / args["pred_file"])
    truth = _rows(root / args["true_file"])
    idc, pc, tc = args["id_col"], args["pred_col"], args["true_col"]
    tmap = {}
    for r in truth:
        v = _tofloat(r.get(tc))
        if v is None and args.get("drop_nonnumeric_true"):
            continue
        tmap[r.get(idc)] = v
    pairs = [(_tofloat(r.get(pc)), tmap.get(r.get(idc))) for r in pred if r.get(idc) in tmap]
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    if len(pairs) < 2:
        return args.get("degenerate_returns", 0.0)
    return _pearson(pairs)


def count_in_top_n(inputs: list[Path], args: dict, base: Path | None = None) -> int:
    """Count how many of `gene_in` land in the top-`top_n` rows ranked by `rank_col`.

    `gene_strip` TRUNCATES the name at the delimiter — 'HSPA1B##1' -> 'HSPA1B' (not a substring drop)."""
    rows = [r for r in _rows(inputs[0]) if _tofloat(r.get(args["rank_col"])) is not None]
    top = sorted(rows, key=lambda r: _tofloat(r[args["rank_col"]]))[: int(args["top_n"])]
    strip = args.get("gene_strip")
    genes = {(r.get(args["gene_col"], "").split(strip)[0] if strip else r.get(args["gene_col"], ""))
             for r in top}
    return sum(1 for g in args["gene_in"] if g in genes)


def top_n_per_group(inputs: list[Path], args: dict, base: Path | None = None) -> Any:
    """Label a target row by whether it is in the top-`n` of its group (ranked by `score_col` desc).

    Accepts `target`|`key` for the row filter and `pos`/`positive`, `neg`/`negative` for labels."""
    rows = _rows(inputs[0])
    target = _find_row(rows, args.get("target") or args["key"])
    if target is None:
        raise KeyError(f"no target row {args.get('target') or args['key']}")
    grp = target[args["group_col"]]
    peers = sorted((r for r in rows if r.get(args["group_col"]) == grp),
                   key=lambda r: _tofloat(r.get(args["score_col"])) or -1e18, reverse=True)
    pos = args.get("pos", args.get("positive", "yes"))
    neg = args.get("neg", args.get("negative", "no"))
    return pos if target in peers[: int(args["n"])] else neg


def ratio(inputs: list[Path], args: dict, base: Path | None = None) -> float:
    """numerator_col / denominator_col for the row where key_col==key."""
    row = _find_row(_rows(inputs[0]), {args["key_col"]: args["key"]})
    if row is None:
        raise KeyError(f"no row {args['key_col']}={args['key']}")
    num, den = _tofloat(row[args["numerator_col"]]), _tofloat(row[args["denominator_col"]])
    return num / den if den else float("inf")


def rank_of(inputs: list[Path], args: dict, base: Path | None = None) -> int:
    """1-indexed rank of the row where `key_col`==`key` when sorted by `sort_col` (order asc|desc)."""
    rows = _rows(inputs[0])
    rev = args.get("order", "desc") == "desc"
    srt = sorted(rows, key=lambda r: _tofloat(r.get(args["sort_col"])) if _tofloat(r.get(args["sort_col"])) is not None
                 else (-1e18 if rev else 1e18), reverse=rev)
    for i, r in enumerate(srt, 1):
        if str(r.get(args["key_col"], "")).strip() == str(args["key"]):
            return i
    raise KeyError(f"no row {args['key_col']}={args['key']}")


def _html_lookup(path: Path, args: dict):
    """Extract a value from a rendered HTML table: rows labelled by their first two cells
    (task + region), value cells of the form '<strong>total</strong> (ci_lo, ci_hi)'."""
    import re
    table = re.search(r"<table.*?</table>", path.read_text(encoding="utf-8"), re.S)
    rows = [re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)
            for r in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0), re.S)]
    strip = lambda s: re.sub(r"<[^>]+>", "", s).strip()  # noqa: E731
    cols = [strip(h).split("=")[-1].strip() for h in rows[0]]
    n_idx = cols.index(args["n_column"])
    for cells in rows[1:]:
        if " ".join(strip(c) for c in cells[:2]) == args["html_row_label"]:
            cell = cells[n_idx]
            if args["value_kind"] == "total":
                return re.search(r"<strong>(.*?)</strong>", cell).group(1).strip()
            ci = re.search(r"\((-?[\d.]+),\s*(-?[\d.]+)\)", strip(cell))
            return ci.group(1 if args["value_kind"] in ("ci_lo", "lo") else 2)
    raise KeyError(f"no html row {args['html_row_label']!r}")


def cell_lookup(inputs: list[Path], args: dict, base: Path | None = None) -> Any:
    """Read one deposited value from inputs[0]. Addressing dialects:
      * {json_path: "a.b.0"}                        — key/index path into a JSON file
      * {txt_line_key: "k", sep: ":"}               — a 'k: value' line in a txt file
      * {html_row_label, n_column, value_kind}      — a cell in a rendered HTML table
      * {value_col, row_col/row_key | match:{...}}  — CSV row lookup [+ list_sep/list_index]
      * {column, line}                              — physical file line (1-indexed)
      * {column, row: {col: val, ...}}              — multi-key CSV row filter."""
    if "html_row_label" in args:
        return _html_lookup(inputs[0], args)
    if "json_path" in args:  # JSON key/index path
        cur = json.loads(inputs[0].read_text(encoding="utf-8"))
        for part in str(args["json_path"]).split("."):
            cur = cur[int(part)] if isinstance(cur, list) else cur[part]
        return cur
    if "txt_line_key" in args:  # 'key<sep>value' line in a txt file
        sep = args.get("sep", ":")
        for line in inputs[0].read_text(encoding="utf-8").splitlines():
            if sep in line and line.split(sep, 1)[0].strip() == args["txt_line_key"]:
                return line.split(sep, 1)[1].strip()
        raise KeyError(f"no txt line {args['txt_line_key']!r}")
    if "value_col" in args:  # {row_col,row_key | match:{...}} + value_col [+ list_sep/list_index]
        row_filter = args["match"] if "match" in args else {args["row_col"]: args["row_key"]}
        hit = _find_row(_rows(inputs[0]), row_filter)
        if hit is None:
            raise KeyError(f"no row {row_filter}")
        val = hit[args["value_col"]]
        if "list_index" in args:  # the cell holds a delimited list; take one element
            val = val.split(args.get("list_sep", ","))[int(args["list_index"])].strip()
        return val
    col = args["column"]
    if "line" in args:
        lines = _lines(inputs[0])
        if col not in lines[0]:
            raise KeyError(f"column {col!r} absent")
        return lines[int(args["line"]) - 1][lines[0].index(col)]
    hit = _find_row(_rows(inputs[0]), args["row"])
    if hit is None:
        raise KeyError(f"no row {args['row']}")
    return hit[col]


# ---- named categorical rules (reviewed): impl(inputs, args, base) -> label ----

def _mediator_call_correct(inputs: list[Path], args: dict, base: Path | None = None) -> str:
    row = _find_row(_rows(inputs[0]), {args["key_col"]: args["key"]})
    if row is None:
        raise KeyError(f"no row {args['key_col']}={args['key']}")
    m, d = _tofloat(row[args["mtdna_col"]]), _tofloat(row[args["n_deg_col"]])
    if d < float(args["n_deg_thr"]):
        return "uncertain"
    return "shared" if m < float(args["depl_thr"]) else "gene_specific"


def _mediator_call_naive(inputs: list[Path], args: dict, base: Path | None = None) -> str:
    row = _find_row(_rows(inputs[0]), {args["key_col"]: args["key"]})
    if row is None:
        raise KeyError(f"no row {args['key_col']}={args['key']}")
    return "gene_specific" if _tofloat(row[args["n_deg_col"]]) >= float(args["n_deg_thr"]) else "uncertain"


RULE_IMPLS: dict[str, Callable[[list[Path], dict, Path | None], Any]] = {
    "mediator_call_correct": _mediator_call_correct,
    "mediator_call_naive": _mediator_call_naive,
    "top_n_per_group": top_n_per_group,
}


def rule_classify(inputs: list[Path], args: dict, base: Path | None = None) -> Any:
    """Dispatch a NAMED categorical rule (reviewed in RULE_IMPLS). New rule name -> LookupError (gap)."""
    impl = RULE_IMPLS.get(args["rule"])
    if impl is None:
        raise LookupError(f"unknown rule {args['rule']!r} (add to RULE_IMPLS)")
    return impl(inputs, args, base)


REFERENCE_REGISTRY: dict[str, Callable[[list[Path], dict, Path | None], Any]] = {
    "count_where": count_where, "count_rows": count_rows,
    "fraction_where": fraction_where, "frac_where": fraction_where,
    "mean": mean, "pearson": pearson, "pearson_corr": pearson_corr,
    "count_in_top_n": count_in_top_n, "rank_of": rank_of, "ratio": ratio, "rule_classify": rule_classify,
    "top_n_per_group": top_n_per_group, "cell_lookup": cell_lookup,
}


def _num_eq(a, b, rel_tol=1e-6) -> bool:
    fa, fb = _tofloat(a), _tofloat(b)
    if fa is not None and fb is not None:
        return math.isclose(fa, fb, rel_tol=rel_tol, abs_tol=rel_tol)
    return str(a).strip() == str(b).strip()


def recompute_verify(obs: dict, case_dir: Path, obs_index: dict) -> str:
    """Execute one obs's recompute contract -> 'ok' / 'fail:<why>' / 'skip:<why>' / 'nonaddr'."""
    rc = obs.get("recompute")
    if not rc:
        return "nonaddr"
    tol = rc.get("tolerance", {})
    kind = tol.get("kind", "rel_tol")
    val = obs["value"]

    # ci_interval: reported point within its declared CI (bounds are sibling obs). No recompute.
    if kind == "ci_interval":
        lo = obs_index.get(tol.get("lo_obs"), {}).get("value")
        hi = obs_index.get(tol.get("hi_obs"), {}).get("value")
        if lo is None or hi is None:
            return f"fail:missing CI bounds {tol.get('lo_obs')}/{tol.get('hi_obs')}"
        fv = _tofloat(val)
        return "ok" if fv is not None and lo <= fv <= hi else f"fail:{val} not in [{lo},{hi}]"

    method = rc.get("method", {})
    inputs = [case_dir / i for i in rc.get("inputs", [])]
    if method.get("reference_fn"):
        fn = REFERENCE_REGISTRY.get(method["reference_fn"])
        if not fn:
            return f"skip:no reference_fn {method['reference_fn']!r} in registry"
        try:
            got = fn(inputs, method.get("args", {}), case_dir)
        except KeyError as e:  # missing arg / row not found -> a real block/data problem, surfaced
            return f"fail:block error {e}"
        except LookupError as e:  # unknown named rule -> w1 registry TODO (gap), not a data fail
            return f"skip:{e}"
        except Exception as e:  # noqa: BLE001
            return f"fail:recompute error {str(e)[:60]}"
    elif method.get("code_entry"):
        return f"skip:code_entry {method['code_entry']!r} (sandbox path deferred)"
    else:
        return "skip:no method"

    # null-equivalence: a null obs matches an NA / empty / null recomputed cell
    if val is None:
        return "ok" if str(got).strip().upper() in ("NA", "", "NULL", "NONE", "NAN") \
            else f"fail:recomputed={got!r} != obs=None"
    if kind == "exact":
        return "ok" if str(got).strip() == str(val).strip() or _num_eq(got, val, rel_tol=0.0) \
            else f"fail:recomputed={got!r} != obs={val!r}"
    if kind == "rel_tol":
        return "ok" if _num_eq(got, val, tol.get("rel_tol", 1e-3)) else f"fail:recomputed={got} != obs={val}"
    return f"skip:unknown tolerance kind {kind!r}"
