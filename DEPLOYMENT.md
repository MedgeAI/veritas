# Veritas 部署指南

本文档按当前仓库实现编写，面向实验室运维人员。核心部署形态是 Docker Compose：

- `deploy/docker-compose.yml`：PostgreSQL 16 + pgvector、Redis、FastAPI Web、Celery worker
- `deploy/docker-compose.cloudflare.yml`：Cloudflare Tunnel overlay
- `deploy/Dockerfile`：前端构建 + Python 运行时 + 审计核心 third_party 子目录
- `Makefile`：封装本地开发、Docker 生命周期和 Cloudflare 部署命令

当前代码是 fail-loud 设计：`VERITAS_DATABASE_URL`、Celery broker/backend、关键 API key 缺失时不会静默回退。

---

## 1. 系统要求

### 1.1 硬件

| 资源 | 建议 | 说明 |
|---|---:|---|
| CPU | 4 核以上 | MinerU PDF 解析、数值取证、图像检测会消耗 CPU |
| 内存 | 16 GB 以上 | panel 提取、copy-move、TruFor/SSCD 相关流程内存占用较高 |
| 磁盘 | 100 GB 以上 | 存放上传论文、审计产物、PostgreSQL volume、备份 |
| GPU | 可选 | TruFor、SSCD、SILA dense 等视觉能力使用 CUDA 时收益明显 |

### 1.2 软件

| 软件 | 要求 |
|---|---|
| Docker Engine | 20.10+ |
| Docker Compose | v2 |
| Git | 支持 submodule |
| Python/uv | 仅本地执行脚本、测试或用户 CLI 时需要 |

### 1.3 端口

| 端口 | 当前 compose 默认行为 |
|---|---|
| `8765` | 容器内 Web 端口。`deploy/docker-compose.yml` 默认没有发布到宿主机 |
| `5432` | PostgreSQL 容器内端口，不对外暴露 |
| `6379` | Redis 容器内端口，不对外暴露 |
| `5433` | 仅本地开发 `deploy/docker-compose.local-db.yml` 发布 |

如需本机或反向代理访问 Web，请使用 Cloudflare overlay，或添加本地 compose override 发布 `8765:8765`。不要对公网直接暴露 PostgreSQL/Redis。

---

## 2. 获取代码

Veritas 依赖 git submodule：

```bash
git clone --recursive <repo-url> veritas
cd veritas
```

如果已克隆但缺少子模块：

```bash
git submodule update --init --recursive
```

Dockerfile 当前只复制运行时必需的 third_party 子目录：

- `third_party/research-integrity-auditor/`
- `third_party/elis/system_modules/`
- `third_party/paperconan/`

新增进入主链路的 third_party 依赖时，需要同步检查 `.dockerignore` 和 `deploy/Dockerfile`。

---

## 3. 环境文件

当前部署同时使用两个 env 文件：

| 文件 | 用途 |
|---|---|
| `.env` | API key、应用开关、本地开发默认值 |
| `deploy/.env` | 生产 PostgreSQL 凭据；已 gitignore，不应提交真实值 |

### 3.1 根目录 `.env`

```bash
cp .env.example .env
chmod 600 .env
```

至少填写：

```bash
MINERU_API_TOKEN=<mineru-token>
DASHSCOPE_API_KEY=<dashscope-api-key>
```

如果使用 Cloudflare Tunnel：

```bash
CLOUDFLARE_TUNNEL_TOKEN=<cloudflare-tunnel-token>
```

### 3.2 `deploy/.env`

创建或更新：

```bash
cat > deploy/.env <<'EOF'
POSTGRES_DB=veritas_prod
POSTGRES_USER=veritas_prod
POSTGRES_PASSWORD=<strong-password>
EOF
chmod 600 deploy/.env
```

`POSTGRES_PASSWORD` 是 compose 里的必填项，未设置会直接启动失败。

### 3.3 认证模式注意

当前 `deploy/docker-compose.yml` 在 `veritas.environment` 中硬编码：

```yaml
- VERITAS_AUTH_MODE=none
```

因此，仅在 `.env` 或 `deploy/.env` 写 `VERITAS_AUTH_MODE=basic` 不会覆盖它。要启用认证，必须修改 compose 中这一行，或新增本地 overlay 并用 `docker compose config` 确认最终环境变量已覆盖。

---

## 4. 数据目录

当前 `deploy/docker-compose.yml` 默认把仓库根目录下的相对目录挂载进容器：

| 宿主机路径 | 容器路径 | 用途 |
|---|---|---|
| `./web_data` | `/app/web_data` | case 元数据、上传文件、`users.db` |
| `./outputs` | `/app/outputs` | 审计报告和中间产物 |
| Docker volume `pgdata` | `/var/lib/postgresql/data` | PostgreSQL 数据 |

