from __future__ import annotations

import os
from pathlib import Path
from typing import MutableMapping

NO_ENV_FILE_MARKER = "VERITAS_NO_ENV_FILE"

# Default log directory (repo-relative).  Override with VERITAS_LOG_DIR.
DEFAULT_LOG_DIR = "logs/"

PROXY_ENV_KEYS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "NO_PROXY",
    "no_proxy",
)


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


def _trust_proxy_env(env: dict[str, str]) -> bool:
    return env.get("VERITAS_TRUST_PROXY_ENV", "").lower() in {"1", "true", "yes", "on"}


def strip_proxy_env(env: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``env`` without process-wide proxy variables.

    Project subprocesses and SDK clients should not inherit desktop proxy
    settings by default because unsupported schemes such as ``socks5h://`` can
    break unrelated HTTP clients.  Set ``VERITAS_TRUST_PROXY_ENV=1`` to opt in.
    """
    if _trust_proxy_env(env):
        return dict(env)
    return {key: value for key, value in env.items() if key not in PROXY_ENV_KEYS}


def strip_proxy_env_inplace(env: MutableMapping[str, str]) -> None:
    """Remove proxy variables from ``os.environ`` unless explicitly trusted."""
    if _trust_proxy_env(dict(env)):
        return
    for key in PROXY_ENV_KEYS:
        env.pop(key, None)


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
    env = strip_proxy_env(dict(os.environ if base_env is None else base_env))
    if not include_env_file:
        env[NO_ENV_FILE_MARKER] = "1"
        return env
    if env.get(NO_ENV_FILE_MARKER) == "1":
        return env
    for key, value in parse_env_file(Path(project_root) / ".env").items():
        env.setdefault(key, value)
    return strip_proxy_env(env)
