"""CBIR (Content-Based Image Retrieval) search endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from ..cbir_service import search_similar_panels, search_similar_by_image_upload
from ..dependencies import AppDependencies, get_app_dependencies

router = APIRouter(prefix="/cbir", tags=["cbir"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class CbirSearchRequest(BaseModel):
    """Request body for CBIR similarity search."""

    panel_id: str
    case_id: str | None = None
    top_k: int = Field(default=20, ge=1, le=500)
    threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    label: str | None = None


class SimilarPanel(BaseModel):
    """A single panel returned by CBIR search."""

    case_id: str
    panel_id: str
    figure_id: str | None = None
    image_path: str = ""
    similarity: float
    label: str = ""


class CbirSearchResponse(BaseModel):
    """Response body for CBIR similarity search."""

    query_panel_id: str
    query_case_id: str | None = None
    threshold: float
    total_candidates: int = 0
    similar_panels: list[SimilarPanel] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/search", response_model=CbirSearchResponse)
async def cbir_search(
    body: CbirSearchRequest,
    deps: AppDependencies = Depends(get_app_dependencies),
) -> CbirSearchResponse:
    """Find panels similar to *panel_id* using SSCD embeddings.

    Supports cross-case search (omit ``case_id``) or single-case search
    (provide ``case_id``).  Optionally filter results by panel label.
    """
    if deps._session_factory is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_unavailable",
                "detail": "database not configured",
            },
        )

    session = deps._session_factory()
    try:
        # Build an artifact resolver that returns the latest workdir for a case.
        artifact_resolver = None
        if body.label is not None:

            def _resolve(case_id: str) -> Any:
                return deps.artifacts.latest_workdir(case_id)

            artifact_resolver = _resolve

        result = search_similar_panels(
            session,
            body.panel_id,
            case_id=body.case_id,
            top_k=body.top_k,
            threshold=body.threshold,
            label=body.label,
            artifact_resolver=artifact_resolver,
        )
    finally:
        session.close()

    return CbirSearchResponse(**result)


@router.get("/search/by-panel")
async def cbir_search_by_label(
    case_id: str,
    label: str,
    top_k: int = 20,
    threshold: float = 0.85,
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Find all panels in *case_id* whose label contains *label*.

    This is a convenience endpoint for label-based browsing without a
    query panel.  Returns matching panels with their embedding status.
    """
    from ..models import ImageEmbeddingModel

    if deps._session_factory is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_unavailable",
                "detail": "database not configured",
            },
        )

    # Resolve labels before opening the embedding DB session. This avoids
    # nested sessions on the same engine, which is unnecessary here and can
    # exhaust lightweight PGlite connection pools in tests.
    workdir = deps.artifacts.latest_workdir(case_id)
    panel_labels: dict[str, str] = {}
    if workdir is not None:
        from ..cbir_service import _read_panel_evidence

        panel_doc = _read_panel_evidence(workdir)
        if panel_doc:
            for panel in panel_doc.get("panels") or []:
                pid = str(panel.get("panel_id", ""))
                lbl = str(panel.get("label", ""))
                if pid:
                    panel_labels[pid] = lbl

    session = deps._session_factory()
    try:
        embeddings = (
            session.query(ImageEmbeddingModel)
            .filter(ImageEmbeddingModel.case_id == case_id)
            .all()
        )

        label_lower = label.lower()
        matches: list[dict[str, Any]] = []
        for row in embeddings:
            panel_label = panel_labels.get(row.panel_id, "")
            if label_lower in panel_label.lower():
                matches.append(
                    {
                        "panel_id": row.panel_id,
                        "figure_id": row.figure_id,
                        "image_path": row.image_path,
                        "label": panel_label,
                        "has_embedding": row.embedding is not None,
                    }
                )

        matches.sort(key=lambda m: m["panel_id"])
        return {
            "case_id": case_id,
            "label_filter": label,
            "match_count": len(matches),
            "panels": matches[:top_k],
        }
    finally:
        session.close()


@router.post("/search/upload", response_model=CbirSearchResponse)
async def cbir_search_by_upload(
    file: UploadFile = File(..., description="Image file to search for similar panels"),
    case_id: str | None = None,
    top_k: int = 20,
    threshold: float = 0.85,
    label: str | None = None,
    deps: AppDependencies = Depends(get_app_dependencies),
) -> CbirSearchResponse:
    """Find panels similar to an uploaded image using SSCD embeddings.

    Upload an image file (JPEG/PNG) and find visually similar panels in the
    indexed database. Supports cross-case search (omit ``case_id``) or
    single-case search (provide ``case_id``). Optionally filter results by
    panel label.
    """
    if deps._session_factory is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_unavailable",
                "detail": "database not configured",
            },
        )

    # Validate file type
    if file.content_type not in {"image/jpeg", "image/png", "image/jpg"}:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_file_type",
                "detail": f"unsupported image type: {file.content_type}",
            },
        )

    # Read image bytes
    try:
        image_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "file_read_failed", "detail": str(exc)},
        )

    session = deps._session_factory()
    try:
        # Build an artifact resolver for label filtering
        artifact_resolver = None
        if label is not None:

            def _resolve(case_id: str) -> Any:
                return deps.artifacts.latest_workdir(case_id)

            artifact_resolver = _resolve

        result = search_similar_by_image_upload(
            session,
            image_bytes,
            case_id=case_id,
            top_k=top_k,
            threshold=threshold,
            label=label,
            artifact_resolver=artifact_resolver,
        )

        # Check for errors
        if "error" in result:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "embedding_extraction_failed",
                    "detail": result["error"],
                },
            )

        # Map result to response model
        return CbirSearchResponse(
            query_panel_id="uploaded_image",
            query_case_id=case_id,
            threshold=result["threshold"],
            total_candidates=result["total_candidates"],
            similar_panels=[SimilarPanel(**p) for p in result["similar_panels"]],
        )
    finally:
        session.close()
