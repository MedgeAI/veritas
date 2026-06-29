"""Stage modules for the static audit pipeline.

Each stage encapsulates one phase of the audit pipeline.  The orchestrator
in ``pipeline.py`` calls them sequentially, passing results forward.
"""

from engine.static_audit.stages import (
    discovery,
    investigation,
    mineru,
    planning,
    report,
    roles,
    source_data,
    visual,
)

__all__ = [
    "discovery",
    "planning",
    "mineru",
    "source_data",
    "visual",
    "investigation",
    "roles",
    "report",
]
