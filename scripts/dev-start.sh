#!/usr/bin/env bash
# scripts/dev-start.sh — Start Veritas dev environment in background.
# Called by: make dev-up
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
mkdir -p logs

# Load project .env so VERITAS_AUTH_MODE etc. are available to the backend.
if [ -f "$REPO_ROOT/.env" ]; then
  # shellcheck disable=SC1091
  set -a
  . "$REPO_ROOT/.env"
  set +a
fi

LOCAL_DB_URL="${VERITAS_DATABASE_URL:-postgresql://veritas_dev:veritas_dev_pass@127.0.0.1:5433/veritas_dev}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8765}"

echo "→ Starting backend (auth=${VERITAS_AUTH_MODE:-none})..."
VERITAS_DATABASE_URL="$LOCAL_DB_URL" \
VERITAS_DEV=1 \
VERITAS_LOG_DIR=logs \
VERITAS_AUTH_MODE="${VERITAS_AUTH_MODE:-none}" \
VERITAS_USERS_DB="${VERITAS_USERS_DB:-web_data/users.db}" \
PYTHONPATH="$REPO_ROOT" \
  nohup uv run python -c "
from web.backend.veritas_web.app import serve
serve(host='$BACKEND_HOST', port=$BACKEND_PORT, data_root='web_data', output_root='outputs')
" > logs/dev-backend.log 2>&1 &
BACKEND_PID=$!
echo "  Backend PID=$BACKEND_PID"

echo "→ Starting frontend..."
cd "$REPO_ROOT/web/frontend"
nohup npm run dev > "$REPO_ROOT/logs/dev-frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "  Frontend PID=$FRONTEND_PID"

echo "→ Starting celery worker..."
cd "$REPO_ROOT"
VERITAS_DATABASE_URL="$LOCAL_DB_URL" \
VERITAS_DEV=1 \
VERITAS_LOG_DIR=logs \
VERITAS_AUTH_MODE="${VERITAS_AUTH_MODE:-none}" \
VERITAS_USERS_DB="${VERITAS_USERS_DB:-web_data/users.db}" \
PYTHONPATH="$REPO_ROOT" \
  nohup uv run celery -A engine.tasks.celery_app worker --loglevel=debug > "$REPO_ROOT/logs/dev-celery.log" 2>&1 &
CELERY_PID=$!
echo "  Celery PID=$CELERY_PID"

# Wait for backend
echo "→ Waiting for backend..."
for i in $(seq 1 20); do
  if curl -sf --noproxy '*' "http://$BACKEND_HOST:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    echo "  Backend ready."
    break
  fi
  if [ "$i" -eq 20 ]; then
    echo "  ⚠ Backend did not start. Check logs/dev-backend.log"
  fi
  sleep 1
done

# Wait for frontend
echo "→ Waiting for frontend..."
for i in $(seq 1 20); do
  if curl -sf --noproxy '*' "http://localhost:5173" -o /dev/null 2>&1; then
    echo "  Frontend ready."
    break
  fi
  if [ "$i" -eq 20 ]; then
    echo "  ⚠ Frontend did not start. Check logs/dev-frontend.log"
  fi
  sleep 1
done

echo ""
echo "Dev stack ready:"
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://$BACKEND_HOST:$BACKEND_PORT"
echo "  Logs:     logs/dev-backend.log, logs/dev-frontend.log, logs/dev-celery.log, logs/veritas.log"
echo "  Stop:     make dev-down"
