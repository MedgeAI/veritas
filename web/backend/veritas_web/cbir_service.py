"""CBIR (Content-Based Image Retrieval) search service.

Provides cross-case and single-case panel similarity search using
SSCD embeddings stored in the ``image_embeddings`` table.  Extends
the case-scoped ``query_similar`` in ``embeddings.py`` with:

* Cross-case search (query one panel, find matches in all cases).
* Label-based filtering via ``panel_evidence.json``.
* Structured result model suitable for the ``/api/cbir/search`` endpoint.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def search_similar_panels(
    db: Session,
    panel_id: str,
    *,
    case_id: str | None = None,
    top_k: int = 20,
    threshold: float = 0.85,
    label: str | None = None,
    artifact_resolver: Any = None,
) -> dict[str, Any]:
    """Find panels similar to *panel_id* using cosine similarity.

    Parameters
    ----------
    db:
        SQLAlchemy session.
    panel_id:
        The panel to use as the query.
    case_id:
        If given, restrict the search scope to this single case.
        Otherwise search across all indexed cases.
    top_k:
        Maximum number of results to return.
    threshold:
        Minimum cosine similarity (0–1).
    label:
        If given, only return results whose panel label (from
        ``panel_evidence.json``) contains this substring (case-insensitive).
    artifact_resolver:
        Optional callable ``(case_id) -> Path | None`` that returns the
        audit workdir for a case.  Required for label filtering.

    Returns
    -------
    dict with ``query_panel_id``, ``query_case_id``, ``threshold``,
    ``total_candidates``, and ``similar_panels`` list.
    """
    from .embeddings import _cosine_similarity
    from .models import ImageEmbeddingModel

    # Locate the query panel embedding.
    query_filters = [ImageEmbeddingModel.panel_id == panel_id]
    if case_id is not None:
        query_filters.append(ImageEmbeddingModel.case_id == case_id)

    query_row = (
        db.query(ImageEmbeddingModel)
        .filter(*query_filters)
        .first()
    )
    if query_row is None or not query_row.embedding:
        return {
            "query_panel_id": panel_id,
            "query_case_id": case_id,
            "threshold": threshold,
            "total_candidates": 0,
            "similar_panels": [],
        }

    query_embedding = query_row.embedding
    query_case = query_row.case_id

    # Build candidate set.
    candidate_query = db.query(ImageEmbeddingModel).filter(
        ImageEmbeddingModel.panel_id != panel_id,
    )
    if case_id is not None:
        candidate_query = candidate_query.filter(
            ImageEmbeddingModel.case_id == case_id,
        )

    # When label filtering is active we must resolve labels per-case,
    # so collect candidates grouped by case_id.
    if label is not None and artifact_resolver is not None:
        label_lower = label.lower()
        label_cache: dict[str, dict[str, str]] = {}

        all_candidates = candidate_query.all()
        # Group by case
        by_case: dict[str, list[Any]] = {}
        for row in all_candidates:
            by_case.setdefault(row.case_id, []).append(row)

        results: list[dict[str, Any]] = []
        for cid, rows in by_case.items():
            panel_labels = _get_panel_labels(cid, artifact_resolver, label_cache)
            for row in rows:
                if not row.embedding:
                    continue
                panel_label = panel_labels.get(row.panel_id, "")
                if label_lower not in panel_label.lower():
                    continue
                similarity = _cosine_similarity(query_embedding, row.embedding)
                if similarity >= threshold:
                    results.append(_format_result(row, similarity, panel_label))
    else:
        all_candidates = candidate_query.all()
        results = []
        for row in all_candidates:
            if not row.embedding:
                continue
            similarity = _cosine_similarity(query_embedding, row.embedding)
            if similarity >= threshold:
                results.append(_format_result(row, similarity))

    results.sort(key=lambda r: r["similarity"], reverse=True)
    total = len(results)
    results = results[:top_k]

    return {
        "query_panel_id": panel_id,
        "query_case_id": query_case,
        "threshold": threshold,
        "total_candidates": total,
        "similar_panels": results,
    }


def _format_result(
    row: Any,
    similarity: float,
    label: str = "",
) -> dict[str, Any]:
    return {
        "case_id": row.case_id,
        "panel_id": row.panel_id,
        "figure_id": row.figure_id,
        "image_path": row.image_path,
        "similarity": round(similarity, 4),
        "label": label,
    }


def _get_panel_labels(
    case_id: str,
    artifact_resolver: Any,
    cache: dict[str, dict[str, str]],
) -> dict[str, str]:
    """Return a panel_id -> label map for *case_id*, with caching."""
    if case_id in cache:
        return cache[case_id]

    workdir = artifact_resolver(case_id)
    labels: dict[str, str] = {}
    if workdir is not None:
        panel_doc = _read_panel_evidence(workdir)
        if panel_doc:
            for panel in panel_doc.get("panels") or []:
                pid = str(panel.get("panel_id", ""))
                lbl = str(panel.get("label", ""))
                if pid:
                    labels[pid] = lbl

    cache[case_id] = labels
    return labels


def _read_panel_evidence(workdir: Path) -> dict[str, Any] | None:
    """Read panel_evidence.json from *workdir*."""
    try:
        from engine.static_audit.paths import resolve_artifact_path

        mapped = resolve_artifact_path(workdir, "panel_evidence.json")
        if mapped.exists():
            return json.loads(mapped.read_text(encoding="utf-8"))
    except Exception:
        pass

    legacy = workdir / "panel_evidence.json"
    if legacy.exists():
        try:
            return json.loads(legacy.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def search_similar_by_image_upload(
    db: Session,
    image_bytes: bytes,
    *,
    case_id: str | None = None,
    top_k: int = 20,
    threshold: float = 0.85,
    label: str | None = None,
    artifact_resolver: Any = None,
    encoder: Any = None,
) -> dict[str, Any]:
    """Find panels similar to an uploaded image using SSCD embeddings.

    Parameters
    ----------
    db:
        SQLAlchemy session.
    image_bytes:
        Raw image bytes (JPEG/PNG).
    case_id:
        If given, restrict the search scope to this single case.
        Otherwise search across all indexed cases.
    top_k:
        Maximum number of results to return.
    threshold:
        Minimum cosine similarity (0–1).
    label:
        If given, only return results whose panel label contains this substring.
    artifact_resolver:
        Optional callable ``(case_id) -> Path | None`` for label filtering.
    encoder:
        SSCDEncoder instance. If None, creates a default one.

    Returns
    -------
    dict with ``query_source`` ("upload"), ``threshold``, ``total_candidates``,
    and ``similar_panels`` list.
    """
    import tempfile
    from pathlib import Path

    from engine.embeddings.sscd import SSCDEncoder
    from .embeddings import _cosine_similarity
    from .models import ImageEmbeddingModel

    # Create encoder if not provided
    if encoder is None:
        encoder = SSCDEncoder()

    if not encoder.available:
        return {
            "query_source": "upload",
            "threshold": threshold,
            "total_candidates": 0,
            "similar_panels": [],
            "error": "SSCD model not available",
        }

    # Write uploaded image to a temporary file
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = Path(tmp.name)

    try:
        # Extract embedding from uploaded image
        embeddings = encoder.encode_batch([tmp_path])
        if not embeddings or embeddings[0] is None:
            return {
                "query_source": "upload",
                "threshold": threshold,
                "total_candidates": 0,
                "similar_panels": [],
                "error": "failed to extract embedding from uploaded image",
            }

        query_embedding = embeddings[0]

        # Build candidate set
        candidate_query = db.query(ImageEmbeddingModel)
        if case_id is not None:
            candidate_query = candidate_query.filter(
                ImageEmbeddingModel.case_id == case_id,
            )

        candidates = candidate_query.all()

        # Compute similarities
        results: list[dict[str, Any]] = []
        for row in candidates:
            if not row.embedding:
                continue
            similarity = _cosine_similarity(query_embedding, row.embedding)
            if similarity >= threshold:
                results.append({
                    "case_id": row.case_id,
                    "panel_id": row.panel_id,
                    "figure_id": row.figure_id,
                    "image_path": row.image_path,
                    "similarity": round(similarity, 4),
                    "label": "",
                })

        # Sort by similarity descending
        results.sort(key=lambda x: x["similarity"], reverse=True)
        results = results[:top_k]

        # Apply label filtering if requested
        if label is not None and artifact_resolver is not None and results:
            label_lower = label.lower()
            label_cache: dict[str, dict[str, str]] = {}
            filtered: list[dict[str, Any]] = []
            for r in results:
                labels = _get_panel_labels(r["case_id"], artifact_resolver, label_cache)
                panel_label = labels.get(r["panel_id"], "")
                if label_lower in panel_label.lower():
                    r["label"] = panel_label
                    filtered.append(r)
            results = filtered

        return {
            "query_source": "upload",
            "threshold": threshold,
            "total_candidates": len(results),
            "similar_panels": results,
        }
    finally:
        # Clean up temporary file
        tmp_path.unlink(missing_ok=True)
