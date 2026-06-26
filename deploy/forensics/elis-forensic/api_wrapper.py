"""ELIS Forensic Service — FastAPI HTTP wrapper for provenance analysis.

Wraps the existing provenance analysis logic (descriptor extraction,
pairwise matching, graph building) in an HTTP API.  The container stays
warm so descriptor extraction models and cached data persist across
requests.

This wrapper does NOT depend on CBIR.  It calls the provenance logic
directly — the same code path as the CLI ``provenance`` subcommand.

Endpoints:
    POST /provenance  — Full provenance analysis (descriptor → match → graph).
    GET  /health      — Liveness probe.

File I/O protocol:
    The service reads images from and writes results to a shared ``/data``
    bind mount.  The caller sends container-side paths (``/data/...``);
    the adapter translates host ↔ container paths before/after the call.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Ensure the provenance modules are importable.
# The base image has everything at /app/ (conda env provenance).
# ---------------------------------------------------------------------------
sys.path.insert(0, "/app")

from src.schemas import (
    DescriptorType,
    AlignmentStrategy,
    MatchingMethod,
    ProvenanceRequest,
)
from src.main import handle_provenance

from fastapi import FastAPI
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
)
logger = logging.getLogger("elis-forensic-service")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ELIS Forensic Provenance Service",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ImageInput(BaseModel):
    """An image available for provenance analysis."""

    id: str = Field(..., description="Unique image identifier")
    path: str = Field(..., description="Absolute path inside the container")
    label: str = Field("", description="Display label")
    is_query: bool = Field(False, description="Whether this is a query image")


class ProvenanceAnalysisRequest(BaseModel):
    """Request for provenance analysis — no CBIR dependency."""

    images: list[ImageInput] = Field(..., min_length=2)
    query_image_ids: list[str] | None = Field(
        None, description="Query image IDs; defaults to all images"
    )
    output_dir: str = Field(..., description="Output directory (container path)")

    # Descriptor parameters
    descriptor_type: str = Field("cv_rsift", description="Descriptor type")
    check_flip: bool = Field(True, description="Check flipped images")

    # Matching parameters
    alignment_strategy: str = Field("CV_MAGSAC", description="Geometric alignment")
    matching_method: str = Field("BF", description="Keypoint matching method")
    min_keypoints: int = Field(20, ge=4, description="Minimum matching keypoints")
    min_area: float = Field(0.01, ge=0.0, le=1.0, description="Min shared area")

    # Processing parameters
    parallel: bool = Field(True, description="Process pairs in parallel")
    max_workers: int = Field(4, ge=1, le=16, description="Max parallel workers")
    save_descriptors: bool = Field(True, description="Cache computed descriptors")


class ProvenanceAnalysisResponse(BaseModel):
    """Response from provenance analysis."""

    success: bool
    message: str = ""
    total_images: int = 0
    total_pairs_checked: int = 0
    matched_pairs_count: int = 0
    processing_time_seconds: float = 0.0
    graph: dict[str, Any] | None = None
    matched_pairs: list[dict[str, Any]] | None = None
    visualization_data: dict[str, Any] | None = None
    output_files: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/provenance", response_model=ProvenanceAnalysisResponse)
def provenance_analysis(req: ProvenanceAnalysisRequest) -> ProvenanceAnalysisResponse:
    """Full provenance analysis: descriptors → matching → graph."""
    # Convert our request schema to the internal ProvenanceRequest
    from src.schemas import ImageInfo

    query_ids = req.query_image_ids or [img.id for img in req.images]

    internal_images = [
        ImageInfo(
            id=img.id,
            path=img.path,
            label=img.label,
            is_query=img.id in query_ids,
        )
        for img in req.images
    ]

    internal_request = ProvenanceRequest(
        images=internal_images,
        query_image_ids=query_ids,
        descriptor_type=DescriptorType(req.descriptor_type),
        alignment_strategy=AlignmentStrategy(req.alignment_strategy),
        matching_method=MatchingMethod(req.matching_method),
        min_keypoints=req.min_keypoints,
        min_area=req.min_area,
        check_flip=req.check_flip,
        output_dir=req.output_dir,
        parallel=req.parallel,
        max_workers=req.max_workers,
        save_descriptors=req.save_descriptors,
    )

    try:
        response = handle_provenance(internal_request)
    except Exception as exc:
        logger.exception("Provenance analysis failed")
        return ProvenanceAnalysisResponse(
            success=False,
            message=f"Analysis failed: {exc}",
        )

    # Convert internal response to our HTTP response schema
    return ProvenanceAnalysisResponse(
        success=response.success,
        message=response.message,
        total_images=response.total_images,
        total_pairs_checked=response.total_pairs_checked,
        matched_pairs_count=response.matched_pairs_count,
        processing_time_seconds=response.processing_time_seconds,
        graph=response.graph.model_dump() if response.graph else None,
        matched_pairs=[mp.model_dump() for mp in response.matched_pairs]
        if response.matched_pairs
        else None,
        visualization_data=response.visualization_data,
        output_files=response.output_files,
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "healthy", "version": "1.0.0"}


# ---------------------------------------------------------------------------
# Entrypoint (for direct execution)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8771)
