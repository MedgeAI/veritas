"""Public source data acquisition for Veritas.

Fetches supplementary / source data from public repositories (Nature ESM,
Zenodo, Figshare, Dryad, Europe PMC) given a DOI, title, or direct URL.
All HTTP I/O goes through ``runtime.http_fetch``.
"""
