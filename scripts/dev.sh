#!/usr/bin/env bash
#
# Veritas 本地开发一键启停
#
# 架构：
#   PostgreSQL + Backend (含 opencode) → Docker 容器
#   Vite 前端 → 宿主机（HMR 热重载）
#
# 用法:
#   ./scripts/dev.sh up      启动全套
#   ./scripts/dev.sh down    停止所有（PG 数据保留）
#   ./scripts/dev.sh status  查看状态
#   ./scripts/dev.sh logs    查看日志
#   ./scripts/dev.sh build   重建 backend 镜像
#
# 端口约定（不碰生产）:
#   PostgreSQL : 5433
#   FastAPI    : 8765 (容器)
#   Vite       : 5173 (宿主机)
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.dev.yml"
COMPOSE="docker compose -f $COMPOSE_FILE"

PG_PORT=5433
API_HOST=127.0.0.1
API_PORT=8765
FRONTEND_PORT=5173

# --- helpers ---------------------------------------------------------------

log()  { printf '\033[36m[veritas-dev]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[veritas-dev]\033[0m %s\n' "$*"; }
err()  { printf '\033[31m[veritas-dev]\033[0m %s\n' "$*" >&2; }

wait_for_pg() {
    for i in $(seq 1 30); do
        if docker exec veritas-pg-dev pg_isready -U veritas >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    err "PostgreSQL 未在 30s 内就绪"
    return 1
}

wait_for_backend() {
    for i in $(seq 1 60); do
        if curl --noproxy '*' -sf "http://$API_HOST:$API_PORT/api/health" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    err "Backend 未在 60s 内就绪"
    return 1
}

kill_port() {
    local port=$1
    local pid
    pid=$(lsof -ti :"$port" 2>/dev/null || true)
    if [[ -n "$pid" ]]; then
        log "释放端口 $port (PID $pid)"
        kill "$pid" 2>/dev/null || true
        sleep 1
    fi
}

init_db() {
    log "初始化数据库表结构..."
    cd "$PROJECT_ROOT"
    docker compose -f "$COMPOSE_FILE" exec -T backend \
        uv run python -c "from web.backend.veritas_web.database import init_db; init_db()" 2>&1
    ok "数据库就绪"
}

# --- commands --------------------------------------------------------------

cmd_up() {
    log "启动 Veritas 本地开发环境"
    echo ""

    # 1. PostgreSQL + Backend
    log "启动 PostgreSQL (port $PG_PORT) + Backend (port $API_PORT)..."
    $COMPOSE up -d postgres backend
    wait_for_pg
    ok "PostgreSQL 就绪"

    # 2. 等 backend 健康检查通过
    log "等待 Backend 启动..."
    if wait_for_backend; then
        ok "Backend 就绪"
    else
        err "Backend 启动失败，查看日志: docker logs veritas-backend-dev"
        return 1
    fi

    # 3. 初始化 DB
    init_db

    # 4. 释放可能被占用的前端端口
    kill_port "$FRONTEND_PORT"

    # 5. 前端（宿主机 Vite dev server）
    log "启动 Vite 前端 (port $FRONTEND_PORT)..."
    cd "$PROJECT_ROOT/web/frontend"
    npm run dev -- --port "$FRONTEND_PORT" > /tmp/veritas-frontend.log 2>&1 &
    local frontend_pid=$!
    echo "$frontend_pid" > /tmp/veritas-frontend.pid
    ok "前端就绪 (PID $frontend_pid)"

    cd "$PROJECT_ROOT"
    echo ""
    ok "========================================="
    ok " Veritas 本地开发环境已启动"
    ok "========================================="
    echo ""
    echo "  前端   : http://$API_HOST:$FRONTEND_PORT"
    echo "  后端   : http://$API_HOST:$API_PORT (容器)"
    echo "  诊断   : curl http://$API_HOST:$API_PORT/api/diag"
    echo "  日志   : ./scripts/dev.sh logs"
    echo "  停止   : ./scripts/dev.sh down"
    echo ""
}

cmd_down() {
    log "停止 Veritas 本地开发环境"
    echo ""

    # 1. 停止前端
    if [[ -f /tmp/veritas-frontend.pid ]]; then
        local pid
        pid=$(cat /tmp/veritas-frontend.pid)
        kill "$pid" 2>/dev/null || true
        rm -f /tmp/veritas-frontend.pid
        log "前端已停止 (PID $pid)"
    fi
    kill_port "$FRONTEND_PORT"

    # 2. 停止容器
    $COMPOSE down
    log "容器已停止（PG 数据保留在 Docker volume）"

    echo ""
    ok "所有服务已停止"
    echo ""
}

cmd_build() {
    log "重建 Backend 镜像（首次约 5 分钟，后续依赖缓存秒级）..."
    $COMPOSE build backend
    ok "镜像构建完成"
    log "重启 Backend..."
    $COMPOSE up -d backend
    wait_for_backend && ok "Backend 就绪" || err "Backend 启动失败"
}

cmd_status() {
    echo "Veritas 本地开发环境状态"
    echo "========================"
    echo ""

    # PostgreSQL
    if docker exec veritas-pg-dev pg_isready -U veritas >/dev/null 2>&1; then
        ok "PostgreSQL  : 运行中 (port $PG_PORT)"
    else
        err "PostgreSQL  : 未运行"
    fi

    # Backend
    if curl --noproxy '*' -sf "http://$API_HOST:$API_PORT/api/health" >/dev/null 2>&1; then
        ok "Backend     : 运行中 (port $API_PORT, 容器)"
    else
        err "Backend     : 未运行"
    fi

    # 前端
    if curl --noproxy '*' -sf "http://$API_HOST:$FRONTEND_PORT" >/dev/null 2>&1; then
        ok "Vite 前端   : 运行中 (port $FRONTEND_PORT, 宿主机)"
    else
        err "Vite 前端   : 未运行"
    fi

    echo ""

    if [[ -f /tmp/veritas-frontend.pid ]]; then
        echo "  前端 PID: $(cat /tmp/veritas-frontend.pid)"
    fi
}

cmd_logs() {
    echo "=== Backend 容器日志 (最后 50 行) ==="
    docker logs --tail 50 veritas-backend-dev 2>&1 || echo "(容器未运行)"
    echo ""
    echo "=== 前端日志 (最后 20 行) ==="
    if [[ -f /tmp/veritas-frontend.log ]]; then
        tail -20 /tmp/veritas-frontend.log
    else
        echo "(无日志文件)"
    fi
}

# --- main ------------------------------------------------------------------

case "${1:-help}" in
    up)     cmd_up     ;;
    down)   cmd_down   ;;
    build)  cmd_build  ;;
    status) cmd_status ;;
    logs)   cmd_logs   ;;
    *)
        echo "用法: $0 {up|down|build|status|logs}"
        echo ""
        echo "  up      启动 PostgreSQL + Backend 容器 + Vite 前端"
        echo "  down    停止所有（PG 数据保留）"
        echo "  build   重建 Backend 镜像并重启"
        echo "  status  查看运行状态"
        echo "  logs    查看 Backend 容器 + 前端日志"
        exit 1
        ;;
esac
