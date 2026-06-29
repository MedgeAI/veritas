from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from engine.investigation.agent_models import AgentContextPack, TruncationConfig
from engine.static_audit.paths import resolve_artifact_path

TRUNCATION_MARKER = "\n[...truncated...]\n"

HEAD_TAIL_HEAD_RATIO = 0.3
HEAD_TAIL_TAIL_RATIO = 0.3

CHARS_PER_TOKEN = 4

_EXCLUDED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
    ".svg",
    ".ico",
}

_LARGE_ARTIFACT_KEYS = {"full.md", "evidence_ledger.json"}
_JUDGE_CONTEXT_SUMMARY_ARTIFACT = "judge_context_summary.json"

# Cache for canonical finding IDs, keyed by workdir string.
_canonical_ids_cache: dict[str, set[str]] = {}

# Ordered list of canonical artifacts scanned for finding IDs.
_CANONICAL_FINDING_ARTIFACTS: list[str] = [
    "source_data_findings.json",
    "source_data_pair_forensics.json",
    "visual_findings.json",
    "image_relationships.json",
    "static_audit_bundle.json",
]

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


def _read_json_artifact(
    workdir: Path, artifact_name: str
) -> dict[str, Any] | list[Any] | None:
    return _read_json_safe(_artifact_path(workdir, artifact_name))


def _default_truncation_config(role: str) -> TruncationConfig:
    if role == "judge":
        return TruncationConfig(
            max_tokens_per_pack=40_000, max_tokens_per_excerpt=8_000
        )
    return TruncationConfig()


def _collect_limitations(
    workdir: Path,
    *,
    _read: Callable[[Path, str], dict | None] | None = None,
) -> list[str]:
    """Collect limitation strings from all relevant artifacts."""
    _reader = _read or _read_json_artifact
    limitations: list[str] = []
    for name in (
        "material_inventory.json",
        "agent_material_plan.json",
        "source_data_findings.json",
        "source_data_pair_forensics.json",
        "numeric_forensics.json",
    ):
        data = _reader(workdir, name)
        if not isinstance(data, dict):
            continue
        for lim in data.get("limitations", []):
            if isinstance(lim, str) and lim not in limitations:
                limitations.append(lim)
    return limitations


def _compact_str_list(
    values: Any, *, limit: int = 8, max_chars: int = 240
) -> list[str]:
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
        return {
            str(k): _compact_refs(v, limit=limit)
            for k, v in list(value.items())[:limit]
        }
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
        "benign_explanations": _compact_str_list(
            item.get("benign_explanations"), limit=3
        ),
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
        "representative_finding_ids": (item.get("representative_finding_ids") or [])[
            :8
        ],
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
        "representative_finding_ids": (item.get("representative_finding_ids") or [])[
            :8
        ],
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


def _compact_source_data_findings(data: dict[str, Any]) -> dict[str, Any]:
    """Compact source_data_findings for agent context packs.

    Keeps claim_to_source_data but compacts it to only include mappings
    relevant to current findings, with truncated paper references.
    This preserves semantic context for the auditor to judge findings.
    """
    if not isinstance(data, dict):
        return data

    # Extract sheets mentioned in findings
    finding_sheets: set[tuple[str, str]] = set()
    for finding in data.get("findings", []):
        if isinstance(finding, dict):
            wb = finding.get("workbook", "")
            sh = finding.get("sheet", "")
            if wb and sh:
                finding_sheets.add((wb, sh))

    for finding in data.get("priority_findings", []):
        if isinstance(finding, dict):
            wb = finding.get("workbook", "")
            sh = finding.get("sheet", "")
            if wb and sh:
                finding_sheets.add((wb, sh))

    # Compact claim_to_source_data: keep only relevant mappings
    original_mappings = data.get("claim_to_source_data", [])
    compacted_mappings = []
    for mapping in original_mappings:
        if not isinstance(mapping, dict):
            continue
        wb = mapping.get("workbook", "")
        sh = mapping.get("sheet", "")
        # Keep mapping if it's relevant to findings, or if we have few findings
        if (wb, sh) in finding_sheets or len(finding_sheets) == 0:
            compacted_mappings.append(_compact_claim_mapping_for_auditor(mapping))

    # Build compacted data
    compacted = {k: v for k, v in data.items() if k != "claim_to_source_data"}
    compacted["claim_to_source_data"] = compacted_mappings[:18]  # Limit to 18 mappings

    return compacted


