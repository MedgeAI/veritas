"""SSCD (Self-Supervised Copy Detection) embedding extraction.

Uses Meta's SSCD model to extract 512-dimensional L2-normalized embeddings
from panel images.  This is a shared module used by both the CLI pipeline
and the Web P1 service.

Enhancements over baseline:
- Per-image disk cache keyed on (path, mtime, size) — re-indexing unchanged
  panels is near-instant.
- Batch error tracking — callers get structured failure information instead
  of opaque ``None`` values.
- Progress callback — long-running encoding jobs can report progress to the
  caller (e.g. Web progress bar, structured log).

Model reference: https://github.com/facebookresearch/sscd
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

logger = logging.getLogger(__name__)

# Type alias for progress callback: (completed, total, current_path)
ProgressCallback = Callable[[int, int, Path | None], None]


class CacheBackend(Protocol):
    """Storage protocol for per-image embedding cache."""

    def get(self, key: str) -> list[float] | None: ...
    def put(self, key: str, embedding: list[float]) -> None: ...


# ---------------------------------------------------------------------------
# Batch result
# ---------------------------------------------------------------------------


@dataclass
class BatchResult:
    """Structured result from ``encode_batch``.

    ``embeddings`` is aligned 1:1 with the input ``image_paths``.  A ``None``
    entry means that image could not be encoded.  ``error_count`` and
    ``errors`` give callers enough information to distinguish total failure
    from partial failure without re-scanning the list.
    """

    embeddings: list[list[float] | None]
    error_count: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------


def _cache_key(image_path: Path) -> str:
    """Deterministic cache key from path + mtime + size.

    Changes to the file (e.g. re-extraction of a panel) invalidate the cache.
    """
    stat = image_path.stat()
    raw = f"{image_path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha256(raw.encode()).hexdigest()


class DiskCacheBackend:
    """Filesystem-backed embedding cache.

    Each cached embedding is a small JSON file in ``cache_dir``.  The key is
    a SHA-256 hash, so collisions are astronomically unlikely.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> list[float] | None:
        path = self._dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and all(isinstance(x, (int, float)) for x in data):
                return data
            logger.warning("corrupt cache entry %s — discarding", key)
            path.unlink(missing_ok=True)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("failed to read cache entry %s: %s", key, exc)
        return None

    def put(self, key: str, embedding: list[float]) -> None:
        path = self._dir / f"{key}.json"
        try:
            path.write_text(json.dumps(embedding), encoding="utf-8")
        except OSError as exc:
            logger.warning("failed to write cache entry %s: %s", key, exc)


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------


class SSCDEncoder:
    """Lazy-loading SSCD TorchScript model for batch embedding extraction.

    The model is loaded on first call to ``encode_batch`` and cached in
    memory for subsequent calls.  Images are preprocessed (resize 224x224,
    ImageNet normalization) and embeddings are L2-normalized.

    Parameters
    ----------
    model_path:
        Path to the TorchScript model file.  ``None`` uses the default
        search order in :func:`_default_model_path`.
    cache_dir:
        Directory for per-image disk cache.  ``None`` disables caching.
        Pass an explicit ``Path`` to enable it.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._model = None
        self._model_path = Path(model_path) if model_path else _default_model_path()
        self._device = "cpu"
        self._cache: CacheBackend | None = DiskCacheBackend(cache_dir) if cache_dir else None

    @property
    def available(self) -> bool:
        """Check if the SSCD model file exists and can be loaded."""
        return self._model_path.exists()

    # -- public API ---------------------------------------------------------

    def encode_batch(
        self,
        image_paths: list[Path],
        batch_size: int = 32,
        *,
        progress: ProgressCallback | None = None,
    ) -> list[list[float] | None]:
        """Extract 512-dim L2-normalized embeddings for a batch of images.

        Returns one item per input path.  Unreadable images are represented
        as ``None`` so callers can distinguish partial failure from success.

        Parameters
        ----------
        image_paths:
            Paths to the images to encode.
        batch_size:
            Number of images to process in a single forward pass.
        progress:
            Optional callback invoked after each image is processed (whether
            success or failure) with ``(completed, total, current_path)``.
        """
        result = self.encode_batch_detailed(image_paths, batch_size, progress=progress)
        return result.embeddings

    def encode_batch_detailed(
        self,
        image_paths: list[Path],
        batch_size: int = 32,
        *,
        progress: ProgressCallback | None = None,
    ) -> BatchResult:
        """Like :meth:`encode_batch` but returns a structured :class:`BatchResult`.

        Use this when you need error counts or error messages, not just the
        embedding list.
        """
        if not image_paths:
            return BatchResult(embeddings=[])

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

        all_embeddings: list[list[float] | None] = [None] * len(image_paths)
        errors: list[str] = []
        completed = 0
        total = len(image_paths)

        for batch_start in range(0, total, batch_size):
            batch_paths = image_paths[batch_start:batch_start + batch_size]
            tensors: list[torch.Tensor] = []
            tensor_positions: list[int] = []

            for offset, p in enumerate(batch_paths):
                position = batch_start + offset
                try:
                    # Check disk cache first
                    cached = self._cache_get(p)
                    if cached is not None:
                        all_embeddings[position] = cached
                        completed += 1
                        if progress:
                            progress(completed, total, p)
                        continue

                    img = Image.open(p).convert("RGB")
                    tensors.append(preprocess(img))
                    tensor_positions.append(position)
                except Exception as exc:
                    msg = f"failed to load {p}: {exc}"
                    logger.debug(msg)
                    errors.append(msg)
                    completed += 1
                    if progress:
                        progress(completed, total, p)
                    continue

            # Run model on the tensors we could load
            if tensors:
                try:
                    batch_tensor = torch.stack(tensors).to(self._device)
                    with torch.no_grad():
                        raw = self._model(batch_tensor)
                        raw = torch.nn.functional.normalize(raw, p=2, dim=1)

                    for position, embedding in zip(tensor_positions, raw.cpu().tolist()):
                        all_embeddings[position] = embedding
                        self._cache_put(image_paths[position], embedding)
                except Exception as exc:
                    msg = f"model forward pass failed for batch starting at {batch_start}: {exc}"
                    logger.error(msg)
                    errors.append(msg)
                    # tensor_positions entries remain None in all_embeddings

            completed += len(tensor_positions)
            if progress:
                last_path = batch_paths[-1] if batch_paths else None
                progress(completed, total, last_path)

        error_count = sum(1 for e in all_embeddings if e is None)
        return BatchResult(
            embeddings=all_embeddings,
            error_count=error_count,
            errors=errors,
        )

    # -- internals ----------------------------------------------------------

    def _cache_get(self, path: Path) -> list[float] | None:
        if self._cache is None:
            return None
        try:
            return self._cache.get(_cache_key(path))
        except Exception:
            return None

    def _cache_put(self, path: Path, embedding: list[float]) -> None:
        if self._cache is None:
            return
        try:
            self._cache.put(_cache_key(path), embedding)
        except Exception:
            pass

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch
        if torch.cuda.is_available():
            self._device = "cuda"
        self._model = torch.jit.load(str(self._model_path), map_location=self._device)
        self._model.eval()


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


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
