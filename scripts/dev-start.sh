#!/usr/bin/env bash
# scripts/dev-start.sh — Start Veritas dev environment in background.
# Called by: make dev-up
#
# Design decisions:
#   1. No redundant env-var passing — Python entry points (app.py,
#      celery_app.py) call load_project_env() which reads .env and
#      injects into os.environ.  Shell exports still override via setdefault.
#   2. PID files in logs/*.pid for precise process management.
#   3. Backend uses uvicorn --reload for code hot-reload.
#   4. Pre-flight checks before starting any service.
#   5. Forensics services started via Docker Compose (optional —
#      skipped gracefully if base images are not built).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
mkdir -p logs

COMPOSE_FORE="docker compose -p vdev -f deploy/docker-compose.forensics.yml"
BACKEND_HOST="${VERITAS_HOST:-127.0.0.1}"
BACKEND_PORT="${VERITAS_PORT:-8765}"

# =========================================================================
# Pre-flight checks
# =========================================================================
echo "→ Pre-flight checks..."

# 1. Docker daemon
if ! docker info >/dev/null 2>&1; then
  echo "  ✘ Docker daemon not running.  Start Docker first."
  exit 1
fi
echo "  ✓ Docker daemon"

# 2. PostgreSQL image
if ! docker image inspect pgvector/pgvector:pg16 >/dev/null 2>&1; then
  echo "  ✘ PostgreSQL image missing.  Run: docker pull pgvector/pgvector:pg16"
  exit 1
fi
echo "  ✓ PostgreSQL image (pgvector/pgvector:pg16)"

# 3. opencode
if command -v opencode >/dev/null 2>&1; then
  echo "  ✓ opencode ($(command -v opencode))"
else
  echo "  ⚠ opencode not found on PATH (npm install -g opencode-ai)"
fi

# 4. Forensics images (warn, not fatal)
for img in veritas-sila-dense:latest veritas-elis-provenance:latest; do
  if docker image inspect "$img" >/dev/null 2>&1; then
    echo "  ✓ Forensics base image: $img"
  else
    echo "  ⚠ Forensics base image missing: $img"
  fi
done

# 5. .env file
if [ -f "$REPO_ROOT/.env" ]; then
  echo "  ✓ .env file present"
else
  echo "  ⚠ .env file missing — services will use code defaults"
fi

echo "  ✓ Pre-flight complete"
echo ""

# =========================================================================
# Kill stale processes from previous runs
# =========================================================================
for pidfile in logs/backend.pid logs/frontend.pid logs/celery.pid; do
  if [ -f "$pidfile" ]; then
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      echo "→ Stopping stale process (PID $pid from $(basename "$pidfile"))..."
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  fi
done

# =========================================================================
# Start services
# =========================================================================

# --- Backend (uvicorn with --reload) ---
echo "→ Starting backend (uvicorn --reload)..."
VERITAS_DEV=1 VERITAS_LOG_DIR=logs PYTHONPATH="$REPO_ROOT" \
  nohup uv run uvicorn web.backend.veritas_web.app:app \
    --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload \
    --reload-dir engine --reload-dir web/backend \
    > logs/dev-backend.log 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > logs/backend.pid
echo "  Backend PID=$BACKEND_PID"

# --- Frontend (Vite HMR) ---
echo "→ Starting frontend (Vite HMR)..."
cd "$REPO_ROOT/web/frontend"
nohup npm run dev > "$REPO_ROOT/logs/dev-frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$REPO_ROOT/logs/frontend.pid"
cd "$REPO_ROOT"
echo "  Frontend PID=$FRONTEND_PID"

# --- Celery worker ---
echo "→ Starting celery worker..."
VERITAS_DEV=1 VERITAS_LOG_DIR=logs PYTHONPATH="$REPO_ROOT" \
  nohup uv run celery -A engine.tasks.celery_app worker --loglevel=debug \
    > logs/dev-celery.log 2>&1 &
CELERY_PID=$!
echo "$CELERY_PID" > logs/celery.pid
echo "  Celery PID=$CELERY_PID"

# --- Forensics services (optional — skip gracefully if images not built) ---
echo "→ Starting forensics services..."
if $COMPOSE_FORE up -d --build > logs/dev-forensics.log 2>&1; then
  echo "  ✓ Forensics services started (SILA :8770, ELIS :8771)"
else
  echo "  ⚠ Forensics services skipped (build failed or base images missing)"
  echo "    See logs/dev-forensics.log for details"
fi

# =========================================================================
# Wait for readiness
# =========================================================================

echo "→ Waiting for backend..."
for i in $(seq 1 30); do
  if curl -sf --noproxy '*' "http://$BACKEND_HOST:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    echo "  ✓ Backend ready."
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "  ✘ Backend did not start within 30s.  Check logs/dev-backend.log"
  fi
  sleep 1
done

echo "→ Waiting for frontend..."
for i in $(seq 1 20); do
  if curl -sf --noproxy '*' "http://localhost:5173" -o /dev/null 2>&1; then
    echo "  ✓ Frontend ready."
    break
  fi
  if [ "$i" -eq 20 ]; then
    echo "  ⚠ Frontend did not start within 20s.  Check logs/dev-frontend.log"
  fi
  sleep 1
done

echo ""
echo "Dev stack ready:"
echo "  Frontend:  http://localhost:5173"
echo "  Backend:   http://$BACKEND_HOST:$BACKEND_PORT"
echo "  SILA:      http://localhost:8770"
echo "  ELIS:      http://localhost:8771"
echo "  Logs:      logs/dev-backend.log, logs/dev-frontend.log,"
echo "             logs/dev-celery.log, logs/dev-forensics.log, logs/veritas.log"
echo "  PIDs:      logs/backend.pid, logs/frontend.pid, logs/celery.pid"
echo "  Stop:      make dev-down"
