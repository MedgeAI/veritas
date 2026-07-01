# CodeMAP

Veritas 代码仓库结构总览。

Updated: 2026-07-01

## 整体架构

Veritas 是一个**干实验论文投稿前技术复核**原型。当前主链路仍是 `audit-paper` 静态审查闭环：论文输入 -> 材料清单 -> PDF/MinerU 解析 -> Source Data/图像/数值取证 -> Agent 受控调查与复核 -> 结构化 bundle -> Markdown/HTML 报告。`precheck/run/report` 和 subprocess runtime 已有基础能力，但 claim-to-code/runtime replay 还不是 `audit-paper` 的稳定主链路。

当前视觉取证处在 first-party beta：canonical `figure_evidence` / `panel_evidence` / `image_relationship` / `visual_finding` artifact、HTML Visual Evidence Package 和 Web Visual Forensics Gallery 已落地；底层 panel/copy-move 算法仍是 OpenCV + ORB/SIFT 过渡实现。ELIS YOLOv5、RootSIFT/MAGSAC、TruFor、CBIR/Milvus 仍是 adapter 路线，不是当前稳定主链路。

前端已演进为**三入口架构**：`client`（客户服务门户，veritas.science）、`ops`（运营后台，ops.veritas.science）、`verify`（公开验证，verify.veritas.science）。通过 `utils/entrypoint.js` 按 hostname/pathname 分流。新增 Client Report BFF 聚合接口和公开验证接口。前端实现 React 视图过渡（`viewTransitions.js`）、SSE 重连内存泄漏修复、空状态统一、内联样式提取与懒加载优化。

审计档案（Audit Profiles）机制已落地：fast/standard/full 三档控制工具执行深度。Stale run watchdog 监控长时间无心跳运行。Investigation dependency layering 从 O(R²×A) 优化至 O(R×A)。LLM 客户端新增 markdown fence 自动剥离和 async enrichment。

本地 Python 环境由 `uv` 管理，根目录 `Makefile` 是当前推荐操作入口：`make sync` 同步依赖，`make test` 跑 Python 测试，`make lint-python` 跑 ruff，`make audit PAPER_DIR=<paper_dir> CASE_ID=<case_id>` 启动论文审查。Celery broker 已迁移到 Redis。

## CLI 层 (`cli/`)

四个命令，通过 `argparse` 分发：

| 命令 | 用途 | 委托模块 |
|---|---|---|
| `precheck` | 非执行就绪检查（环境、入口、结果文件） | `engine.workflows.precheck` |
| `run` | 完整验证执行，产出报告 | `engine.workflows.execution_verify` |
| `report` | 已有 `report.json` 重渲染为 MD/HTML | `engine.reporting.renderers` |
| `audit-paper` | 论文审计（PDF 解析 + Agent 调查 + 报告） | `engine.static_audit.orchestrator` |

## 引擎层 (`engine/`)

