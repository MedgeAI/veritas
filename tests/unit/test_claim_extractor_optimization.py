"""Tests for grounding_index and claim_enricher used by the claim_extractor pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from engine.static_audit.tools.grounding_index import (
    build_grounding_index,
    save_grounding_index,
)
from engine.static_audit.tools.claim_enricher import enrich_claims


def _write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# grounding_index tests
# ---------------------------------------------------------------------------


def test_build_grounding_index_from_full_md(tmp_path: Path) -> None:
    full_md = tmp_path / "full.md"
    full_md.write_text(
        "# Introduction\n\n"
        "As shown in Fig. 1, the results are significant.\n\n"
        "## Methods\n\n"
        "See Fig. 2a for the western blot.\n\n"
        "## Results\n\n"
        "Table 1 summarizes the data.\n",
        encoding="utf-8",
    )

    idx = build_grounding_index(full_md_path=full_md)

    assert "Fig. 1" in idx["figure_ids"]
    assert "Fig. 2a" in idx["figure_ids"]
    assert "Table 1" in idx["table_ids"]
    assert len(idx["sections"]) >= 1


def test_build_grounding_index_with_evidence_ledger(tmp_path: Path) -> None:
    full_md = tmp_path / "full.md"
    full_md.write_text("# Title\nSome text.\n", encoding="utf-8")

    ledger = {
        "figures": [{"label": "Fig. 3", "id": "f1"}],
        "indexes": {"by_figure_label": {"Fig. 3": ["f1"]}},
    }
    ledger_path = tmp_path / "evidence_ledger.json"
    _write_json(ledger_path, ledger)

    idx = build_grounding_index(
        full_md_path=full_md,
        evidence_ledger_path=ledger_path,
    )

    assert "Fig. 3" in idx["figure_ids"]


def test_build_grounding_index_missing_files(tmp_path: Path) -> None:
    idx = build_grounding_index(
        full_md_path=tmp_path / "nonexistent.md",
        evidence_ledger_path=tmp_path / "no_ledger.json",
        source_data_dir=tmp_path / "no_source_data",
    )

    assert isinstance(idx, dict)
    assert idx["figure_ids"] == []
    assert idx["table_ids"] == []
    assert idx["source_data_sheets"] == {}
    assert idx["sections"] == {}
    assert idx["figure_legend_lines"] == {}


def test_save_grounding_index_roundtrip(tmp_path: Path) -> None:
    full_md = tmp_path / "full.md"
    full_md.write_text("# Heading\nFig. 1 is here.\n", encoding="utf-8")

    idx = build_grounding_index(full_md_path=full_md)
    out_path = tmp_path / "grounding_index.json"
    save_grounding_index(idx, out_path)

    assert out_path.exists()
    restored = json.loads(out_path.read_text(encoding="utf-8"))
    assert restored["figure_ids"] == idx["figure_ids"]


# ---------------------------------------------------------------------------
# claim_enricher tests
# ---------------------------------------------------------------------------


def test_enrich_claims_basic(tmp_path: Path) -> None:
    raw_claims = [
        {
            "claim_text": "Fig. 1 shows X",
            "claim_type": "figure_trace",
            "mentioned_refs": ["Fig. 1"],
        }
    ]
    grounding_index = {
        "figure_ids": ["Fig. 1"],
        "table_ids": [],
        "source_data_sheets": [],
        "sections": {"1-10": "Results"},
        "figure_legend_lines": {},
    }

    result = enrich_claims(
        raw_claims=raw_claims,
        grounding_index=grounding_index,
        case_id="test-case",
    )

    assert result["schema_version"] == "1.0"
    assert result["role_id"] == "claim_extractor"
    assert result["case_id"] == "test-case"
    assert result["status"] == "ran"
    assert len(result["claims"]) == 1
    claim = result["claims"][0]
    assert claim["claim_id"] == "AC-001"
    assert claim["claim_decisiveness"] == "medium"
    assert claim["figure_refs"] == ["Fig. 1"]


def test_enrich_claims_source_data_mapping(tmp_path: Path) -> None:
    raw_claims = [
        {
            "claim_text": "Source Data Fig. 1 confirms the trend",
            "claim_type": "numeric",
            "mentioned_refs": ["Fig. 1"],
        }
    ]
    grounding_index = {
        "figure_ids": ["Fig. 1"],
        "table_ids": [],
        "source_data_sheets": ["Source Data Fig. 1"],
        "sections": {},
        "figure_legend_lines": {},
    }

    result = enrich_claims(
        raw_claims=raw_claims,
        grounding_index=grounding_index,
    )

    claim = result["claims"][0]
    assert "Source Data Fig. 1" in claim["expected_source_data"]
    assert claim["claim_decisiveness"] == "high"


def test_enrich_claims_empty_input() -> None:
    result = enrich_claims(raw_claims=[], grounding_index={})

    assert result["schema_version"] == "1.0"
    assert result["role_id"] == "claim_extractor"
    assert result["claims"] == []
    assert result["limitations"] == []


def test_enrich_claims_decisiveness_rules() -> None:
    grounding_index: dict = {
        "figure_ids": ["Fig. 1"],
        "table_ids": [],
        "source_data_sheets": ["Source Data Fig. 1"],
        "sections": {},
        "figure_legend_lines": {},
    }

    # numeric with source_data -> high
    numeric_with_sd = [
        {
            "claim_text": "The ratio is 2.5",
            "claim_type": "numeric",
            "mentioned_refs": ["Fig. 1"],
        }
    ]
    r1 = enrich_claims(raw_claims=numeric_with_sd, grounding_index=grounding_index)
    assert r1["claims"][0]["claim_decisiveness"] == "high"

    # numeric without source_data -> low
    numeric_no_sd = [
        {
            "claim_text": "The value is 42",
            "claim_type": "numeric",
            "mentioned_refs": [],
        }
    ]
    r2 = enrich_claims(
        raw_claims=numeric_no_sd,
        grounding_index={"figure_ids": [], "table_ids": [], "source_data_sheets": [], "sections": {}, "figure_legend_lines": {}},
    )
    assert r2["claims"][0]["claim_decisiveness"] == "low"

    # figure_trace -> medium
    figure_trace = [
        {
            "claim_text": "Fig. 1 shows the band",
            "claim_type": "figure_trace",
            "mentioned_refs": ["Fig. 1"],
        }
    ]
    r3 = enrich_claims(raw_claims=figure_trace, grounding_index=grounding_index)
    assert r3["claims"][0]["claim_decisiveness"] == "medium"


def test_enrich_claims_with_full_md_location(tmp_path: Path) -> None:
    full_md = tmp_path / "full.md"
    full_md.write_text(
        "# Introduction\n\n"
        "Some background text.\n\n"
        "## Results\n\n"
        "Fig. 1 shows X and the ratio is 2.5.\n",
        encoding="utf-8",
    )

    raw_claims = [
        {
            "claim_text": "Fig. 1 shows X and the ratio is 2.5.",
            "claim_type": "numeric",
            "mentioned_refs": ["Fig. 1"],
        }
    ]
    grounding_index = {
        "figure_ids": ["Fig. 1"],
        "table_ids": [],
        "source_data_sheets": [],
        "sections": {"1-3": "Introduction", "4-6": "Results"},
        "figure_legend_lines": {},
    }

    result = enrich_claims(
        raw_claims=raw_claims,
        grounding_index=grounding_index,
        full_md_path=full_md,
    )

    claim = result["claims"][0]
    assert claim["paper_location"] != ""
    assert "line" in claim["paper_location"]
