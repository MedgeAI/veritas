#!/usr/bin/env bash
# scripts/dev-stop.sh — Stop Veritas dev environment.
# Called by: make dev-down
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "→ Stopping frontend..."
pkill -f "vite.*5173" 2>/dev/null && echo "  Frontend stopped." || echo "  Frontend not running."

echo "→ Stopping backend..."
pkill -f "veritas_web.app.*serve" 2>/dev/null && echo "  Backend stopped." || echo "  Backend not running."
pkill -f "uvicorn.*veritas_web" 2>/dev/null && echo "  Backend (uvicorn) stopped." || true

echo "→ Stopping celery worker..."
pkill -f "celery.*engine.tasks.celery_app" 2>/dev/null && echo "  Celery worker stopped." || echo "  Celery worker not running."

echo "→ Stopping PostgreSQL..."
cd "$REPO_ROOT"
COMPOSE_DB="docker compose -p vdev -f deploy/docker-compose.local-db.yml"
$COMPOSE_DB stop postgres 2>/dev/null && echo "  PostgreSQL stopped." || echo "  PostgreSQL not running."

echo "Done."
