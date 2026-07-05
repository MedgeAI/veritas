"""Evidence window builder: bounded, reproducible evidence reconstruction.

Per PRD WP6, provides locator-based window rebuilding from raw XLSX/CSV
without storing large blobs. Original file hash mismatch -> fail loud.
"""

from engine.static_audit.evidence_windows.locator import EvidenceLocator
from engine.static_audit.evidence_windows.manifest import EvidenceWindowManifest
from engine.static_audit.evidence_windows.window_builder import (
    EvidenceWindowError,
    build_window,
    build_window_from_locator,
)

__all__ = [
    "EvidenceLocator",
    "EvidenceWindowManifest",
    "EvidenceWindowError",
    "build_window",
    "build_window_from_locator",
]
