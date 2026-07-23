"""E1 discovery + provenance-linking scorer (discovery-conditioned).

The oracle eval (metrics.py) GIVES the claim and scores the verdict. E1 inverts
this: the system PROPOSES claims (claim_extractor role) and links them to
source-data loci (claim_enricher + source_data_auditor); we score against a
human gold annotation (case.json claims[]).

Scores (DAG E1, minimum version — discovery + linking; e2e claim verdict is a
scaffold because audit-paper does not emit consistent/inconsistent/insufficient
on discovered claims):

  - discovery precision/recall/F1: of gold quantitative claims, how many did the
    system discover, and how many of its proposals were spurious.
  - provenance-linking accuracy: of discovered (matched) claims, did the system
    point at the correct source-data target locus (cell-range precise, reusing
    the adapter's _expand_a1_range; artifact-basename is a coarse fallback).
  - (e2e inconsistency recall / claim-level FAR: scaffold — requires claim
    verdicts on discovered claims, which the audit-paper pipeline does not
    currently emit; populate once a verdict pass is added).

This scorer REUSES veritas-system primitives rather than re-rolling regex:
  - veritasbench_eval_adapter._series_for_locus  -> gold numeric enrichment
    (handles the 3 locus dialects: explicit range / column / coded key), so a
    textual claim_atom whose values live only in observations still matches on
    its real value series (the ncb_sting failure that motivated this).
  - veritasbench_eval_adapter._loc / _expand_a1_range  -> locus stripping +
    cell-range expansion for linking; the cell-set intersection with the gold
    TARGET range is the precise analog of agent_harness._evidence_matches
    (which compares target loci), applied to raw artifact loci rather than
    '{rel}:src->tgt' spans.

System input: either the static_audit_bundle.json (preferred; has claims[] +
claim_mappings[]) or the raw role files agent_claim_extractor.json +
agent_source_data_auditor.json.
Gold input: case.json (claims[] with claim_atom, source_artifact,
target_artifact, source_a1_range, target_a1_range, verdict, is_clean_claim).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from engine.benchmark.veritasbench_eval_adapter import (
    _expand_a1_range,
    _loc,
    _series_for_locus,
)

LABEL_CLEAN = "clean"
LABEL_DIRTY = "dirty"

# numeric values: integers, decimals, scientific notation (exclude bare years/4-digit to reduce noise)
_NUM_RE = re.compile(r"(?<![\w.])\d{1,6}(?:\.\d{1,12})?(?:[eE][+-]?\d+)?(?![\w])")
_A1_SINGLE = re.compile(r"^([A-Z]+)(\d+)$")
# numeric match tolerance — series values are floats; system text parses to float too
_NUM_TOL = 1e-6


@dataclass
class SysClaim:
    text: str
    claim_type: str = ""
    mentioned_refs: list[str] = field(default_factory=list)
    source_data_refs: list[str] = field(default_factory=list)  # linked artifact loci
    evidence_refs: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class GoldClaim:
    claim_id: str
    atom: str
    source_artifact: str
    target_artifact: str
    source_a1: str
    target_a1: str
    verdict: str
    is_clean: bool
    numbers: set[float] = field(default_factory=set)  # enriched from observations
    raw: dict = field(default_factory=dict)


# ---- loaders ----


def _load_json(p: str | Path) -> dict:
    return json.load(open(p, encoding="utf-8"))


def load_system(case_dir: Path) -> list[SysClaim]:
    """Read static_audit_bundle.json if present, else raw role files."""
    bundle = (
        case_dir / "research-integrity-audit" / "reports" / "static_audit_bundle.json"
    )
    if bundle.exists():
        d = _load_json(bundle)
        # claim_id -> source_data_refs from claim_mappings[]
        ref_map: dict[str, list[str]] = {}
        for m in d.get("claim_mappings", []):
            cid = m.get("claim_id") or m.get("mapping_id")
            refs = list(m.get("evidence_refs", []))
            refs += list((m.get("metadata") or {}).get("source_data_refs", []))
            if cid:
                ref_map[cid] = refs
        out = []
        for c in d.get("claims", []):
            cid = c.get("claim_id")
            out.append(
                SysClaim(
                    text=c.get("text") or c.get("claim_text") or "",
                    claim_type=c.get("claim_type", ""),
                    mentioned_refs=list(c.get("mentioned_refs", [])),
                    source_data_refs=ref_map.get(cid, list(c.get("evidence_refs", []))),
                    evidence_refs=list(c.get("evidence_refs", [])),
                    raw=c,
                )
            )
        return out
    # fallback: raw role files
    root = case_dir / "research-integrity-audit"
    ce = root / "agent_claim_extractor.json"
    sa = root / "agent_source_data_auditor.json"
    sys_claims: list[SysClaim] = []
    link_map: dict[str, list[str]] = {}
    if sa.exists():
        sd = _load_json(sa)
        for item in sd.get("claim_to_source_data", []):
            link_map[item.get("claim_id", "")] = list(item.get("source_data_refs", []))
    if ce.exists():
        cd = _load_json(ce)
        for c in cd.get("claims", []):
            t = c.get("claim_text", "")
            sys_claims.append(
                SysClaim(
                    text=t,
                    claim_type=c.get("claim_type", ""),
                    mentioned_refs=list(c.get("mentioned_refs", [])),
                    source_data_refs=link_map.get(t, []),
                    raw=c,
                )
            )
    return sys_claims


def load_gold(case_json: Path) -> list[GoldClaim]:
    """Load gold claims, enriching each with its real value series via the
    veritas adapter's _series_for_locus (so textual atoms still carry numbers)."""
    d = _load_json(case_json)
    observations = d.get("observations") or {}
    # _series_for_locus keys observations by full 'prefix#sheet!cell'; list-form
    # observations are unsupported by the adapter -> treat as none (fail loud).
    if not isinstance(observations, dict):
        observations = {}
    out = []
    for c in d.get("claims", []):
        atom = c.get("claim_atom") or c.get("claim_text") or ""
        src_ref = c.get("source_artifact", "") or ""
        tgt_ref = c.get("target_artifact", "") or ""
        src_series, _ = _series_for_locus(
            observations, src_ref, atom, "src", c.get("source_a1_range")
        )
        tgt_series, _ = _series_for_locus(
            observations, tgt_ref, atom, "tgt", c.get("target_a1_range")
        )
        nums: set[float] = set()
        for series in (src_series, tgt_series):
            for v in series or []:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    nums.add(float(v))
        if (
            not nums
        ):  # fallback: numbers embedded in the atom (non-L1 / undecodable locus)
            nums = _to_floats(extract_numbers(atom))
        out.append(
            GoldClaim(
                claim_id=c.get("claim_id", ""),
                atom=atom,
                source_artifact=src_ref,
                target_artifact=tgt_ref,
                source_a1=c.get("source_a1_range", "") or "",
                target_a1=c.get("target_a1_range", "") or "",
                verdict=c.get("verdict", ""),
                is_clean=bool(c.get("is_clean_claim", True)),
                numbers=nums,
                raw=c,
            )
        )
    return out


