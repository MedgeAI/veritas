"""Tests for grade_engine.py tier cap logic."""

import pytest

from engine.static_audit.grade_engine import compute_grade


class TestComputeGradeBase:
    """Test base grade computation without tier cap."""

    def test_no_findings_returns_a(self):
        result = compute_grade([])
        assert result['grade'] == 'A'
        assert result['base_grade'] == 'A'
        assert result['tier_capped'] is False

    def test_only_info_findings_returns_b(self):
        findings = [{'risk_level': 'info'}, {'risk_level': 'info'}]
        result = compute_grade(findings)
        assert result['grade'] == 'B'
        assert result['base_grade'] == 'B'

    def test_only_low_findings_returns_c(self):
        findings = [{'risk_level': 'low'}, {'risk_level': 'info'}]
        result = compute_grade(findings)
        assert result['grade'] == 'C'
        assert result['base_grade'] == 'C'

    def test_medium_findings_returns_c_minus(self):
        findings = [{'risk_level': 'medium'}, {'risk_level': 'low'}]
        result = compute_grade(findings)
        assert result['grade'] == 'C-'
        assert result['base_grade'] == 'C-'

    def test_high_findings_returns_d(self):
        findings = [{'risk_level': 'high'}, {'risk_level': 'medium'}]
        result = compute_grade(findings)
        assert result['grade'] == 'D'
        assert result['base_grade'] == 'D'

    def test_critical_findings_returns_f(self):
        findings = [{'risk_level': 'critical'}, {'risk_level': 'high'}]
        result = compute_grade(findings)
        assert result['grade'] == 'F'
        assert result['base_grade'] == 'F'

    def test_missing_risk_level_defaults_to_info(self):
        findings = [{'other_field': 'value'}]
        result = compute_grade(findings)
        assert result['grade'] == 'B'


class TestTierCapEnforcement:
    """Test reproducibility tier cap logic."""

    def test_full_tier_no_cap_on_a(self):
        """Full tier allows max grade A."""
        result = compute_grade([], reproducibility_tier='full')
        assert result['grade'] == 'A'
        assert result['base_grade'] == 'A'
        assert result['tier_capped'] is False
        assert result['reproducibility_tier'] == 'full'

    def test_partial_tier_caps_a_to_b(self):
        """Partial tier caps A to B."""
        result = compute_grade([], reproducibility_tier='partial')
        assert result['grade'] == 'B'
        assert result['base_grade'] == 'A'
        assert result['tier_capped'] is True
        assert result['reproducibility_tier'] == 'partial'

    def test_code_only_tier_caps_a_to_c(self):
        """Code-only tier caps A to C."""
        result = compute_grade([], reproducibility_tier='code_only')
        assert result['grade'] == 'C'
        assert result['base_grade'] == 'A'
        assert result['tier_capped'] is True
        assert result['reproducibility_tier'] == 'code_only'

    def test_static_tier_caps_a_to_c_minus(self):
        """Static tier caps A to C-."""
        result = compute_grade([], reproducibility_tier='static')
        assert result['grade'] == 'C-'
        assert result['base_grade'] == 'A'
        assert result['tier_capped'] is True
        assert result['reproducibility_tier'] == 'static'

    def test_partial_tier_no_cap_on_c(self):
        """Partial tier does not cap grades worse than B."""
        findings = [{'risk_level': 'medium'}]  # base grade C-
        result = compute_grade(findings, reproducibility_tier='partial')
        assert result['grade'] == 'C-'
        assert result['base_grade'] == 'C-'
        assert result['tier_capped'] is False
        assert result['reproducibility_tier'] == 'partial'

    def test_code_only_tier_no_cap_on_d(self):
        """Code-only tier does not cap grades worse than C."""
        findings = [{'risk_level': 'high'}]  # base grade D
        result = compute_grade(findings, reproducibility_tier='code_only')
        assert result['grade'] == 'D'
        assert result['base_grade'] == 'D'
        assert result['tier_capped'] is False
        assert result['reproducibility_tier'] == 'code_only'

    def test_static_tier_caps_b_to_c_minus(self):
        """Static tier caps B to C-."""
        findings = [{'risk_level': 'info'}]  # base grade B
        result = compute_grade(findings, reproducibility_tier='static')
        assert result['grade'] == 'C-'
        assert result['base_grade'] == 'B'
        assert result['tier_capped'] is True

    def test_static_tier_no_cap_on_f(self):
        """Static tier does not cap F (already worse than C-)."""
        findings = [{'risk_level': 'critical'}]  # base grade F
        result = compute_grade(findings, reproducibility_tier='static')
        assert result['grade'] == 'F'
        assert result['base_grade'] == 'F'
        assert result['tier_capped'] is False

    def test_unknown_tier_no_cap(self):
        """Unknown tier does not apply any cap."""
        result = compute_grade([], reproducibility_tier='unknown_tier')
        assert result['grade'] == 'A'
        assert result['base_grade'] == 'A'
        assert result['tier_capped'] is False
        assert result['reproducibility_tier'] is None

    def test_none_tier_no_cap(self):
        """None tier does not apply any cap."""
        result = compute_grade([], reproducibility_tier=None)
        assert result['grade'] == 'A'
        assert result['base_grade'] == 'A'
        assert result['tier_capped'] is False
        assert result['reproducibility_tier'] is None


class TestSummaryMessages:
    """Test summary message generation."""

    def test_summary_tier_capped(self):
        """Summary explains tier cap."""
        result = compute_grade([], reproducibility_tier='partial')
        assert 'Base grade A capped to B' in result['summary']
        assert 'partial' in result['summary']

    def test_summary_no_cap(self):
        """Summary explains grade within tier."""
        findings = [{'risk_level': 'medium'}]
        result = compute_grade(findings, reproducibility_tier='partial')
        assert 'within tier' in result['summary']

    def test_summary_no_tier(self):
        """Summary explains grade from findings."""
        result = compute_grade([])
        assert 'computed from findings' in result['summary']


class TestAllTierGradeCombinations:
    """Parametrized tests for all tier × grade combinations."""

    @pytest.mark.parametrize(
        'tier,max_grade',
        [
            ('full', 'A'),
            ('partial', 'B'),
            ('code_only', 'C'),
            ('static', 'C-'),
        ],
    )
    def test_tier_allows_grade_at_max(self, tier, max_grade):
        """Each tier allows grades at or worse than its max."""
        # Create findings that would produce exactly the max grade
        if max_grade == 'A':
            findings = []
        elif max_grade == 'B':
            findings = [{'risk_level': 'info'}]
        elif max_grade == 'C':
            findings = [{'risk_level': 'low'}]
        elif max_grade == 'C-':
            findings = [{'risk_level': 'medium'}]

        result = compute_grade(findings, reproducibility_tier=tier)
        assert result['grade'] == max_grade
        assert result['tier_capped'] is False

    @pytest.mark.parametrize(
        'tier,max_grade',
        [
            ('partial', 'B'),
            ('code_only', 'C'),
            ('static', 'C-'),
        ],
    )
    def test_tier_caps_better_grades(self, tier, max_grade):
        """Each tier (except full) caps grades better than its max."""
        # Empty findings produce grade A, which should be capped
        result = compute_grade([], reproducibility_tier=tier)
        assert result['grade'] == max_grade
        assert result['base_grade'] == 'A'
        assert result['tier_capped'] is True
