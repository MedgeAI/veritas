"""ELIS TruFor forgery detection subprocess wrapper.

Invoked via ``python -m engine.static_audit.tools._elis_trufor_runner``.
Loads the TruFor SegFormer-B2 model once, runs inference on a batch of images,
and outputs JSON results to stdout.

Input (JSON on stdin)::

    {
      "figures": [
        {"figure_id": "FE-0001", "path": "/abs/path.png"},
        ...
      ],
      "output_dir": "/path/to/output",
      "weights_path": "/path/to/trufor.pth.tar",
      "config_path": "/path/to/trufor.yaml",
      "device": "cuda:0",
      "score_threshold": 0.5
    }

Output (JSON on stdout)::

    {
      "results": [
        {
          "figure_id": "FE-0001",
          "status": "completed",
          "integrity_score": 0.73,
          "is_suspicious": true,
          "localization_map_path": "/path/to/FE-0001_pred_map.png",
          "confidence_map_path": "/path/to/FE-0001_conf_map.png",
          "image_width": 800,
          "image_height": 600,
          "inference_seconds": 1.23
        },
        ...
      ]
    }
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from torch.nn import functional as F

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ELIS_TRUFOR_SRC = _REPO_ROOT / "third_party" / "elis" / "system_modules" / "TruFor" / "docker" / "src"
DEFAULT_WEIGHTS = _REPO_ROOT / "models" / "trufor" / "weights" / "trufor.pth.tar"
DEFAULT_CONFIG = ELIS_TRUFOR_SRC / "trufor.yaml"


def _setup_trufor_path() -> None:
    """Add TruFor docker/src to sys.path so model imports work."""
    src = str(ELIS_TRUFOR_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)


def _load_model(weights_path: str, device: str) -> Any:
    """Load TruFor model from checkpoint."""
    _setup_trufor_path()

    # Build model config directly (bypass YAML loading to avoid CWD issues)
    from yacs.config import CfgNode as CN

    cfg = CN()
    cfg.CUDNN = CN({"BENCHMARK": False, "DETERMINISTIC": False, "ENABLED": False})
    cfg.WORKERS = 1
    cfg.DATASET = CN({"NUM_CLASSES": 2})
    cfg.MODEL = CN()
    cfg.MODEL.NAME = "detconfcmx"
    cfg.MODEL.PRETRAINED = ""
    cfg.MODEL.MODS = ("RGB", "NP++")
    cfg.MODEL.EXTRA = CN(new_allowed=True)
    cfg.MODEL.EXTRA.BACKBONE = "mit_b2"
    cfg.MODEL.EXTRA.DECODER = "MLPDecoder"
    cfg.MODEL.EXTRA.DECODER_EMBED_DIM = 512
    cfg.MODEL.EXTRA.PREPRC = "imagenet"
    cfg.MODEL.EXTRA.BN_EPS = 0.001
    cfg.MODEL.EXTRA.BN_MOMENTUM = 0.1
    cfg.MODEL.EXTRA.DETECTION = "confpool"
    cfg.MODEL.EXTRA.CONF = True
    cfg.TEST = CN({"MODEL_FILE": weights_path})

    from models.cmx.builder_np_conf import myEncoderDecoder as confcmx
    model = confcmx(cfg=cfg)

    checkpoint = torch.load(weights_path, map_location=torch.device(device), weights_only=False)
    model.load_state_dict(checkpoint["state_dict"])
    model = model.to(device)
    model.eval()
    return model


def _preprocess_image(image_path: str, device: str) -> tuple[torch.Tensor, tuple[int, int]]:
    """Load and preprocess an image for TruFor inference."""
    _setup_trufor_path()
    from data_core import myDataset

    dataset = myDataset(list_img=[image_path])
    loader = torch.utils.data.DataLoader(dataset, batch_size=1)
    for rgb, _ in loader:
        rgb = rgb.to(device)
        img = Image.open(image_path)
        return rgb, img.size  # (width, height)
    raise RuntimeError(f"Failed to load image: {image_path}")


def _save_heatmap(arr: np.ndarray, path: str, original_size: tuple[int, int], colormap: str = "RdBu_r") -> None:
    """Save a 2D array as a heatmap PNG resized to original image dimensions."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cmap = plt.get_cmap(colormap)
    colored = cmap(arr)
    colored_rgb = (colored[:, :, :3] * 255).astype(np.uint8)
    img = Image.fromarray(colored_rgb, mode="RGB")
    img = img.resize(original_size, Image.BILINEAR)
    img.save(path)


