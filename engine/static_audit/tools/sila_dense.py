"""SILA dense copy-move detection via HTTP service.

Wraps the ELIS copy-move-detection module (Zernike Moments / PCT / FMT dense
features) running as a long-running HTTP service (veritas-sila-service:8770).
The service keeps the detection engine loaded in memory, eliminating the
per-invocation Docker container startup overhead.

Supports single-image and cross-image detection modes.  Single-image
detection uses **batch** mode — all panels are sent in one HTTP call.
Results are converted to ImageRelationship dicts compatible with the
Veritas finding pipeline.

File I/O:
    The service reads images from a shared ``/data`` bind mount.  The
    adapter translates host paths to container paths (project root → /data)
    before sending, and translates back for result paths.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from engine.env import get_env
from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service URL and project root for path translation.
# ---------------------------------------------------------------------------

_SERVICE_URL: str = get_env(
    "SILA_DENSE_URL", required=False, default="http://localhost:8770"
)

# Project root — the bind mount maps this to /data inside the container.
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

_HTTP_TIMEOUT = 180.0  # generous — batch of many images can take a while


def _client() -> httpx.Client:
    """Return an httpx client that bypasses env proxy settings for local calls."""
    return httpx.Client(base_url=_SERVICE_URL, timeout=_HTTP_TIMEOUT, trust_env=False)


# ---------------------------------------------------------------------------
# Path translation  (host ↔ container)
# ---------------------------------------------------------------------------


def _to_container_path(host_path: Path) -> str:
    """Translate a host absolute path to the container's ``/data/...`` path."""
    return str(host_path).replace(str(_PROJECT_ROOT), "/data", 1)


def _to_host_path(container_path: str) -> str:
    """Translate a container ``/data/...`` path back to host absolute path."""
    return container_path.replace("/data", str(_PROJECT_ROOT), 1)


# ---------------------------------------------------------------------------
# Service health check
# ---------------------------------------------------------------------------


def _service_available() -> bool:
    """Return True if the SILA dense service is reachable."""
    try:
        with _client() as c:
            resp = c.get("/health", timeout=5.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


# ---------------------------------------------------------------------------
# HTTP detection calls
# ---------------------------------------------------------------------------


def _detect_batch_via_service(
    image_paths: list[Path],
    output_dir: Path,
    method: int = 2,
) -> dict[str, Any]:
    """Batch single-image detection — one HTTP call for all images."""
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "images": [
            {"id": p.stem, "path": _to_container_path(p.resolve())}
            for p in image_paths
        ],
        "output_dir": _to_container_path(output_dir.resolve()),
        "method": method,
    }

    with _client() as c:
        resp = c.post("/detect", json=payload)
    resp.raise_for_status()
    data = resp.json()

    # Translate container paths back to host paths
    for result in data.get("results", []):
        for key in ("mask_path", "matches_path", "clusters_path"):
            if result.get(key):
                result[key] = _to_host_path(result[key])

    return data


def _detect_cross_via_service(
    source_path: Path,
    target_path: Path,
    output_dir: Path,
    method: int = 2,
) -> dict[str, Any]:
    """Cross-image detection — single HTTP call."""
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "source": {
            "id": source_path.stem,
            "path": _to_container_path(source_path.resolve()),
        },
        "target": {
            "id": target_path.stem,
            "path": _to_container_path(target_path.resolve()),
        },
        "output_dir": _to_container_path(output_dir.resolve()),
        "method": method,
    }

    with _client() as c:
        resp = c.post("/detect/cross", json=payload)
    resp.raise_for_status()
    data = resp.json()

    # Translate container paths back to host paths
    for key in ("mask_source", "mask_target", "matches_path", "clusters_path"):
        if data.get(key):
            data[key] = _to_host_path(data[key])

    return data


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------


