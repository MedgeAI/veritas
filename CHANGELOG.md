# CHANGELOG

## 2026-07-01

- **审计档案（Audit Profiles）**：新增 fast/standard/full 三档审计档案，控制工具执行深度和范围。通过 `pipeline.py` 的 profile 参数传递，影响 Tool Registry 中哪些工具被执行。
- **Stale Run Watchdog**：新增 `engine/tasks/stale_run_watchdog.py`，监控长时间无心跳的审计运行，自动恢复或标记失败。
- **Investigation 性能优化**：`investigation_dispatch.py` 中依赖层叠从 O(R²×A) 降至 O(R×A)——预先构建 artifact→producer 索引，避免对每个 input_artifact 扫描所有角色。
- **LLM markdown fence 剥离**：`engine/llm/client.py` 新增 markdown 代码块围栏自动剥离，避免 LLM 返回 JSON 时包裹 ```json``` 导致解析失败。
- **LLM async enrichment**：`engine/reporting/text_generator.py` 重构为 dataclass 驱动的并发 LLM 调用，提升报告生成中上下文构建的吞吐。
- **Verify Store case index**：`verify_store.py` 新增 case index 支持版本化查询，`context_pack.py` 重构以支持可注入的 `_read` callable 提升可测试性。
- **扩展运行状态与决策类型**：Web 后端新增扩展的 run status 枚举和 decision type 模型，`routers/cases.py` 增强 case 查询接口。
- **视觉取证 pipeline 重构**：`visual_pipeline.py` 和 figure classification 大规模重构，强化 copy-move 检测测试和 provenance runner 覆盖。
- **HTML 报告 hero header + certainty layers**：报告头部重设计，新增 certainty layers 视觉样式，`_styles.py` 和 `_patterns.py` 增强。
- **Client Workspace 三入口路由**：前端实现 client/ops/verify 三入口分流（`entrypoint.js`），client 端独立工作台、主题刷新、ClientFooter/ClientHeader 组件。
- **Redis broker 迁移**：Celery broker 从文件/内存迁移到 Redis，`app.py` 更新 broker URL 配置。
- **Proxy stripping**：图片处理链路中代理路径自动剥离，确保 canonical artifact 路径一致性。
- **前端 SSE 重连内存泄漏修复**：SSE 重连时旧 EventSource 未正确关闭导致内存泄漏，已修复。
- **React 视图过渡**：前端实现 `viewTransitions.js` 工具模块，页面切换使用 View Transitions API。
- **前端内联样式提取与懒加载优化**：将内联 style 对象提取到独立常量，组件 lazy import 统一优化。
- **前端空状态统一**：所有页面空态组件统一为 `EmptyState`，消除散落的状态展示逻辑。
- **anti_overfit 双正则修复**：`anti_overfit.py` 修复每行双重正则搜索的性能问题。
- **代码审查 PRD 修复（Phases 1-6）**：安全、架构、重构三方面的全量代码审查修复，涉及 93 个文件。

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
