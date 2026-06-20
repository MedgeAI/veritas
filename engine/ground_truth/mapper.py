"""Phase 1 — Map structured claims to capability taxonomy.

Each claim is matched to a capability_id from the taxonomy.
The mapping is keyword-based for reproducibility and auditability.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from engine.ground_truth.parser import StructuredClaim


@dataclass
class MappedClaim:
    """A claim mapped to a capability in the taxonomy."""

    claim: StructuredClaim
    capability_id: str
    capability_category: str
    detected: bool = False
    existing_finding_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["claim"] = self.claim.to_dict()
        return d


def map_claims_to_capabilities(
    claims: list[StructuredClaim],
    catalog_path: Path | None = None,
    existing_findings: list[dict] | None = None,
) -> list[MappedClaim]:
    """Map each claim to a capability_id from the taxonomy.

    Parameters
    ----------
    claims : list[StructuredClaim]
        Claims from parser.
    catalog_path : Path, optional
        Path to capability_catalog.yaml. If None, uses keyword-based mapping.
    existing_findings : list[dict], optional
        Findings from a prior audit run. Used to set ``detected=True``.

    Returns
    -------
    list[MappedClaim]
        Claims with capability mapping and detection status.
    """
    catalog = _load_catalog(catalog_path) if catalog_path else {}
    finding_index = _build_finding_index(existing_findings or [])

    mapped: list[MappedClaim] = []
    for claim in claims:
        cap_id, cap_cat = _resolve_capability(claim, catalog)
        finding_id = _find_matching_finding(claim, finding_index)
        mapped.append(
            MappedClaim(
                claim=claim,
                capability_id=cap_id,
                capability_category=cap_cat,
                detected=bool(finding_id),
                existing_finding_id=finding_id,
            )
        )
    return mapped


def _load_catalog(catalog_path: Path) -> dict[str, dict]:
    """Load capability catalog YAML."""
    if not catalog_path.exists():
        return {}
    data = yaml.safe_load(catalog_path.read_text()) or {}
    capabilities = data.get("capabilities", data)
    if isinstance(capabilities, list):
        return {
            str(c.get("capability_id", "")): c
            for c in capabilities
            if isinstance(c, dict)
        }
    if isinstance(capabilities, dict):
        return capabilities
    return {}


def _resolve_capability(claim: StructuredClaim, catalog: dict) -> tuple[str, str]:
    """Map a claim to a capability_id using claim_type as primary key."""
    direct = claim.claim_type
    if direct in catalog:
        entry = catalog[direct]
        return (direct, str(entry.get("category", "unknown")))

    category_map = {
        "visual.copy_move_keypoint": ("visual.copy_move_keypoint", "visual"),
        "visual.image_quality": ("visual.image_quality", "visual"),
        "source_data.fixed_difference": ("source_data.fixed_difference", "source_data"),
        "source_data.fixed_ratio": ("source_data.fixed_ratio", "source_data"),
        "source_data.duplicate_columns": (
            "source_data.duplicate_columns",
            "source_data",
        ),
        "source_data.row_offset_exact_reuse": (
            "source_data.row_offset_exact_reuse",
            "source_data",
        ),
        "source_data.paired_difference_spread": (
            "source_data.paired_difference_spread",
            "source_data",
        ),
        "completeness.missing_source_data": (
            "completeness.missing_source_data",
            "completeness",
        ),
    }

    if direct in category_map:
        return category_map[direct]

    for prefix in ("visual", "source_data", "numeric", "completeness"):
        if direct.startswith(prefix):
            return (direct, prefix)

    return (direct, "unknown")


def _build_finding_index(findings: list[dict]) -> list[dict]:
    """Index findings by category and target for matching."""
    return [f for f in findings if isinstance(f, dict)]


def _find_matching_finding(claim: StructuredClaim, findings: list[dict]) -> str:
    """Check if any existing finding matches this claim.

    Simple heuristic: match by category keyword overlap and target substring.
    """
    target_lower = claim.target.lower()
    claim_type_lower = claim.claim_type.lower()

    for f in findings:
        f_cat = str(f.get("category", "")).lower()
        f_target = str(f.get("target", f.get("locator", ""))).lower()
        f_summary = str(f.get("summary", "")).lower()

        category_match = _category_compatible(claim_type_lower, f_cat)
        target_match = (
            target_lower in f_target
            or target_lower in f_summary
            or (f_target and f_target in target_lower)
        )

        if category_match and target_match:
            return str(f.get("finding_id", ""))

    return ""


def _category_compatible(claim_type: str, finding_category: str) -> bool:
    """Check if claim_type and finding_category are semantically compatible."""
    type_prefix = claim_type.split(".")[0] if "." in claim_type else claim_type
    aliases = {
        "visual": {
            "copy_move",
            "visual",
            "panel",
            "exact_duplicate",
            "dhash",
            "overlap",
            "forged",
            "tru_for",
            "image_quality",
        },
        "source_data": {
            "fixed_difference",
            "fixed_ratio",
            "duplicate",
            "row_offset",
            "paired",
            "formula",
            "source_data",
        },
        "completeness": {"missing", "completeness", "source_data_missing"},
        "numeric": {"numeric", "benford", "variance", "digit", "rounding"},
    }
    compatible_set = aliases.get(type_prefix, {type_prefix})
    return any(alias in finding_category for alias in compatible_set)
