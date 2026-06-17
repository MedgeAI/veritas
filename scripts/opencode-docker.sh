#!/usr/bin/env bash
#
# opencode Docker wrapper
#
# 在 backend 容器内执行 opencode。opencode 已预装在 backend 镜像中。
# backend 容器由 docker-compose.dev.yml 管理，随 dev.sh up 一起启动。
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TIMEOUT="${OPENCODE_TIMEOUT:-300}"
COMPOSE_CMD=(docker compose -f "$PROJECT_ROOT/docker-compose.dev.yml")

if ! docker inspect veritas-backend-dev >/dev/null 2>&1; then
    echo "[opencode-docker] backend 容器未运行，请先执行 ./scripts/dev.sh up" >&2
    exit 1
fi

exec timeout "$TIMEOUT" "${COMPOSE_CMD[@]}" exec -T \
    -e DASHSCOPE_API_KEY="${DASHSCOPE_API_KEY:-}" \
    -e MINERU_API_TOKEN="${MINERU_API_TOKEN:-}" \
    backend \
    opencode \
    "$@"
