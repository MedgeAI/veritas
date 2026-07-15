"""Deterministic L1 verifier for the closed eval loop — operates on the two in-memory value series.

B3's typed verifier for L1 source-data consistency: given the source/target series an L1 claim
compares, decide if they are byte-identical (duplication), differ by a constant (fixed offset), or
are a near-perfect linear transform (slope != 1). Any of those fires an `inconsistent` signal with a
grounded span; otherwise the locus is clean.

HONEST LIMIT (surfaced, not hidden): identical values map to THREE different gold verdicts in the
signed corpus — inconsistent (cross-experiment copy), consistent (legitimate reuse / FP trap),
insufficient (undecidable). A value-only verifier cannot tell them apart, so on the FP-trap and
insufficient cases it WILL false-fire. That gap is exactly the verifier_conflict signal B3 is meant
to expose against the agent/context tiers — do not tune it away.
"""

from __future__ import annotations

from engine.benchmark.agent_harness import TypedVerifier, VerifierSignal
from engine.benchmark.schema import BenchmarkCase, ClaimInstance


def _linreg(a: list[float], b: list[float]) -> tuple[float, float, float]:
    """Least-squares b ~ slope*a + intercept; returns (r2, slope, intercept)."""
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    saa = sum((x - ma) ** 2 for x in a)
    sab = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    sbb = sum((y - mb) ** 2 for y in b)
    if saa == 0 or sbb == 0:
        return (1.0 if saa == sbb else 0.0), 0.0, mb
    slope = sab / saa
    r2 = (sab * sab) / (saa * sbb)
    return r2, slope, mb - slope * ma


def classify_relationship(a: list[float], b: list[float], *, r2_thresh: float = 0.999,
                          slope_eps: float = 0.02, offset_eps: float = 1e-6) -> tuple[str, str]:
    """Return (kind, detail). kind ∈ {duplicate, constant_offset, linear_transform, independent}."""
    if len(a) != len(b) or len(a) < 2:
        return "independent", "length mismatch or too short"
    if all(abs(x - y) <= offset_eps for x, y in zip(a, b)):
        return "duplicate", "byte-identical series"
    diffs = [y - x for x, y in zip(a, b)]
    if max(diffs) - min(diffs) <= offset_eps:
        return "constant_offset", f"constant offset {diffs[0]:+.6g}"
    # linear needs >= 3 points: any 2 points fit a line perfectly (r2=1), a spurious "transform".
    r2, slope, intercept = _linreg(a, b)
    if len(a) >= 3 and r2 >= r2_thresh and abs(slope - 1.0) > slope_eps:
        return "linear_transform", f"slope={slope:.4g} intercept={intercept:.4g} r2={r2:.5f}"
    return "independent", f"no exact relation (r2={r2:.4f}, slope={slope:.4g})"


def l1_relationship_verifier() -> TypedVerifier:
    """A TypedVerifier (B3): fires `inconsistent` on duplicate / constant-offset / linear-transform."""

    def verify(claim: ClaimInstance, _case: BenchmarkCase) -> VerifierSignal | None:
        md = claim.metadata or {}
        if md.get("axis") != "L1":
            return None  # not in scope
        a, b = md.get("src_series") or [], md.get("tgt_series") or []
        kind, _detail = classify_relationship(a, b)
        span = f"L1:{md.get('src_label')}->{md.get('tgt_label')}"
        fired = kind in ("duplicate", "constant_offset", "linear_transform")
        return VerifierSignal(relation="L1", fired=fired, evidence_span=span, confidence=1.0)

    return verify
