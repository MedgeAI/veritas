"""Unit tests for PaperFraud knowledge base adapter."""

from __future__ import annotations

from engine.static_audit.adapters.paperfraud_knowledge import (
    PaperFraudRule,
    RuleMatch,
    load_knowledge_base,
    match_rules,
    summarize_matches,
    _check_study_type,
)


def test_load_knowledge_base_returns_48_rules() -> None:
    """All 6 YAML files should produce exactly 48 rules."""
    rules = load_knowledge_base()
    assert len(rules) == 48


def test_load_knowledge_base_rule_fields() -> None:
    """Every rule must have id, category, severity, and rule_type."""
    rules = load_knowledge_base()
    for rule in rules:
        assert rule.id, f"Rule missing id: {rule}"
        assert rule.category, f"Rule {rule.id} missing category"
        assert rule.severity in {"red", "orange", "yellow", "green"}, (
            f"Rule {rule.id} has unknown severity: {rule.severity}"
        )
        assert rule.rule_type in {"methodology_review", "fraud_detection"}, (
            f"Rule {rule.id} has unknown rule_type: {rule.rule_type}"
        )


def test_match_rules_with_rct_text() -> None:
    """RCT-related keywords should trigger relevant rules."""
    rules = load_knowledge_base()
    text = (
        "We conducted a randomized controlled trial with 200 participants. "
        "Statistical significance was assessed using p-value < 0.05. "
        "Multiple comparisons were corrected using Bonferroni method."
    )
    matches = match_rules(rules, paper_full_text=text)
    triggered = [m for m in matches if m.triggered]
    assert len(triggered) > 0, "Expected at least one rule to trigger for RCT text"
    # All triggered matches should have evidence
    for m in triggered:
        assert m.evidence, f"Rule {m.rule.id} triggered but has no evidence"


def test_match_rules_empty_text() -> None:
    """Empty text should not trigger any rules."""
    rules = load_knowledge_base()
    matches = match_rules(rules, paper_full_text="")
    triggered = [m for m in matches if m.triggered]
    assert len(triggered) == 0


def test_negative_triggers_suppress_false_positive() -> None:
    """Rules with negative triggers should not fire when the negative pattern is present."""
    rule = PaperFraudRule(
        id="test_rule",
        category="test",
        severity="yellow",
        detection={
            "triggers": {
                "keywords": ["p-value"],
            },
            "negative_triggers": ["not applicable"],
        },
        evidence_template="Found: {excerpt}",
    )
    # Without negative trigger → should trigger
    matches = match_rules([rule], paper_full_text="The p-value was significant.")
    assert matches[0].triggered

    # With negative trigger → should NOT trigger
    matches = match_rules([rule], paper_full_text="The p-value was not applicable here.")
    assert not matches[0].triggered


def test_summarize_matches_handles_unknown_severity() -> None:
    """Unknown severity levels should not crash summarize_matches."""
    rule_normal = PaperFraudRule(id="r1", category="test", severity="red")
    rule_unknown = PaperFraudRule(id="r2", category="test", severity="purple")

    matches = [
        RuleMatch(rule=rule_normal, triggered=True, evidence="found"),
        RuleMatch(rule=rule_unknown, triggered=True, evidence="found"),
    ]
    summary = summarize_matches(matches)

    assert summary["total_triggered"] == 2
    assert summary["red_count"] == 1
    # "purple" severity should appear in by_severity without crashing
    assert "purple" in summary["by_severity"]
    assert len(summary["by_severity"]["purple"]) == 1


def test_summarize_matches_empty() -> None:
    """Empty matches should produce zero counts."""
    summary = summarize_matches([])
    assert summary["total_rules_loaded"] == 0
    assert summary["total_triggered"] == 0
    assert summary["red_count"] == 0


def test_check_study_type_experimental_not_too_broad() -> None:
    """'experimental' should not match generic 'cell' mentions."""
    # "T cells" is generic biology language, not an experimental design indicator
    assert not _check_study_type("experimental", "We analyzed T cells from patients.")
    # But "cell line" or "cell culture" should match
    assert _check_study_type("experimental", "We used HEK293 cell line for transfection.")
    assert _check_study_type("experimental", "Primary cell culture was established from mouse tissue.")
    assert _check_study_type("experimental", "Experiments were performed in vivo.")


def test_check_study_type_rct() -> None:
    """RCT patterns should match standard clinical trial language."""
    assert _check_study_type("rct", "This was a randomized controlled trial.")
    assert _check_study_type("rct", "Patients were enrolled in a clinical trial.")
    assert not _check_study_type("rct", "This observational study examined trends.")


def test_generate_reviewer_form() -> None:
    """Reviewer form should have one row per rule."""
    from engine.static_audit.adapters.paperfraud_knowledge import generate_reviewer_form

    rules = load_knowledge_base()
    form = generate_reviewer_form(rules)
    assert len(form) == len(rules)
    assert all("rule_id" in row for row in form)
    assert all("score" in row for row in form)
