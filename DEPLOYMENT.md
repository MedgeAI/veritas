# Veritas 部署指南

本文档面向实验室运维人员，覆盖 Veritas 系统的完整部署、配置、运维和故障排查。

---

## 1. 系统要求

### 1.1 硬件要求

| 资源 | 最低要求 | 说明 |
|------|---------|------|
| CPU | 4+ 核 | 审计任务 CPU 密集（MinerU PDF 解析、数值取证） |
| 内存 | 16GB+ | MinerU + YOLOv5 panel 提取 + copy-move 检测同时运行时内存占用高 |
| 磁盘 | 100GB+ | 论文产物、视觉产物、数据库、备份；建议独立数据盘 |
| GPU | 可选，强烈推荐 | TruFor 伪造检测、SSCD embedding、SILA dense copy-move 需要 CUDA |

### 1.2 软件要求

| 软件 | 版本要求 | 说明 |
|------|---------|------|
| Docker | 20.10+ | 容器运行时 |
| Docker Compose | 2.0+ | 服务编排（已内置于 Docker Desktop / docker-compose-plugin） |
| Git | 2.20+ | 需要支持 `--recursive` 克隆子模块 |
| 网络 | 内网部署 | 无需公网访问；需要访问 MinerU API 和 DashScope API 的内网出口 |

### 1.3 端口需求

| 端口 | 用途 | 方向 |
|------|------|------|
| 80 | Web 界面 HTTP | 入站（局域网） |
| 5432 | PostgreSQL | 仅容器间通信，生产环境不建议对外暴露 |

---

## 2. 快速部署

### 2.1 克隆仓库

Veritas 使用 git submodule 跟踪第三方依赖（MinerU、ELIS 等），必须使用 `--recursive`：

```bash
git clone --recursive <repo-url> veritas
cd veritas
```

如果已经克隆但缺少子模块：

```bash
git submodule update --init --recursive
```

### 2.2 配置环境变量

```bash
cp .env.example .env
vim .env
```

`.env` 文件最小内容：

```bash
# MinerU PDF 解析 API token（必需）
MINERU_API_TOKEN=your_mineru_token_here

# 阿里云 DashScope API key，用于 LLM Agent（必需）
DASHSCOPE_API_KEY=your_dashscope_key_here
```

### 2.3 设置文件权限

`.env` 包含 API 密钥，必须限制访问权限：

```bash
./scripts/setup_env_permissions.sh
```

该脚本将 `.env` 权限设为 `600`（仅所有者可读写），如果系统存在 `veritas` 用户则同时修正所有者。

### 2.4 创建数据目录

生产环境数据存储在 `/data/veritas/`，需要预先创建并设置权限：

```bash
sudo mkdir -p /data/veritas/web_data
sudo mkdir -p /data/veritas/outputs
sudo mkdir -p /data/veritas/backups
sudo chown -R 1000:1000 /data/veritas
```

> `1000:1000` 是容器内 `veritas` 用户的默认 UID/GID。如果构建时通过 `USER_UID`/`USER_GID` 指定了其他值，请对应调整。

### 2.5 启动服务

```bash
docker compose up -d
```

首次启动会构建镜像（约 5–10 分钟），后续启动秒级完成。

服务启动后：

| 服务 | 地址 |
|------|------|
| Web 界面 | http://localhost:80 |
| 健康检查 | http://localhost/api/health |
| PostgreSQL | localhost:5432（容器间通信） |

验证服务状态：

```bash
# 检查容器状态
docker compose ps

# 检查健康端点
curl http://localhost/api/health
```

### 2.6 初始化管理员

生产环境默认使用 `basic` 认证模式，必须创建管理员账户：

```bash
./scripts/init_admin.sh admin your_password admin@lab.edu admin
```

参数说明：`<用户名> <密码> [邮箱] [角色]`

角色取值：
- `admin` — 管理员：管理用户、删除 case、查看所有 case
- `operator` — 普通用户：只能查看和操作自己的 case

