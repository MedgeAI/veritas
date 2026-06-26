#!/usr/bin/env bash
# scripts/dev-stop.sh — Stop Veritas dev environment.
# Called by: make dev-down
#
# Uses PID files (written by dev-start.sh) for precise process killing.
# Falls back to pkill -f only when PID file is missing (crashed start).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# =========================================================================
# Stop local processes via PID files
# =========================================================================

kill_by_pidfile() {
  local pidfile="$1"
  local label="$2"
  if [ -f "$pidfile" ]; then
    local pid
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && echo "  ✓ $label stopped (PID $pid)." || true
      sleep 1
      # Ensure it's dead
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    else
      echo "  - $label not running (stale PID $pid)."
    fi
    rm -f "$pidfile"
  else
    echo "  - $label PID file not found."
  fi
}

echo "→ Stopping frontend..."
kill_by_pidfile "logs/frontend.pid" "Frontend"

echo "→ Stopping backend..."
kill_by_pidfile "logs/backend.pid" "Backend"

echo "→ Stopping celery worker..."
kill_by_pidfile "logs/celery.pid" "Celery worker"

# =========================================================================
# Fallback: pkill for processes that escaped PID tracking
# =========================================================================

# Only if no PID file existed — catches processes from manual starts.
if [ ! -f logs/frontend.pid ]; then
  pkill -f "vite.*5173" 2>/dev/null && echo "  ✓ Frontend (fallback pkill)." || true
fi
if [ ! -f logs/backend.pid ]; then
  pkill -f "uvicorn.*veritas_web" 2>/dev/null && echo "  ✓ Backend (fallback pkill)." || true
fi
if [ ! -f logs/celery.pid ]; then
  pkill -f "celery.*engine.tasks.celery_app" 2>/dev/null && echo "  ✓ Celery (fallback pkill)." || true
fi

# =========================================================================
# Stop forensics services
# =========================================================================

echo "→ Stopping forensics services..."
docker compose -p vdev -f deploy/docker-compose.forensics.yml down 2>/dev/null \
  && echo "  ✓ Forensics services stopped." \
  || echo "  - Forensics services not running."

# =========================================================================
# Stop PostgreSQL
# =========================================================================

echo "→ Stopping PostgreSQL..."
docker compose -p vdev -f deploy/docker-compose.local-db.yml stop postgres 2>/dev/null \
  && echo "  ✓ PostgreSQL stopped." \
  || echo "  - PostgreSQL not running."

echo "Done."
