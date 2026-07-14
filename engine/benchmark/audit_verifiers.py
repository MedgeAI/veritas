"""Audit-line forensics: duplicate-sample-column detection on expression.csv + a NEUTRAL renderer.

The audit tasks inject fabricated samples by COPYING a sample column (exact = v1; near-duplicate =
perturb ~10% of genes = v2 / k10 tasks). Two detector modes make the "exact-match is a reflex"
finding a controlled ablation:

  mode='naive'  : flag a column PAIR only if byte-IDENTICAL (overlap == 1.0). Misses near-dups.
  mode='robust' : flag if byte-identical VALUE OVERLAP >= threshold. A copied-then-perturbed column
                  shares ~85-90% of exact string values; independent columns <~3%; a merely
                  CORRELATED pair (hard negative, r~0.998) shares almost no identical values -> not
                  flagged. So robust separates COPYING from CORRELATION (kills the FP trap).

The renderer feeds a bare agent NEUTRAL descriptive stats only (per-sample mean/sd + the raw
pairwise correlation matrix) — never "these pairs look duplicated" — so B1's baseline is clean and
the B1->B3 ablation is fair.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

from engine.benchmark.agent_harness import ArtifactRenderer, TypedVerifier, VerifierSignal
from engine.benchmark.audit_adapter import AXIS_ARTIFACT
from engine.benchmark.schema import BenchmarkCase, ClaimInstance

_MAX_ROWS = 4000  # subsample rows for speed; near-dup overlap is stable well under this


def _read_str_columns(path: Path, max_rows: int = _MAX_ROWS) -> tuple[list[str], list[list[str]]]:
    """Return (sample_names, columns_of_raw_string_values). Raw strings so 'byte-identical' is exact."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        samples = header[1:]
        cols: list[list[str]] = [[] for _ in samples]
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            for j, v in enumerate(row[1:]):
                if j < len(cols):
                    cols[j].append(v)
    return samples, cols


def _overlap(a: list[str], b: list[str]) -> float:
    n = min(len(a), len(b))
    if not n:
        return 0.0
    return sum(1 for x, y in zip(a, b) if x == y) / n


def _tofloat(v: str) -> float:
    try:
        return float(v)
    except ValueError:
        return 0.0


def _linreg(a: list[float], b: list[float]) -> tuple[float, float]:
    """Least-squares fit b ~ slope*a + intercept; return (r_squared, slope)."""
    n = min(len(a), len(b))
    if n < 3:
        return 0.0, 0.0
    ma = sum(a[:n]) / n
    mb = sum(b[:n]) / n
    sab = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    saa = sum((a[i] - ma) ** 2 for i in range(n))
    sbb = sum((b[i] - mb) ** 2 for i in range(n))
    if saa == 0 or sbb == 0:
        return 0.0, 0.0
    r = sab / (saa ** 0.5 * sbb ** 0.5)
    return r * r, sab / saa


def detect_duplicate_columns(path: str | Path, *, mode: str = "robust", threshold: float = 0.5,
                             r2_threshold: float = 0.999, slope_eps: float = 0.02,
                             max_rows: int = _MAX_ROWS) -> list[tuple[str, str, float]]:
    """Return (sample_a, sample_b, byte_overlap) for column pairs judged duplicated under `mode`.

    naive  : exact byte-identical (overlap==1.0) — the reflex; misses near-dup & linear-transform.
    robust : byte-identical overlap >= threshold (block/near/cross-group copy) OR a near-perfect
             linear fit with slope != 1 (r^2 >= r2_threshold, |slope-1| > slope_eps = mode #5
             linear-transform, which shares NO identical values). A merely-correlated pair
             (slope ~ 1 with biological noise, r^2 < 0.999) is NOT flagged -> copying, not correlation.
    """
    samples, scols = _read_str_columns(Path(path), max_rows)
    fcols = [[_tofloat(v) for v in c] for c in scols]
    out = []
    for i in range(len(samples)):
        for j in range(i + 1, len(samples)):
            ov = _overlap(scols[i], scols[j])
            if mode == "naive":
                hit = ov >= 1.0
            elif ov >= threshold:
                hit = True
            else:
                r2, slope = _linreg(fcols[i], fcols[j])
                hit = r2 >= r2_threshold and abs(slope - 1.0) > slope_eps
            if hit:
                out.append((samples[i], samples[j], ov))
    return out


