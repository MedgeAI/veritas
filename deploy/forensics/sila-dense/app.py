"""SILA Dense Copy-Move Detection — FastAPI HTTP service.

Wraps the existing SILA dense detection logic (Zernike/PCT/FMT features)
in an HTTP API so that the detection engine stays loaded in memory,
eliminating per-invocation Docker container startup overhead.

Endpoints:
    POST /detect      — Run detection on one or more images (batch).
    POST /detect/cross — Run cross-image detection on a pair.
    GET  /health      — Liveness probe.

File I/O protocol:
    The service reads images from and writes results to a shared ``/data``
    bind mount.  The caller sends container-side paths (``/data/...``);
    the adapter translates host ↔ container paths before/after the call.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure the detection modules are importable.
# The base image has everything at /app/src/.
# ---------------------------------------------------------------------------
sys.path.insert(0, "/app")

try:
    from src.detector import CopyMoveDetector, CrossImageCopyDetector
    from src.utility.utilityImage import imread2f
except ImportError:
    # Fallback for different image layouts.
    from copy_move_detection.detector import CopyMoveDetector, CrossImageCopyDetector
    from copy_move_detection.utility.utilityImage import imread2f

import cv2
import numpy as np
import matplotlib

matplotlib.use("Agg")  # headless — no X11
import matplotlib.pyplot as plt
from fastapi import FastAPI
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
)
logger = logging.getLogger("sila-dense-service")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SILA Dense Copy-Move Detection Service",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ImageRef(BaseModel):
    """Reference to an image on the shared data volume."""

    id: str = Field(..., description="Unique identifier for this image")
    path: str = Field(..., description="Absolute path inside the container")


class DetectRequest(BaseModel):
    """Batch single-image detection request."""

    images: list[ImageRef] = Field(..., min_length=1)
    output_dir: str = Field(..., description="Output directory (container path)")
    method: int = Field(2, ge=1, le=5, description="Feature extraction method ID")
    timeout_per_image: int = Field(120, ge=10, le=600, description="Per-image timeout (s)")
    clustering: dict[str, Any] = Field(
        default_factory=lambda: {"algorithm": "dbscan"},
        description="Clustering parameters",
    )


class DetectResult(BaseModel):
    """Result for a single image."""

    id: str
    success: bool
    mask_path: str | None = None
    matches_path: str | None = None
    clusters_path: str | None = None
    elapsed_seconds: float = 0.0
    error: str | None = None


class DetectResponse(BaseModel):
    """Batch detection response."""

    success: bool
    total: int
    succeeded: int
    failed: int
    results: list[DetectResult]


class CrossDetectRequest(BaseModel):
    """Cross-image detection request."""

    source: ImageRef
    target: ImageRef
    output_dir: str
    method: int = Field(2, ge=1, le=5)
    timeout: int = Field(120, ge=10, le=600)
    clustering: dict[str, Any] = Field(default_factory=dict)


class CrossDetectResponse(BaseModel):
    success: bool
    mask_source: str | None = None
    mask_target: str | None = None
    matches_path: str | None = None
    clusters_path: str | None = None
    elapsed_seconds: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Detection logic
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict[str, Any] = {
    "type_feat": 2,
    "clustering_algorithm": "dbscan",
    "clustering_eps": 0.5,
    "clustering_min_samples": 13,
    "clustering_min_cluster_size": 13,
    "clustering_max_eps": float("inf"),
    "clustering_xi": 0.05,
    "clustering_distance_threshold": 0.5,
    "clustering_bandwidth_quantile": 0.2,
}


def _build_config(method: int, clustering: dict[str, Any]) -> dict[str, Any]:
    """Merge method + clustering params into the config dict the detector expects."""
    config = dict(_DEFAULT_CONFIG)
    config["type_feat"] = method
    for key, value in clustering.items():
        config_key = f"clustering_{key}"
        config[config_key] = value
    return config


def _run_single(image_path: str, output_dir: str, config: dict[str, Any]) -> DetectResult:
    """Run single-image copy-move detection. Returns result (no subprocess)."""
    stem = Path(image_path).stem
    image_id = stem
    os.makedirs(output_dir, exist_ok=True)

    detector = CopyMoveDetector(config)
    try:
        img = imread2f(image_path)
    except Exception as exc:
        return DetectResult(id=image_id, success=False, error=f"load failed: {exc}")

    t0 = time.monotonic()
    try:
        mask, _clusters = detector.run(img)
    except Exception as exc:
        return DetectResult(
            id=image_id, success=False, error=f"detection failed: {exc}",
            elapsed_seconds=time.monotonic() - t0,
        )

    elapsed = time.monotonic() - t0

    # Save mask
    mask_path = os.path.join(output_dir, f"{stem}_mask.png")
    cv2.imwrite(mask_path, (mask * 255).astype(np.uint8))

    # Save match visualization
    detector.visualize_matches()
    matches_path = os.path.join(output_dir, f"{stem}_matches.png")
    plt.gcf().savefig(matches_path, bbox_inches="tight", pad_inches=0)
    plt.close(plt.gcf())

    # Save cluster visualization
    detector.visualize_clusters()
    clusters_path = os.path.join(output_dir, f"{stem}_clusters.png")
    plt.gcf().savefig(clusters_path, bbox_inches="tight", pad_inches=0)
    plt.close(plt.gcf())

    return DetectResult(
        id=image_id,
        success=True,
        mask_path=mask_path,
        matches_path=matches_path,
        clusters_path=clusters_path,
        elapsed_seconds=round(elapsed, 3),
    )


def _run_cross(
    source_path: str,
    target_path: str,
    output_dir: str,
    config: dict[str, Any],
) -> CrossDetectResponse:
    """Run cross-image copy-move detection."""
    os.makedirs(output_dir, exist_ok=True)
    stem_a = Path(source_path).stem
    stem_b = Path(target_path).stem

    detector = CrossImageCopyDetector(config)
    try:
        img_a = imread2f(source_path)
        img_b = imread2f(target_path)
    except Exception as exc:
        return CrossDetectResponse(success=False, error=f"load failed: {exc}")

    t0 = time.monotonic()
    try:
        mask_a, mask_b, _cl_a, _cl_b = detector.run(img_a, img_b)
    except Exception as exc:
        return CrossDetectResponse(
            success=False, error=f"detection failed: {exc}",
            elapsed_seconds=time.monotonic() - t0,
        )

    elapsed = time.monotonic() - t0

    base = f"{stem_a}_vs_{stem_b}"
    mask_a_path = os.path.join(output_dir, f"{base}_maskA.png")
    mask_b_path = os.path.join(output_dir, f"{base}_maskB.png")
    cv2.imwrite(mask_a_path, (mask_a * 255).astype(np.uint8))
    cv2.imwrite(mask_b_path, (mask_b * 255).astype(np.uint8))

    detector.visualize_matches()
    matches_path = os.path.join(output_dir, f"{base}_matches.png")
    plt.gcf().savefig(matches_path, bbox_inches="tight", pad_inches=0)
    plt.close(plt.gcf())

    detector.visualize_clusters()
    clusters_path = os.path.join(output_dir, f"{base}_clusters.png")
    plt.gcf().savefig(clusters_path, bbox_inches="tight", pad_inches=0)
    plt.close(plt.gcf())

    return CrossDetectResponse(
        success=True,
        mask_source=mask_a_path,
        mask_target=mask_b_path,
        matches_path=matches_path,
        clusters_path=clusters_path,
        elapsed_seconds=round(elapsed, 3),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/detect", response_model=DetectResponse)
def detect(req: DetectRequest) -> DetectResponse:
    """Batch single-image copy-move detection."""
    config = _build_config(req.method, req.clustering)
    results: list[DetectResult] = []

    for img_ref in req.images:
        per_image_output = os.path.join(req.output_dir, img_ref.id)
        result = _run_single(img_ref.path, per_image_output, config)
        result.id = img_ref.id
        results.append(result)

    succeeded = sum(1 for r in results if r.success)
    return DetectResponse(
        success=succeeded > 0,
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


@app.post("/detect/cross", response_model=CrossDetectResponse)
def detect_cross(req: CrossDetectRequest) -> CrossDetectResponse:
    """Cross-image copy-move detection."""
    config = _build_config(req.method, req.clustering)
    return _run_cross(req.source.path, req.target.path, req.output_dir, config)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "healthy", "version": "1.0.0"}


# ---------------------------------------------------------------------------
# Entrypoint (for direct execution)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8770)
