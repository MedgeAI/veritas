"""Typed adapters for static-audit artifacts.

Eliminates raw ``dict.get()`` chains in report consumers by providing
strongly-typed, backward-compatible views of audit findings.

Covered artifacts:
- ``source_data_pair_forensics.json``  -> ``PairForensicsFinding`` / ``PairForensicsArtifact``
- ``source_data_findings.json``        -> ``SourceDataFinding`` / ``SourceDataFindingsArtifact``
- ``visual_findings.json``             -> ``VisualFinding`` / ``VisualFindingsArtifact``
- ``numeric_forensics.json``           -> ``NumericForensicsArtifact``

The ``from_dict`` classmethod is the single compatibility boundary:
- Missing fields receive safe defaults (no exceptions).
- Historical field-name aliases are resolved in priority order.
- The original dict is preserved in ``raw`` for lossless access.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class PairForensicsFinding:
    """Typed view of a single priority finding from the pair-forensics artifact.

    All public fields have backward-compatible defaults so that historical
    artifacts (which may lack newer fields) parse without error.
    """

    finding_id: str | None
    category: str
    risk_level: str
    workbook: str
    sheet: str | None
    columns: tuple[str, ...]
    support_rows: int
    overlap_rows: int | None
    support_rate: float | None
    row_offset: int | None
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PairForensicsFinding:
        """Parse a raw finding dict with backward-compatible defaults.

        Field-name aliases are resolved in priority order (first hit wins):

        * ``columns``      <- ``columns`` -> ``column_pair`` -> ``column``
        * ``support_rows`` <- ``support_rows`` -> ``matched_pairs`` -> ``equal_rows``
        * ``overlap_rows`` <- ``overlap_rows`` -> ``overlap_pairs`` -> ``overlap_pair_groups``
        """
        columns_raw = (
            _first_present(data, ("columns", "column_pair", "column")) or ()
        )
        if isinstance(columns_raw, list):
            columns = tuple(str(item) for item in columns_raw)
        elif isinstance(columns_raw, tuple):
            columns = columns_raw
        elif isinstance(columns_raw, str):
            columns = (columns_raw,)
        else:
            columns = ()

        support_rows = _coerce_int(
            _first_present(
                data, ("support_rows", "matched_pairs", "equal_rows")
            )
        )
        overlap_rows = _coerce_int_optional(
            _first_present(
                data, ("overlap_rows", "overlap_pairs", "overlap_pair_groups")
            )
        )
        support_rate = _coerce_float_optional(data.get("support_rate"))
        row_offset = _coerce_int_optional(
            _first_present(data, ("row_offset", "pair_id_offset"))
        )

        return cls(
            finding_id=_coerce_str_optional(data.get("finding_id")),
            category=str(data.get("category") or ""),
            risk_level=str(data.get("risk_level") or "info"),
            workbook=str(data.get("workbook") or ""),
            sheet=_coerce_str_optional(data.get("sheet")),
            columns=columns,
            support_rows=support_rows,
            overlap_rows=overlap_rows,
            support_rate=support_rate,
            row_offset=row_offset,
            raw=data,
        )


@dataclass(frozen=True)
class PairForensicsArtifact:
    """Typed view of the full ``source_data_pair_forensics.json`` artifact.

    ``raw`` preserves the entire original dict for consumers that need
    fields not modelled here (e.g. ``finding_clusters``, ``review_tasks``).
    """

    priority_findings: tuple[PairForensicsFinding, ...]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PairForensicsArtifact:
        findings_raw = data.get("priority_findings") or []
        findings = tuple(
            PairForensicsFinding.from_dict(item)
            for item in findings_raw
            if isinstance(item, dict)
        )
        return cls(priority_findings=findings, raw=data)


# ---------------------------------------------------------------------------
# Public loading helpers
# ---------------------------------------------------------------------------


def load_pair_forensics_artifact(path: Path) -> PairForensicsArtifact | None:
    """Load a pair-forensics artifact JSON file into a typed view.

    Returns ``None`` when the file does not exist or is empty/unparseable.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return PairForensicsArtifact.from_dict(data)


def iter_priority_findings(
    artifact: PairForensicsArtifact,
) -> Iterator[PairForensicsFinding]:
    """Iterate over the typed priority findings in an artifact."""
    return iter(artifact.priority_findings)


