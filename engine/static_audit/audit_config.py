from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from engine.shared import PROJECT_ROOT

CONFIG_PATH = PROJECT_ROOT / "configs" / "audit_roles.yaml"

DEFAULT_AUDIT_ROLE_CONFIG: dict[str, Any] = {
    "role_timeouts": {
        "agent_material_plan": 120,
        "agent_plan": 180,
        "source_data_auditor": 300,
        "judge": 180,
        "agent_review": 180,
    },
    "provenance_edge_threshold": 0.85,
    "provenance_max_relationships": 30,
    "priority_scoring": {
        "cross_sheet_fractional_tail_reuse": {
            "min_consecutive_matches": 5,
            "min_decimal_places": 5,
            "review_priority": "high",
        },
        "repeated_measurement_value": {
            "min_repeats": 3,
            "min_decimal_places": 4,
            "review_priority": "high",
        },
        "fractional_tail_reuse": {
            "min_decimal_places": 5,
            "review_priority": "medium",
        },
        "small_n_fixed_difference": {"review_priority": "medium"},
        "small_n_fixed_ratio": {"review_priority": "medium"},
        "low_information_numeric": {"review_priority": "low", "filter": True},
    },
}

_VALID_PRIORITIES = {"critical", "high", "medium", "low"}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _validate_config(config: dict[str, Any]) -> None:
    role_timeouts = config.get("role_timeouts")
    if not isinstance(role_timeouts, dict):
        raise ValueError("configs/audit_roles.yaml role_timeouts must be a mapping")
    for role, timeout in role_timeouts.items():
        if not isinstance(role, str) or not isinstance(timeout, int) or timeout <= 0:
            raise ValueError(f"invalid role timeout for {role!r}: {timeout!r}")

    threshold = config.get("provenance_edge_threshold")
    if not isinstance(threshold, int | float) or not 0 <= float(threshold) <= 1:
        raise ValueError("provenance_edge_threshold must be between 0 and 1")

    max_relationships = config.get("provenance_max_relationships")
    if not isinstance(max_relationships, int) or max_relationships <= 0:
        raise ValueError("provenance_max_relationships must be a positive integer")

    scoring = config.get("priority_scoring")
    if not isinstance(scoring, dict):
        raise ValueError("priority_scoring must be a mapping")
    for category, rules in scoring.items():
        if not isinstance(category, str) or not isinstance(rules, dict):
            raise ValueError(f"invalid priority_scoring entry: {category!r}")
        priority = rules.get("review_priority")
        if priority is not None and priority not in _VALID_PRIORITIES:
            raise ValueError(
                f"invalid review_priority for {category}: {priority!r}"
            )


@lru_cache(maxsize=1)
def load_audit_role_config() -> dict[str, Any]:
    """Load fail-loud audit tuning config shared by agents and tools."""
    raw: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("configs/audit_roles.yaml must contain a mapping")
        raw = loaded
    config = _deep_merge(DEFAULT_AUDIT_ROLE_CONFIG, raw)
    _validate_config(config)
    return config


def resolve_role_timeout(role_id: str, fallback: int) -> int:
    timeouts = load_audit_role_config().get("role_timeouts") or {}
    value = timeouts.get(role_id)
    return int(value) if isinstance(value, int) and value > 0 else fallback


def priority_scoring_config() -> dict[str, dict[str, Any]]:
    scoring = load_audit_role_config().get("priority_scoring") or {}
    return {
        str(category): dict(rules)
        for category, rules in scoring.items()
        if isinstance(rules, dict)
    }


def provenance_relationship_config() -> tuple[float, int]:
    config = load_audit_role_config()
    return (
        float(config["provenance_edge_threshold"]),
        int(config["provenance_max_relationships"]),
    )
