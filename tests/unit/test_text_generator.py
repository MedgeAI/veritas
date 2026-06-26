"""Tests for engine/reporting/text_generator.py — LLM text enrichment."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from engine.reporting.text_generator import (
    FindingLLMContext,
    _build_finding_context,
    _build_llm_prompt,
    _select_top_findings,
    _validate_response,
    enrich_bundle_with_llm_text,
)
from engine.static_audit.models import (
    Claim,
    ClaimMapping,
    EvidenceItem,
    Finding,
    StaticAuditBundle,
)
from tests.conftest import MockLLMClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_finding() -> Finding:
    return Finding(
        finding_id="F-001",
        category="fixed_difference",
        risk_level="high",
        summary="固定差关系",
        issue_category="consistency",
        evidence_refs=["E-001"],
        claim_refs=["C-001"],
        metadata={
            "sheet": "Table S1",
            "workbook": "source.xlsx",
            "column_pair": ["D", "E"],
            "row_offset": 3,
            "relationship_value": 0.3,
            "support_rate": 1.0,
            "pattern_strength": "complete",
        },
    )


@pytest.fixture
def sample_bundle(sample_finding: Finding) -> StaticAuditBundle:
    return StaticAuditBundle(
        case_id="test-case",
        inputs={"paper_dir": "/tmp/paper"},
        claims=[
            Claim(claim_id="C-001", text="Treatment changes endpoint.", claim_type="experimental"),
        ],
        findings=[
            sample_finding,
            Finding(
                finding_id="F-002",
                category="fixed_difference",
                risk_level="medium",
                summary="另一个固定差",
                metadata={"sheet": "Table S2"},
            ),
            Finding(
                finding_id="F-003",
                category="duplicate_row_vector",
                risk_level="critical",
                summary="行向量重复",
            ),
        ],
        claim_mappings=[
            ClaimMapping(
                mapping_id="M-001",
                claim_id="C-001",
                evidence_refs=["E-001"],
                confidence="high",
                finding_refs=["F-001"],
            ),
        ],
        evidence_items=[
            EvidenceItem(
                evidence_id="E-001",
                kind="sheet",
                source_path="source.xlsx",
                summary="Sheet: Table S1",
            ),
        ],
    )


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """Create a minimal workdir with empty artifacts."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "source_data_auditor.json").write_text(json.dumps({
        "finding_reviews": [
            {
                "finding_id": "F-001",
                "benign_explanations": ["可能是公式派生列"],
                "next_steps": ["核对列定义"],
            }
        ],
    }))
    (agents_dir / "judge.json").write_text(json.dumps({
        "risk_suggestions": [
            {
                "finding_ids": ["F-001"],
                "reason": "固定关系需人工确认",
                "risk_level": "high",
                "requires_human_review": True,
            }
        ],
    }))
    return tmp_path


# ---------------------------------------------------------------------------
# _build_finding_context
# ---------------------------------------------------------------------------

