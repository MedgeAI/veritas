"""Deterministic anchoring and enrichment of raw LLM claims.

Takes raw claims from the LLM claim-extraction phase and enriches them with
deterministic references resolved from the evidence ledger, grounding index,
and full-text markdown.  The output is compatible with the
``agent_claim_extractor.json`` schema consumed by downstream audit roles.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_FIG_NUM_RE = re.compile(r"[Ff]ig(?:ure)?[\.\s]*(\d+)")


def _extract_base_figure_number(figure_ref: str) -> str | None:
    """Return the base figure number from a label like 'Fig. 1b' -> '1'."""
    m = _FIG_NUM_RE.search(figure_ref)
    return m.group(1) if m else None


def _normalize_label(label: str | None) -> str:
    """Lowercase, strip, collapse whitespace for fuzzy comparison."""
    if not label:
        return ""
    return re.sub(r"\s+", " ", label.strip().lower())


def _fuzzy_line_match(claim_text: str, lines: list[str]) -> int | None:
    """Return 1-based line number with highest substring overlap.

    Uses a sliding window of words from *claim_text* and returns the first
    line that shares the longest contiguous token sequence.  Returns ``None``
    when no line shares at least three consecutive tokens.
    """
    tokens = claim_text.lower().split()
    if len(tokens) < 3:
        return None

    best_line: int | None = None
    best_overlap = 2  # minimum threshold

    # Build a set of n-grams from claim_text for fast lookup
    ngram_size = min(5, len(tokens))
    claim_ngrams: set[str] = set()
    for n in range(3, ngram_size + 1):
        for i in range(len(tokens) - n + 1):
            claim_ngrams.add(" ".join(tokens[i : i + n]))

    for idx, line in enumerate(lines, start=1):
        line_tokens = line.lower().split()
        if len(line_tokens) < 3:
            continue
        for n in range(ngram_size, 2, -1):
            for i in range(len(line_tokens) - n + 1):
                if " ".join(line_tokens[i : i + n]) in claim_ngrams:
                    if n > best_overlap:
                        best_overlap = n
                        best_line = idx
                    break  # only need one match per n-gram size per line

    return best_line


# ---------------------------------------------------------------------------
# Public sub-functions
# ---------------------------------------------------------------------------


def resolve_figure_refs(
    mentioned_refs: list[str],
    evidence_ledger: dict[str, Any] | None,
) -> list[str]:
    """Resolve *mentioned_refs* to canonical figure labels.

    When *evidence_ledger* is available the function searches its ``figures``
    array and ``indexes.by_figure_label`` for matches.  Otherwise the raw
    *mentioned_refs* are returned as-is (they originated from the grounding
    index menu presented to the LLM).
    """
    if not mentioned_refs:
        return []

    if evidence_ledger is None:
        return list(mentioned_refs)

    resolved: list[str] = []
    ledger_figures: list[dict[str, Any]] = evidence_ledger.get("figures", [])
    by_label: dict[str, Any] = (
        evidence_ledger.get("indexes", {}).get("by_figure_label", {})
    )

    for ref in mentioned_refs:
        norm = _normalize_label(ref)
        matched = False

        # Search figures array
        for fig in ledger_figures:
            for key in ("label", "label_key"):
                if _normalize_label(fig.get(key)) == norm:
                    resolved.append(fig.get("label") or ref)
                    matched = True
                    break
            if matched:
                break

        # Search by_figure_label index
        if not matched and by_label:
            for ledger_label in by_label:
                if _normalize_label(ledger_label) == norm:
                    resolved.append(ledger_label)
                    matched = True
                    break

        if not matched:
            # Keep original ref — it came from the grounding menu
            resolved.append(ref)

    return resolved


def resolve_source_data_refs(
    figure_refs: list[str],
    grounding_index: dict[str, Any],
) -> list[str]:
    """Map figure references to source-data sheet names.

    For each figure ref the base figure number is extracted (e.g. ``"Fig. 1b"``
    -> ``"1"``) and matched against sheet names in
    ``grounding_index["source_data_sheets"]``.
    """
    if not figure_refs or not grounding_index:
        return []

    sheets: list[dict[str, Any]] | list[str] = grounding_index.get(
        "source_data_sheets", []
    )
    if not sheets:
        return []

    # Normalise sheet entries to a list of name strings
    sheet_names: list[str] = []
    for s in sheets:
        if isinstance(s, str):
            sheet_names.append(s)
        elif isinstance(s, dict):
            name = s.get("sheet_name") or s.get("sheet") or s.get("name") or ""
            if name:
                sheet_names.append(str(name))

    resolved: list[str] = []
    for fig_ref in figure_refs:
        base = _extract_base_figure_number(fig_ref)
        if base is None:
            continue
        for name in sheet_names:
            # Match patterns like "Source Data Fig. 1", "Fig. 1", "Fig.1"
            if base in name and re.search(
                r"(?:Source\s+Data\s+)?Fig[\.\s]*" + re.escape(base),
                name,
                re.IGNORECASE,
            ):
                if name not in resolved:
                    resolved.append(name)

    return resolved


def find_line_in_full_md(
    claim_text: str,
    full_md_path: Path | None,
) -> int | None:
    """Find the 1-based line number of *claim_text* in the full markdown.

    Falls back to fuzzy n-gram matching when an exact substring search fails.
    Returns ``None`` when the file is missing or no reasonable match is found.
    """
    if full_md_path is None or not claim_text:
        return None

    try:
        text = full_md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.warning("Cannot read full.md at %s", full_md_path)
        return None

    lines = text.splitlines()

    # Exact substring search
    norm_claim = claim_text.strip()
    for idx, line in enumerate(lines, start=1):
        if norm_claim in line:
            return idx

    # Fuzzy fallback
    return _fuzzy_line_match(claim_text, lines)


def sections_for_line(
    line_no: int | None,
    grounding_index: dict[str, Any],
) -> str:
    """Return the section name containing *line_no*.

    Parses ``grounding_index["sections"]`` whose keys have the form
    ``"start_line-end_line"``.  Returns ``""`` when no match is found or the
    grounding index has no section information.
    """
    if line_no is None or not grounding_index:
        return ""

    sections: dict[str, Any] = grounding_index.get("sections", {})
    if not isinstance(sections, dict):
        return ""

    for range_key, section_info in sections.items():
        try:
            parts = range_key.split("-")
            if len(parts) != 2:
                continue
            start, end = int(parts[0]), int(parts[1])
            if start <= line_no <= end:
                if isinstance(section_info, dict):
                    return str(section_info.get("title") or section_info.get("name") or range_key)
                return str(section_info)
        except (ValueError, TypeError):
            continue

    return ""


def rate_decisiveness(
    raw_claim: dict[str, Any],
    source_data_refs: list[str],
) -> str:
    """Rate how decisive a claim is for the audit.

    Rules:
    * ``numeric`` with non-empty *source_data_refs* -> ``"high"``
    * ``figure_trace`` -> ``"medium"``
    * ``numeric`` with no source data -> ``"low"``
    * Otherwise -> ``"medium"``
    """
    claim_type = raw_claim.get("claim_type", "")
    if claim_type == "numeric" and source_data_refs:
        return "high"
    if claim_type == "figure_trace":
        return "medium"
    if claim_type == "numeric":
        return "low"
    return "medium"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def enrich_claims(
    raw_claims: list[dict[str, Any]],
    grounding_index: dict[str, Any],
    evidence_ledger: dict[str, Any] | None = None,
    full_md_path: Path | None = None,
    case_id: str = "",
) -> dict[str, Any]:
    """Enrich raw LLM claims with deterministic anchoring.

    Parameters
    ----------
    raw_claims:
        List of raw claim dicts from the LLM Phase 2 extraction.  Each must
        contain at least ``claim_text``; optional keys are ``claim_type`` and
        ``mentioned_refs``.
    grounding_index:
        Parsed ``grounding_index.json`` content.
    evidence_ledger:
        Parsed ``evidence_ledger.json`` content, or ``None`` when unavailable.
    full_md_path:
        Path to the paper's ``full.md``, or ``None`` when unavailable.
    case_id:
        Case identifier written into the output envelope.

    Returns
    -------
    dict
        Complete ``agent_claim_extractor.json``-compatible output dict.
    """
    enriched_claims: list[dict[str, Any]] = []
    limitations: list[str] = []

    for idx, raw in enumerate(raw_claims, start=1):
        try:
            claim_text = str(raw.get("claim_text", "")).strip()
            if not claim_text:
                continue

            claim_type = str(raw.get("claim_type", "other")).strip() or "other"
            mentioned_refs: list[str] = list(raw.get("mentioned_refs", []))

            # Resolve figure references
            figure_refs = resolve_figure_refs(mentioned_refs, evidence_ledger)

            # Resolve source-data sheet references
            source_data_refs = resolve_source_data_refs(figure_refs, grounding_index)

            # Locate claim in full.md
            line_no = find_line_in_full_md(claim_text, full_md_path)
            section = sections_for_line(line_no, grounding_index)

            # Build paper_location
            location_parts: list[str] = []
            if section:
                location_parts.append(section)
            if line_no is not None:
                location_parts.append(f"line {line_no}")
            paper_location = " (" .join(location_parts) + ")" if location_parts else ""

            # Rate decisiveness
            decisiveness = rate_decisiveness(raw, source_data_refs)

            enriched: dict[str, Any] = {
                "claim_id": f"AC-{idx:03d}",
                "claim_text": claim_text,
                "claim_type": claim_type,
                "paper_location": paper_location,
                "evidence_refs": [],
                "status": "needs_review",
                "claim_decisiveness": decisiveness,
                "figure_refs": figure_refs,
                "expected_source_data": source_data_refs,
                "claim_source": "claim_extractor",
            }
            enriched_claims.append(enriched)

        except Exception:
            logger.warning(
                "Failed to enrich claim at index %d; skipping", idx, exc_info=True
            )
            limitations.append(f"claim at index {idx} could not be enriched")

    return {
        "schema_version": "1.0",
        "role_id": "claim_extractor",
        "case_id": case_id,
        "status": "ran",
        "claims": enriched_claims,
        "limitations": limitations,
    }
