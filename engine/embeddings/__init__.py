"""Shared SSCD embedding extraction for Veritas.

Provides ``SSCDEncoder`` for both the CLI audit pipeline and the Web P1 service.
"""

from engine.embeddings.sscd import SSCDEncoder

__all__ = ["SSCDEncoder"]
