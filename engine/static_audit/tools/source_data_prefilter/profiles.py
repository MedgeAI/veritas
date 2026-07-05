"""Profile definitions for the deterministic prefilter ledger.

Each profile controls how detector signals are routed through the prefilter:

- ``forensic``: preserve every raw signal with full visibility; no demotion.
- ``review``: apply deterministic demotion rules; hidden signals remain in the
  ledger and diagnostics but are collapsed in the default report view.
- ``triage``: aggressively hide suspected false positives; only the smallest
  candidate set is surfaced by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProfileName = Literal["forensic", "review", "triage"]

# Risk levels ordered from most to least severe.
RISK_ORDER: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "info": 0,
}

VALID_RISK_LEVELS = set(RISK_ORDER)

# False-positive contexts that deterministic rules recognise.  A signal whose
# ``false_positive_context`` intersects the profile's ``benign_contexts`` is
# eligible for demotion (or hiding in triage).
BENIGN_CONTEXTS: frozenset[str] = frozenset(
    {
        "derived_or_unit_conversion",
        "formula_column",
        "complementary_percentage",
        "statistical_summary",
        "normalized_or_scaled",
        "genomic_coordinate",
        "technical_replicate",
        "model_output",
    }
)


@dataclass(frozen=True)
class ProfileDefinition:
    """Declarative description of how a profile treats prefilter actions."""

    name: ProfileName
    # Maps prefilter_action -> profile_action for this profile.
    action_map: dict[str, str]
    # False-positive contexts that trigger demotion/hiding.
    benign_contexts: frozenset[str]
    # Whether signals hidden by this profile remain visible in the report.
    visible_in_report: bool
    # Whether hidden signals are sent to the LLM for verdict.
    sent_to_llm: bool
    # Risk demotion step count (0 = no demotion).
    demotion_steps: int

    def resolve_profile_action(self, prefilter_action: str) -> str:
        return self.action_map.get(prefilter_action, "kept")


FORENSIC = ProfileDefinition(
    name="forensic",
    action_map={"keep": "kept", "downweight": "kept", "drop": "kept"},
    benign_contexts=frozenset(),
    visible_in_report=True,
    sent_to_llm=True,
    demotion_steps=0,
)

REVIEW = ProfileDefinition(
    name="review",
    action_map={"keep": "kept", "downweight": "demoted", "drop": "demoted"},
    benign_contexts=BENIGN_CONTEXTS,
    visible_in_report=True,
    sent_to_llm=True,
    demotion_steps=1,
)

TRIAGE = ProfileDefinition(
    name="triage",
    action_map={"keep": "kept", "downweight": "hidden", "drop": "hidden"},
    benign_contexts=BENIGN_CONTEXTS,
    visible_in_report=False,
    sent_to_llm=False,
    demotion_steps=2,
)

PROFILES: dict[ProfileName, ProfileDefinition] = {
    "forensic": FORENSIC,
    "review": REVIEW,
    "triage": TRIAGE,
}


def get_profile(name: str) -> ProfileDefinition:
    """Return the profile definition for *name*, or raise ``KeyError``."""
    if name not in PROFILES:
        raise KeyError(
            f"Unknown profile {name!r}; expected one of {sorted(PROFILES)}"
        )
    return PROFILES[name]


def demote_risk(risk: str, steps: int) -> str:
    """Demote *risk* by *steps* levels; clamp at ``info``."""
    level = RISK_ORDER.get(risk, 0)
    new_level = max(0, level - steps)
    for label, ordinal in RISK_ORDER.items():
        if ordinal == new_level:
            return label
    return "info"
