from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def _normalize_path(value: str) -> str:
    """Normalize a file path for consistent lookups."""
    text = str(value or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text


def _build_path_to_panel_map(
    panel_evidence: list[dict] | None,
) -> dict[str, list[dict[str, str]]]:
    """Map image file paths to panel canonical IDs from panel evidence.

    Each panel evidence entry may carry *source_image_path* (the full figure
    the panel was cropped from) and *crop_path* (the panel crop itself).
    Multiple panels can originate from the same source image, so the map
    values are lists of ``{"panel_id": ..., "figure_id": ...}`` dicts
    deduplicated by panel_id.
    """
    if not panel_evidence:
        return {}
    raw: dict[str, dict[str, dict[str, str]]] = {}
    for panel in panel_evidence:
        if not isinstance(panel, dict):
            continue
        panel_id = str(panel.get("panel_id") or "")
        figure_id = str(panel.get("parent_figure_id") or "")
        if not panel_id:
            continue
        entry = {"panel_id": panel_id, "figure_id": figure_id}
        for path_key in ("source_image_path", "crop_path"):
            raw_path = panel.get(path_key)
            if raw_path:
                key = _normalize_path(raw_path)
                if key:
                    raw.setdefault(key, {})[panel_id] = entry
                    raw.setdefault(Path(key).name, {})[panel_id] = entry
    return {k: list(v.values()) for k, v in raw.items()}


def _resolve_panels_for_image(
    image_path: Path,
    path_to_panels: dict[str, list[dict[str, str]]],
    *,
    has_panel_evidence: bool,
) -> list[dict[str, str]] | None:
    """Resolve an image path to its panel canonical IDs.

    When *has_panel_evidence* is ``False`` (standalone CLI without panel
    extraction), returns a single pseudo-entry using the file stem so that
    the output schema remains consistent.  When panel evidence is available
    but the image cannot be resolved, returns ``None`` to signal that the
    candidate should be skipped.
    """
    if not has_panel_evidence:
        return [{"panel_id": image_path.stem, "figure_id": image_path.stem}]
    key = _normalize_path(str(image_path))
    panels = path_to_panels.get(key) or path_to_panels.get(image_path.name)
    return panels


def find_images(images_dir: Path) -> list[Path]:
    if not images_dir.is_dir():
        return []
    return [
        path
        for path in sorted(images_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def dhash(path: Path, hash_size: int = 8) -> int:
    from PIL import Image

    with Image.open(path) as image:
        resized = image.convert("L").resize((hash_size + 1, hash_size))
        pixels = list(resized.getdata())
    value = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            value = (value << 1) | int(left > right)
    return value


def generate_similarity_candidates(
    images_dir: Path,
    *,
    max_distance: int = 8,
    max_candidates: int = 200,
    panel_evidence: list[dict] | None = None,
) -> dict[str, Any]:
    images = find_images(images_dir)
    if not images:
        return {
            "schema_version": "2.0",
            "created_by": "engine/static_audit/tools/image_similarity.py",
            "status": "skipped",
            "method": "dhash",
            "inputs": {"images_dir": str(images_dir)},
            "image_count": 0,
            "candidate_count": 0,
            "candidates": [],
            "errors": [],
            "limitations": ["No image files were found."],
        }

    try:
        hashes = [(path, dhash(path)) for path in images]
    except ImportError:
        return {
            "schema_version": "2.0",
            "created_by": "engine/static_audit/tools/image_similarity.py",
            "status": "not_available",
            "method": "dhash",
            "inputs": {"images_dir": str(images_dir)},
            "image_count": len(images),
            "candidate_count": 0,
            "candidates": [],
            "errors": ["Pillow is not installed; near-duplicate image candidates were not computed."],
            "limitations": ["Install Pillow to enable deterministic dHash image similarity candidates."],
        }

    path_to_panels = _build_path_to_panel_map(panel_evidence)
    has_panel_evidence = bool(panel_evidence)

    candidates: list[dict[str, Any]] = []
    for idx, (left_path, left_hash) in enumerate(hashes):
        for right_path, right_hash in hashes[idx + 1 :]:
            distance = hamming_distance(left_hash, right_hash)
            if distance <= max_distance:
                left_panels = _resolve_panels_for_image(
                    left_path, path_to_panels, has_panel_evidence=has_panel_evidence,
                )
                right_panels = _resolve_panels_for_image(
                    right_path, path_to_panels, has_panel_evidence=has_panel_evidence,
                )
                if left_panels is None or right_panels is None:
                    continue
                for lp in left_panels:
                    for rp in right_panels:
                        candidates.append(
                            {
                                "source_figure_id": lp["figure_id"],
                                "source_panel_id": lp["panel_id"],
                                "target_figure_id": rp["figure_id"],
                                "target_panel_id": rp["panel_id"],
                                "method": "dhash",
                                "distance": distance,
                                "max_distance": max_distance,
                                "manual_review_needed": True,
                            }
                        )
                        if len(candidates) >= max_candidates:
                            break
                    if len(candidates) >= max_candidates:
                        break
                if len(candidates) >= max_candidates:
                    break
        if len(candidates) >= max_candidates:
            break

    return {
        "schema_version": "2.0",
        "created_by": "engine/static_audit/tools/image_similarity.py",
        "status": "ran",
        "method": "dhash",
        "inputs": {"images_dir": str(images_dir), "max_distance": max_distance},
        "image_count": len(images),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "errors": [],
        "limitations": [
            "dHash candidates are triage leads only; crops, rotations, contrast changes, and local reuse require visual or manual review.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find near-duplicate image candidates with dHash.")
    parser.add_argument("images_dir", help="Directory containing extracted paper images.")
    parser.add_argument("--output", required=True, help="Output JSON path.")
    parser.add_argument("--max-distance", type=int, default=8, help="Maximum dHash Hamming distance.")
    parser.add_argument("--max-candidates", type=int, default=200, help="Maximum candidate pairs to emit.")
    parser.add_argument(
        "--panel-evidence",
        help="Path to panel evidence JSON (or a JSON array) for canonical ID resolution.",
    )
    return parser.parse_args()


def _load_panel_evidence(path: str) -> list[dict]:
    """Load panel evidence from a JSON file (object with 'panels' key or bare array)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        panels = data.get("panels")
        if isinstance(panels, list):
            return panels
    return []


def main() -> int:
    args = parse_args()
    images_dir = Path(args.images_dir).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    panel_evidence = _load_panel_evidence(args.panel_evidence) if args.panel_evidence else None
    result = generate_similarity_candidates(
        images_dir,
        max_distance=args.max_distance,
        max_candidates=args.max_candidates,
        panel_evidence=panel_evidence,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "status": result["status"], "candidate_count": result["candidate_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

