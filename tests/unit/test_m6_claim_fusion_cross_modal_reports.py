"""Tests for M6 milestone: Claim Fusion, Cross-Modal Dossier, Report modules.

Uses synthetic data exclusively — no real PaperConan output, no real
audit bundles.  Tests are organized by keyword for selective execution:

    pytest tests/ -k "claim_fusion"
    pytest tests/ -k "cross_modal"
    pytest tests/ -k "numeric_forensics_report"
"""

from __future__ import annotations

from engine.static_audit.numeric_signal_schema import (
    ApplicabilityPremise,
    EvidenceLocator,
    NumericSignal,
)
from engine.static_audit.claim_fusion import (
    ClaimMapping,
    build_claim_index,
    enrich_signal_with_claim_mapping,
    fuse_signal_to_claims,
    fuse_signals_to_claims,
)
from engine.static_audit.cross_modal_dossier import (
    build_cross_modal_dossier,
    build_dossiers_for_claims,
    get_all_refute_mechanisms,
    get_refute_mechanisms,
    register_refute_mechanism,
)
from engine.reporting.numeric_forensics_report import (
    build_numeric_forensics_summary,
)
from engine.reporting.paperconan_coverage_report import (
    build_paperconan_coverage_report,
)
from engine.reporting.prefilter_ledger_report import (
    build_prefilter_ledger_report,
)
from engine.reporting.red_team_report import (
    build_red_team_report,
)
from engine.reporting.source_acquisition_report import (
    build_source_acquisition_report,
)


# ============================================================================
# Synthetic data factories
# ============================================================================

def _make_signal(
    signal_id: str = "NUM-SIG-0001",
    source_path: str = "SourceData.xlsx",
    sheet: str = "Fig4",
    risk: str = "high",
    impact_scope: str = "unknown",
    claim_refs: list[str] | None = None,
    figure_refs: list[str] | None = None,
    profile_action: str = "kept",
    detector_family: str = "column_relations",
    requires_raw: bool = False,
    needs_author: str = "",
) -> NumericSignal:
    """Create a synthetic NumericSignal for testing."""
    return NumericSignal(
        signal_id=signal_id,
        source_tool="paperconan",
        source_tool_version="0.3",
        detector_id="paperconan.constant_offset",
        detector_family=detector_family,
        raw_kind="constant_offset",
        canonical_category="constant_offset",
        rule="Two columns differ by a constant offset of 3.0",
        n=35,
        effect_size=1.0,
        mechanical_confidence=0.95,
        risk_level_raw=risk,
        profile="review",
        profile_action=profile_action,
        prefilter_action="keep",
        false_positive_context=["derived_or_unit_conversion"],
        prefilter_reason="",
        applicability_premise=ApplicabilityPremise(
            requires_raw_measurement=requires_raw,
        ),
        evidence_locator=EvidenceLocator(
            source_path=source_path,
            source_sha256="abc123",
            sheet=sheet,
            rows="5-39",
            cols="B-D",
        ),
        raw_payload_ref="numeric/paperconan_scan.json#/relations_blocks/0",
        claim_refs=claim_refs or [],
        figure_refs=figure_refs or [],
        source_data_refs=[],
        impact_scope=impact_scope,  # type: ignore[arg-type]
        impact_reason="",
        needs_author_data=needs_author,
    )


# ============================================================================
# claim_fusion tests
# ============================================================================

