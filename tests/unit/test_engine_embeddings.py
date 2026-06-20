"""Tests for engine/embeddings/ — SSCD encoder, cache, and indexer pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.embeddings.sscd import (
    BatchResult,
    DiskCacheBackend,
    SSCDEncoder,
    _cache_key,
)
from engine.embeddings.indexer import (
    EmbeddingIndexer,
    collect_panel_evidence,
    get_index_status,
    update_index_job_status,
)


# ---------------------------------------------------------------------------
# Helpers — fake stores and encoders
# ---------------------------------------------------------------------------


class FakeEmbeddingStore:
    """In-memory EmbeddingStore for tests."""

    def __init__(self) -> None:
        self.records: dict[str, list[dict[str, Any]]] = {}  # case_id -> records
        self.bulk_upsert_calls: list[tuple[str, list[dict]]] = []
        self.fail_on_upsert: bool = False

    def bulk_upsert(self, case_id: str, records: list[dict[str, Any]]) -> int:
        self.bulk_upsert_calls.append((case_id, records))
        if self.fail_on_upsert:
            raise RuntimeError("simulated db failure")
        existing = self.records.setdefault(case_id, [])
        # upsert semantics: replace by panel_id
        new_ids = {r["panel_id"] for r in records}
        kept = [r for r in existing if r["panel_id"] not in new_ids]
        kept.extend(records)
        self.records[case_id] = kept
        return len(records)

    def count(self, case_id: str) -> int:
        return len(self.records.get(case_id, []))

    def latest_indexed_at(self, case_id: str) -> str | None:
        records = self.records.get(case_id, [])
        if not records:
            return None
        return max(r.get("indexed_at", "") for r in records) or None


class FakeJobStore:
    """In-memory JobStore for tests."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}

    def upsert(
        self,
        case_id: str,
        status: str,
        *,
        indexed_count: int = 0,
        expected_count: int | None = None,
        detail: str = "",
    ) -> dict[str, Any]:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        existing = self.jobs.get(case_id, {})
        job = {
            "case_id": case_id,
            "status": status,
            "indexed_count": indexed_count,
            "expected_count": expected_count,
            "detail": detail,
            "updated_at": now,
            "started_at": existing.get("started_at")
            or (now if status in {"queued", "running"} else None),
            "completed_at": now if status not in {"queued", "running"} else None,
        }
        self.jobs[case_id] = job
        return job

    def get(self, case_id: str) -> dict[str, Any] | None:
        return self.jobs.get(case_id)


class FakeEncoder:
    """Encoder that returns deterministic embeddings without torch."""

    available = True
    _model_path = Path("/fake/model.pt")

    def __init__(self, dim: int = 512, fail_indices: set[int] | None = None) -> None:
        self._dim = dim
        self._fail_indices = fail_indices or set()
        self.call_count = 0

    def encode_batch(
        self, image_paths: list[Path], batch_size: int = 32, **kwargs
    ) -> list[list[float] | None]:
        return self.encode_batch_detailed(image_paths, batch_size, **kwargs).embeddings

    def encode_batch_detailed(
        self, image_paths: list[Path], batch_size: int = 32, **kwargs
    ) -> BatchResult:
        self.call_count += 1
        embeddings: list[list[float] | None] = []
        errors: list[str] = []
        progress = kwargs.get("progress")
        for i, p in enumerate(image_paths):
            if i in self._fail_indices:
                embeddings.append(None)
                errors.append(f"simulated failure for {p}")
            else:
                # Deterministic embedding: [i, 0, 0, ...]
                vec = [0.0] * self._dim
                vec[0] = float(i)
                embeddings.append(vec)
            if progress:
                progress(i + 1, len(image_paths), p)
        return BatchResult(
            embeddings=embeddings,
            error_count=sum(1 for e in embeddings if e is None),
            errors=errors,
        )


