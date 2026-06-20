"""Shared SSCD embedding extraction and indexing for Veritas.

Provides :class:`SSCDEncoder` for both the CLI audit pipeline and the Web P1
service, plus the engine-level :class:`EmbeddingIndexer` pipeline for writing
embeddings to a vector store.
"""

from engine.embeddings.indexer import (
    EmbeddingIndexer,
    EmbeddingStore,
    IndexResult,
    IndexStatus,
    JobStore,
    PanelRecord,
    collect_panel_evidence,
    get_index_status,
    update_index_job_status,
)
from engine.embeddings.sscd import BatchResult, DiskCacheBackend, SSCDEncoder

__all__ = [
    "BatchResult",
    "DiskCacheBackend",
    "EmbeddingIndexer",
    "EmbeddingStore",
    "IndexResult",
    "IndexStatus",
    "JobStore",
    "PanelRecord",
    "SSCDEncoder",
    "collect_panel_evidence",
    "get_index_status",
    "update_index_job_status",
]
