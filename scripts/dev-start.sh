#!/usr/bin/env bash
# scripts/dev-start.sh — Start Veritas dev environment in background.
# Called by: make dev-up
#
# Log layout (semantic grouping — see "Log layout" below):
#   logs/infra/     PostgreSQL, Redis              (Docker containers)
#   logs/app/       Backend (uvicorn), Frontend (Vite)
#   logs/worker/    Celery worker, Forensics (SILA + ELIS)
#   logs/veritas.log   Runtime business log (written by Python via
#                     VERITAS_LOG_DIR; path contract shared with prod)
#
# Design decisions:
#   1. No redundant env-var passing — Python entry points (app.py,
#      celery_app.py) call load_project_env() which reads .env and
#      injects into os.environ.  Shell exports still override via setdefault.
#   2. PID files colocated with their log files under logs/{infra,app,worker}/
#      for precise process management.
#   3. Backend uses uvicorn --reload for code hot-reload.
#   4. Pre-flight checks BEFORE starting any service.
#   5. Fail-loud: backend not ready in 30s → exit 1 (not silent success).
#   6. Forensics services started via Docker Compose (optional —
#      skipped gracefully if base images are not built).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── Log layout ──────────────────────────────────────────────────────────────
mkdir -p logs/infra logs/app logs/worker

COMPOSE_FORE="docker compose -p vdev -f deploy/docker-compose.forensics.yml"
BACKEND_HOST="${VERITAS_HOST:-127.0.0.1}"
BACKEND_PORT="${VERITAS_PORT:-8765}"

# ── Pre-flight checks ───────────────────────────────────────────────────────
echo "→ Pre-flight checks..."

if ! docker info >/dev/null 2>&1; then
  echo "  ✘ Docker daemon not running.  Start Docker first."
  exit 1
fi
echo "  ✓ Docker daemon"

if ! docker image inspect pgvector/pgvector:pg16 >/dev/null 2>&1; then
  echo "  ✘ PostgreSQL image missing.  Run: docker pull pgvector/pgvector:pg16"
  exit 1
fi
echo "  ✓ PostgreSQL image (pgvector/pgvector:pg16)"

if command -v opencode >/dev/null 2>&1; then
  echo "  ✓ opencode ($(command -v opencode))"
else
  echo "  ⚠ opencode not found on PATH (npm install -g opencode-ai)"
fi

for img in veritas-sila-dense:latest veritas-elis-provenance:latest; do
  if docker image inspect "$img" >/dev/null 2>&1; then
    echo "  ✓ Forensics base image: $img"
  else
    echo "  ⚠ Forensics base image missing: $img"
  fi
done

if [ -f "$REPO_ROOT/.env" ]; then
  echo "  ✓ .env file present"
else
  echo "  ⚠ .env file missing — services will use code defaults"
fi

echo "  ✓ Pre-flight complete"
echo ""

# ── Kill stale processes from previous runs ─────────────────────────────────
# PID files now live next to their logs under logs/{infra,app,worker}/.
for pidfile in logs/app/backend.pid logs/app/frontend.pid logs/worker/celery.pid; do
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

# ── Port cleanup: kill orphan Vite processes that escaped PID tracking ──────
# npm run dev forks node children (Vite) that become orphans (PPID=1)
# when the parent dies.  Sweep dev ports before starting fresh.
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

# ── Start services ──────────────────────────────────────────────────────────

# --- Backend (uvicorn with --reload) ---
# stdout/stderr → logs/app/backend.log (uvicorn access logs)
# Business logs   → logs/veritas.log     (via VERITAS_LOG_DIR)
echo "→ Starting backend (uvicorn --reload)..."
VERITAS_DEV=1 VERITAS_LOG_DIR=logs PYTHONPATH="$REPO_ROOT" \
  nohup uv run uvicorn web.backend.veritas_web.app:app \
    --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload \
    --reload-dir engine --reload-dir web/backend \
    > logs/app/backend.log 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > logs/app/backend.pid
echo "  Backend PID=$BACKEND_PID"

# --- Frontend (Vite HMR) ---
echo "→ Starting frontend (Vite HMR)..."
cd "$REPO_ROOT/web/frontend"
nohup npm run dev > "$REPO_ROOT/logs/app/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$REPO_ROOT/logs/app/frontend.pid"
cd "$REPO_ROOT"
echo "  Frontend PID=$FRONTEND_PID"

# --- Celery worker ---
echo "→ Starting celery worker..."
VERITAS_DEV=1 VERITAS_LOG_DIR=logs PYTHONPATH="$REPO_ROOT" \
  nohup uv run celery -A engine.tasks.celery_app worker --loglevel=debug \
    > logs/worker/celery.log 2>&1 &
CELERY_PID=$!
echo "$CELERY_PID" > logs/worker/celery.pid
echo "  Celery PID=$CELERY_PID"

# --- Forensics services (optional — skip gracefully if images not built) ---
echo "→ Starting forensics services..."
if $COMPOSE_FORE up -d --build > logs/worker/forensics.log 2>&1; then
  echo "  ✓ Forensics services started (SILA :8770, ELIS :8771)"
  # Track the compose up process so dev-stop.sh can decide whether to down.
  echo "$!" > logs/worker/forensics.pid
else
  echo "  ⚠ Forensics services skipped (build failed or base images missing)"
  echo "    See logs/worker/forensics.log for details"
  rm -f logs/worker/forensics.pid
fi

# ── Wait for readiness ──────────────────────────────────────────────────────
# Fail-loud: if backend/frontend doesn't come up, exit non-zero so callers
# (CI, scripts, humans reading $?) know the stack is broken — don't mask it.

echo "→ Waiting for backend..."
backend_ready=0
for i in $(seq 1 30); do
  if curl -sf --noproxy '*' "http://$BACKEND_HOST:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    echo "  ✓ Backend ready."
    backend_ready=1
    break
  fi
  sleep 1
done
if [ "$backend_ready" -ne 1 ]; then
  echo "  ✘ Backend did not start within 30s.  Check logs/app/backend.log"
  exit 1
fi

echo "→ Waiting for frontend..."
for i in $(seq 1 20); do
  if curl -sf --noproxy '*' "http://localhost:5173" -o /dev/null 2>&1; then
    echo "  ✓ Frontend ready."
    break
  fi
  if [ "$i" -eq 20 ]; then
    echo "  ⚠ Frontend did not start within 20s.  Check logs/app/frontend.log"
  fi
  sleep 1
done

echo ""
echo "Dev stack ready:"
echo "  Frontend:  http://localhost:5173"
echo "  Backend:   http://$BACKEND_HOST:$BACKEND_PORT"
echo "  SILA:      http://localhost:8770"
echo "  ELIS:      http://localhost:8771"
echo "  Logs:"
echo "    infra/:  logs/infra/postgres.log   logs/infra/redis.log"
echo "    app/:    logs/app/backend.log      logs/app/frontend.log"
echo "    worker/: logs/worker/celery.log    logs/worker/forensics.log"
echo "    runtime: logs/veritas.log"
echo "  PIDs:      logs/app/{backend,frontend}.pid  logs/worker/celery.pid"
echo "  Stop:      make dev-down"
