"""Deterministic legitimate-relationship whitelist for twin scoring."""

from __future__ import annotations

from math import isclose
from typing import Any


def _label_text(finding: dict[str, Any]) -> str:
    labels = finding.get("column_labels") or finding.get("columns") or []
    if isinstance(labels, str):
        labels = [labels]
    return " ".join(str(label).lower() for label in labels)


def whitelist_reason(finding: dict[str, Any]) -> str | None:
    """Return the v1.1 whitelist reason for a benign deterministic relation."""
    text = _label_text(finding)
    category = str(finding.get("category", "")).lower()
    relationship = str(finding.get("relationship_value", "")).lower()

    if _looks_like_declared_difference_or_ratio(text):
        return "declared_difference_or_ratio_column"
    if _looks_like_exp_log_transform(text):
        return "exp_log_transform"
    if _looks_like_ci_estimate_relation(text):
        return "ci_estimate_relation"
    if _looks_like_p_from_stat_relation(text):
        return "p_from_stat_df"
    if _looks_like_chisq_z_squared(text, finding):
        return "chisq_z_squared"
    if category in {"fixed_difference", "fixed_ratio"} and relationship in {"0", "1"}:
        return "identity_or_zero_difference"
    return None


def filter_whitelisted_findings(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    for finding in findings:
        reason = whitelist_reason(finding)
        if reason:
            copy = dict(finding)
            copy["whitelist_reason"] = reason
            filtered.append(copy)
        else:
            kept.append(finding)
    return kept, filtered


def _looks_like_declared_difference_or_ratio(text: str) -> bool:
    return any(
        token in text
        for token in (
            "auc_diff",
            "auc diff",
            "auc difference",
            "difference",
            " diff",
            "ratio",
            "fold",
            "delta",
        )
    )


def _looks_like_exp_log_transform(text: str) -> bool:
    has_hr = "hr" in text or "hazard ratio" in text
    has_log = "loghr" in text or "log hr" in text or "log(" in text
    return has_hr and has_log


def _looks_like_ci_estimate_relation(text: str) -> bool:
    has_estimate = any(token in text for token in ("estimate", "est", "hr", "or"))
    has_ci = any(token in text for token in ("lci", "uci", "lower ci", "upper ci", "95% ci"))
    has_se = "se" in text or "std. error" in text or "standard error" in text
    return has_estimate and has_ci and has_se


def _looks_like_p_from_stat_relation(text: str) -> bool:
    has_p = "p" in text or "p.value" in text or "p-value" in text
    has_stat = any(token in text for token in (" t ", " z ", "stat", "chisq", "chi"))
    has_df = "df" in text
    return has_p and has_stat and has_df


def _looks_like_chisq_z_squared(text: str, finding: dict[str, Any]) -> bool:
    if "chisq" not in text and "chi" not in text:
        return False
    if "z" not in text:
        return False
    samples = finding.get("sample_pairs") or []
    for sample in samples[:5]:
        left = sample.get("left")
        right = sample.get("right")
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            if isclose(left, right * right, rel_tol=1e-6, abs_tol=1e-9) or isclose(
                right, left * left, rel_tol=1e-6, abs_tol=1e-9
            ):
                return True
    return True
