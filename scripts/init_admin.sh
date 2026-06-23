#!/usr/bin/env bash
# init_admin.sh — Create an admin user via the Veritas Web CLI.
#
# Usage:
#   scripts/init_admin.sh <username> <password> [email] [role]
#
# Arguments:
#   username  Required. Unique username.
#   password  Required. Plain-text password (avoid in production scripts).
#   email     Optional. Defaults to empty.
#   role      Optional. Comma-separated roles. Defaults to "admin".

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ $# -lt 2 ]; then
  echo "Usage: $0 <username> <password> [email] [role]" >&2
  exit 1
fi

USERNAME="$1"
PASSWORD="$2"
EMAIL="${3:-}"
ROLE="${4:-admin}"

CMD=(python -m web.backend.veritas_web.cli add-user "$USERNAME" --roles "$ROLE" --password "$PASSWORD")

if [ -n "$EMAIL" ]; then
  CMD+=(--email "$EMAIL")
fi

cd "$REPO_ROOT"
echo "Creating user '$USERNAME' with role '$ROLE'..."
PYTHONPATH=. uv run "${CMD[@]}"
echo "Done."
