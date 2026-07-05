"""PaperConan Translator: converts paperconan scan results into Veritas canonical NumericSignals.

This module implements the WP2 milestone of the PaperConan integration PRD.
It reads the compact paperconan_scan.json artifact (produced by the existing
adapter) and translates each detector finding into a NumericSignal with full
provenance tracing back to the original scan result.

Translation scope (per PRD WP2):
- relations_blocks[].relations
- relations_blocks[].progressions
- relations_blocks[].equal_pairs
- relations_blocks[].row_pairs
- relations_blocks[].within_col
- relations_blocks[].identical_after_rounding
- relations_blocks[].grim
- cross_sheet_findings[]
- digit_distribution[]
- decimal_endings[]
- scan_errors[]

Each signal MUST have a raw_payload_ref that traces back to the original
paperconan_scan.json path (e.g., "relations_blocks/0/relations/3").

The translator also produces a translation ledger that records every skip
decision (e.g., findings with empty kind, unsupported structures) so that
no signal is silently lost.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.static_audit.numeric_signal_schema import (
    ApplicabilityPremise,
    EvidenceLocator,
    NumericSignal,
    NumericSignalSet,
    generate_signal_id,
    validate_numeric_signal,
)

logger = logging.getLogger(__name__)

# --- Kind -> detector family mapping ---
# This mirrors the coverage matrix in configs/paperconan_detector_coverage.yaml

_KIND_TO_FAMILY: dict[str, str] = {
    # column_relations
    "identical_column": "column_relations",
    "constant_offset": "column_relations",
    "constant_ratio": "column_relations",
    "exact_linear": "column_relations",
    "sum_constant": "column_relations",
    "small_diff_set": "column_relations",
    "partial_constant_offset": "column_relations",
    # copy_tweak_fingerprints
    "integer_diff_shared_fraction": "copy_tweak_fingerprints",
    "row_pair_digit_coupling": "copy_tweak_fingerprints",
    "many_equal_pairs": "copy_tweak_fingerprints",
    "identical_after_rounding": "copy_tweak_fingerprints",
    # within_column
    "within_col_value_duplication": "within_column",
    "within_col_decimal_repetition": "within_column",
    "rounded_to_half_or_int": "within_column",
    "missing_last_digits": "within_column",
    "repeated_two_decimal_endings": "within_column",
    # cross_sheet
    "cross_sheet_position_identical": "cross_sheet",
    "cross_sheet_value_overlap": "cross_sheet",
    "cross_sheet_decimal_tail_reuse": "cross_sheet",
    "cross_sheet_column_duplicate": "cross_sheet",
    # matrix_vector_reuse
    "within_table_fraction_reuse": "matrix_vector_reuse",
    "recurring_row_vector": "matrix_vector_reuse",
    # statistical_impossibility
    "grim_inconsistent": "statistical_impossibility",
    "grimmer_inconsistent": "statistical_impossibility",
    # digit_statistics (virtual kinds for digit_distribution/decimal_endings)
    "last_digit_chi_square": "digit_statistics",
    # progressions
    "arithmetic_progression": "progressions",
}

# --- Kind -> applicability premise ---
# GRIM/GRIMMER require integer-valued items; last-digit requires raw measurement.

_KIND_TO_PREMISE: dict[str, ApplicabilityPremise] = {
    "grim_inconsistent": ApplicabilityPremise(
        requires_integer_valued_items=True,
        requires_independent_rows=True,
        requires_raw_measurement=True,
    ),
    "grimmer_inconsistent": ApplicabilityPremise(
        requires_integer_valued_items=True,
        requires_independent_rows=True,
        requires_raw_measurement=True,
    ),
    "last_digit_chi_square": ApplicabilityPremise(
        requires_raw_measurement=True,
    ),
    "within_col_value_duplication": ApplicabilityPremise(
        requires_raw_measurement=True,
    ),
    "within_col_decimal_repetition": ApplicabilityPremise(
        requires_raw_measurement=True,
    ),
    "rounded_to_half_or_int": ApplicabilityPremise(
        requires_raw_measurement=True,
    ),
    "missing_last_digits": ApplicabilityPremise(
        requires_raw_measurement=True,
    ),
    "repeated_two_decimal_endings": ApplicabilityPremise(
        requires_raw_measurement=True,
    ),
}

# Keys within relations_blocks that contain translatable finding lists
_RELATIONS_BLOCK_FINDING_KEYS = (
    "relations",
    "progressions",
    "equal_pairs",
    "row_pairs",
    "within_col",
    "identical_after_rounding",
    "grim",
)


@dataclass(frozen=True)
class TranslationLedgerEntry:
    """Records a single translation decision (success or skip)."""

    raw_payload_ref: str
    raw_kind: str
    action: str  # "translated" | "skipped"
    reason: str = ""
    signal_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "raw_payload_ref": self.raw_payload_ref,
            "raw_kind": self.raw_kind,
            "action": self.action,
        }
        if self.reason:
            result["reason"] = self.reason
        if self.signal_id:
            result["signal_id"] = self.signal_id
        return result


@dataclass
class TranslationResult:
    """Output of the PaperConan translator.

    Contains:
    - signals: NumericSignalSet with all translated signals
    - ledger: list of all translation decisions (successes and skips)
    - scan_errors: list of scan error entries from the original scan
    """

    signals: NumericSignalSet = field(default_factory=NumericSignalSet)
    ledger: list[TranslationLedgerEntry] = field(default_factory=list)
    scan_errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "total_signals": len(self.signals),
            "total_ledger_entries": len(self.ledger),
            "translated_count": sum(1 for e in self.ledger if e.action == "translated"),
            "skipped_count": sum(1 for e in self.ledger if e.action == "skipped"),
            "scan_errors": self.scan_errors,
            "ledger": [e.to_dict() for e in self.ledger],
            "signals": self.signals.to_dict(),
        }

    def write_artifacts(self, output_dir: Path) -> tuple[Path, Path]:
        """Write signals and ledger JSON artifacts to output_dir.

        Returns:
            Tuple of (signals_path, ledger_path)
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        signals_path = output_dir / "paperconan_signals.json"
        ledger_path = output_dir / "paperconan_translation_ledger.json"

        signals_path.write_bytes(self.signals.to_json_bytes())
        ledger_dict = {
            "schema_version": "1.0",
            "total_entries": len(self.ledger),
            "translated_count": sum(1 for e in self.ledger if e.action == "translated"),
            "skipped_count": sum(1 for e in self.ledger if e.action == "skipped"),
            "entries": [e.to_dict() for e in self.ledger],
        }
        ledger_path.write_text(
            json.dumps(ledger_dict, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return signals_path, ledger_path


def translate_paperconan_scan(
    scan_result: dict[str, Any],
    *,
    profile: str = "review",
) -> TranslationResult:
    """Translate a PaperConan compact scan result into Veritas canonical NumericSignals.

    Args:
        scan_result: The compact scan result dict (as produced by the existing
            paperconan adapter, i.e., the "scan_result" key in paperconan_scan.json).
        profile: The profile used during scanning ("review", "forensic", "triage").

    Returns:
        TranslationResult with signals, ledger, and scan_errors.
    """
    result = TranslationResult()
    counter = 0

    tool_version = scan_result.get("tool_version", "unknown")

    # --- Translate relations_blocks ---
    for block_idx, block in enumerate(scan_result.get("relations_blocks", [])):
        block_file = block.get("file", "")
        block_sheet = block.get("sheet", "")
        block_rows = ""
        block_cols = ""
        block_info = block.get("block", {})
        if isinstance(block_info, dict):
            block_rows = str(block_info.get("rows", ""))
            block_cols = str(block_info.get("cols", ""))

        for finding_key in _RELATIONS_BLOCK_FINDING_KEYS:
            findings_list = block.get(finding_key, [])
            for finding_idx, finding in enumerate(findings_list):
                counter += 1
                raw_ref = f"relations_blocks/{block_idx}/{finding_key}/{finding_idx}"
                kind = finding.get("kind", "")

                if not kind:
                    result.ledger.append(TranslationLedgerEntry(
                        raw_payload_ref=raw_ref,
                        raw_kind="",
                        action="skipped",
                        reason="empty kind field",
                    ))
                    continue

                signal = _translate_block_finding(
                    finding=finding,
                    kind=kind,
                    raw_ref=raw_ref,
                    block_file=block_file,
                    block_sheet=block_sheet,
                    block_rows=block_rows,
                    block_cols=block_cols,
                    profile=profile,
                    tool_version=tool_version,
                    counter=counter,
                )

                errors = validate_numeric_signal(signal)
                if errors:
                    result.ledger.append(TranslationLedgerEntry(
                        raw_payload_ref=raw_ref,
                        raw_kind=kind,
                        action="skipped",
                        reason=f"validation failed: {'; '.join(errors)}",
                    ))
                else:
                    result.signals.add(signal)
                    result.ledger.append(TranslationLedgerEntry(
                        raw_payload_ref=raw_ref,
                        raw_kind=kind,
                        action="translated",
                        signal_id=signal.signal_id,
                    ))

    # --- Translate cross_sheet_findings ---
    for cs_idx, cs_finding in enumerate(scan_result.get("cross_sheet_findings", [])):
        counter += 1
        raw_ref = f"cross_sheet_findings/{cs_idx}"
        kind = cs_finding.get("kind", "")

        if not kind:
            result.ledger.append(TranslationLedgerEntry(
                raw_payload_ref=raw_ref,
                raw_kind="",
                action="skipped",
                reason="empty kind field",
            ))
            continue

        signal = _translate_cross_sheet_finding(
            finding=cs_finding,
            kind=kind,
            raw_ref=raw_ref,
            profile=profile,
            tool_version=tool_version,
            counter=counter,
        )

        errors = validate_numeric_signal(signal)
        if errors:
            result.ledger.append(TranslationLedgerEntry(
                raw_payload_ref=raw_ref,
                raw_kind=kind,
                action="skipped",
                reason=f"validation failed: {'; '.join(errors)}",
            ))
        else:
            result.signals.add(signal)
            result.ledger.append(TranslationLedgerEntry(
                raw_payload_ref=raw_ref,
                raw_kind=kind,
                action="translated",
                signal_id=signal.signal_id,
            ))

    # --- Translate digit_distribution ---
    for dd_idx, dd_entry in enumerate(scan_result.get("digit_distribution", [])):
        counter += 1
        raw_ref = f"digit_distribution/{dd_idx}"
        kind = "last_digit_chi_square"
        p_val = dd_entry.get("p", 1.0)
        p_adj = dd_entry.get("p_adj")
        fdr_sig = dd_entry.get("fdr_significant", False)

        # Only translate if the test is at least marginally significant
        # or if profile is forensic (keep everything)
        if profile == "forensic" or p_val < 0.05 or fdr_sig:
            confidence = max(0.0, min(1.0, 1.0 - p_val))
            risk = _p_to_risk(p_adj if p_adj is not None else p_val)

            signal = NumericSignal(
                signal_id=generate_signal_id(counter),
                source_tool="paperconan",
                detector_id=f"paperconan.{kind}",
                detector_family="digit_statistics",
                raw_kind=kind,
                canonical_category=kind,
                rule=dd_entry.get("label", f"last-digit chi-square on sheet {dd_entry.get('label', '?')}"),
                n=dd_entry.get("n"),
                mechanical_confidence=round(confidence, 4),
                risk_level_raw=risk,
                profile=profile,
                profile_action="kept",
                prefilter_action="keep",
                applicability_premise=_KIND_TO_PREMISE.get(kind),
                raw_payload_ref=raw_ref,
                extra={
                    "chi2": dd_entry.get("chi2"),
                    "p": p_val,
                    "p_adj": p_adj,
                    "fdr_significant": fdr_sig,
                    "counts": dd_entry.get("counts"),
                    "top": dd_entry.get("top"),
                },
            )
            result.signals.add(signal)
            result.ledger.append(TranslationLedgerEntry(
                raw_payload_ref=raw_ref,
                raw_kind=kind,
                action="translated",
                signal_id=signal.signal_id,
            ))
        else:
            result.ledger.append(TranslationLedgerEntry(
                raw_payload_ref=raw_ref,
                raw_kind=kind,
                action="skipped",
                reason=f"p={p_val:.4f} not significant at 0.05 threshold (profile={profile})",
            ))

    # --- Translate decimal_endings ---
    for de_idx, de_entry in enumerate(scan_result.get("decimal_endings", [])):
        counter += 1
        raw_ref = f"decimal_endings/{de_idx}"
        kind = "repeated_two_decimal_endings"
        top = de_entry.get("top", [])

        # Only translate if there are significant repetitions
        if top or profile == "forensic":
            n = de_entry.get("n", 0)
            if top:
                # Use the top repetition's fraction as a rough confidence proxy
                top_count = top[0][1] if top and len(top[0]) > 1 else 0
                confidence = min(1.0, top_count / max(n, 1)) if n > 0 else 0.0
            else:
                confidence = 0.0

            risk = "high" if confidence > 0.7 else "medium" if confidence > 0.4 else "low"

            signal = NumericSignal(
                signal_id=generate_signal_id(counter),
                source_tool="paperconan",
                detector_id=f"paperconan.{kind}",
                detector_family="digit_statistics",
                raw_kind=kind,
                canonical_category=kind,
                rule=f"repeated 2-decimal endings in {de_entry.get('label', '?')}",
                n=n,
                mechanical_confidence=round(confidence, 4),
                risk_level_raw=risk,
                profile=profile,
                profile_action="kept",
                prefilter_action="keep",
                applicability_premise=_KIND_TO_PREMISE.get(kind),
                raw_payload_ref=raw_ref,
                extra={
                    "n_unique": de_entry.get("n_unique"),
                    "top": top,
                },
            )
            result.signals.add(signal)
            result.ledger.append(TranslationLedgerEntry(
                raw_payload_ref=raw_ref,
                raw_kind=kind,
                action="translated",
                signal_id=signal.signal_id,
            ))
        else:
            result.ledger.append(TranslationLedgerEntry(
                raw_payload_ref=raw_ref,
                raw_kind=kind,
                action="skipped",
                reason="no significant decimal ending repetitions found",
            ))

    # --- Record scan_errors ---
    for err in scan_result.get("scan_errors", []):
        result.scan_errors.append(err)
        counter += 1
        raw_ref = f"scan_errors/{len(result.scan_errors) - 1}"
        kind = "scan_error"
        signal = NumericSignal(
            signal_id=generate_signal_id(counter),
            source_tool="paperconan",
            detector_id="paperconan.scan_error",
            detector_family="scan_errors",
            raw_kind=kind,
            canonical_category=kind,
            rule=f"scan error: {err.get('error', 'unknown')}",
            profile=profile,
            profile_action="kept",
            prefilter_action="keep",
            raw_payload_ref=raw_ref,
            extra={
                "file": err.get("file", ""),
                "sheet": err.get("sheet", ""),
                "error": err.get("error", ""),
            },
        )
        result.signals.add(signal)
        result.ledger.append(TranslationLedgerEntry(
            raw_payload_ref=raw_ref,
            raw_kind=kind,
            action="translated",
            signal_id=signal.signal_id,
        ))

    return result


def _translate_block_finding(
    *,
    finding: dict[str, Any],
    kind: str,
    raw_ref: str,
    block_file: str,
    block_sheet: str,
    block_rows: str,
    block_cols: str,
    profile: str,
    tool_version: str,
    counter: int,
) -> NumericSignal:
    """Translate a single finding from a relations_block into a NumericSignal."""
    family = _KIND_TO_FAMILY.get(kind, "unknown")
    severity = _normalize_severity(finding.get("severity", "low"))
    profile_action = _normalize_profile_action(finding.get("profile_action", "kept"))
    prefilter_reason = finding.get("prefilter_reason", "")
    fp_context = finding.get("false_positive_context", [])
    if not isinstance(fp_context, list):
        fp_context = [str(fp_context)] if fp_context else []

    # Determine prefilter_action from profile_action
    if profile_action == "hidden":
        prefilter_action = "drop"
    elif profile_action == "demoted":
        prefilter_action = "downweight"
    else:
        prefilter_action = "keep"

    # Build evidence locator
    evidence_locator = EvidenceLocator(
        source_path=block_file,
        sheet=block_sheet,
        rows=block_rows,
        cols=block_cols,
        highlight_rows=_extract_highlight_rows(finding),
        highlight_cols=_extract_highlight_cols(finding),
    )

    # Build extra metadata from finding-specific fields
    extra = _extract_extra_fields(finding, kind)

    return NumericSignal(
        signal_id=generate_signal_id(counter),
        source_tool="paperconan",
        detector_id=f"paperconan.{kind}",
        detector_family=family,
        raw_kind=kind,
        canonical_category=kind,
        rule=finding.get("rule", ""),
        n=_safe_int(finding.get("n") or finding.get("n_cells")),
        effect_size=_safe_float(finding.get("fraction_of_smaller")),
        mechanical_confidence=_safe_float(finding.get("evidence_confidence")),
        risk_level_raw=severity,
        profile=profile,
        profile_action=profile_action,
        prefilter_action=prefilter_action,
        false_positive_context=fp_context,
        prefilter_reason=prefilter_reason,
        applicability_premise=_KIND_TO_PREMISE.get(kind),
        evidence_locator=evidence_locator,
        raw_payload_ref=raw_ref,
        extra=extra,
    )


def _translate_cross_sheet_finding(
    *,
    finding: dict[str, Any],
    kind: str,
    raw_ref: str,
    profile: str,
    tool_version: str,
    counter: int,
) -> NumericSignal:
    """Translate a cross-sheet finding into a NumericSignal."""
    family = _KIND_TO_FAMILY.get(kind, "cross_sheet")
    severity = _normalize_severity(finding.get("severity", "low"))
    profile_action = _normalize_profile_action(finding.get("profile_action", "kept"))
    prefilter_reason = finding.get("prefilter_reason", "")
    fp_context = finding.get("false_positive_context", [])
    if not isinstance(fp_context, list):
        fp_context = [str(fp_context)] if fp_context else []

    if profile_action == "hidden":
        prefilter_action = "drop"
    elif profile_action == "demoted":
        prefilter_action = "downweight"
    else:
        prefilter_action = "keep"

    # Cross-sheet findings reference file-level evidence
    source_file = finding.get("file", "")
    sheet_a = finding.get("sheet_a", "")
    sheet_b = finding.get("sheet_b", "")
    sheet_ref = f"{sheet_a} vs {sheet_b}" if sheet_a and sheet_b else sheet_a or sheet_b

    evidence_locator = EvidenceLocator(
        source_path=source_file,
        sheet=sheet_ref,
    )

    extra = _extract_extra_fields(finding, kind)

    return NumericSignal(
        signal_id=generate_signal_id(counter),
        source_tool="paperconan",
        detector_id=f"paperconan.{kind}",
        detector_family=family,
        raw_kind=kind,
        canonical_category=kind,
        rule=finding.get("rule", ""),
        n=_safe_int(finding.get("n") or finding.get("n_cells")),
        effect_size=_safe_float(finding.get("fraction_of_smaller")),
        mechanical_confidence=_safe_float(finding.get("evidence_confidence")),
        risk_level_raw=severity,
        profile=profile,
        profile_action=profile_action,
        prefilter_action=prefilter_action,
        false_positive_context=fp_context,
        prefilter_reason=prefilter_reason,
        applicability_premise=_KIND_TO_PREMISE.get(kind),
        evidence_locator=evidence_locator,
        raw_payload_ref=raw_ref,
        extra=extra,
    )


def _normalize_severity(severity: str) -> str:
    """Normalize severity to valid risk level."""
    s = str(severity).lower().strip()
    if s in ("critical", "high", "medium", "low", "info"):
        return s
    # paperconan uses "high"/"medium"/"low"; map unknown to "low"
    return "low"


def _normalize_profile_action(action: str) -> str:
    """Normalize profile_action to valid value."""
    a = str(action).lower().strip()
    if a in ("kept", "demoted", "hidden"):
        return a
    return "kept"


def _safe_int(value: Any) -> int | None:
    """Safely convert a value to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_highlight_rows(finding: dict[str, Any]) -> list[int]:
    """Extract highlight row indices from a finding if present."""
    # paperconan findings may include row information in various formats
    rows = finding.get("highlight_rows", [])
    if isinstance(rows, list):
        return [int(r) for r in rows if isinstance(r, (int, float))]
    return []


def _extract_highlight_cols(finding: dict[str, Any]) -> list[str]:
    """Extract highlight column labels from a finding if present."""
    cols = finding.get("highlight_cols", [])
    if isinstance(cols, list):
        return [str(c) for c in cols]
    # Also extract col_a/col_b for relation findings
    result = []
    for key in ("col_a", "col_b", "col"):
        val = finding.get(key)
        if val is not None:
            result.append(str(val))
    return result


def _extract_extra_fields(finding: dict[str, Any], kind: str) -> dict[str, Any]:
    """Extract detector-specific extra fields from a finding.

    Keeps fields that are useful for diagnostics and report display but
    not part of the canonical signal schema.
    """
    # Fields that are part of the canonical schema or are internal metadata
    _canonical_keys = {
        "kind", "severity", "rule", "n", "n_cells", "evidence_confidence",
        "fraction_of_smaller", "profile_action", "false_positive_context",
        "prefilter_reason", "prefilter", "likely_benign", "flags",
        "highlight_rows", "highlight_cols", "col_a", "col_b", "col",
        "col_a_idx", "col_b_idx", "col_idx", "block_c0",
    }

    extra: dict[str, Any] = {}
    for key, value in finding.items():
        if key not in _canonical_keys and key not in ("kind",):
            # Keep only JSON-safe values
            if isinstance(value, (str, int, float, bool, type(None))):
                extra[key] = value
            elif isinstance(value, list) and len(value) <= 20:
                # Keep small lists (e.g., sample values, examples)
                if all(isinstance(v, (str, int, float, bool, type(None))) for v in value):
                    extra[key] = value

    return extra


def _p_to_risk(p_value: float) -> str:
    """Convert a p-value to a risk level for digit statistics."""
    if p_value < 0.001:
        return "high"
    if p_value < 0.01:
        return "medium"
    return "low"