class UnavailableEncoder:
    """Encoder that reports itself unavailable."""

    available = False
    _model_path = Path("/nonexistent/model.pt")

    def encode_batch(self, image_paths, batch_size=32, **kwargs):
        raise RuntimeError("should not be called")

    def encode_batch_detailed(self, image_paths, batch_size=32, **kwargs):
        raise RuntimeError("should not be called")


def _make_test_image(path: Path, color: tuple[int, int, int] = (128, 128, 128)) -> None:
    """Create a minimal PNG image."""
    from PIL import Image

    img = Image.new("RGB", (64, 64), color)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))


def _make_workdir_with_panels(tmp_path: Path, n_panels: int = 3) -> Path:
    """Create a workdir with panel_evidence.json and panel images."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    panels_dir = workdir / "visual" / "panels"
    panels_dir.mkdir(parents=True)

    panels = []
    for i in range(n_panels):
        pid = f"P{i + 1}"
        img_path = panels_dir / f"{pid}.png"
        _make_test_image(img_path, color=(50 * (i + 1), 50, 50))
        panels.append(
            {
                "panel_id": pid,
                "parent_figure_id": "F1",
                "crop_path": f"visual/panels/{pid}.png",
            }
        )

    panel_doc = {"schema_version": "1.0", "panels": panels}
    (workdir / "panel_evidence.json").write_text(
        json.dumps(panel_doc), encoding="utf-8"
    )
    return workdir


# ===========================================================================
# DiskCacheBackend tests
# ===========================================================================


class TestDiskCacheBackend:
    def test_put_get_roundtrip(self, tmp_path: Path) -> None:
        cache = DiskCacheBackend(tmp_path / "cache")
        embedding = [0.1, 0.2, 0.3]
        cache.put("test_key", embedding)
        assert cache.get("test_key") == embedding

    def test_missing_key_returns_none(self, tmp_path: Path) -> None:
        cache = DiskCacheBackend(tmp_path / "cache")
        assert cache.get("nonexistent") is None

    def test_corrupt_file_returns_none(self, tmp_path: Path) -> None:
        cache = DiskCacheBackend(tmp_path / "cache")
        # Write invalid JSON
        cache_file = tmp_path / "cache" / "bad_key.json"
        cache_file.write_text("not json", encoding="utf-8")
        assert cache.get("bad_key") is None

    def test_non_list_data_returns_none(self, tmp_path: Path) -> None:
        cache = DiskCacheBackend(tmp_path / "cache")
        cache_file = tmp_path / "cache" / "obj_key.json"
        cache_file.write_text('{"not": "a list"}', encoding="utf-8")
        assert cache.get("obj_key") is None

    def test_creates_directory(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "a" / "b" / "c"
        cache = DiskCacheBackend(cache_dir)
        cache.put("k", [1.0])
        assert cache.get("k") == [1.0]


class TestCacheKey:
    def test_deterministic(self, tmp_path: Path) -> None:
        p = tmp_path / "img.png"
        p.write_bytes(b"fake")
        k1 = _cache_key(p)
        k2 = _cache_key(p)
        assert k1 == k2

    def test_different_paths_different_keys(self, tmp_path: Path) -> None:
        p1 = tmp_path / "a.png"
        p2 = tmp_path / "b.png"
        p1.write_bytes(b"fake")
        p2.write_bytes(b"fake")
        assert _cache_key(p1) != _cache_key(p2)


# ===========================================================================
# BatchResult tests
# ===========================================================================


class TestBatchResult:
    def test_empty_input(self) -> None:
        result = BatchResult(embeddings=[])
        assert result.embeddings == []
        assert result.error_count == 0
        assert result.errors == []

    def test_all_none(self) -> None:
        result = BatchResult(
            embeddings=[None, None],
            error_count=2,
            errors=["err1", "err2"],
        )
        assert result.error_count == 2
        assert len(result.errors) == 2


# ===========================================================================
# SSCDEncoder tests (no torch needed — just availability/path)
# ===========================================================================


class TestSSCDEncoder:
    def test_unavailable_without_model(self, tmp_path: Path) -> None:
        encoder = SSCDEncoder(model_path=tmp_path / "nonexistent.pt")
        assert not encoder.available

    def test_default_model_path_returns_something(self) -> None:
        encoder = SSCDEncoder()
        assert encoder._model_path is not None

    def test_cache_disabled_by_default(self) -> None:
        encoder = SSCDEncoder()
        assert encoder._cache is None

    def test_cache_enabled_with_dir(self, tmp_path: Path) -> None:
        encoder = SSCDEncoder(cache_dir=tmp_path / "cache")
        assert encoder._cache is not None
        assert isinstance(encoder._cache, DiskCacheBackend)


# ===========================================================================
# collect_panel_evidence tests
# ===========================================================================


class TestCollectPanelEvidence:
    def test_normal_case(self, tmp_path: Path) -> None:
        workdir = _make_workdir_with_panels(tmp_path, n_panels=3)
        records, error = collect_panel_evidence(workdir)
        assert error is None
        assert len(records) == 3
        assert records[0].panel_id == "P1"
        assert records[0].figure_id == "F1"
        assert records[0].image_path.exists()

    def test_missing_panel_evidence(self, tmp_path: Path) -> None:
        records, error = collect_panel_evidence(tmp_path)
        assert error is not None
        assert "panel_evidence.json" in error
        assert records == []

    def test_empty_panels(self, tmp_path: Path) -> None:
        doc = {"schema_version": "1.0", "panels": []}
        (tmp_path / "panel_evidence.json").write_text(json.dumps(doc), encoding="utf-8")
        records, error = collect_panel_evidence(tmp_path)
        assert error is None  # empty is not an error
        assert records == []

    def test_missing_image_files_skipped(self, tmp_path: Path) -> None:
        doc = {
            "panels": [
                {
                    "panel_id": "P1",
                    "parent_figure_id": "F1",
                    "crop_path": "no_such_file.png",
                },
            ]
        }
        (tmp_path / "panel_evidence.json").write_text(json.dumps(doc), encoding="utf-8")
        records, error = collect_panel_evidence(tmp_path)
        assert error is None
        assert records == []  # missing image → skipped

    def test_missing_panel_id_skipped(self, tmp_path: Path) -> None:
        workdir = _make_workdir_with_panels(tmp_path, n_panels=1)
        # Overwrite with a panel that has no panel_id
        doc = {
            "panels": [
                {
                    "panel_id": "",
                    "parent_figure_id": "F1",
                    "crop_path": "visual/panels/P1.png",
                },
            ]
        }
        (workdir / "panel_evidence.json").write_text(json.dumps(doc), encoding="utf-8")
        records, error = collect_panel_evidence(workdir)
        assert error is None
        assert records == []


# ===========================================================================
# EmbeddingIndexer tests
# ===========================================================================


class TestEmbeddingIndexer:
    def test_successful_run(self, tmp_path: Path) -> None:
        workdir = _make_workdir_with_panels(tmp_path, n_panels=3)
        store = FakeEmbeddingStore()
        job_store = FakeJobStore()
        encoder = FakeEncoder()

        indexer = EmbeddingIndexer(
            case_id="case1",
            workdir=workdir,
            encoder=encoder,
            embedding_store=store,
            job_store=job_store,
        )
        result = indexer.run()

        assert result.status == "completed"
        assert result.indexed_count == 3
        assert result.expected_count == 3
        assert result.failure_category is None
        assert store.count("case1") == 3
        assert job_store.jobs["case1"]["status"] == "completed"
        assert job_store.jobs["case1"]["indexed_count"] == 3

    def test_missing_panel_evidence(self, tmp_path: Path) -> None:
        store = FakeEmbeddingStore()
        encoder = FakeEncoder()

        indexer = EmbeddingIndexer(
            case_id="case1",
            workdir=tmp_path,
            encoder=encoder,
            embedding_store=store,
        )
        result = indexer.run()

        assert result.status == "failed"
        assert result.failure_category == "artifact_missing"
        assert result.indexed_count == 0

    def test_no_panels(self, tmp_path: Path) -> None:
        doc = {"panels": []}
        (tmp_path / "panel_evidence.json").write_text(json.dumps(doc), encoding="utf-8")
        store = FakeEmbeddingStore()
        encoder = FakeEncoder()

        indexer = EmbeddingIndexer(
            case_id="case1",
            workdir=tmp_path,
            encoder=encoder,
            embedding_store=store,
        )
        result = indexer.run()

        assert result.status == "no_panels"
        assert result.indexed_count == 0

    def test_encoder_unavailable(self, tmp_path: Path) -> None:
        workdir = _make_workdir_with_panels(tmp_path, n_panels=2)
        store = FakeEmbeddingStore()
        encoder = UnavailableEncoder()

        indexer = EmbeddingIndexer(
            case_id="case1",
            workdir=workdir,
            encoder=encoder,
            embedding_store=store,
        )
        result = indexer.run()

        assert result.status == "failed"
        assert result.failure_category == "environment"
        assert result.expected_count == 2

    def test_partial_failure(self, tmp_path: Path) -> None:
        workdir = _make_workdir_with_panels(tmp_path, n_panels=3)
        store = FakeEmbeddingStore()
        encoder = FakeEncoder(fail_indices={1, 2})  # 2 of 3 fail

        indexer = EmbeddingIndexer(
            case_id="case1",
            workdir=workdir,
            encoder=encoder,
            embedding_store=store,
        )
        result = indexer.run()

        assert result.status == "partial"
        assert result.indexed_count == 1
        assert result.expected_count == 3
        assert store.count("case1") == 1

    def test_all_images_fail(self, tmp_path: Path) -> None:
        workdir = _make_workdir_with_panels(tmp_path, n_panels=2)
        store = FakeEmbeddingStore()
        encoder = FakeEncoder(fail_indices={0, 1})

        indexer = EmbeddingIndexer(
            case_id="case1",
            workdir=workdir,
            encoder=encoder,
            embedding_store=store,
        )
        result = indexer.run()

        assert result.status == "failed"
        assert result.failure_category == "image_load_failed"
        assert result.indexed_count == 0

    def test_bulk_upsert_failure(self, tmp_path: Path) -> None:
        workdir = _make_workdir_with_panels(tmp_path, n_panels=2)
        store = FakeEmbeddingStore()
        store.fail_on_upsert = True
        encoder = FakeEncoder()

        indexer = EmbeddingIndexer(
            case_id="case1",
            workdir=workdir,
            encoder=encoder,
            embedding_store=store,
        )
        result = indexer.run()

        assert result.status == "failed"
        assert result.failure_category == "db_write_failed"
        assert result.indexed_count == 0

    def test_progress_callback_invoked(self, tmp_path: Path) -> None:
        workdir = _make_workdir_with_panels(tmp_path, n_panels=3)
        store = FakeEmbeddingStore()
        encoder = FakeEncoder()
        progress_calls: list[tuple[int, int, Path | None]] = []

        def on_progress(completed: int, total: int, path: Path | None) -> None:
            progress_calls.append((completed, total, path))

        indexer = EmbeddingIndexer(
            case_id="case1",
            workdir=workdir,
            encoder=encoder,
            embedding_store=store,
            progress=on_progress,
        )
        indexer.run()

        assert len(progress_calls) > 0
        # Last call should have completed == total
        assert progress_calls[-1][0] == progress_calls[-1][1]

    def test_no_job_store(self, tmp_path: Path) -> None:
        """Indexer works without a job store — just skips job updates."""
        workdir = _make_workdir_with_panels(tmp_path, n_panels=2)
        store = FakeEmbeddingStore()
        encoder = FakeEncoder()

        indexer = EmbeddingIndexer(
            case_id="case1",
            workdir=workdir,
            encoder=encoder,
            embedding_store=store,
            job_store=None,
        )
        result = indexer.run()

        assert result.status == "completed"
        assert result.indexed_count == 2

    def test_upsert_records_contain_expected_fields(self, tmp_path: Path) -> None:
        workdir = _make_workdir_with_panels(tmp_path, n_panels=1)
        store = FakeEmbeddingStore()
        encoder = FakeEncoder()

        indexer = EmbeddingIndexer(
            case_id="case1",
            workdir=workdir,
            encoder=encoder,
            embedding_store=store,
        )
        indexer.run()

        assert len(store.bulk_upsert_calls) == 1
        case_id, records = store.bulk_upsert_calls[0]
        assert case_id == "case1"
        assert len(records) == 1
        rec = records[0]
        assert rec["panel_id"] == "P1"
        assert rec["figure_id"] == "F1"
        assert "image_path" in rec
        assert "embedding" in rec
        assert "indexed_at" in rec
        assert isinstance(rec["embedding"], list)
        assert len(rec["embedding"]) == 512

    def test_reindex_updates_existing(self, tmp_path: Path) -> None:
        """Running indexer twice should update, not duplicate."""
        workdir = _make_workdir_with_panels(tmp_path, n_panels=2)
        store = FakeEmbeddingStore()
        encoder = FakeEncoder()

        indexer = EmbeddingIndexer(
            case_id="case1",
            workdir=workdir,
            encoder=encoder,
            embedding_store=store,
        )
        indexer.run()
        assert store.count("case1") == 2

        # Re-index
        indexer.run()
        assert store.count("case1") == 2  # no duplicates


# ===========================================================================
# get_index_status tests
# ===========================================================================


class TestGetIndexStatus:
    def test_no_embeddings_no_job(self) -> None:
        store = FakeEmbeddingStore()
        status = get_index_status("case1", store)
        assert status.status == "not_indexed"
        assert status.indexed_count == 0

    def test_with_embeddings(self) -> None:
        store = FakeEmbeddingStore()
        store.bulk_upsert(
            "case1",
            [
                {
                    "panel_id": "P1",
                    "figure_id": "F1",
                    "image_path": "p.png",
                    "embedding": [0.1] * 512,
                    "indexed_at": "2026-01-01T00:00:00Z",
                },
            ],
        )
        status = get_index_status("case1", store)
        assert status.status == "indexed"
        assert status.indexed_count == 1
        assert status.last_indexed_at == "2026-01-01T00:00:00Z"

    def test_with_job_store_running(self) -> None:
        store = FakeEmbeddingStore()
        job_store = FakeJobStore()
        job_store.upsert("case1", "running", expected_count=10)

        status = get_index_status("case1", store, job_store)
        assert status.status == "running"
        assert status.expected_count == 10

    def test_with_job_store_completed_and_embeddings(self) -> None:
        store = FakeEmbeddingStore()
        store.bulk_upsert(
            "case1",
            [
                {
                    "panel_id": "P1",
                    "figure_id": "F1",
                    "image_path": "p.png",
                    "embedding": [0.1] * 512,
                    "indexed_at": "2026-01-01T00:00:00Z",
                },
            ],
        )
        job_store = FakeJobStore()
        job_store.upsert("case1", "completed", indexed_count=1, expected_count=1)

        status = get_index_status("case1", store, job_store)
        assert status.status == "indexed"  # completed + embeddings → "indexed"


# ===========================================================================
# update_index_job_status tests
# ===========================================================================


class TestUpdateIndexJobStatus:
    def test_delegates_to_job_store(self) -> None:
        job_store = FakeJobStore()
        result = update_index_job_status(
            "case1",
            "running",
            job_store,
            expected_count=5,
            detail="test",
        )
        assert result["status"] == "running"
        assert result["expected_count"] == 5
        assert job_store.jobs["case1"]["status"] == "running"
