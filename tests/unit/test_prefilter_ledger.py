"""Tests for the deterministic profile / prefilter ledger (WP3).

Validates the three core invariants from the PRD:

1. ``forensic`` visible >= ``review`` visible >= ``triage`` visible.
2. Ledger total count is preserved across all profiles (no signal deletion).
3. Hidden / demoted signals always carry ``prefilter_reason``.
"""

from __future__ import annotations

import pytest

from engine.static_audit.tools.source_data_prefilter import (
    NumericPrefilterLedger,
    PrefilterLedgerEntry,
    get_profile,
    run_prefilter,
)
from engine.static_audit.tools.source_data_prefilter.profiles import (
    ProfileName,
    demote_risk,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_signal(
    signal_id: str,
    *,
    risk: str = "high",
    prefilter_action: str = "keep",
    fp_context: list[str] | None = None,
    reason: str = "",
    detector_action: str = "grim_inconsistent",
) -> dict:
    return {
        "signal_id": signal_id,
        "risk_level_raw": risk,
        "prefilter_action": prefilter_action,
        "prefilter_reason": reason,
        "false_positive_context": fp_context or [],
        "detector_original_action": detector_action,
    }


@pytest.fixture()
def mixed_signals() -> list[dict]:
    """A mix of clean signals, downweight candidates, and drop candidates."""
    return [
        _make_signal("SIG-001", risk="critical"),
        _make_signal(
            "SIG-002",
            risk="high",
            prefilter_action="downweight",
            fp_context=["derived_or_unit_conversion"],
            reason="deterministic relation prefilter matched unit_conversion_or_normalization",
        ),
        _make_signal(
            "SIG-003",
            risk="medium",
            prefilter_action="drop",
            fp_context=["formula_column"],
            reason="column is a formula derivation",
        ),
        _make_signal("SIG-004", risk="low"),
        _make_signal(
            "SIG-005",
            risk="high",
            prefilter_action="downweight",
            fp_context=["statistical_summary"],
            reason="summary statistic, not raw measurement",
        ),
    ]


# ---------------------------------------------------------------------------
# Profile definitions
# ---------------------------------------------------------------------------


class TestProfileDefinitions:
    """Verify the three profile contracts."""

    def test_all_three_profiles_registered(self) -> None:
        for name in ("forensic", "review", "triage"):
            profile = get_profile(name)
            assert profile.name == name

    def test_unknown_profile_raises(self) -> None:
        with pytest.raises(KeyError, match="Unknown profile"):
            get_profile("nonexistent")

    def test_forensic_keeps_everything(self) -> None:
        profile = get_profile("forensic")
        for action in ("keep", "downweight", "drop"):
            assert profile.resolve_profile_action(action) == "kept"

    def test_review_demotes_downweight_and_drop(self) -> None:
        profile = get_profile("review")
        assert profile.resolve_profile_action("keep") == "kept"
        assert profile.resolve_profile_action("downweight") == "demoted"
        assert profile.resolve_profile_action("drop") == "demoted"

    def test_triage_hides_downweight_and_drop(self) -> None:
        profile = get_profile("triage")
        assert profile.resolve_profile_action("keep") == "kept"
        assert profile.resolve_profile_action("downweight") == "hidden"
        assert profile.resolve_profile_action("drop") == "hidden"


# ---------------------------------------------------------------------------
# Risk demotion
# ---------------------------------------------------------------------------


class TestDemoteRisk:
    def test_zero_steps_no_change(self) -> None:
        assert demote_risk("high", 0) == "high"

    def test_one_step_demotes(self) -> None:
        assert demote_risk("high", 1) == "medium"
        assert demote_risk("critical", 1) == "high"

    def test_clamps_at_info(self) -> None:
        assert demote_risk("low", 5) == "info"

    def test_unknown_risk_treated_as_zero(self) -> None:
        assert demote_risk("unknown", 0) == "info"


# ---------------------------------------------------------------------------
# Prefilter run -- core invariants
# ---------------------------------------------------------------------------


class TestPrefilterCoreInvariants:
    """Test the three PRD invariants across all profiles."""

    def test_ledger_count_preserved_all_profiles(
        self, mixed_signals: list[dict]
    ) -> None:
        """Invariant: review and triage do not reduce ledger count."""
        for profile_name in ("forensic", "review", "triage"):
            ledger = run_prefilter(mixed_signals, profile_name)
            assert ledger.total == len(mixed_signals), (
                f"Profile {profile_name} changed ledger count"
            )

    def test_forensic_all_visible(self, mixed_signals: list[dict]) -> None:
        """Forensic profile: every signal is visible."""
        ledger = run_prefilter(mixed_signals, "forensic")
        assert ledger.visible_count == ledger.total
        assert ledger.hidden_count == 0

    def test_review_visible_leq_forensic(self, mixed_signals: list[dict]) -> None:
        """Invariant: forensic visible >= review visible."""
        forensic = run_prefilter(mixed_signals, "forensic")
        review = run_prefilter(mixed_signals, "review")
        assert forensic.visible_count >= review.visible_count

    def test_triage_visible_leq_review(self, mixed_signals: list[dict]) -> None:
        """Invariant: review visible >= triage visible."""
        review = run_prefilter(mixed_signals, "review")
        triage = run_prefilter(mixed_signals, "triage")
        assert review.visible_count >= triage.visible_count

    def test_visibility_chain_forensic_ge_review_ge_triage(
        self, mixed_signals: list[dict]
    ) -> None:
        """Invariant: forensic >= review >= triage in a single assertion."""
        forensic = run_prefilter(mixed_signals, "forensic")
        review = run_prefilter(mixed_signals, "review")
        triage = run_prefilter(mixed_signals, "triage")
        assert forensic.visible_count >= review.visible_count >= triage.visible_count

    def test_drop_never_deletes_signal(self, mixed_signals: list[dict]) -> None:
        """Drop must not remove signals; only visibility is affected."""
        drop_signals = [s for s in mixed_signals if s["prefilter_action"] == "drop"]
        assert len(drop_signals) > 0, "fixture must contain drop signals"
        for profile_name in ("forensic", "review", "triage"):
            ledger = run_prefilter(mixed_signals, profile_name)
            drop_ids = {s["signal_id"] for s in drop_signals}
            ledger_ids = {e.signal_id for e in ledger.entries}
            assert drop_ids.issubset(ledger_ids), (
                f"Profile {profile_name} lost drop signals"
            )

    def test_hidden_signals_have_reason(self, mixed_signals: list[dict]) -> None:
        """Every hidden/demoted signal must have a prefilter_reason."""
        for profile_name in ("review", "triage"):
            ledger = run_prefilter(mixed_signals, profile_name)
            for entry in ledger.hidden_entries():
                assert entry.profile_action in ("hidden", "demoted")
                # Reason or FP context must be non-empty for non-kept entries.
                has_context = bool(
                    entry.prefilter_reason or entry.false_positive_context
                )
                assert has_context, (
                    f"Signal {entry.signal_id} is {entry.profile_action} "
                    f"under {profile_name} but has no reason or FP context"
                )

    def test_hidden_signals_in_diagnostics(self, mixed_signals: list[dict]) -> None:
        """Hidden signals must appear in diagnostics summary."""
        triage = run_prefilter(mixed_signals, "triage")
        diag = triage.diagnostics_summary()
        assert diag["total_signals"] == len(mixed_signals)
        assert diag["hidden_from_report"] == triage.hidden_count
        assert diag["visible_in_report"] == triage.visible_count


# ---------------------------------------------------------------------------
# Profile-specific behaviour
# ---------------------------------------------------------------------------


class TestForensicProfile:
    def test_no_demotions(self, mixed_signals: list[dict]) -> None:
        ledger = run_prefilter(mixed_signals, "forensic")
        assert ledger.demoted_count == 0

    def test_all_kept_action(self, mixed_signals: list[dict]) -> None:
        ledger = run_prefilter(mixed_signals, "forensic")
        for entry in ledger.entries:
            assert entry.profile_action == "kept"

    def test_risk_unchanged(self, mixed_signals: list[dict]) -> None:
        ledger = run_prefilter(mixed_signals, "forensic")
        for entry in ledger.entries:
            assert entry.risk_after == entry.risk_before

    def test_all_sent_to_llm(self, mixed_signals: list[dict]) -> None:
        ledger = run_prefilter(mixed_signals, "forensic")
        for entry in ledger.entries:
            assert entry.sent_to_llm is True


class TestReviewProfile:
    def test_downweight_demoted(self) -> None:
        signals = [
            _make_signal(
                "SIG-DW",
                risk="high",
                prefilter_action="downweight",
                fp_context=["derived_or_unit_conversion"],
            )
        ]
        ledger = run_prefilter(signals, "review")
        entry = ledger.entries[0]
        assert entry.profile_action == "demoted"
        assert entry.risk_after == "medium"
        assert entry.visible_in_report is True

    def test_drop_demoted_not_hidden(self) -> None:
        signals = [
            _make_signal(
                "SIG-DR",
                risk="high",
                prefilter_action="drop",
                fp_context=["formula_column"],
            )
        ]
        ledger = run_prefilter(signals, "review")
        entry = ledger.entries[0]
        assert entry.profile_action == "demoted"
        assert entry.visible_in_report is True

    def test_clean_signal_kept(self) -> None:
        signals = [_make_signal("SIG-CLEAN", risk="high")]
        ledger = run_prefilter(signals, "review")
        entry = ledger.entries[0]
        assert entry.profile_action == "kept"
        assert entry.risk_after == entry.risk_before


class TestTriageProfile:
    def test_downweight_hidden(self) -> None:
        signals = [
            _make_signal(
                "SIG-DW",
                risk="high",
                prefilter_action="downweight",
                fp_context=["derived_or_unit_conversion"],
            )
        ]
        ledger = run_prefilter(signals, "triage")
        entry = ledger.entries[0]
        assert entry.profile_action == "hidden"
        assert entry.visible_in_report is False
        assert entry.sent_to_llm is False

    def test_drop_hidden(self) -> None:
        signals = [
            _make_signal(
                "SIG-DR",
                risk="high",
                prefilter_action="drop",
                fp_context=["formula_column"],
            )
        ]
        ledger = run_prefilter(signals, "triage")
        entry = ledger.entries[0]
        assert entry.profile_action == "hidden"
        assert entry.visible_in_report is False

    def test_clean_signal_kept(self) -> None:
        signals = [_make_signal("SIG-CLEAN", risk="high")]
        ledger = run_prefilter(signals, "triage")
        entry = ledger.entries[0]
        assert entry.profile_action == "kept"
        assert entry.visible_in_report is True
        assert entry.sent_to_llm is True


# ---------------------------------------------------------------------------
# Ledger serialisation
# ---------------------------------------------------------------------------


class TestLedgerSerialisation:
    def test_to_dict_round_trip(self, mixed_signals: list[dict]) -> None:
        ledger = run_prefilter(mixed_signals, "review")
        data = ledger.to_dict()
        assert data["schema_version"] == "1.0"
        assert data["profile"] == "review"
        assert len(data["entries"]) == len(mixed_signals)

    def test_entry_fields_complete(self) -> None:
        signals = [_make_signal("SIG-X", risk="medium")]
        ledger = run_prefilter(signals, "forensic")
        entry_dict = ledger.entries[0].to_dict()
        required_fields = {
            "signal_id",
            "profile",
            "detector_original_action",
            "prefilter_action",
            "profile_action",
            "false_positive_context",
            "prefilter_reason",
            "risk_before",
            "risk_after",
            "visible_in_report",
            "sent_to_llm",
        }
        assert required_fields.issubset(entry_dict.keys())


# ---------------------------------------------------------------------------
# Empty / edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_signals(self) -> None:
        ledger = run_prefilter([], "review")
        assert ledger.total == 0
        assert ledger.visible_count == 0

    def test_signal_without_optional_fields(self) -> None:
        """Minimal signal with only signal_id should not crash."""
        signals = [{"signal_id": "SIG-MIN"}]
        for profile_name in ("forensic", "review", "triage"):
            ledger = run_prefilter(signals, profile_name)
            assert ledger.total == 1

    def test_single_signal_all_profiles(self) -> None:
        signals = [_make_signal("SIG-1")]
        forensic = run_prefilter(signals, "forensic")
        review = run_prefilter(signals, "review")
        triage = run_prefilter(signals, "triage")
        assert forensic.visible_count >= review.visible_count >= triage.visible_count
