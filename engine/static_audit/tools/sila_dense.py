"""SILA dense copy-move detection via Docker container.

Wraps the ELIS copy-move-detection module (Zernike Moments / PCT / FMT dense
features) running in a Python 3.8 Docker container, since the compiled pm3D
extension is not compatible with Veritas's Python 3.12.

Supports single-image and cross-image detection modes. Results are converted
to ImageRelationship dicts compatible with the Veritas finding pipeline.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION

DOCKER_IMAGE = "veritas-sila-dense:latest"


def _docker_available() -> bool:
    """Check if Docker is available and the SILA image exists."""
    try:
        result = subprocess.run(
            ["docker", "images", "-q", DOCKER_IMAGE],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def _run_single_image_docker(
    image_path: Path,
    output_dir: Path,
    method: int = 2,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run SILA dense single-image detection via Docker."""
    output_dir.mkdir(parents=True, exist_ok=True)
    # Docker requires absolute paths for volume mounts
    abs_image_path = image_path.resolve()
    abs_output_dir = output_dir.resolve()

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{abs_image_path.parent}:/input:ro",
        "-v", f"{abs_output_dir}:/output",
        DOCKER_IMAGE,
        "--input", f"/input/{abs_image_path.name}",
        "--output", "/output",
        "--method", str(method),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        success = proc.returncode == 0
        # Check for output files
        stem = image_path.stem
        mask_path = output_dir / f"{stem}_mask.png"
        matches_path = output_dir / f"{stem}_matches.png"
        clusters_path = output_dir / f"{stem}_clusters.png"

        return {
            "success": success and mask_path.exists(),
            "mask_path": str(mask_path) if mask_path.exists() else None,
            "matches_path": str(matches_path) if matches_path.exists() else None,
            "clusters_path": str(clusters_path) if clusters_path.exists() else None,
            "stderr": proc.stderr[-500:] if not success else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stderr": "Docker container timed out"}
    except OSError as e:
        return {"success": False, "stderr": str(e)}


def _run_cross_image_docker(
    source_path: Path,
    target_path: Path,
    output_dir: Path,
    method: int = 2,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run SILA dense cross-image detection via Docker."""
    output_dir.mkdir(parents=True, exist_ok=True)
    abs_source = source_path.resolve()
    abs_target = target_path.resolve()
    abs_output = output_dir.resolve()

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{abs_source.parent}:/input1:ro",
        "-v", f"{abs_target.parent}:/input2:ro",
        "-v", f"{abs_output}:/output",
        DOCKER_IMAGE,
        "--input", f"/input1/{abs_source.name}", f"/input2/{abs_target.name}",
        "--output", "/output",
        "--method", str(method),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        success = proc.returncode == 0
        base = f"{source_path.stem}_vs_{target_path.stem}"
        mask_path = output_dir / f"{base}_mask.png"
        matches_path = output_dir / f"{base}_matches.png"
        clusters_path = output_dir / f"{base}_clusters.png"

        return {
            "success": success and mask_path.exists(),
            "mask_path": str(mask_path) if mask_path.exists() else None,
            "matches_path": str(matches_path) if matches_path.exists() else None,
            "clusters_path": str(clusters_path) if clusters_path.exists() else None,
            "stderr": proc.stderr[-500:] if not success else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stderr": "Docker container timed out"}
    except OSError as e:
        return {"success": False, "stderr": str(e)}


def detect_sila_dense(
    panel_evidence: list[dict],
    figure_evidence: list[dict],
    *,
    workdir: Path,
    method: str = "sila_dense",
    min_score: float = 0.05,
    max_relationships: int = 500,
) -> dict[str, Any]:
    """Run SILA dense copy-move detection on panels.

    For each panel, runs single-image detection. Results are converted to
    ImageRelationship dicts for the Veritas finding pipeline.
    """
    if not _docker_available():
        return {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "created_by": "engine/static_audit/tools/sila_dense.py",
            "status": "skipped",
            "method": method,
            "panel_count": 0,
            "relationship_count": 0,
            "relationships": [],
            "errors": [],
            "limitations": [
                f"Docker image '{DOCKER_IMAGE}' not found. "
                f"Build with: docker build -t {DOCKER_IMAGE} third_party/elis/system_modules/copy-move-detection/"
            ],
        }

    panels_with_crops = []
    for panel in panel_evidence:
        crop = str(panel.get("crop_path") or "")
        if not crop:
            continue
        crop_path = workdir / crop
        if crop_path.exists():
            panels_with_crops.append((panel, crop_path))

    if not panels_with_crops:
        return {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "created_by": "engine/static_audit/tools/sila_dense.py",
            "status": "skipped",
            "method": method,
            "panel_count": 0,
            "relationship_count": 0,
            "relationships": [],
            "errors": [],
            "limitations": ["No panels with valid crop paths available."],
        }

    output_base = workdir / "sila_dense"
    relationships: list[dict[str, Any]] = []
    errors: list[str] = []
    counter = 0

    for panel, crop_path in panels_with_crops:
        panel_id = str(panel.get("panel_id") or "")
        panel_output = output_base / panel_id
        result = _run_single_image_docker(crop_path, panel_output)

        if not result["success"]:
            errors.append(f"SILA dense failed for {panel_id}: {result.get('stderr', 'unknown')}")
            continue

        # For single-image SILA, we detected clusters of copy-move regions
        # within the panel. We emit a self-referencing relationship to flag
        # this panel as having within-panel copy-move detections.
        # The mask file presence indicates forgery was detected.
        mask_path = result.get("mask_path")
        if mask_path:
            try:
                rel_mask = str(Path(mask_path).relative_to(workdir))
            except ValueError:
                rel_mask = mask_path

            # Score based on mask coverage (non-zero pixels / total pixels)
            try:
                from PIL import Image
                import numpy as np
                mask_img = np.array(Image.open(mask_path).convert("L"))
                coverage = float(np.count_nonzero(mask_img)) / max(mask_img.size, 1)
                score = min(1.0, coverage * 5)  # Scale up for visibility
            except Exception:
                score = 0.5  # Default score if coverage calculation fails

            if score >= min_score:
                counter += 1
                matches_path = result.get("matches_path")
                if matches_path:
                    try:
                        rel_matches = str(Path(matches_path).relative_to(workdir))
                    except ValueError:
                        rel_matches = matches_path
                else:
                    rel_matches = None

                relationships.append({
                    "relationship_id": f"IR-SILA-{counter:04d}",
                    "source_type": "copy_move_single",
                    "source_panel_id": panel_id,
                    "target_panel_id": panel_id,
                    "score": round(score, 4),
                    "match_method": "sila_dense_single",
                    "inlier_count": 0,  # SILA doesn't provide keypoint counts
                    "homography": None,
                    "overlay_path": rel_matches,
                    "flip_detected": False,
                    "metadata": {
                        "detection_mode": "sila_dense_single",
                        "mask_path": rel_mask,
                    },
                })

    # Sort by score, cap
    relationships.sort(key=lambda r: r["score"], reverse=True)
    relationships = relationships[:max_relationships]
    for i, rel in enumerate(relationships, start=1):
        rel["relationship_id"] = f"IR-SILA-{i:04d}"

    status = "ran" if relationships else "skipped"
    if not relationships and panels_with_crops:
        return {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "created_by": "engine/static_audit/tools/sila_dense.py",
            "status": status,
            "method": method,
            "panel_count": len(panels_with_crops),
            "relationship_count": 0,
            "relationships": [],
            "errors": errors,
            "limitations": ["SILA dense did not detect copy-move in any panel above threshold."],
        }

    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/sila_dense.py",
        "status": status,
        "method": method,
        "panel_count": len(panels_with_crops),
        "relationship_count": len(relationships),
        "relationships": relationships,
        "errors": errors,
        "limitations": [],
    }
