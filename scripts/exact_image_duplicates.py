#!/usr/bin/env python3
"""Find byte-identical image duplicates by SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find byte-identical image duplicates.")
    parser.add_argument("image_root", help="Directory containing extracted images.")
    parser.add_argument("--output", required=True, help="Output JSON path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.image_root).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    groups: dict[str, list[str]] = {}
    image_paths = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    for path in image_paths:
        groups.setdefault(sha256(path), []).append(str(path))
    duplicate_groups = [paths for paths in groups.values() if len(paths) > 1]
    result = {
        "image_count": len(image_paths),
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_image_count": sum(len(paths) for paths in duplicate_groups),
        "duplicate_groups": duplicate_groups,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), **{k: result[k] for k in result if k != "duplicate_groups"}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
