"""Tests for engine.investigation.context_pack — bounded context builder."""
from __future__ import annotations

import json
from pathlib import Path

from engine.investigation.agent_models import TruncationConfig
from engine.investigation.context_pack import (
    build_context_pack_for_role,
    build_material_inventory_context_pack,
    build_review_context_pack,
    estimate_tokens,
    head_tail_truncate,
)


def _write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _make_workdir_with_findings(tmp_path: Path) -> Path:
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    _write_json(workdir / "material_inventory.json", {
        "summary": {"file_count": 5, "by_material_type": {"source_data": 2}},
        "limitations": ["No code environment provided"],
    })
    _write_json(workdir / "agent_material_plan.json", {
        "status": "ok",
        "selected_optional_lanes": [],
        "limitations": [],
    })
    _write_json(workdir / "source_data_findings.json", {
        "summary": {"total_findings": 10},
        "priority_findings": [
            {
                "finding_id": "FD-001",
                "risk_level": "high",
                "category": "duplicate_columns",
                "workbook": "source.xlsx",
                "sheet": "Fig1",
                "column_pair": ["A", "B"],
                "relationship_value": None,
                "benign_explanations": ["Manual copy-paste error"],
            },
            {
                "finding_id": "FD-002",
                "risk_level": "medium",
                "category": "fixed_difference",
                "workbook": "source.xlsx",
                "sheet": "Fig2",
                "column_pair": ["C", "D"],
                "relationship_value": 3.0,
                "benign_explanations": ["Derived column"],
            },
        ],
        "limitations": [],
    })
    _write_json(workdir / "source_data_pair_forensics.json", {
        "summary": {"total_findings": 3},
        "priority_findings": [
            {
                "finding_id": "PF-001",
                "risk_level": "high",
                "category": "row_offset",
                "workbook": "source.xlsx",
                "sheet": "Fig3",
                "support_rate": 0.98,
                "sample_pairs": [[1, 5], [2, 6]],
            },
        ],
        "limitations": [],
    })
    _write_json(workdir / "numeric_forensics.json", {
        "all_number_count": 500,
        "number_count": 480,
        "table_count": 8,
        "benford": {"applicability": "applicable", "mad": 0.012},
        "limitations": [],
    })
    (workdir / "full.md").write_text(
        "# Paper Title\n\nSome content.\n" * 100, encoding="utf-8",
    )
    (workdir / "evidence_ledger.json").write_text(
        json.dumps({"stats": {"total": 50}, "items": [], "warnings": []}),
        encoding="utf-8",
    )
    return workdir


def test_estimate_tokens_basic() -> None:
    assert estimate_tokens("hello world") == 2


def test_head_tail_truncate_short_text_unchanged() -> None:
    text = "short text within budget"
    assert head_tail_truncate(text, max_tokens=100_000) == text


def test_head_tail_truncate_long_text_truncated() -> None:
    text = "A" * 100_000
    result = head_tail_truncate(text, max_tokens=100)
    assert "[...truncated...]" in result
    assert len(result) < len(text)


def test_head_tail_truncate_preserves_structure() -> None:
    lines = [f"line-{i:04d}" for i in range(1000)]
    text = "\n".join(lines)
    result = head_tail_truncate(text, max_tokens=100)
    assert "line-0000" in result
    assert "line-0999" in result
    assert "[...truncated...]" in result


def test_context_pack_token_budget_enforced() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)
        big_text = "X" * 800_000
        (workdir / "full.md").write_text(big_text, encoding="utf-8")
        _write_json(workdir / "material_inventory.json", {"summary": {}})

        config = TruncationConfig(max_tokens_per_pack=200_000, max_tokens_per_excerpt=50_000)
        pack = build_context_pack_for_role("claim_extractor", workdir, "test-case", config=config)

        total = estimate_tokens(json.dumps(pack.to_dict(), ensure_ascii=False))
        assert total <= 200_000 + 5000


