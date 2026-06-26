"""Pytest configuration for tests/unit/engine/.

Skip collection of llm tests due to package shadowing issue.
See review-fix-decisions.md for details.
"""
from __future__ import annotations

collect_ignore = ["llm"]
