"""Numeric forensics adapter for Veritas static audit.

Wraps the upstream ``research-integrity-auditor`` numeric forensics script
(``scripts/numeric_forensics.py``), which extracts numeric leads from MinerU
markdown output (Benford analysis, digit analysis, table relationships,
duplicate detection).

The adapter:
1. Provides a first-party schema (``NumericForensicsArtifact`` via typed_adapters)
   that isolates consumers from upstream field-name changes.
2. Validates upstream output before it reaches report generators or context packs.
3. Enriches the artifact with ``limitations`` metadata so downstream consumers
   can surface capability boundaries to the user.

Upstream output schema (controlled by ``scripts/numeric_forensics.py``)::

    {
      "source_markdown": str,
      "scope": "auto" | "tables" | "all",
      "effective_scope": str,
      "all_number_count": int,
      "number_count": int,
      "table_count": int,
      "duplicates": {...},
      "digits": {...},
      "benford": {
        "applicability": "applicable" | "not_applicable",
        "reason": str,
        "sample_size": int,
        "orders_of_magnitude": float,
        "observed": {digit: probability},
        "expected": {digit: probability},
        "mean_absolute_deviation": float
      },
      "table_relationships": [...],
      "records_sample": [...]
    }

First-party consumer contract (``NumericForensicsArtifact`` in typed_adapters):
  - ``all_number_count``, ``number_count``, ``table_count``, ``effective_scope``
  - ``benford_mad``          <- ``benford.mean_absolute_deviation`` (or legacy ``benford.mad``)
  - ``benford_mean_absolute_deviation`` <- alias for ``benford_mad``
  - ``benford_applicability`` <- ``benford.applicability``
  - ``benford_reason``        <- ``benford.reason``
  - ``limitations``           <- injected by the adapter, not upstream

If upstream changes any of these field names, the adapter raises no exception
(it uses ``.get()`` with safe defaults) and consumers see ``None`` instead of
crashing.  The ``raw`` attribute preserves lossless access to the upstream dict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "invoke_numeric_forensics",
    "enrich_numeric_forensics_artifact",
    "NUMERIC_FORENSICS_ARTIFACT_NAME",
]

NUMERIC_FORENSICS_ARTIFACT_NAME = "numeric_forensics.json"

_LIMITATIONS = [
    "PDF numeric forensics operates on MinerU markdown extraction; OCR errors "
    "and table parsing artifacts can introduce spurious numbers.",
    "Benford analysis requires >= 100 plausible quantities spanning >= 2 orders "
    "of magnitude; below that threshold applicability is 'not_applicable'.",
    "Table relationships (fixed-difference / fixed-ratio candidates) are leads "
    "only; they require human review before escalation.",
    "Upstream field names are not under Veritas control; all consumers MUST "
    "read via NumericForensicsArtifact typed adapter, not raw dict access.",
]


def invoke_numeric_forensics(
    output_path: Path,
    *,
    upstream_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich upstream numeric forensics output into a first-party artifact.

    The pipeline invokes the upstream ``scripts/numeric_forensics.py`` as a
    subprocess (via ``run_command``).  After the subprocess completes, this
    function is called to:

    1. Load the upstream JSON that was just written.
    2. Validate that required keys are present.
    3. Enrich the artifact with ``limitations`` and ``_veritas_schema_version``.
    4. Rewrite the artifact in place with enriched content.

    Args:
        output_path: Path to the upstream-written JSON artifact.
        upstream_data: Pre-loaded upstream data dict.  When ``None``, the file
            at *output_path* is loaded from disk.

    Returns:
        The enriched artifact dict (also written back to *output_path*).

    Raises:
        FileNotFoundError: If *output_path* does not exist and no
            *upstream_data* was provided.
    """
    if upstream_data is None:
        if not output_path.exists():
            raise FileNotFoundError(
                f"numeric forensics artifact not found: {output_path}"
            )
        upstream_data = json.loads(output_path.read_text(encoding="utf-8"))

    if not isinstance(upstream_data, dict):
        raise ValueError(
            f"numeric forensics artifact root must be a dict, got {type(upstream_data).__name__}"
        )

    enriched = enrich_numeric_forensics_artifact(upstream_data)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return enriched


def enrich_numeric_forensics_artifact(
    upstream_data: dict[str, Any],
) -> dict[str, Any]:
    """Return a first-party enriched copy of the upstream artifact.

    The returned dict contains:
    - ``_veritas_schema_version``: schema version for migration detection.
    - ``limitations``: list of capability limitation strings.
    - ``upstream``: the original upstream data (lossless).
    - All original upstream top-level keys (``benford``, ``all_number_count``,
      etc.) so that both typed and legacy consumers can read the artifact.
    """
    return {
        "_veritas_schema_version": 1,
        "limitations": list(_LIMITATIONS),
        "upstream": upstream_data,
        **upstream_data,
    }
