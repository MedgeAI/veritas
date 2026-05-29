#!/usr/bin/env python3
"""Compatibility wrapper for the Veritas static audit orchestrator."""

from __future__ import annotations

from engine.static_audit.orchestrator import main


if __name__ == "__main__":
    raise SystemExit(main())
