from __future__ import annotations

from engine.static_audit.audit_config import (
    priority_scoring_config,
    provenance_relationship_config,
    resolve_role_timeout,
)


def test_audit_roles_config_loads_role_timeouts() -> None:
    assert resolve_role_timeout("agent_plan", 999) == 180
    assert resolve_role_timeout("unknown_role", 999) == 999


def test_audit_roles_config_loads_thresholds_and_priority() -> None:
    threshold, max_items = provenance_relationship_config()
    assert threshold == 0.85
    assert max_items == 30
    assert (
        priority_scoring_config()["cross_sheet_fractional_tail_reuse"][
            "review_priority"
        ]
        == "high"
    )
