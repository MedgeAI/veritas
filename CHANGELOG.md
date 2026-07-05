# CHANGELOG

## 2026-07-05

- **流水线 8 阶段重构**：`engine/static_audit/pipeline.py` 从单体函数重构为 8 个阶段模块（`stages/`：discovery → planning → mineru → source_data → visual → investigation → roles → report），每阶段返回 frozen dataclass（如 `DiscoveryResult`、`PlanningResult`），阶段间通过 typed 结果传递数据。
- **StageExecutor 声明式框架**：新增 `stage_executor.py`（`StepDefinition`/`StagePlan`/`StageExecutor`），source_data 阶段已迁移（8 步骤：profile → findings → pair_forensics → cross_sheet → cross_sheet_filter → paperconan → briefings → verdict）。`fail_policy` 控制失败行为（stop/skip_downstream/continue）。
- **AuditConfig 数据类**：`config.py` 封装 14 个配置参数为 frozen dataclass，替代散落的 kwargs 传递。
- **Paper PDF 显式选择**：当上传多个 PDF 时，前端通过 `AMBIGUOUS_PAPER_PDF` 错误码触发 `PaperPdfSelector` 弹窗。后端新增 `paper_pdf.py` 模块处理歧义检测和路径验证。`CaseModel` 新增 `paper_pdf` 字段。
- **Source Data 取证扩展至 20 种检测模式**：新增 binary_arithmetic_relation（A*B=C 三列关系）、copy_paste_modify（复制后修改）、shifted_paste（位移粘贴）、internal_sequence_relation（列内等差/等比数列）、decimal_tail_match_shifted（位移小数尾匹配）、strict_linear_relation（严格线性关系）。所有新检测器使用 `SheetNumericIndex` 预计算索引。
- **认证分级引擎**：`grade_engine.py` 实现 A/B/C/D 四维评分（Reproducibility/Numerical/Methodology/Interpretation），最差维度决定等级，可复现性 tier 可施加 cap（full→A, partial→B, code_only→C, static→C-）。
- **确定性三层架构**：`certainty_enrichment.py` 为每个 finding 生成 FACT（客观事实）/ INFERENCE（AI 推断，带免责声明）/ SUGGESTION（修复建议）三层信息。
- **Run Diagnostics 系统**：`run_diagnostics.py` 聚合 5 类诊断子 artifact（agent_debug、run_quality、artifact_summary、performance、model_calls），写入 `recommended_next_actions.md` 和 `run_diagnostics.json`。
- **Typed Adapters**：`typed_adapters.py` 提供 4 种 artifact typed adapter（PairForensics、SourceData、Visual、NumericForensics），消除 dict.get 链，向后兼容字段别名。
- **Finding Categories 注册表**：`finding_categories.py` 声明式注册 22 个 finding category，添加 category 只需一个 `register()` 调用。
- **Investigation Tools 注册表分发**：`investigation_tools.py` 替代 600 行 elif 链，8 个 adapter 函数按 tool_id 分发。
- **Tool Registry 重构**：26 个 ToolDefinition，引入声明式 `param_schema` + auto coercer，`execution_phase` 四层分类。
- **LLM 配置集中化**：`engine/llm/config.py` 为 `DEFAULT_LLM_MODEL`/`DEFAULT_LLM_BASE_URL` 单一事实源，消除散落硬编码。
- **Web 数据库 Schema 扩展**：新增 7 张 ORM 表（`InvestigationRecordModel`、`ReviewDecisionModel`、`ArtifactModel`、`FindingModel`、`RunDiagnosticsSummaryModel`、`ToolRegistryModel`、`CloudflareUserModel`），`RunModel` 新增 `celery_task_id`/`stages`/`current_stage`，扩展状态枚举。
- **Engine/Web 分离（P1-5）**：`engine.reporting.risk`、`engine.reporting.review_queue`、`engine.reporting.finding_details` 承载领域逻辑，Web 层 risk/review_queue 变为瘦适配层。
- **Runtime 统一（P0-1）**：所有 subprocess 调用统一到 `runtime/executors/subprocess_executor.py`，typed `ExecutionRequest`/`ExecutionResult`。
- **视觉取证服务容器化**：sila-dense（:8770）和 elis-forensic（:8771）作为长驻 HTTP 容器服务，新增 `deploy/docker-compose.forensics.yml` 独立开发 compose。
- **Client 前端完整页面体系**：新增 6 个 client 页面（SubmitPage、ProgressPage、ReportPage、IssuePage、ReverificationPage、VerifyPage），新增 PaperPdfSelector 组件、usePaperPdfSelector hook、paperPdf 工具函数。
- **Source Data 工具扩展**：新增 `image_quality.py`（像素级质量检查）、`source_data_query.py`（语义查询）、`source_data_sheet_briefing.py`（sheet 结构简报）。`source_data_pair_forensics` 重构为包（13 个文件）。
- **visual_pipeline 包重构**：从单文件拆分为 6 个源文件（`_orchestrator.py`、`finding_pipeline.py`、`panel_extraction.py`、`sila_dense.py`、`tru_for.py`、`provenance_relationships.py`）。
- **context_pack 包重构**：从单文件拆分为包（`_shared.py`、`claims.py`、`deterministic.py`、`evidence.py`、`role_outputs.py`）。
- **engine/shared/ 共享模块**：`types.py`（StepStatus/StepResult/InvestigationAction/ProgressCallback）、`constants.py`（OUTPUT_DIRS/ARTIFACT_PATH_MAP/STEP_TOOL_IDS）、`helpers.py`（finding 层级分类/event 合约/step 进度发射）。
- **engine/reporting/ 扩展**：新增 `finding_details.py`、`layers.py`、`render_json.py`、`review_queue.py`、`risk.py`。
- **engine/static_audit/adapters/ 扩展**：新增 `numeric_forensics_adapter/`（upstream 包装 + schema enrichment）、`paperfraud_knowledge/`（YAML 规则匹配）。
- **Adapters 三模块**：`paperconan_adapter/`（GRIM/GRIMMER 扫描 + Veritas-shaped findings）、`paperfraud_knowledge/`（YAML 规则 + reviewer form）、`numeric_forensics_adapter/`（upstream enrichment + limitations）。
- **HTML 报告样式增强**：`_styles.py` 大幅重构（+429 行），certainty layers 视觉样式。
- **Pipeline 步骤状态修复（P0-1）**：warning → failed 状态语义统一。
- **异常处理修复（P0-2）**：消除静默异常吞掉。
- **循环依赖修复（P1-2）**：消除 runtime→engine 循环依赖。
- **LLM 配置集中（P1-3）**：`DEFAULT_LLM_MODEL` 替代散落硬编码。
- **Engine→Runtime Facade（P1-4）**：`_call_audit_func` 桥接新旧接口。
- **参数封装（P1-6）**：`AuditConfig` 替代 14 个散落 kwargs。

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