class TestClaimFusion:
    """Tests for claim_fusion module."""

    def test_fuse_signal_no_mapping_yields_unknown(self) -> None:
        """A signal with no matching claim/figure should get impact_scope=unknown."""
        signal = _make_signal()
        index = build_claim_index()

        mapping = fuse_signal_to_claims(signal, index)

        assert mapping.impact_scope == "unknown"
        assert mapping.claim_refs == []
        assert mapping.figure_refs == []
        assert mapping.mapping_confidence == "low"

    def test_fuse_signal_mapped_to_claim_via_source_data_map(self) -> None:
        """A signal whose sheet is in the source_data_map gets claim_refs."""
        signal = _make_signal(sheet="Fig4")
        index = build_claim_index(
            claims=[
                {"claim_id": "claim_main", "text": "Main conclusion"},
            ],
            source_data_map={"Fig4": ["claim_main"]},
        )

        mapping = fuse_signal_to_claims(signal, index)

        assert "claim_main" in mapping.claim_refs
        assert mapping.impact_scope in ("core", "supporting")
        assert mapping.source_data_refs == ["Fig4"]

    def test_fuse_signal_mapped_to_figure(self) -> None:
        """A signal whose sheet is referenced by a figure gets figure_refs."""
        signal = _make_signal(sheet="Fig4")
        index = build_claim_index(
            claims=[
                {"claim_id": "claim_secondary", "text": "Secondary observation"},
            ],
            figures=[
                {"figure_id": "Fig.4c", "source_data_refs": ["Fig4"]},
            ],
            source_data_map={"Fig4": ["claim_secondary"]},
        )

        mapping = fuse_signal_to_claims(signal, index)

        assert "Fig.4c" in mapping.figure_refs

    def test_fuse_signal_core_claim_detection(self) -> None:
        """A signal mapped to a 'main' claim should get impact_scope=core."""
        signal = _make_signal(sheet="SourceData")
        index = build_claim_index(
            claims=[
                {"claim_id": "main_conclusion", "text": "The main result"},
            ],
            source_data_map={"SourceData": ["main_conclusion"]},
        )

        mapping = fuse_signal_to_claims(signal, index)

        assert mapping.impact_scope == "core"

    def test_fuse_signals_batch(self) -> None:
        """Batch mapping should produce one ClaimMapping per signal."""
        signals = [
            _make_signal(signal_id="S1", sheet="A"),
            _make_signal(signal_id="S2", sheet="B"),
        ]
        index = build_claim_index(
            source_data_map={"A": ["c1"]},
        )

        mappings = fuse_signals_to_claims(signals, index)

        assert len(mappings) == 2
        assert mappings[0].signal_id == "S1"
        assert mappings[1].signal_id == "S2"
        assert mappings[0].claim_refs == ["c1"]
        assert mappings[1].claim_refs == []

    def test_enrich_signal_with_claim_mapping(self) -> None:
        """enrich_signal_with_claim_mapping returns a new signal with WP8 fields."""
        signal = _make_signal()
        mapping = ClaimMapping(
            signal_id=signal.signal_id,
            claim_refs=["c1"],
            figure_refs=["Fig.1"],
            source_data_refs=["Sheet1"],
            impact_scope="core",
            impact_reason="Central to main conclusion",
            needs_author_data="Raw values needed",
            mapping_confidence="high",
        )

        enriched = enrich_signal_with_claim_mapping(signal, mapping)

        assert enriched.claim_refs == ["c1"]
        assert enriched.figure_refs == ["Fig.1"]
        assert enriched.impact_scope == "core"
        assert enriched.needs_author_data == "Raw values needed"
        # Original is unchanged (frozen)
        assert signal.claim_refs == []

    def test_never_default_to_peripheral(self) -> None:
        """When no mapping is found, impact_scope must be 'unknown', not 'peripheral'."""
        signal = _make_signal()
        index = build_claim_index(claims=[], figures=[], source_data_map={})

        mapping = fuse_signal_to_claims(signal, index)

        assert mapping.impact_scope == "unknown"
        assert mapping.impact_scope != "peripheral"


# ============================================================================
# cross_modal tests
# ============================================================================

