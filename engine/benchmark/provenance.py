"""Provenance Consistency (edge) verifiers — the L1-L4 layer of the claim provenance chain.

These are the B4 tools: they check whether each TRANSFORMATION is faithful, complementing the
Artifact-Integrity (B3) node checks. This module ships the L1 skeleton and the shared comparison
core; L2/L3/L4 verifiers slot in the same shape.

  L1 (C->T): does the code's output equal the value reported in the table?

Rerunning code is subprocess I/O that MUST go through the runtime layer, so replay is a pluggable
BOUNDARY (`ReplayFn`) — stubbed / cached in tests, runtime-backed in production. The rounding-aware
comparison (`values_consistent`) is the substantive, testable part: it must NOT flag 0.0501 vs a
reported 0.05 (a false-positive trap), but MUST flag a genuine mismatch.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from engine.benchmark.agent_harness import TypedVerifier, VerifierSignal
from engine.benchmark.schema import BenchmarkCase, ClaimInstance, parse_evidence_span


@dataclass(frozen=True)
class ComputedValue:
    """Result of replaying code for one L1 target, with the code's OWN reported uncertainty.

    ci_lo/ci_hi (bootstrap CI) and sd let the comparison be CI/SD-aware for stochastic pipelines,
    so a reproducible seed difference is not mistaken for fraud.
    """

    value: float | None
    ok: bool                 # did replay succeed (reproducible)?
    detail: str = ""
    ci_lo: float | None = None
    ci_hi: float | None = None
    sd: float | None = None


# The replay boundary: (code locus = span source, output locus = span target, case) -> computed
# value. A real runtime impl reruns `source` and extracts `target`; the cached impls below just
# READ the already-materialised code output at `target` (the team pre-runs each paper and stores
# results/*.csv), so no sandbox is needed to wire the plumbing.
ReplayFn = Callable[[str, str, BenchmarkCase], ComputedValue]


def static_replay(computed_by_locus: dict[str, float]) -> ReplayFn:
    """A ReplayFn over pre-recorded {output_locus: value} — for tests / fully-cached outputs."""

    def replay(_source: str, target: str, _case: BenchmarkCase) -> ComputedValue:
        if target in computed_by_locus:
            return ComputedValue(float(computed_by_locus[target]), ok=True)
        return ComputedValue(None, ok=False, detail=f"no cached value for {target!r}")

    return replay


def _read_csv_cell(path: Path, key: str) -> float | None:
    """Read a numeric cell from a results CSV. key = '<row_id>_<column>' (e.g. 'xgb_C_mean' -> row
    where col0=='xgb', column 'C_mean') or just '<column>' for a single-row table."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return None
    header = rows[0]
    best_col, best_len = None, -1
    for col in header[1:]:
        if (key == col or key.endswith("_" + col)) and len(col) > best_len:
            best_col, best_len = col, len(col)
    if best_col is None:
        return None
    col_idx = header.index(best_col)
    row_id = None if key == best_col else key[: -(len(best_col) + 1)]
    for r in rows[1:]:
        if row_id is None or (r and r[0] == row_id):
            try:
                return float(r[col_idx])
            except (ValueError, IndexError):
                return None
    return None


def results_replay(base_dir: str | Path) -> ReplayFn:
    """A ReplayFn that READS the code-output value from a pre-run results CSV under base_dir.

    The output locus (span target) is '<csv path relative to base_dir>:<row_id>_<column>', e.g.
    'code/results/summary_metrics.csv:xgb_C_mean'. This is the team's guaranteed code-output side
    (they rerun each paper and store results/*.csv); the runtime-backed rerun impl comes later.
    """
    base = Path(base_dir)

    def replay(_source: str, target: str, _case: BenchmarkCase) -> ComputedValue:
        if ":" not in target:
            return ComputedValue(None, ok=False, detail=f"no key in output locus {target!r}")
        path_part, key = target.rsplit(":", 1)
        path = base / path_part
        if not path.exists():
            return ComputedValue(None, ok=False, detail=f"missing results file {path_part}")
        value = _read_csv_cell(path, key)
        if value is None:
            return ComputedValue(None, ok=False, detail=f"no cell {key!r} in {path_part}")
        # for a '<metric>_mean' output, also read its reported uncertainty (sd / bootstrap CI) so a
        # stochastic pipeline is judged CI-aware rather than by a too-tight fixed tolerance.
        ci_lo = ci_hi = sd = None
        if key.endswith("_mean"):
            stem = key[: -len("_mean")]
            sd = _read_csv_cell(path, stem + "_sd")
            ci_lo = _read_csv_cell(path, stem + "_boot_lo")
            ci_hi = _read_csv_cell(path, stem + "_boot_hi")
        return ComputedValue(value, ok=True, ci_lo=ci_lo, ci_hi=ci_hi, sd=sd)

    return replay


