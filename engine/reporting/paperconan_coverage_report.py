"""PaperConan Coverage Summary Report (WP10).

Reports how completely PaperConan detector kinds are covered by the
Veritas canonical signal translator.  Each PaperConan kind should be
in one of these states:

- ``translated``: translated to a Veritas canonical signal.
- ``native_equivalent``: already covered by a Veritas native detector.
- ``native_superset``: covered by Veritas native with more information.
- ``planned``: not yet connected but tracked.
- ``not_applicable``: explicitly excluded with a reason.
- ``skipped``: present in scan output but skipped by translator
    (with a reason recorded in the translation ledger).

This module does NOT read raw PaperConan output.  It consumes the
translation ledger produced by the PaperConan translator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PaperconanCoverageReport:
    """Summary of PaperConan detector coverage in Veritas.

    Attributes:
        total_kinds_tracked: Total PaperConan kinds in the coverage matrix.
        translated: Kinds successfully translated to canonical signals.
        native_equivalent: Kinds covered by native Veritas detectors.
        native_superset: Kinds where Veritas native provides more info.
        planned: Kinds not yet connected.
        not_applicable: Kinds explicitly excluded.
        skipped_in_scan: Kinds present in scan but skipped by translator.
        unexplained_skips: Kinds skipped without a documented reason.
        coverage_rate: Fraction of tracked kinds that are translated,
            native_equivalent, or native_superset.
    """

    total_kinds_tracked: int = 0
    translated: int = 0
    native_equivalent: int = 0
    native_superset: int = 0
    planned: int = 0
    not_applicable: int = 0
    skipped_in_scan: int = 0
    unexplained_skips: int = 0
    coverage_rate: float = 0.0
    kind_details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_kinds_tracked": self.total_kinds_tracked,
            "translated": self.translated,
            "native_equivalent": self.native_equivalent,
            "native_superset": self.native_superset,
            "planned": self.planned,
            "not_applicable": self.not_applicable,
            "skipped_in_scan": self.skipped_in_scan,
            "unexplained_skips": self.unexplained_skips,
            "coverage_rate": self.coverage_rate,
            "kind_details": list(self.kind_details),
        }


def build_paperconan_coverage_report(
    coverage_matrix: list[dict[str, Any]] | None = None,
    translation_ledger: list[dict[str, Any]] | None = None,
) -> PaperconanCoverageReport:
    """Build a PaperConan coverage report.

    Args:
        coverage_matrix: The coverage matrix (e.g. from
            ``configs/paperconan_detector_coverage.yaml``), as a list of
            dicts with at least ``kind`` and ``status`` fields.
        translation_ledger: The translation ledger from the PaperConan
            translator, as a list of dicts with ``kind``, ``status``
            (translated/skipped), and optionally ``skip_reason``.

    Returns:
        A PaperconanCoverageReport summarizing coverage.
    """
    matrix = coverage_matrix or []
    ledger = translation_ledger or []

    # Count coverage matrix statuses
    translated = 0
    native_equivalent = 0
    native_superset = 0
    planned = 0
    not_applicable = 0
    kind_details: list[dict[str, Any]] = []

    for entry in matrix:
        status = entry.get("status", "planned")
        kind = entry.get("kind", "")
        detail = {"kind": kind, "matrix_status": status}

        if status == "translated":
            translated += 1
        elif status == "native_equivalent":
            native_equivalent += 1
        elif status == "native_superset":
            native_superset += 1
        elif status == "planned":
            planned += 1
        elif status == "not_applicable":
            not_applicable += 1

        kind_details.append(detail)

    # Count translation ledger skips
    ledger_by_kind: dict[str, dict[str, Any]] = {}
    for entry in ledger:
        kind = entry.get("kind", "")
        ledger_by_kind[kind] = entry

    skipped_in_scan = 0
    unexplained_skips = 0
    for kind, entry in ledger_by_kind.items():
        if entry.get("status") == "skipped":
            skipped_in_scan += 1
            if not entry.get("skip_reason"):
                unexplained_skips += 1

    # Coverage rate: (translated + native_equivalent + native_superset) / total
    total = len(matrix)
    covered = translated + native_equivalent + native_superset
    coverage_rate = covered / total if total > 0 else 0.0

    return PaperconanCoverageReport(
        total_kinds_tracked=total,
        translated=translated,
        native_equivalent=native_equivalent,
        native_superset=native_superset,
        planned=planned,
        not_applicable=not_applicable,
        skipped_in_scan=skipped_in_scan,
        unexplained_skips=unexplained_skips,
        coverage_rate=round(coverage_rate, 4),
        kind_details=kind_details,
    )
