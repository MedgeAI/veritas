from __future__ import annotations

from pathlib import Path

from engine.investigation.agent_models import AgentContextPack, TruncationConfig
from engine.shared import filter_judge_input
from engine.investigation.context_pack._shared import (
    _ROLE_ARTIFACTS,
    _ALL_DETERMINISTIC_ARTIFACTS,
    _JUDGE_CONTEXT_SUMMARY_ARTIFACT,
    _default_truncation_config,
    _collect_limitations,
    _build_bounded_excerpts,
    _enforce_token_budget,
    _read_json_artifact,
    head_tail_truncate,
    _artifact_path,
)
from engine.investigation.context_pack.evidence import (
    _scan_workdir_artifacts,
    _extract_evidence_refs,
    _extract_top_n_findings,
)
from engine.investigation.context_pack.deterministic import (
    _build_judge_context_summary,
    _json_excerpt,
)


def build_context_pack_for_role(
    role: str,
    workdir: Path,
    case_id: str,
    config: TruncationConfig | None = None,
) -> AgentContextPack:
    """Build bounded context pack for a specific Agent role."""
    if config is None:
        config = _default_truncation_config(role)

    _artifact_cache: dict[str, dict | None] = {}

    def _cached_read(wd: Path, name: str) -> dict | None:
        if name not in _artifact_cache:
            _artifact_cache[name] = _read_json_artifact(wd, name)
        return _artifact_cache[name]

    artifact_names = _ROLE_ARTIFACTS.get(role, [])
    manifest = _scan_workdir_artifacts(workdir)
    evidence_refs = _extract_evidence_refs(workdir)
    top_n_findings = _extract_top_n_findings(workdir, n=12 if role == "judge" else 5)
    limitations = _collect_limitations(workdir, _read=_cached_read)
    if role == "judge":
        # PRD2-T6: Filter Judge input to only Layer 1 + Layer 2 findings
        top_n_findings = filter_judge_input(top_n_findings)
        bounded_excerpts = {
            _JUDGE_CONTEXT_SUMMARY_ARTIFACT: _json_excerpt(
                _build_judge_context_summary(workdir),
                config,
            ),
        }
    elif role == "claim_extractor":
        # Claim extractor needs full paper text (no truncation) and grounding
        # index for figure/table reference validation. Other artifacts from
        # _ROLE_ARTIFACTS (material_inventory, agent_material_plan,
        # evidence_ledger, source_data_findings, source_data_pair_forensics)
        # are intentionally excluded.
        bounded_excerpts = {}
        full_md_path = _artifact_path(workdir, "full.md")
        if full_md_path.exists():
            try:
                bounded_excerpts["full.md"] = full_md_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                pass
        grounding_path = _artifact_path(workdir, "grounding_index.json")
        if grounding_path.exists():
            try:
                bounded_excerpts["grounding_index.json"] = grounding_path.read_text(
                    encoding="utf-8"
                )
            except UnicodeDecodeError:
                pass
    else:
        bounded_excerpts = _build_bounded_excerpts(
            workdir, artifact_names, config, role=role
        )

    pack = AgentContextPack(
        artifact_manifest=manifest,
        evidence_refs=evidence_refs,
        top_n_findings=top_n_findings,
        limitations=limitations,
        bounded_excerpts=bounded_excerpts,
        truncation_config=config,
    )
    return _enforce_token_budget(pack)


def build_material_inventory_context_pack(
    workdir: Path,
    case_id: str,
    config: TruncationConfig | None = None,
) -> AgentContextPack:
    """Simpler pack for material_plan step — material_inventory summary only."""
    if config is None:
        config = TruncationConfig()

    _artifact_cache: dict[str, dict | None] = {}

    def _cached_read(wd: Path, name: str) -> dict | None:
        if name not in _artifact_cache:
            _artifact_cache[name] = _read_json_artifact(wd, name)
        return _artifact_cache[name]

    manifest = _scan_workdir_artifacts(workdir)
    bounded_excerpts: dict[str, str] = {}

    inv_path = _artifact_path(workdir, "material_inventory.json")
    if inv_path.exists():
        try:
            text = inv_path.read_text(encoding="utf-8")
            bounded_excerpts["material_inventory.json"] = head_tail_truncate(
                text,
                config.max_tokens_per_excerpt,
            )
        except UnicodeDecodeError:
            pass

    limitations = _collect_limitations(workdir, _read=_cached_read)

    pack = AgentContextPack(
        artifact_manifest=manifest,
        evidence_refs=[],
        top_n_findings=[],
        limitations=limitations,
        bounded_excerpts=bounded_excerpts,
        truncation_config=config,
    )
    return _enforce_token_budget(pack)


def build_review_context_pack(
    workdir: Path,
    case_id: str,
    config: TruncationConfig | None = None,
) -> AgentContextPack:
    """Pack for agent_review step — all deterministic audit artifacts."""
    if config is None:
        config = TruncationConfig()

    _artifact_cache: dict[str, dict | None] = {}

    def _cached_read(wd: Path, name: str) -> dict | None:
        if name not in _artifact_cache:
            _artifact_cache[name] = _read_json_artifact(wd, name)
        return _artifact_cache[name]

    manifest = _scan_workdir_artifacts(workdir)
    evidence_refs = _extract_evidence_refs(workdir)
    top_n_findings = _extract_top_n_findings(workdir)
    limitations = _collect_limitations(workdir, _read=_cached_read)
    bounded_excerpts = _build_bounded_excerpts(
        workdir,
        _ALL_DETERMINISTIC_ARTIFACTS,
        config,
        role="review",
    )

    pack = AgentContextPack(
        artifact_manifest=manifest,
        evidence_refs=evidence_refs,
        top_n_findings=top_n_findings,
        limitations=limitations,
        bounded_excerpts=bounded_excerpts,
        truncation_config=config,
    )
    return _enforce_token_budget(pack)