### 2.7 部署验证

部署完成后，按以下步骤验证所有功能是否正常。

#### 自动化验证

运行测试套件，验证所有新增功能：

```bash
# 运行 54 个部署相关测试（上传限制、并发限制、日志、metrics、用户 API、case 删除）
uv run pytest tests/ -v -k "upload_size or concurrency or logging_config or metrics_endpoint or users_api or case_delete"
```

预期输出：`54 passed`

验证前端构建：

```bash
cd web/frontend && npm run build
```

预期输出：`LoginPage-*.js` 和 `AdminPage-*.js` 已编译。

#### 手动验证

**1. 检查文件权限**

```bash
# .env 文件权限应为 600
ls -la .env
# 预期：-rw------- 1 veritas veritas ...

# 脚本应有可执行权限
ls -la scripts/setup_env_permissions.sh scripts/init_admin.sh
# 预期：-rwxr-xr-x
```

**2. 检查 Docker 配置**

```bash
# 确认认证模式
grep VERITAS_AUTH_MODE docker-compose.yml
# 预期：VERITAS_AUTH_MODE=basic
```

**3. 验证 API 端点**

```bash
# 健康检查（无需认证）
curl -s http://localhost/api/health | python3 -m json.tool
# 预期：{"status": "ok", "runner_mode": "thread_pool", ...}

# 未认证请求应返回 401
curl -s http://localhost/api/users
# 预期：401 Unauthorized

# 管理员访问用户列表
curl -s -u admin:your_password http://localhost/api/users | python3 -m json.tool
# 预期：返回用户列表 JSON

# 查看运行指标（无需认证）
curl -s http://localhost/api/metrics | python3 -m json.tool
# 预期：{"cases_total": 0, "runs_active": 0, ...}
```

**4. 验证 Web 界面**

浏览器访问 http://localhost，验证：

| 验证项 | 预期 |
|--------|------|
| 登录页面 | 显示用户名 + 密码表单 |
| 登录 | 用 admin/your_password 登录成功 |
| Dashboard | 显示 case 列表（可能为空） |
| 侧边栏 | 底部有"用户管理"导航项 |
| 顶部栏 | 显示当前用户名 + 登出按钮 |
| 用户管理 | 可创建/编辑/删除用户 |

**5. 验证上传限制（200MB）**

```bash
# 创建 250MB 测试文件
dd if=/dev/zero of=/tmp/large_file.pdf bs=1M count=250

# 尝试上传（应返回 413）
curl -s -u admin:your_password -F "file=@/tmp/large_file.pdf" \
  http://localhost/api/cases/test-case/inputs
# 预期：HTTP 413，detail 包含 "File size exceeds 200MB limit"

# 清理
rm /tmp/large_file.pdf
```

**6. 验证权限控制**

```bash
# 创建普通用户
./scripts/init_admin.sh alice alice_password alice@lab.edu operator

# 用 alice 登录 Web 界面，验证：
# - 侧边栏没有"用户管理"导航
# - case 卡片上没有删除按钮

# 用 alice 访问管理 API（应返回 403）
curl -s -u alice:alice_password http://localhost/api/users
# 预期：403 Forbidden

# 清理
PYTHONPATH=. uv run python -m web.backend.veritas_web.cli delete-user alice
```

**7. 验证日志**

```bash
# 检查日志文件存在
docker exec veritas-web ls -lh /app/logs/veritas.log

# 查看最近日志
docker exec veritas-web tail -20 /app/logs/veritas.log
# 预期：格式为 [时间] [级别] 模块: 消息
```

#### 验证结果汇总

| 验证项 | 通过标准 |
|--------|---------|
| 自动化测试 | 54/54 passed |
| 前端构建 | LoginPage + AdminPage 已编译 |
| .env 权限 | 600 |
| Docker 配置 | VERITAS_AUTH_MODE=basic |
| /api/health | 返回 200 + JSON |
| /api/users（未认证） | 返回 401 |
| /api/users（admin） | 返回用户列表 |
| /api/metrics | 返回 JSON 指标 |
| Web 登录 | 登录成功，跳转 Dashboard |
| 用户管理 | CRUD 操作正常 |
| 上传限制 | >200MB 返回 413 |
| 权限控制 | operator 无法访问管理功能 |
| 日志 | /app/logs/veritas.log 存在 |

