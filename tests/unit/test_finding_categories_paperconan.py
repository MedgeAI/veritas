"""Validation tests for PaperConan detector finding categories (WP4).

Verifies the 9 new PaperConan detector categories are registered correctly
and carry the required metadata fields.

See PRD "Veritas-数值取证设计哲学吸收PRD-paperconan.md" §WP4.
"""

from __future__ import annotations

import pytest

from engine.static_audit.finding_categories import (
    FindingCategoryDefinition,
    all_definitions,
    get,
    pair_forensics_categories,
    source_data_pattern_keys,
)


# The 9 new PaperConan detector categories
PAPERCONAN_CATEGORIES = [
    "grim_inconsistent",
    "grimmer_inconsistent",
    "last_digit_chi_square",
    "row_pair_digit_coupling",
    "integer_diff_shared_fraction",
    "partial_constant_offset",
    "cross_sheet_decimal_tail_reuse",
    "within_table_fraction_reuse",
    "recurring_row_vector",
]

# GRIM/GRIMMER require applicability_premise gating text in review_question
GRIM_FAMILY = ["grim_inconsistent", "grimmer_inconsistent"]


def test_all_37_categories_registered():
    """All 37 categories (28 original + 9 PaperConan) are registered."""
    categories = [d.category for d in all_definitions()]
    assert len(categories) == 37
    for cat in PAPERCONAN_CATEGORIES:
        assert cat in categories, f"Missing PaperConan category: {cat}"


def test_all_paperconan_categories_registered_individually():
    """Each PaperConan category is individually retrievable via get()."""
    for cat in PAPERCONAN_CATEGORIES:
        defn = get(cat)
        assert defn is not None, f"get({cat!r}) returned None"
        assert isinstance(defn, FindingCategoryDefinition)


def test_paperconan_categories_have_required_fields():
    """All PaperConan categories have required metadata fields."""
    for cat in PAPERCONAN_CATEGORIES:
        defn = get(cat)
        assert defn.category == cat
        assert defn.label, f"{cat} missing label"
        assert defn.pattern_key, f"{cat} missing pattern_key"
        assert defn.id_prefix, f"{cat} missing id_prefix"
        assert defn.review_question, f"{cat} missing review_question"
        assert defn.issue_category in {"consistency", "matching", "completeness"}, (
            f"{cat} has invalid issue_category: {defn.issue_category}"
        )


def test_paperconan_id_prefixes_are_unique():
    """Each PaperConan category has a distinct id_prefix."""
    prefixes = [get(cat).id_prefix for cat in PAPERCONAN_CATEGORIES]
    assert len(prefixes) == len(set(prefixes)), f"Duplicate prefixes: {prefixes}"


def test_paperconan_pattern_keys_match_category():
    """Each PaperConan category has pattern_key == category (no grouping alias)."""
    for cat in PAPERCONAN_CATEGORIES:
        defn = get(cat)
        assert defn.pattern_key == cat, (
            f"{cat} pattern_key mismatch: {defn.pattern_key!r} != {cat!r}"
        )


def test_grim_family_applicability_premise_gating():
    """GRIM/GRIMMER review_question mentions integer-valued premise gating.

    PRD WP4: GRIM/GRIMMER 仅在 integer-valued premise 成立或待确认时进入复核，
    不可对连续测量下确定结论。
    """
    for cat in GRIM_FAMILY:
        defn = get(cat)
        rq = defn.review_question
        assert "integer" in rq.lower() or "整数" in rq, (
            f"{cat} review_question must mention integer-valued premise: {rq!r}"
        )
        assert "不可" in rq or "不得" in rq, (
            f"{cat} review_question must include negative constraint: {rq!r}"
        )


def test_paperconan_categories_are_not_pair_forensics():
    """PaperConan detector categories are not pair forensics.

    They originate from PaperConan scan, not from Veritas pair forensics pipeline.
    """
    pair_cats = pair_forensics_categories()
    for cat in PAPERCONAN_CATEGORIES:
        assert cat not in pair_cats, (
            f"{cat} should not be in pair_forensics_categories()"
        )
        defn = get(cat)
        assert defn.is_pair_forensics is False


def test_paperconan_categories_not_in_source_data_patterns():
    """PaperConan categories are not flagged as source_data_patterns.

    They flow through PaperConan translator, not the native source-data pipeline.
    """
    sd_keys = source_data_pattern_keys()
    for cat in PAPERCONAN_CATEGORIES:
        assert cat not in sd_keys, (
            f"{cat} should not be in source_data_pattern_keys()"
        )


def test_paperconan_categories_issue_category_consistency():
    """All PaperConan detector categories default to issue_category='consistency'.

    These are numeric consistency checks (GRIM math, digit distribution,
    copy-paste fingerprints), not matching or completeness.
    """
    for cat in PAPERCONAN_CATEGORIES:
        defn = get(cat)
        assert defn.issue_category == "consistency", (
            f"{cat} should be consistency, got {defn.issue_category!r}"
        )


def test_paperconan_categories_context_only_false():
    """All PaperConan categories are substantive (context_only=False).

    These are real detector signals, not informational footnotes.
    """
    for cat in PAPERCONAN_CATEGORIES:
        defn = get(cat)
        assert defn.context_only is False, (
            f"{cat} should not be context_only"
        )


# ---- Synthetic fixture: simulate a finding dict and verify category lookup ----


@pytest.mark.parametrize("category", PAPERCONAN_CATEGORIES)
def test_synthetic_finding_resolves_to_category(category: str):
    """A finding dict with the given category resolves to the registered definition."""
    finding = {"category": category, "risk_level": "high"}
    defn = get(finding["category"])
    assert defn is not None
    assert defn.category == category
    assert defn.label
    assert defn.id_prefix
    assert defn.review_question


@pytest.mark.parametrize("category", GRIM_FAMILY)
def test_grim_family_synthetic_finding_has_premise_warning(category: str):
    """GRIM/GRIMMER synthetic findings must carry integer-valued premise warning."""
    finding = {
        "category": category,
        "risk_level": "high",
        "applicability_premise": {"requires_integer_valued_items": True},
    }
    defn = get(finding["category"])
    rq = defn.review_question
    # The review question must warn about the integer-valued premise constraint
    assert "整数" in rq or "integer" in rq.lower()
    # The review question must forbid concluding against continuous measurements
    assert "不可" in rq


def test_total_definition_count_after_wp4():
    """Total definition count is 37 after WP4 adds 9 PaperConan categories."""
    assert len(all_definitions()) == 37
