"""Visual forensics pipeline orchestration for Veritas static audit.

Split from a single module into a package. All public names are re-exported
here so that existing imports continue to work.
"""

from __future__ import annotations

from engine.static_audit.visual_pipeline._orchestrator import (
    run_image_quality_detection,
    run_overlap_reuse_detection,
    run_provenance_graph,
)
from engine.static_audit.visual_pipeline.finding_pipeline import (
    run_visual_finding_pipeline,
)
from engine.static_audit.visual_pipeline.panel_extraction import (
    extract_panels_batch,
    run_visual_panel_extraction,
)
from engine.static_audit.visual_pipeline.sila_dense import (
    run_sila_dense_detection,
)
from engine.static_audit.visual_pipeline.tru_for import (
    run_tru_for_detection,
)

__all__ = [
    "extract_panels_batch",
    "run_image_quality_detection",
    "run_overlap_reuse_detection",
    "run_provenance_graph",
    "run_sila_dense_detection",
    "run_tru_for_detection",
    "run_visual_finding_pipeline",
    "run_visual_panel_extraction",
]