全部通过后，部署验证完成。如有失败项，参考第 8 章"常见问题排查"。

---

## 3. 环境变量说明

### 3.1 API 密钥（必需）

| 变量 | 必需 | 说明 |
|------|------|------|
| `MINERU_API_TOKEN` | 是 | MinerU PDF 解析服务 API token |
| `DASHSCOPE_API_KEY` | 是 | 阿里云 DashScope API key，用于 opencode Agent LLM 调用 |

### 3.2 服务配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VERITAS_HOST` | `0.0.0.0` | 监听地址（Docker 内必须为 `0.0.0.0`） |
| `VERITAS_PORT` | `8765` | 容器内监听端口 |
| `VERITAS_DATA_ROOT` | `/app/web_data` | Web 数据根目录（case 元数据、用户上传） |
| `VERITAS_OUTPUT_ROOT` | `/app/outputs` | 审计产物根目录（报告、视觉产物） |
| `VERITAS_DATABASE_URL` | `postgresql://veritas:veritas@postgres:5432/veritas` | PostgreSQL 连接 URL |

### 3.3 认证配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VERITAS_AUTH_MODE` | `basic` | 认证模式：`none` / `basic` / `bearer` |
| `VERITAS_USERS_DB` | `/app/web_data/users.db` | 用户数据库路径（`basic` 模式） |
| `VERITAS_JWT_SECRET` | — | JWT 签名密钥（`bearer` 模式必需） |
| `VERITAS_JWT_ISSUER` | `veritas` | JWT issuer 字段（`bearer` 模式） |

### 3.4 运维配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VERITAS_LOG_LEVEL` | `INFO` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `VERITAS_LOG_DIR` | `/app/logs` | 日志输出目录 |

---

## 4. 认证配置

Veritas 支持三种认证模式，通过 `VERITAS_AUTH_MODE` 环境变量切换。

### 4.1 Basic 模式（生产推荐）

用户名密码认证，用户数据存储在 SQLite（`users.db`）。

```bash
# .env 中设置
VERITAS_AUTH_MODE=basic

# 重启服务
docker compose restart
```

用户管理命令：

```bash
# 添加用户
./scripts/init_admin.sh <username> <password> [email] [role]

# 列出所有用户
PYTHONPATH=. uv run python -m web.backend.veritas_web.cli list-users

# 修改密码
PYTHONPATH=. uv run python -m web.backend.veritas_web.cli change-password <username>

# 删除用户
PYTHONPATH=. uv run python -m web.backend.veritas_web.cli delete-user <username>
```

### 4.2 None 模式（开发/测试）

无认证，所有 API 公开访问。

```bash
# .env 中设置
VERITAS_AUTH_MODE=none

docker compose restart
```

> **警告**：不要在可访问网络中使用 `none` 模式。此模式仅适用于完全隔离的开发环境。

### 4.3 Bearer 模式（系统集成）

JWT Bearer Token 认证，适用于与主产品系统集成。

```bash
# .env 中设置
VERITAS_AUTH_MODE=bearer
VERITAS_JWT_SECRET=your_shared_secret_here

docker compose restart
```

客户端请求需在 `Authorization` 头携带 JWT token：

```
Authorization: Bearer <jwt_token>
```

JWT 使用 HS256 算法签名，issuer 默认为 `veritas`（可通过 `VERITAS_JWT_ISSUER` 修改）。

---

## 5. 数据目录

