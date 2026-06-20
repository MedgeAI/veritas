"""Content-Based Image Retrieval (CBIR) search over extracted panels.

Computes per-panel feature vectors from image color histograms and retrieves
similar panel pairs via cosine similarity.  The pipeline:

1. Load panel_evidence; filter out panels without resolvable image paths.
2. For each panel image, compute an HSV color histogram feature vector.
3. Normalize feature vectors to unit length for cosine similarity.
4. For each panel, find the top-k most similar other panels.
5. Filter pairs by min_score and emit ``visual/cbir_search.json``.

Failure isolation: any exception is caught and recorded as a limitation;
the tool never blocks the audit pipeline.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
from typing import Any

from PIL import Image

from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

# HSV histogram bins: H=12, S=4, V=4 => 192-dim vector
_H_HIST_BINS = 12
_S_HIST_BINS = 4
_V_HIST_BINS = 4
_FEATURE_DIM = _H_HIST_BINS * _S_HIST_BINS * _V_HIST_BINS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_valid_panel(panel: dict[str, Any]) -> bool:
    """Check that a panel has required IDs and a resolvable image path."""
    return bool(panel.get("panel_id")) and bool(_panel_image_path(panel))


def _panel_image_path(panel: dict[str, Any]) -> Path | None:
    """Resolve the image path from panel evidence (crop_path or source_image_path)."""
    for key in ("crop_path", "source_image_path"):
        raw = panel.get(key)
        if raw:
            return Path(str(raw))
    return None


def _compute_hsv_histogram(img: Image.Image) -> list[float]:
    """Compute a normalized HSV color histogram as a flat list of floats."""
    hsv = img.convert("HSV").resize((64, 64))
    pixels = list(hsv.getdata())
    hist = [0.0] * _FEATURE_DIM
    total = len(pixels)
    if total == 0:
        return hist
    for h_raw, s_raw, v_raw in pixels:
        h_bin = min(int(h_raw * _H_HIST_BINS / 256), _H_HIST_BINS - 1)
        s_bin = min(int(s_raw * _S_HIST_BINS / 256), _S_HIST_BINS - 1)
        v_bin = min(int(v_raw * _V_HIST_BINS / 256), _V_HIST_BINS - 1)
        idx = h_bin * (_S_HIST_BINS * _V_HIST_BINS) + s_bin * _V_HIST_BINS + v_bin
        hist[idx] += 1.0
    # Normalize to unit vector for cosine similarity
    norm = math.sqrt(sum(x * x for x in hist))
    if norm > 0:
        hist = [x / norm for x in hist]
    return hist


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two unit vectors (dot product)."""
    return sum(x * y for x, y in zip(a, b))


def _resolve_panel_image_path(panel: dict[str, Any], workdir: Path) -> Path | None:
    """Resolve a panel's image path relative to the workdir."""
    raw_path = _panel_image_path(panel)
    if raw_path is None:
        return None
    if raw_path.is_absolute():
        return raw_path if raw_path.exists() else None
    candidate = workdir / raw_path
    if candidate.exists():
        return candidate
    # Try under visual/ subdirectory
    visual_candidate = workdir / "visual" / raw_path.name
    if visual_candidate.exists():
        return visual_candidate
    return None


