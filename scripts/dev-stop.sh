#!/usr/bin/env bash
# scripts/dev-stop.sh — Stop Veritas dev environment.
# Called by: make dev-down
#
# Symmetric teardown for dev-start.sh:
#   - App services (backend, frontend) killed via PID files in logs/app/
#   - Worker services (celery, forensics) killed via PID files in logs/worker/
#   - Forensics docker-compose brought down (removes containers + network)
#   - DB (postgres + redis) brought down via `docker compose down`
#     (deletes containers, releases ports, PRESERVES volumes — cattle, not pets)
#   - Fallback pkill sweeps for processes that escaped PID tracking
#   - Orphan Vite process sweep on dev ports
#
# NOTE: logs/veritas.log is NOT touched — it's the runtime business log
# shared with prod (/app/logs/veritas.log in Docker), path controlled
# by VERITAS_LOG_DIR.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# =========================================================================
# Kill local processes via PID files (colocated with their logs)
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
kill_by_pidfile "logs/app/frontend.pid" "Frontend"

echo "→ Stopping backend..."
kill_by_pidfile "logs/app/backend.pid" "Backend"

echo "→ Stopping celery worker..."
kill_by_pidfile "logs/worker/celery.pid" "Celery worker"

# =========================================================================
# Fallback: pkill for processes that escaped PID tracking
# =========================================================================
# Only if no PID file existed — catches processes from manual starts
# or from the older layout (logs/*.pid) that haven't been cleaned up.

if [ ! -f logs/app/frontend.pid ]; then
  pkill -f "vite.*5173" 2>/dev/null && echo "  ✓ Frontend (fallback pkill)." || true
fi
if [ ! -f logs/app/backend.pid ]; then
  pkill -f "uvicorn.*veritas_web" 2>/dev/null && echo "  ✓ Backend (fallback pkill)." || true
fi
if [ ! -f logs/worker/celery.pid ]; then
  pkill -f "celery.*engine.tasks.celery_app" 2>/dev/null && echo "  ✓ Celery (fallback pkill)." || true
fi

# =========================================================================
# Port cleanup: kill orphan Vite/Node processes on dev ports
# =========================================================================
# npm run dev forks a node child (Vite) that escapes PID tracking.
# When the parent npm dies, the child becomes an orphan (PPID=1)
# and keeps its port occupied.  Always sweep after PID-based kill.

echo "→ Cleaning up orphan Vite processes on dev ports..."
FRONTEND_DIR="$REPO_ROOT/web/frontend"
for port in 5173 5174 5175 5176 5177 5178 5179; do
  pids=$(lsof -ti:$port 2>/dev/null | sort -u || true)
  for pid in $pids; do
    cmd=$(ps -p "$pid" -o cmd= 2>/dev/null || true)
    if echo "$cmd" | grep -q "vite" && echo "$cmd" | grep -q "$FRONTEND_DIR"; then
      kill "$pid" 2>/dev/null && echo "  ✓ Killed orphan Vite PID $pid on port $port" || true
    fi
  done
done

# =========================================================================
# Stop forensics services (SILA + ELIS docker-compose)
# =========================================================================
# If forensics was started, a PID file exists — use it as the signal that
# `docker compose down` is meaningful.  Without this guard, every dev-down
# would print a noisy "not running" line.

echo "→ Stopping forensics services..."
if [ -f logs/worker/forensics.pid ]; then
  docker compose -p vdev -f deploy/docker-compose.forensics.yml down 2>/dev/null \
    && echo "  ✓ Forensics services stopped." \
    || echo "  - Forensics services already stopped."
  rm -f logs/worker/forensics.pid
else
  echo "  - Forensics services not running (no PID file)."
fi

# =========================================================================
# Stop DB infrastructure (PostgreSQL + Redis)
# =========================================================================
# `down` (not `stop`) — deletes containers, releases ports, preserves volumes.
# This prevents zombie docker-proxy processes from holding ports between
# dev-up cycles.  Data lives in the `pgdata_dev` volume and is NOT deleted.
#
# Symmetry: dev-start.sh (via make dev-up) runs `up -d postgres redis`,
# so dev-down must bring both down.  The previous version only stopped
# postgres and leaked redis — fixed here.

echo "→ Stopping PostgreSQL + Redis..."
docker compose -p vdev -f deploy/docker-compose.local-db.yml down 2>/dev/null \
  && echo "  ✓ PostgreSQL + Redis stopped (containers removed, ports released, data preserved)." \
  || echo "  - DB not running."

echo "Done."
