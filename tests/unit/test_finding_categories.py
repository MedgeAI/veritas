"""Validation tests for FindingCategoryRegistry (WP5).

Validates all 28 categories end-to-end: registry registration, derived constants,
and consumer migration.

See PRD "Veritas-抽象层治理与架构演进-PRD.md" §WP5 契约 C.
"""

from __future__ import annotations

import pytest

from engine.static_audit.finding_categories import (
    FindingCategoryDefinition,
    all_definitions,
    get,
    pair_forensics_categories,
    register,
)


# ---- Registry registration tests ----


def test_all_28_categories_registered():
    """All 28 categories are registered in the registry."""
    categories = [d.category for d in all_definitions()]
    assert len(categories) == 28
    # Verify key categories from each group
    assert "repeated_measurement_value" in categories  # canary
    assert "row_offset_scalar_multiple" in categories  # pair forensics
    assert "duplicate_numeric_columns" in categories  # numeric
    assert "copy_move_single" in categories  # visual
    assert "paperfraud.methodology_review" in categories  # paperfraud


def test_register_duplicate_raises():
    """Duplicate registration raises ValueError."""
    defn = FindingCategoryDefinition(
        category="repeated_measurement_value",
        label="dup",
        pattern_key="dup",
        id_prefix="DUP",
        review_question="dup",
    )
    with pytest.raises(ValueError, match="Duplicate finding category"):
        register(defn)


# ---- CATEGORY_LABELS derivation tests ----


def test_category_labels_derived_from_registry():
    """CATEGORY_LABELS is derived from registry and contains all 28 labels."""
    from engine.static_audit.html_report._config import CATEGORY_LABELS

    assert len(CATEGORY_LABELS) == 28
    # Verify key labels
    assert CATEGORY_LABELS["repeated_measurement_value"] == "重复展示数值"
    assert CATEGORY_LABELS["duplicate_numeric_columns"] == "数值列重复"
    assert CATEGORY_LABELS["copy_move_single"] == "单图内局部相似"
    assert CATEGORY_LABELS["paperfraud.methodology_review"] == "方法学提示"


def test_no_hardcoded_category_labels_fallback():
    """_CATEGORY_LABELS_FALLBACK constant has been removed."""
    from engine.static_audit.html_report import _config

    assert not hasattr(_config, "_CATEGORY_LABELS_FALLBACK")


# ---- PAIR_FORENSICS_CATEGORIES derivation tests ----


def test_pair_forensics_categories_derived_from_registry():
    """PAIR_FORENSICS_CATEGORIES is derived from registry and contains 16 categories."""
    from engine.static_audit.html_report._config import PAIR_FORENSICS_CATEGORIES

    assert len(PAIR_FORENSICS_CATEGORIES) == 16
    # Verify key pair forensics categories
    assert "repeated_measurement_value" in PAIR_FORENSICS_CATEGORIES
    assert "row_offset_scalar_multiple" in PAIR_FORENSICS_CATEGORIES
    assert "binary_arithmetic_relation" in PAIR_FORENSICS_CATEGORIES
    # Verify non-pair categories are not included
    assert "copy_move_single" not in PAIR_FORENSICS_CATEGORIES
    assert "paperfraud.methodology_review" not in PAIR_FORENSICS_CATEGORIES


def test_pair_forensics_categories_function():
    """pair_forensics_categories() returns all 16 pair forensics categories."""
    result = pair_forensics_categories()
    assert len(result) == 16
    assert "repeated_measurement_value" in result
    assert "row_offset_scalar_multiple" in result


def test_no_hardcoded_pair_forensics_fallback():
    """_PAIR_FORENSICS_CATEGORIES_FALLBACK constant has been removed."""
    from engine.static_audit.html_report import _config

    assert not hasattr(_config, "_PAIR_FORENSICS_CATEGORIES_FALLBACK")


# ---- pattern_key_for_finding tests ----


def test_pattern_key_for_pair_forensics():
    """pattern_key_for_finding returns correct pattern_key for pair forensics."""
    from engine.static_audit.html_report._shared import pattern_key_for_finding

    # Test various pair forensics categories
    assert pattern_key_for_finding({"category": "repeated_measurement_value"}) == "repeated_measurement_value"
    assert pattern_key_for_finding({"category": "row_offset_scalar_multiple"}) == "paired_offset_ratio_reuse"
    assert pattern_key_for_finding({"category": "duplicate_row_vector"}) == "row_vector_reuse"
    assert pattern_key_for_finding({"category": "binary_arithmetic_relation"}) == "binary_arithmetic_relation"