class TestCrossModalDossier:
    """Tests for cross_modal_dossier module."""

    def test_build_dossier_empty(self) -> None:
        """An empty dossier should have no evidence and info risk."""
        dossier = build_cross_modal_dossier(
            dossier_id="D1",
            claim_id="c1",
            claim_text="Test claim",
        )

        assert dossier.dossier_id == "D1"
        assert dossier.evidence == []
        assert dossier.highest_risk_level() == "info"
        assert dossier.modalities_present() == []

    def test_build_dossier_with_numeric_signals(self) -> None:
        """A dossier with numeric signals should list 'numeric' modality."""
        sig = _make_signal(risk="high")
        dossier = build_cross_modal_dossier(
            dossier_id="D1",
            claim_id="c1",
            claim_text="Test",
            numeric_signals=[sig],
        )

        assert len(dossier.evidence) == 1
        assert dossier.evidence[0].modality == "numeric"
        assert dossier.highest_risk_level() == "high"
        assert "numeric" in dossier.modalities_present()

    def test_build_dossier_multi_modal(self) -> None:
        """A dossier with all three modalities should list them all."""
        sig = _make_signal(risk="medium")
        img = {"finding_id": "IMG-001", "risk_level": "high", "summary": "Panel reuse"}
        code = {"finding_id": "CODE-001", "risk_level": "low", "summary": "Cannot reproduce"}

        dossier = build_cross_modal_dossier(
            dossier_id="D1",
            claim_id="c1",
            claim_text="Multi-modal claim",
            numeric_signals=[sig],
            image_findings=[img],
            code_findings=[code],
        )

        assert len(dossier.evidence) == 3
        assert set(dossier.modalities_present()) == {"numeric", "image", "code"}
        assert dossier.highest_risk_level() == "high"

    def test_evidence_by_modality(self) -> None:
        """evidence_by_modality should filter correctly."""
        sig = _make_signal()
        img = {"finding_id": "IMG-001", "risk_level": "info", "summary": "ok"}

        dossier = build_cross_modal_dossier(
            dossier_id="D1",
            claim_id="c1",
            claim_text="Test",
            numeric_signals=[sig],
            image_findings=[img],
        )

        assert len(dossier.evidence_by_modality("numeric")) == 1
        assert len(dossier.evidence_by_modality("image")) == 1
        assert len(dossier.evidence_by_modality("code")) == 0

    def test_build_dossiers_for_claims(self) -> None:
        """build_dossiers_for_claims should create one dossier per claim with evidence."""
        claims = [
            {"claim_id": "c1", "text": "Claim 1"},
            {"claim_id": "c2", "text": "Claim 2"},
            {"claim_id": "c3", "text": "Claim 3 (no evidence)"},
        ]
        sig1 = _make_signal(signal_id="S1", claim_refs=["c1"])
        sig2 = _make_signal(signal_id="S2", claim_refs=["c2"])
        img = {"finding_id": "IMG-001", "risk_level": "medium", "summary": "test", "claim_refs": ["c1"]}

        dossiers = build_dossiers_for_claims(
            claims=claims,
            numeric_signals=[sig1, sig2],
            image_findings=[img],
        )

        # c3 has no evidence, so only 2 dossiers
        assert len(dossiers) == 2
        dossier_map = {d.claim_id: d for d in dossiers}
        assert "c1" in dossier_map
        assert "c2" in dossier_map
        # c1 has 1 numeric + 1 image
        assert len(dossier_map["c1"].evidence) == 2
        # c2 has 1 numeric
        assert len(dossier_map["c2"].evidence) == 1

    def test_refute_mechanisms_default(self) -> None:
        """Default refute mechanisms should cover all three modalities."""
        all_mechs = get_all_refute_mechanisms()
        assert "numeric" in all_mechs
        assert "image" in all_mechs
        assert "code" in all_mechs
        assert len(all_mechs["numeric"]) > 0

    def test_register_refute_mechanism(self) -> None:
        """Custom refute mechanisms can be registered per modality."""
        register_refute_mechanism("numeric", "custom_test_mechanism")
        mechs = get_refute_mechanisms("numeric")
        assert "custom_test_mechanism" in mechs

    def test_dossier_to_dict(self) -> None:
        """to_dict should produce a JSON-serializable dict."""
        dossier = build_cross_modal_dossier(
            dossier_id="D1",
            claim_id="c1",
            claim_text="Test",
            numeric_signals=[_make_signal()],
        )

        d = dossier.to_dict()
        assert d["dossier_id"] == "D1"
        assert d["modalities_present"] == ["numeric"]
        assert d["highest_risk_level"] == "high"
        assert len(d["evidence"]) == 1


# ============================================================================
# numeric_forensics_report tests
# ============================================================================