| 模块 | 职责 |
|---|---|
| `claims/` | CSV 结果加载 + 论文 claim 与实际数据比对，生成 Finding |
| `ingest/` | JSON manifest 解析 + 路径解析 |
| `investigation/` | opencode Agent 多轮调查规划、bounded context pack、AgentStepRunner、JSON 校验、重试和错误分类。关键文件：`context_pack.py`（bounded context pack 构建，重构为可注入的 `_read` callable 提升可测试性）、`agent_step_runner.py`（AgentStepRunner，统一调用 opencode）、`agent_models.py`（`AgentContextPack` 数据模型）、`planner.py`（`AgentInvestigationPlanner`）、`role_runners.py`（角色 Agent 运行器）、`opencode_agent.py`（legacy adapter）、`validators.py`（Agent 输出校验）、`review_material.py`（审阅材料构建）、`_shared.py`（共享工具，`_run_with_context_pack`） |
| `repo_intel/` | Git repo 扫描，识别入口脚本、配置文件、结果文件 |
| `tools/registry.py` | 确定性工具注册表（30 个 ToolDefinition），按 `ExecutionPhase` 分层：`MANDATORY_BASELINE` / `CONDITIONAL_BASELINE` / `AGENT_SELECTABLE` / `REPORT_ONLY` |
| `static_audit/` | 核心审计流水线。内部结构：`pipeline.py`（pipeline 编排，`run_static_audit` 实际归属，**审计档案 fast/standard/full 控制工具执行深度**）、`orchestrator.py`（backward-compat shim，re-export from pipeline/cli_driver/_shared/report/investigation_dispatch/visual_pipeline）、`cli_driver.py`（CLI 解析、`discover_pdf`、`main()`）、`_shared.py`（共享类型 `StepResult`/`ProgressCallback`、工具函数）、`_pipeline_steps.py`（步骤实现）、`paths.py`（artifact 路径解析，从 orchestrator 提取）、`materials.py`（材料清单）、`investigation_dispatch.py`（investigation 轮次执行和 tool 选择，**依赖层叠从 O(R²×A) 优化至 O(R×A)**）、`visual_pipeline.py`（视觉取证 pipeline + `run_visual_finding_pipeline`，**已完成 figure classification 重构**）、`visual_schemas.py`/`visual_constants.py`（视觉 schema 和常量）、`report_id.py`（报告 ID 生成，格式 `VRT-YYYYMM-XXXXXX`）、`verify_store.py`（公开验证数据存储和加载，**新增 case index 支持版本化查询**）、`report/`（报告数据聚合和渲染子包：`generator.py`、`claims.py`、`evidence.py`、`findings.py`、`sections.py`）、`roles.py`（角色定义）、`models.py`/`protocol.py`（数据模型）、`tools/`（24 个静态审查工具实现文件，含 `_elis_copy_move_runner.py`、`_elis_provenance_runner.py`、`_elis_trufor_runner.py`、`_copy_move_rotation.py`、`sila_dense.py`、`source_data_sheet_briefing.py`、`visual_finding_pipeline.py` 等）、`html_report/`（HTML 报告生成，14 个子模块：`_core`、`_executive`、`_findings`、`_visual`、`_source_data`、`_clusters`、`_benign`、`_manual_tasks`、`_appendix`、`_patterns`、`_config`、`_shared`、`_styles`、`_html_utils`，**hero header + certainty layers 视觉样式增强**）、`adapters/`（paperconan/paperfraud adapter）、`upstream/research_integrity_auditor/`（只读镜像） |
| `reporting/` | 报告数据模型 + MD/HTML/JSON 渲染。关键文件：`render_html.py`（VerificationReport HTML 渲染）、`text_generator.py`（LLM 上下文构建，**重构为 dataclass 驱动的并发 LLM 调用 async enrichment**） |
| `llm/` | LLM 客户端封装：`client.py`（**新增 markdown fence 自动剥离，避免 LLM 返回 JSON 时包裹 ```json``` 导致解析失败**） |
| `workflows/` | precheck 和 execution_verify 流程编排 |
| `ground_truth/` | Ground truth 管线：`parser.py`（标注解析）、`mapper.py`（claim-to-finding 映射）、`gap_analyzer.py`（PRD gap 分析）、`design_spec.py`（规格定义）、`anti_overfit.py`（过拟合防护，**修复每行双重正则搜索性能问题**） |
| `follow_up/` | Follow-up 行动生成：`generator.py`（行动生成器）、`prompts.py`/`templates.py`（模板和提示词） |
| `tasks/` | Celery 异步任务：`audit_task.py`（审计任务，`_notify_progress` 桥接到 SSE）、`embedding_task.py`（embedding 任务）、`celery_app.py`（Celery 应用配置，**broker 已迁移到 Redis**）、`process_cleanup.py`（进程清理）、`stale_run_watchdog.py`（**stale run 监控，检查长时间无心跳运行并自动恢复或标记失败**） |
| `env.py` | 环境变量集中管理（禁止 `os.getenv()` 散落在业务代码中） |

## Web 层 (`web/`)

