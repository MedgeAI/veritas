"""Tests for the ground truth pipeline (parser, mapper, gap_analyzer, anti_overfit)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engine.ground_truth.anti_overfit import AntiOverfitChecker
from engine.ground_truth.design_spec import generate_design_spec
from engine.ground_truth.gap_analyzer import GapRecord, analyze_gaps
from engine.ground_truth.mapper import MappedClaim, map_claims_to_capabilities
from engine.ground_truth.parser import (
    StructuredClaim,
    parse_manual_annotations,
    parse_pubpeer_post,
)

GROUND_TRUTH_DIR = Path("ground_truth/paper2")
CATALOG_PATH = Path("capabilities/capability_catalog.yaml")


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestPubPeerParser:
    def test_parse_splits_comments(self):
        text = """
**#1** ***Species***
The image in Fig. 4h appears identical after rotation — same structure repeated.

**#2** ***Species***
In Fig.5c, rows have identical values for both markers; fixed difference pattern.
"""
        claims = parse_pubpeer_post(text)
        assert len(claims) >= 1

    def test_parse_detects_rotation_claim(self):
        text = """
**#1** ***TestSpecies***
In panel h of Extended Data Fig. 4:
The image in the upper center appears almost identical to the one on the upper left after a 90° clockwise rotation.
"""
        claims = parse_pubpeer_post(text)
        assert any(c.claim_type == "visual.copy_move_keypoint" for c in claims)

    def test_parse_detects_fixed_difference(self):
        text = """
**#3** ***TestSpecies***
In Fig.5c, the following repeated entries are present.
Fixed difference pattern found across rows.
"""
        claims = parse_pubpeer_post(text)
        assert len(claims) >= 1

    def test_parse_detects_missing_source_data(self):
        text = """
**#7** ***TestSpecies***
Also, no source data from Fig. 7i
"""
        claims = parse_pubpeer_post(text)
        assert any(c.evidence_type == "completeness" for c in claims)

    def test_empty_text_returns_empty(self):
        assert parse_pubpeer_post("") == []
        assert parse_pubpeer_post("no comments here") == []


class TestManualAnnotations:
    def test_parse_paper2_annotations(self):
        annotations_path = GROUND_TRUTH_DIR / "annotations.yaml"
        if not annotations_path.exists():
            pytest.skip("paper2 annotations not available")
        claims = parse_manual_annotations(annotations_path)
        assert len(claims) == 9
        assert all(isinstance(c, StructuredClaim) for c in claims)
        assert all(c.confirmed_by_human for c in claims)

    def test_claim_types_are_valid(self):
        annotations_path = GROUND_TRUTH_DIR / "annotations.yaml"
        if not annotations_path.exists():
            pytest.skip("paper2 annotations not available")
        claims = parse_manual_annotations(annotations_path)
        valid_prefixes = ("visual.", "source_data.", "completeness.", "numeric.")
        for c in claims:
            assert any(c.claim_type.startswith(p) for p in valid_prefixes), (
                f"Invalid claim_type: {c.claim_type}"
            )


# ---------------------------------------------------------------------------
# Mapper tests
# ---------------------------------------------------------------------------


class TestMapper:
    def test_map_visual_claim(self):
        claims = [StructuredClaim(
            claim_type="visual.copy_move_keypoint",
            target="Extended Data Fig. 4h",
            description="90° rotation",
            evidence_type="image",
        )]
        mapped = map_claims_to_capabilities(claims)
        assert len(mapped) == 1
        assert mapped[0].capability_id == "visual.copy_move_keypoint"
        assert mapped[0].capability_category == "visual"

    def test_map_source_data_claim(self):
        claims = [StructuredClaim(
            claim_type="source_data.fixed_ratio",
            target="Fig. 7d",
            description="Pairs 21-40 = Pairs 1-20 × 1.2",
            evidence_type="source_data",
        )]
        mapped = map_claims_to_capabilities(claims)
        assert mapped[0].capability_category == "source_data"

    def test_detected_when_finding_matches(self):
        claims = [StructuredClaim(
            claim_type="source_data.fixed_ratio",
            target="Fig. 7d",
            description="fixed ratio 1.2",
            evidence_type="source_data",
        )]
        findings = [{
            "finding_id": "FR-0001",
            "category": "fixed_ratio",
            "summary": "Fig. 7d shows fixed ratio 1.2",
            "target": "Fig. 7d",
        }]
        mapped = map_claims_to_capabilities(claims, existing_findings=findings)
        assert mapped[0].detected is True
        assert mapped[0].existing_finding_id == "FR-0001"

    def test_not_detected_when_no_match(self):
        claims = [StructuredClaim(
            claim_type="source_data.fixed_ratio",
            target="Fig. 99z",
            description="something unique",
            evidence_type="source_data",
        )]
        mapped = map_claims_to_capabilities(claims, existing_findings=[])
        assert mapped[0].detected is False


# ---------------------------------------------------------------------------
# Gap analyzer tests
# ---------------------------------------------------------------------------


class TestGapAnalyzer:
    def test_gap_for_undetected_claim(self):
        claim = StructuredClaim(
            claim_type="visual.copy_move_keypoint",
            target="Fig. 4h",
            description="rotation detected",
            evidence_type="image",
        )
        mapped = [MappedClaim(
            claim=claim, capability_id="visual.copy_move_keypoint",
            capability_category="visual", detected=False,
        )]
        gaps = analyze_gaps(mapped)
        assert len(gaps) == 1
        assert gaps[0].gap_type in ("NEW_DETECTOR", "CALIBRATION")
        assert gaps[0].severity == "high"

    def test_no_gap_for_detected_claim(self):
        claim = StructuredClaim(
            claim_type="source_data.fixed_ratio",
            target="Fig. 7d",
            description="ratio",
            evidence_type="source_data",
        )
        mapped = [MappedClaim(
            claim=claim, capability_id="source_data.fixed_ratio",
            capability_category="source_data", detected=True,
        )]
        gaps = analyze_gaps(mapped)
        assert len(gaps) == 0

    def test_coverage_gap_for_missing_source_data(self):
        claim = StructuredClaim(
            claim_type="completeness.missing_source_data",
            target="Fig. 7i",
            description="no source data provided",
            evidence_type="completeness",
        )
        mapped = [MappedClaim(
            claim=claim, capability_id="completeness.missing_source_data",
            capability_category="completeness", detected=False,
        )]
        gaps = analyze_gaps(mapped)
        assert len(gaps) == 1
        assert gaps[0].gap_type == "COVERAGE"
        assert gaps[0].severity == "low"


# ---------------------------------------------------------------------------
# Design spec tests
# ---------------------------------------------------------------------------


class TestDesignSpec:
    def test_visual_design_spec(self):
        gap = GapRecord(
            gap_type="NEW_DETECTOR",
            capability_id="visual.copy_move_keypoint",
            claim_description="rotation",
            claim_target="Fig. 4h",
            recommended_action="implement",
        )
        spec = generate_design_spec(gap)
        assert spec.capability_id == "visual.copy_move_keypoint"
        assert "images" in spec.input_contract
        assert len(spec.test_contract) == 3
        assert len(spec.anti_overfit_checklist) == 5

    def test_source_data_design_spec(self):
        gap = GapRecord(
            gap_type="NEW_DETECTOR",
            capability_id="source_data.fixed_ratio",
            claim_description="ratio",
            claim_target="Fig. 7d",
            recommended_action="implement",
        )
        spec = generate_design_spec(gap)
        assert "source_data_dir" in spec.input_contract


# ---------------------------------------------------------------------------
# Anti-overfit tests
# ---------------------------------------------------------------------------


class TestAntiOverfit:
    def test_clean_code_passes(self, tmp_path):
        checker = AntiOverfitChecker()
        code = """