# ---- alignment primitives ----


def extract_numbers(text: str) -> set[str]:
    return {
        m.group(0)
        for m in _NUM_RE.finditer(text or "")
        if not _is_bare_year(m.group(0))
    }


def _is_bare_year(s: str) -> bool:
    # drop standalone 4-digit years (2019-2026) to reduce noise
    return bool(re.fullmatch(r"(19|20)\d{2}", s))


def _to_floats(values: Iterable[str]) -> set[float]:
    out: set[float] = set()
    for v in values:
        try:
            out.add(float(v))
        except (TypeError, ValueError):
            pass
    return out


def _num_in(x: float, gold: set[float]) -> bool:
    return any(abs(x - y) < _NUM_TOL for y in gold)


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower())}


def _artifact_key(path: str) -> str:
    """Normalize an artifact path/id to its comparable basename (coarse fallback)."""
    p = (path or "").split("#")[0].split("/")[-1].lower()
    p = re.sub(r"\.(xlsx|csv|tsv|pdf)$", "", p)
    return p


def _cells_in(sheet: str, tail: str) -> list[str]:
    """Expand 'sheet' + 'A1:B2' (range) or 'A1' (single cell) -> ['sheet!A1', ...].
    Reuses the adapter's _expand_a1_range for ranges; single cells are a local
    fallback (the adapter expands ranges only)."""
    tail = (tail or "").strip()
    if ":" in tail:
        return _expand_a1_range(sheet, tail)
    if _A1_SINGLE.match(tail):
        return [f"{sheet}!{tail}"]
    return []


def _sheet_of(cellref: str) -> str:
    """'artifacts/x#Extended Data Fig. 2d!I4' -> 'Extended Data Fig. 2d'."""
    loc = _loc(cellref)  # strip the artifact prefix after '#'
    return loc.split("!")[0].strip() if "!" in loc else loc.strip()


def _gold_target_cells(g: GoldClaim) -> set[str]:
    """Cell set for the gold TARGET locus — the thing the system must point at
    (mirrors agent_harness._evidence_matches, which compares target loci)."""
    sheet = _sheet_of(g.target_artifact)
    loc = _loc(g.target_artifact)
    rng = g.target_a1 or (loc.split("!", 1)[1] if "!" in loc else "")
    return {c.lower() for c in _cells_in(sheet, rng)}


