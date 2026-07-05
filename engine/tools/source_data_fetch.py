"""Tool Registry entry for ``source_data.fetch_public``.

This is the bridge between the Tool Registry and the source acquisition
orchestrator.  It is the ONLY module in ``engine/tools/`` that knows about
source acquisition.
"""
from __future__ import annotations

import logging
from pathlib import Path

from engine.static_audit.source_acquisition.fetcher import (
    RuntimeFetchClient,
    fetch_public_source_data,
)
from engine.static_audit.source_acquisition.manifest import (
    AcquisitionQuery,
    SourceAcquisitionManifest,
)

logger = logging.getLogger(__name__)


def run_source_data_fetch(
    *,
    output_dir: Path,
    doi: str | None = None,
    title: str | None = None,
    url: str | None = None,
) -> SourceAcquisitionManifest:
    """Execute the ``source_data.fetch_public`` tool.

    Parameters
    ----------
    output_dir:
        Case output directory.  Downloaded files and the manifest are written
        under ``output_dir/source_data/``.
    doi:
        Paper DOI (e.g. ``10.1038/s41558-024-01234-x``).
    title:
        Paper title (used for disambiguation when DOI is unavailable).
    url:
        Direct URL to source data or supplementary material.

    Returns
    -------
    SourceAcquisitionManifest
        The provenance record.  Always written to
        ``output_dir/source_acquisition_manifest.json``.
    """
    query = AcquisitionQuery(doi=doi, title=title, url=url)
    client = RuntimeFetchClient()
    return fetch_public_source_data(query=query, output_dir=output_dir, client=client)
