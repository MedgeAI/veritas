# CodeMAP

Veritas 代码仓库结构总览。

Updated: 2026-07-05

## 整体架构

Veritas 是一个**干实验论文投稿前技术复核**原型。当前主链路仍是 `audit-paper` 静态审查闭环，已重构为 **8 阶段流水线**（discovery → planning → mineru → source_data → visual → investigation → roles → report），每个阶段由独立模块实现，通过 typed result dataclass 传递数据。引入 `StageExecutor` 声明式步骤执行框架（source_data 阶段已迁移），`AuditConfig` 数据类封装 14 个配置参数。新增**认证分级引擎**（A/B/C/D 四维评分）、**确定性三层架构**（FACT/INFERENCE/SUGGESTION）、**Run Diagnostics** 系统。`precheck/run/report` 和 subprocess runtime 已有基础能力，所有 subprocess 调用已统一到 `runtime/executors/subprocess_executor.py`。

当前视觉取证处在 first-party beta：canonical `figure_evidence` / `panel_evidence` / `image_relationship` / `visual_finding` artifact、HTML Visual Evidence Package 和 Web Visual Forensics Gallery 已落地；底层 panel/copy-move 算法仍是 OpenCV + ORB/SIFT 过渡实现。ELIS YOLOv5、RootSIFT/MAGSAC、TruFor、CBIR/Milvus 仍是 adapter 路线，不是当前稳定主链路。视觉取证服务已容器化为长驻 HTTP 服务（sila-dense:8770, elis-forensic:8771）。

前端已演进为**三入口架构**：`client`（客户服务门户，veritas.science）、`ops`（运营后台，ops.veritas.science）、`verify`（公开验证，verify.veritas.science）。通过 `utils/entrypoint.js` 按 hostname/pathname 分流。Client 端新增完整页面体系（SubmitPage、ProgressPage、ReportPage、IssuePage、ReverificationPage、VerifyPage）。新增 Paper PDF 显式选择与多 PDF 歧义处理机制。前端实现 React 视图过渡（`viewTransitions.js`）、SSE 重连内存泄漏修复、空状态统一、内联样式提取与懒加载优化。