class TestNumericForensicsReport:
    """Tests for numeric_forensics_report module."""

    def test_empty_signals(self) -> None:
        """An empty signal list should produce a zeroed summary."""
        summary = build_numeric_forensics_summary([])

        assert summary.total_signals == 0
        assert summary.high_priority_signals == []
        assert summary.hidden_signal_count == 0

    def test_single_high_priority_signal(self) -> None:
        """A single high-risk kept signal should appear in high_priority_signals."""
        sig = _make_signal(risk="high", profile_action="kept")
        summary = build_numeric_forensics_summary([sig])

        assert summary.total_signals == 1
        assert len(summary.high_priority_signals) == 1
        assert summary.high_priority_signals[0]["signal_id"] == "NUM-SIG-0001"

    def test_demoted_signal_not_high_priority(self) -> None:
        """A demoted signal should NOT appear in high_priority_signals."""
        sig = _make_signal(risk="high", profile_action="demoted")
        summary = build_numeric_forensics_summary([sig])

        assert summary.total_signals == 1
        assert summary.demoted_signal_count == 1
        assert len(summary.high_priority_signals) == 0

    def test_hidden_signal_counted(self) -> None:
        """Hidden signals should increment hidden_signal_count."""
        sig = _make_signal(risk="medium", profile_action="hidden")
        summary = build_numeric_forensics_summary([sig])

        assert summary.hidden_signal_count == 1
        assert len(summary.high_priority_signals) == 0

    def test_by_detector_family(self) -> None:
        """Signals should be grouped by detector_family."""
        signals = [
            _make_signal(signal_id="S1", detector_family="column_relations"),
            _make_signal(signal_id="S2", detector_family="column_relations"),
            _make_signal(signal_id="S3", detector_family="statistical_impossibility"),
        ]
        summary = build_numeric_forensics_summary(signals)

        assert summary.by_detector_family["column_relations"] == 2
        assert summary.by_detector_family["statistical_impossibility"] == 1

    def test_by_impact_scope(self) -> None:
        """Signals should be grouped by impact_scope."""
        signals = [
            _make_signal(signal_id="S1", impact_scope="core"),
            _make_signal(signal_id="S2", impact_scope="unknown"),
            _make_signal(signal_id="S3", impact_scope="unknown"),
        ]
        summary = build_numeric_forensics_summary(signals)

        assert summary.by_impact_scope["core"] == 1
        assert summary.by_impact_scope["unknown"] == 2

    def test_claim_mapping_count(self) -> None:
        """Signals with claim_refs should be counted."""
        signals = [
            _make_signal(signal_id="S1", claim_refs=["c1"]),
            _make_signal(signal_id="S2"),  # no claim refs
        ]
        summary = build_numeric_forensics_summary(signals)

        assert summary.signals_with_claim_mapping == 1

    def test_needs_author_data_count(self) -> None:
        """Signals with needs_author_data should be counted."""
        signals = [
            _make_signal(signal_id="S1", needs_author="Raw values"),
            _make_signal(signal_id="S2", needs_author=""),
        ]
        summary = build_numeric_forensics_summary(signals)

        assert summary.signals_needing_author_data == 1

    def test_to_dict_serializable(self) -> None:
        """to_dict should produce a JSON-serializable dict."""
        sig = _make_signal()
        summary = build_numeric_forensics_summary([sig])
        d = summary.to_dict()

        assert d["total_signals"] == 1
        assert isinstance(d["by_detector_family"], dict)
        assert isinstance(d["high_priority_signals"], list)


# ============================================================================
# Additional WP10 report tests (not in the filter keyword but still valuable)
# ============================================================================