def values_consistent(reported: float | str, computed: float | None, *,
                      rel_tol: float = 1e-3, abs_tol: float = 1e-9,
                      ci_lo: float | None = None, ci_hi: float | None = None,
                      sd: float | None = None, sd_k: float = 2.0) -> bool:
    """Is `computed` consistent with the `reported` value?

    Consistent if ANY holds: reported is inside the code's own bootstrap CI [ci_lo, ci_hi]
    (STOCHASTIC pipelines — the right tolerance, so a seed difference is not flagged); OR within
    sd_k standard deviations of the computed value; OR within a fixed rel/abs tolerance; OR rounds
    to `reported` at its displayed precision (0.0501 -> '0.05'). CI/SD default off (deterministic).
    """
    if computed is None:
        return False
    reported_num = float(reported)
    if ci_lo is not None and ci_hi is not None and ci_lo <= reported_num <= ci_hi:
        return True
    if sd is not None and sd > 0 and abs(reported_num - computed) <= sd_k * sd:
        return True
    if math.isclose(reported_num, computed, rel_tol=rel_tol, abs_tol=abs_tol):
        return True
    if isinstance(reported, str) and "." in reported:
        decimals = len(reported.split(".", 1)[1])
        if round(computed, decimals) == reported_num:
            return True
    return False


def _reported_value(claim: ClaimInstance) -> float | str | None:
    md = claim.metadata or {}
    for key in ("reported_value", "reported", "table_value"):
        if md.get(key) is not None:
            return md[key]
    return None


def l1_computation_verifier(replay: ReplayFn, *, rel_tol: float = 1e-3) -> TypedVerifier:
    """B4/L1 — flag a claim iff the code's replayed output disagrees with the reported table value.

    In scope only for L1 claims that carry a reported value. Returns None when out of scope or when
    replay fails (not reproducible -> the verifier abstains and the agent handles it).
    """

    def verify(claim: ClaimInstance, case: BenchmarkCase) -> VerifierSignal | None:
        if claim.level != "L1":
            return None
        reported = _reported_value(claim)
        if reported is None:
            return None
        _relation, source, target = parse_evidence_span(claim.evidence_span or "")
        computed = replay(source, target, case)
        if not computed.ok:
            return None  # could not reproduce / read output -> abstain, fall back to the agent
        fired = not values_consistent(reported, computed.value, rel_tol=rel_tol,
                                      ci_lo=computed.ci_lo, ci_hi=computed.ci_hi, sd=computed.sd)
        span = f"L1:{source}->{target}" if source or target else claim.evidence_span
        return VerifierSignal(claim.relation, fired=fired, evidence_span=span, confidence=0.9)

    return verify


def _span_parts(claim: ClaimInstance) -> tuple[str, str]:
    _relation, source, target = parse_evidence_span(claim.evidence_span or "")
    return source, target


# ---- L2 (D->C): does the code implement the method the paper describes? --------------------

@dataclass(frozen=True)
class ImplementedMethod:
    name: str | None
    ok: bool
    detail: str = ""


MethodProbeFn = Callable[[str, BenchmarkCase], ImplementedMethod]

# synonym groups so a naming difference is NOT flagged (false-positive trap: same method, other name)
_METHOD_SYNONYMS = [
    {"ols", "linear regression", "linear model", "lm", "least squares"},
    {"t-test", "student t-test", "two-sample t-test", "independent t-test"},
    {"psm", "propensity score matching"},
    {"mann-whitney", "mann-whitney u", "wilcoxon rank-sum"},
    {"anova", "analysis of variance"},
]


def static_method_probe(implemented_by_source: dict[str, str]) -> MethodProbeFn:
    def probe(source: str, _case: BenchmarkCase) -> ImplementedMethod:
        if source in implemented_by_source:
            return ImplementedMethod(implemented_by_source[source], ok=True)
        return ImplementedMethod(None, ok=False, detail=f"code not analysed for {source!r}")
    return probe