def _sys_locus_cells(ref: str) -> set[str]:
    """Cell set the system cited in one ref. Returns {} for a bare path with no
    sheet!range (caller falls back to artifact-basename)."""
    loc = _loc(ref)
    if "!" not in loc:
        return set()
    sheet, tail = loc.split("!", 1)
    return {c.lower() for c in _cells_in(sheet, tail)}


def _claim_score(sys_c: SysClaim, gold: GoldClaim) -> float:
    """Alignment score in [0,1]; >= threshold counts as a match.

    Numeric signal uses the veritas-enriched gold series (gold.numbers), NOT
    extract_numbers(gold.atom) — the ncb_sting atom is pure text; its values
    live only in observations, so atom-only extraction yields 0 overlap."""
    sn = _to_floats(extract_numbers(sys_c.text))
    num_match = sum(1 for x in sn if _num_in(x, gold.numbers))
    num_sim = num_match / len(sn) if sn else 0.0
    # token (word) similarity
    st, gt = _tokens(sys_c.text), _tokens(gold.atom)
    tok_sim = len(st & gt) / len(st | gt) if (st | gt) else 0.0
    # figure/method ref overlap
    ref_sim = 0.0
    if sys_c.mentioned_refs:
        grefs = set(re.findall(r"(?:fig(?:ure)?|table)\s*\d+[a-z]?", gold.atom.lower()))
        grefs |= set(re.findall(r"\b\d+[a-z]\b", gold.source_a1.lower()))
        srefs = {r.lower() for r in sys_c.mentioned_refs}
        ref_sim = len(srefs & grefs) / max(1, len(srefs | grefs))
    # a shared number is the dominant signal for numeric claims
    if num_match > 0 and num_sim >= 0.3:
        return 0.6 + 0.4 * max(tok_sim, ref_sim)
    return max(tok_sim, ref_sim) * 0.5  # weak without number overlap


def align(system: list[SysClaim], gold: list[GoldClaim], threshold: float = 0.5):
    """Greedy best-match alignment. Returns (matches, unmatched_sys, unmatched_gold)."""
    scored = []
    for i, s in enumerate(system):
        for j, g in enumerate(gold):
            sc = _claim_score(s, g)
            if sc >= threshold:
                scored.append((sc, i, j))
    scored.sort(reverse=True)
    used_sys, used_gold = set(), set()
    matches = []
    for sc, i, j in scored:
        if i in used_sys or j in used_gold:
            continue
        matches.append((sc, i, j))
        used_sys.add(i)
        used_gold.add(j)
    unmatched_sys = [i for i in range(len(system)) if i not in used_sys]
    unmatched_gold = [j for j in range(len(gold)) if j not in used_gold]
    return matches, unmatched_sys, unmatched_gold


# ---- metrics ----


def discovery_prf(matches, n_sys, n_gold):
    tp = len(matches)
    p = tp / n_sys if n_sys else 0.0
    r = tp / n_gold if n_gold else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {
        "discovery_precision": round(p, 4),
        "discovery_recall": round(r, 4),
        "discovery_f1": round(f1, 4),
        "n_matched": tp,
        "n_sys": n_sys,
        "n_gold": n_gold,
    }


def linking_accuracy(matches, system, gold):
    """Of matched (discovered) claims, fraction whose system locus points at the
    correct gold TARGET locus. Two granularities (reuses adapter _expand_a1_range
    for cell-range precision; _artifact_key basename is a coarse fallback):
      - linking_accuracy_locus: cell-set intersection with the gold target range
      - linking_accuracy_artifact: same workbook basename (coarse)"""
    if not matches:
        return {
            "linking_accuracy_locus": 0.0,
            "linking_accuracy_artifact": 0.0,
            "n_linkable": 0,
            "n_correct_link_locus": 0,
            "n_correct_link_artifact": 0,
        }
    n = correct_locus = correct_art = 0
    for _, i, j in matches:
        s = system[i]
        g = gold[j]
        sys_refs = s.source_data_refs + s.evidence_refs
        if not sys_refs:
            continue  # system gave no locus -> not linkable for this pair
        n += 1
        gold_cells = _gold_target_cells(g)
        # locus-level: any system-cited cell inside the gold target range
        sys_cells = set()
        for r in sys_refs:
            sys_cells |= _sys_locus_cells(r)
        if gold_cells and sys_cells and (gold_cells & sys_cells):
            correct_locus += 1
        # artifact-level fallback: same workbook basename (when loci don't parse)
        sys_keys = {_artifact_key(r) for r in sys_refs}
        gold_keys = {_artifact_key(g.source_artifact), _artifact_key(g.target_artifact)}
        gold_keys.discard("")
        if gold_keys and (sys_keys & gold_keys):
            correct_art += 1
    return {
        "linking_accuracy_locus": round(correct_locus / n, 4) if n else 0.0,
        "linking_accuracy_artifact": round(correct_art / n, 4) if n else 0.0,
        "n_linkable": n,
        "n_correct_link_locus": correct_locus,
        "n_correct_link_artifact": correct_art,
    }


