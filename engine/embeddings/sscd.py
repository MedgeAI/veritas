"""SSCD (Self-Supervised Copy Detection) embedding extraction.

Uses Meta's SSCD model to extract 512-dimensional L2-normalized embeddings
from panel images.  This is a shared module used by both the CLI pipeline
and the Web P1 service.

Model reference: https://github.com/facebookresearch/sscd
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SSCDEncoder:
    """Lazy-loading SSCD TorchScript model for batch embedding extraction.

    The model is loaded on first call to ``encode_batch`` and cached
    for subsequent calls.  Images are preprocessed (resize 224x224,
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
