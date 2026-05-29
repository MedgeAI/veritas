#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT"

if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$PROJECT_ROOT/.env"
  set +a
fi

HOST="${OPENCODE_HOST:-127.0.0.1}"
PORT="${OPENCODE_PORT:-4096}"
COMMAND=(serve --hostname "$HOST" --port "$PORT")

resolve_opencode_bin() {
  if [ -n "${OPENCODE_BIN:-}" ]; then
    printf '%s\n' "$OPENCODE_BIN"
    return 0
  fi

  if command -v opencode >/dev/null 2>&1; then
    command -v opencode
    return 0
  fi

  if command -v npm >/dev/null 2>&1; then
    local npm_root
    npm_root="$(npm root -g 2>/dev/null || true)"
    if [ -x "$npm_root/opencode-ai/bin/opencode.exe" ]; then
      printf '%s\n' "$npm_root/opencode-ai/bin/opencode.exe"
      return 0
    fi
  fi

  return 1
}

if [ -n "${OPENCODE_CORS:-}" ]; then
  IFS=',' read -r -a CORS_ORIGINS <<< "$OPENCODE_CORS"
  for origin in "${CORS_ORIGINS[@]}"; do
    if [ -n "$origin" ]; then
      COMMAND+=(--cors "$origin")
    fi
  done
fi

if [ "${OPENCODE_PRINT_COMMAND:-0}" = "1" ]; then
  printf 'cd %q\n' "$PROJECT_ROOT"
  if OPENCODE_BIN_RESOLVED="$(resolve_opencode_bin)"; then
    printf '%q' "$OPENCODE_BIN_RESOLVED"
  else
    printf 'npx -y opencode-ai@latest'
  fi
  printf ' %q' "${COMMAND[@]}"
  printf '\n'
  exit 0
fi

if OPENCODE_BIN_RESOLVED="$(resolve_opencode_bin)"; then
  exec "$OPENCODE_BIN_RESOLVED" "${COMMAND[@]}"
fi

if command -v npx >/dev/null 2>&1; then
  exec npx -y opencode-ai@latest "${COMMAND[@]}"
fi

cat >&2 <<'EOF'
opencode is not installed and npx is unavailable.

Install one of:
  npm install -g opencode-ai
  curl -fsSL https://opencode.ai/install | bash
EOF
exit 127
