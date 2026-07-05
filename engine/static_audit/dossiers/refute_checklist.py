"""Refute checklist: 10-item schema for red-team review of numeric signals.

Each item represents a potential benign explanation that the red-team
reviewer must attempt to verify or reject. The checklist is fixed and
schema-ized to prevent LLM free-form hallucination.

Per PRD §3.5 and WP7 Refute checklist.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Literal


RefuteStatus = Literal[
    "checked_no_fit",         # Checked, does not explain the signal
    "plausible_unconfirmed",  # Plausible but cannot be confirmed with current data
    "confirmed",              # Confirmed as the benign explanation
    "not_applicable",         # Not applicable to this signal
    "not_checked",            # Not yet checked
]


@dataclass(frozen=True)
class RefuteChecklistItem:
    """A single item in the red-team refute checklist.

    Attributes:
        mechanism: Canonical mechanism identifier.
        label: Human-readable description.
        description: Detailed explanation of what this mechanism means.
        default_status: Default status for a new review.
    """

    mechanism: str
    label: str
    description: str
    default_status: RefuteStatus = "not_checked"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# The 10-item refute checklist (fixed, schema-ized).
REFUTE_CHECKLIST: list[RefuteChecklistItem] = [
    RefuteChecklistItem(
        mechanism="shared_control_or_replot",
        label="Shared control / baseline replot",
        description=(
            "The apparent duplicate or offset data may come from the same "
            "control group or baseline being replot in multiple panels."
        ),
    ),
    RefuteChecklistItem(
        mechanism="same_data_replot",
        label="Same data replot / duplicate upload",
        description=(
            "The same dataset may have been plotted in different ways "
            "(e.g., bar chart vs. line chart) or accidentally uploaded twice."
        ),
    ),
    RefuteChecklistItem(
        mechanism="unit_conversion_or_formula",
        label="Unit conversion / formula / normalization",
        description=(
            "The numeric relationship may be explained by a unit conversion, "
            "a normalization formula, or a deterministic transformation."
        ),
    ),
    RefuteChecklistItem(
        mechanism="fixed_denominator",
        label="Fixed denominator / percentage",
        description=(
            "Values may appear related because they share a fixed denominator "
            "(e.g., percentages of the same total)."
        ),
    ),
    RefuteChecklistItem(
        mechanism="axis_dose_time_rank_coordinate",
        label="Axis / dose / time / rank / coordinate transformation",
        description=(
            "The pattern may arise from axis transformations, dose-response "
            "ordering, time-series alignment, or coordinate mapping."
        ),
    ),
    RefuteChecklistItem(
        mechanism="technical_replicate",
        label="Technical replicate / repeated instrument read",
        description=(
            "Values may be technical replicates (same sample measured "
            "multiple times) rather than independent biological replicates."
        ),
    ),
    RefuteChecklistItem(
        mechanism="boundary_censoring_missing_fill",
        label="Boundary / censoring / missing fill",
        description=(
            "The pattern may be explained by detection limits, data "
            "censoring, or fill values for missing data."
        ),
    ),
    RefuteChecklistItem(
        mechanism="model_output_statistical_summary",
        label="Model output / statistical summary / omics matrix",
        description=(
            "The data may be model outputs, statistical summaries "
            "(mean/SEM/SD), or an omics expression matrix rather than "
            "raw measurements."
        ),
    ),
    RefuteChecklistItem(
        mechanism="methods_legend_allows_reuse",
        label="Methods/legend explicitly allows reuse",
        description=(
            "The paper's Methods or figure legend may explicitly state "
            "that the data is reused, replotted, or derived from a shared "
            "source."
        ),
    ),
    RefuteChecklistItem(
        mechanism="missing_provenance_independence_premise",
        label="Missing provenance or independence premise",
        description=(
            "The signal cannot be evaluated because the provenance of the "
            "data or the independence premise is not established. This is "
            "a meta-reason: the data itself may be fine, but we lack "
            "enough context to assess the signal."
        ),
    ),
]


def get_checklist_item(mechanism: str) -> RefuteChecklistItem | None:
    """Look up a checklist item by mechanism identifier."""
    for item in REFUTE_CHECKLIST:
        if item.mechanism == mechanism:
            return item
    return None


def all_mechanisms() -> list[str]:
    """Return all mechanism identifiers in order."""
    return [item.mechanism for item in REFUTE_CHECKLIST]


def validate_mechanism(mechanism: str) -> bool:
    """Check if a mechanism string is a valid checklist item."""
    return get_checklist_item(mechanism) is not None