def detect_sila_dense(
    panel_evidence: list[dict],
    figure_evidence: list[dict],
    *,
    workdir: Path,
    output_base: Path | None = None,
    method: str = "sila_dense",
    min_score: float = 0.05,
    max_relationships: int = 500,
) -> dict[str, Any]:
    """Run SILA dense copy-move detection on panels.

    Sends all panels in one **batch** HTTP call to the service, then
    processes results locally (mask coverage scoring, relationship building).
    """
    if not _service_available():
        return _sila_failed(
            "environment",
            [
                f"SILA dense service unreachable at {_SERVICE_URL}. "
                "Production uses compose service DNS "
                "SILA_DENSE_URL=http://sila-dense:8770; "
                "for local development run: make forensics-up."
            ],
            method=method,
        )

    panels_with_crops = []
    for panel in panel_evidence:
        crop = str(panel.get("crop_path") or "")
        if not crop:
            continue
        crop_path = workdir / crop
        if crop_path.exists():
            panels_with_crops.append((panel, crop_path))

    if not panels_with_crops:
        return _sila_failed(
            "dependency",
            ["No panels with valid crop paths available."],
            method=method,
        )

    output_base = output_base or (workdir / "sila_dense")

    # ---- Batch HTTP call ----
    crop_paths = [cp for _, cp in panels_with_crops]
    try:
        batch_result = _detect_batch_via_service(crop_paths, output_base)
    except httpx.HTTPError as exc:
        return _sila_failed(
            "service",
            [f"SILA dense service call failed: {exc}"],
            method=method,
        )

    # Build a lookup: stem → result dict (with host paths)
    result_by_id: dict[str, dict] = {
        r["id"]: r for r in batch_result.get("results", [])
    }

    # ---- Process results locally ----
    relationships: list[dict[str, Any]] = []
    errors: list[str] = []
    counter = 0

    for panel, crop_path in panels_with_crops:
        panel_id = str(panel.get("panel_id") or "")
        result = result_by_id.get(crop_path.stem, {})

        if not result.get("success"):
            errors.append(
                f"SILA dense failed for {panel_id}: {result.get('error', 'unknown')}"
            )
            continue

        mask_path = result.get("mask_path")
        if not mask_path or not Path(mask_path).exists():
            continue

        # Score based on mask coverage (non-zero pixels / total pixels)
        try:
            from PIL import Image
            import numpy as np

            mask_img = np.array(Image.open(mask_path).convert("L"))
            coverage = float(np.count_nonzero(mask_img)) / max(mask_img.size, 1)
            score = min(1.0, coverage * 5)  # Scale up for visibility
        except (OSError, ValueError, ImportError) as exc:
            logger.warning("SILA dense mask coverage failed for %s: %s", panel_id, exc)
            errors.append(f"SILA dense mask coverage failed for {panel_id}: {exc}")
            continue

        if score >= min_score:
            counter += 1
            matches_path = result.get("matches_path")
            try:
                rel_mask = str(Path(mask_path).relative_to(workdir))
            except ValueError:
                rel_mask = mask_path
            rel_matches = None
            if matches_path:
                try:
                    rel_matches = str(Path(matches_path).relative_to(workdir))
                except ValueError:
                    rel_matches = matches_path

            relationships.append(
                {
                    "relationship_id": f"IR-SILA-{counter:04d}",
                    "source_type": "copy_move_single",
                    "source_panel_id": panel_id,
                    "target_panel_id": panel_id,
                    "score": round(score, 4),
                    "match_method": "sila_dense_single",
                    "inlier_count": 0,
                    "homography": None,
                    "overlay_path": rel_matches,
                    "flip_detected": False,
                    "metadata": {
                        "detection_mode": "sila_dense_single",
                        "mask_path": rel_mask,
                    },
                }
            )

    # Sort by score, cap
    relationships.sort(key=lambda r: r["score"], reverse=True)
    relationships = relationships[:max_relationships]
    for i, rel in enumerate(relationships, start=1):
        rel["relationship_id"] = f"IR-SILA-{i:04d}"

    limitations = (
        []
        if relationships
        else ["SILA dense did not detect copy-move in any panel above threshold."]
    )
    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/sila_dense.py",
        "status": "ran",
        "failure_category": None,
        "method": method,
        "panel_count": len(panels_with_crops),
        "relationship_count": len(relationships),
        "relationships": relationships,
        "errors": errors,
        "limitations": limitations,
    }


def _sila_failed(
    failure_category: str,
    errors: list[str],
    *,
    method: str = "sila_dense",
) -> dict[str, Any]:
    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/sila_dense.py",
        "status": "failed",
        "failure_category": failure_category,
        "method": method,
        "panel_count": 0,
        "relationship_count": 0,
        "relationships": [],
        "errors": errors,
        "limitations": [],
    }