def _compact_claim_mapping_for_auditor(mapping: dict[str, Any]) -> dict[str, Any]:
    """Compact a single claim mapping for source_data_auditor context.

    Keeps semantic context (figure ID, paper reference) but truncates
    verbose fields to reduce size.
    """
    # Extract brief paper reference (first 200 chars of first match)
    paper_refs = mapping.get("matched_paper_references", [])
    brief_ref = ""
    if paper_refs and isinstance(paper_refs, list):
        first_ref = paper_refs[0]
        if isinstance(first_ref, dict):
            text = first_ref.get("text", "")
            brief_ref = text[:200] + "..." if len(text) > 200 else text

    return {
        "mapping_id": mapping.get("mapping_id"),
        "workbook": mapping.get("workbook"),
        "sheet": mapping.get("sheet"),
        "source_figure_id": mapping.get("source_figure_id"),
        "source_figure_kind": mapping.get("source_figure_kind"),
        "paper_context": brief_ref,  # Brief paper description for semantic context
        "review_priority": mapping.get("review_priority"),
        "mapping_confidence": mapping.get("mapping_confidence"),
    }


def _compact_pair_forensics(data: dict[str, Any]) -> dict[str, Any]:
    """Compact source_data_pair_forensics for agent context packs.

    Keeps findings and review tasks needed for auditing, but excludes
    verbose per-finding data like raw_data_samples and detailed pair lists.
    """
    if not isinstance(data, dict):
        return data

    def _compact_finding(f: dict[str, Any]) -> dict[str, Any]:
        """Compact a single finding, excluding verbose fields."""
        if not isinstance(f, dict):
            return f
        return {
            "finding_id": f.get("finding_id"),
            "category": f.get("category"),
            "risk_level": f.get("risk_level"),
            "workbook": f.get("workbook"),
            "sheet": f.get("sheet"),
            "rows": f.get("rows", [])[:10],  # Limit rows list
            "columns": f.get("columns", [])[:5],
            "values": f.get("values", [])[:5],
            "support_rate": f.get("support_rate"),
            "benign_explanations": (f.get("benign_explanations") or [])[:3],
            # Exclude: raw_data_samples, detailed_pairs, etc.
        }

    # Compact all finding lists
    compacted = dict(data)

    # Compact findings (main list)
    if "findings" in compacted and isinstance(compacted["findings"], list):
        compacted["findings"] = [
            _compact_finding(f) for f in compacted["findings"][:20]
        ]

    # Compact priority_findings
    if "priority_findings" in compacted and isinstance(
        compacted["priority_findings"], list
    ):
        compacted["priority_findings"] = [
            _compact_finding(f) for f in compacted["priority_findings"][:12]
        ]

    # Compact specialized finding lists (they're also verbose)
    for key in [
        "duplicate_row_vector_findings",
        "row_offset_scalar_findings",
        "long_format_paired_ratio_reuse_findings",
        "long_format_within_pair_ratio_enrichment_findings",
        "rounding_bias_findings",
        "cross_block_paired_diff_too_narrow_findings",
    ]:
        if key in compacted and isinstance(compacted[key], list):
            compacted[key] = [_compact_finding(f) for f in compacted[key][:8]]

    # Keep review_tasks and finding_clusters (they're already compact)
    if "review_tasks" in compacted and isinstance(compacted["review_tasks"], list):
        compacted["review_tasks"] = compacted["review_tasks"][:12]

    if "finding_clusters" in compacted and isinstance(
        compacted["finding_clusters"], list
    ):
        compacted["finding_clusters"] = compacted["finding_clusters"][:8]

    return compacted


def _build_bounded_excerpts(
    workdir: Path,
    artifact_names: list[str],
    config: TruncationConfig,
    role: str = "",
) -> dict[str, str]:
    """Create bounded excerpts for large artifacts using head_tail_truncate.

    For source_data_auditor role, compacts source data artifacts to exclude
    large unnecessary fields like claim_to_source_data.
    """
    excerpts: dict[str, str] = {}
    for name in artifact_names:
        path = _artifact_path(workdir, name)
        if not path.exists():
            continue
        try:
            raw_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        # Apply role-specific compaction for JSON source data artifacts
        if role == "source_data_auditor" and path.suffix.lower() == ".json":
            try:
                raw_data = json.loads(raw_text)
                if name == "source_data_findings.json":
                    raw_data = _compact_source_data_findings(raw_data)
                elif name == "source_data_pair_forensics.json":
                    raw_data = _compact_pair_forensics(raw_data)
                raw_text = json.dumps(raw_data, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass  # Keep original text if JSON parsing fails

        if name in _LARGE_ARTIFACT_KEYS:
            excerpts[name] = head_tail_truncate(raw_text, config.max_tokens_per_excerpt)
        else:
            excerpts[name] = head_tail_truncate(raw_text, config.max_tokens_per_excerpt)
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
            pack.bounded_excerpts[key],
            new_max,
        )

    return pack
