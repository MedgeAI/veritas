"""Embedding indexing pipeline for Veritas.

Core engine-level module that extracts SSCD embeddings from panel images and
persists them to a vector store.  Designed to be DB-backend agnostic: a
``EmbeddingStore`` protocol isolates the indexing logic from SQLAlchemy ORM,
making the pipeline testable with an in-memory fake and reusable from both
the CLI and the Web P1 service.

Pipeline stages:
  1. ``collect_panel_evidence`` — read panel_evidence.json, resolve image paths.
  2. ``EmbeddingIndexer.run``  — call the encoder in batches, bulk-upsert into
     the store, track progress.
  3. ``get_index_status`` / ``update_index_job_status`` — query/mutate the
     job status record.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from engine.embeddings.sscd import BatchResult, ProgressCallback, SSCDEncoder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PanelRecord:
    """A single panel resolved from panel_evidence.json."""

    panel_id: str
    figure_id: str
    image_path: Path
    relative_path: str  # relative to workdir, used for storage


@dataclass
class IndexResult:
    """Outcome of an indexing run.

    ``status`` is one of:
      ``completed``    — all panels encoded and stored.
      ``partial``      — some panels failed (image load or encode error).
      ``failed``       — no panels were successfully indexed.
      ``no_panels``    — panel_evidence.json was empty or missing.
    """

    status: str
    indexed_count: int = 0
    expected_count: int = 0
    failure_category: str | None = None
    detail: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class IndexStatus:
    """Snapshot of the current indexing state for a case."""

    case_id: str
    status: str  # "not_indexed" | "queued" | "running" | "completed" | "failed" | "indexed"
    indexed_count: int = 0
    expected_count: int | None = None
    detail: str = ""
    last_indexed_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str | None = None


# ---------------------------------------------------------------------------
# Store protocol — the seam between engine and persistence
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingStore(Protocol):
    """Persistence contract for embedding records.

    Implementations may back onto SQLAlchemy/PostgreSQL+pgvector, SQLite+JSON,
    or an in-memory dict for tests.  The indexer never touches ORM classes
    directly.
    """

    def bulk_upsert(
        self,
        case_id: str,
        records: list[dict[str, Any]],
    ) -> int:
        """Insert or update embedding records.  Returns the number upserted."""
        ...

    def count(self, case_id: str) -> int:
        """Return how many embeddings exist for this case."""
        ...

    def latest_indexed_at(self, case_id: str) -> str | None:
        """Return the most recent ``indexed_at`` timestamp, or ``None``."""
        ...


@runtime_checkable
class JobStore(Protocol):
    """Persistence contract for indexing job status records."""

    def upsert(
        self,
        case_id: str,
        status: str,
        *,
        indexed_count: int = 0,
        expected_count: int | None = None,
        detail: str = "",
    ) -> dict[str, Any]:
        """Insert or update the job record.  Returns the record as a dict."""
        ...

    def get(self, case_id: str) -> dict[str, Any] | None:
        """Return the job record for *case_id*, or ``None``."""
        ...


# ---------------------------------------------------------------------------
# Panel evidence collection
# ---------------------------------------------------------------------------


def collect_panel_evidence(workdir: Path) -> tuple[list[PanelRecord], str | None]:
    """Read panel_evidence.json and return resolved panel records.

    Returns ``(records, error_detail)``.  If *error_detail* is not ``None``,
    the list is empty and the caller should treat it as a terminal failure.
    """
    panel_doc = _read_panel_evidence(workdir)
    if panel_doc is None:
        return [], "required artifact missing: panel_evidence.json"

    panels = panel_doc.get("panels") or []
    if not panels:
        return [], None  # no panels is not an error — just nothing to do

    records: list[PanelRecord] = []
    for panel in panels:
        panel_id = str(panel.get("panel_id", ""))
        figure_id = str(panel.get("parent_figure_id", ""))
        crop_path = panel.get("crop_path", "")
        if not crop_path or not panel_id:
            continue
        full_path = workdir / crop_path
        if not full_path.exists():
            logger.debug("panel image missing: %s", full_path)
            continue
        records.append(PanelRecord(
            panel_id=panel_id,
            figure_id=figure_id,
            image_path=full_path,
            relative_path=crop_path,
        ))

    return records, None


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------


class EmbeddingIndexer:
    """Orchestrates the full embedding indexing pipeline.

    Parameters
    ----------
    case_id:
        Identifier for the paper/case being indexed.
    workdir:
        Root directory containing ``panel_evidence.json`` and panel images.
    encoder:
        An :class:`SSCDEncoder` instance (or any object with a compatible
        ``encode_batch`` method).
    embedding_store:
        Persistence backend for embedding vectors.
    job_store:
        Persistence backend for job status records.
    batch_size:
        Number of images per encoder forward pass.
    progress:
        Optional callback for progress reporting.
    """

    def __init__(
        self,
        case_id: str,
        workdir: Path,
        encoder: SSCDEncoder,
        embedding_store: EmbeddingStore,
        job_store: JobStore | None = None,
        *,
        batch_size: int = 32,
        progress: ProgressCallback | None = None,
    ) -> None:
        self._case_id = case_id
        self._workdir = workdir
        self._encoder = encoder
        self._embedding_store = embedding_store
        self._job_store = job_store
        self._batch_size = batch_size
        self._progress = progress

    def run(self) -> IndexResult:
        """Execute the full indexing pipeline.

        1. Collect panel evidence.
        2. Encode images in batches.
        3. Bulk-upsert embeddings.
        4. Return structured result.
        """
        start = time.monotonic()

        # Stage 1: collect panel evidence
        records, error = collect_panel_evidence(self._workdir)
        if error is not None:
            result = IndexResult(
                status="failed",
                failure_category="artifact_missing",
                detail=error,
                elapsed_seconds=_elapsed(start),
            )
            self._update_job(result)
            return result

        if not records:
            result = IndexResult(
                status="no_panels",
                detail="panel_evidence.json contained no usable panels",
                elapsed_seconds=_elapsed(start),
            )
            self._update_job(result)
            return result

        expected_count = len(records)

        # Check encoder availability
        if not self._encoder.available:
            result = IndexResult(
                status="failed",
                failure_category="environment",
                expected_count=expected_count,
                detail=f"SSCD model not found at {self._encoder._model_path}",
                elapsed_seconds=_elapsed(start),
            )
            self._update_job(result)
            return result

        # Mark as running
        if self._job_store:
            self._job_store.upsert(
                self._case_id, "running",
                expected_count=expected_count,
                detail="SSCD embedding extraction running",
            )

        # Stage 2: encode
        image_paths = [r.image_path for r in records]
        batch_result: BatchResult = self._encoder.encode_batch_detailed(
            image_paths,
            batch_size=self._batch_size,
            progress=self._progress,
        )

        # Stage 3: build upsert records
        upsert_records: list[dict[str, Any]] = []
        for record, embedding in zip(records, batch_result.embeddings):
            if embedding is None:
                continue
            upsert_records.append({
                "panel_id": record.panel_id,
                "figure_id": record.figure_id,
                "image_path": record.relative_path,
                "embedding": embedding,
                "indexed_at": _utc_now(),
            })

        # Stage 4: bulk upsert
        indexed_count = 0
        if upsert_records:
            try:
                indexed_count = self._embedding_store.bulk_upsert(
                    self._case_id, upsert_records
                )
            except Exception as exc:
                logger.exception("bulk upsert failed for case %s", self._case_id)
                result = IndexResult(
                    status="failed",
                    failure_category="db_write_failed",
                    indexed_count=0,
                    expected_count=expected_count,
                    detail=f"database write failed: {exc}",
                    elapsed_seconds=_elapsed(start),
                )
                self._update_job(result)
                return result

        # Stage 5: build result
        result = _build_result(indexed_count, expected_count, batch_result, start)
        self._update_job(result)
        return result

    def _update_job(self, result: IndexResult) -> None:
        """Push the IndexResult into the job store, if one is configured."""
        if self._job_store is None:
            return
        status = result.status
        # Map "no_panels" to a completed job — nothing to do is not a failure
        if status == "no_panels":
            status = "completed"
        self._job_store.upsert(
            self._case_id,
            status,
            indexed_count=result.indexed_count,
            expected_count=result.expected_count,
            detail=result.detail,
        )


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


def get_index_status(
    case_id: str,
    embedding_store: EmbeddingStore,
    job_store: JobStore | None = None,
) -> IndexStatus:
    """Return the current indexing status for a case."""
    count = embedding_store.count(case_id)
    last_ts = embedding_store.latest_indexed_at(case_id)

    status = IndexStatus(
        case_id=case_id,
        status="indexed" if count > 0 else "not_indexed",
        indexed_count=count,
        last_indexed_at=last_ts,
    )

    if job_store:
        job = job_store.get(case_id)
        if job:
            status.status = job.get("status", status.status)
            status.indexed_count = job.get("indexed_count", count)
            status.expected_count = job.get("expected_count")
            status.detail = job.get("detail", "")
            status.started_at = job.get("started_at")
            status.completed_at = job.get("completed_at")
            status.updated_at = job.get("updated_at")
            # If there are embeddings and job says completed, prefer "indexed"
            if count > 0 and status.status in {"completed", "indexed"}:
                status.status = "indexed"

    return status


def update_index_job_status(
    case_id: str,
    status: str,
    job_store: JobStore,
    *,
    indexed_count: int = 0,
    expected_count: int | None = None,
    detail: str = "",
) -> dict[str, Any]:
    """Convenience wrapper around ``JobStore.upsert``."""
    return job_store.upsert(
        case_id,
        status,
        indexed_count=indexed_count,
        expected_count=expected_count,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_result(
    indexed_count: int,
    expected_count: int,
    batch_result: BatchResult,
    start: float,
) -> IndexResult:
    """Derive an :class:`IndexResult` from encoding and upsert outcomes."""
    elapsed = _elapsed(start)

    if indexed_count == 0:
        return IndexResult(
            status="failed",
            failure_category="image_load_failed",
            indexed_count=0,
            expected_count=expected_count,
            detail=f"failed to load or encode all {expected_count} panel images",
            elapsed_seconds=elapsed,
        )

    if indexed_count < expected_count:
        return IndexResult(
            status="partial",
            failure_category="partial_image_load_failed",
            indexed_count=indexed_count,
            expected_count=expected_count,
            detail=f"indexed {indexed_count} of {expected_count} panel images",
            elapsed_seconds=elapsed,
        )

    return IndexResult(
        status="completed",
        indexed_count=indexed_count,
        expected_count=expected_count,
        elapsed_seconds=elapsed,
    )


def _read_panel_evidence(workdir: Path) -> dict[str, Any] | None:
    """Read panel_evidence.json, trying the canonical mapped path then legacy."""
    try:
        from engine.static_audit.paths import resolve_artifact_path
        mapped = resolve_artifact_path(workdir, "panel_evidence.json")
        if mapped.exists():
            return json.loads(mapped.read_text(encoding="utf-8"))
    except ImportError:
        pass

    legacy = workdir / "panel_evidence.json"
    if legacy.exists():
        return json.loads(legacy.read_text(encoding="utf-8"))
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _elapsed(start: float) -> float:
    return round(time.monotonic() - start, 2)