| 目录 | 容器路径 | 用途 | 是否必须备份 |
|------|---------|------|------------|
| `/data/veritas/web_data/` | `/app/web_data` | Web 数据：case 元数据、用户上传文件、用户数据库 | 是 |
| `/data/veritas/outputs/` | `/app/outputs` | 审计产物：报告、视觉取证产物、日志 | 建议 |
| PostgreSQL volume `pgdata` | `/var/lib/postgresql/data` | 数据库：run 记录、工具注册 | 是 |

> 数据目录通过 Docker volume 挂载，容器重建不会丢失数据。删除 volume（`docker compose down -v`）会丢失数据库数据。

---

## 6. 备份和恢复

### 6.1 自动备份

使用内置备份脚本：

```bash
# 手动执行备份
./scripts/backup.sh
```

备份脚本行为：
- 备份 `/data/veritas/web_data` 和 `/data/veritas/outputs` 到 `/data/veritas/backups/veritas_YYYYMMDD_HHMMSS.tar.gz`
- 默认保留 7 天，通过 `BACKUP_RETENTION_DAYS` 环境变量调整
- 自动清理过期备份

配置定时任务（每天凌晨 2 点执行）：

```bash
# 编辑 crontab
crontab -e

# 添加以下行
0 2 * * * /opt/veritas/scripts/backup.sh >> /var/log/veritas-backup.log 2>&1
```

### 6.2 手动备份

```bash
# 备份 Web 数据
tar -czf web_data_$(date +%Y%m%d).tar.gz -C / data/veritas/web_data

# 备份 PostgreSQL 数据库
docker exec veritas-postgres pg_dump -U veritas veritas > db_$(date +%Y%m%d).sql
```

### 6.3 恢复

```bash
# 恢复 Web 数据
tar -xzf web_data_YYYYMMDD.tar.gz -C /

# 恢复 PostgreSQL 数据库
docker exec -i veritas-postgres psql -U veritas veritas < db_YYYYMMDD.sql

# 重启服务
docker compose restart
```

---

## 7. 日志管理

### 7.1 查看日志

```bash
# 查看 Veritas 服务实时日志
docker compose logs -f veritas

# 查看最近 100 行
docker compose logs --tail=100 veritas

# 查看 PostgreSQL 日志
docker compose logs -f postgres

# 查看所有服务日志
docker compose logs -f
```

### 7.2 日志配置

日志输出路径和轮转策略：

| 位置 | 配置 |
|------|------|
| 容器内应用日志 | `/app/logs/veritas.log`（10MB/文件，保留 5 个） |
| Docker 容器日志 | `json-file` driver（10MB/文件，保留 3 个） |

修改日志级别：

```bash
# 在 .env 中添加或修改
VERITAS_LOG_LEVEL=DEBUG

docker compose restart
```

> 生产环境建议使用 `INFO` 或 `WARNING`，避免日志量过大。排查问题时临时切换到 `DEBUG`。

---

## 8. 常见问题排查

### 8.1 服务无法启动

**症状**：`docker compose ps` 显示 veritas 容器状态为 `Restarting` 或 `Exited`。

```bash
# 1. 查看容器日志
docker compose logs veritas

# 2. 检查端口占用
sudo lsof -i :80
sudo lsof -i :5432

# 3. 检查磁盘空间
df -h /data/veritas

# 4. 检查数据目录权限
ls -la /data/veritas/

# 5. 检查 .env 文件是否存在
ls -la .env
```

常见原因：
- 端口 80 被其他服务占用（nginx、apache 等）
- `/data/veritas` 目录不存在或权限不正确
- `.env` 文件缺失

### 8.2 认证失败

**症状**：访问 Web 界面提示 401 Unauthorized。

```bash
# 1. 确认当前认证模式
docker exec veritas-web env | grep VERITAS_AUTH_MODE

# 2. basic 模式下检查用户数据库
ls -la /data/veritas/web_data/users.db

# 3. 列出已创建的用户
PYTHONPATH=. uv run python -m web.backend.veritas_web.cli list-users

# 4. 重置管理员密码
./scripts/init_admin.sh admin new_password
```

### 8.3 审计任务卡住