创建目录：

```bash
mkdir -p web_data outputs
```

通过 Makefile 构建时，镜像用户 UID/GID 会匹配当前宿主机用户，通常不需要手动 `chown`。如果手动 compose 并使用默认 UID/GID，则确保这些目录可由 UID/GID `1000:1000` 写入。

`scripts/backup.sh` 目前假设数据根目录是 `/data/veritas`。如果生产仓库不放在 `/data/veritas`，请使用第 9 节的手动备份命令，或先调整备份脚本路径。

---

## 5. 启动部署

### 5.1 Cloudflare Tunnel 部署

`make deploy-rebuild` 使用 base compose + Cloudflare overlay：

```bash
make deploy-rebuild
```

该命令会：

1. 读取 `.env` 和 `deploy/.env`
2. 使用 compose project `vdeploy`
3. 构建并重启 `postgres`、`redis`、`veritas`、`celery-worker`、`cloudflared`
4. 等待容器健康
5. 在容器内执行 `/api/health`、`/api/health/deep`、`/api/cases` 冒烟检查

注意：如果启用了非 `none` 认证，`/api/cases` 的无认证冒烟检查会返回 401；Makefile 会打印 warning，但不会中断部署。此时以 `/api/health` 和 `/api/health/deep` 为基础健康判断。

Cloudflare public hostname 的 origin service 应配置为：

```text
http://veritas:8765
```

### 5.2 不使用 Cloudflare

启动 base compose：

```bash
make rebuild
```

当前 base compose 不发布宿主机端口。健康检查可通过容器内执行：

```bash
make docker-health
```

如需宿主机访问，添加本地 overlay，例如 `deploy/docker-compose.local-port.yml`：

```yaml
services:
  veritas:
    ports:
      - "127.0.0.1:8765:8765"
```

然后手动启动：

```bash
docker compose --env-file "$PWD/.env" --env-file "$PWD/deploy/.env" \
  -p vdeploy \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.local-port.yml \
  up --build -d
```

---

## 6. 服务架构

| 服务 | 容器名 | 职责 |
|---|---|---|
| `postgres` | `veritas-postgres` | PostgreSQL 16 + pgvector |
| `redis` | `veritas-redis` | Celery broker |
| `veritas` | `veritas-web` | FastAPI API + 前端静态资源 + 审计编排 |
| `celery-worker` | `veritas-celery-worker` | Celery 异步审计 worker |
| `cloudflared` | `veritas-cloudflared` | Cloudflare Tunnel，仅 overlay 启动 |

Web 容器是否把审计任务派发给 Celery 由 `VERITAS_USE_CELERY` 控制：

| 值 | `/api/health.runner_mode` | 行为 |
|---|---|---|
| 未设置、空、`false` | `thread_pool` | Web 进程线程池执行审计；worker 即使启动也不会接收任务 |
| `1`、`true`、`yes` | `celery` | Web 将任务发送到 Redis，Celery worker 执行 |

生产异步执行建议在 `.env` 中设置：

```bash
VERITAS_USE_CELERY=true
```

相关并发开关：

| 变量 | 默认 | 说明 |
|---|---:|---|
| `VERITAS_MAX_CONCURRENT_AUDITS` | `5` | Web/API 层同时 running 的审计上限 |
| `AUDIT_MAX_QUEUE_SIZE` | `10` | queued run 上限 |
| `AUDIT_MAX_CONCURRENT_JOBS` | `2` | Celery worker concurrency |
| `AUDIT_TASK_TIMEOUT_SECONDS` | `3600` | Celery 单任务 hard time limit |

---

## 7. 认证

代码支持 `none`、`basic`、`bearer`、`cloudflare` 四种模式。当前生产 compose 默认硬编码为 `none`。

### 7.1 `none`

无认证。后端把所有请求视为 `operator` 且带 `admin` role。只适用于可信内网或上游网关已经完成访问控制的环境。

### 7.2 `basic`

内置 HTTP Basic 认证，用户存储在 SQLite `users.db`。

启用步骤：

1. 将 `deploy/docker-compose.yml` 中 `VERITAS_AUTH_MODE=none` 改为 `VERITAS_AUTH_MODE=basic`，或用本地 overlay 覆盖。
2. 确保容器环境有 `VERITAS_USERS_DB=/app/web_data/users.db`；base compose 已设置。
3. 重启服务。
4. 在仓库根目录创建管理员：

```bash
./scripts/init_admin.sh admin '<password>' admin@lab.edu admin
```

用户管理：

```bash
PYTHONPATH=. uv run python -m web.backend.veritas_web.cli list-users
PYTHONPATH=. uv run python -m web.backend.veritas_web.cli change-password admin
PYTHONPATH=. uv run python -m web.backend.veritas_web.cli delete-user alice
```

