from __future__ import annotations

import json

from engine.static_audit.models import EvidenceItem
from engine.static_audit.orchestrator import collect_claims_and_findings, resolve_artifact_path


def write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_agent_refined_mapping_is_canonical_over_deterministic_scaffolding(tmp_path) -> None:
    write_json(
        resolve_artifact_path(tmp_path, "source_data_findings.json"),
        {
            "claim_to_source_data": [
                {
                    "mapping_id": "CM-0001",
                    "source_figure_id": "Fig.1a",
                    "workbook": "source.xlsx",
                    "sheet": "Fig.1a",
                    "candidate_claims": [{"text": "truncated deterministic candidate"}],
                    "linked_priority_findings": [{"finding_id": "FD-0001"}],
                    "mapping_confidence": "high",
                }
            ],
            "priority_findings": [
                {
                    "finding_id": "FD-0001",
                    "category": "fixed_difference",
                    "risk_level": "medium",
                    "workbook": "source.xlsx",
                    "sheet": "Fig.1a",
                    "benign_explanations": [],
                    "pressure_test_result": "needs_review",
                }
            ],
        },
    )
    write_json(
        resolve_artifact_path(tmp_path, "agent_claim_extractor.json"),
        {
            "claims": [
                {
                    "claim_id": "AC-001",
                    "claim_text": "Agent refined biological claim.",
                    "claim_type": "numeric",
                    "paper_location": "full.md:12",
                    "evidence_refs": ["CM-0001"],
                    "status": "needs_review",
                }
            ]
        },
    )
    write_json(
        resolve_artifact_path(tmp_path, "agent_source_data_auditor.json"),
        {
            "claim_to_source_data": [
                {
                    "claim_id": "AC-001",
                    "mapping_id": "CM-0001",
                    "source_data_refs": ["source.xlsx/Fig.1a"],
                    "confidence": "medium",
                    "needs_human_review": True,
                }
            ]
        },
    )

    claims, mappings, findings = collect_claims_and_findings(
        tmp_path,
        [
            EvidenceItem(
                evidence_id="EV-SD-0001",
                kind="sheet",
                source_path="source.xlsx",
                metadata={"finding_id": "FD-0001"},
            )
        ],
    )

    assert claims[0].claim_id == "AC-001"
    assert claims[0].text == "Agent refined biological claim."
    assert claims[0].metadata["canonical_source"] == "agent_refined"
    assert mappings[0].claim_id == "AC-001"
    assert mappings[0].status == "agent_refined_mapping"
    assert mappings[0].metadata["deterministic_mapping"]["source_figure_id"] == "Fig.1a"
    assert findings[0].evidence_refs == ["EV-SD-0001"]
