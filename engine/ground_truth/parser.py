"""Phase 1 — Parse PubPeer posts and manual annotations into structured claims.

Supports two input formats:
  1. PubPeer Markdown post (regex-based extraction of comment structure)
  2. Manual annotation YAML (pre-structured claims)

Each claim must meet the Minimum Executable Specification:
  - type: must match capability taxonomy
  - target: paper element locator (e.g. "Fig. 4h", "Sheet 3")
  - description: must contain verifiable, quantifiable facts
  - evidence_type: "image" | "source_data" | "numeric" | "completeness"
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

EvidenceType = Literal["image", "source_data", "numeric", "completeness"]


@dataclass
class StructuredClaim:
    """A single ground-truth claim extracted from a PubPeer post or annotation."""

    claim_type: str
    target: str
    description: str
    evidence_type: EvidenceType
    source: str = "unknown"
    comment_id: str = ""
    confirmed_by_human: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_pubpeer_post(text: str) -> list[StructuredClaim]:
    """Extract structured claims from a PubPeer post Markdown.

    Splits the post into comments (by ``**#N**`` headers) and extracts
    claim candidates from each comment.  Human confirmation is required
    before claims proceed to mapping.
    """
    claims: list[StructuredClaim] = []
    comment_blocks = _split_comments(text)

    for comment_id, body in comment_blocks:
        extracted = _extract_claims_from_comment(body, comment_id)
        claims.extend(extracted)

    return claims


def parse_manual_annotations(yaml_path: Path) -> list[StructuredClaim]:
    """Parse manually annotated claims from a YAML file.

    Expected YAML structure::

        claims:
          - claim_type: "visual.copy_move_keypoint"
            target: "Extended Data Fig. 4h"
            description: "upper center ≈ upper left after 90° rotation"
            evidence_type: "image"
    """
    import yaml

    data = yaml.safe_load(yaml_path.read_text())
    raw_claims = data.get("claims", [])
    return [
        StructuredClaim(
            claim_type=str(c.get("claim_type", "")),
            target=str(c.get("target", "")),
            description=str(c.get("description", "")),
            evidence_type=str(c.get("evidence_type", "image")),
            source="manual_annotation",
            confirmed_by_human=bool(c.get("confirmed_by_human", True)),
        )
        for c in raw_claims
        if c.get("claim_type") and c.get("target")
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split_comments(text: str) -> list[tuple[str, str]]:
    """Split a PubPeer post into (comment_id, body) pairs."""
    pattern = re.compile(r"^\*{2}#(\d+)\*{2}", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        return []

    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        cid = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        blocks.append((cid, body))
    return blocks


_CLAIM_PATTERNS: list[tuple[re.Pattern, str, EvidenceType]] = [
    (re.compile(r"(?i)(\d+°\s*(?:clockwise|counterclockwise|rotation|rotate))"), "visual.copy_move_keypoint", "image"),
    (re.compile(r"(?i)(identical|same|复制|重复).*(?:value|row|entry|值|行)"), "source_data.duplicate_columns", "source_data"),
    (re.compile(r"(?i)(fixed\s*(?:difference|ratio)|固定[差比])"), "source_data.fixed_difference", "source_data"),
    (re.compile(r"(?i)(\d+\.\d+)\s*×\s*([A-Z]\w+|PT|RT)"), "source_data.fixed_ratio", "source_data"),
    (re.compile(r"(?i)(N\+20|N\s*\+\s*\d+).*ratio.*dupl"), "source_data.row_offset_exact_reuse", "source_data"),
    (re.compile(r"(?i)(no\s*source\s*data|缺.*source\s*data|missing)"), "completeness.missing_source_data", "completeness"),
    (re.compile(r"(?i)(paired\s*difference|配对[差值]).*(±|range)"), "source_data.paired_difference_spread", "source_data"),
    (re.compile(r"(?i)(blot|band|条带).*(no\s*background|无背景)"), "visual.image_quality", "image"),
]


def _extract_claims_from_comment(body: str, comment_id: str) -> list[StructuredClaim]:
    """Extract claim candidates from a single comment body using regex patterns."""
    claims: list[StructuredClaim] = []

    for pattern, claim_type, evidence_type in _CLAIM_PATTERNS:
        if pattern.search(body):
            target = _extract_target(body)
            first_line = body.split("\n")[0][:200]
            claims.append(StructuredClaim(
                claim_type=claim_type,
                target=target,
                description=first_line,
                evidence_type=evidence_type,
                source="pubpeer",
                comment_id=comment_id,
            ))
            break

    return claims


def _extract_target(body: str) -> str:
    """Extract a paper element locator from comment text."""
    fig_match = re.search(
        r"(?i)(Extended\s+Data\s+)?Fig(?:ure)?\.?\s*(\d+[a-z]?)",
        body,
    )
    if fig_match:
        prefix = "Extended Data " if fig_match.group(1) else ""
        return f"{prefix}Fig. {fig_match.group(2)}"

    sheet_match = re.search(r"(?i)(MOESM\d+|Sheet\s*\d+|Supplementary\s+(?:Data|Table)\s*\d+)", body)
    if sheet_match:
        return sheet_match.group(1)

    return "unknown"
