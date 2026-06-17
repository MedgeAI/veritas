"""SSCD embedding extraction and similarity search.

Uses Meta's SSCD (Self-Supervised Copy Detection) model to extract
512-dimensional embeddings from panel images.  Embeddings are stored
in the ``image_embeddings`` table.  The current Web P1 implementation
stores vectors as JSON and performs bounded brute-force cosine search;
pgvector can replace this storage/query layer when the production DB
schema stabilises.

Model reference: https://github.com/facebookresearch/sscd
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SSCD Model Wrapper
# ---------------------------------------------------------------------------

class SSCDEncoder:
    """Lazy-loading SSCD TorchScript model for batch embedding extraction.

    The model is loaded on first call to ``encode_batch`` and cached
    for subsequent calls.  Images are preprocessed (resize 224×224,
    ImageNet normalization) and embeddings are L2-normalized.
    """

    def __init__(self, model_path: str | Path | None = None) -> None:
        self._model = None
        self._model_path = Path(model_path) if model_path else _default_model_path()
        self._device = "cpu"  # Will use CUDA if available

    @property
    def available(self) -> bool:
        """Check if the SSCD model file exists and can be loaded."""
        return self._model_path.exists()

    def encode_batch(
        self,
        image_paths: list[Path],
        batch_size: int = 32,
    ) -> list[list[float] | None]:
        """Extract 512-dim L2-normalized embeddings for a batch of images.

        Returns one item per input path.  Unreadable images are represented
        as ``None`` so callers can distinguish partial failure from success.
        """
        import torch
        import torchvision.transforms as T
        from PIL import Image

        self._ensure_loaded()
        assert self._model is not None

        preprocess = T.Compose([
            T.Resize(224),
            T.CenterCrop(224),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

        all_embeddings: list[list[float] | None] = []

        for i in range(0, len(image_paths), batch_size):
            batch_paths = image_paths[i:i + batch_size]
            tensors = []
            tensor_positions: list[int] = []
            batch_outputs: list[list[float] | None] = [None] * len(batch_paths)
            for position, p in enumerate(batch_paths):
                try:
                    img = Image.open(p).convert("RGB")
                    tensors.append(preprocess(img))
                    tensor_positions.append(position)
                except Exception as exc:
                    logger.debug("failed to load image for SSCD embedding %s: %s", p, exc)
                    continue

            if not tensors:
                all_embeddings.extend(batch_outputs)
                continue

            batch_tensor = torch.stack(tensors).to(self._device)
            with torch.no_grad():
                embeddings = self._model(batch_tensor)
                # L2 normalize
                embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)

            encoded = embeddings.cpu().tolist()
            for position, embedding in zip(tensor_positions, encoded):
                batch_outputs[position] = embedding
            all_embeddings.extend(batch_outputs)

        return all_embeddings

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch
        if torch.cuda.is_available():
            self._device = "cuda"
        self._model = torch.jit.load(str(self._model_path), map_location=self._device)
        self._model.eval()


def _default_model_path() -> Path:
    """Return the default SSCD model path, checking common locations."""
    candidates = [
        Path("models/sscd/sscd_disc_mixup.torchscript.pt"),
        Path.home() / ".cache" / "veritas" / "sscd_disc_mixup.torchscript.pt",
        Path("/opt/veritas/models/sscd_disc_mixup.torchscript.pt"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]  # Return first as default (may not exist)


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def index_panels(
    db: Session,
    case_id: str,
    workdir: Path,
    encoder: SSCDEncoder,
) -> dict[str, Any]:
    """Extract SSCD embeddings for all panels in a case and store in DB.

    Reads panel_evidence.json to get panel image paths, runs the SSCD
    model on each, and UPSERTs the embeddings into image_embeddings.

    Returns a status dict with indexed count and timing.
    """
    import time

    from .models import ImageEmbeddingModel

    start = time.time()

    # Read panel evidence
    panel_doc = _read_panel_evidence(workdir)
    if not panel_doc:
        return {
            "status": "failed",
            "failure_category": "artifact_missing",
            "indexed_count": 0,
            "elapsed_seconds": 0,
            "detail": "required artifact missing: panel_evidence.json",
        }

    panels = panel_doc.get("panels") or []
    if not panels:
        return {"status": "no_panels", "indexed_count": 0, "elapsed_seconds": 0}

    # Resolve image paths
    image_paths: list[tuple[str, str, Path]] = []  # (panel_id, figure_id, path)
    for panel in panels:
        panel_id = str(panel.get("panel_id", ""))
        figure_id = str(panel.get("parent_figure_id", ""))
        crop_path = panel.get("crop_path", "")
        if not crop_path or not panel_id:
            continue
        full_path = workdir / crop_path
        if full_path.exists():
            image_paths.append((panel_id, figure_id, full_path))

    if not image_paths:
        return {
            "status": "failed",
            "failure_category": "no_valid_images",
            "indexed_count": 0,
            "elapsed_seconds": time.time() - start,
            "detail": "panel evidence contained no existing crop paths",
        }

    # Check if encoder is available
    if not encoder.available:
        return {
            "status": "failed",
            "failure_category": "environment",
            "indexed_count": 0,
            "elapsed_seconds": time.time() - start,
            "detail": f"SSCD model not found at {encoder._model_path}",
        }

    # Extract embeddings
    paths_only = [p for _, _, p in image_paths]
    embeddings = encoder.encode_batch(paths_only)

    # UPSERT to database
    indexed = 0
    for (panel_id, figure_id, _path), embedding in zip(image_paths, embeddings):
        if embedding is None:
            continue
        # Check if already exists
        existing = (
            db.query(ImageEmbeddingModel)
            .filter(
                ImageEmbeddingModel.case_id == case_id,
                ImageEmbeddingModel.panel_id == panel_id,
            )
            .first()
        )
        if existing:
            existing.embedding = embedding
            existing.figure_id = figure_id
            existing.image_path = str(_path.relative_to(workdir))
            existing.indexed_at = _utc_now()
        else:
            db.add(ImageEmbeddingModel(
                case_id=case_id,
                panel_id=panel_id,
                figure_id=figure_id,
                image_path=str(_path.relative_to(workdir)),
                embedding=embedding,
                indexed_at=_utc_now(),
            ))
        indexed += 1

    db.commit()

    expected_count = len(image_paths)
    if indexed == 0:
        return {
            "status": "failed",
            "failure_category": "image_load_failed",
            "indexed_count": 0,
            "expected_count": expected_count,
            "elapsed_seconds": round(time.time() - start, 2),
            "detail": f"failed to load or encode all {expected_count} panel images",
        }
    if indexed < expected_count:
        return {
            "status": "partial",
            "failure_category": "partial_image_load_failed",
            "indexed_count": indexed,
            "expected_count": expected_count,
            "elapsed_seconds": round(time.time() - start, 2),
            "detail": f"indexed {indexed} of {expected_count} panel images",
        }

    return {
        "status": "completed",
        "indexed_count": indexed,
        "expected_count": expected_count,
        "elapsed_seconds": round(time.time() - start, 2),
    }


def get_index_status(db: Session, case_id: str) -> dict[str, Any]:
    """Return indexing status for a case."""
    from .models import EmbeddingIndexJobModel, ImageEmbeddingModel

    count = (
        db.query(ImageEmbeddingModel)
        .filter(ImageEmbeddingModel.case_id == case_id)
        .count()
    )
    latest = (
        db.query(ImageEmbeddingModel)
        .filter(ImageEmbeddingModel.case_id == case_id)
        .order_by(ImageEmbeddingModel.indexed_at.desc())
        .first()
    )
    status = {
        "case_id": case_id,
        "indexed_count": count,
        "last_indexed_at": latest.indexed_at if latest else None,
        "status": "indexed" if count > 0 else "not_indexed",
    }
    job = db.get(EmbeddingIndexJobModel, case_id)
    if job:
        status.update({
            "status": job.status,
            "job_status": job.status,
            "expected_count": job.expected_count,
            "detail": job.detail or "",
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "updated_at": job.updated_at,
        })
        if count > 0 and job.status in {"completed", "indexed"}:
            status["status"] = "indexed"
    return status


def update_index_job(
    db: Session,
    case_id: str,
    status: str,
    *,
    indexed_count: int = 0,
    expected_count: int | None = None,
    detail: str = "",
) -> dict[str, Any]:
    """Upsert the latest SSCD indexing job status for a case."""
    from .models import EmbeddingIndexJobModel

    now = _utc_now()
    job = db.get(EmbeddingIndexJobModel, case_id)
    if job is None:
        job = EmbeddingIndexJobModel(case_id=case_id)
        db.add(job)
    job.status = status
    job.indexed_count = indexed_count
    job.expected_count = expected_count
    job.detail = detail
    job.updated_at = now
    if status in {"queued", "running"} and not job.started_at:
        job.started_at = now
    if status not in {"queued", "running"}:
        job.completed_at = now
    db.commit()
    db.refresh(job)
    return job.to_dict()


# ---------------------------------------------------------------------------
# Similarity Search
# ---------------------------------------------------------------------------

def query_similar(
    db: Session,
    case_id: str,
    panel_id: str,
    top_k: int = 20,
    threshold: float = 0.85,
) -> list[dict[str, Any]]:
    """Find panels similar to the given panel using cosine similarity.

    Uses pgvector's cosine distance operator for PostgreSQL.
    Falls back to brute-force Python computation for SQLite.
    """
    from .models import ImageEmbeddingModel

    # Get the query embedding
    query_embedding_row = (
        db.query(ImageEmbeddingModel)
        .filter(
            ImageEmbeddingModel.case_id == case_id,
            ImageEmbeddingModel.panel_id == panel_id,
        )
        .first()
    )
    if not query_embedding_row or not query_embedding_row.embedding:
        return []

    query_embedding = query_embedding_row.embedding

    # Get all embeddings for this case
    all_embeddings = (
        db.query(ImageEmbeddingModel)
        .filter(
            ImageEmbeddingModel.case_id == case_id,
            ImageEmbeddingModel.panel_id != panel_id,
        )
        .all()
    )

    # Compute cosine similarity (brute force — works for both SQLite and PostgreSQL)
    results: list[dict[str, Any]] = []
    for row in all_embeddings:
        if not row.embedding:
            continue
        similarity = _cosine_similarity(query_embedding, row.embedding)
        if similarity >= threshold:
            results.append({
                "panel_id": row.panel_id,
                "figure_id": row.figure_id,
                "image_path": row.image_path,
                "similarity": round(similarity, 4),
            })

    # Sort by similarity descending
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]


def query_all_similar_pairs(
    db: Session,
    case_id: str,
    threshold: float = 0.85,
) -> list[dict[str, Any]]:
    """Find all pairs of similar panels above the threshold.

    Returns a list of {source_panel_id, target_panel_id, similarity} dicts.
    Each pair is returned only once (source < target alphabetically).
    """
    from .models import ImageEmbeddingModel

    all_embeddings = (
        db.query(ImageEmbeddingModel)
        .filter(ImageEmbeddingModel.case_id == case_id)
        .all()
    )

    if len(all_embeddings) < 2:
        return []

    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for i, row_a in enumerate(all_embeddings):
        if not row_a.embedding:
            continue
        for row_b in all_embeddings[i + 1:]:
            if not row_b.embedding:
                continue
            # Ensure consistent ordering
            key = tuple(sorted([row_a.panel_id, row_b.panel_id]))
            if key in seen:
                continue
            seen.add(key)

            similarity = _cosine_similarity(row_a.embedding, row_b.embedding)
            if similarity >= threshold:
                # Source is the one that comes first alphabetically
                if row_a.panel_id <= row_b.panel_id:
                    source, target = row_a, row_b
                else:
                    source, target = row_b, row_a
                pairs.append({
                    "source_panel_id": source.panel_id,
                    "target_panel_id": target.panel_id,
                    "source_figure_id": source.figure_id,
                    "target_figure_id": target.figure_id,
                    "similarity": round(similarity, 4),
                })

    pairs.sort(key=lambda x: x["similarity"], reverse=True)
    return pairs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Assumes vectors are already L2-normalized (so dot product = cosine).
    """
    if len(a) != len(b):
        return 0.0
    # For L2-normalized vectors, dot product equals cosine similarity
    return sum(x * y for x, y in zip(a, b))


def _read_panel_evidence(workdir: Path) -> dict[str, Any] | None:
    """Read panel_evidence.json, trying mapped path then legacy."""
    from engine.static_audit.paths import resolve_artifact_path

    mapped = resolve_artifact_path(workdir, "panel_evidence.json")
    if mapped.exists():
        return json.loads(mapped.read_text(encoding="utf-8"))
    legacy = workdir / "panel_evidence.json"
    if legacy.exists():
        return json.loads(legacy.read_text(encoding="utf-8"))
    return None


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
