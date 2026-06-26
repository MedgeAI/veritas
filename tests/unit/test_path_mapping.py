from __future__ import annotations

from pathlib import Path

from web.backend.veritas_web.path_mapping import normalize_workdir_path


def test_normalize_workdir_path_maps_docker_output_root(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "outputs"
    workdir = output_root / "paper4" / "research-integrity-audit"
    workdir.mkdir(parents=True)

    assert (
        normalize_workdir_path(
            "/app/outputs/paper4/research-integrity-audit",
            output_root=output_root,
        )
        == workdir
    )


def test_normalize_workdir_path_maps_workspace_output_root_without_existing_path(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "outputs"

    assert (
        normalize_workdir_path(
            "/workspace/outputs/case-a/research-integrity-audit",
            output_root=output_root,
        )
        == output_root / "case-a" / "research-integrity-audit"
    )