| 模块 | 职责 |
|---|---|
| `backend/veritas_web/app.py` | HTTP API 入口（`create_app`）、CORS、鉴权入口、路由挂载、前端 dist 托管 |
| `backend/veritas_web/database.py` | SQLAlchemy 引擎 + session factory + FastAPI 依赖注入。`VERITAS_DATABASE_URL` 必须指向 PostgreSQL + pgvector，无 SQLite fallback |
| `backend/veritas_web/auth.py` | `NoAuthProvider` / `BearerTokenProvider` / `BasicAuthProvider` / `CloudflareAccessProvider`（Cloudflare Access JWT 验证），把请求头转换为 `AuthContext` |
| `backend/veritas_web/config.py` | 从环境变量构造 Web 鉴权配置和 provider |
| `backend/veritas_web/cli.py` | Basic Auth 用户管理 CLI（SQLite + bcrypt） |
| `backend/veritas_web/case_store.py` | case/run/event 存储接口。当前支持 PostgreSQL（通过 `database.py`）和 file-based（`web_data/`）双后端 |
| `backend/veritas_web/runner.py` | `AuditRunner`：线程池调用 `run_static_audit()`，维护 `last_event_at` heartbeat 和 stale recovery |
| `backend/veritas_web/sse.py` | Server-Sent Events：`notify_progress`（sync，从 worker 写入 + `pg_notify`）、`sse_event_stream`（async generator，轮询 `run_events` 表） |
| `backend/veritas_web/sse_buffer.py` | SSE 事件缓冲区，支持重连时回放最近事件 |
| `backend/veritas_web/client_report_service.py` | Client Report BFF 服务：`build_client_report()` 聚合认证等级、风险摘要、certainty layers、复核项和验证元数据 |
| `backend/veritas_web/diagnostics.py` | 运行时就绪检查：`CheckResult`/`DiagReport`，被 `/api/diag` 和 `scripts/diag.sh` 消费 |
| `backend/veritas_web/artifacts.py` | 将 `outputs/<case_id>/research-integrity-audit/` 的关键产物映射给 Web；访问控制由 `app.py` 的 case gate 负责 |
| `backend/veritas_web/models.py` | `CaseRecord`、`AuditRunRecord`（**扩展 run status 枚举和 decision type**）、`ArtifactRef` 等数据结构 |
| `backend/veritas_web/path_mapping.py` | 路径映射：容器内绝对路径 ↔ 本地相对路径 |
| `backend/veritas_web/permissions.py` | 权限控制逻辑 |
| `backend/veritas_web/risk.py` | 风险评估：从 `static_audit_bundle` 提取 risk summary |
| `backend/veritas_web/review_queue.py` | 人工复核队列管理 |
| `backend/veritas_web/tool_catalog.py` | `seed_tool_registry()`：将 Tool Registry 数据暴露给前端 |
| `backend/veritas_web/dependencies.py` | FastAPI 依赖注入（DB session、auth context 等） |
| `backend/veritas_web/logging_config.py` | 结构化日志配置 |
| **Routers**（`backend/veritas_web/routers/`） | 模块化路由拆分：`cases.py`（case CRUD）、`artifacts.py`（artifact 读取）、`audit_jobs.py`（异步审计任务管理，Celery 路径）、`client_report.py`（Client Report BFF，聚合认证等级/风险/发现/复核）、`investigations.py`（调查数据）、`materials.py`（材料管理）、`metrics.py`（Prometheus 指标）、`review.py`（复核接口）、`tools.py`（工具目录）、`users.py`（用户管理）、`verify.py`（公开验证，无需认证，按 report_id 查询认证状态）、`visual.py`（视觉取证数据） |
| `frontend/` | Vite + React + Tailwind 内测工作台 |

### 前端架构 (`web/frontend/`)

前端已演进为**三入口架构**，通过 `utils/entrypoint.js` 按 hostname/pathname 分流：

- `client`（默认）：客户服务门户（veritas.science），`ClientApp.jsx` + `ClientLayout.jsx`
- `ops`：运营后台（ops.veritas.science 或 `/ops`），`AppLayout.jsx`
- `verify`：公开验证（verify.veritas.science 或 `/verify`），`VerifyPage.jsx`

### 前端页面 (`web/frontend/src/pages/`)

