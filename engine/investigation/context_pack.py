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

TRUNCATION_MARKER = "\n[...truncated...]\n"

HEAD_TAIL_HEAD_RATIO = 0.3
HEAD_TAIL_TAIL_RATIO = 0.3

CHARS_PER_TOKEN = 4

_EXCLUDED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".svg", ".ico",
}

_LARGE_ARTIFACT_KEYS = {"full.md", "evidence_ledger.json"}

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
        "material_inventory.json",
        "agent_material_plan.json",
        "agent_claim_extractor.json",
        "agent_source_data_auditor.json",
        "numeric_forensics.json",
        "source_data_findings.json",
        "source_data_pair_forensics.json",
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

    for path in sorted(workdir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() in _EXCLUDED_EXTENSIONS:
            continue
        size_bytes = path.stat().st_size
        summary = _artifact_file_summary(path)
        manifest.append({
            "id": path.name,
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


def _extract_evidence_refs(workdir: Path) -> list[dict[str, Any]]:
    """Extract evidence_refs: pointers to artifact_id + line ranges."""
    refs: list[dict[str, Any]] = []

    source_findings = _read_json_safe(workdir / "source_data_findings.json")
    if isinstance(source_findings, dict):
        for item in (source_findings.get("priority_findings") or [])[:10]:
            if isinstance(item, dict):
                refs.append({
                    "artifact_id": "source_data_findings.json",
                    "finding_id": item.get("finding_id"),
                    "risk_level": item.get("risk_level"),
                    "category": item.get("category"),
                })

    pair_forensics = _read_json_safe(workdir / "source_data_pair_forensics.json")
    if isinstance(pair_forensics, dict):
        for item in (pair_forensics.get("priority_findings") or [])[:10]:
            if isinstance(item, dict):
                refs.append({
                    "artifact_id": "source_data_pair_forensics.json",
                    "finding_id": item.get("finding_id"),
                    "risk_level": item.get("risk_level"),
                    "category": item.get("category"),
                })

    image_dups = _read_json_safe(workdir / "exact_image_duplicates.json")
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

    source_findings = _read_json_safe(workdir / "source_data_findings.json")
    if isinstance(source_findings, dict):
        for item in (source_findings.get("priority_findings") or [])[:n]:
            if isinstance(item, dict):
                findings.append(_compact_priority_finding(item))

    pair_forensics = _read_json_safe(workdir / "source_data_pair_forensics.json")
    if isinstance(pair_forensics, dict):
        remaining = n - len(findings)
        for item in (pair_forensics.get("priority_findings") or [])[:remaining]:
            if isinstance(item, dict):
                findings.append(_compact_pair_forensics_finding(item))

    numeric = _read_json_safe(workdir / "numeric_forensics.json")
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
        data = _read_json_safe(workdir / name)
        if not isinstance(data, dict):
            continue
        for lim in data.get("limitations", []):
            if isinstance(lim, str) and lim not in limitations:
                limitations.append(lim)
    return limitations


def _build_bounded_excerpts(
    workdir: Path,
    artifact_names: list[str],
    config: TruncationConfig,
) -> dict[str, str]:
    """Create bounded excerpts for large artifacts using head_tail_truncate."""
    excerpts: dict[str, str] = {}
    for name in artifact_names:
        path = workdir / name
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
        config = TruncationConfig()

    artifact_names = _ROLE_ARTIFACTS.get(role, [])
    manifest = _scan_workdir_artifacts(workdir)
    evidence_refs = _extract_evidence_refs(workdir)
    top_n_findings = _extract_top_n_findings(workdir)
    limitations = _collect_limitations(workdir)
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

    inv_path = workdir / "material_inventory.json"
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
