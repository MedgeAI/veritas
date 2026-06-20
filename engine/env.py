from __future__ import annotations

import os
from pathlib import Path


NO_ENV_FILE_MARKER = "VERITAS_NO_ENV_FILE"


def parse_env_file(env_file: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_file.exists():
        return values
    for raw_line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key] = value
    return values


def load_project_env(
    project_root: Path,
    *,
    include_env_file: bool = True,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    if not include_env_file:
        env[NO_ENV_FILE_MARKER] = "1"
        return env
    if env.get(NO_ENV_FILE_MARKER) == "1":
        return env
    for key, value in parse_env_file(Path(project_root) / ".env").items():
        env.setdefault(key, value)
    return env
