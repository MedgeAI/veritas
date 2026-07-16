from __future__ import annotations

import json

import pytest

from engine.exceptions import AmbiguousPaperPdfError, InvalidPaperPdfError
from engine.static_audit.cli_driver import discover_pdf


def _pdf(path) -> None:
    path.write_bytes(b"%PDF-1.4\n")


def test_discover_pdf_single_pdf_is_deterministic(tmp_path):
    paper = tmp_path / "paper.pdf"
    _pdf(paper)

    selection = discover_pdf(tmp_path)

    assert selection.path == paper.resolve()
    assert selection.relative_path == "paper.pdf"
    assert selection.source == "single_pdf"
    assert [candidate.relative_path for candidate in selection.candidates] == [
        "paper.pdf"
    ]


def test_discover_pdf_explicit_relative_path_wins(tmp_path):
    _pdf(tmp_path / "supplement.pdf")
    paper = tmp_path / "main.pdf"
    _pdf(paper)

    selection = discover_pdf(tmp_path, explicit_pdf="main.pdf")

    assert selection.path == paper.resolve()
    assert selection.source == "explicit"


def test_discover_pdf_manifest_selects_paper(tmp_path):
    _pdf(tmp_path / "supplement.pdf")
    paper = tmp_path / "paper.pdf"
    _pdf(paper)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"paper_pdf": "paper.pdf"}),
        encoding="utf-8",
    )

    selection = discover_pdf(tmp_path)

    assert selection.path == paper.resolve()
    assert selection.source == "manifest"


def test_discover_pdf_multiple_without_selection_fails_loud(tmp_path):
    _pdf(tmp_path / "a.pdf")
    _pdf(tmp_path / "b.pdf")

    with pytest.raises(AmbiguousPaperPdfError):
        discover_pdf(tmp_path)


@pytest.mark.parametrize("declared", ["/tmp/paper.pdf", "../paper.pdf", "paper.txt"])
def test_discover_pdf_rejects_unsafe_explicit_paths(tmp_path, declared):
    _pdf(tmp_path / "paper.pdf")

    with pytest.raises(InvalidPaperPdfError):
        discover_pdf(tmp_path, explicit_pdf=declared)


def test_discover_pdf_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.pdf"
    _pdf(outside)
    try:
        (tmp_path / "link.pdf").symlink_to(outside)
        with pytest.raises(InvalidPaperPdfError):
            discover_pdf(tmp_path)
    finally:
        outside.unlink(missing_ok=True)