**症状**：case 状态持续显示 "Running"，长时间无进展。

```bash
# 1. 查看活跃任务数
curl -s http://localhost/api/metrics | python3 -m json.tool

# 2. 查看任务相关日志（替换 <case_id>）
docker exec veritas-web grep "<case_id>" /app/logs/veritas.log

# 3. 检查 MinerU API 连通性
docker exec veritas-web curl -v https://mineru-api.example.com/health

# 4. 重启服务
# 重启后会自动将遗留的 "Running" 任务标记为 "interrupted"
docker compose restart veritas
```

### 8.4 磁盘空间不足

**症状**：上传失败或审计任务中途失败，日志中出现 `No space left on device`。

```bash
# 1. 查看各目录占用
du -sh /data/veritas/web_data
du -sh /data/veritas/outputs
du -sh /data/veritas/backups

# 2. 清理旧审计产物（谨慎！确认后再执行）
find /data/veritas/outputs -maxdepth 1 -type d -mtime +90

# 3. 清理过期备份
find /data/veritas/backups -type f -mtime +30 -delete

# 4. 清理 Docker 悬空镜像和构建缓存
docker system prune -f
docker builder prune -f
```

### 8.5 GPU 不可用

**症状**：TruFor 或 SSCD 相关任务失败，日志提示 CUDA 不可用。

```bash
# 1. 检查宿主机 GPU 状态
nvidia-smi

# 2. 检查容器内 GPU 可见性
docker exec veritas-web nvidia-smi

# 3. 检查 Docker GPU 配置
docker inspect veritas-web | grep -A 10 DeviceRequests

# 4. 确认 NVIDIA Container Toolkit 已安装
dpkg -l | grep nvidia-container-toolkit
```

> 生产 Dockerfile 基于 CPU 镜像构建。如需 GPU 支持，需要使用 `Dockerfile.dev`（基于 PyTorch CUDA 镜像）或修改生产 Dockerfile 基础镜像。

### 8.6 数据库连接失败

**症状**：服务启动失败，日志中出现 `connection refused` 或 `database "veritas" does not exist`。

```bash
# 1. 检查 PostgreSQL 容器状态
docker compose ps postgres

# 2. 检查 PostgreSQL 是否就绪
docker exec veritas-postgres pg_isready -U veritas

# 3. 查看 PostgreSQL 日志
docker compose logs postgres

# 4. 如果数据库损坏，可以从备份恢复
# 警告：这会丢失所有现有数据
docker compose down
docker volume rm veritas_pgdata
docker compose up -d
```

---

## 9. 性能调优

### 9.1 并发控制

审计任务包含 CPU 密集的数值取证和图像分析步骤。并发任务数需要根据硬件能力合理配置，避免资源争抢导致任务超时。

当前并发控制通过系统资源自然限制（线程池），无需额外配置。如果服务器资源有限，建议：

- 4 核 CPU / 16GB 内存：同时运行不超过 2 个审计任务
- 8 核 CPU / 32GB 内存：同时运行不超过 4 个审计任务
- 16 核 CPU / 64GB 内存：同时运行不超过 6 个审计任务

### 9.2 日志级别

生产环境建议使用 `INFO` 或 `WARNING`：

```bash
# .env
VERITAS_LOG_LEVEL=WARNING

docker compose restart
```

`DEBUG` 级别会产生大量日志，仅在排查问题时临时启用。

### 9.3 磁盘 IO

审计任务会产生大量小文件（panel 图像、中间产物）。建议：
- 数据目录使用 SSD
- 如果数据目录在网络存储（NFS/SMB）上，确保 IO 性能满足要求
- 定期清理过期产物

---

## 10. 升级

### 10.1 升级步骤

```bash
# 1. 备份当前数据
./scripts/backup.sh

# 2. 停止服务
docker compose down

# 3. 拉取新代码
git pull origin main
git submodule update --recursive

# 4. 重建镜像
docker compose build --no-cache

# 5. 启动服务
docker compose up -d

# 6. 检查服务状态和日志
docker compose ps
docker compose logs -f veritas
```

