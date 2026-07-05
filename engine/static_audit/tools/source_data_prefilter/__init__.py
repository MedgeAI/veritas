"""Deterministic Profile / Prefilter Ledger for numeric signals.

This package implements the WP3 contract from the PaperConan integration PRD.
It provides three profiles (forensic / review / triage) that control signal
visibility, priority and LLM routing without ever deleting signals.

Public API
----------
- :func:`run_prefilter` -- main entry point.
- :class:`NumericPrefilterLedger` -- container for ledger entries.
- :class:`PrefilterLedgerEntry` -- one row of the ledger.
- :func:`get_profile` -- look up a profile definition by name.
"""

from __future__ import annotations

from .ledger import NumericPrefilterLedger, PrefilterLedgerEntry
from .prefilter import run_prefilter
from .profiles import ProfileName, get_profile

__all__ = [
    "NumericPrefilterLedger",
    "PrefilterLedgerEntry",
    "ProfileName",
    "get_profile",
    "run_prefilter",
]