# ---------------------------------------------------------------------------
# source_data_findings typed adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceDataFinding:
    """Typed view of a single finding from ``source_data_findings.json``.

    Covers both ``findings`` and ``priority_findings`` lists.  All public
    fields have backward-compatible defaults.
    """

    finding_id: str | None
    category: str
    risk_level: str
    workbook: str
    sheet: str | None
    columns: tuple[str, ...]
    support_rows: int
    overlap_rows: int | None
    support_rate: float | None
    equal_rows: int
    confidence: str | None
    artifact_likelihood: str | None
    benign_explanations: tuple[str, ...]
    pressure_test_result: str | None
    manual_review_note: str | None
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceDataFinding:
        """Parse a raw finding dict with backward-compatible defaults.

        Field-name aliases resolved in priority order:

        * ``columns``      <- ``columns`` -> ``column_pair`` -> ``column``
        * ``support_rows`` <- ``support_rows`` -> ``matched_pairs`` -> ``equal_rows``
        """
        columns_raw = (
            _first_present(data, ("columns", "column_pair", "column")) or ()
        )
        if isinstance(columns_raw, list):
            columns = tuple(str(item) for item in columns_raw)
        elif isinstance(columns_raw, tuple):
            columns = columns_raw
        elif isinstance(columns_raw, str):
            columns = (columns_raw,)
        else:
            columns = ()

        support_rows = _coerce_int(
            _first_present(data, ("support_rows", "matched_pairs"))
        )
        equal_rows = _coerce_int(data.get("equal_rows"))
        overlap_rows = _coerce_int_optional(data.get("overlap_rows"))
        support_rate = _coerce_float_optional(data.get("support_rate"))

        benign_raw = data.get("benign_explanations") or []
        benign_explanations = tuple(str(v) for v in benign_raw if isinstance(v, (str, int, float)))

        return cls(
            finding_id=_coerce_str_optional(data.get("finding_id")),
            category=str(data.get("category") or ""),
            risk_level=str(data.get("risk_level") or "info"),
            workbook=str(data.get("workbook") or ""),
            sheet=_coerce_str_optional(data.get("sheet")),
            columns=columns,
            support_rows=support_rows,
            overlap_rows=overlap_rows,
            support_rate=support_rate,
            equal_rows=equal_rows,
            confidence=_coerce_str_optional(data.get("confidence")),
            artifact_likelihood=_coerce_str_optional(data.get("artifact_likelihood")),
            benign_explanations=benign_explanations,
            pressure_test_result=_coerce_str_optional(data.get("pressure_test_result")),
            manual_review_note=_coerce_str_optional(data.get("manual_review_note")),
            raw=data,
        )


@dataclass(frozen=True)
class SourceDataFindingsArtifact:
    """Typed view of the full ``source_data_findings.json`` artifact.

    ``raw`` preserves the entire original dict for consumers that need
    fields not modelled here (e.g. ``claim_to_source_data``, ``summary``).
    """

    priority_findings: tuple[SourceDataFinding, ...]
    findings: tuple[SourceDataFinding, ...]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceDataFindingsArtifact:
        pf_raw = data.get("priority_findings") or []
        f_raw = data.get("findings") or []
        return cls(
            priority_findings=tuple(
                SourceDataFinding.from_dict(item)
                for item in pf_raw
                if isinstance(item, dict)
            ),
            findings=tuple(
                SourceDataFinding.from_dict(item)
                for item in f_raw
                if isinstance(item, dict)
            ),
            raw=data,
        )


def load_source_data_findings_artifact(path: Path) -> SourceDataFindingsArtifact | None:
    """Load a ``source_data_findings.json`` artifact into a typed view."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return SourceDataFindingsArtifact.from_dict(data)


def iter_source_data_findings(
    artifact: SourceDataFindingsArtifact,
) -> Iterator[SourceDataFinding]:
    """Iterate over typed priority findings in a source-data artifact."""
    return iter(artifact.priority_findings)


# ---------------------------------------------------------------------------
# visual_findings typed adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisualFinding:
    """Typed view of a single finding from ``visual_findings.json``.

    All public fields have backward-compatible defaults.
    """

    finding_id: str | None
    category: str
    risk_level: str
    summary: str
    source_panel_id: str | None
    target_panel_id: str | None
    score: float | None
    overlay_path: str | None
    relationship_id: str | None
    benign_explanations: tuple[str, ...]
    manual_review_questions: tuple[str, ...]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisualFinding:
        """Parse a raw visual finding dict with backward-compatible defaults."""
        benign_raw = data.get("benign_explanations") or []
        questions_raw = data.get("manual_review_questions") or []

        return cls(
            finding_id=_coerce_str_optional(data.get("finding_id")),
            category=str(data.get("category") or "visual_finding"),
            risk_level=str(data.get("risk_level") or "medium"),
            summary=str(data.get("summary") or ""),
            source_panel_id=_coerce_str_optional(data.get("source_panel_id")),
            target_panel_id=_coerce_str_optional(data.get("target_panel_id")),
            score=_coerce_float_optional(data.get("score")),
            overlay_path=_coerce_str_optional(data.get("overlay_path")),
            relationship_id=_coerce_str_optional(data.get("relationship_id")),
            benign_explanations=tuple(
                str(v) for v in benign_raw if isinstance(v, (str, int, float))
            ),
            manual_review_questions=tuple(
                str(v) for v in questions_raw if isinstance(v, (str, int, float))
            ),
            raw=data,
        )


@dataclass(frozen=True)
class VisualFindingsArtifact:
    """Typed view of the full ``visual_findings.json`` artifact.

    ``raw`` preserves the entire original dict for consumers that need
    fields not modelled here (e.g. ``finding_clusters``, ``review_queue``).
    """

    findings: tuple[VisualFinding, ...]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisualFindingsArtifact:
        findings_raw = data.get("findings") or []
        return cls(
            findings=tuple(
                VisualFinding.from_dict(item)
                for item in findings_raw
                if isinstance(item, dict)
            ),
            raw=data,
        )


def load_visual_findings_artifact(path: Path) -> VisualFindingsArtifact | None:
    """Load a ``visual_findings.json`` artifact into a typed view."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return VisualFindingsArtifact.from_dict(data)