审计档案（Audit Profiles）机制已落地：fast/standard/full 三档控制工具执行深度。Stale run watchdog 监控长时间无心跳运行。Investigation dependency layering 从 O(R²×A) 优化至 O(R×A)。LLM 配置已集中到 `engine/llm/config.py`（`DEFAULT_LLM_MODEL` / `DEFAULT_LLM_BASE_URL` 单一事实源）。Tool Registry 重构为 26 个 ToolDefinition，引入 `execution_phase` 四层分类和声明式参数 schema。

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
| `investigation/` | opencode Agent 多轮调查规划、bounded context pack、AgentStepRunner、JSON 校验、重试和错误分类。关键文件：`context_pack/`（**已重构为包**：`_shared.py`、`claims.py`、`deterministic.py`、`evidence.py`、`role_outputs.py`）、`agent_step_runner.py`（AgentStepRunner，统一调用 opencode）、`agent_step_components.py`（步骤组件）、`agent_models.py`（`AgentContextPack` 数据模型）、`planner.py`（`AgentInvestigationPlanner`）、`role_runners.py`（角色 Agent 运行器）、`opencode_agent.py`（legacy adapter）、`validators.py`（Agent 输出校验）、`review_material.py`（审阅材料构建）、`_shared.py`（共享工具，`_run_with_context_pack`） |
| `repo_intel/` | Git repo 扫描，识别入口脚本、配置文件、结果文件 |
| `tools/registry.py` | 确定性工具注册表（26 个 ToolDefinition），按 `ExecutionPhase` 分层：`MANDATORY_BASELINE` / `CONDITIONAL_BASELINE` / `AGENT_SELECTABLE` / `REPORT_ONLY`。引入声明式 `param_schema` + 自动 coercer |
| `static_audit/` | 核心审计流水线。**已重构为 8 阶段流水线**：`stages/` 包含 `discovery.py`（PDF 发现/材料清单）、`planning.py`（Agent 计划/可选 lane）、`mineru.py`（PDF 解析/evidence ledger/numeric forensics/PaperFraud 规则）、`source_data.py`（Source Data 取证）、`visual.py`（图像重复/figure 分类/视觉基线）、`investigation.py`（调查轮次/Agent review）、`roles.py`（角色 Agent：Claim/SourceData/Judge）、`report.py`（bundle/报告/manifest）。每个阶段返回 frozen dataclass（如 `DiscoveryResult`）。`stage_executor.py`（**声明式步骤执行框架**：`StepDefinition`/`StagePlan`/`StageExecutor`，source_data 阶段已迁移）。其他关键文件：`pipeline.py`（阶段编排，`run_static_audit` 归属，审计档案 fast/standard/full）、`config.py`（**`AuditConfig` 数据类，封装 14 个配置参数**）、`audit_config.py`（审计角色配置，加载 `configs/audit_roles.yaml`）、`orchestrator.py`（backward-compat shim）、`cli_driver.py`（CLI 解析、PDF 发现/选择、多 PDF 歧义处理）、`_shared.py`（共享类型/工具函数）、`_pipeline_steps.py`（步骤实现桥接）、`paths.py`（artifact 路径解析）、`materials.py`（材料清单）、`investigation_dispatch.py`（调查轮次执行，O(R×A) 依赖层叠）、`investigation_tools.py`（**注册表分发替代 600 行 elif 链**）、`typed_adapters.py`（**4 种 artifact typed adapter，消除 dict.get 链**）、`finding_categories.py`（**22 个声明式 finding category 注册表**）、`grade_engine.py`（**A/B/C/D 认证分级引擎，4 维度独立评分**）、`certainty_enrichment.py`（**FACT/INFERENCE/SUGGESTION 三层确定性**）、`run_diagnostics.py`（**per-run 诊断聚合**）、`run_steps.py`/`step_labels.py`（步骤状态/标签/阶段映射）、`visual_pipeline/`（**已重构为包**：`_orchestrator.py`、`finding_pipeline.py`、`panel_extraction.py`、`sila_dense.py`、`tru_for.py`、`provenance_relationships.py`）、`visual_schemas.py`/`visual_constants.py`、`report_id.py`（VRT-YYYYMM-XXXXXX）、`verify_store.py`（公开验证数据）、`report/`（报告子包：`generator.py`、`claims.py`、`evidence.py`、`findings.py`、`sections/`）、`roles.py`、`models.py`/`protocol.py`、`tools/`（20+ 工具实现，含新增 `image_quality.py`、`source_data_query.py`、`source_data_sheet_briefing.py`；`source_data_pair_forensics/` **已重构为包，20 种检测模式**）、`html_report/`（14 个子模块，hero header + certainty layers）、`adapters/`（`paperconan_adapter/`、`paperfraud_knowledge/`、`numeric_forensics_adapter/`）、`upstream/research_integrity_auditor/`（只读镜像） |
| `reporting/` | 报告数据模型 + MD/HTML/JSON 渲染。关键文件：`render_html.py`（HTML 渲染）、`render_md.py`（MD 渲染）、`render_json.py`（JSON 渲染）、`text_generator.py`（dataclass 驱动的并发 LLM async enrichment）、`finding_details.py`（**finding 详情提取**）、`layers.py`（**finding 层级分类**）、`risk.py`（**风险摘要聚合**，从 Web 迁入 engine）、`review_queue.py`（**复核项聚合**，从 Web 迁入 engine） |
| `llm/` | LLM 客户端封装：`config.py`（**LLM 配置集中管理**：`DEFAULT_LLM_MODEL`/`DEFAULT_LLM_BASE_URL` 单一事实源）、`client.py`（`VeritasLLMClient`，OpenAI SDK + litellm 成本追踪，markdown fence 自动剥离） |
| `workflows/` | precheck 和 execution_verify 流程编排 |
| `ground_truth/` | Ground truth 管线：`parser.py`（标注解析）、`mapper.py`（claim-to-finding 映射）、`gap_analyzer.py`（PRD gap 分析）、`design_spec.py`（规格定义）、`anti_overfit.py`（过拟合防护，**修复每行双重正则搜索性能问题**） |
| `follow_up/` | Follow-up 行动生成：`generator.py`（行动生成器）、`prompts.py`/`templates.py`（模板和提示词） |
| `tasks/` | Celery 异步任务：`audit_task.py`（审计任务，`_notify_progress` 桥接到 SSE）、`_task_orm.py`（任务 ORM）、`celery_app.py`（Celery 应用配置，**broker 已迁移到 Redis**）、`process_cleanup.py`（进程清理）、`stale_run_watchdog.py`（**stale run 监控**） |
| `shared/` | 共享模块：`types.py`（`StepStatus` 枚举、`StepResult`/`InvestigationAction`/`ProgressCallback`）、`constants.py`（`OUTPUT_DIRS` 8 子目录、`ARTIFACT_PATH_MAP` 60 项路径映射、`STEP_TOOL_IDS`）、`helpers.py`（finding 层级分类、event 合约强制、step 进度发射、调查工具解析） |
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
| `backend/veritas_web/runner.py` | `AuditRunner`：支持线程池和 Celery 双路径，`AuditConfig` 封装参数，heartbeat + stale recovery，paper_pdf 传递，认证分级加载 |
| `backend/veritas_web/sse.py` | Server-Sent Events：`notify_progress`（sync，从 worker 写入 + `pg_notify`）、`sse_event_stream`（async generator，轮询 `run_events` 表） |
| `backend/veritas_web/sse_buffer.py` | SSE 事件缓冲区，支持重连时回放最近事件 |
| `backend/veritas_web/client_report_service.py` | Client Report BFF 服务：`build_client_report()` 聚合认证等级、风险摘要、certainty layers、复核项和验证元数据 |
| `backend/veritas_web/diagnostics.py` | 运行时就绪检查：`CheckResult`/`DiagReport`，被 `/api/diag` 和 `scripts/diag.sh` 消费 |
| `backend/veritas_web/artifacts.py` | 将 `outputs/<case_id>/research-integrity-audit/` 的关键产物映射给 Web；访问控制由 `app.py` 的 case gate 负责 |
| `backend/veritas_web/models.py` | ORM 模型（PostgreSQL）：`CaseModel`（含 `paper_pdf` 字段）、`RunModel`（含 `celery_task_id`/`stages`/`current_stage`）、`RunEventModel`、`InvestigationRecordModel`（**新增，调查轮次持久化**）、`ReviewDecisionModel`（**新增，人工复核决策**）、`ArtifactModel`（**新增，artifact 索引**）、`FindingModel`（**新增，finding 索引查询**）、`RunDiagnosticsSummaryModel`（**新增，诊断摘要**）、`ToolRegistryModel`（**新增**）、`UserModel`/`CloudflareUserModel`。扩展状态枚举：`enhancing`/`completed_with_warnings`/`failed_timeout` 等 |
| `backend/veritas_web/paper_pdf.py` | **新增**：Paper PDF 选择与歧义处理。`pdf_candidate_payloads()`、`ambiguous_paper_pdf_error()`（HTTP 422 `AMBIGUOUS_PAPER_PDF`）、`validate_paper_pdf_relative()` |
| `backend/veritas_web/path_mapping.py` | 路径映射：容器内绝对路径 ↔ 本地相对路径 |
| `backend/veritas_web/permissions.py` | 权限控制逻辑 |
| `backend/veritas_web/risk.py` | **瘦适配层**：路径解析 + 委托到 `engine.reporting.risk`（P1-5 业务逻辑迁入 engine） |
| `backend/veritas_web/review_queue.py` | **瘦适配层**：聚合 3 个 artifact 源的 review items + DB UPSERT `ReviewDecisionModel`（P1-5 业务逻辑迁入 engine） |
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
| `NewAuditPage.jsx` | 创建 case、上传文件、启动审查（ops 入口），**集成 PaperPdfSelector** |
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