def e2e_scaffold(matches, gold):
    """Scaffold: e2e recall/FAR requires claim verdicts on discovered claims.
    audit-paper does not emit consistent/inconsistent/insufficient on discovered
    claims today; populate once a verdict pass is added. We report the
    discoverable dirty/clean counts so the denominator is ready."""
    dirty_gold = [j for _, _, j in matches if not gold[j].is_clean]
    clean_gold = [j for _, _, j in matches if gold[j].is_clean]
    return {
        "e2e_recall_dirty_denom": len(dirty_gold),
        "e2e_far_clean_denom": len(clean_gold),
        "e2e_recall": None,
        "claim_far": None,
        "note": "audit-paper emits no claim verdict; run a verdict pass to fill",
    }


def score_case(case_dir: Path, gold_json: Path) -> dict:
    sys_claims = load_system(case_dir)
    gold = load_gold(gold_json)
    matches, unsys, ungold = align(sys_claims, gold)
    m = discovery_prf(matches, len(sys_claims), len(gold))
    m["discovery_false_positives"] = len(unsys)  # spurious system proposals
    m["discovery_false_negatives"] = len(ungold)  # missed gold claims
    m.update(linking_accuracy(matches, sys_claims, gold))
    m.update(e2e_scaffold(matches, gold))
    m["case_id"] = gold_json.parent.name
    return m


# ---- self-test (synthetic system claim vs ncb_sting gold) ----


def _selftest(ncb_dir: Path) -> int:
    """Synthesize the ncb_sting dirty claim as if the system proposed it, with
    the correct target locus, and assert discovery + linking both hit."""
    gold = load_gold(ncb_dir / "case.json")
    dirty = next((g for g in gold if not g.is_clean), None)
    assert dirty, "ncb_sting has a dirty (inconsistent) gold claim"
    # system 'discovers' the claim text and links it to the gold target locus
    sys_claim = SysClaim(
        text=dirty.atom,
        source_data_refs=[dirty.target_artifact],
    )
    matches, _, ungold = align([sys_claim], gold)
    link = linking_accuracy(matches, [sys_claim], gold)
    print(
        json.dumps(
            {
                "gold_dirty_numbers": sorted(dirty.numbers),
                "n_gold": len(gold),
                "n_matched": len(matches),
                "unmatched_gold": ungold,
                "matches": [
                    {
                        "score": round(s, 4),
                        "gold_id": gold[j].claim_id,
                        "gold_is_clean": gold[j].is_clean,
                    }
                    for s, _, j in matches
                ],
                "linking": link,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    ok = bool(matches) and link["linking_accuracy_locus"] == 1.0
    print("✓ selftest PASS" if ok else "✗ selftest FAIL")
    return 0 if ok else 1


# ---- CLI ----


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E1 discovery + linking scorer")
    ap.add_argument(
        "--audit-dir", help="outputs/<case_id> (with research-integrity-audit/)"
    )
    ap.add_argument("--gold", help="case.json gold annotation")
    ap.add_argument("--out", default="e1_pilot_metrics.csv", help="append CSV row")
    ap.add_argument("--print", action="store_true")
    ap.add_argument(
        "--selftest",
        metavar="CASE_DIR",
        help="run the ncb_sting synthetic self-test against this case dir",
    )
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest(Path(a.selftest))
    if not (a.audit_dir and a.gold):
        ap.error("--audit-dir and --gold are required (or use --selftest)")
    m = score_case(Path(a.audit_dir), Path(a.gold))
    cols = [
        "case_id",
        "discovery_precision",
        "discovery_recall",
        "discovery_f1",
        "n_matched",
        "n_sys",
        "n_gold",
        "discovery_false_positives",
        "discovery_false_negatives",
        "linking_accuracy_locus",
        "linking_accuracy_artifact",
        "n_linkable",
        "n_correct_link_locus",
        "n_correct_link_artifact",
        "e2e_recall_dirty_denom",
        "e2e_far_clean_denom",
        "e2e_recall",
        "claim_far",
        "note",
    ]
    out = Path(a.out)
    exists = out.exists()
    with open(out, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if not exists:
            w.writeheader()
        w.writerow({k: m.get(k, "") for k in cols})
    if a.print:
        print(json.dumps(m, ensure_ascii=False, indent=2))
    print(
        f"✓ {a.out} += {m['case_id']}: disc P={m['discovery_precision']} R={m['discovery_recall']} F1={m['discovery_f1']} | link_locus={m['linking_accuracy_locus']} link_art={m['linking_accuracy_artifact']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