def iter_visual_findings(
    artifact: VisualFindingsArtifact,
) -> Iterator[VisualFinding]:
    """Iterate over typed visual findings in an artifact."""
    return iter(artifact.findings)


# ---------------------------------------------------------------------------
# numeric_forensics typed adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NumericForensicsArtifact:
    """Typed view of ``numeric_forensics.json`` (upstream RIA numeric forensics).

    Isolates consumers from upstream field-name changes:
    - ``benford_mad``          reads ``benford.mean_absolute_deviation`` first,
      then falls back to ``benford.mad`` (historical alias).
    - ``benford_mean_absolute_deviation`` is an explicit alias for ``benford_mad``.
    - ``benford_applicability`` reads ``benford.applicability``.
    - ``limitations`` reads the adapter-injected ``limitations`` list.

    ``raw`` preserves the entire original dict for consumers that need
    fields not modelled here (e.g. ``duplicates``, ``digits``,
    ``table_relationships``, ``records_sample``).
    """

    all_number_count: int | None
    number_count: int | None
    table_count: int | None
    effective_scope: str | None
    benford_mad: float | None
    benford_mean_absolute_deviation: float | None
    benford_applicability: str | None
    benford_reason: str | None
    benford_sample_size: int | None
    benford_orders_of_magnitude: float | None
    limitations: tuple[str, ...]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NumericForensicsArtifact:
        """Parse a raw numeric forensics dict with backward-compatible defaults.

        The adapter-enriched artifact may wrap upstream data in an ``upstream``
        key; this method transparently unwraps it so consumers do not need to
        know whether they are reading enriched or raw upstream data.

        Field-name aliases (first hit wins):
        * ``benford_mad``      <- ``benford.mean_absolute_deviation`` -> ``benford.mad``
        * ``benford_applicability`` <- ``benford.applicability``
        """
        # Support both enriched (with ``upstream`` wrapper) and raw upstream.
        upstream = data.get("upstream") if isinstance(data.get("upstream"), dict) else None
        benford_source = upstream if upstream is not None else data

        benford_raw = benford_source.get("benford") or {}
        if not isinstance(benford_raw, dict):
            benford_raw = {}

        # mad: prefer mean_absolute_deviation, fall back to mad (legacy alias).
        mad_value: float | None
        mad_value = _coerce_float_optional(
            benford_raw.get("mean_absolute_deviation")
        )
        if mad_value is None:
            mad_value = _coerce_float_optional(benford_raw.get("mad"))

        limitations_raw = data.get("limitations") or []
        if not isinstance(limitations_raw, list):
            limitations_raw = []

        return cls(
            all_number_count=_coerce_int_optional(
                benford_source.get("all_number_count")
            ),
            number_count=_coerce_int_optional(benford_source.get("number_count")),
            table_count=_coerce_int_optional(benford_source.get("table_count")),
            effective_scope=_coerce_str_optional(benford_source.get("effective_scope")),
            benford_mad=mad_value,
            benford_mean_absolute_deviation=mad_value,
            benford_applicability=_coerce_str_optional(benford_raw.get("applicability")),
            benford_reason=_coerce_str_optional(benford_raw.get("reason")),
            benford_sample_size=_coerce_int_optional(benford_raw.get("sample_size")),
            benford_orders_of_magnitude=_coerce_float_optional(
                benford_raw.get("orders_of_magnitude")
            ),
            limitations=tuple(
                str(v) for v in limitations_raw if isinstance(v, str)
            ),
            raw=data,
        )


def load_numeric_forensics_artifact(path: Path) -> NumericForensicsArtifact | None:
    """Load a ``numeric_forensics.json`` artifact into a typed view.

    Returns ``None`` when the file does not exist or is empty/unparseable.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return NumericForensicsArtifact.from_dict(data)


def load_numeric_forensics_from_workdir(
    workdir: Path, artifact_name: str = "numeric_forensics.json"
) -> NumericForensicsArtifact | None:
    """Load numeric forensics artifact using the standard path mapping.

    Uses ``resolve_artifact_path`` to find the artifact at its mapped location
    (``numeric/forensics.json``), falling back to the legacy flat path.
    """
    from engine.static_audit._shared import resolve_artifact_path  # local import to avoid cycle

    mapped = resolve_artifact_path(workdir, artifact_name)
    result = load_numeric_forensics_artifact(mapped)
    if result is not None:
        return result
    # Legacy flat path fallback.
    legacy = workdir / artifact_name
    if legacy != mapped:
        return load_numeric_forensics_artifact(legacy)
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _first_present(
    data: dict[str, Any], keys: tuple[str, ...]
) -> Any:
    """Return the value for the first key in *keys* that exists and is truthy."""
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return None


def _coerce_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_int_optional(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float_optional(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_str_optional(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