| 页面 | 职责 |
|---|---|
| `CasesPage.jsx` | Case 列表、状态概览、删除操作（ops 入口） |
| `NewAuditPage.jsx` | 创建 case、上传文件、启动审查（ops 入口） |
| `MissionControlPage.jsx` | 轮询/SSE 监听 run 状态和 progress events（ops 入口） |
| `EvidenceReviewPage.jsx` | 结构化 evidence 审阅（ops 入口） |
| `FindingsPage.jsx` | Finding 列表和详情展示（ops 入口） |
| `ActionsPage.jsx` | Follow-up 行动管理、材料审阅、风险摘要（ops 入口） |
| `AdminPage.jsx` | 用户管理（Cloudflare Access 模式下，ops 入口） |
| `LoginPage.jsx` | Basic Auth / Cloudflare 登录（ops 入口） |
| `ReportCenterPage.jsx` | iframe 预览最终 HTML 报告（ops 入口） |
| `PlaceholderPage.jsx` | 功能占位页面（ops 入口） |
| `VerifyPage.jsx` | 公开验证页面——输入 report_id 查询认证状态（verify 入口） |
| `ReverificationPage.jsx` | 重新验证页面（ops 入口） |

### 前端组件 (`web/frontend/src/components/`)

核心组件：

| 组件 | 职责 |
|---|---|
| `AuditProgressBar.jsx` | 审计进度条 |
| `AuditTaskList.jsx` | 审计任务列表 |
| `EmptyState.jsx` | 空态占位 |
| `ErrorBoundary.jsx` | 错误边界 |
| `FollowUpDisplay.jsx` | Follow-up 行动展示 |
| `GradeBadge.jsx` | 认证等级徽章 |
| `LoadingFallback.jsx` | 加载占位 |
| `MaterialChecklist.jsx` | 材料清单 |
| `MetricCard.jsx` | 指标卡片 |
| `OverlapDetailDrawer.jsx` | Overlap 复用详情抽屉 |
| `OverlapGraph.jsx` | Overlap 复用关系图 |
| `ProgressTracker.jsx` | 进度跟踪器 |
| `ProvenanceGraph.jsx` | 图片溯源图 |
| `ReproducibilityTierPicker.jsx` | 可复现性等级选择器 |
| `RiskTrafficLight.jsx` | 风险红绿灯 |
| `SecurityTierPicker.jsx` | 安全等级选择器 |
| `ServiceTierPicker.jsx` | 服务等级选择器 |
| `StatusPill.jsx` | 状态标签 |
| `Sidebar.jsx` / `Topbar.jsx` | 导航框架 |
| `LayerGroup.jsx` | 分层展示组 |

进度子组件（`progress/`）：`CollapsedPastPhases`、`CompletionSummary`、`GhostedFuturePhases`、`PhaseHeroCard`、`PhaseRail`

客户端组件（`client/`）：`CertaintyLayer`、`FindingCard`、`GradeStrip`、`LineItem`、`ResolutionChoice`、`ServiceRow`、`StepRow`、`TierRow`

客户端布局（`layouts/`）：`ClientLayout.jsx`

客户端工具（`utils/`）：`entrypoint.js`（入口分流）、`clientWorkspace.js`、`layers.js`、`piLabels.js`、`viewTransitions.js`（**React 视图过渡工具模块，使用 View Transitions API**）

客户端组件（`components/` 新增）：`ClientFooter.jsx`、`ClientHeader.jsx`（client 端布局组件）

## Runtime 层 (`runtime/`)

| 模块 | 职责 |
|---|---|
| `executors/` | `subprocess_executor.py`（本地执行）已实现，`docker_executor.py` 为 stub |
| `jobs/` | JobRecord 生命周期模型 |
| `policies/` | 占位包 |
| `artifacts/` | 占位包 |

## 配置层 (`configs/`)

- `opencode.json`：指向阿里云 DashScope 模型（当前默认 `qwen3.7-plus`）
- `configs/methodology/`：5 份领域取证方法文档（general、source-data、biomed-wetlab、bioinfo、visual-forensics）
- `configs/opencode/`：Agent 任务路由、审计方法索引、工具职责说明

`docs/` 是产品、开发和决策文档工作区；当前 `.gitignore` 默认忽略新文件，只有显式纳入版本控制的 docs 可被提交版流程依赖。重要工程边界仍应同步到根目录文档或 `configs/`。

