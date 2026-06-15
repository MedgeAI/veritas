"""ELIS KeypointCopyMoveDetector subprocess wrapper.

This module is invoked via ``python -m engine.static_audit.tools._elis_copy_move_runner``
and acts as a bridge between Veritas and the ELIS copy-move-detection-keypoint module.

It supports two modes:

- **single**: Run single-image copy-move detection on each panel independently.
  Detects regions copied within the same panel (e.g. a blot band duplicated).
- **cross**: Run cross-image copy detection on pre-selected figure pairs.
  Detects content shared between two images, with horizontal flip detection.

Input is JSON on stdin; output is JSON on stdout.

Input (single mode)::

    {
      "mode": "single",
      "panels": [{"panel_id": "PE-001", "path": "/abs/path.png"}, ...],
      "output_dir": "/path/to/output",
      "min_keypoints": 20,
      "min_area": 0.01
    }

Input (cross mode)::

    {
      "mode": "cross",
      "pairs": [{"pair_id": "001", "source": "...", "target": "..."}, ...],
      "output_dir": "/path/to/output",
      "min_keypoints": 20,
      "min_area": 0.01,
      "check_flip": true
    }

Output::

    {
      "results": [
        {"panel_id" or "pair_id": ..., "success": bool, "found_forgery": bool,
         "matched_keypoints": int, "shared_area_source": float,
         "shared_area_target": float, "is_flipped": bool, ...},
        ...
      ]
    }
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ELIS_KEYPOINT_SRC = _REPO_ROOT / "third_party" / "elis" / "system_modules" / "copy-move-detection-keypoint" / "src"


def _setup_elis_path() -> None:
    """Add ELIS keypoint src/ to sys.path so detector imports work."""
    src = str(ELIS_KEYPOINT_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)


def _run_single(panels: list[dict[str, str]], output_dir: str, min_keypoints: int, min_area: float) -> list[dict[str, Any]]:
    """Run single-image copy-move detection on each panel."""
    _setup_elis_path()
    from detector import KeypointCopyMoveDetector
    from feature_extraction import DescriptorType
    from matching import AlignmentStrategy, MatchingMethod

    detector = KeypointCopyMoveDetector(
        output_dir=output_dir,
        descriptor_type=DescriptorType.CV_RSIFT,
        alignment_strategy=AlignmentStrategy.CV_MAGSAC,
        matching_method=MatchingMethod.BF,
        check_flip=False,  # Not needed for single-image
        min_keypoints=min_keypoints,
        min_area=min_area,
    )

    results = []
    for panel in panels:
        panel_id = panel["panel_id"]
        path = panel["path"]
        try:
            result = detector.detect_single_image(path)
            results.append({
                "panel_id": panel_id,
                "success": result.get("success", False),
                "found_forgery": result.get("found_forgery", False),
                "matched_keypoints": result.get("matched_keypoints", 0),
                "num_clusters": result.get("num_clusters", 0),
                "mask_path": result.get("mask_path", ""),
                "matches_path": result.get("matches_path", ""),
                "clusters_path": result.get("clusters_path", ""),
                "error": result.get("error", ""),
            })
        except Exception as e:
            results.append({
                "panel_id": panel_id,
                "success": False,
                "found_forgery": False,
                "matched_keypoints": 0,
                "error": str(e),
            })
    return results


def _run_cross(pairs: list[dict[str, str]], output_dir: str, min_keypoints: int, min_area: float, check_flip: bool) -> list[dict[str, Any]]:
    """Run cross-image copy detection on each pair."""
    _setup_elis_path()
    from detector import KeypointCopyMoveDetector
    from feature_extraction import DescriptorType
    from matching import AlignmentStrategy, MatchingMethod

    detector = KeypointCopyMoveDetector(
        output_dir=output_dir,
        descriptor_type=DescriptorType.CV_RSIFT,
        alignment_strategy=AlignmentStrategy.CV_MAGSAC,
        matching_method=MatchingMethod.BF,
        check_flip=check_flip,
        min_keypoints=min_keypoints,
        min_area=min_area,
    )

    results = []
    for pair in pairs:
        pair_id = pair["pair_id"]
        source = pair["source"]
        target = pair["target"]
        try:
            result = detector.detect_cross_image(source, target)
            results.append({
                "pair_id": pair_id,
                "source_figure_id": pair.get("source_figure_id", ""),
                "target_figure_id": pair.get("target_figure_id", ""),
                "success": result.get("success", False),
                "found_forgery": result.get("found_forgery", False),
                "matched_keypoints": result.get("matched_keypoints", 0),
                "shared_area_source": result.get("shared_area_source", 0.0),
                "shared_area_target": result.get("shared_area_target", 0.0),
                "is_flipped": result.get("is_flipped", False),
                "num_clusters_source": result.get("num_clusters_source", 0),
                "num_clusters_target": result.get("num_clusters_target", 0),
                "mask_path": result.get("mask_path", ""),
                "matches_path": result.get("matches_path", ""),
                "clusters_path": result.get("clusters_path", ""),
                "error": result.get("error", ""),
            })
        except Exception as e:
            results.append({
                "pair_id": pair_id,
                "source_figure_id": pair.get("source_figure_id", ""),
                "target_figure_id": pair.get("target_figure_id", ""),
                "success": False,
                "found_forgery": False,
                "matched_keypoints": 0,
                "shared_area_source": 0.0,
                "shared_area_target": 0.0,
                "is_flipped": False,
                "error": str(e),
            })
    return results


def main() -> int:
    input_data = json.load(sys.stdin)
    mode = input_data.get("mode", "")
    output_dir = input_data.get("output_dir", "/tmp/elis_copy_move")
    min_keypoints = int(input_data.get("min_keypoints", 20))
    min_area = float(input_data.get("min_area", 0.01))

    os.makedirs(output_dir, exist_ok=True)

    if mode == "single":
        panels = input_data.get("panels", [])
        results = _run_single(panels, output_dir, min_keypoints, min_area)
    elif mode == "cross":
        pairs = input_data.get("pairs", [])
        check_flip = bool(input_data.get("check_flip", True))
        results = _run_cross(pairs, output_dir, min_keypoints, min_area, check_flip)
    else:
        results = []
        print(json.dumps({"error": f"Unknown mode: {mode}"}))
        return 1

    print(json.dumps({"results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