class TestBuildFindingContext:
    def test_extracts_metadata_fields(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        assert ctx.finding_id == "F-001"
        assert ctx.category == "fixed_difference"
        assert ctx.risk_level == "high"
        assert ctx.sheet == "Table S1"
        assert ctx.workbook == "source.xlsx"
        assert ctx.columns == ["D", "E"]
        assert ctx.row_offset == 3
        assert ctx.relationship_value == 0.3
        assert ctx.support_rate == 1.0
        assert ctx.pattern_strength == "complete"

    def test_resolves_claims_via_mapping(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        assert len(ctx.related_claims) == 1
        assert ctx.related_claims[0]["claim_id"] == "C-001"
        assert "Treatment" in ctx.related_claims[0]["text"]

    def test_resolves_evidence_items(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        assert len(ctx.evidence_items) == 1
        assert ctx.evidence_items[0]["evidence_id"] == "E-001"

    def test_resolves_agent_source_review(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        assert ctx.agent_source_review is not None
        assert "公式派生" in ctx.agent_source_review["benign_explanations"][0]

    def test_resolves_agent_judge_risk(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        assert ctx.agent_judge_risk is not None
        assert ctx.agent_judge_risk["requires_human_review"] is True

    def test_sibling_count(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        # F-002 has same category "fixed_difference", F-003 is different
        assert ctx.sibling_count == 1

    def test_to_prompt_dict_excludes_empty(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        d = ctx.to_prompt_dict()
        assert "finding_id" in d
        assert "metadata" in d
        assert "related_claims" in d
        assert "evidence_items" in d


# ---------------------------------------------------------------------------
# _build_llm_prompt
# ---------------------------------------------------------------------------

class TestBuildLLMPrompt:
    def test_contains_constraints(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        prompt = _build_llm_prompt(ctx)
        assert "引用" in prompt
        assert "不预判学术不端" in prompt
        assert "JSON" in prompt

    def test_contains_finding_data(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        prompt = _build_llm_prompt(ctx)
        assert "F-001" in prompt
        assert "Table S1" in prompt
        assert "fixed_difference" in prompt


# ---------------------------------------------------------------------------
# _validate_response
# ---------------------------------------------------------------------------

class TestValidateResponse:
    def test_valid_response(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        response = {
            "review_question": "核对 Sheet Table S1 列 D、E 的固定差关系",
            "benign_explanations": ["可能是公式派生列"],
            "relation_text": "固定差 0.3，覆盖 35 行",
            "evidence_cited": ["E-001", "C-001"],
        }
        _validate_response(response, ctx)  # should not raise

    def test_missing_field_raises(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        response = {"review_question": "test"}  # missing other fields
        with pytest.raises(ValueError, match="Missing field"):
            _validate_response(response, ctx)

    def test_not_dict_raises(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        with pytest.raises(ValueError, match="not a dict"):
            _validate_response("not a dict", ctx)

    def test_evidence_cited_not_list_raises(self, sample_finding, sample_bundle, workdir):
        ctx = _build_finding_context(sample_finding, sample_bundle, workdir)
        response = {
            "review_question": "test",
            "benign_explanations": [],
            "relation_text": "test",
            "evidence_cited": "not a list",
        }
        with pytest.raises(ValueError, match="not a list"):
            _validate_response(response, ctx)


# ---------------------------------------------------------------------------
# _select_top_findings
# ---------------------------------------------------------------------------

class TestSelectTopFindings:
    def test_sorts_by_risk_priority(self, sample_bundle):
        top = _select_top_findings(sample_bundle.findings, max_findings=2)
        assert len(top) == 2
        # F-003 is critical (highest), F-001 is high
        assert top[0].finding_id == "F-003"
        assert top[1].finding_id == "F-001"

    def test_limits_to_max(self, sample_bundle):
        top = _select_top_findings(sample_bundle.findings, max_findings=1)
        assert len(top) == 1
        assert top[0].finding_id == "F-003"  # critical


# ---------------------------------------------------------------------------
# enrich_bundle_with_llm_text
# ---------------------------------------------------------------------------

class TestEnrichBundleWithLLMText:
    def test_success_writes_metadata(self, sample_bundle, workdir):
        llm_response = {
            "review_question": "核对 Table S1 列 D、E",
            "benign_explanations": ["公式派生"],
            "relation_text": "固定差 0.3",
            "evidence_cited": ["E-001"],
        }
        client = MockLLMClient(response=llm_response)
        enrich_bundle_with_llm_text(sample_bundle, workdir, client, max_findings=3)

        # All 3 findings should have llm_text
        for finding in sample_bundle.findings:
            assert "llm_text" in finding.metadata
            assert finding.metadata["llm_text"]["review_question"] == "核对 Table S1 列 D、E"
            assert finding.metadata["llm_text"]["model"] == "qwen3.7-plus"

    def test_failure_writes_error(self, sample_bundle, workdir):
        client = MockLLMClient(raise_error=True)
        enrich_bundle_with_llm_text(sample_bundle, workdir, client, max_findings=3)

        for finding in sample_bundle.findings:
            assert "llm_text" in finding.metadata
            assert "error" in finding.metadata["llm_text"]

    def test_skips_when_no_llm(self, sample_bundle, workdir):
        result = enrich_bundle_with_llm_text(sample_bundle, workdir, None)
        assert result is sample_bundle
        # No metadata should be written
        for finding in sample_bundle.findings:
            assert "llm_text" not in finding.metadata

    def test_limits_to_top_n(self, sample_bundle, workdir):
        client = MockLLMClient(response={
            "review_question": "test",
            "benign_explanations": [],
            "relation_text": "test",
            "evidence_cited": [],
        })
        enrich_bundle_with_llm_text(sample_bundle, workdir, client, max_findings=1)

        # Only 1 finding should have llm_text
        enriched = [f for f in sample_bundle.findings if "llm_text" in f.metadata]
        assert len(enriched) == 1
        assert enriched[0].finding_id == "F-003"  # critical risk

    def test_per_finding_failure_isolation(self, sample_bundle, workdir):
        """One finding's failure should not affect others."""
        call_count = 0
        original_chat_json = MockLLMClient.chat_json

        def flaky_chat_json(self_client, prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("transient failure")
            return {
                "review_question": "test",
                "benign_explanations": [],
                "relation_text": "test",
                "evidence_cited": [],
            }

        client = MockLLMClient()
        client.chat_json = lambda prompt, **kwargs: flaky_chat_json(client, prompt, **kwargs)

        enrich_bundle_with_llm_text(sample_bundle, workdir, client, max_findings=3)

        # First finding: success
        assert "review_question" in sample_bundle.findings[2].metadata.get("llm_text", {})  # F-003 (critical)
        # Second finding: error (call_count=2)
        # Third finding: success
        errors = [f for f in sample_bundle.findings if "error" in (f.metadata.get("llm_text") or {})]
        successes = [f for f in sample_bundle.findings if "review_question" in (f.metadata.get("llm_text") or {})]
        assert len(errors) == 1
        assert len(successes) == 2

    def test_empty_bundle(self, workdir):
        bundle = StaticAuditBundle(case_id="empty", inputs={})
        client = MockLLMClient()
        result = enrich_bundle_with_llm_text(bundle, workdir, client)
        assert result is bundle
        assert client.call_count == 0
