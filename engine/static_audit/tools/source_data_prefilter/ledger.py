"""Ledger dataclass for the deterministic profile / prefilter ledger.

The ledger records every signal's routing decision without deleting anything.
Hidden signals remain in the ledger and diagnostics; they only disappear from
the default report view.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .profiles import ProfileName


@dataclass
class PrefilterLedgerEntry:
    """One row of the numeric prefilter ledger."""

    signal_id: str
    profile: ProfileName
    detector_original_action: str
    prefilter_action: str  # keep | downweight | drop
    profile_action: str  # kept | demoted | hidden
    false_positive_context: list[str] = field(default_factory=list)
    prefilter_reason: str = ""
    risk_before: str = "medium"
    risk_after: str = "medium"
    visible_in_report: bool = True
    sent_to_llm: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NumericPrefilterLedger:
    """Container for all ledger entries produced by a single prefilter run."""

    profile: ProfileName
    entries: list[PrefilterLedgerEntry] = field(default_factory=list)

    # -- Query helpers --------------------------------------------------

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def visible_count(self) -> int:
        return sum(1 for e in self.entries if e.visible_in_report)

    @property
    def hidden_count(self) -> int:
        return self.total - self.visible_count

    @property
    def demoted_count(self) -> int:
        return sum(1 for e in self.entries if e.profile_action == "demoted")

    def visible_entries(self) -> list[PrefilterLedgerEntry]:
        return [e for e in self.entries if e.visible_in_report]

    def hidden_entries(self) -> list[PrefilterLedgerEntry]:
        return [e for e in self.entries if not e.visible_in_report]

    def diagnostics_summary(self) -> dict[str, Any]:
        """Return a diagnostics-safe summary of the ledger.

        Hidden signals are always represented here so that diagnostics
        consumers can account for every signal.
        """
        return {
            "profile": self.profile,
            "total_signals": self.total,
            "visible_in_report": self.visible_count,
            "hidden_from_report": self.hidden_count,
            "demoted": self.demoted_count,
            "sent_to_llm": sum(1 for e in self.entries if e.sent_to_llm),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "profile": self.profile,
            "summary": self.diagnostics_summary(),
            "entries": [e.to_dict() for e in self.entries],
        }