def test_pattern_key_for_numeric_categories():
    """pattern_key_for_finding returns correct pattern_key for numeric categories."""
    from engine.static_audit.html_report._shared import pattern_key_for_finding

    assert pattern_key_for_finding({"category": "duplicate_numeric_columns"}) == "duplicate_numeric_columns"
    assert pattern_key_for_finding({"category": "fixed_difference"}) == "formula_derivation"
    assert pattern_key_for_finding({"category": "formula_derived_columns"}) == "formula_derivation"


def test_pattern_key_for_visual_categories():
    """pattern_key_for_finding returns correct pattern_key for visual categories."""
    from engine.static_audit.html_report._shared import pattern_key_for_finding

    # Visual categories map to visual_forensics via token matching
    assert pattern_key_for_finding({"category": "copy_move_single"}) == "visual_forensics"
    assert pattern_key_for_finding({"category": "exact_duplicate"}) == "visual_forensics"


def test_pattern_key_for_paperfraud_categories():
    """pattern_key_for_finding returns correct pattern_key for paperfraud categories."""
    from engine.static_audit.html_report._shared import pattern_key_for_finding

    # PaperFraud categories have their own pattern keys
    assert pattern_key_for_finding({"category": "paperfraud.methodology_review"}) == "paperfraud.methodology_review"
    assert pattern_key_for_finding({"category": "paperfraud.fraud_detection"}) == "paperfraud.fraud_detection"


# ---- assign_ids tests ----


def test_assign_ids_uses_registry_prefix():
    """assign_ids uses registry-defined id_prefix for all categories."""
    from engine.static_audit.tools.source_data_pair_forensics.review_tasks import (
        assign_ids,
    )

    # Test pair forensics categories
    findings = [
        {"category": "repeated_measurement_value", "risk_level": "high"},
        {"category": "row_offset_scalar_multiple", "risk_level": "medium"},
        {"category": "binary_arithmetic_relation", "risk_level": "high"},
    ]
    assign_ids(findings)
    assert findings[0]["finding_id"] == "RMV-0001"
    assert findings[1]["finding_id"] == "ROS-0001"
    assert findings[2]["finding_id"] == "BAR-0001"


# ---- _category_review_question tests ----


def test_category_review_question_returns_registered_text():
    """_category_review_question returns the registered review question."""
    from engine.static_audit.tools.source_data_pair_forensics.review_tasks import (
        _category_review_question,
    )

    # Test various categories
    defn_rmv = get("repeated_measurement_value")
    assert _category_review_question("repeated_measurement_value") == defn_rmv.review_question
    assert "独立样本" in _category_review_question("repeated_measurement_value")

    defn_ros = get("row_offset_scalar_multiple")
    assert _category_review_question("row_offset_scalar_multiple") == defn_ros.review_question
    assert "单位换算" in _category_review_question("row_offset_scalar_multiple")


# ---- Category attribute validation tests ----


def test_all_categories_have_required_fields():
    """All registered categories have required fields populated."""
    for defn in all_definitions():
        assert defn.category, f"Category missing category field"
        assert defn.label, f"Category {defn.category} missing label"
        assert defn.pattern_key, f"Category {defn.category} missing pattern_key"
        assert defn.id_prefix, f"Category {defn.category} missing id_prefix"
        assert defn.review_question, f"Category {defn.category} missing review_question"
        assert defn.issue_category in {"consistency", "matching", "completeness"}, \
            f"Category {defn.category} has invalid issue_category: {defn.issue_category}"


def test_pair_forensics_flag_consistency():
    """Categories with is_pair_forensics=True match PAIR_FORENSICS_CATEGORIES."""
    from engine.static_audit.html_report._config import PAIR_FORENSICS_CATEGORIES

    pair_categories = {d.category for d in all_definitions() if d.is_pair_forensics}
    assert pair_categories == PAIR_FORENSICS_CATEGORIES


def test_category_labels_completeness():
    """CATEGORY_LABELS contains all registered categories."""
    from engine.static_audit.html_report._config import CATEGORY_LABELS

    registered_categories = {d.category for d in all_definitions()}
    assert set(CATEGORY_LABELS.keys()) == registered_categories


# ---- Additional: get returns None for unregistered ----


def test_get_unregistered_returns_none():
    """get() returns None for unregistered categories (no exception)."""
    assert get("nonexistent_category_xyz") is None
