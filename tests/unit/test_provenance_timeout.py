from __future__ import annotations

from engine.static_audit.pipeline import resolve_audit_profile
from engine.static_audit.visual_pipeline._orchestrator import (
    _resolve_provenance_timeout,
)


def test_fast_profile_uses_practical_elis_timeout_floor() -> None:
    assert resolve_audit_profile("fast")["elis_timeout_seconds"] == 180


def test_provenance_timeout_scales_with_pair_count() -> None:
    timeout = _resolve_provenance_timeout(
        figure_count=103,
        configured_timeout=180,
    )

    assert timeout >= 270


def test_provenance_timeout_respects_full_profile_minimum() -> None:
    timeout = _resolve_provenance_timeout(
        figure_count=3,
        configured_timeout=300,
    )

    assert timeout == 300


def test_provenance_timeout_is_bounded() -> None:
    timeout = _resolve_provenance_timeout(
        figure_count=1000,
        configured_timeout=180,
    )

    assert timeout == 600
