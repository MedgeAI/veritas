"""Core deterministic prefilter logic.

The prefilter receives a list of numeric signals (already translated into the
canonical form) and produces a :class:`NumericPrefilterLedger` that records
every routing decision.  Signals are never deleted -- they are only marked as
kept, demoted or hidden based on the active profile.
"""

from __future__ import annotations

from typing import Any

from .ledger import NumericPrefilterLedger, PrefilterLedgerEntry
from .profiles import (
    BENIGN_CONTEXTS,
    ProfileDefinition,
    ProfileName,
    demote_risk,
    get_profile,
)


def _signal_false_positive_contexts(signal: dict[str, Any]) -> list[str]:
    """Extract the false-positive context list from a raw signal dict.

    Only string entries are accepted; non-string items (e.g. dicts from
    malformed upstream data) are silently ignored to avoid unhashable-type
    errors when checking membership in the BENIGN_CONTEXTS frozenset.
    """
    ctx = signal.get("false_positive_context", [])
    if isinstance(ctx, str):
        ctx = [ctx]
    if not isinstance(ctx, list):
        return []
    return [c for c in ctx if isinstance(c, str) and c in BENIGN_CONTEXTS]


def _determine_prefilter_action(
    signal: dict[str, Any],
    profile: ProfileDefinition,
) -> tuple[str, str]:
    """Return ``(prefilter_action, prefilter_reason)`` for *signal*.

    The prefilter action is derived from the signal's own ``prefilter_action``
    field (if present) or inferred from false-positive context overlap with
    the profile's benign contexts.
    """
    raw_action = signal.get("prefilter_action", "keep")
    fp_contexts = _signal_false_positive_contexts(signal)

    if raw_action in ("keep", "downweight", "drop"):
        return raw_action, signal.get("prefilter_reason", "")

    # Fallback: infer from FP context overlap.
    if fp_contexts and profile.benign_contexts:
        overlap = sorted(set(fp_contexts) & profile.benign_contexts)
        if overlap:
            return "downweight", f"benign_context_overlap:{','.join(overlap)}"

    return "keep", ""


def _apply_profile(
    signal: dict[str, Any],
    profile: ProfileDefinition,
) -> PrefilterLedgerEntry:
    """Apply *profile* to a single *signal* and return the ledger entry."""
    prefilter_action, prefilter_reason = _determine_prefilter_action(signal, profile)
    profile_action = profile.resolve_profile_action(prefilter_action)

    risk_before = signal.get("risk_level_raw", signal.get("risk_before", "medium"))
    risk_after = risk_before
    if profile_action == "demoted":
        risk_after = demote_risk(risk_before, profile.demotion_steps)
    elif profile_action == "hidden":
        risk_after = demote_risk(risk_before, profile.demotion_steps)

    # Visibility and LLM routing are determined by the *profile_action*:
    #   - "kept"   -> always visible and sent to LLM
    #   - "demoted" -> visible in forensic/review, hidden in triage
    #   - "hidden"  -> never visible, never sent to LLM
    if profile_action == "kept":
        visible = True
        sent = True
    elif profile_action == "demoted":
        visible = profile.visible_in_report
        sent = profile.sent_to_llm
    else:  # hidden
        visible = False
        sent = False

    return PrefilterLedgerEntry(
        signal_id=signal.get("signal_id", ""),
        profile=profile.name,
        detector_original_action=signal.get(
            "detector_original_action", raw_detector_action(signal)
        ),
        prefilter_action=prefilter_action,
        profile_action=profile_action,
        false_positive_context=_signal_false_positive_contexts(signal),
        prefilter_reason=prefilter_reason,
        risk_before=risk_before,
        risk_after=risk_after,
        visible_in_report=visible,
        sent_to_llm=sent,
    )


def raw_detector_action(signal: dict[str, Any]) -> str:
    """Best-effort extraction of the detector's original action string."""
    return signal.get("detector_action", signal.get("raw_kind", "unknown"))


def run_prefilter(
    signals: list[dict[str, Any]],
    profile: ProfileName | str = "review",
) -> NumericPrefilterLedger:
    """Run the deterministic prefilter over *signals* under *profile*.

    Parameters
    ----------
    signals:
        List of canonical numeric signal dicts.  Each dict must carry at
        minimum a ``signal_id``; optional fields include ``risk_level_raw``,
        ``prefilter_action``, ``prefilter_reason``, ``false_positive_context``,
        ``detector_original_action``.
    profile:
        One of ``"forensic"``, ``"review"``, ``"triage"``.

    Returns
    -------
    NumericPrefilterLedger
        Ledger with one entry per input signal.  The ledger never drops
        signals -- it only records visibility / priority changes.
    """
    profile_def = get_profile(profile)
    entries = [_apply_profile(sig, profile_def) for sig in signals]
    return NumericPrefilterLedger(profile=profile_def.name, entries=entries)