def _save_grayscale(arr: np.ndarray, path: str, original_size: tuple[int, int]) -> None:
    """Save a 2D array as a grayscale PNG resized to original dimensions."""
    gray = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    img = Image.fromarray(gray, mode="L")
    img = img.resize(original_size, Image.BILINEAR)
    img.save(path)


def run_batch(
    figures: list[dict[str, str]],
    output_dir: str,
    weights_path: str,
    device: str = "cuda:0",
    score_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Run TruFor inference on a batch of figures."""
    os.makedirs(output_dir, exist_ok=True)

    results: list[dict[str, Any]] = []

    # Load model once
    try:
        model = _load_model(weights_path, device)
    except Exception as e:
        for fig in figures:
            results.append({
                "figure_id": fig["figure_id"],
                "status": "failed",
                "skip_reason": f"model_load_failed: {e}",
                "integrity_score": None,
                "is_suspicious": False,
                "localization_map_path": None,
                "confidence_map_path": None,
                "image_width": 0,
                "image_height": 0,
                "inference_seconds": 0.0,
            })
        return results

    # Process each figure
    for fig in figures:
        figure_id = fig["figure_id"]
        image_path = fig["path"]
        t0 = time.time()

        try:
            rgb, original_size = _preprocess_image(image_path, device)

            with torch.no_grad():
                pred, conf, det, npp = model(rgb)

            # Detection score from confpool (apply sigmoid to get probability in [0,1])
            if det is not None and det.numel() == 1:
                det_score = float(torch.sigmoid(det).item())
            else:
                det_score = 0.0

            # Localization map
            pred_squeezed = torch.squeeze(pred, 0)
            pred_map = F.softmax(pred_squeezed, dim=0)[1]
            pred_np = pred_map.cpu().numpy()

            # Confidence map
            conf_np = None
            if conf is not None:
                conf_squeezed = torch.squeeze(conf, 0)
                conf_map = torch.sigmoid(conf_squeezed)[0]
                conf_np = conf_map.cpu().numpy()

            elapsed = time.time() - t0

            # Save visualization maps
            pred_map_path = os.path.join(output_dir, f"{figure_id}_pred_map.png")
            conf_map_path = os.path.join(output_dir, f"{figure_id}_conf_map.png")
            _save_heatmap(pred_np, pred_map_path, original_size)
            if conf_np is not None:
                _save_grayscale(conf_np, conf_map_path, original_size)

            results.append({
                "figure_id": figure_id,
                "status": "completed",
                "integrity_score": round(det_score, 4),
                "is_suspicious": det_score > score_threshold,
                "localization_map_path": pred_map_path,
                "confidence_map_path": conf_map_path if conf_np is not None else None,
                "image_width": original_size[0],
                "image_height": original_size[1],
                "inference_seconds": round(elapsed, 2),
            })

        except Exception as e:
            elapsed = time.time() - t0
            results.append({
                "figure_id": figure_id,
                "status": "failed",
                "skip_reason": str(e),
                "integrity_score": None,
                "is_suspicious": False,
                "localization_map_path": None,
                "confidence_map_path": None,
                "image_width": 0,
                "image_height": 0,
                "inference_seconds": round(elapsed, 2),
            })

    return results


def main() -> int:
    input_data = json.load(sys.stdin)
    figures = input_data.get("figures", [])
    output_dir = input_data.get("output_dir", "/tmp/trufor_output")
    weights_path = input_data.get("weights_path", str(DEFAULT_WEIGHTS))
    device = input_data.get("device", "cuda:0")
    score_threshold = float(input_data.get("score_threshold", 0.5))

    results = run_batch(figures, output_dir, weights_path, device, score_threshold)
    print(json.dumps({"results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