def audit_integrity_verifier(*, mode: str = "robust", threshold: float = 0.5) -> TypedVerifier:
    """B3 artifact verifier for audit datasets: fires an integrity claim iff a duplicated sample
    column pair is detected in that dataset's expression.csv (blind — GT is not consulted)."""

    def verify(claim: ClaimInstance, case: BenchmarkCase) -> VerifierSignal | None:
        md = claim.metadata or {}
        if md.get("axis") != AXIS_ARTIFACT:
            return None
        dataset = md.get("dataset")
        path = Path(case.artifacts.get("data", "")) / str(dataset) / "expression.csv"
        if not path.exists():
            return None
        dupes = detect_duplicate_columns(path, mode=mode, threshold=threshold)
        detected = sorted({c for pair in dupes for c in pair[:2]})
        fired = bool(dupes)
        span = f"artifact:{dataset}/expression.csv->cols:{','.join(detected)}"
        return VerifierSignal(claim.relation, fired=fired, evidence_span=span, confidence=0.9 if fired else 0.85)

    return verify


def detected_columns(case: BenchmarkCase, dataset: str, *, mode: str = "robust",
                     threshold: float = 0.5) -> set[str]:
    """The sample columns a mode flags in a dataset (for evidence-precision vs GT injected samples)."""
    path = Path(case.artifacts.get("data", "")) / dataset / "expression.csv"
    if not path.exists():
        return set()
    return {c for pair in detect_duplicate_columns(path, mode=mode, threshold=threshold) for c in pair[:2]}


# --- neutral artifact renderer (per guardrail: descriptive stats only, no leading hints) --------

def _read_float_columns(path: Path, max_rows: int = 1500) -> tuple[list[str], list[list[float]]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        samples = header[1:]
        cols: list[list[float]] = [[] for _ in samples]
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            for j, v in enumerate(row[1:]):
                if j < len(cols):
                    try:
                        cols[j].append(float(v))
                    except ValueError:
                        cols[j].append(0.0)
    return samples, cols


def _corr(a: list[float], b: list[float]) -> float:
    try:
        return statistics.correlation(a, b)
    except (statistics.StatisticsError, ValueError):
        return 0.0


def audit_renderer() -> ArtifactRenderer:
    """Render a dataset as NEUTRAL descriptive statistics: sample groups, per-sample mean/sd, and
    the raw pairwise correlation matrix. No interpretation — the agent judges for itself."""

    def render(claim: ClaimInstance, case: BenchmarkCase) -> str:
        dataset = (claim.metadata or {}).get("dataset")
        base = Path(case.artifacts.get("data", "")) / str(dataset)
        expr = base / "expression.csv"
        if not expr.exists():
            return f"(no data for {dataset})"
        samples, cols = _read_float_columns(expr)
        groups: dict[str, str] = {}
        meta = base / "sample_metadata.csv"
        if meta.exists():
            for row in csv.DictReader(open(meta, encoding="utf-8")):
                groups[row.get("sample_id", "")] = row.get("group", "")
        lines = [f"# {dataset}/expression.csv  ({len(samples)} samples, stats over first {len(cols[0]) if cols else 0} features)",
                 "sample  group  mean  sd"]
        for s, c in zip(samples, cols):
            m = statistics.fmean(c) if c else 0.0
            sd = statistics.pstdev(c) if len(c) > 1 else 0.0
            lines.append(f"{s}  {groups.get(s, '?')}  {m:.2f}  {sd:.2f}")
        lines.append("\npairwise correlation matrix:")
        lines.append("     " + " ".join(f"{s:>6s}" for s in samples))
        for i, s in enumerate(samples):
            row = " ".join(f"{_corr(cols[i], cols[j]):6.3f}" for j in range(len(samples)))
            lines.append(f"{s:>4s} {row}")
        return "\n".join(lines)

    return render
