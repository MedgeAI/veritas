# Veritas 服务器部署 SOP

本文说明如何把 Veritas Web 工作台部署到内网服务器，并通过 Cloudflare Tunnel 暴露 HTTPS 入口给团队使用。

部署结构：

- `deploy/Dockerfile`：多阶段构建，前端 + Python 运行时合一
- `deploy/docker-compose.yml`：PostgreSQL + pgvector + Veritas Web
- `deploy/docker-compose.cloudflare.yml`：Cloudflare Tunnel overlay
- `Makefile`：运维命令封装

## 1. 部署目标

部署完成后应满足：

- `https://<your-domain>/api/health` 公网可达
- PostgreSQL 健康，Veritas Web 容器 healthy
- `cloudflared` 容器 running，公网域名可正常访问

访问路径：

```text
团队浏览器 -> Cloudflare HTTPS 域名 -> cloudflared 容器 -> veritas:8765 -> postgres:5432
```

## 2. 服务器前置条件

- Ubuntu 22.04/24.04 或同类 Linux
- 4 核 8 GB 内存以上（静态审查 + 图像处理吃内存）
- 50 GB 以上磁盘（论文产物、图像取证数据较大）
- Docker Engine + Docker Compose v2
- Git 拉取权限

检查：

```bash
docker --version
docker compose version
git --version
```

## 3. Cloudflare Tunnel 准备

在 Cloudflare Zero Trust 控制台创建 named tunnel：

1. 创建 Tunnel，选 Cloudflared
2. 添加 Public Hostname，例如 `veritas.internal.example.com`
3. Service 类型 HTTP，服务地址填：
   ```text
   http://veritas:8765
   ```
4. 复制 tunnel token，写入服务器 `.env`

注意：

- Cloudflare Tunnel public hostname 的 service 必须是 `http://veritas:8765`，不是 `localhost:8765`
- 不要提交 tunnel token 到 Git
- 建议用 Cloudflare Access 做团队邮箱白名单，限制访问范围

## 4. 拉取代码

```bash
sudo mkdir -p /opt/veritas
sudo chown "$USER":"$USER" /opt/veritas
cd /opt/veritas

git clone <your-repo-url> .
git checkout master
```

## 5. 配置 `.env`

```bash
cp .env.example .env
chmod 600 .env
```

至少填写：

```bash
# MinerU PDF 解析 API token
MINERU_API_TOKEN=your-mineru-token

# DashScope / 百炼 API key（Source Data 语义裁决、claim extractor 等）
DASHSCOPE_API_KEY=sk-your-dashscope-key

# Cloudflare Tunnel token
CLOUDFLARE_TUNNEL_TOKEN=your-cloudflare-tunnel-token
```

可选：

```bash
# 认证模式（basic = 内置 users.db 用户名密码；none = 无认证）
VERITAS_AUTH_MODE=basic

# 日志级别
VERITAS_LOG_LEVEL=INFO
```

## 6. 首次启动

```bash
make rebuild
```

等待服务启动：

```bash
make ps
make logs
```

或直接 compose：

```bash
docker compose --env-file .env \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.cloudflare.yml \
  up --build -d
```

首次启动时 Veritas 会初始化数据库表结构，可能需要几十秒。

## 7. 部署验证

### 7.1 容器状态

```bash
make ps
```

期望看到：

- `veritas-postgres` 为 healthy
- `veritas-web` 为 healthy
- `veritas-cloudflared` 为 running

### 7.2 本机健康检查

```bash
make docker-health
```

或：

```bash
curl -sf http://127.0.0.1/api/health | python3 -m json.tool
```

### 7.3 公网健康检查

替换为你的 Cloudflare 域名：

```bash
curl -sf https://veritas.internal.example.com/api/health | python3 -m json.tool
```

如果本机通但公网不通，优先检查：

- `CLOUDFLARE_TUNNEL_TOKEN` 是否正确
- Cloudflare Tunnel public hostname service 是否是 `http://veritas:8765`
- cloudflared 容器日志：

```bash
docker compose --env-file .env \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.cloudflare.yml \
  logs --tail=100 cloudflared
```

## 8. 日常运维

```bash
make ps              # 服务状态
make logs            # 应用日志（follow）
make restart         # 重启 veritas 容器
make rebuild         # 重新构建并启动
make down            # 停止服务，保留数据卷
make shell           # 进入 veritas 容器 shell
make docker-health   # 健康检查（通过 port 80）
```

进入 Postgres：

```bash
docker compose exec postgres psql -U veritas
```

## 9. 更新部署

```bash
git fetch origin master
git pull --ff-only origin master
make rebuild
make docker-health
```

## 10. 回滚

```bash
git log --oneline -10
git checkout <commit-sha>
make rebuild
make docker-health
```

确认无误后再决定是否在开发机创建 revert commit push 到 master。

## 11. 数据库重置

慎用：

```bash
make db-reset
```

只有在数据结构严重不一致或需要干净演示环境时使用。

## 12. 安全检查

部署前确认：

- `.env` 没有提交到 Git（已在 `.gitignore`）
- `CLOUDFLARE_TUNNEL_TOKEN` 没有出现在日志、commit diff 中
- Cloudflare Access 已配置团队访问白名单
- 服务器防火墙不对公网开放 `5432`
- 不直接对公网开放 `8765`，所有公网流量走 Cloudflare Tunnel

## 13. 常见问题

### veritas 容器一直 unhealthy

```bash
make logs
```

检查：

- `MINERU_API_TOKEN` 是否有效
- `DASHSCOPE_API_KEY` 是否有效
- Postgres 是否 healthy
- 服务器是否能访问外部 API（MinerU、DashScope）

### Cloudflare 域名访问不到

检查 cloudflared 日志：

```bash
docker compose --env-file .env \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.cloudflare.yml \
  logs --tail=100 cloudflared
```

确认 Cloudflare public hostname service 是 `http://veritas:8765`，不是 `localhost:8765`。

### 前端页面 404

确认 `Dockerfile` 多阶段构建正常完成，`web/frontend/dist/` 已被 COPY 进镜像。

## 14. 最短路径

首次部署最短命令：

```bash
git clone <repo-url> /opt/veritas
cd /opt/veritas
cp .env.example .env
chmod 600 .env
vim .env   # 填 MINERU_API_TOKEN、DASHSCOPE_API_KEY、CLOUDFLARE_TUNNEL_TOKEN

make rebuild
make docker-health

# 确认公网
curl -sf https://veritas.internal.example.com/api/health | python3 -m json.tool
```
