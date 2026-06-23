#!/bin/bash
# Veritas 部署验证脚本
# 验证所有部署增强功能是否正常工作

set -e

echo "╔══════════════════════════════════════════════════════╗"
echo "║  Veritas 部署验证                                    ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass() { echo -e "${GREEN}✓${NC} $1" }
fail() { echo -e "${RED}✗${NC} $1"; exit 1 }
warn() { echo -e "${YELLOW}⚠${NC} $1" }

# 1. 检查新增文件
echo "━━━ 1. 检查新增文件 ━━━"
[ -f scripts/setup_env_permissions.sh ] && pass "setup_env_permissions.sh 存在" || fail "setup_env_permissions.sh 缺失"
[ -f scripts/init_admin.sh ] && pass "init_admin.sh 存在" || fail "init_admin.sh 缺失"
[ -f web/backend/veritas_web/permissions.py ] && pass "permissions.py 存在" || fail "permissions.py 缺失"
[ -f web/backend/veritas_web/routers/users.py ] && pass "users.py 存在" || fail "users.py 缺失"
[ -f web/backend/veritas_web/routers/metrics.py ] && pass "metrics.py 存在" || fail "metrics.py 缺失"
[ -f web/backend/veritas_web/logging_config.py ] && pass "logging_config.py 存在" || fail "logging_config.py 缺失"
[ -f web/frontend/src/pages/LoginPage.jsx ] && pass "LoginPage.jsx 存在" || fail "LoginPage.jsx 缺失"
[ -f web/frontend/src/pages/AdminPage.jsx ] && pass "AdminPage.jsx 存在" || fail "AdminPage.jsx 缺失"
[ -f DEPLOYMENT.md ] && pass "DEPLOYMENT.md 存在" || fail "DEPLOYMENT.md 缺失"
echo ""

# 2. 检查脚本可执行权限
echo "━━━ 2. 检查脚本权限 ━━━"
[ -x scripts/setup_env_permissions.sh ] && pass "setup_env_permissions.sh 可执行" || fail "setup_env_permissions.sh 不可执行"
[ -x scripts/init_admin.sh ] && pass "init_admin.sh 可执行" || fail "init_admin.sh 不可执行"
echo ""

# 3. 检查 docker-compose.yml 配置
echo "━━━ 3. 检查 docker-compose.yml ━━━"
grep -q "VERITAS_AUTH_MODE=basic" docker-compose.yml && pass "VERITAS_AUTH_MODE=basic 已配置" || fail "VERITAS_AUTH_MODE 未配置"
grep -q "VERITAS_USERS_DB=/app/web_data/users.db" docker-compose.yml && pass "VERITAS_USERS_DB 已配置" || fail "VERITAS_USERS_DB 未配置"
echo ""

# 4. 检查 .env 文件
echo "━━━ 4. 检查 .env 文件 ━━━"
[ -f .env ] && pass ".env 文件存在" || warn ".env 文件不存在（部署时需要创建）"
if [ -f .env ]; then
    PERMS=$(stat -c %a .env 2>/dev/null || stat -f %Lp .env 2>/dev/null)
    [ "$PERMS" = "600" ] && pass ".env 权限 600" || warn ".env 权限 $PERMS（建议 600）"
fi
echo ""

# 5. 运行测试
echo "━━━ 5. 运行新增测试 ━━━"
TEST_OUTPUT=$(uv run pytest tests/ -q -k "upload_size or concurrency or logging_config or metrics_endpoint or users_api or case_delete" 2>&1)
TEST_COUNT=$(echo "$TEST_OUTPUT" | grep -oP '\d+ passed' | grep -oP '\d+')
if [ -n "$TEST_COUNT" ] && [ "$TEST_COUNT" -ge 54 ]; then
    pass "新增测试通过（$TEST_COUNT 个）"
else
    fail "新增测试失败"
fi
echo ""

# 6. 检查前端构建
echo "━━━ 6. 检查前端构建 ━━━"
if [ -d web/frontend/dist ]; then
    pass "前端已构建（dist/ 存在）"
    if [ -f web/frontend/dist/assets/LoginPage-*.js ]; then
        pass "LoginPage 已编译"
    else
        warn "LoginPage 未找到（可能需要重新构建）"
    fi
    if [ -f web/frontend/dist/assets/AdminPage-*.js ]; then
        pass "AdminPage 已编译"
    else
        warn "AdminPage 未找到（可能需要重新构建）"
    fi
else
    warn "前端未构建（运行 cd web/frontend && npm run build）"
fi
echo ""

# 7. 检查关键代码
echo "━━━ 7. 检查关键代码 ━━━"
grep -q "MAX_UPLOAD_SIZE_BYTES = 200 \* 1024 \* 1024" web/backend/veritas_web/routers/cases.py && pass "上传限制 200MB 已添加" || fail "上传限制未找到"
grep -q "VERITAS_MAX_CONCURRENT_AUDITS" web/backend/veritas_web/runner.py && pass "并发限制已添加" || fail "并发限制未找到"
grep -q "RotatingFileHandler" web/backend/veritas_web/logging_config.py && pass "日志轮转已配置" || fail "日志轮转未找到"
grep -q "/api/metrics" web/backend/veritas_web/routers/metrics.py && pass "/metrics 端点已添加" || fail "/metrics 端点未找到"
grep -q "require_admin" web/backend/veritas_web/permissions.py && pass "权限检查函数已添加" || fail "权限检查函数未找到"
echo ""

# 8. 总结
echo "╔══════════════════════════════════════════════════════╗"
echo "║  验证完成                                            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "下一步："
echo "1. 启动服务：docker compose up -d"
echo "2. 初始化管理员：./scripts/init_admin.sh admin your_password"
echo "3. 访问 Web 界面：http://localhost"
echo "4. 查看详细文档：cat DEPLOYMENT.md"
echo ""
echo "常见问题："
echo "- 端口冲突：lsof -i :80 查看占用进程"
echo "- 认证失败：检查 VERITAS_AUTH_MODE 设置"
echo "- GPU 不可用：docker exec veritas nvidia-smi 检查"