### 7.3 `bearer`

用于上游系统集成。要求：

```bash
VERITAS_AUTH_MODE=bearer
VERITAS_JWT_SECRET=<at-least-32-chars>
VERITAS_JWT_ISSUER=veritas
```

JWT 使用 HS256，payload 需要包含 `exp`、`iss`、`userId`。

### 7.4 `cloudflare`

用于 Cloudflare Access。要求 Cloudflare Access 向 origin 注入 `cf-access-jwt-assertion` header，并设置：

```bash
VERITAS_AUTH_MODE=cloudflare
VERITAS_CF_TEAM_NAME=<team-name>
VERITAS_CF_AUDIENCE_TAG=<access-application-aud>
VERITAS_BOOTSTRAP_ADMIN_EMAILS=pi@example.edu,admin@example.edu
```

首次访问时用户会自动登记；邮箱命中 bootstrap 列表的用户会获得 `admin` role，否则为 `operator`。

---

## 8. 验证

### 8.1 容器状态

```bash
make ps
docker ps --filter "name=veritas-"
```

期望：

- `veritas-postgres` healthy
- `veritas-redis` healthy
- `veritas-web` healthy
- `veritas-celery-worker` running
- 使用 Cloudflare overlay 时，`docker ps` 能看到 `veritas-cloudflared` running

### 8.2 健康检查

容器内检查：

```bash
make docker-health
```

如果发布了宿主机端口：

```bash
curl -s http://127.0.0.1:8765/api/health | python3 -m json.tool
curl -s http://127.0.0.1:8765/api/health/deep | python3 -m json.tool
```

`/api/health` 返回：

```json
{
  "status": "ok",
  "runner_mode": "thread_pool",
  "recovered_interrupted_runs": 0
}
```

`runner_mode` 会在 `VERITAS_USE_CELERY=true` 时变为 `celery`。

`/api/health/deep` 会检查：

- MinerU 脚本目录和 `mineru_convert.py`
- `opencode` 是否在 `PATH`
- `/app/web_data` 和 `/app/outputs` 是否可写
- 审计关键 Python import 是否可用

### 8.3 API 验证

以下 `curl` 命令假设已经按第 5.2 节发布宿主机端口；如果使用 Cloudflare Tunnel，请把 base URL 替换为 Cloudflare 域名。

`none` 模式下：

```bash
curl -s http://127.0.0.1:8765/api/cases | python3 -m json.tool
curl -s http://127.0.0.1:8765/api/metrics | python3 -m json.tool
```

`basic` 模式下：

```bash
curl -s -u admin:'<password>' http://127.0.0.1:8765/api/cases | python3 -m json.tool
curl -s -u admin:'<password>' http://127.0.0.1:8765/api/metrics | python3 -m json.tool
```

`/api/metrics` 是 admin-only，返回字段包括 `cases_total`、`runs_total`、`runs_active`、`runs_failed`、`runs_interrupted`、`uptime_seconds`、`timestamp`。

### 8.4 上传限制

当前上传限制：

| 上传方式 | 限制 |
|---|---:|
| multipart/form-data | 200 MB |
| legacy JSON/base64 | 50 MB |

超过限制时返回 HTTP 413。

---

## 9. 备份和恢复

### 9.1 文件备份

如果仓库根目录就是 `/data/veritas`，可直接使用：

```bash
./scripts/backup.sh
```

否则手动备份当前 compose 默认目录：

```bash
mkdir -p backups
tar -czf "backups/veritas_files_$(date +%Y%m%d_%H%M%S).tar.gz" web_data outputs
```

### 9.2 PostgreSQL 备份

```bash
docker exec veritas-postgres sh -lc 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "backups/veritas_db_$(date +%Y%m%d_%H%M%S).sql"
```

### 9.3 恢复

文件恢复：

```bash
tar -xzf backups/veritas_files_YYYYMMDD_HHMMSS.tar.gz
```

数据库恢复：

```bash
docker exec -i veritas-postgres sh -lc 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  < backups/veritas_db_YYYYMMDD_HHMMSS.sql
```

恢复后重启：

```bash
make restart
```

---

## 10. 日志

### 10.1 Docker 日志

```bash
make logs
docker logs --tail=100 -f veritas-celery-worker
docker logs --tail=100 -f veritas-postgres
```

### 10.2 应用日志

`web/backend/veritas_web/logging_config.py` 会把日志写到 stderr，并在 `VERITAS_LOG_DIR` 非空时写入轮转文件：

| 环境 | 默认目录 | 轮转 |
|---|---|---|
| Docker | `/app/logs/veritas.log` | 10 MB，保留 5 个备份 |
| 本地 dev | `logs/veritas.log` | 10 MB，保留 1 个备份 |

