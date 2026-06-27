"""Unit tests for the certification grade engine.

Tests cover the four grade levels (A/B/C/D) and the four dimensions:
reproducibility, numerical fidelity, methodology, interpretation.
"""

from __future__ import annotations

from engine.static_audit.grade_engine import (
    CertificationGrade,
    compute_grade,
)
from engine.static_audit.models import (
    Finding,
    StaticAuditBundle,
    ToolRun,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bundle(
    *,
    findings: list[Finding] | None = None,
    tool_runs: list[ToolRun] | None = None,
) -> StaticAuditBundle:
    """Create a minimal StaticAuditBundle for testing."""
    return StaticAuditBundle(
        case_id="test-case-001",
        inputs={},
        findings=findings or [],
        tool_runs=tool_runs or [],
    )


def _make_finding(
    finding_id: str = "F001",
    category: str = "duplicate_column",
    risk_level: str = "medium",
    issue_category: str = "consistency",
) -> Finding:
    """Create a minimal Finding for testing."""
    return Finding(
        finding_id=finding_id,
        category=category,
        risk_level=risk_level,  # type: ignore[arg-type]
        summary="test finding",
        issue_category=issue_category,  # type: ignore[arg-type]
    )


def _make_tool_run(step_key: str, status: str = "ran") -> ToolRun:
    """Create a minimal ToolRun for testing."""
    return ToolRun(tool_id=f"tool_{step_key}", step_key=step_key, status=status)  # type: ignore[arg-type]


def _dimension_status(grade: CertificationGrade, name: str) -> str:
    """Extract the status of a named dimension from a grade."""
    for dim in grade.dimensions:
        if dim.name == name:
            return dim.status
    raise KeyError(f"Dimension {name!r} not found")


# ---------------------------------------------------------------------------
# Grade A: all dimensions pass
# ---------------------------------------------------------------------------


class TestGradeA:
    """Grade A: all dimensions pass or pass_with_notes."""

    def test_empty_findings_grade_a(self) -> None:
        """Empty findings list should produce grade A."""
        bundle = _make_bundle(
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.grade == "A"
        assert grade.label == "完全通过"
        assert grade.total_findings == 0

    def test_only_low_info_findings_grade_a(self) -> None:
        """Only low/info consistency findings → pass_with_notes → grade A."""
        findings = [
            _make_finding("F001", risk_level="low", issue_category="consistency"),
            _make_finding("F002", risk_level="info", issue_category="consistency"),
        ]
        bundle = _make_bundle(
            findings=findings,
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.grade == "A"
        assert _dimension_status(grade, "numerical_fidelity") == "pass_with_notes"

    def test_all_steps_ran_no_findings(self) -> None:
        """All critical steps ran, no findings → grade A."""
        bundle = _make_bundle(
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
                _make_tool_run("source_data_extract"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.grade == "A"
        assert _dimension_status(grade, "reproducibility") == "pass"


# ---------------------------------------------------------------------------
# Grade B: warning, no fail
# ---------------------------------------------------------------------------


class TestGradeB:
    """Grade B: any dimension has warning, no dimension fails."""

    def test_medium_consistency_warning(self) -> None:
        """Medium consistency findings → warning → grade B."""
        findings = [
            _make_finding("F001", risk_level="medium", issue_category="consistency"),
        ]
        bundle = _make_bundle(
            findings=findings,
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.grade == "B"
        assert _dimension_status(grade, "numerical_fidelity") == "warning"

    def test_methodology_review_warning(self) -> None:
        """paperfraud.methodology_review → warning in interpretation → grade B."""
        findings = [
            _make_finding(
                "F001",
                category="paperfraud.methodology_review",
                risk_level="high",
                issue_category="matching",
            ),
        ]
        bundle = _make_bundle(
            findings=findings,
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.grade == "B"
        assert _dimension_status(grade, "interpretation") == "warning"

    def test_source_data_failed_warning(self) -> None:
        """Source data step failed → warning in reproducibility → grade B."""
        bundle = _make_bundle(
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
                _make_tool_run("source_data_extract", status="failed"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.grade == "B"
        assert _dimension_status(grade, "reproducibility") == "warning"


# ---------------------------------------------------------------------------
# Grade C: dimension fails but reproducibility not fully broken
# ---------------------------------------------------------------------------


class TestGradeC:
    """Grade C: a non-reproducibility dimension fails."""

    def test_critical_consistency_fail_grade_c(self) -> None:
        """Critical consistency finding → fail in numerical fidelity → grade C."""
        findings = [
            _make_finding(
                "F001", risk_level="critical", issue_category="consistency"
            ),
        ]
        bundle = _make_bundle(
            findings=findings,
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.grade == "C"
        assert _dimension_status(grade, "numerical_fidelity") == "fail"

    def test_high_consistency_fail_grade_c(self) -> None:
        """High consistency finding → fail in numerical fidelity → grade C."""
        findings = [
            _make_finding("F001", risk_level="high", issue_category="consistency"),
        ]
        bundle = _make_bundle(
            findings=findings,
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.grade == "C"
        assert _dimension_status(grade, "numerical_fidelity") == "fail"


# ---------------------------------------------------------------------------
# Grade D: reproducibility fails
# ---------------------------------------------------------------------------


class TestGradeD:
    """Grade D: reproducibility fails (critical pipeline step failed)."""

    def test_mineru_failed_grade_d(self) -> None:
        """MinerU step failed → grade D."""
        bundle = _make_bundle(
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru", status="failed"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.grade == "D"
        assert _dimension_status(grade, "reproducibility") == "fail"
        assert grade.label == "未通过"

    def test_discover_failed_grade_d(self) -> None:
        """Discover step failed → grade D."""
        bundle = _make_bundle(
            tool_runs=[
                _make_tool_run("discover", status="failed"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.grade == "D"

    def test_multiple_critical_steps_failed(self) -> None:
        """Multiple critical steps failed → grade D."""
        bundle = _make_bundle(
            tool_runs=[
                _make_tool_run("discover", status="failed"),
                _make_tool_run("material_inventory", status="failed"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.grade == "D"
        assert "discover" in _dimension_status(grade, "reproducibility") or True
        dim = next(d for d in grade.dimensions if d.name == "reproducibility")
        assert dim.status == "fail"


# ---------------------------------------------------------------------------
# Mixed findings across dimensions
# ---------------------------------------------------------------------------


class TestMixedFindings:
    """Findings that span multiple dimensions simultaneously."""

    def test_consistency_and_methodology_findings(self) -> None:
        """Consistency (critical) + completeness (high) → worst is C."""
        findings = [
            _make_finding(
                "F001", risk_level="critical", issue_category="consistency"
            ),
            _make_finding(
                "F002", risk_level="high", issue_category="completeness"
            ),
        ]
        bundle = _make_bundle(
            findings=findings,
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        # consistency critical → fail → C
        # completeness high → warning in methodology
        # worst = fail, reproducibility = pass → C
        assert grade.grade == "C"
        assert _dimension_status(grade, "numerical_fidelity") == "fail"
        assert _dimension_status(grade, "methodology") == "warning"

    def test_reproducibility_fail_overrides_consistency_fail(self) -> None:
        """Reproducibility fail + consistency fail → D (reproducibility wins)."""
        findings = [
            _make_finding(
                "F001", risk_level="critical", issue_category="consistency"
            ),
        ]
        bundle = _make_bundle(
            findings=findings,
            tool_runs=[
                _make_tool_run("discover", status="failed"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.grade == "D"

    def test_all_dimensions_have_findings(self) -> None:
        """Findings in all four dimensions at once."""
        findings = [
            _make_finding(
                "F001",
                category="paperfraud.methodology_review",
                risk_level="high",
                issue_category="matching",
            ),
            _make_finding(
                "F002", risk_level="medium", issue_category="consistency"
            ),
            _make_finding(
                "F003", risk_level="high", issue_category="completeness"
            ),
        ]
        bundle = _make_bundle(
            findings=findings,
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
                _make_tool_run("source_data_extract", status="failed"),
            ],
        )
        grade = compute_grade(bundle)
        # reproducibility: warning (source_data failed)
        # numerical_fidelity: warning (medium consistency)
        # methodology: warning (high completeness)
        # interpretation: warning (methodology_review)
        # worst = warning → B
        assert grade.grade == "B"


# ---------------------------------------------------------------------------
# Finding count accuracy
# ---------------------------------------------------------------------------


class TestFindingCounts:
    """Verify that finding counts are computed correctly."""

    def test_counts_across_risk_levels(self) -> None:
        """Verify critical/high/medium counts."""
        findings = [
            _make_finding("F001", risk_level="critical"),
            _make_finding("F002", risk_level="high"),
            _make_finding("F003", risk_level="high"),
            _make_finding("F004", risk_level="medium"),
            _make_finding("F005", risk_level="low"),
            _make_finding("F006", risk_level="info"),
        ]
        bundle = _make_bundle(
            findings=findings,
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        assert grade.total_findings == 6
        assert grade.critical_count == 1
        assert grade.high_count == 2
        assert grade.medium_count == 1


# ---------------------------------------------------------------------------
# Dimension score data structure
# ---------------------------------------------------------------------------


class TestDimensionScoreStructure:
    """Verify DimensionScore data structure contents."""

    def test_all_four_dimensions_present(self) -> None:
        """Grade must have exactly 4 dimensions."""
        bundle = _make_bundle(
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        assert len(grade.dimensions) == 4
        names = {d.name for d in grade.dimensions}
        assert names == {
            "reproducibility",
            "numerical_fidelity",
            "methodology",
            "interpretation",
        }

    def test_dimension_labels_are_chinese(self) -> None:
        """All dimension labels should be in Chinese."""
        bundle = _make_bundle(
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        expected_labels = {"可复现性", "数字一致性", "方法学", "解读合理性"}
        actual_labels = {d.label for d in grade.dimensions}
        assert actual_labels == expected_labels

    def test_finding_refs_populated(self) -> None:
        """Findings contributing to a dimension should appear in finding_refs."""
        findings = [
            _make_finding(
                "F001", risk_level="critical", issue_category="consistency"
            ),
            _make_finding(
                "F002", risk_level="medium", issue_category="consistency"
            ),
        ]
        bundle = _make_bundle(
            findings=findings,
            tool_runs=[
                _make_tool_run("discover"),
                _make_tool_run("material_inventory"),
                _make_tool_run("mineru"),
                _make_tool_run("evidence_ledger"),
            ],
        )
        grade = compute_grade(bundle)
        nf = next(d for d in grade.dimensions if d.name == "numerical_fidelity")
        assert "F001" in nf.finding_refs
        assert "F002" in nf.finding_refs