class TestPaperconanCoverageReport:
    """Tests for paperconan_coverage_report module."""

    def test_empty_inputs(self) -> None:
        report = build_paperconan_coverage_report()
        assert report.total_kinds_tracked == 0
        assert report.coverage_rate == 0.0

    def test_full_coverage(self) -> None:
        matrix = [
            {"kind": "grim_inconsistent", "status": "translated"},
            {"kind": "identical_column", "status": "native_equivalent"},
            {"kind": "last_digit_chi_square", "status": "translated"},
        ]
        report = build_paperconan_coverage_report(coverage_matrix=matrix)

        assert report.total_kinds_tracked == 3
        assert report.translated == 2
        assert report.native_equivalent == 1
        assert report.coverage_rate == 1.0

    def test_partial_coverage(self) -> None:
        matrix = [
            {"kind": "grim_inconsistent", "status": "translated"},
            {"kind": "some_new_kind", "status": "planned"},
        ]
        report = build_paperconan_coverage_report(coverage_matrix=matrix)

        assert report.coverage_rate == 0.5
        assert report.planned == 1

    def test_unexplained_skips(self) -> None:
        ledger = [
            {"kind": "grim_inconsistent", "status": "skipped", "skip_reason": ""},
            {"kind": "identical_column", "status": "skipped", "skip_reason": "duplicate"},
        ]
        report = build_paperconan_coverage_report(translation_ledger=ledger)

        assert report.skipped_in_scan == 2
        assert report.unexplained_skips == 1


class TestPrefilterLedgerReport:
    """Tests for prefilter_ledger_report module."""

    def test_empty_ledger(self) -> None:
        report = build_prefilter_ledger_report()
        assert report.total_entries == 0

    def test_mixed_ledger(self) -> None:
        entries = [
            {"signal_id": "S1", "profile": "review", "profile_action": "kept",
             "prefilter_action": "keep", "visible_in_report": True, "sent_to_llm": True},
            {"signal_id": "S2", "profile": "review", "profile_action": "demoted",
             "prefilter_action": "downweight", "visible_in_report": True, "sent_to_llm": False},
            {"signal_id": "S3", "profile": "review", "profile_action": "hidden",
             "prefilter_action": "drop", "visible_in_report": False, "sent_to_llm": False},
        ]
        report = build_prefilter_ledger_report(entries)

        assert report.total_entries == 3
        assert report.kept_count == 1
        assert report.demoted_count == 1
        assert report.hidden_count == 1
        assert report.visible_in_report == 2
        assert report.sent_to_llm == 1


class TestRedTeamReport:
    """Tests for red_team_report module."""

    def test_empty_reviews(self) -> None:
        report = build_red_team_report()
        assert report.total_reviews == 0

    def test_mixed_reviews(self) -> None:
        reviews = [
            {"review_id": "R1", "review_status": "confirmed", "target_signal_ids": ["S1"]},
            {"review_id": "R2", "review_status": "rejected", "target_signal_ids": ["S2"]},
            {"review_id": "R3", "review_status": "needs_more_material"},
        ]
        report = build_red_team_report(reviews)

        assert report.total_reviews == 3
        assert report.confirmed == 1
        assert report.rejected == 1
        assert report.needs_more_material == 1

    def test_gate_compliance(self) -> None:
        reviews = [
            {"review_id": "R1", "review_status": "confirmed"},
        ]
        report = build_red_team_report(reviews, tier1_tier2_candidates=2)

        assert report.gate_compliance == 0.5


class TestSourceAcquisitionReport:
    """Tests for source_acquisition_report module."""

    def test_empty_manifest(self) -> None:
        report = build_source_acquisition_report()
        assert report.status == "not_attempted"
        assert report.total_files == 0

    def test_user_uploaded(self) -> None:
        manifest = {
            "status": "user_only",
            "downloaded_files": [
                {
                    "path": "data.xlsx",
                    "sha256": "abc123",
                    "size_bytes": 1024,
                    "origin": "user_uploaded",
                },
            ],
        }
        report = build_source_acquisition_report(manifest)

        assert report.status == "user_only"
        assert report.total_files == 1
        assert report.has_user_uploaded is True
        assert report.has_public_fetched is False
        assert report.total_size_bytes == 1024

    def test_no_data_found(self) -> None:
        manifest = {
            "status": "no_data_found",
            "query": {"doi": "10.1234/test"},
            "no_data_found_reason": "No supplementary data found at publisher site",
            "matched_sources": [],
            "downloaded_files": [],
            "fetch_errors": ["DOI resolved but no data links found"],
        }
        report = build_source_acquisition_report(manifest)

        assert report.status == "no_data_found"
        assert report.no_data_found_reason != ""
        assert len(report.fetch_errors) == 1
