"""Tests for Review Dossier + Red-Team Refute (WP7).

Uses synthetic fixtures to verify:
- ReviewDossier schema roundtrip
- RedTeamRefute output schema
- 10-item refute checklist completeness
- Tier 1/2 gate: no refute -> cannot escalate
- Refute mechanism validation
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.static_audit.dossiers.red_team_refute import (
    RedTeamRefute,
    RefuteAttempt,
    run_red_team_refute,
)
from engine.static_audit.dossiers.refute_checklist import (
    REFUTE_CHECKLIST,
    RefuteChecklistItem,
    all_mechanisms,
    get_checklist_item,
    validate_mechanism,
)
from engine.static_audit.dossiers.review_dossier import ReviewDossier


# ---- Synthetic fixtures ----


@pytest.fixture()
def sample_dossier() -> ReviewDossier:
    """Create a sample Tier 1 review dossier."""
    return ReviewDossier(
        schema_version="1.0",
        dossier_id="DOSSIER-0001",
        target_signal_ids=["NUM-SIG-0001"],
        signal_summary="GRIM inconsistent: reported mean not achievable for integer n",
        detector_family="statistical_impossibility",
        risk_level_raw="high",
        suspicion_tier=1,
        impact_scope="core",
        evidence_locator={
            "source_path": "SourceData.xlsx",
            "source_sha256": "abc123",
            "sheet": "Source Data Fig.4",
            "rows": "5-39",
            "cols": "2-4",
        },
        claim_refs=["CLAIM-001"],
        figure_refs=["Fig.4c"],
        source_data_refs=["SourceData.xlsx"],
        profile_action="kept",
        prefilter_reason="",
        false_positive_context=[],
        benign_explanation_checklist=[],
        impact_hypothesis="If raw data is not integer-valued, GRIM may not apply",
        missing_materials=["raw measurement values"],
        scan_errors=[],
        review_status="pending",
    )


@pytest.fixture()
def sample_dossier_tier3() -> ReviewDossier:
    """Create a sample Tier 3 review dossier (low priority)."""
    return ReviewDossier(
        schema_version="1.0",
        dossier_id="DOSSIER-0003",
        target_signal_ids=["NUM-SIG-0003"],
        signal_summary="Weak digit distribution anomaly",
        detector_family="digit_statistics",
        risk_level_raw="low",
        suspicion_tier=3,
        impact_scope="peripheral",
    )


# ---- Refute Checklist tests ----


class TestRefuteChecklist:
    def test_checklist_has_10_items(self) -> None:
        assert len(REFUTE_CHECKLIST) == 10

    def test_all_mechanisms_unique(self) -> None:
        mechanisms = all_mechanisms()
        assert len(mechanisms) == len(set(mechanisms))

    def test_all_mechanisms_have_label_and_description(self) -> None:
        for item in REFUTE_CHECKLIST:
            assert item.mechanism, f"Item missing mechanism"
            assert item.label, f"Item {item.mechanism} missing label"
            assert item.description, f"Item {item.mechanism} missing description"

    def test_validate_mechanism(self) -> None:
        assert validate_mechanism("shared_control_or_replot") is True
        assert validate_mechanism("unit_conversion_or_formula") is True
        assert validate_mechanism("nonexistent_mechanism") is False

    def test_get_checklist_item(self) -> None:
        item = get_checklist_item("shared_control_or_replot")
        assert item is not None
        assert item.label == "Shared control / baseline replot"

    def test_get_checklist_item_missing(self) -> None:
        assert get_checklist_item("nonexistent") is None

    def test_checklist_item_to_dict(self) -> None:
        item = REFUTE_CHECKLIST[0]
        d = item.to_dict()
        assert "mechanism" in d
        assert "label" in d
        assert "description" in d
        assert "default_status" in d


# ---- ReviewDossier tests ----


class TestReviewDossier:
    def test_roundtrip(self, sample_dossier: ReviewDossier) -> None:
        d = sample_dossier.to_dict()
        restored = ReviewDossier.from_dict(d)
        assert restored.dossier_id == sample_dossier.dossier_id
        assert restored.target_signal_ids == sample_dossier.target_signal_ids
        assert restored.suspicion_tier == sample_dossier.suspicion_tier

    def test_requires_refute_tier1(self, sample_dossier: ReviewDossier) -> None:
        assert sample_dossier.requires_refute() is True

    def test_requires_refute_tier2(self) -> None:
        dossier = ReviewDossier(suspicion_tier=2)
        assert dossier.requires_refute() is True

    def test_no_refute_tier3(self, sample_dossier_tier3: ReviewDossier) -> None:
        assert sample_dossier_tier3.requires_refute() is False

    def test_impact_scope_default_unknown(self) -> None:
        dossier = ReviewDossier()
        assert dossier.impact_scope == "unknown"

    def test_dossier_json_serializable(self, sample_dossier: ReviewDossier) -> None:
        json_str = json.dumps(sample_dossier.to_dict())
        assert "DOSSIER-0001" in json_str


# ---- RedTeamRefute tests ----


class TestRedTeamRefute:
    def test_refute_attempt_valid(self) -> None:
        attempt = RefuteAttempt(
            mechanism="shared_control_or_replot",
            status="checked_no_fit",
            note="No shared control found",
        )
        errors = attempt.validate()
        assert errors == []

    def test_refute_attempt_invalid_mechanism(self) -> None:
        attempt = RefuteAttempt(
            mechanism="nonexistent",
            status="checked_no_fit",
        )
        errors = attempt.validate()
        assert any("Unknown mechanism" in e for e in errors)

    def test_refute_attempt_invalid_status(self) -> None:
        attempt = RefuteAttempt(
            mechanism="shared_control_or_replot",
            status="invalid_status",  # type: ignore[arg-type]
        )
        errors = attempt.validate()
        assert any("Invalid status" in e for e in errors)

    def test_red_team_refute_valid(self) -> None:
        refute = RedTeamRefute(
            review_id="REFUTE-0001",
            target_signal_ids=["NUM-SIG-0001"],
            review_status="confirmed",
            refute_attempts=[
                RefuteAttempt(
                    mechanism="shared_control_or_replot",
                    status="checked_no_fit",
                )
            ],
        )
        errors = refute.validate()
        assert errors == []

    def test_red_team_refute_missing_review_id(self) -> None:
        refute = RedTeamRefute(
            target_signal_ids=["NUM-SIG-0001"],
            review_status="confirmed",
        )
        errors = refute.validate()
        assert any("review_id" in e for e in errors)

    def test_red_team_refute_wrong_reviewer_role(self) -> None:
        refute = RedTeamRefute(
            review_id="R1",
            target_signal_ids=["NUM-SIG-0001"],
            review_status="confirmed",
            reviewer_role="not_red_team",
        )
        errors = refute.validate()
        assert any("reviewer_role" in e for e in errors)

    def test_refute_roundtrip(self) -> None:
        refute = RedTeamRefute(
            review_id="REFUTE-0001",
            target_signal_ids=["NUM-SIG-0001"],
            review_status="needs_more_material",
            refute_attempts=[
                RefuteAttempt(
                    mechanism="unit_conversion_or_formula",
                    status="plausible_unconfirmed",
                    note="Possible unit conversion",
                )
            ],
            strongest_benign_explanation="unit conversion remains plausible",
            remaining_uncertainty="raw measurement status unknown",
            recommended_final_status="needs_more_material",
            needs_author_data="raw values needed",
        )
        d = refute.to_dict()
        restored = RedTeamRefute.from_dict(d)
        assert restored.review_id == refute.review_id
        assert len(restored.refute_attempts) == 1
        assert restored.strongest_benign_explanation == refute.strongest_benign_explanation

    def test_refute_save(self, tmp_path: Path) -> None:
        refute = RedTeamRefute(
            review_id="REFUTE-0001",
            target_signal_ids=["NUM-SIG-0001"],
            review_status="confirmed",
        )
        out_path = tmp_path / "refute.json"
        refute.save(out_path)
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert data["review_id"] == "REFUTE-0001"


# ---- run_red_team_refute tests ----


class TestRunRedTeamRefute:
    def test_run_confirmed(self, sample_dossier: ReviewDossier) -> None:
        attempts = [
            RefuteAttempt(
                mechanism="shared_control_or_replot",
                status="checked_no_fit",
                note="No shared control",
            ),
            RefuteAttempt(
                mechanism="unit_conversion_or_formula",
                status="checked_no_fit",
                note="No formula found",
            ),
        ]
        result = run_red_team_refute(
            dossier=sample_dossier,
            refute_attempts=attempts,
            strongest_benign_explanation="",
            remaining_uncertainty="none",
            recommended_final_status="confirmed",
        )
        assert result.review_status == "confirmed"
        assert result.target_signal_ids == ["NUM-SIG-0001"]

    def test_run_rejected_when_benign_confirmed(
        self, sample_dossier: ReviewDossier
    ) -> None:
        attempts = [
            RefuteAttempt(
                mechanism="unit_conversion_or_formula",
                status="confirmed",
                note="Confirmed: values are unit-converted",
            ),
        ]
        result = run_red_team_refute(
            dossier=sample_dossier,
            refute_attempts=attempts,
        )
        assert result.review_status == "rejected"

    def test_run_needs_more_material(
        self, sample_dossier: ReviewDossier
    ) -> None:
        attempts = [
            RefuteAttempt(
                mechanism="unit_conversion_or_formula",
                status="plausible_unconfirmed",
                note="Possible but unconfirmed",
            ),
        ]
        result = run_red_team_refute(
            dossier=sample_dossier,
            refute_attempts=attempts,
        )
        assert result.review_status == "needs_more_material"

    def test_run_auto_review_id(self, sample_dossier: ReviewDossier) -> None:
        result = run_red_team_refute(
            dossier=sample_dossier,
            refute_attempts=[
                RefuteAttempt(
                    mechanism="shared_control_or_replot",
                    status="checked_no_fit",
                )
            ],
        )
        assert result.review_id.startswith("REFUTE-")
        assert "NUM-SIG-0001" in result.review_id

    def test_run_invalid_mechanism_raises(
        self, sample_dossier: ReviewDossier
    ) -> None:
        with pytest.raises(ValueError, match="failed validation"):
            run_red_team_refute(
                dossier=sample_dossier,
                refute_attempts=[
                    RefuteAttempt(
                        mechanism="nonexistent",
                        status="checked_no_fit",
                    )
                ],
            )


# ---- Tier gate tests ----


class TestTierGate:
    """Tier 1/2 findings without refute cannot enter high-priority zone."""

    def test_tier1_requires_refute(self, sample_dossier: ReviewDossier) -> None:
        assert sample_dossier.suspicion_tier == 1
        assert sample_dossier.requires_refute() is True

    def test_tier2_requires_refute(self) -> None:
        dossier = ReviewDossier(suspicion_tier=2)
        assert dossier.requires_refute() is True

    def test_tier3_no_refute_needed(
        self, sample_dossier_tier3: ReviewDossier
    ) -> None:
        assert sample_dossier_tier3.suspicion_tier == 3
        assert sample_dossier_tier3.requires_refute() is False

    def test_tier1_without_refute_cannot_escalate(
        self, sample_dossier: ReviewDossier
    ) -> None:
        """A Tier 1 dossier with pending review_status cannot be escalated."""
        assert sample_dossier.requires_refute() is True
        assert sample_dossier.review_status == "pending"
        # Gate logic: requires_refute() == True AND review_status == "pending"
        # means cannot enter high-priority conclusion zone
        can_escalate = (
            not sample_dossier.requires_refute()
            or sample_dossier.review_status != "pending"
        )
        assert can_escalate is False

    def test_tier1_with_confirmed_refute_can_escalate(
        self, sample_dossier: ReviewDossier
    ) -> None:
        sample_dossier.review_status = "confirmed"
        can_escalate = (
            not sample_dossier.requires_refute()
            or sample_dossier.review_status != "pending"
        )
        assert can_escalate is True
