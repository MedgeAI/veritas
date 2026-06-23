#!/usr/bin/env bash
# setup_env_permissions.sh — Restrict .env file permissions.
#
# Usage:
#   scripts/setup_env_permissions.sh [PATH_TO_ENV]
#
# Defaults to .env in the repository root (one level above scripts/).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${1:-${REPO_ROOT}/.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE does not exist." >&2
  exit 1
fi

chmod 600 "$ENV_FILE"
echo "chmod 600 $ENV_FILE"

if id veritas &>/dev/null; then
  chown veritas:veritas "$ENV_FILE"
  echo "chown veritas:veritas $ENV_FILE"
else
  echo "veritas user does not exist — skipping chown."
fi

ls -l "$ENV_FILE"
