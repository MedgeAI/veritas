"""Deployment Dockerfile contract tests."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_image_copies_shared_runtime_packages() -> None:
    dockerfile = (PROJECT_ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")

    required_copy_lines = [
        "COPY cli/ ./cli/",
        "COPY common/ ./common/",
        "COPY engine/ ./engine/",
        "COPY runtime/ ./runtime/",
        "COPY configs/ ./configs/",
        "COPY web/backend/ ./web/backend/",
        "COPY scripts/ ./scripts/",
    ]

    for line in required_copy_lines:
        assert line in dockerfile