def _empty_result(
    *,
    status: str = "skipped",
    errors: list[str] | None = None,
    limitations: list[str] | None = None,
    workdir: Path | None = None,
    skipped_panels: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/cbir_search.py",
        "status": status,
        "method": "hsv_histogram_cosine",
        "panel_count": 0,
        "skipped_panels": skipped_panels,
        "pair_count": 0,
        "pairs": [],
        "errors": errors or [],
        "limitations": limitations or [],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_cbir_search(
    panels: list[dict[str, Any]],
    *,
    workdir: Path,
    top_k: int = 5,
    min_score: float = 0.70,
    max_pairs: int = 500,
) -> dict[str, Any]:
    """Run CBIR search over a list of panel evidence entries.

    Parameters
    ----------
    panels:
        List of panel evidence dicts, each with ``panel_id`` and a resolvable
        image path (``crop_path`` or ``source_image_path``).
    workdir:
        Working directory for resolving relative image paths.
    top_k:
        Number of most similar panels to retrieve per panel.
    min_score:
        Minimum cosine similarity score to emit a pair.
    max_pairs:
        Maximum number of pairs to emit.

    Returns
    -------
    dict
        Structured CBIR result with ``pairs`` list.
    """
    errors: list[str] = []
    limitations: list[str] = []

    if not panels:
        return _empty_result(errors=["No panel evidence provided."], skipped_panels=0)

    # Build (panel_id, figure_id, feature_vector) index
    index: list[tuple[str, str, list[float]]] = []
    skipped = 0
    for panel in panels:
        if not _is_valid_panel(panel):
            skipped += 1
            continue
        img_path = _resolve_panel_image_path(panel, workdir)
        if img_path is None:
            skipped += 1
            continue
        try:
            with Image.open(img_path) as img:
                features = _compute_hsv_histogram(img)
        except Exception as exc:
            errors.append(f"Failed to process {img_path}: {exc}")
            skipped += 1
            continue
        panel_id = str(panel["panel_id"])
        figure_id = str(panel.get("parent_figure_id") or "")
        index.append((panel_id, figure_id, features))

    if len(index) < 2:
        return _empty_result(
            status="ran",
            errors=errors,
            limitations=[
                "Fewer than 2 panels had valid images; CBIR search cannot produce pairs."
            ],
            skipped_panels=skipped,
        )

    # Compute pairwise similarities and collect top-k per panel
    seen: set[tuple[str, str]] = set()
    pairs: list[dict[str, Any]] = []

    for i, (pid_i, fid_i, feat_i) in enumerate(index):
        # Compute similarities to all other panels
        scores: list[tuple[int, float]] = []
        for j, (pid_j, fid_j, feat_j) in enumerate(index):
            if i == j:
                continue
            sim = _cosine_similarity(feat_i, feat_j)
            if sim >= min_score:
                scores.append((j, sim))
        # Sort by descending similarity, take top_k
        scores.sort(key=lambda x: -x[1])
        for j, sim in scores[:top_k]:
            pid_j, fid_j, _ = index[j]
            pair_key = (min(pid_i, pid_j), max(pid_i, pid_j))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            pairs.append(
                {
                    "source_panel_id": pid_i,
                    "source_figure_id": fid_i,
                    "target_panel_id": pid_j,
                    "target_figure_id": fid_j,
                    "score": round(sim, 6),
                    "method": "hsv_histogram_cosine",
                    "feature_dim": _FEATURE_DIM,
                    "source_type": "cbir_similar",
                    "manual_review_needed": True,
                }
            )
            if len(pairs) >= max_pairs:
                break
        if len(pairs) >= max_pairs:
            break

    if skipped > 0:
        limitations.append(
            f"{skipped} panels were skipped due to missing or unresolvable image paths."
        )
    limitations.append(
        "CBIR candidates are triage leads based on global color distribution similarity; "
        "they do not imply local region reuse and require manual review."
    )

    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/cbir_search.py",
        "status": "ran",
        "method": "hsv_histogram_cosine",
        "inputs": {
            "top_k": top_k,
            "min_score": min_score,
            "max_pairs": max_pairs,
            "feature_dim": _FEATURE_DIM,
        },
        "panel_count": len(index),
        "skipped_panels": skipped,
        "pair_count": len(pairs),
        "pairs": pairs,
        "errors": errors,
        "limitations": limitations,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CBIR search: find similar panels via color histogram cosine similarity."
    )
    parser.add_argument("panel_json", help="Path to panel_evidence.json")
    parser.add_argument(
        "--figure-json",
        help="Path to visual evidence.json (unused, kept for interface consistency).",
    )
    parser.add_argument("--output", required=True, help="Output JSON path.")
    parser.add_argument(
        "--workdir", required=True, help="Working directory for image path resolution."
    )
    parser.add_argument(
        "--top-k", type=int, default=5, help="Number of most similar panels per panel."
    )
    parser.add_argument(
        "--min-score", type=float, default=0.70, help="Minimum cosine similarity score."
    )
    parser.add_argument(
        "--max-pairs", type=int, default=500, help="Maximum number of pairs to emit."
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    panel_json = Path(args.panel_json).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    workdir = Path(args.workdir).expanduser().resolve()

    try:
        panels_data = json.loads(panel_json.read_text(encoding="utf-8"))
    except Exception as exc:
        result = _empty_result(
            status="failed", errors=[f"Failed to read panel evidence: {exc}"]
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        return 1

    panels_list = (
        panels_data.get("panels", panels_data)
        if isinstance(panels_data, dict)
        else panels_data
    )

    result = run_cbir_search(
        panels_list,
        workdir=workdir,
        top_k=args.top_k,
        min_score=args.min_score,
        max_pairs=args.max_pairs,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "status": result["status"],
                "pair_count": result["pair_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
