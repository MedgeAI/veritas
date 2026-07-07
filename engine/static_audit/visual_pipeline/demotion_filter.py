"""Visual finding demotion filter.

Determines which visual findings lack sufficient corroboration from
independent detectors and should be demoted from the primary report
to ``visual/candidates/``.

A demoted finding is not deleted -- it is preserved as a
:class:`~engine.static_audit.visual_schemas.DemotedCandidate` record
for manual review but excluded from the main findings rendering path.

Demotion is based on *corroboration*: a demotable finding is only
promoted to the primary report when at least one other detector family
has produced a finding at the same scope (panel pair, figure, or
figure pair).

Design rationale (see PRD ``docs/product/Veritas-视觉能力产品化改进PRD-ELIS边界-20260706.md``
§7 Phase 0):

* ``exact_duplicate`` (SHA-256 match) is common from export pipelines;
  without geometric overlap it is likely a benign duplicate.
* ``dhash_similar`` is a weak perceptual signal with many false positives
  from similar experimental conditions.
* ``forged_region_suspicious`` (TruFor) alone has high FP rates on
  cropped/resized/compressed images.
* ``visual_provenance_relationship`` edges are coarse graph signals
  that need detector-level overlap to be actionable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Categories eligible for demotion when uncorroborated.
DEMOTABLE_CATEGORIES: frozenset[str] = frozenset(
    {
        "exact_duplicate",
        "dhash_similar",
        "forged_region_suspicious",
        "visual_provenance_relationship",
    }
)


@dataclass(frozen=True)
class DemotionRule:
    """Declares which detector families must corroborate a demotable category.

    A finding in ``category`` is *promoted* when at least one finding at the
    same scope belongs to any family listed in ``requires_any_of``.
    Otherwise it is *demoted*.
    """

    category: str
    requires_any_of: frozenset[str]
    reason: str


#: Default demotion rules derived from PRD Phase 0 product decision.
DEFAULT_DEMOTION_RULES: tuple[DemotionRule, ...] = (
    DemotionRule(
        category="exact_duplicate",
        requires_any_of=frozenset({"copy_move", "overlap_reuse"}),
        reason="SHA-256 exact match without geometric verification",
    ),
    DemotionRule(
        category="dhash_similar",
        requires_any_of=frozenset({"copy_move", "overlap_reuse"}),
        reason="dHash perceptual similarity without geometric verification",
    ),
    DemotionRule(
        category="forged_region_suspicious",
        requires_any_of=frozenset({"copy_move", "overlap_reuse"}),
        reason="TruFor-alone without overlap verification",
    ),
    DemotionRule(
        category="visual_provenance_relationship",
        requires_any_of=frozenset(
            {
                "copy_move",
                "overlap_reuse",
                "dhash_similar",
                "exact_duplicate",
            }
        ),
        reason="Provenance-alone without other detector corroboration",
    ),
)


#: Map from finding ``category`` to the detector family that produced it.
_CATEGORY_TO_FAMILY: dict[str, str] = {
    "copy_move_single": "copy_move",
    "copy_move_cross": "copy_move",
    "overlap_reuse_cross_panel": "overlap_reuse",
    "exact_duplicate": "exact_duplicate",
    "dhash_similar": "dhash_similar",
    "forged_region_suspicious": "tru_for",
    "visual_provenance_relationship": "provenance",
}


# ---------------------------------------------------------------------------
# Scope key
# ---------------------------------------------------------------------------


def _scope_key(finding: dict[str, Any]) -> str:
    """Compute a grouping key for corroboration lookup.

    Different finding types use different scope semantics:

    * Relationship findings (``exact_duplicate``, ``dhash_similar``,
      ``copy_move_*``, ``overlap_reuse_*``): unordered panel pair.
    * TruFor (``forged_region_suspicious``): parent figure ID
      (TruFor is figure-level, not panel-level).
    * Provenance (``visual_provenance_relationship``): ordered figure pair.
    """
    category = finding.get("category", "")
    src = str(finding.get("source_panel_id", ""))
    tgt = str(finding.get("target_panel_id", ""))

    if category == "forged_region_suspicious":
        meta = finding.get("metadata") or {}
        figure_id = meta.get("figure_id") or meta.get("source_parent_figure_id") or src
        return f"fig:{figure_id}"

    if category == "visual_provenance_relationship":
        src_fig = str(finding.get("source_figure") or finding.get("source_node") or "")
        tgt_fig = str(finding.get("target_figure") or finding.get("target_node") or "")
        return f"figpair:{min(src_fig, tgt_fig)}:{max(src_fig, tgt_fig)}"

    return f"panel:{min(src, tgt)}:{max(src, tgt)}"


# ---------------------------------------------------------------------------
# Corroboration index
# ---------------------------------------------------------------------------


def _build_corroboration_index(
    all_findings: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """Build ``scope_key -> set of detector families`` present at that scope.

    This is the core data structure: for each scope (panel pair, figure,
    figure pair), which detector families have produced findings there?
    A demotable finding is promoted when its scope has at least one
    corroborating family.
    """
    index: dict[str, set[str]] = {}
    for finding in all_findings:
        family = _CATEGORY_TO_FAMILY.get(finding.get("category", ""), "")
        if not family:
            continue
        key = _scope_key(finding)
        index.setdefault(key, set()).add(family)
    return index


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_findings(
    findings: list[dict[str, Any]],
    *,
    rules: tuple[DemotionRule, ...] = DEFAULT_DEMOTION_RULES,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split findings into ``(promoted, demoted)`` based on corroboration.

    Args:
        findings: All visual findings dicts from ``build_visual_findings``
            and provenance edge conversion.
        rules: Demotion rules to apply.  Defaults to
            :data:`DEFAULT_DEMOTION_RULES`.

    Returns:
        ``(promoted, demoted)`` -- both lists contain the original finding
        dicts unchanged.  The caller is responsible for wrapping demoted
        findings in :class:`DemotedCandidate` records and writing them to
        the candidates artifact.
    """
    corroboration = _build_corroboration_index(findings)
    rule_map = {rule.category: rule for rule in rules}

    promoted: list[dict[str, Any]] = []
    demoted: list[dict[str, Any]] = []

    for finding in findings:
        category = finding.get("category", "")
        rule = rule_map.get(category)

        # Not a demotable category or no rule matches → always promote.
        if rule is None or category not in DEMOTABLE_CATEGORIES:
            promoted.append(finding)
            continue

        key = _scope_key(finding)
        families_at_scope = corroboration.get(key, set())
        corroborating = families_at_scope & rule.requires_any_of

        if corroborating:
            promoted.append(finding)
        else:
            demoted.append(finding)

    return promoted, demoted
