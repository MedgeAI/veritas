from __future__ import annotations

import os
from pathlib import Path

NO_ENV_FILE_MARKER = "VERITAS_NO_ENV_FILE"

# Default log directory (repo-relative).  Override with VERITAS_LOG_DIR.
DEFAULT_LOG_DIR = "logs/"


def get_env(
    key: str, *, required: bool = True, default: str | None = None
) -> str | None:
    """Read an environment variable with fail-loud semantics.

    This is the single point of env-var access for business code.
    Do not use os.getenv / os.environ in engine/ or web/backend/.

    Args:
        key: Environment variable name.
        required: If True (default), raise RuntimeError when the variable
            is missing or empty.  Set to False for optional configuration.
        default: Fallback value returned when the variable is missing/empty
            and *required* is False.  Ignored when *required* is True.

    Returns:
        The variable value, or *default* if not set and not required.

    Raises:
        RuntimeError: If *required* is True and the variable is not set
            or is empty.
    """
    value = os.environ.get(key)
    if value:
        return value
    if required:
        raise RuntimeError(
            f"Required environment variable {key!r} is not set. "
            f"Set it in the shell or in the project .env file."
        )
    return default


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