def test_context_pack_excludes_raw_pdfs() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)
        (workdir / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
        _write_json(workdir / "material_inventory.json", {"summary": {}})

        pack = build_context_pack_for_role("claim_extractor", workdir, "test-case")
        artifact_ids = [m["id"] for m in pack.artifact_manifest]
        assert "paper.pdf" not in artifact_ids


def test_context_pack_excludes_images() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)
        (workdir / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (workdir / "fig2.jpg").write_bytes(b"\xff\xd8\xff")
        _write_json(workdir / "material_inventory.json", {"summary": {}})

        pack = build_context_pack_for_role("claim_extractor", workdir, "test-case")
        artifact_ids = [m["id"] for m in pack.artifact_manifest]
        assert "fig1.png" not in artifact_ids
        assert "fig2.jpg" not in artifact_ids


def test_build_review_context_pack_with_findings() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        workdir = _make_workdir_with_findings(Path(td))

        pack = build_review_context_pack(workdir, "test-case")

        assert len(pack.top_n_findings) >= 2
        assert any(f.get("finding_id") == "FD-001" for f in pack.top_n_findings)
        assert "full.md" in pack.bounded_excerpts
        assert "source_data_findings.json" in pack.bounded_excerpts
        assert len(pack.limitations) >= 1
        assert "No code environment provided" in pack.limitations


def test_build_role_context_pack_claim_extractor() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        workdir = _make_workdir_with_findings(Path(td))

        pack = build_context_pack_for_role("claim_extractor", workdir, "test-case")

        excerpt_keys = set(pack.bounded_excerpts.keys())
        assert "full.md" in excerpt_keys
        assert "evidence_ledger.json" in excerpt_keys
        assert "source_data_findings.json" in excerpt_keys
        assert "material_inventory.json" in excerpt_keys
        assert len(pack.evidence_refs) >= 1


def test_context_pack_serialization_roundtrip() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        workdir = _make_workdir_with_findings(Path(td))

        pack = build_context_pack_for_role("judge", workdir, "test-case")

        d = pack.to_dict()
        json_bytes = json.dumps(d, ensure_ascii=False).encode("utf-8")
        restored = json.loads(json_bytes.decode("utf-8"))

        assert restored["case_id"] if "case_id" in restored else True
        assert isinstance(restored["artifact_manifest"], list)
        assert isinstance(restored["evidence_refs"], list)
        assert isinstance(restored["top_n_findings"], list)
        assert isinstance(restored["limitations"], list)
        assert isinstance(restored["bounded_excerpts"], dict)
        assert isinstance(restored["truncation_config"], dict)
        assert restored["truncation_config"]["max_tokens_per_pack"] == 40_000
        assert restored["truncation_config"]["max_tokens_per_excerpt"] == 8_000
        assert restored["truncation_config"]["strategy"] == "head_tail"


def test_build_role_context_pack_judge_uses_compact_summary_only() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        workdir = _make_workdir_with_findings(Path(td))
        _write_json(workdir / "agent_claim_extractor.json", {
            "schema_version": "1.0",
            "role_id": "claim_extractor",
            "case_id": "test-case",
            "status": "ran",
            "claims": [
                {
                    "claim_id": "AC-001",
                    "claim_text": "Figure 1 shows the reported Source Data trend.",
                    "claim_type": "figure_trace",
                    "paper_location": "Figure 1",
                    "evidence_refs": ["figure:1"],
                    "status": "needs_review",
                }
            ],
            "limitations": ["Claim extraction was bounded."],
        })
        _write_json(workdir / "agent_source_data_auditor.json", {
            "schema_version": "1.0",
            "role_id": "source_data_auditor",
            "case_id": "test-case",
            "status": "ran",
            "claim_to_source_data": [
                {
                    "claim_id": "AC-001",
                    "mapping_id": "MAP-001",
                    "source_data_refs": ["source.xlsx", "Fig1"],
                    "confidence": "medium",
                    "needs_human_review": True,
                }
            ],
            "finding_reviews": [
                {
                    "finding_id": "PF-001",
                    "assessment": "manual_review_required",
                    "residual_risk": "high",
                    "benign_explanations": ["Derived ratio could explain the reuse."],
                    "evidence_refs": ["source_data_pair_forensics.json:PF-001"],
                }
            ],
            "manual_review_tasks": [
                {
                    "task_id": "MR-001",
                    "priority": "high",
                    "question": "Ask the student to explain the repeated ratio pattern.",
                    "evidence_refs": ["source_data_pair_forensics.json:PF-001"],
                }
            ],
            "limitations": ["Source Data review was bounded."],
        })
        _write_json(workdir / "source_data_pair_forensics.json", {
            "summary": {"total_findings": 60},
            "priority_findings": [
                {
                    "finding_id": f"PF-{idx:03d}",
                    "risk_level": "high",
                    "category": "paired_ratio_reuse",
                    "workbook": "source.xlsx",
                    "sheet": "Fig1",
                    "support_rate": 0.99,
                    "sample_pairs": [[1, 2], [3, 4]],
                    "large_payload": "X" * 4000,
                }
                for idx in range(60)
            ],
            "limitations": [],
        })

        pack = build_context_pack_for_role("judge", workdir, "test-case")

        assert set(pack.bounded_excerpts) == {"judge_context_summary.json"}
        assert "source_data_pair_forensics.json" not in pack.bounded_excerpts
        excerpt = pack.bounded_excerpts["judge_context_summary.json"]
        assert "large_payload" not in excerpt
        summary = json.loads(excerpt)
        assert summary["contract"]["output_limits"]["risk_suggestions"] == 8
        assert summary["role_outputs"]["claim_extractor"]["claim_count"] == 1
        assert summary["role_outputs"]["source_data_auditor"]["manual_review_task_count"] == 1
        assert summary["deterministic_artifact_summaries"]["source_data_pair_forensics"] == {"total_findings": 60}
        assert pack.truncation_config.max_tokens_per_pack == 40_000


def test_build_material_inventory_context_pack() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)
        _write_json(workdir / "material_inventory.json", {
            "summary": {"file_count": 3, "by_material_type": {"source_data": 1}},
            "limitations": ["Missing source data for experiment 3"],
        })

        pack = build_material_inventory_context_pack(workdir, "test-case")

        assert "material_inventory.json" in pack.bounded_excerpts
        assert "Missing source data for experiment 3" in pack.limitations
        assert pack.top_n_findings == []
        assert pack.evidence_refs == []
