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

`REFERENCE_REGISTRY` maps a contract `reference_fn` name to a pure fn(inputs, args) -> value. A case
only needs its family's fn to exist here; the 3-5 families above cover the current rep_ corpus.
"""

from __future__ import annotations

import csv
import gzip
import io
import math
from pathlib import Path
from typing import Any, Callable

_OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


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


# ---- reference functions: fn(inputs: list[Path], args: dict) -> value ----

def count_where(inputs: list[Path], args: dict) -> int:
    """Count rows in inputs[0] where `column` `op` `thresh` (numeric)."""
    col, op, thresh = args["column"], _OPS[args["op"]], float(args["thresh"])
    n = 0
    for r in _rows(inputs[0]):
        v = _tofloat(r.get(col))
        if v is not None and op(v, thresh):
            n += 1
    return n


def fraction_where(inputs: list[Path], args: dict) -> float:
    rows = _rows(inputs[0])
    total = sum(1 for r in rows if _tofloat(r.get(args["column"])) is not None)
    return count_where(inputs, args) / total if total else 0.0


def mean(inputs: list[Path], args: dict) -> float:
    vals = [_tofloat(r.get(args["column"])) for r in _rows(inputs[0])]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def pearson(inputs: list[Path], args: dict) -> float:
    """Pearson r between two columns (same file, or x in inputs[0], y in inputs[1])."""
    xr = _rows(inputs[0])
    yr = _rows(inputs[1]) if len(inputs) > 1 and args.get("y_in_second") else xr
    xs = [_tofloat(r.get(args["x_column"])) for r in xr]
    ys = [_tofloat(r.get(args["y_column"])) for r in yr]
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 2:
        return 0.0
    mx, my = sum(x for x, _ in pairs) / n, sum(y for _, y in pairs) / n
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else 0.0


def count_in_top_n(inputs: list[Path], args: dict) -> int:
    """Count how many of `gene_in` land in the top-`top_n` rows of inputs[0] ranked by `rank_col`.

    `gene_strip` (e.g. "##") TRUNCATES the gene name at the delimiter — 'HSPA1B##1' -> 'HSPA1B' —
    it is NOT a substring removal (that would leave 'HSPA1B1' and miss the match)."""
    rows = [r for r in _rows(inputs[0]) if _tofloat(r.get(args["rank_col"])) is not None]
    top = sorted(rows, key=lambda r: _tofloat(r[args["rank_col"]]))[: int(args["top_n"])]
    strip = args.get("gene_strip")
    genes = {(r.get(args["gene_col"], "").split(strip)[0] if strip else r.get(args["gene_col"], ""))
             for r in top}
    return sum(1 for g in args["gene_in"] if g in genes)


def _find_row(rows: list[dict], filt: dict) -> dict | None:
    hit = [r for r in rows if all(str(r.get(k, "")).strip() == str(v) for k, v in filt.items())]
    return hit[0] if hit else None


def _mediator_call_correct(row: dict, args: dict) -> str:
    m, d = _tofloat(row[args["mtdna_col"]]), _tofloat(row[args["n_deg_col"]])
    depleter = m < float(args["depl_thr"])                 # mtDNA-depleted -> ISR confound
    if d < float(args["n_deg_thr"]):
        return "uncertain"
    return "shared" if depleter else "gene_specific"


def _mediator_call_naive(row: dict, args: dict) -> str:
    # the trap: ignores mtDNA confound, calls any big signature gene_specific
    return "gene_specific" if _tofloat(row[args["n_deg_col"]]) >= float(args["n_deg_thr"]) else "uncertain"


# Named discriminator rules — w1-reviewed code, NOT data-declared logic (integrity: a case can't
# smuggle in arbitrary classification; new rules are added here on review).
RULE_IMPLS: dict[str, Callable[[dict, dict], Any]] = {
    "mediator_call_correct": _mediator_call_correct,
    "mediator_call_naive": _mediator_call_naive,
}


def rule_classify(inputs: list[Path], args: dict) -> Any:
    """Recompute a categorical call by applying a NAMED rule to a target row (args: rule, key_col,
    key, + rule params). The rule is a reviewed impl in RULE_IMPLS — recomputes the discriminating
    decision from the data, catching a shipped call that doesn't follow the rule."""
    row = _find_row(_rows(inputs[0]), {args["key_col"]: args["key"]})
    if row is None:
        raise KeyError(f"no row {args['key_col']}={args['key']}")
    impl = RULE_IMPLS.get(args["rule"])
    if impl is None:
        raise LookupError(f"unknown rule {args['rule']!r} (add to RULE_IMPLS)")
    return impl(row, args)


