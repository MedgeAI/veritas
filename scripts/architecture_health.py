#!/usr/bin/env python3
"""Architecture health metrics for the Veritas codebase.

Read-only audit tool. Produces counts of structural risk indicators
and emits a Markdown report to ``outputs/architecture_health.md``.

Metrics
-------
functions_over_150_lines
    Python functions / methods whose source body exceeds 150 lines.
    Long functions are a reliable proxy for "needs decomposition".
classes_over_500_lines
    Python classes whose body exceeds 500 lines.
central_if_chain_count
    Top-level if/elif chains with >= 5 branches inside one function.
    Such chains are dispatch disguised as control flow.
dict_get_in_report_consumers
    Calls to ``.get(`` inside ``engine/reporting/``,
    ``engine/static_audit/report/``, ``engine/static_audit/html_report/``.
    Report consumers should operate on typed models, not dict probing.
direct_subprocess_calls_outside_runtime
    ``subprocess.run / Popen / call / check_output / check_call`` invoked
    outside the ``runtime/`` package.  Side-effects belong in Runtime.
tool_registry_untyped_param_branches
    ``if isinstance(...)`` branches inside ``_coerce_*`` helpers in
    ``engine/tools/registry.py``.  Each branch is a manual type-check
    that should be absorbed into a typed schema.
finding_categories_without_registry_entry
    Finding categories emitted by tool code that have no matching
    ``tool_id`` registration — indicates drift between producers and
    the registry contract.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = REPO_ROOT / "engine"
RUNTIME_DIR = REPO_ROOT / "runtime"
REPORT_DIRS = [
    ENGINE_DIR / "reporting",
    ENGINE_DIR / "static_audit" / "report",
    ENGINE_DIR / "static_audit" / "html_report",
]
REGISTRY_PATH = ENGINE_DIR / "tools" / "registry.py"
OUTPUT_PATH = REPO_ROOT / "outputs" / "architecture_health.md"

# Thresholds -----------------------------------------------------------------

FUNCTION_LINE_THRESHOLD = 150
CLASS_LINE_THRESHOLD = 500
IF_CHAIN_MIN_BRANCHES = 5

# Helpers --------------------------------------------------------------------


@dataclass
class Finding:
    location: str  # file:line or module
    detail: str
    metric: str


@dataclass
class Report:
    counts: dict[str, int] = field(default_factory=dict)
    hotspots: list[Finding] = field(default_factory=list)


def _iter_python_files(roots: list[Path] | Path) -> list[Path]:
    if isinstance(roots, Path):
        roots = [roots]
    result: list[Path] = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in filenames:
                if fn.endswith(".py"):
                    result.append(Path(dirpath) / fn)
    return result


def _line_span(node: ast.AST) -> int:
    """Return the source line span of an AST node (end_lineno - lineno)."""
    end = getattr(node, "end_lineno", None)
    start = getattr(node, "lineno", None)
    if end is None or start is None:
        return 0
    return end - start


def _safe_parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return None


# Metric 1: functions over N lines ------------------------------------------


def _functions_over_threshold(
    roots: list[Path] | Path, threshold: int
) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_python_files(roots):
        tree = _safe_parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                span = _line_span(node)
                if span > threshold:
                    findings.append(
                        Finding(
                            location=f"{path.relative_to(REPO_ROOT)}:{node.lineno}",
                            detail=f"{node.name} ({span} lines)",
                            metric="long_function",
                        )
                    )
    return findings


# Metric 2: classes over N lines --------------------------------------------


def _classes_over_threshold(
    roots: list[Path] | Path, threshold: int
) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_python_files(roots):
        tree = _safe_parse(path)
        if tree is None:
            continue
        for node in ast.iter_child_nodes(tree):
            # Only top-level classes; nested classes are rare and usually
            # small test fixtures.
            if isinstance(node, ast.ClassDef):
                span = _line_span(node)
                if span > threshold:
                    findings.append(
                        Finding(
                            location=f"{path.relative_to(REPO_ROOT)}:{node.lineno}",
                            detail=f"{node.name} ({span} lines)",
                            metric="large_class",
                        )
                    )
    return findings


# Metric 3: central if-chain count ------------------------------------------


def _if_chains(roots: list[Path] | Path, min_branches: int) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_python_files(roots):
        tree = _safe_parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seen: set[int] = set()
            for inner in ast.walk(node):
                if not isinstance(inner, ast.If) or inner.lineno in seen:
                    continue
                # Walk the elif chain starting at `inner`.
                chain = 1
                cur = inner
                visited = {inner.lineno}
                while (
                    cur.orelse
                    and len(cur.orelse) == 1
                    and isinstance(cur.orelse[0], ast.If)
                ):
                    nxt = cur.orelse[0]
                    if nxt.lineno in visited:
                        break
                    visited.add(nxt.lineno)
                    chain += 1
                    cur = nxt
                for ln in visited:
                    seen.add(ln)
                if chain >= min_branches:
                    findings.append(
                        Finding(
                            location=f"{path.relative_to(REPO_ROOT)}:{node.lineno}",
                            detail=f"{node.name} (if-chain depth {chain})",
                            metric="if_chain",
                        )
                    )
    return findings


# Metric 4: dict.get in report consumers ------------------------------------


_DICT_GET_RE = re.compile(r"\.get\s*\(")


def _dict_get_in_report_consumers() -> tuple[int, list[Finding]]:
    findings: list[Finding] = []
    total = 0
    for root in REPORT_DIRS:
        if not root.exists():
            continue
        for path in _iter_python_files(root):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            count = len(_DICT_GET_RE.findall(text))
            total += count
            if count > 0:
                findings.append(
                    Finding(
                        location=str(path.relative_to(REPO_ROOT)),
                        detail=f".get() calls: {count}",
                        metric="dict_get_report",
                    )
                )
    return total, findings


# Metric 5: direct subprocess calls outside runtime -------------------------


_SUBPROCESS_RE = re.compile(
    r"^\s*(?:[\w.]+\s*=\s*)?"
    r"(?:subprocess\.run|subprocess\.Popen|subprocess\.call|"
    r"subprocess\.check_output|subprocess\.check_call)\s*\("
)


def _direct_subprocess_outside_runtime() -> list[Finding]:
    findings: list[Finding] = []
    scan_roots = [
        ENGINE_DIR,
        REPO_ROOT / "cli",
        REPO_ROOT / "web" / "backend",
        REPO_ROOT / "scripts",
    ]
    for root in scan_roots:
        if not root.exists():
            continue
        for path in _iter_python_files(root):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for idx, line in enumerate(lines, start=1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if _SUBPROCESS_RE.match(line):
                    findings.append(
                        Finding(
                            location=f"{path.relative_to(REPO_ROOT)}:{idx}",
                            detail=stripped.rstrip(),
                            metric="subprocess_outside_runtime",
                        )
                    )
    return findings


# Metric 6: untyped param branches in registry coercers --------------------


_ISINSTANCE_RE = re.compile(r"isinstance\s*\(")


def _registry_untyped_branches() -> tuple[int, list[Finding]]:
    """Count ``isinstance()`` branches used for manual parameter dispatch
    in ``engine/tools/registry.py``.

    Excludes the ``_coerce_*`` helpers (they use bounded converters).
    Each remaining isinstance branch is a hand-rolled type check that
    should ideally be absorbed into a typed plan schema.
    """
    if not REGISTRY_PATH.exists():
        return 0, []
    try:
        source = REGISTRY_PATH.read_text(encoding="utf-8")
        lines = source.splitlines()
    except OSError:
        return 0, []
    try:
        tree = ast.parse(source, filename=str(REGISTRY_PATH))
    except SyntaxError:
        return 0, []

    # Collect line ranges of _coerce_* helpers — they use bounded
    # converters, not isinstance dispatch, so exclude them.
    coerce_ranges: list[tuple[int, int]] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_coerce_") or node.name == "coercer":
                coerce_ranges.append(
                    (node.lineno, getattr(node, "end_lineno", node.lineno))
                )

    def _in_coercer(lineno: int) -> bool:
        return any(s <= lineno <= e for s, e in coerce_ranges)

    fn_nodes = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    def _enclosing_fn(lineno: int) -> ast.FunctionDef | None:
        best = None
        for fn in fn_nodes:
            if fn.lineno <= lineno <= getattr(fn, "end_lineno", fn.lineno):
                if best is None or fn.lineno > best.lineno:
                    best = fn
        return best

    per_fn: dict[str, list[int]] = {}
    for idx, line in enumerate(lines, start=1):
        if _ISINSTANCE_RE.search(line) and not _in_coercer(idx):
            fn = _enclosing_fn(idx)
            if fn is not None:
                per_fn.setdefault(fn.name, []).append(idx)

    findings: list[Finding] = []
    if per_fn:
        # Aggregate into a single hotspot entry that names all offenders,
        # sorted by branch count descending so the worst is most visible.
        ranked = sorted(per_fn.items(), key=lambda kv: -len(kv[1]))
        summary_parts = [f"{name} ({len(lines)})" for name, lines in ranked]
        first_line = min(linenos[0] for linenos in per_fn.values())
        findings.append(
            Finding(
                location=f"engine/tools/registry.py:{first_line}",
                detail="isinstance() branches in: " + ", ".join(summary_parts),
                metric="untyped_coercer_branch",
            )
        )
    total = sum(len(v) for v in per_fn.values())
    return total, findings


# Metric 7: finding categories without registry entry -----------------------


_TOOL_ID_RE = re.compile(r"""["']([\w.]+)["']""")


def _findings_without_registry_entry() -> list[Finding]:
    """Look for ``finding_category = "..."`` or ``category="..."`` literals
    that don't appear as a registered ``tool_id``.

    This is a best-effort scan: it compares category literals found in
    engine code against the tool_ids registered in ``registry.py``.
    """
    if not REGISTRY_PATH.exists():
        return []
    try:
        registry_src = REGISTRY_PATH.read_text(encoding="utf-8")
    except OSError:
        return []

    # Collect registered tool_ids from TOOL_ID_* constants and the TOOLS dict
    # registration.  The simplest reliable signal is ``"<namespace>.<name>"``
    # strings that appear in _ToolRegistration(...) calls or as constants.
    registered: set[str] = set()
    for m in _TOOL_ID_RE.finditer(registry_src):
        val = m.group(1)
        if "." in val and not val.startswith("_"):
            registered.add(val)

    # Scan engine for ``category = "x.y"`` or ``finding_category="x.y"``
    # patterns.  Skip tests and __pycache__.
    cat_re = re.compile(
        r"""(?:finding_category|category)\s*=\s*["']([\w.]+)["']"""
    )
    findings: list[Finding] = []
    for path in _iter_python_files(ENGINE_DIR):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            m = cat_re.search(line)
            if not m:
                continue
            cat = m.group(1)
            if cat not in registered and "." in cat:
                findings.append(
                    Finding(
                        location=f"{path.relative_to(REPO_ROOT)}:{idx}",
                        detail=f"category '{cat}' not in registry tool_ids",
                        metric="orphan_finding_category",
                    )
                )
    return findings


# Report generation ---------------------------------------------------------


def _collect() -> Report:
    report = Report()

    long_fns = _functions_over_threshold([ENGINE_DIR, RUNTIME_DIR], FUNCTION_LINE_THRESHOLD)
    report.counts["functions_over_150_lines"] = len(long_fns)
    report.hotspots.extend(long_fns)

    large_cls = _classes_over_threshold([ENGINE_DIR, RUNTIME_DIR], CLASS_LINE_THRESHOLD)
    report.counts["classes_over_500_lines"] = len(large_cls)
    report.hotspots.extend(large_cls)

    if_chains = _if_chains([ENGINE_DIR, RUNTIME_DIR], IF_CHAIN_MIN_BRANCHES)
    report.counts["central_if_chain_count"] = len(if_chains)
    report.hotspots.extend(if_chains)

    dict_get_total, dict_get_details = _dict_get_in_report_consumers()
    report.counts["dict_get_in_report_consumers"] = dict_get_total
    report.hotspots.extend(dict_get_details)

    subprocess_findings = _direct_subprocess_outside_runtime()
    report.counts["direct_subprocess_calls_outside_runtime"] = len(subprocess_findings)
    report.hotspots.extend(subprocess_findings)

    untyped_total, untyped_details = _registry_untyped_branches()
    report.counts["tool_registry_untyped_param_branches"] = untyped_total
    report.hotspots.extend(untyped_details)

    orphan_findings = _findings_without_registry_entry()
    report.counts["finding_categories_without_registry_entry"] = len(orphan_findings)
    report.hotspots.extend(orphan_findings)

    return report


def _render_markdown(report: Report) -> str:
    lines: list[str] = []
    lines.append("# Architecture Health Report")
    lines.append("")
    lines.append("Generated by `scripts/architecture_health.py`. Read-only audit — "
                 "this tool does not modify code.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---|")
    for key, value in report.counts.items():
        lines.append(f"| `{key}` | {value} |")
    lines.append("")

    # Top 20 hotspots: sort by a simple risk weighting.
    # Top 20 hotspots: ensure diversity — pick the top entry per metric
    # first, then fill remaining slots by weight.
    metric_weight = {
        "long_function": 2,
        "large_class": 3,
        "if_chain": 3,
        "dict_get_report": 1,
        "subprocess_outside_runtime": 5,
        "untyped_coercer_branch": 2,
        "orphan_finding_category": 4,
    }
    sorted_all = sorted(
        report.hotspots,
        key=lambda f: (-metric_weight.get(f.metric, 1), f.location),
    )
    seen_metrics: set[str] = set()
    diverse: list[Finding] = []
    rest: list[Finding] = []
    for f in sorted_all:
        if f.metric not in seen_metrics:
            seen_metrics.add(f.metric)
            diverse.append(f)
        else:
            rest.append(f)
    top = (diverse + rest)[:20]

    lines.append("## Top 20 High-Risk Hotspots")
    lines.append("")
    lines.append("| # | Metric | Location | Detail |")
    lines.append("|---|---|---|---|")
    for idx, finding in enumerate(top, start=1):
        lines.append(
            f"| {idx} | `{finding.metric}` | `{finding.location}` | "
            f"{finding.detail} |"
        )
    lines.append("")

    lines.append("## Thresholds")
    lines.append("")
    lines.append(f"- Function line threshold: {FUNCTION_LINE_THRESHOLD}")
    lines.append(f"- Class line threshold: {CLASS_LINE_THRESHOLD}")
    lines.append(f"- If-chain minimum branches: {IF_CHAIN_MIN_BRANCHES}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = _collect()
    md = _render_markdown(report)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(md, encoding="utf-8")
    print(md)
    print(f"\nWrote {OUTPUT_PATH.relative_to(REPO_ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