## 本地工具链

| 文件 | 职责 |
|---|---|
| `Makefile` | 当前推荐本地操作入口：`sync`、`test`、`lint-python`、`audit`、`web-*`、`db-up`/`db-down`/`db-init`/`db-reset`、`deploy-rebuild`、`celery-worker` 等 |
| `pyproject.toml` | Python 包、runtime 依赖、dev 依赖和 ruff 配置 |
| `uv.lock` | `uv` 生成的 Python 依赖锁文件 |
| `.gitignore` | 忽略 `outputs/`、`web_data/`、`.uv-cache/`、前端构建产物和本地密钥 |

## 脚本 (`scripts/`)

| 脚本 | 职责 |
|---|---|
| `build_tool_contract.py` | 从 Tool Registry 生成 `configs/opencode/generated/tool_contract.md` |
| `lock_prompts.py` | 锁定 Agent 提示词版本 |
| `migrate_web_data_to_postgres.py` | 从 file-based `web_data/` 迁移到 PostgreSQL |

## 部署 (`deploy/`)

| 文件 | 职责 |
|---|---|
| `Dockerfile` | 生产容器构建 |
| `docker-compose.yml` | 生产编排（backend + Celery worker + PostgreSQL） |
| `docker-compose.cloudflare.yml` | Cloudflare 部署编排 |
| `docker-compose.local-db.yml` | 独立开发 DB compose（PostgreSQL + pgvector，端口 5433） |
| `cloudflare.md` | Cloudflare 部署文档 |

## 关键设计约束

- **审计档案**：`audit-paper` 支持 fast/standard/full 三档审计档案，控制工具执行深度。通过 `pipeline.py` 的 `profile` 参数或 `--profile <name>` CLI 参数指定
- **Stale Run Watchdog**：`stale_run_watchdog.py` 监控长时间无心跳的审计运行，自动恢复或标记失败
- **Investigation 性能**：`investigation_dispatch.py` 依赖层叠从 O(R²×A) 优化至 O(R×A)——预构建 artifact→producer 索引
- **LLM 客户端**：`engine/llm/client.py` 新增 markdown fence 自动剥离；`engine/reporting/text_generator.py` 重构为 dataclass 驱动的并发 LLM 调用
- **Celery Broker**：已从文件/内存迁移到 Redis（`celery_app.py` 配置）
- **Evidence First**：报告必须从结构化 evidence event 生成
- **Agent 边界**：Agent 不编辑源码、不自动提交、不绕过 Tool Registry
- **Tool Registry**：`audit-paper` 只能执行 `registry.py` 允许的 tool_id（当前 30 个 ToolDefinition，按 `ExecutionPhase` 四层分类）
- **Web 鉴权边界**：`app.py` 先认证得到 `AuthContext`，所有 case-scoped route 必须通过 owner 校验；artifact/report/run/event/input 不能绕过 owner gate。`verify` 路由是唯一例外——公开验证接口无需认证
- **三入口分流**：前端通过 hostname（`ops.`/`verify.`）或 pathname（`/ops`/`/verify`）分流到 client/ops/verify 三个入口，默认进入 client
- **数据库**：Web 存储使用 PostgreSQL + pgvector（`VERITAS_DATABASE_URL` 必须显式设置，无 SQLite fallback）。开发环境 `make db-up` 启动 Docker PostgreSQL
- **PDF 解析**：通过 MinerU，token 从环境变量读取
- **视觉取证状态**：visual v1 artifacts 已落地；TruFor（`MANDATORY_BASELINE`）需 GPU，无 GPU 时 skip-only；ELIS 重型/深度学习 adapter 未落地前只能写成计划或 limitations
- **orchestrator.py 是 backward-compat shim**：新代码应直接 import `pipeline.py`、`cli_driver.py`、`_shared.py`、`report/`（子包）、`investigation_dispatch.py`、`visual_pipeline.py`，不再从 `orchestrator.py` 导入
- **报告 ID 格式**：`VRT-YYYYMM-XXXXXX`，由 `engine/static_audit/report_id.py` 生成，`verify_store.py` 提供公开验证数据加载