def top_n_per_group(inputs: list[Path], args: dict) -> Any:
    """Label a target row by whether it is in the top-`n` of its group (ranked by `score_col` desc).

    args: {group_col, score_col, n, target:{col:val}, pos, neg}."""
    rows = _rows(inputs[0])
    target = _find_row(rows, args["target"])
    if target is None:
        raise KeyError(f"no target row {args['target']}")
    grp = target[args["group_col"]]
    peers = sorted((r for r in rows if r.get(args["group_col"]) == grp),
                   key=lambda r: _tofloat(r.get(args["score_col"])) or -1e18, reverse=True)
    return args.get("pos", "yes") if target in peers[: int(args["n"])] else args.get("neg", "no")


def cell_lookup(inputs: list[Path], args: dict) -> Any:
    """Read one deposited cell from inputs[0]. args: {line, column} OR {row: {col: val, ...}, column}."""
    col = args["column"]
    if "line" in args:  # physical file line (1-indexed), matches the L<line>:<col> obs contract
        lines = _lines(inputs[0])
        header = lines[0]
        if col not in header:
            raise KeyError(f"column {col!r} absent")
        return lines[int(args["line"]) - 1][header.index(col)]
    filt = args["row"]
    hit = [r for r in _rows(inputs[0]) if all(str(r.get(k, "")).strip() == str(v) for k, v in filt.items())]
    if not hit:
        raise KeyError(f"no row {filt}")
    return hit[0][col]


REFERENCE_REGISTRY: dict[str, Callable[[list[Path], dict], Any]] = {
    "count_where": count_where, "fraction_where": fraction_where, "frac_where": fraction_where,
    "mean": mean, "pearson": pearson, "count_in_top_n": count_in_top_n,
    "rule_classify": rule_classify, "top_n_per_group": top_n_per_group, "cell_lookup": cell_lookup,
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

    # ci_interval: the reported point must fall within its declared CI (bounds are sibling obs, already
    # in the CSV). CI-aware => bootstrap noise on a genuine reproduction is not flagged. No recompute.
    if kind == "ci_interval":
        lo = obs_index.get(tol.get("lo_obs"), {}).get("value")
        hi = obs_index.get(tol.get("hi_obs"), {}).get("value")
        if lo is None or hi is None:
            return f"fail:missing CI bounds {tol.get('lo_obs')}/{tol.get('hi_obs')}"
        fv = _tofloat(val)
        return "ok" if fv is not None and lo <= fv <= hi else f"fail:{val} not in [{lo},{hi}]"

    # otherwise recompute via the declared method, then compare under the tolerance.
    method = rc.get("method", {})
    inputs = [case_dir / i for i in rc.get("inputs", [])]
    if method.get("reference_fn"):
        fn = REFERENCE_REGISTRY.get(method["reference_fn"])
        if not fn:
            return f"skip:no reference_fn {method['reference_fn']!r} in registry"
        try:
            got = fn(inputs, method.get("args", {}))
        except LookupError as e:  # unknown named rule -> w1 registry TODO, not a data fail
            return f"skip:{e}"
        except Exception as e:  # noqa: BLE001
            return f"fail:recompute error {str(e)[:60]}"
    elif method.get("code_entry"):
        return f"skip:code_entry {method['code_entry']!r} (sandbox path deferred)"
    else:
        return "skip:no method"

    if kind == "exact":
        return "ok" if str(got).strip() == str(val).strip() or _num_eq(got, val, rel_tol=0.0) \
            else f"fail:recomputed={got!r} != obs={val!r}"
    if kind == "rel_tol":
        return "ok" if _num_eq(got, val, tol.get("rel_tol", 1e-3)) else f"fail:recomputed={got} != obs={val}"
    return f"skip:unknown tolerance kind {kind!r}"