def detect_anomaly(columns, threshold=0.05):
    for col in columns:
        if col.value > threshold:
            yield col
"""
        dist = tmp_path / "distribution_analysis.md"
        dist.write_text("# Threshold analysis\nDerived from 100-paper distribution.")
        report = checker.check_all(
            "test.cap", code,
            validation_papers=["paper1", "paper2", "paper3"],
            distribution_path=dist,
        )
        assert report.passed is True
        assert len(report.violations) == 0

    def test_hardcoded_figure_fails(self):
        checker = AntiOverfitChecker()
        code = """
def check_fig7d(data):
    return data["Fig. 7d"] > 1.2
"""
        report = checker.check_all("test.cap", code)
        hardcoded_violations = [v for v in report.violations if "Rule 2" in v]
        assert len(hardcoded_violations) > 0

    def test_insufficient_validation_papers(self):
        checker = AntiOverfitChecker()
        ok, msg = checker.check_cross_paper_validation(["paper1"])
        assert ok is False
        assert "3" in msg

    def test_sufficient_validation_papers(self):
        checker = AntiOverfitChecker()
        ok, msg = checker.check_cross_paper_validation(["paper1", "paper2", "paper3"])
        assert ok is True


# ---------------------------------------------------------------------------
# Capability catalog tests
# ---------------------------------------------------------------------------


class TestCapabilityCatalog:
    def test_catalog_exists_and_valid(self):
        if not CATALOG_PATH.exists():
            pytest.skip("capability catalog not available")
        data = yaml.safe_load(CATALOG_PATH.read_text())
        assert "capabilities" in data
        caps = data["capabilities"]
        assert isinstance(caps, list)
        assert len(caps) > 0

    def test_catalog_entries_have_required_fields(self):
        if not CATALOG_PATH.exists():
            pytest.skip("capability catalog not available")
        data = yaml.safe_load(CATALOG_PATH.read_text())
        for cap in data["capabilities"]:
            assert "capability_id" in cap
            assert "category" in cap
            assert cap["category"] in ("visual", "source_data", "completeness", "numeric")
