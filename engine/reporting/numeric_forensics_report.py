"""Numeric Forensics Summary Report (WP10).

Generates the "Numeric Forensics Summary" section data for the audit report.
This module consumes canonical ``NumericSignal`` instances (not raw PaperConan
output) and produces a structured summary suitable for report rendering.

Design constraints:
- Only reads from the canonical signal schema.
- Does NOT modify existing report structures.
- Produces a plain-data dict that the HTML/JSON/MD renderers can consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.static_audit.numeric_signal_schema import NumericSignal


@dataclass(frozen=True)
class NumericForensicsSummary:
    """Structured summary of all numeric forensics signals.

    Attributes:
        total_signals: Total number of canonical signals.
        by_detector_family: Signal counts grouped by detector_family.
        by_risk_level: Signal counts grouped by risk_level_raw.
        by_profile_action: Signal counts grouped by profile_action
            (kept/demoted/hidden).
        by_impact_scope: Signal counts grouped by impact_scope.
        high_priority_signals: Signals with risk_level_raw in (high, critical)
            and profile_action == "kept".
        hidden_signal_count: Number of signals with profile_action == "hidden".
        demoted_signal_count: Number of signals with profile_action == "demoted".
        signals_with_claim_mapping: Count of signals with non-empty claim_refs.
        signals_needing_author_data: Count of signals with non-empty
            needs_author_data.
    """

    total_signals: int = 0
    by_detector_family: dict[str, int] = field(default_factory=dict)
    by_risk_level: dict[str, int] = field(default_factory=dict)
    by_profile_action: dict[str, int] = field(default_factory=dict)
    by_impact_scope: dict[str, int] = field(default_factory=dict)
    high_priority_signals: list[dict[str, Any]] = field(default_factory=list)
    hidden_signal_count: int = 0
    demoted_signal_count: int = 0
    signals_with_claim_mapping: int = 0
    signals_needing_author_data: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_signals": self.total_signals,
            "by_detector_family": dict(self.by_detector_family),
            "by_risk_level": dict(self.by_risk_level),
            "by_profile_action": dict(self.by_profile_action),
            "by_impact_scope": dict(self.by_impact_scope),
            "high_priority_signals": list(self.high_priority_signals),
            "hidden_signal_count": self.hidden_signal_count,
            "demoted_signal_count": self.demoted_signal_count,
            "signals_with_claim_mapping": self.signals_with_claim_mapping,
            "signals_needing_author_data": self.signals_needing_author_data,
        }


def build_numeric_forensics_summary(
    signals: list[NumericSignal],
) -> NumericForensicsSummary:
    """Build a NumericForensicsSummary from canonical signals.

    This is the main entry point for report consumers.

    Args:
        signals: All canonical NumericSignal instances for this run.

    Returns:
        A NumericForensicsSummary ready for report rendering.
    """
    if not signals:
        return NumericForensicsSummary()

    by_family: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    by_action: dict[str, int] = {}
    by_impact: dict[str, int] = {}
    high_priority: list[dict[str, Any]] = []
    hidden = 0
    demoted = 0
    with_claim = 0
    needs_author = 0

    for sig in signals:
        # Detector family counts
        fam = sig.detector_family or "unclassified"
        by_family[fam] = by_family.get(fam, 0) + 1

        # Risk level counts
        risk = sig.risk_level_raw or "info"
        by_risk[risk] = by_risk.get(risk, 0) + 1

        # Profile action counts
        action = sig.profile_action
        by_action[action] = by_action.get(action, 0) + 1
        if action == "hidden":
            hidden += 1
        elif action == "demoted":
            demoted += 1

        # Impact scope counts
        impact = sig.impact_scope
        by_impact[impact] = by_impact.get(impact, 0) + 1

        # High priority: high/critical risk + kept
        if risk in ("high", "critical") and action == "kept":
            high_priority.append({
                "signal_id": sig.signal_id,
                "detector_id": sig.detector_id,
                "canonical_category": sig.canonical_category,
                "risk_level_raw": risk,
                "impact_scope": sig.impact_scope,
                "rule": sig.rule,
                "claim_refs": sig.claim_refs,
                "needs_author_data": sig.needs_author_data,
            })

        # Claim mapping count
        if sig.claim_refs:
            with_claim += 1

        # Needs author data count
        if sig.needs_author_data:
            needs_author += 1

    # Sort high priority by risk (critical first)
    risk_order = {"critical": 0, "high": 1}
    high_priority.sort(key=lambda x: risk_order.get(x["risk_level_raw"], 99))

    return NumericForensicsSummary(
        total_signals=len(signals),
        by_detector_family=by_family,
        by_risk_level=by_risk,
        by_profile_action=by_action,
        by_impact_scope=by_impact,
        high_priority_signals=high_priority,
        hidden_signal_count=hidden,
        demoted_signal_count=demoted,
        signals_with_claim_mapping=with_claim,
        signals_needing_author_data=needs_author,
    )
