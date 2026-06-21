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
warn() { printf '\033[33m[veritas-dev]\033[0m %s\n' "$*"; }

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

# --- 工具可用性检查 ---------------------------------------------------------

check_docker_image() {
    local image=$1
    local description=$2

    if docker images | grep -q "$image.*latest"; then
        ok "✓ $description: 镜像就绪"
        return 0
    else
        err "✗ $description: 镜像缺失"
        return 1
    fi
}

check_model_weights() {
    local path=$1
    local description=$2

    if [[ -f "$path" ]]; then
        ok "✓ $description: $path"
        return 0
    else
        err "✗ $description: 缺失 $path"
        return 1
    fi
}

check_python_dependency() {
    local module=$1
    local description=$2

    cd "$PROJECT_ROOT"
    # 使用 uv run python 而不是系统 python，确保使用虚拟环境中的包
    if docker compose -f "$COMPOSE_FILE" exec -T backend \
        uv run python -c "import $module" 2>/dev/null; then
        ok "✓ $description: 已安装"
        return 0
    else
        err "✗ $description: 未安装"
        return 1
    fi
}

check_pytorch_cuda() {
    cd "$PROJECT_ROOT"
    if docker compose -f "$COMPOSE_FILE" exec -T backend \
        uv run python -c "import torch; assert torch.cuda.is_available(), 'CUDA not available'" 2>/dev/null; then
        ok "✓ PyTorch CUDA: 可用"
        return 0
    else
        warn "⚠ PyTorch CUDA: 不可用（GPU 工具将无法运行）"
        return 1
    fi
}

check_all_tools() {
    log "=== 工具可用性检查 ==="
    echo ""

    local all_ok=true

    # 1. Docker 镜像检查
    log "Docker 镜像:"
    if ! check_docker_image "veritas-elis-provenance" "ELIS provenance (MST 溯源图)"; then
        all_ok=false
        echo "  → 构建: make build-elis-provenance"
    fi
    echo ""

    # 2. 模型权重检查
    log "模型权重:"
    check_model_weights "$PROJECT_ROOT/models/panel_extraction/model_4_class.pt" "Panel extraction (YOLOv5 4-class)" || all_ok=false
    check_model_weights "$PROJECT_ROOT/models/panel_extraction/model_5_class.pt" "Panel extraction (YOLOv5 5-class)" || all_ok=false
    check_model_weights "$PROJECT_ROOT/models/trufor/weights/trufor.pth.tar" "TruFor (伪造检测)" || all_ok=false
    check_model_weights "$PROJECT_ROOT/models/sscd/sscd_disc_mixup.torchscript.pt" "SSCD (embedding encoder)" || all_ok=false
    echo ""

    # 3. Python 依赖检查（在 backend 容器中）
    log "Python 依赖（backend 容器）:"
    check_python_dependency "torch" "PyTorch" || all_ok=false
    check_python_dependency "cv2" "OpenCV" || all_ok=false
    # 注意：YOLOv5 通过 subprocess 调用 ELIS 脚本，不需要 Python import
    echo ""

    # 4. PyTorch CUDA 检查
    log "GPU 支持:"
    if ! check_pytorch_cuda; then
        warn "  → GPU 工具（TruFor/SILA dense/SSCD）需要 CUDA 支持"
        warn "  → 如果开发机有 GPU，请确保 Docker 配置了 NVIDIA runtime"
    fi
    echo ""

    # 5. 总结
    if $all_ok; then
        ok "========================================="
        ok " ✓ 所有工具就绪，可以运行完整审计"
        ok "========================================="
    else
        warn "========================================="
        warn " ⚠ 部分工具缺失，某些功能不可用"
        warn "========================================="
        echo ""
        echo "修复建议:"
        echo "  • 镜像缺失: make build-elis-provenance"
        echo "  • 权重缺失: make download-models"
        echo "  • 依赖缺失: make sync (然后 rebuild backend: docker compose build backend)"
        echo "  • CUDA 不可用: 检查 NVIDIA driver 和 Docker runtime 配置"
    fi
    echo ""
}

init_db() {
    log "初始化数据库表结构..."
    cd "$PROJECT_ROOT"
    docker compose -f "$COMPOSE_FILE" exec -T backend \
        uv run python -c "from web.backend.veritas_web.database import init_db; init_db()" 2>&1
    ok "数据库就绪"
}

reset_db() {
    log "重置数据库（删除所有表并重建）..."
    cd "$PROJECT_ROOT"
    docker compose -f "$COMPOSE_FILE" exec -T backend \
        uv run python -c "
import web.backend.veritas_web.models  # noqa: F401 — populate Base.metadata
from web.backend.veritas_web.database import create_db_engine, Base
engine = create_db_engine()
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
print('✓ 数据库已重置：所有表已删除并重建')
" 2>&1
    ok "数据库已重置"
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

    # 3. 工具可用性检查（在容器启动后运行）
    check_all_tools

    # 4. 初始化 DB
    init_db

    # 5. 释放可能被占用的前端端口
    kill_port "$FRONTEND_PORT"

    # 6. 前端（宿主机 Vite dev server）
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

    # ELIS Provenance
    if docker images | grep -q "veritas-elis-provenance.*latest"; then
        ok "ELIS provenance: 镜像就绪"
    else
        err "ELIS provenance: 镜像缺失 (make build-elis-provenance)"
    fi

    # PostgreSQL
    if docker exec veritas-pg-dev pg_isready -U veritas >/dev/null 2>&1; then
        ok "PostgreSQL    : 运行中 (port $PG_PORT)"
    else
        err "PostgreSQL    : 未运行"
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

cmd_db_reset() {
    log "重置数据库"
    echo ""
    echo "⚠️  WARNING: This will DELETE all data in the database!"
    read -p "Continue? [y/N] " confirm
    if [[ "$confirm" != "y" ]]; then
        log "已取消"
        return 0
    fi

    reset_db

    echo ""
    ok "数据库已重置完成"
    echo ""
}

cmd_check_tools() {
    check_all_tools
}

# --- main ------------------------------------------------------------------

case "${1:-help}" in
    up)          cmd_up          ;;
    down)        cmd_down        ;;
    build)       cmd_build       ;;
    status)      cmd_status      ;;
    logs)        cmd_logs        ;;
    db-reset)    cmd_db_reset    ;;
    check-tools) cmd_check_tools ;;
    *)
        echo "用法: $0 {up|down|build|status|logs|db-reset|check-tools}"
        echo ""
        echo "  up          启动 PostgreSQL + Backend 容器 + Vite 前端"
        echo "  down        停止所有（PG 数据保留）"
        echo "  build       重建 Backend 镜像并重启"
        echo "  status      查看运行状态"
        echo "  logs        查看 Backend 容器 + 前端日志"
        echo "  db-reset    重置数据库（删除所有表并重建）"
        echo "  check-tools 检查所有工具可用性（镜像、权重、依赖、GPU）"
        exit 1
        ;;
esac
