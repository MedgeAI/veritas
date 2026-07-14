"""Unified VeritasBench case / claim schema.

Freezes ONE representation that both benchmark sources map into:

  * synthetic twins        engine/twins/injector.py  -> annotations.yaml (source: "injected",
                           cell-level `injection`, `deterministically_verifiable: true`)
  * human-annotated real   ground_truth/**/annotations.yaml (source: "human", `comment_id`
                           PubPeer ref, `confirmed_by_human: true`)

The four evaluation levels are all binary relations between two representations (story arc v3.1):

  L1  Computational-Report Consistency   C -> T / C -> S   (code output vs table / text)
  L2  Method-Implementation Consistency  S_method <-> C    (paper method text vs code)
  L3  Report-Claim Consistency           T/F -> S          (table / figure evidence vs text claim)
  L4  Visual Encoding Fidelity           T/D -> F          (figure faithfully encodes table / data)

NOTE ON CURRENT COVERAGE: every claim_type that exists today (source_data.* / visual.* /
completeness.* / numeric.*) is an *evidence-integrity verifier feeding L3* — exactly as the
story arc demotes image tampering to "an L3 verifier". L1 / L2 / L4 have NO claim_type yet;
their level codes are reserved so those case types can slot in without a schema change.
`level_coverage()` reports which levels a set of cases actually populates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# --- levels & the binary relation each audits -------------------------------------------
LEVELS: dict[str, str] = {
    "L1": "computational_report_consistency",
    "L2": "method_implementation_consistency",
    "L3": "report_claim_consistency",
    "L4": "visual_encoding_fidelity",
}
LEVEL_RELATION: dict[str, str] = {
    "L1": "C->T/S",
    "L2": "S_method<->C",
    "L3": "T/F->S",
    "L4": "T/D->F",
}

# claim_type family -> level. Prefix match on the part before the first dot, then refined.
# Everything shipping today is an L3 evidence-integrity verifier.
_FAMILY_LEVEL: dict[str, str] = {
    "source_data": "L3",
    "visual": "L3",
    "completeness": "L3",
    "numeric": "L3",
    "report": "L3",       # generic L3 (T/F->S) family for Data-Guide JSON claims
    # reserved for future case types:
    "computation": "L1",
    "method": "L2",
    "encoding": "L4",
}

# canonical family per level, used when a Data-Guide claim gives relation_type directly.
_LEVEL_FAMILY: dict[str, str] = {"L1": "computation", "L2": "method", "L3": "report", "L4": "encoding"}

# labels a claim can carry (the binary positive/negative axis for metrics)
LABEL_DIRTY = "dirty"   # an inconsistency genuinely exists at this locus
LABEL_CLEAN = "clean"   # matched clean claim (benign locus) — used to measure false-accusation rate

# Data-Guide verdict vocabulary (richer than label; label is derived from it).
VERDICT_CONSISTENT = "consistent"
VERDICT_INCONSISTENT = "inconsistent"
VERDICT_INSUFFICIENT = "insufficient"
VERDICTS = {VERDICT_CONSISTENT, VERDICT_INCONSISTENT, VERDICT_INSUFFICIENT}

# the three failure modes the benchmark must trigger (story arc v4). A claim may be tagged with
# which one it is built to expose.
FM_GROUNDING = "grounding"
FM_VERIFIER_CONFLICT = "verifier_conflict"
FM_FALSE_POSITIVE_TRAP = "false_positive_trap"
FAILURE_MODES = {FM_GROUNDING, FM_VERIFIER_CONFLICT, FM_FALSE_POSITIVE_TRAP}

# provenance of the ground truth
SOURCE_INJECTED = "injected"
SOURCE_HUMAN = "human"

# benchmark splits. synthetic-test is kept but is NON-headline (real-test is the headline set);
# never reuse synthetic across dev and test.
SPLITS = {"real-test", "synthetic-dev", "synthetic-test"}


def label_from_verdict(verdict: str | None, *, is_clean: bool = False) -> str:
    """Map a Data-Guide verdict (+ is_clean flag) to the binary metrics label.

    Only an explicit `inconsistent` verdict is the positive (dirty) class; consistent /
    insufficient / missing verdicts and any is_clean_claim are the negative (clean) class.
    """
    if is_clean:
        return LABEL_CLEAN
    return LABEL_DIRTY if verdict == VERDICT_INCONSISTENT else LABEL_CLEAN


def parse_evidence_span(span: str) -> tuple[str, str, str]:
    """Split a canonical evidence_span '{relation}:{source}->{target}' into its three parts.

    Missing pieces come back as ''. Example:
        'L1:analysis.py:output_p_value->table1.json:row3_col4'
        -> ('L1', 'analysis.py:output_p_value', 'table1.json:row3_col4')
    """
    relation, _, rest = span.partition(":")
    source, sep, target = rest.partition("->")
    if not sep:  # no '->' — treat the whole remainder as the target locus
        return relation.strip(), "", source.strip()
    return relation.strip(), source.strip(), target.strip()


def level_of(claim_type: str) -> str:
    """Map a claim_type (e.g. 'source_data.duplicate_columns') to its evaluation level."""
    family = str(claim_type).split(".", 1)[0]
    if family not in _FAMILY_LEVEL:
        raise ValueError(f"unknown claim_type family {family!r} (claim_type={claim_type!r})")
    return _FAMILY_LEVEL[family]


@dataclass(frozen=True)
class Evidence:
    """Where the audited relation lives. Cell-level for synthetic; target-only for real."""

    evidence_type: str                 # source_data | image | completeness | numeric | code | runtime
    target: str                        # human-readable locus, e.g. "Fig. 5c (Source Data)"
    workbook: str | None = None
    sheet: str | None = None
    cells: frozenset[str] = frozenset()  # e.g. {"E3", "E4"} — cell-level GT when known


@dataclass(frozen=True)
class ClaimInstance:
    claim_id: str
    claim_type: str                    # e.g. source_data.duplicate_columns
    level: str                         # L1..L4 (derived from claim_type)
    label: str                         # dirty | clean
    relation: str                      # the binary relation audited (LEVEL_RELATION[level])
    evidence: Evidence
    description: str = ""
    source: str = SOURCE_HUMAN         # injected | human
    confirmed_by_human: bool = False
    deterministically_verifiable: bool = False
    comment_id: str | None = None      # PubPeer / reviewer ref (real annotations)
    injection: dict[str, Any] | None = None  # cell-level injection params (synthetic)
    # --- Data-Guide (story arc v4) fields: the provenance EDGE + failure-mode metadata ---
    claim_text: str = ""               # the claim in the paper's own words
    verdict: str | None = None         # consistent | inconsistent | insufficient (label derived from this)
    evidence_span: str | None = None   # canonical edge '{relation}:{source}->{target}'
    discrepancy_type: str | None = None  # e.g. p_value_mismatch, method_mismatch, axis_truncation
    severity: str | None = None        # high | medium | low
    failure_mode_trigger: str | None = None  # grounding | verifier_conflict | false_positive_trap
    per_level_verdicts: dict[str, str] | None = None  # {"L1":"consistent","L2":"inconsistent",...} for FM2
    metadata: dict[str, Any] | None = None   # catch-all: distractor_artifacts, evidence_chain_length, trap_type...

    def __post_init__(self) -> None:
        if self.label not in (LABEL_DIRTY, LABEL_CLEAN):
            raise ValueError(f"claim {self.claim_id}: label must be dirty|clean, got {self.label!r}")
        if self.level not in LEVELS:
            raise ValueError(f"claim {self.claim_id}: unknown level {self.level!r}")
        if self.source not in (SOURCE_INJECTED, SOURCE_HUMAN):
            raise ValueError(f"claim {self.claim_id}: unknown source {self.source!r}")
        if self.verdict is not None and self.verdict not in VERDICTS:
            raise ValueError(f"claim {self.claim_id}: unknown verdict {self.verdict!r}")
        if self.failure_mode_trigger is not None and self.failure_mode_trigger not in FAILURE_MODES:
            raise ValueError(f"claim {self.claim_id}: unknown failure_mode_trigger {self.failure_mode_trigger!r}")


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    split: str                         # real-test | synthetic-dev | synthetic-test
    base_paper_id: str
    claims: tuple[ClaimInstance, ...]
    doi: str | None = None
    pubpeer_url: str | None = None
    # future-proof artifact map: {"source_data": [xlsx...], "pdf": ..., "code": ..., "figures": [...]}
    artifacts: dict[str, Any] = field(default_factory=dict)
    # Data-Guide case-level fields
    title: str | None = None
    language: str | None = None        # python | r | ...
    failure_mode_coverage: dict[str, bool] | None = None  # {"grounding":True,"verifier_conflict":False,...}

    def __post_init__(self) -> None:
        if self.split not in SPLITS:
            raise ValueError(f"case {self.case_id}: split must be one of {sorted(SPLITS)}, got {self.split!r}")

    def dirty_claims(self) -> tuple[ClaimInstance, ...]:
        return tuple(c for c in self.claims if c.label == LABEL_DIRTY)

    def clean_claims(self) -> tuple[ClaimInstance, ...]:
        return tuple(c for c in self.claims if c.label == LABEL_CLEAN)


# --- adapters: existing on-disk formats -> unified schema --------------------------------

def _evidence_from_annotation(row: dict[str, Any]) -> Evidence:
    inj = row.get("injection") or {}
    workbook = sheet = None
    target = str(row.get("target", ""))
    # twin targets look like "<workbook> / <sheet>"; split when present
    if " / " in target:
        workbook, sheet = (part.strip() for part in target.split(" / ", 1))
    cells: frozenset[str] = frozenset()
    # cell refs may be carried explicitly, or reconstructed from injection col+rows
    if inj.get("cells"):
        cells = frozenset(str(c) for c in inj["cells"])
    return Evidence(
        evidence_type=str(row.get("evidence_type", "source_data")),
        target=target,
        workbook=workbook,
        sheet=sheet,
        cells=cells,
    )


def _claim_from_annotation(row: dict[str, Any], *, case_id: str, idx: int, source: str) -> ClaimInstance:
    claim_type = str(row["claim_type"])
    level = level_of(claim_type)
    label = str(row.get("label", LABEL_DIRTY))
    return ClaimInstance(
        claim_id=str(row.get("claim_id") or f"{case_id}::c{idx:03d}"),
        claim_type=claim_type,
        level=level,
        label=label,
        relation=LEVEL_RELATION[level],
        evidence=_evidence_from_annotation(row),
        description=str(row.get("description", "")),
        source=source,
        confirmed_by_human=bool(row.get("confirmed_by_human", source == SOURCE_HUMAN)),
        deterministically_verifiable=bool(row.get("deterministically_verifiable", False)),
        comment_id=row.get("comment_id"),
        injection=row.get("injection"),
    )


# --- adapter: Data-Guide per-case JSON (the canonical GT delivery format) ----------------

def _evidence_from_span(span: str | None, evidence_type: str, *, fallback_target: str = "") -> Evidence:
    if not span:
        return Evidence(evidence_type=evidence_type, target=fallback_target)
    _relation, _source, target = parse_evidence_span(span)
    return Evidence(evidence_type=evidence_type, target=target or fallback_target or span)


def _per_level_verdicts(row: dict[str, Any]) -> dict[str, str] | None:
    """Accept either a nested per_level_verdicts dict or flat L1_verdict.. keys (Data Guide §3.2)."""
    if isinstance(row.get("per_level_verdicts"), dict):
        return {str(k): str(v) for k, v in row["per_level_verdicts"].items()}
    flat = {lvl: row[f"{lvl}_verdict"] for lvl in LEVELS if row.get(f"{lvl}_verdict")}
    return {k: str(v) for k, v in flat.items()} or None


_CASE_JSON_KNOWN_CLAIM_KEYS = frozenset({
    "claim_id", "claim_text", "relation_type", "level", "verdict", "discrepancy_type",
    "evidence_span", "severity", "is_clean_claim", "failure_mode_trigger", "notes",
    "per_level_verdicts", "L1_verdict", "L2_verdict", "L3_verdict", "L4_verdict",
})


def _claim_from_case_json(row: dict[str, Any], *, case_id: str, idx: int, source: str) -> ClaimInstance:
    relation_type = str(row.get("relation_type") or row.get("level") or "L3")
    if relation_type not in LEVELS:
        raise ValueError(f"claim json {idx}: unknown relation_type/level {relation_type!r}")
    verdict = row.get("verdict")
    verdict = str(verdict) if verdict else None
    is_clean = bool(row.get("is_clean_claim", False))
    label = label_from_verdict(verdict, is_clean=is_clean)
    discrepancy = row.get("discrepancy_type")
    family = _LEVEL_FAMILY[relation_type]
    claim_type = f"{family}.{discrepancy}" if discrepancy else f"{family}.unspecified"
    span = row.get("evidence_span")
    metadata = {k: v for k, v in row.items() if k not in _CASE_JSON_KNOWN_CLAIM_KEYS} or None
    return ClaimInstance(
        claim_id=str(row.get("claim_id") or f"{case_id}::c{idx:03d}"),
        claim_type=claim_type,
        level=relation_type,
        label=label,
        relation=LEVEL_RELATION[relation_type],
        evidence=_evidence_from_span(span, family),
        description=str(row.get("notes", "")),
        source=source,
        claim_text=str(row.get("claim_text", "")),
        verdict=verdict,
        evidence_span=str(span) if span else None,
        discrepancy_type=str(discrepancy) if discrepancy else None,
        severity=row.get("severity"),
        failure_mode_trigger=row.get("failure_mode_trigger"),
        per_level_verdicts=_per_level_verdicts(row),
        metadata=metadata,
    )


def _load_case_json(path: Path, *, split: str, case_id: str | None) -> BenchmarkCase:
    doc = json.loads(path.read_text(encoding="utf-8")) or {}
    source = str(doc.get("source", SOURCE_HUMAN))
    cid = case_id or str(doc.get("case_id") or path.stem)
    doi = doc.get("paper_doi") or doc.get("doi")
    claims = tuple(
        _claim_from_case_json(row, case_id=cid, idx=i, source=source)
        for i, row in enumerate(doc.get("claims", []) or [])
    )
    return BenchmarkCase(
        case_id=cid,
        split=split,
        base_paper_id=str(doi or doc.get("paper_title") or cid),
        claims=claims,
        doi=doi,
        artifacts=doc.get("artifacts", {}) or {},
        title=doc.get("paper_title"),
        language=doc.get("language"),
        failure_mode_coverage=doc.get("failure_mode_coverage"),
    )


def load_annotations(path: str | Path, *, split: str, case_id: str | None = None) -> BenchmarkCase:
    """Load a case into the unified BenchmarkCase.

    Dispatches on file type: `.json` -> Data-Guide per-case JSON (canonical GT delivery);
    otherwise the twin/human `paper` + `claims[]` YAML. `source` is taken from the file
    (twins set "injected") and defaults to "human" for hand-annotated files.
    """
    path = Path(path)
    if path.suffix == ".json":
        return _load_case_json(path, split=split, case_id=case_id)
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    paper = doc.get("paper", {}) or {}
    source = str(paper.get("source", SOURCE_HUMAN))
    base_paper_id = str(paper.get("base_paper_id") or paper.get("doi") or paper.get("title") or path.parent.name)
    cid = case_id or str(paper.get("base_paper_id") or path.parent.name)
    claims = tuple(
        _claim_from_annotation(row, case_id=cid, idx=i, source=source)
        for i, row in enumerate(doc.get("claims", []) or [])
    )
    return BenchmarkCase(
        case_id=cid,
        split=split,
        base_paper_id=base_paper_id,
        claims=claims,
        doi=paper.get("doi"),
        pubpeer_url=paper.get("pubpeer_url"),
    )


# --- reporting helpers ------------------------------------------------------------------

def level_coverage(cases: list[BenchmarkCase]) -> dict[str, int]:
    """Count dirty claims per level across cases (which of L1..L4 are actually populated)."""
    counts = {lvl: 0 for lvl in LEVELS}
    for case in cases:
        for claim in case.dirty_claims():
            counts[claim.level] += 1
    return counts
