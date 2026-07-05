"""Profile / Prefilter Ledger Summary Report (WP10).

Reports on the deterministic profile/prefilter decisions applied to
numeric signals.  This lets users see which signals were kept, demoted,
or hidden, and why.

The ledger is the product contract for ``profile`` behavior — every
signal must appear in the ledger exactly once, regardless of whether
it is visible in the report.

This module does NOT read raw PaperConan output.  It consumes the
prefilter ledger artifact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PrefilterLedgerEntry:
    """A single entry in the prefilter ledger.

    Attributes:
        signal_id: The signal this entry describes.
        profile: The profile under which this decision was made.
        prefilter_action: keep / downweight / drop.
        profile_action: kept / demoted / hidden.
        false_positive_context: list of FP context tags.
        prefilter_reason: Human-readable reason for the action.
        risk_before: Risk level before prefilter.
        risk_after: Risk level after prefilter.
        visible_in_report: Whether this signal is visible in the report.
        sent_to_llm: Whether this signal was sent to LLM for review.
    """

    signal_id: str
    profile: str = "review"
    prefilter_action: str = "keep"
    profile_action: str = "kept"
    false_positive_context: list[str] = field(default_factory=list)
    prefilter_reason: str = ""
    risk_before: str = "info"
    risk_after: str = "info"
    visible_in_report: bool = True
    sent_to_llm: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "profile": self.profile,
            "prefilter_action": self.prefilter_action,
            "profile_action": self.profile_action,
            "false_positive_context": list(self.false_positive_context),
            "prefilter_reason": self.prefilter_reason,
            "risk_before": self.risk_before,
            "risk_after": self.risk_after,
            "visible_in_report": self.visible_in_report,
            "sent_to_llm": self.sent_to_llm,
        }


@dataclass(frozen=True)
class PrefilterLedgerReport:
    """Summary of the prefilter ledger.

    Attributes:
        total_entries: Total number of signals in the ledger.
        profile: The profile under which the ledger was generated.
        kept_count: Signals with profile_action == "kept".
        demoted_count: Signals with profile_action == "demoted".
        hidden_count: Signals with profile_action == "hidden".
        drop_count: Signals with prefilter_action == "drop".
        downweight_count: Signals with prefilter_action == "downweight".
        visible_in_report: Signals visible in the report.
        sent_to_llm: Signals sent to LLM for review.
        entries: All ledger entries.
    """

    total_entries: int = 0
    profile: str = "review"
    kept_count: int = 0
    demoted_count: int = 0
    hidden_count: int = 0
    drop_count: int = 0
    downweight_count: int = 0
    visible_in_report: int = 0
    sent_to_llm: int = 0
    entries: list[PrefilterLedgerEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_entries": self.total_entries,
            "profile": self.profile,
            "kept_count": self.kept_count,
            "demoted_count": self.demoted_count,
            "hidden_count": self.hidden_count,
            "drop_count": self.drop_count,
            "downweight_count": self.downweight_count,
            "visible_in_report": self.visible_in_report,
            "sent_to_llm": self.sent_to_llm,
            "entries": [e.to_dict() for e in self.entries],
        }


def build_prefilter_ledger_report(
    ledger_entries: list[dict[str, Any]] | None = None,
) -> PrefilterLedgerReport:
    """Build a PrefilterLedgerReport from raw ledger entry dicts.

    Args:
        ledger_entries: List of prefilter ledger entry dicts, each with
            at least ``signal_id``.

    Returns:
        A PrefilterLedgerReport summarizing the ledger.
    """
    raw = ledger_entries or []
    if not raw:
        return PrefilterLedgerReport()

    entries: list[PrefilterLedgerEntry] = []
    kept = demoted = hidden = drop = downweight = visible = to_llm = 0
    profile = "review"

    for data in raw:
        entry = PrefilterLedgerEntry(
            signal_id=str(data.get("signal_id", "")),
            profile=str(data.get("profile", "review")),
            prefilter_action=str(data.get("prefilter_action", "keep")),
            profile_action=str(data.get("profile_action", "kept")),
            false_positive_context=list(data.get("false_positive_context", [])),
            prefilter_reason=str(data.get("prefilter_reason", "")),
            risk_before=str(data.get("risk_before", "info")),
            risk_after=str(data.get("risk_after", "info")),
            visible_in_report=bool(data.get("visible_in_report", True)),
            sent_to_llm=bool(data.get("sent_to_llm", True)),
        )
        entries.append(entry)
        profile = entry.profile

        if entry.profile_action == "kept":
            kept += 1
        elif entry.profile_action == "demoted":
            demoted += 1
        elif entry.profile_action == "hidden":
            hidden += 1

        if entry.prefilter_action == "drop":
            drop += 1
        elif entry.prefilter_action == "downweight":
            downweight += 1

        if entry.visible_in_report:
            visible += 1
        if entry.sent_to_llm:
            to_llm += 1

    return PrefilterLedgerReport(
        total_entries=len(entries),
        profile=profile,
        kept_count=kept,
        demoted_count=demoted,
        hidden_count=hidden,
        drop_count=drop,
        downweight_count=downweight,
        visible_in_report=visible,
        sent_to_llm=to_llm,
        entries=entries,
    )
