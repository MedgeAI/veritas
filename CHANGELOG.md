# CHANGELOG

## 2026-06-25

- **MinerU 早失败机制**：MinerU PDF 解析失败后立即终止审计流水线，标记所有 17 个后续步骤为 `failed`，而非跳过 dependent 步骤后继续盲跑。
- **`/api/audit/queue` 路由修复**：`/{job_id}` 参数化路由拦截了 `/queue` 静态路由，调整定义顺序后修复。
- **Font preload 404 修复**：移除 `index.html` 中硬编码的 Google Fonts 预加载 URL（版本更新后失效），CSS 已有 `font-display: swap` 处理。
- **Docker 镜像 third_party 修复**：`.dockerignore` 放行 `research-integrity-auditor/`、`elis/system_modules/`、`paperconan/`；`Dockerfile` 添加对应 COPY。之前 Docker 容器缺少 MinerU 脚本，审计流水线会崩溃。
- **深度健康检查**：新增 `/api/health/deep` 端点，验证 MinerU 脚本、opencode 二进制、Python imports、数据目录权限。
- **AGENTS.md 精简**：651→172 行，删除冗余状态更新和重复流程描述，新增本地开发与生产部署一致性章节。

## 2026-06-24

- **Web 界面 guideline 修复**：ARIA roles、focus states、typography、content handling 等全部合规。
- **遗留端点废弃**：`POST /api/cases/{case_id}/runs` 统一迁移到 `POST /api/audit`。
- **Celery 部署修复**：`pyproject.toml` 添加 `celery[sqlalchemy]` 依赖，解决 celery-worker 容器启动崩溃。
- **前端 API 迁移**：`startRun` → `submitAudit`，响应字段 `run_id` → `job_id`。

## 2026-06-15 ~ 2026-06-23

- P0 完成：`audit-paper` happy path 稳定走通，paper1 全量审计验证通过（257 figures、811 panels、493 pair forensics findings、14 分钟）
- P1 完成：God File 拆分、ELIS adapter 接入、Source Data PRD v2、异步审计任务系统、视觉 overlap/reuse detection
- 测试增长：1146 → 1216+