### 客户端页面 (`web/frontend/src/pages/client/`)

| 页面 | 职责 |
|---|---|
| `SubmitPage.jsx` | **新增**：客户提交页面——文件分类拖放、服务选择、Paper PDF 选择、隐藏运营参数 |
| `ProgressPage.jsx` | **新增**：客户审计进度跟踪 |
| `ReportPage.jsx` | **新增**：客户端报告查看 |
| `IssuePage.jsx` | **新增**：单个 finding/issue 详情 |
| `ReverificationPage.jsx` | **新增**：客户重新验证流程 |
| `VerifyPage.jsx` | **新增**：客户公开验证 |

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

客户端工具（`utils/`）：`entrypoint.js`（入口分流）、`clientWorkspace.js`、`layers.js`、`piLabels.js`、`viewTransitions.js`（React 视图过渡）、`paperPdf.js`（**新增**：PDF 候选提取、歧义检测）

客户端 hooks（`hooks/`）：`usePaperPdfSelector.js`（**新增**：Promise-based 模态控制器）

客户端新增组件：`PaperPdfSelector.jsx`（**多 PDF 歧义选择弹窗**）、`ClientFooter.jsx`、`ClientHeader.jsx`

## Runtime 层 (`runtime/`)

| 模块 | 职责 |
|---|---|
| `executors/` | `subprocess_executor.py`（**统一 subprocess 入口**：`execute_subprocess(ExecutionRequest)` 支持重试/流式/进度回调，`run_simple_command()` 轻量单次调用）、`base.py`（`ExecutionRequest`/`ExecutionResult` typed dataclass） |
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
| `docker-compose.yml` | 生产编排（6 服务：postgres + redis + veritas + celery-worker + sila-dense + elis-forensic） |
| `docker-compose.forensics.yml` | **新增**：独立视觉取证服务 compose（sila-dense:8770 + elis-forensic:8771，开发用） |
| `docker-compose.cloudflare.yml` | Cloudflare 部署 overlay |
| `docker-compose.local-db.yml` | 独立开发 DB compose（PostgreSQL + pgvector，端口 5433） |
| `forensics/sila-dense/` | SILA dense 视觉服务 Dockerfile + 入口 |
| `forensics/elis-forensic/` | ELIS forensic 服务 Dockerfile + 入口 |
| `cloudflare.md` | Cloudflare 部署文档 |

