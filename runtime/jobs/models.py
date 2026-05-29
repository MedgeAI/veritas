from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JobRecord:
    command: str
    workdir: str
    status: str