def methods_equivalent(claimed: str | None, implemented: str | None) -> bool:
    if not claimed or not implemented:
        return False
    a, b = claimed.strip().lower(), implemented.strip().lower()
    if a == b:
        return True
    return any(a in group and b in group for group in _METHOD_SYNONYMS)


def l2_method_verifier(probe: MethodProbeFn) -> TypedVerifier:
    """B4/L2 — flag iff the code's actual method differs from the method the paper claims (synonyms OK)."""

    def verify(claim: ClaimInstance, case: BenchmarkCase) -> VerifierSignal | None:
        if claim.level != "L2":
            return None
        claimed = (claim.metadata or {}).get("claimed_method")
        if not claimed:
            return None
        source, target = _span_parts(claim)
        impl = probe(source, case)
        if not impl.ok:
            return None
        fired = not methods_equivalent(str(claimed), impl.name)
        return VerifierSignal(claim.relation, fired=fired, evidence_span=f"L2:{source}->{target}", confidence=0.85)

    return verify


# ---- L3 (T/F->S): does the text claim overstate what the table/figure evidence shows? ------

@dataclass(frozen=True)
class ObservedRelation:
    direction: str | None      # "increase" | "decrease" | "none"
    significant: bool | None
    ok: bool
    detail: str = ""


EvidenceProbeFn = Callable[[str, BenchmarkCase], ObservedRelation]


def static_relation_probe(observed_by_target: dict[str, ObservedRelation]) -> EvidenceProbeFn:
    def probe(target: str, _case: BenchmarkCase) -> ObservedRelation:
        return observed_by_target.get(target, ObservedRelation(None, None, ok=False, detail="not observed"))
    return probe


def l3_claim_verifier(probe: EvidenceProbeFn) -> TypedVerifier:
    """B4/L3 — flag iff the textual claim overstates the evidence (claims significance/direction the
    data does not support). A claim that matches the evidence is not flagged."""

    def verify(claim: ClaimInstance, case: BenchmarkCase) -> VerifierSignal | None:
        if claim.level != "L3":
            return None
        md = claim.metadata or {}
        claimed_dir = md.get("claimed_direction")
        claimed_sig = md.get("claimed_significant")
        if claimed_dir is None and claimed_sig is None:
            return None
        source, target = _span_parts(claim)
        obs = probe(target, case)
        if not obs.ok:
            return None
        fired = False
        if claimed_sig is True and obs.significant is False:
            fired = True                       # claimed significant, evidence isn't -> overstatement
        if claimed_dir and obs.direction and str(claimed_dir) != obs.direction:
            fired = True                       # claimed direction contradicts the evidence
        return VerifierSignal(claim.relation, fired=fired, evidence_span=f"L3:{source}->{target}", confidence=0.8)

    return verify


# ---- L4 (T/D->F): does the figure faithfully encode the underlying data? -------------------

FigureProbeFn = Callable[[str, BenchmarkCase], "list[float] | None"]


def static_figure_probe(encoded_by_target: dict[str, list[float]]) -> FigureProbeFn:
    def probe(target: str, _case: BenchmarkCase) -> list[float] | None:
        return encoded_by_target.get(target)
    return probe


def l4_encoding_verifier(probe: FigureProbeFn, *, rel_tol: float = 1e-2) -> TypedVerifier:
    """B4/L4 — flag iff the figure's encoded values (bar heights/points) diverge from the data table
    (wrong height, truncated axis...). Rounding-tolerant so faithful figures are not flagged."""

    def verify(claim: ClaimInstance, case: BenchmarkCase) -> VerifierSignal | None:
        if claim.level != "L4":
            return None
        data_values = (claim.metadata or {}).get("data_values")
        if not data_values:
            return None
        source, target = _span_parts(claim)
        encoded = probe(target, case)
        if encoded is None:
            return None
        if len(encoded) != len(data_values):
            fired = True
        else:
            fired = not all(values_consistent(d, e, rel_tol=rel_tol) for d, e in zip(data_values, encoded))
        return VerifierSignal(claim.relation, fired=fired, evidence_span=f"L4:{source}->{target}", confidence=0.8)

    return verify
