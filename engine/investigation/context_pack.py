"""Agent Function Runtime — bounded context pack builder.

Builds AgentContextPack instances with hard token limits for each
Agent role. Replaces the ad-hoc context passing in opencode_agent.py
during Phase 2 migration.

See PRD: prd/opencode-agent-function-runtime.md
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.investigation.agent_models import AgentContextPack, TruncationConfig
from engine.static_audit.paths import resolve_artifact_path

TRUNCATION_MARKER = "\n[...truncated...]\n"

HEAD_TAIL_HEAD_RATIO = 0.3
HEAD_TAIL_TAIL_RATIO = 0.3

CHARS_PER_TOKEN = 4

_EXCLUDED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".svg", ".ico",
}

_LARGE_ARTIFACT_KEYS = {"full.md", "evidence_ledger.json"}
_JUDGE_CONTEXT_SUMMARY_ARTIFACT = "judge_context_summary.json"

_ROLE_ARTIFACTS: dict[str, list[str]] = {
    "claim_extractor": [
        "material_inventory.json",
        "agent_material_plan.json",
        "full.md",
        "evidence_ledger.json",
        "source_data_findings.json",
        "source_data_pair_forensics.json",
    ],
    "source_data_auditor": [
        "material_inventory.json",
        "agent_material_plan.json",
        "source_data_findings.json",
        "source_data_pair_forensics.json",
        "agent_claim_extractor.json",
    ],
    "judge": [
        _JUDGE_CONTEXT_SUMMARY_ARTIFACT,
    ],
}

_ALL_DETERMINISTIC_ARTIFACTS = [
    "material_inventory.json",
    "agent_material_plan.json",
    "full.md",
    "evidence_ledger.json",
    "source_data_findings.json",
    "source_data_pair_forensics.json",
    "numeric_forensics.json",
    "exact_image_duplicates.json",
    "image_similarity_candidates.json",
    "static_audit_bundle.json",
    "audit_run_manifest.json",
    "investigation_rounds.jsonl",
]


def estimate_tokens(text: str) -> int:
    """Estimate token count using 4 chars ≈ 1 token heuristic."""
    return len(text) // CHARS_PER_TOKEN


def head_tail_truncate(text: str, max_tokens: int) -> str:
    """Keep first 30% + last 30% of tokens, insert marker in middle.

    Returns text as-is if already within budget.
    """
    total_tokens = estimate_tokens(text)
    if total_tokens <= max_tokens:
        return text

    char_budget = max_tokens * CHARS_PER_TOKEN
    head_chars = int(char_budget * HEAD_TAIL_HEAD_RATIO)
    tail_chars = int(char_budget * HEAD_TAIL_TAIL_RATIO)

    if len(text) <= head_chars + tail_chars:
        return text

    head = text[:head_chars]
    tail = text[-tail_chars:] if tail_chars > 0 else ""
    return head + TRUNCATION_MARKER + tail


def _scan_workdir_artifacts(workdir: Path) -> list[dict[str, Any]]:
    """Scan workdir for existing artifacts, excluding binary/PDF/image."""
    manifest: list[dict[str, Any]] = []
    if not workdir.is_dir():
        return manifest

    for path in sorted(workdir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in _EXCLUDED_EXTENSIONS:
            continue
        artifact_id = path.relative_to(workdir).as_posix()
        size_bytes = path.stat().st_size
        summary = _artifact_file_summary(path)
        manifest.append({
            "id": artifact_id,
            "type": _artifact_type(path),
            "size_bytes": size_bytes,
            "summary": summary,
        })
    return manifest


def _artifact_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".md":
        return "markdown"
    if suffix == ".html":
        return "html_report"
    return "other"


def _artifact_file_summary(path: Path) -> str:
    """Generate a short summary for artifact manifest entry."""
    if path.suffix.lower() not in {".json", ".jsonl"}:
        size = path.stat().st_size
        return f"{path.name}: {size} bytes"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        size = path.stat().st_size
        return f"{path.name}: {size} bytes (parse error)"

    if isinstance(data, dict):
        if "summary" in data and isinstance(data["summary"], dict):
            keys = list(data["summary"].keys())[:5]
            return f"{path.name}: summary keys={keys}"
        top_keys = list(data.keys())[:6]
        return f"{path.name}: top_keys={top_keys}"
    if isinstance(data, list):
        return f"{path.name}: list[{len(data)}]"
    return f"{path.name}: {type(data).__name__}"


def _read_json_safe(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _artifact_path(workdir: Path, artifact_name: str) -> Path:
    """Return the canonical artifact path, falling back to legacy flat files."""
    mapped = resolve_artifact_path(workdir, artifact_name)
    if mapped.exists():
        return mapped
    legacy = workdir / artifact_name
    if legacy.exists():
        return legacy
    return mapped


def _read_json_artifact(workdir: Path, artifact_name: str) -> dict[str, Any] | list[Any] | None:
    return _read_json_safe(_artifact_path(workdir, artifact_name))


def _default_truncation_config(role: str) -> TruncationConfig:
    if role == "judge":
        return TruncationConfig(max_tokens_per_pack=40_000, max_tokens_per_excerpt=8_000)
    return TruncationConfig()


def _extract_evidence_refs(workdir: Path) -> list[dict[str, Any]]:
    """Extract evidence_refs: pointers to artifact_id + line ranges."""
    refs: list[dict[str, Any]] = []

    source_findings = _read_json_artifact(workdir, "source_data_findings.json")
    if isinstance(source_findings, dict):
        for item in (source_findings.get("priority_findings") or [])[:10]:
            if isinstance(item, dict):
                refs.append({
                    "artifact_id": "source_data_findings.json",
                    "finding_id": item.get("finding_id"),
                    "risk_level": item.get("risk_level"),
                    "category": item.get("category"),
                })

    pair_forensics = _read_json_artifact(workdir, "source_data_pair_forensics.json")
    if isinstance(pair_forensics, dict):
        for item in (pair_forensics.get("priority_findings") or [])[:10]:
            if isinstance(item, dict):
                refs.append({
                    "artifact_id": "source_data_pair_forensics.json",
                    "finding_id": item.get("finding_id"),
                    "risk_level": item.get("risk_level"),
                    "category": item.get("category"),
                })

    image_dups = _read_json_artifact(workdir, "exact_image_duplicates.json")
    if isinstance(image_dups, dict) and image_dups.get("duplicate_group_count", 0) > 0:
        refs.append({
            "artifact_id": "exact_image_duplicates.json",
            "duplicate_group_count": image_dups.get("duplicate_group_count"),
            "duplicate_image_count": image_dups.get("duplicate_image_count"),
        })

    return refs


def _extract_top_n_findings(
    workdir: Path,
    n: int = 5,
) -> list[dict[str, Any]]:
    """Extract Top-N findings from deterministic audit artifacts."""
    findings: list[dict[str, Any]] = []

    source_findings = _read_json_artifact(workdir, "source_data_findings.json")
    if isinstance(source_findings, dict):
        for item in (source_findings.get("priority_findings") or [])[:n]:
            if isinstance(item, dict):
                findings.append(_compact_priority_finding(item))

    pair_forensics = _read_json_artifact(workdir, "source_data_pair_forensics.json")
    if isinstance(pair_forensics, dict):
        remaining = n - len(findings)
        for item in (pair_forensics.get("priority_findings") or [])[:remaining]:
            if isinstance(item, dict):
                findings.append(_compact_pair_forensics_finding(item))

    numeric = _read_json_artifact(workdir, "numeric_forensics.json")
    if isinstance(numeric, dict):
        remaining = n - len(findings)
        benford = numeric.get("benford") or {}
        if benford.get("applicability") and benford.get("mad", benford.get("mean_absolute_deviation")) is not None:
            findings.append({
                "source": "numeric_forensics.json",
                "category": "benford_analysis",
                "mad": benford.get("mad", benford.get("mean_absolute_deviation")),
                "applicability": benford.get("applicability"),
            })

    return findings[:n]


def _compact_priority_finding(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "source_data_findings.json",
        "finding_id": item.get("finding_id"),
        "risk_level": item.get("risk_level"),
        "category": item.get("category"),
        "workbook": item.get("workbook"),
        "sheet": item.get("sheet"),
        "column_pair": item.get("column_pair"),
        "relationship_value": item.get("relationship_value"),
        "benign_explanations": (item.get("benign_explanations") or [])[:3],
    }


def _compact_pair_forensics_finding(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "source_data_pair_forensics.json",
        "finding_id": item.get("finding_id"),
        "risk_level": item.get("risk_level"),
        "category": item.get("category"),
        "workbook": item.get("workbook"),
        "sheet": item.get("sheet"),
        "support_rate": item.get("support_rate"),
        "sample_pairs": (item.get("sample_pairs") or item.get("sample_exact_pairs") or [])[:5],
    }


def _collect_limitations(workdir: Path) -> list[str]:
    """Collect limitation strings from all relevant artifacts."""
    limitations: list[str] = []
    for name in (
        "material_inventory.json",
        "agent_material_plan.json",
        "source_data_findings.json",
        "source_data_pair_forensics.json",
        "numeric_forensics.json",
    ):
        data = _read_json_artifact(workdir, name)
        if not isinstance(data, dict):
            continue
        for lim in data.get("limitations", []):
            if isinstance(lim, str) and lim not in limitations:
                limitations.append(lim)
    return limitations


def _compact_str_list(values: Any, *, limit: int = 8, max_chars: int = 240) -> list[str]:
    if not isinstance(values, list):
        return []
    compacted: list[str] = []
    for value in values[:limit]:
        if isinstance(value, str):
            compacted.append(value[:max_chars])
    return compacted


def _compact_refs(value: Any, *, limit: int = 6) -> Any:
    if isinstance(value, list):
        return value[:limit]
    if isinstance(value, dict):
        return {str(k): _compact_refs(v, limit=limit) for k, v in list(value.items())[:limit]}
    return value


def _compact_claim_for_judge(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": item.get("claim_id"),
        "claim_type": item.get("claim_type"),
        "paper_location": item.get("paper_location"),
        "status": item.get("status"),
        "claim_text": str(item.get("claim_text", ""))[:360],
        "evidence_refs": _compact_refs(item.get("evidence_refs")),
    }


def _risk_rank(value: Any) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(value).lower(), 4)


def _compact_finding_review_for_judge(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "finding_id": item.get("finding_id"),
        "assessment": item.get("assessment"),
        "residual_risk": item.get("residual_risk"),
        "benign_explanations": _compact_str_list(item.get("benign_explanations"), limit=3),
        "evidence_refs": _compact_refs(item.get("evidence_refs")),
    }


def _compact_manual_task_for_judge(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": item.get("task_id"),
        "priority": item.get("priority"),
        "question": str(item.get("question", ""))[:360],
        "evidence_refs": _compact_refs(item.get("evidence_refs")),
    }


def _compact_pair_review_task_for_judge(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": item.get("task_id"),
        "priority": item.get("priority"),
        "cluster_id": item.get("cluster_id"),
        "category": item.get("category"),
        "workbook": item.get("workbook"),
        "sheet": item.get("sheet"),
        "cluster_count": item.get("cluster_count"),
        "finding_count": item.get("finding_count"),
        "question": str(item.get("question", ""))[:420],
        "evidence_refs": _compact_refs(item.get("evidence_refs")),
    }


def _compact_pair_cluster_for_judge(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "cluster_id": item.get("cluster_id"),
        "category": item.get("category"),
        "risk_level": item.get("risk_level"),
        "workbook": item.get("workbook"),
        "sheet": item.get("sheet"),
        "pattern_signature": item.get("pattern_signature"),
        "finding_count": item.get("finding_count"),
        "representative_finding_ids": (item.get("representative_finding_ids") or [])[:8],
        "review_question": str(item.get("review_question", ""))[:360],
    }


def _compact_visual_review_task_for_judge(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": item.get("task_id"),
        "priority": item.get("priority"),
        "cluster_id": item.get("cluster_id"),
        "category": item.get("category"),
        "scope": item.get("scope"),
        "figure_ids": (item.get("figure_ids") or [])[:6],
        "finding_count": item.get("finding_count"),
        "relationship_count": item.get("relationship_count"),
        "panel_extraction_quality": item.get("panel_extraction_quality"),
        "question": str(item.get("question", ""))[:420],
        "evidence_refs": _compact_refs(item.get("evidence_refs")),
    }


def _compact_visual_cluster_for_judge(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "cluster_id": item.get("cluster_id"),
        "category": item.get("category"),
        "risk_level": item.get("risk_level"),
        "scope": item.get("scope"),
        "figure_ids": (item.get("figure_ids") or [])[:6],
        "panel_extraction_quality": item.get("panel_extraction_quality"),
        "finding_count": item.get("finding_count"),
        "relationship_count": item.get("relationship_count"),
        "max_score": item.get("max_score"),
        "representative_finding_ids": (item.get("representative_finding_ids") or [])[:8],
        "review_question": str(item.get("review_question", ""))[:360],
    }


def _compact_mapping_for_judge(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": item.get("claim_id"),
        "mapping_id": item.get("mapping_id"),
        "source_data_refs": _compact_refs(item.get("source_data_refs")),
        "confidence": item.get("confidence"),
        "needs_human_review": item.get("needs_human_review"),
    }


def _artifact_summary_value(data: dict[str, Any] | list[Any] | None) -> Any:
    if isinstance(data, dict):
        if isinstance(data.get("summary"), dict):
            return data.get("summary")
        return {"top_keys": list(data.keys())[:10]}
    if isinstance(data, list):
        return {"count": len(data)}
    return {"status": "missing"}


def _extend_unique_strings(target: list[str], values: Any) -> None:
    for value in _compact_str_list(values, limit=12):
        if value not in target:
            target.append(value)


def _build_judge_context_summary(workdir: Path) -> dict[str, Any]:
    claim_output = _read_json_artifact(workdir, "agent_claim_extractor.json")
    source_output = _read_json_artifact(workdir, "agent_source_data_auditor.json")
    material_inventory = _read_json_artifact(workdir, "material_inventory.json")
    material_plan = _read_json_artifact(workdir, "agent_material_plan.json")
    numeric = _read_json_artifact(workdir, "numeric_forensics.json")
    source_findings = _read_json_artifact(workdir, "source_data_findings.json")
    pair_forensics = _read_json_artifact(workdir, "source_data_pair_forensics.json")
    visual_findings = _read_json_artifact(workdir, "visual_findings.json")
    image_relationships = _read_json_artifact(workdir, "image_relationships.json")

    claims = claim_output.get("claims") if isinstance(claim_output, dict) else []
    if not isinstance(claims, list):
        claims = []
    mappings = source_output.get("claim_to_source_data") if isinstance(source_output, dict) else []
    if not isinstance(mappings, list):
        mappings = []
    finding_reviews = source_output.get("finding_reviews") if isinstance(source_output, dict) else []
    if not isinstance(finding_reviews, list):
        finding_reviews = []
    manual_tasks = source_output.get("manual_review_tasks") if isinstance(source_output, dict) else []
    if not isinstance(manual_tasks, list):
        manual_tasks = []

    top_reviews = sorted(
        [item for item in finding_reviews if isinstance(item, dict)],
        key=lambda item: _risk_rank(item.get("residual_risk")),
    )[:12]
    top_tasks = sorted(
        [item for item in manual_tasks if isinstance(item, dict)],
        key=lambda item: _risk_rank(item.get("priority")),
    )[:12]

    limitations = _collect_limitations(workdir)
    if isinstance(claim_output, dict):
        _extend_unique_strings(limitations, claim_output.get("limitations"))
    if isinstance(source_output, dict):
        _extend_unique_strings(limitations, source_output.get("limitations"))

    inventory_summary = material_inventory.get("summary") if isinstance(material_inventory, dict) else {}
    return {
        "contract": {
            "role_id": "judge",
            "purpose": "Synthesize prior role outputs and compact deterministic summaries into report-ready risk suggestions.",
            "primary_inputs": [
                "agent_claim_extractor.json",
                "agent_source_data_auditor.json",
                "top_n_findings",
                "limitations",
            ],
            "raw_artifacts_excluded": [
                "full.md",
                "evidence_ledger.json",
                "source_data_findings.json",
                "source_data_pair_forensics.json",
                "visual image files",
            ],
            "output_limits": {
                "risk_suggestions": 8,
                "report_notes": 8,
                "limitations": 10,
            },
        },
        "role_outputs": {
            "claim_extractor": {
                "status": claim_output.get("status") if isinstance(claim_output, dict) else "missing",
                "claim_count": len(claims),
                "sample_claims": [
                    _compact_claim_for_judge(item)
                    for item in claims[:12]
                    if isinstance(item, dict)
                ],
                "limitations": _compact_str_list(claim_output.get("limitations") if isinstance(claim_output, dict) else []),
            },
            "source_data_auditor": {
                "status": source_output.get("status") if isinstance(source_output, dict) else "missing",
                "claim_mapping_count": len(mappings),
                "finding_review_count": len(finding_reviews),
                "manual_review_task_count": len(manual_tasks),
                "sample_claim_mappings": [
                    _compact_mapping_for_judge(item)
                    for item in mappings[:12]
                    if isinstance(item, dict)
                ],
                "top_finding_reviews": [
                    _compact_finding_review_for_judge(item)
                    for item in top_reviews
                ],
                "top_manual_review_tasks": [
                    _compact_manual_task_for_judge(item)
                    for item in top_tasks
                ],
                "limitations": _compact_str_list(source_output.get("limitations") if isinstance(source_output, dict) else []),
            },
        },
        "deterministic_artifact_summaries": {
            "material_inventory": {
                "file_count": inventory_summary.get("file_count") if isinstance(inventory_summary, dict) else None,
                "by_material_type": inventory_summary.get("by_material_type", {}) if isinstance(inventory_summary, dict) else {},
            },
            "material_plan": {
                "selected_optional_lanes": material_plan.get("selected_optional_lanes", []) if isinstance(material_plan, dict) else [],
                "missing_materials": material_plan.get("missing_materials", []) if isinstance(material_plan, dict) else [],
                "unsupported_materials": (material_plan.get("unsupported_materials") or [])[:8] if isinstance(material_plan, dict) else [],
            },
            "numeric_forensics": _artifact_summary_value(numeric),
            "source_data_findings": _artifact_summary_value(source_findings),
            "source_data_pair_forensics": _artifact_summary_value(pair_forensics),
            "source_data_pair_forensics_review_tasks": [
                _compact_pair_review_task_for_judge(item)
                for item in ((pair_forensics.get("review_tasks") if isinstance(pair_forensics, dict) else []) or [])[:12]
                if isinstance(item, dict)
            ],
            "source_data_pair_forensics_clusters": [
                _compact_pair_cluster_for_judge(item)
                for item in ((pair_forensics.get("finding_clusters") if isinstance(pair_forensics, dict) else []) or [])[:12]
                if isinstance(item, dict)
            ],
            "visual_findings": _artifact_summary_value(visual_findings),
            "visual_review_queue": [
                _compact_visual_review_task_for_judge(item)
                for item in ((visual_findings.get("review_queue") if isinstance(visual_findings, dict) else []) or [])[:12]
                if isinstance(item, dict)
            ],
            "visual_finding_clusters": [
                _compact_visual_cluster_for_judge(item)
                for item in ((visual_findings.get("finding_clusters") if isinstance(visual_findings, dict) else []) or [])[:12]
                if isinstance(item, dict)
            ],
            "image_relationships": _artifact_summary_value(image_relationships),
        },
        "top_n_findings": _extract_top_n_findings(workdir, n=12),
        "limitations": limitations[:12],
    }


def _json_excerpt(data: dict[str, Any], config: TruncationConfig) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return head_tail_truncate(text, config.max_tokens_per_excerpt)


def _build_bounded_excerpts(
    workdir: Path,
    artifact_names: list[str],
    config: TruncationConfig,
) -> dict[str, str]:
    """Create bounded excerpts for large artifacts using head_tail_truncate."""
    excerpts: dict[str, str] = {}
    for name in artifact_names:
        path = _artifact_path(workdir, name)
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        if name in _LARGE_ARTIFACT_KEYS:
            excerpts[name] = head_tail_truncate(text, config.max_tokens_per_excerpt)
        else:
            excerpts[name] = head_tail_truncate(text, config.max_tokens_per_excerpt)
    return excerpts


def _enforce_token_budget(pack: AgentContextPack) -> AgentContextPack:
    """Reduce excerpts proportionally if total tokens exceed budget."""
    config = pack.truncation_config
    max_total = config.max_tokens_per_pack

    def _total_tokens() -> int:
        total = estimate_tokens(json.dumps(pack.to_dict(), ensure_ascii=False))
        return total

    if _total_tokens() <= max_total:
        return pack

    keys_by_size = sorted(
        pack.bounded_excerpts.keys(),
        key=lambda k: len(pack.bounded_excerpts[k]),
        reverse=True,
    )

    for key in keys_by_size:
        if _total_tokens() <= max_total:
            break
        current_len = len(pack.bounded_excerpts[key])
        if current_len <= 200:
            del pack.bounded_excerpts[key]
            continue
        new_max = max(1000, estimate_tokens(pack.bounded_excerpts[key]) // 2)
        pack.bounded_excerpts[key] = head_tail_truncate(
            pack.bounded_excerpts[key], new_max,
        )

    return pack


def build_context_pack_for_role(
    role: str,
    workdir: Path,
    case_id: str,
    config: TruncationConfig | None = None,
) -> AgentContextPack:
    """Build bounded context pack for a specific Agent role."""
    if config is None:
        config = _default_truncation_config(role)

    artifact_names = _ROLE_ARTIFACTS.get(role, [])
    manifest = _scan_workdir_artifacts(workdir)
    evidence_refs = _extract_evidence_refs(workdir)
    top_n_findings = _extract_top_n_findings(workdir, n=12 if role == "judge" else 5)
    limitations = _collect_limitations(workdir)
    if role == "judge":
        bounded_excerpts = {
            _JUDGE_CONTEXT_SUMMARY_ARTIFACT: _json_excerpt(
                _build_judge_context_summary(workdir),
                config,
            ),
        }
    else:
        bounded_excerpts = _build_bounded_excerpts(workdir, artifact_names, config)

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

    manifest = _scan_workdir_artifacts(workdir)
    bounded_excerpts: dict[str, str] = {}

    inv_path = _artifact_path(workdir, "material_inventory.json")
    if inv_path.exists():
        try:
            text = inv_path.read_text(encoding="utf-8")
            bounded_excerpts["material_inventory.json"] = head_tail_truncate(
                text, config.max_tokens_per_excerpt,
            )
        except UnicodeDecodeError:
            pass

    limitations = _collect_limitations(workdir)

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

    manifest = _scan_workdir_artifacts(workdir)
    evidence_refs = _extract_evidence_refs(workdir)
    top_n_findings = _extract_top_n_findings(workdir)
    limitations = _collect_limitations(workdir)
    bounded_excerpts = _build_bounded_excerpts(
        workdir, _ALL_DETERMINISTIC_ARTIFACTS, config,
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