## 关键设计约束

- **8 阶段流水线**：`audit-paper` 已重构为 8 阶段（discovery → planning → mineru → source_data → visual → investigation → roles → report），每阶段返回 frozen dataclass，`pipeline.py` 顺序编排
- **StageExecutor 声明式框架**：`stage_executor.py` 提供 `StepDefinition`/`StagePlan`/`StageExecutor`，步骤声明为数据而非命令式代码。source_data 阶段已迁移（8 步骤），`fail_policy` 控制失败行为（stop/skip_downstream/continue）
- **AuditConfig 数据类**：`config.py` 封装 14 个配置参数为 frozen dataclass，替代散落的 kwargs
- **审计档案**：fast/standard/full 三档，通过 `--profile <name>` CLI 参数指定
- **认证分级引擎**：`grade_engine.py` 4 维度独立评分（Reproducibility/Numerical/Methodology/Interpretation），最差维度决定 A/B/C/D 等级，可复现性 tier 可施加 cap
- **确定性三层**：`certainty_enrichment.py` 为每个 finding 生成 FACT（客观事实）/ INFERENCE（AI 推断，带免责声明）/ SUGGESTION（修复建议）
- **Tool Registry**：26 个 ToolDefinition，`execution_phase` 四层分类，声明式 `param_schema` + auto coercer
- **LLM 配置集中化**：`engine/llm/config.py` 为 `DEFAULT_LLM_MODEL`/`DEFAULT_LLM_BASE_URL` 单一事实源
- **Typed Adapters**：`typed_adapters.py` 4 种 artifact typed adapter，消除 dict.get 链，向后兼容字段别名
- **Finding Categories**：22 个声明式注册表，添加 category 只需一个 `register()` 调用
- **Paper PDF 显式选择**：多 PDF 时前端必须选择，后端通过 `AMBIGUOUS_PAPER_PDF` 错误码触发选择 UI
- **Stale Run Watchdog**：heartbeat 超 300s 标记 interrupted，无 heartbeat 标记 failed
- **Investigation 性能**：依赖层叠 O(R×A)，预构建 artifact→producer 索引
- **Source Data 取证**：20 种检测模式（含新增 binary_arithmetic、copy_paste_modify、shifted_paste、internal_sequence、decimal_tail_shifted、strict_linear）
- **Celery Broker**：Redis（AOF 持久化），PostgreSQL result backend
- **Runtime 统一**：所有 subprocess 调用通过 `runtime/executors/subprocess_executor.py`，typed `ExecutionRequest`/`ExecutionResult`
- **Engine/Web 分离**（P1-5）：`engine.reporting.risk`、`engine.reporting.review_queue`、`engine.reporting.finding_details` 承载领域逻辑，Web 层为瘦适配层
- **Evidence First**：报告必须从结构化 evidence event 生成
- **Agent 边界**：Agent 不编辑源码、不自动提交、不绕过 Tool Registry
- **Web 鉴权边界**：`app.py` 先认证得到 `AuthContext`，所有 case-scoped route 必须通过 owner 校验。`verify` 路由是唯一例外
- **三入口分流**：前端通过 hostname/pathname 分流到 client/ops/verify
- **数据库**：PostgreSQL + pgvector（`VERITAS_DATABASE_URL` 必须显式设置，无 SQLite fallback）。7 张核心表 + lightweight migration
- **PDF 解析**：通过 MinerU，支持显式 paper PDF 选择
- **视觉取证服务**：sila-dense（:8770）和 elis-forensic（:8771）为长驻 HTTP 容器服务
- **orchestrator.py 是 backward-compat shim**：新代码直接 import `pipeline.py` 或 `stages/`
- **报告 ID 格式**：`VRT-YYYYMM-XXXXXX`
- **Run Diagnostics**：`run_diagnostics.py` 聚合 5 类诊断子 artifact（agent_debug、run_quality、artifact_summary、performance、model_calls）
