"""Copy-Move rotation/flip/scale detection using SIFT + affine transform.

This module detects copy-move manipulations involving rotation, flipping,
and scaling by using SIFT features and RANSAC affine transform estimation.

Detection flow:
1. SIFT feature extraction on both images
2. Feature matching (BFMatcher with cross-check)
3. RANSAC affine transform estimation
4. Decompose affine matrix to extract rotation angle, scale, flip flag

Only executed on wet_lab panels (blots, microscopy, etc.) to avoid
false positives on code-generated images.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Minimum inlier matches required to confirm rotation/flip/scale
MIN_MATCHES_ROTATION = 10

# RANSAC threshold (pixels) for affine transform estimation
RANSAC_THRESHOLD = 3.0


def decompose_affine_transform(matrix: np.ndarray) -> tuple[float, float, bool]:
    """Decompose 2x3 affine transform matrix into rotation angle, scale, and flip.

    Args:
        matrix: 2x3 affine transformation matrix

    Returns:
        tuple of (angle_degrees, scale, is_flipped)
        - angle_degrees: rotation angle in degrees [-180, 180]
        - scale: uniform scale factor
        - is_flipped: True if horizontal flip detected

    The affine matrix has form:
        [a11 a12 tx]
        [a21 a22 ty]

    For rotation + scale + flip:
        [s*cos(θ)  -s*sin(θ)  tx]
        [s*sin(θ)   s*cos(θ)  ty]

    With horizontal flip:
        [-s*cos(θ)  -s*sin(θ)  tx]
        [-s*sin(θ)   s*cos(θ)  ty]
    """
    if matrix.shape != (2, 3):
        raise ValueError(f"Expected 2x3 matrix, got {matrix.shape}")

    # Extract the linear part (2x2)
    A = matrix[:, :2]

    # Compute scale (determinant magnitude gives scale^2 for uniform scaling)
    det = np.linalg.det(A)
    scale = np.sqrt(abs(det))

    if scale < 1e-6:
        # Degenerate case (no scale)
        return 0.0, 0.0, False

    # Check for flip: negative determinant indicates reflection
    is_flipped = det < 0

    # Normalize A by scale to get pure rotation (+ possible flip)
    if is_flipped:
        # Flip detected: negate first column to recover rotation
        A_normalized = A / scale
        A_normalized[:, 0] *= -1
    else:
        A_normalized = A / scale

    # Extract rotation angle from normalized rotation matrix
    # [cos(θ)  -sin(θ)]
    # [sin(θ)   cos(θ)]
    cos_theta = A_normalized[0, 0]
    sin_theta = A_normalized[1, 0]

    # Use atan2 for robust angle extraction
    angle_rad = np.arctan2(sin_theta, cos_theta)
    angle_deg = np.degrees(angle_rad)

    # Normalize to [-180, 180]
    if angle_deg > 180:
        angle_deg -= 360
    elif angle_deg < -180:
        angle_deg += 360

    return float(angle_deg), float(scale), bool(is_flipped)


def detect_copy_move_rotation(
    img_a: np.ndarray,
    img_b: np.ndarray,
    min_matches: int = MIN_MATCHES_ROTATION,
) -> dict[str, Any] | None:
    """Detect copy-move with rotation/flip/scale using SIFT + affine transform.

    Detection strategy:
    1. Try matching img_a with img_b directly -> rotation/scale detection
    2. Try matching img_a with flip(img_b) -> flip detection

    This two-step approach is necessary because SIFT descriptors are
    rotation-invariant but NOT reflection-invariant. To detect flips,
    we must explicitly match against the flipped version.

    Args:
        img_a: Source image (BGR format from cv2.imread)
        img_b: Target image (BGR format from cv2.imread)
        min_matches: Minimum number of inlier matches to confirm detection

    Returns:
        dict with keys: angle, scale, is_flipped, transform_matrix, inlier_count
        or None if insufficient matches or RANSAC fails
    """
    import cv2

    # Validate inputs
    if img_a is None or img_b is None:
        logger.warning("detect_copy_move_rotation: received None image")
        return None

    if img_a.ndim != 3 or img_b.ndim != 3:
        logger.warning(
            f"detect_copy_move_rotation: expected 3-channel images, got {img_a.ndim}D and {img_b.ndim}D"
        )
        return None

    # Strategy 1: Match img_a with img_b (rotation/scale)
    result_direct = _match_with_affine(img_a, img_b, min_matches)

    # Strategy 2: Match img_a with flip(img_b) (flip detection)
    img_b_flipped = cv2.flip(img_b, 1)  # horizontal flip
    result_flipped = _match_with_affine(img_a, img_b_flipped, min_matches)

    # Choose the better match (more inliers)
    if result_direct is None and result_flipped is None:
        return None

    if result_direct is None:
        # Only flip match succeeded
        result_flipped["is_flipped"] = True
        return result_flipped

    if result_flipped is None:
        # Only direct match succeeded
        result_direct["is_flipped"] = False
        return result_direct

    # Both succeeded: choose the one with more inliers
    if result_flipped["inlier_count"] > result_direct["inlier_count"]:
        result_flipped["is_flipped"] = True
        return result_flipped
    else:
        result_direct["is_flipped"] = False
        return result_direct


def _match_with_affine(
    img_a: np.ndarray,
    img_b: np.ndarray,
    min_matches: int,
) -> dict[str, Any] | None:
    """Match two images using SIFT + affine transform estimation.

    Returns dict with angle, scale, transform_matrix, inlier_count, or None.
    Does NOT set is_flipped (caller handles that).
    """
    import cv2

    # Convert to grayscale for SIFT
    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)

    # SIFT feature extraction
    sift = cv2.SIFT_create()
    kp_a, desc_a = sift.detectAndCompute(gray_a, None)
    kp_b, desc_b = sift.detectAndCompute(gray_b, None)

    if desc_a is None or desc_b is None:
        logger.debug("SIFT returned no descriptors")
        return None

    if len(kp_a) < min_matches or len(kp_b) < min_matches:
        logger.debug(f"Insufficient keypoints: {len(kp_a)} vs {len(kp_b)}")
        return None

    # Feature matching with BFMatcher + cross-check
    bf = cv2.BFMatcher(cv2.NORM_L2, crossCheck=True)
    matches = bf.match(desc_a, desc_b)

    if len(matches) < min_matches:
        logger.debug(f"Insufficient matches: {len(matches)} < {min_matches}")
        return None

    # Sort matches by distance
    matches = sorted(matches, key=lambda m: m.distance)

    # Extract matched point coordinates
    src_pts = np.float32([kp_a[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp_b[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

    # Estimate affine transform with RANSAC
    # Use estimateAffine2D (full 6-DOF affine) instead of estimateAffinePartial2D
    # (4-DOF similarity) because similarity transforms cannot represent reflections
    # (flips). estimateAffine2D can produce negative-determinant matrices, enabling
    # flip detection.
    M, inliers = cv2.estimateAffine2D(
        src_pts, dst_pts, method=cv2.RANSAC, ransacReprojThreshold=RANSAC_THRESHOLD
    )

    if M is None:
        logger.debug("RANSAC failed to estimate affine transform")
        return None

    # Count inliers
    if inliers is None:
        inlier_count = 0
    else:
        inlier_count = int(np.sum(inliers))

    if inlier_count < min_matches:
        logger.debug(f"Insufficient inliers: {inlier_count} < {min_matches}")
        return None

    # Decompose the affine transform
    angle, scale, _ = decompose_affine_transform(M)  # ignore flip from matrix (handled by caller)

    return {
        "angle": angle,
        "scale": scale,
        "transform_matrix": M.tolist(),
        "inlier_count": inlier_count,
    }


def run_rotation_detection_on_pairs(
    pairs: list[dict[str, Any]],
    workdir: Path,
    min_matches: int = MIN_MATCHES_ROTATION,
    min_score: float = 0.05,
    max_pairs: int = 500,
) -> list[dict[str, Any]]:
    """Run rotation detection on a list of image pairs.

    Args:
        pairs: List of dicts with 'source', 'target', 'pair_id' keys
        workdir: Working directory for resolving relative paths
        min_matches: Minimum inlier matches to confirm detection
        min_score: Minimum score to emit a relationship
        max_pairs: Maximum number of pairs to process

    Returns:
        List of relationship dicts (same format as cross-figure detection)
    """
    import cv2

    if not pairs:
        return []

    # Cap the number of pairs
    pairs = pairs[:max_pairs]

    results = []
    for pair in pairs:
        pair_id = pair.get("pair_id", "")
        source_path = pair.get("source", "")
        target_path = pair.get("target", "")

        # Resolve paths
        src_full = Path(source_path)
        if not src_full.is_absolute():
            src_full = workdir / source_path

        tgt_full = Path(target_path)
        if not tgt_full.is_absolute():
            tgt_full = workdir / target_path

        if not src_full.exists() or not tgt_full.exists():
            logger.warning(f"Rotation detection: missing files for pair {pair_id}")
            continue

        # Load images
        try:
            img_a = cv2.imread(str(src_full))
            img_b = cv2.imread(str(tgt_full))
        except Exception as e:
            logger.warning(f"Failed to load images for pair {pair_id}: {e}")
            continue

        if img_a is None or img_b is None:
            logger.warning(f"cv2.imread returned None for pair {pair_id}")
            continue

        # Run rotation detection
        result = detect_copy_move_rotation(img_a, img_b, min_matches=min_matches)

        if result is None:
            continue

        inlier_count = result["inlier_count"]
        angle = result["angle"]
        scale = result["scale"]
        is_flipped = result["is_flipped"]

        # Compute score based on inlier count (normalize to [0, 1])
        # Cap at 200 inliers for score=1.0
        score = min(1.0, inlier_count / 200.0)

        if score < min_score:
            continue

        # Build relationship dict
        relationship = {
            "pair_id": pair_id,
            "source_figure_id": pair.get("source_figure_id", ""),
            "target_figure_id": pair.get("target_figure_id", ""),
            "success": True,
            "found_forgery": True,
            "matched_keypoints": inlier_count,
            "inlier_count": inlier_count,
            "score": round(score, 4),
            "is_flipped": is_flipped,
            "flip_detected": is_flipped,
            "rotation_angle": round(angle, 2),
            "scale_factor": round(scale, 4),
            "transform_matrix": result["transform_matrix"],
            "detection_mode": "rotation_affine",
            "metadata": {
                "rotation_angle": round(angle, 2),
                "scale_factor": round(scale, 4),
                "is_flipped": is_flipped,
                "inlier_count": inlier_count,
                "detection_method": "SIFT+RANSAC_affine",
            },
        }

        results.append(relationship)

    return results