### 10.2 回滚

```bash
# 1. 停止当前服务
docker compose down

# 2. 切换到旧版本
git checkout <old-commit>
git submodule update --recursive

# 3. 重建镜像
docker compose build

# 4. 如果数据 schema 有变更，恢复备份数据
tar -xzf web_data_YYYYMMDD.tar.gz -C /
docker exec -i veritas-postgres psql -U veritas veritas < db_YYYYMMDD.sql

# 5. 启动服务
docker compose up -d
```

---

## 11. 监控

### 11.1 健康检查

```bash
# 服务整体健康
curl -s http://localhost/api/health | python3 -m json.tool

# 预期返回：
# {"status": "ok", "runner_mode": "thread_pool", "recovered_interrupted_runs": 0}
```

Docker Compose 已配置自动健康检查（每 60 秒），不健康的容器会自动重启（`restart: unless-stopped` 策略）。

### 11.2 运行指标

```bash
# 查看运行指标
curl -s http://localhost/api/metrics | python3 -m json.tool
```

指标字段说明：

| 字段 | 说明 |
|------|------|
| `cases_total` | 总 case 数 |
| `cases_by_status` | 各状态 case 数量 |
| `runs_total` | 总 run 数 |
| `runs_active` | 当前活跃 run 数 |
| `runs_completed` | 已完成 run 数 |
| `runs_failed` | 失败 run 数 |
| `uptime_seconds` | 服务运行时长（秒） |

### 11.3 建议监控项

如果使用监控系统（Prometheus / Zabbix 等），建议采集以下指标：

| 指标 | 采集方式 | 告警阈值 |
|------|---------|---------|
| 服务健康 | `GET /api/health` | 连续 3 次失败 |
| 磁盘使用率 | 系统指标 | > 85% |
| 内存使用率 | 系统指标 | > 90% |
| 活跃 run 数 | `/api/metrics` | > 预期并发上限 |
| 失败 run 数 | `/api/metrics` | 持续增长 |
| 容器状态 | `docker compose ps` | 非 running |

---

## 12. 安全建议

1. **认证模式**：生产环境必须使用 `basic` 或 `bearer` 模式，禁止使用 `none` 模式。
2. **API 密钥管理**：定期轮换 `MINERU_API_TOKEN` 和 `DASHSCOPE_API_KEY`；`.env` 文件权限保持 `600`。
3. **网络访问控制**：使用防火墙或 iptables 限制 80 端口的访问 IP 范围。
4. **数据库安全**：PostgreSQL 密码（默认 `veritas:veritas`）应在部署时修改；5432 端口不对宿主机以外的网络开放。
5. **定期备份**：每天自动备份，保留至少 7 天；定期验证备份可恢复性。
6. **磁盘监控**：设置磁盘空间告警，避免审计任务因磁盘满而失败。
7. **HTTPS**：如需通过反向代理对外暴露，配置 TLS 证书（Let's Encrypt 或内部 CA）。
8. **日志审计**：保留操作日志，定期审查异常访问模式。

---

## 附录：常用运维命令速查

```bash
# 启动服务
docker compose up -d

# 停止服务（保留数据卷）
docker compose down

# 重启服务
docker compose restart

# 查看服务状态
docker compose ps

# 查看实时日志
docker compose logs -f veritas

# 进入容器 shell
docker exec -it veritas-web /bin/bash

# 检查健康状态
curl http://localhost/api/health

# 查看运行指标
curl http://localhost/api/metrics

# 手动备份
./scripts/backup.sh

# 添加用户
./scripts/init_admin.sh <username> <password> [email] [role]

# 列出用户
PYTHONPATH=. uv run python -m web.backend.veritas_web.cli list-users

# 重建镜像（代码更新后）
docker compose build --no-cache && docker compose up -d
```

---

**文档版本**：1.1
**最后更新**：2026-06-23
**维护者**：Veritas 开发团队