Docker compose 还配置了 `json-file` 日志轮转：50 MB，保留 5 个文件。

修改日志级别：

```bash
VERITAS_LOG_LEVEL=DEBUG
```

生产建议使用 `INFO` 或 `WARNING`，排查问题时临时改为 `DEBUG`。

---

## 11. 常见问题

### 11.1 服务启动失败

```bash
make ps
make logs
docker logs --tail=100 veritas-postgres
```

优先检查：

- `deploy/.env` 是否设置了 `POSTGRES_PASSWORD`
- `.env` 是否设置了 `MINERU_API_TOKEN`、`DASHSCOPE_API_KEY`
- `web_data`、`outputs` 是否可写
- 如果使用 Cloudflare overlay，`CLOUDFLARE_TUNNEL_TOKEN` 是否有效

### 11.2 数据库连接失败

当前代码要求 PostgreSQL，不支持 SQLite 作为 Web 主库。compose 会注入：

```text
VERITAS_DATABASE_URL=postgresql://<user>:<password>@postgres:5432/<db>
```

排查：

```bash
docker exec veritas-postgres sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker logs --tail=100 veritas-postgres
```

### 11.3 `/api/health` 显示 `thread_pool`

这是默认行为。要让 Web 把审计任务派发给 Celery，在 `.env` 中设置：

```bash
VERITAS_USE_CELERY=true
```

然后重启：

```bash
make restart
```

确认：

```bash
make docker-health
docker logs --tail=100 -f veritas-celery-worker
```

### 11.4 认证没有生效

检查 compose 最终配置：

```bash
docker compose --env-file "$PWD/.env" --env-file "$PWD/deploy/.env" \
  -p vdeploy -f deploy/docker-compose.yml config | grep VERITAS_AUTH_MODE
```

如果仍是 `VERITAS_AUTH_MODE=none`，说明 base compose 的硬编码环境变量仍在生效。

### 11.5 审计任务卡住

```bash
docker exec veritas-web curl -s http://localhost:8765/api/audit/queue
docker logs --tail=200 veritas-web
docker logs --tail=200 veritas-celery-worker
```

重启 Web 时，启动恢复逻辑会把遗留的 running run 标记为 interrupted。

### 11.6 Cloudflare 域名无法访问

检查：

- Tunnel token 是否正确
- Public hostname service 是否是 `http://veritas:8765`
- Cloudflare Access 是否已放行当前用户

日志：

```bash
make deploy-logs
```

---

## 12. 升级和回滚

### 12.1 升级

```bash
./scripts/backup.sh || true
git fetch origin
git pull --ff-only origin master
git submodule update --init --recursive
make deploy-rebuild
```

如果没有使用 Cloudflare overlay，用 `make rebuild` 替代 `make deploy-rebuild`。

### 12.2 回滚

```bash
git log --oneline -10
git checkout <old-commit>
git submodule update --init --recursive
make deploy-rebuild
```

如果数据库 schema 已变更且需要数据回滚，先恢复第 9 节的数据库备份，再启动服务。

---

## 13. 安全建议

1. 不要提交 `.env`、`deploy/.env`、真实论文、审计产物或密钥。
2. `deploy/.env` 中的 `POSTGRES_PASSWORD` 必须使用强密码。
3. 当前 compose 默认 `VERITAS_AUTH_MODE=none`。如果通过 Cloudflare Tunnel 或反向代理暴露给多人使用，应启用 `basic`、`bearer` 或 `cloudflare`，或确保上游访问控制等价可靠。
4. 不要对公网开放 PostgreSQL、Redis 或未认证的 8765 端口。
5. 定期备份 `web_data`、`outputs` 和 PostgreSQL。
6. 监控磁盘使用率；审计任务会产生大量中间文件。
7. 轮换 `MINERU_API_TOKEN`、`DASHSCOPE_API_KEY`、`CLOUDFLARE_TUNNEL_TOKEN`。

---

## 14. 常用命令

```bash
# Cloudflare overlay 部署/重建
make deploy-rebuild

# Base compose 重建，不含 Cloudflare
make rebuild

# 服务状态
make ps

# Web 日志
make logs

# Cloudflare 日志
make deploy-logs

# 容器内健康检查
make docker-health

# 停止 base compose
make down

# 停止 Cloudflare overlay
make deploy-down

# 进入 Web 容器
make shell

# 本地用户管理，basic 模式
./scripts/init_admin.sh <username> <password> [email] [role]
PYTHONPATH=. uv run python -m web.backend.veritas_web.cli list-users

# 手动检查深度健康
docker exec veritas-web curl -sf http://localhost:8765/api/health/deep
```

---

**文档版本**：1.3
**最后更新**：2026-07-01
**维护者**：Veritas 开发团队
