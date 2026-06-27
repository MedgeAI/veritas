"""Grade computation and certification tier enforcement.

Computes certification grades based on audit findings and enforces
reproducibility tier caps. The tier system limits the maximum grade
a case can achieve based on available reproducibility evidence.

Tier → Max Grade mapping:
- full      → A  (Data + Code + Environment + run history)
- partial   → B  (Data + Code + Environment, no run history)
- code_only → C  (Code + data API, data private)
- static    → C- (Paper + result files only)
"""

from __future__ import annotations

from typing import Any

# Reproducibility tier to maximum grade mapping
TIER_MAX_GRADES: dict[str, str] = {
    "full": "A",
    "partial": "B",
    "code_only": "C",
    "static": "C-",
}

# Grade ordering for comparison (lower index = better grade)
GRADE_ORDER: list[str] = ["A", "B", "C", "C-", "D", "F"]


def _grade_rank(grade: str) -> int:
    """Return the rank of a grade (lower is better).

    Unknown grades are ranked worse than F.
    """
    try:
        return GRADE_ORDER.index(grade)
    except ValueError:
        return len(GRADE_ORDER)


def compute_grade(
    findings: list[dict[str, Any]],
    reproducibility_tier: str | None = None,
) -> dict[str, Any]:
    """Compute certification grade from findings with optional tier cap.

    Args:
        findings: List of finding dicts from the audit. Each finding should
            have a 'risk_level' field ('critical', 'high', 'medium', 'low', 'info').
        reproducibility_tier: Optional tier name ('full', 'partial', 'code_only',
            'static'). If provided, the computed grade is capped at the tier's
            maximum. If None or unrecognized, no cap is applied.

    Returns:
        A dict with:
        - 'grade': The final certification grade (str)
        - 'base_grade': The grade before tier cap (str)
        - 'tier_capped': Whether the grade was downgraded by tier cap (bool)
        - 'reproducibility_tier': The tier that was applied (str or None)
        - 'summary': Human-readable explanation (str)

    Grade computation logic:
    - Any 'critical' finding → F
    - Any 'high' finding → D
    - Any 'medium' finding → C-
    - Only 'low' findings → C
    - Only 'info' findings → B
    - No findings → A
    """
    if not findings:
        base_grade = "A"
    else:
        risk_levels = {f.get("risk_level", "info") for f in findings}
        if "critical" in risk_levels:
            base_grade = "F"
        elif "high" in risk_levels:
            base_grade = "D"
        elif "medium" in risk_levels:
            base_grade = "C-"
        elif "low" in risk_levels:
            base_grade = "C"
        else:
            base_grade = "B"

    # Apply tier cap if specified
    tier_capped = False
    final_grade = base_grade
    applied_tier = None

    if reproducibility_tier and reproducibility_tier in TIER_MAX_GRADES:
        applied_tier = reproducibility_tier
        max_grade = TIER_MAX_GRADES[reproducibility_tier]

        # If base grade is better (lower rank) than tier max, cap it
        if _grade_rank(base_grade) < _grade_rank(max_grade):
            final_grade = max_grade
            tier_capped = True

    # Build summary
    if tier_capped:
        summary = (
            f"Base grade {base_grade} capped to {final_grade} by "
            f"reproducibility tier '{applied_tier}' (max {max_grade})."
        )
    elif applied_tier:
        summary = f"Grade {final_grade} within tier '{applied_tier}' limits."
    else:
        summary = f"Grade {final_grade} computed from findings."

    return {
        "grade": final_grade,
        "base_grade": base_grade,
        "tier_capped": tier_capped,
        "reproducibility_tier": applied_tier,
        "summary": summary,
    }
