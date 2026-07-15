"""Closed-loop eval adapter: official case.json (v2.0) -> BenchmarkCase, ORACLE-CONDITIONED, L1 only.

Solves the 遗漏.md #1 risk (eval contract not locked / gold leakage) by wiring the *official* signed
cases into the already-verified `engine.benchmark` agent loop WITHOUT ever showing the agent a gold
answer. The agent receives an oracle-conditioned CANDIDATE claim — the two data loci the paper treats
as independent measurements, plus their raw values — and must itself emit {verdict, evidence_span}.

Red line (taskbrief §): these gold fields are carried on the ClaimInstance for SCORING ONLY and are
NEVER placed in the agent prompt: verdict, discrepancy_type, is_clean_claim, gold evidence_span.
The neutral candidate text is SYNTHESISED from the loci + relation — the raw `claim_atom` is NOT used
verbatim, because its phrasing leaks the answer ("...are independent measurements (genuinely
different)", "...is NOT the best", "...within its own CI"). See test_veritasbench_eval_adapter.

Scope: L1 (the only level with an automatic verifier). Non-L1 claims are dropped.

Series extraction (the two value series compared by an L1 claim) handles the three locus dialects
seen in the signed corpus, in priority order, and FAILS LOUD (claim dropped + logged) if none apply:
  1. explicit A1 range in the atom, e.g. "(B3:G3)" / "(AG13:AG18)"  — row- or column-oriented;
  2. A1 single-cell source/target with distinct columns (clean "two columns" claims) -> column series;
  3. coded keys "9c_r3_C" -> panel+column series down the rows.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from openpyxl.utils import column_index_from_string, get_column_letter

from engine.benchmark.schema import (
    LEVEL_RELATION,
    SOURCE_HUMAN,
    BenchmarkCase,
    ClaimInstance,
    Evidence,
    label_from_verdict,
)

AXIS_L1 = "L1"
_A1_RANGE = re.compile(r"\(([A-Z]+\d+:[A-Z]+\d+)\)")
_A1_CELL = re.compile(r"^(?P<sheet>.+)!(?P<col>[A-Z]+)(?P<row>\d+)$")
_CODED = re.compile(r"^(?P<panel>.+?)_r(?P<row>\d+)_(?P<col>.+)$")


def _loc(cellref: str) -> str:
    """The locus part after '#': 'artifacts/x.xlsx#Fig6!AG13' -> 'Fig6!AG13'."""
    return cellref.split("#", 1)[-1]


def _obs_value(observations: dict, artifact_prefix: str, loc: str):
    key = f"{artifact_prefix}#{loc}"
    o = observations.get(key)
    return o["value"] if o else None


def _expand_a1_range(sheet: str, rng: str) -> list[str]:
    a, b = rng.split(":")
    (ca, ra), (cb, rb) = re.match(r"([A-Z]+)(\d+)", a).groups(), re.match(r"([A-Z]+)(\d+)", b).groups()
    ci0, ci1 = sorted((column_index_from_string(ca), column_index_from_string(cb)))
    ri0, ri1 = sorted((int(ra), int(rb)))
    return [f"{sheet}!{get_column_letter(c)}{r}"
            for c in range(ci0, ci1 + 1) for r in range(ri0, ri1 + 1)]


def _series_for_locus(observations: dict, cellref: str, atom: str, which: str,
                      explicit_range: str | None = None) -> tuple[list[float] | None, str]:
    """Return (series, method) for `which` ('src'|'tgt'). method ∈ {'range','column','coded',''}.

    Priority: the CONTRACT field `source/target_a1_range` (data window Round-2 delivery) — an explicit
    A1 range on the artifact's sheet, unambiguous. Falls back to parsing a range out of the atom, then
    to heuristic column/coded reconstruction (retained for any pre-contract case)."""
    prefix = cellref.split("#", 1)[0]
    loc = _loc(cellref)
    idx = 0 if which == "src" else 1
    m0 = _A1_CELL.match(loc)
    sheet = m0["sheet"] if m0 else loc.split("!")[0]

    # method 'range' (preferred): explicit contract range on the artifact's sheet.
    if explicit_range:
        vals = [_obs_value(observations, prefix, c) for c in _expand_a1_range(sheet, explicit_range)]
        vals = [v for v in vals if v is not None]
        if vals:
            return vals, "range"

    # method 'range' (legacy): an A1 range embedded in the atom text.
    ranges = _A1_RANGE.findall(atom or "")
    if idx < len(ranges):
        vals = [_obs_value(observations, prefix, c) for c in _expand_a1_range(sheet, ranges[idx])]
        vals = [v for v in vals if v is not None]
        if vals:
            return vals, "range"

    # method 'column': A1 single cell -> the whole spreadsheet column (heuristic)
    m = _A1_CELL.match(loc)
    if m:
        pat = re.compile(rf"^{re.escape(m['sheet'])}!{m['col']}\d+$")
        rows = sorted((int(_A1_CELL.match(_loc(k))["row"]), observations[k]["value"])
                      for k in observations if pat.match(_loc(k)))
        if rows:
            return [v for _, v in rows], "column"

    # method 'coded': coded key "panel_rN_col" -> panel+column series (heuristic)
    c = _CODED.match(loc)
    if c:
        rows = []
        for k in observations:
            kc = _CODED.match(_loc(k))
            if kc and kc["panel"] == c["panel"] and kc["col"] == c["col"]:
                rows.append((int(kc["row"]), observations[k]["value"]))
        if rows:
            return [v for _, v in sorted(rows)], "coded"

    return None, ""


def _locus_label(cellref: str, atom: str, which: str) -> str:
    """Human locus label for the neutral candidate text (no verdict content)."""
    ranges = _A1_RANGE.findall(atom or "")
    idx = 0 if which == "src" else 1
    loc = _loc(cellref)
    sheet = loc.split("!")[0] if "!" in loc else loc
    if idx < len(ranges):
        return f"{sheet} {ranges[idx]}"
    return loc


def _neutral_claim_text(src_label: str, tgt_label: str) -> str:
    """Oracle-safe candidate: states what the PAPER asserts, never the gold verdict/discrepancy."""
    return (
        f"The paper presents the value series at '{src_label}' and at '{tgt_label}' as two "
        f"independent measurements (L1 source-data internal consistency). Decide whether the data "
        f"is consistent with that, or shows a suspicious exact relationship between the two series."
    )


def _l1_claim(row: dict, *, case_id: str, idx: int, observations: dict,
              explicit_range_only: bool) -> ClaimInstance | None:
    atom = row.get("claim_atom", "")
    src_ref, tgt_ref = row.get("source_artifact", ""), row.get("target_artifact", "")
    src, sm = _series_for_locus(observations, src_ref, atom, "src", row.get("source_a1_range"))
    tgt, tm = _series_for_locus(observations, tgt_ref, atom, "tgt", row.get("target_a1_range"))
    if not src or not tgt:
        return None  # fail loud at load: undecodable locus -> caller logs + counts, never silent-wrong
    # eval<->data contract: a span is verifier-extractable ONLY via an explicit A1 range; heuristic
    # column/coded reconstruction mis-extracts, so the clean pilot keeps range-only (taskbrief §收窄).
    if explicit_range_only and not (sm == "range" and tm == "range"):
        return None
    def label_for(ref, rng, which):
        sheet = _loc(ref).split("!")[0] if "!" in _loc(ref) else _loc(ref)
        return f"{sheet} {rng}" if rng else _locus_label(ref, atom, which)
    src_label = label_for(src_ref, row.get("source_a1_range"), "src")
    tgt_label = label_for(tgt_ref, row.get("target_a1_range"), "tgt")
    verdict = row.get("verdict")
    verdict = str(verdict) if verdict else None
    return ClaimInstance(
        claim_id=str(row.get("claim_id") or f"{case_id}::c{idx:03d}"),
        claim_type="source_data.l1_consistency",
        level="L1",
        label=label_from_verdict(verdict, is_clean=bool(row.get("is_clean_claim", False))),
        relation=LEVEL_RELATION["L1"],
        claim_text=_neutral_claim_text(src_label, tgt_label),
        evidence=Evidence(evidence_type="source_data", target=tgt_label),
        # GOLD — scoring only, MUST NOT be rendered into the prompt. The grounding target is the
        # LOCUS (derived from the allowed source/target artifacts, not the verdict): the raw gold
        # span is generic ("L1:source_data->source_data") so evidence-precision would be untestable;
        # we anchor grounding on the specific locus instead (raw gold span kept in metadata).
        verdict=verdict,
        evidence_span=f"L1:{src_label}->{tgt_label}",
        discrepancy_type=str(row["discrepancy_type"]) if row.get("discrepancy_type") else None,
        source=SOURCE_HUMAN,
        metadata={"axis": AXIS_L1, "src_series": src, "tgt_series": tgt,
                  "src_label": src_label, "tgt_label": tgt_label,
                  "gold_evidence_span": str(row.get("evidence_span") or "")},
    )


def load_veritasbench_case(case_dir: str | Path, *, split: str = "real-test",
                           explicit_range_only: bool = True) -> tuple[BenchmarkCase, dict]:
    """Load one official case.json into an L1-only, oracle-conditioned BenchmarkCase.

    Returns (case, report) where report={'total_l1','loaded','dropped'} — dropped = undecodable-locus
    or (when explicit_range_only) non-range claims (fail-loud, never silently rendered wrong-series).
    """
    case_dir = Path(case_dir)
    doc = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    observations = doc.get("observations") or {}
    cid = str(doc.get("case_id") or case_dir.name)

    claims: list[ClaimInstance] = []
    l1 = 0
    for i, row in enumerate(doc.get("claims", []) or []):
        if str(row.get("relation_type") or row.get("level")) != "L1":
            continue
        l1 += 1
        c = _l1_claim(row, case_id=cid, idx=i, observations=observations,
                      explicit_range_only=explicit_range_only)
        if c is not None:
            claims.append(c)

    case = BenchmarkCase(
        case_id=cid, split=split, base_paper_id=str(doc.get("paper_title") or cid),
        claims=tuple(claims), artifacts={"data": str(case_dir)}, title=doc.get("paper_title"),
    )
    return case, {"total_l1": l1, "loaded": len(claims), "dropped": l1 - len(claims)}


def veritasbench_renderer():
    """Neutral oracle renderer: the two raw value series + basic descriptive stats, NO leading hints.

    Deliberately gives NO word that pre-judges (no 'duplicate'/'identical'/'suspicious'): the agent
    must read the numbers and decide, keeping the B1 baseline clean (taskbrief red line)."""

    def render(claim: ClaimInstance, _case: BenchmarkCase) -> str:
        md = claim.metadata or {}
        a, b = md.get("src_series") or [], md.get("tgt_series") or []

        def stat(xs):
            n = len(xs)
            mean = sum(xs) / n if n else 0.0
            sd = (sum((x - mean) ** 2 for x in xs) / n) ** 0.5 if n else 0.0
            return f"n={n}, mean={mean:.4g}, sd={sd:.4g}"

        return (
            f"SERIES A (source, {md.get('src_label')}): {a}\n  [{stat(a)}]\n"
            f"SERIES B (target, {md.get('tgt_label')}): {b}\n  [{stat(b)}]"
        )

    return render
