# Veritas 当前端到端数据流

更新时间：2026-06-29

本文只描述当前已落地的 `audit-paper` + Web 数据流，目的是快速恢复项目掌控感。

当前核心事实：

- Web 不是一套新的审查引擎。
- Web 只是把”创建 case、上传输入、启动审查、查看进度、打开报告”包了一层浏览器界面。
- 前端已演进为**三入口架构**：`client`（客户服务门户）、`ops`（运营后台）、`verify`（公开验证）。通过 `utils/entrypoint.js` 按 hostname/pathname 分流。
- Web API 入口先把请求鉴权成 `AuthContext`（支持 4 种 provider：None / Bearer Token / Basic Auth / Cloudflare Access JWT）；所有 case-scoped route 必须通过 owner 校验。唯一例外是 `/api/verify/*` 公开验证接口，无需认证。
- 真正审查仍然调用 `engine.static_audit.pipeline.run_static_audit()`。
- Web 存储层已迁移到 PostgreSQL + pgvector（通过 `VERITAS_DATABASE_URL` 环境变量配置），开发环境 `make db-up` 启动 Docker PostgreSQL。
- 进度推送从 polling 迁移到 SSE（Server-Sent Events），通过 `pg_notify('audit_progress', ...)` + SSE 流实现实时推送。
- 新增 Client Report BFF（`/api/cases/{case_id}/client-report`）聚合认证等级、风险摘要、certainty layers、复核项等数据供客户服务门户消费。
- 输入临时落在 `web_data/`（file-based 路径）或 PostgreSQL（生产路径）。
- 审查产物仍然落在 `outputs/`。

## 1. 总览图

```text
Browser (three-entry architecture)
  |
  |  entrypoint.js: hostname/pathname -> client | ops | verify
  |
  |  Client entry (veritas.science):
  |    GET  /api/cases/{case_id}/client-report   (aggregated BFF)
  |    GET  /api/cases/{case_id}/artifacts
  |    GET  /api/cases/{case_id}/visual/*
  |
  |  Ops entry (ops.veritas.science or /ops):
  |    POST /api/cases
  |    POST /api/cases/{case_id}/inputs
  |    POST /api/cases/{case_id}/runs
  |    GET  /api/cases/{case_id}/runs/{run_id}/sse  (SSE stream)
  |    GET  /api/cases/{case_id}/artifacts
  |    GET  /api/cases/{case_id}/report/html
  |
  |  Verify entry (verify.veritas.science or /verify):
  |    GET  /api/verify/{report_id}   (public, no auth)
  v
Web Backend (FastAPI / stdlib HTTP)
  |
  |  _authenticate() -> AuthContext  (except /api/verify/*)
  |  _require_case_access(case_id)
  |
  |  web/backend/veritas_web/app.py
  |  web/backend/veritas_web/auth.py (NoAuth / BearerToken / BasicAuth / CloudflareAccess)
  |  web/backend/veritas_web/database.py (SQLAlchemy + PostgreSQL)
  |  web/backend/veritas_web/case_store.py
  |  web/backend/veritas_web/runner.py
  |  web/backend/veritas_web/sse.py + sse_buffer.py
  |  web/backend/veritas_web/client_report_service.py (BFF aggregation)
  |  web/backend/veritas_web/routers/ (cases, artifacts, audit_jobs, client_report,
  |    investigations, materials, metrics, review, tools, users, verify, visual)
  v
PostgreSQL + pgvector  /  Local Web Store (file-based fallback)
  |
  |  cases / runs / run_events / users  (PostgreSQL tables)
  |  -- 或 --
  |  web_data/cases/{case_id}/case.json
  |  web_data/cases/{case_id}/inputs/*
  |  web_data/cases/{case_id}/runs/{run_id}/run.json
  |  web_data/cases/{case_id}/runs/{run_id}/events.jsonl
  v
Static Audit Pipeline
  |
  |  engine.static_audit.pipeline.run_static_audit(
  |    paper_dir=<inputs>,
  |    case_id={case_id},
  |    output_root=outputs,
  |    agent_mode=review,
  |    fresh=true,
  |    force=true
  |  )
  v
Audit Workdir
  |
  |  outputs/{case_id}/research-integrity-audit/
  |    material_inventory.json
  |    full.md
  |    images/
  |    evidence_ledger.json
  |    numeric_forensics.json
  |    source_data_profile.json
  |    source_data_findings.json
  |    source_data_pair_forensics.json
  |    exact_image_duplicates.json
  |    visual_evidence.json
  |    panel_evidence.json
  |    image_relationships.json
  |    visual_findings.json
  |    investigation/round_XX/action_YY/<tool artifact>
  |    investigation_rounds.jsonl
  |    context_pack_*.json
  |    logs/*.log
  |    agent_review.json
  |    agent_role_*.json
  |    static_audit_bundle.json
  |    report_id.txt  (VRT-YYYYMM-XXXXXX)
  |    verification_summary.json
  |    final_audit_report.md
  |    final_audit_report.html
  |    audit_run_manifest.json
  v
Browser
  |
  |  Ops:     GET /api/cases/{case_id}/runs/{run_id}/events  (or SSE stream)
  |  Ops:     GET /api/cases/{case_id}/artifacts
  |  Ops:     GET /api/cases/{case_id}/report/html
  |  Client:  GET /api/cases/{case_id}/client-report  (aggregated BFF)
  |  Verify:  GET /api/verify/{report_id}  (public)
  v
ClientApp (client entry) / CasesPage+MissionControl+EvidenceReview+FindingsPage+ActionsPage+ReportCenter (ops entry) / VerifyPage (verify entry)
```

## 2. 目录职责

```text
web/frontend/
```

浏览器端界面。复用了 ELIS 前端的 Vite + React + Tailwind 基础设施形态，但业务页面是 Veritas first-party。

前端已演进为**三入口架构**，通过 `utils/entrypoint.js` 按 hostname/pathname 分流：

- `client`（默认）：客户服务门户（veritas.science），`ClientApp.jsx` + `ClientLayout.jsx`
- `ops`：运营后台（ops.veritas.science 或 `/ops`），`AppLayout.jsx`
- `verify`：公开验证（verify.veritas.science 或 `/verify`），`VerifyPage.jsx`

关键文件：

- `web/frontend/src/App.jsx`：入口分流，`detectEntry()` -> client | ops | verify
- `web/frontend/src/ClientApp.jsx`：客户服务端应用
- `web/frontend/src/layouts/ClientLayout.jsx`：客户服务端布局
- `web/frontend/src/pages/NewAuditPage.jsx`：创建 case、上传文件、启动审查（ops）
- `web/frontend/src/pages/CasesPage.jsx`：case 列表、状态概览、删除操作（ops）
- `web/frontend/src/pages/MissionControlPage.jsx`：轮询/SSE 监听 run 状态和 progress events（ops）
- `web/frontend/src/pages/EvidenceReviewPage.jsx`：结构化 evidence 审阅（ops）
- `web/frontend/src/pages/FindingsPage.jsx`：Finding 列表和详情展示（ops）
- `web/frontend/src/pages/ActionsPage.jsx`：Follow-up 行动管理、材料审阅、风险摘要（ops）
- `web/frontend/src/pages/AdminPage.jsx`：用户管理（Cloudflare Access 模式下，ops）
- `web/frontend/src/pages/LoginPage.jsx`：Basic Auth / Cloudflare 登录（ops）
- `web/frontend/src/pages/ReportCenterPage.jsx`：iframe 预览最终 HTML 报告（ops）
- `web/frontend/src/pages/VerifyPage.jsx`：公开验证——输入 report_id 查询认证状态（verify）
- `web/frontend/src/pages/ReverificationPage.jsx`：重新验证页面（ops）
- `web/frontend/src/pages/PlaceholderPage.jsx`：功能占位页面（ops）
- `web/frontend/src/services/api.js`：封装所有 `/api/*` 调用
- `web/frontend/src/utils/entrypoint.js`：入口分流逻辑
- `web/frontend/src/components/client/`：客户服务端专用组件（CertaintyLayer、FindingCard、GradeStrip 等）
- `web/frontend/src/components/progress/`：进度展示子组件（PhaseHeroCard、PhaseRail 等）

```text
web/backend/veritas_web/
```

Python Web backend（stdlib HTTP + FastAPI 混合），通过 `routers/` 子包组织模块化路由。

关键文件：

- `app.py`：HTTP 路由入口（`create_app`）、CORS、鉴权入口、case 子资源 owner gate、JSON 响应、artifact/report 静态返回、前端 dist 托管。
- `auth.py`：`NoAuthProvider`、`BearerTokenProvider`、`BasicAuthProvider`、`CloudflareAccessProvider`（Cloudflare Access JWT 验证）和 `AuthContext`。
- `config.py`：读取 `VERITAS_AUTH_MODE`、JWT secret/issuer、Basic Auth SQLite DB 和 Cloudflare Access 配置。
- `cli.py`：Basic Auth 用户增删改查和密码变更。
- `database.py`：SQLAlchemy 引擎 + session factory + FastAPI 依赖注入。`VERITAS_DATABASE_URL` 必须指向 PostgreSQL + pgvector，无 SQLite fallback。
- `case_store.py`：case/run/event 存储接口。支持 PostgreSQL 和 file-based 双后端；按 `owner` / `user_id` 校验访问。
- `runner.py`：后台线程调用 `run_static_audit()`。
- `sse.py`：Server-Sent Events。`notify_progress()`（sync，从 Celery worker 写入 + `pg_notify`）和 `sse_event_stream()`（async generator，轮询 `run_events` 表 yield SSE 帧）。
- `sse_buffer.py`：SSE 事件缓冲区，支持重连时回放最近事件。
- `client_report_service.py`：Client Report BFF 服务。`build_client_report()` 聚合认证等级、风险摘要、certainty layers、复核项和验证元数据，供客户服务门户消费。
- `diagnostics.py`：运行时就绪检查（`CheckResult` / `DiagReport`），被 `/api/diag` 消费。
- `artifacts.py`：把 `outputs/{case_id}/research-integrity-audit/` 中的关键文件映射成 Web artifacts；不单独承担授权，调用前必须已通过 `app.py` 的 case gate。
- `models.py`：`CaseRecord`、`AuditRunRecord`、`ArtifactRef` 数据结构。
- `risk.py`：从 `static_audit_bundle` 提取 risk summary。
- `review_queue.py`：人工复核队列管理。
- `tool_catalog.py`：`seed_tool_registry()` 将 Tool Registry 数据暴露给前端。
- `path_mapping.py`：容器内绝对路径 ↔ 本地相对路径映射。
- `permissions.py`：权限控制逻辑。
- `dependencies.py`：FastAPI 依赖注入（DB session、auth context 等）。
- `logging_config.py`：结构化日志配置。

Routers（`routers/` 子包）：

- `cases.py`：case CRUD（list / create / get / delete）。
- `artifacts.py`：artifact 读取和 visual 图片服务。
- `audit_jobs.py`：异步审计任务管理（Celery 路径：submit / status / cancel / list）。
- `client_report.py`：Client Report BFF（`GET /api/cases/{case_id}/client-report`），聚合认证等级/风险/发现/复核。
- `investigations.py`：调查数据查询。
- `materials.py`：材料管理（list / upload / delete）。
- `metrics.py`：Prometheus 指标端点。
- `review.py`：复核接口。
- `tools.py`：工具目录查询。
- `users.py`：用户管理（list / create / delete / password change）。
- `verify.py`：公开验证（`GET /api/verify/{report_id}`），**无需认证**，按 report_id 查询认证状态。
- `visual.py`：视觉取证数据（figures / panels / relationships / findings）。

```text
web_data/
```

Web 的本地状态库。这里是用户输入和 Web 任务状态，不是审查报告产物。

该目录被 `.gitignore` 忽略。

```text
outputs/
```

审查引擎的输出目录。当前 CLI 和 Web 共用这里。

该目录被 `.gitignore` 忽略。

## 3. Web 创建 Case 的流向

用户在 `New Audit` 页面填写：

- `case_id`
- `paper_title`

当前请求用户来自 Web 鉴权层的 `auth_context.user_id`。前端不能决定 owner；`POST /api/cases` 创建时由后端写入 `CaseRecord.owner`。

前端调用：

```text
POST /api/cases
```

请求由 `web/backend/veritas_web/app.py` 接收，然后调用：

```python
CaseStore.create_case(user_id=auth_context.user_id)
```

落盘结果：

```text
web_data/cases/{case_id}/case.json
web_data/cases/{case_id}/inputs/
web_data/cases/{case_id}/runs/
```

`case.json` 记录 case 元信息，例如：

```json
{
  "case_id": "paper2-web",
  "paper_title": "Unknown until parsed",
  "owner": "operator",
  "status": "Draft",
  "latest_run_id": null,
  "input_count": 0
}
```

`GET /api/cases` 调用 `CaseStore.list_cases(user_id=auth_context.user_id)`，只返回当前用户拥有的 case。`GET /api/cases/{case_id}` 和后续所有 case 子资源都先调用 `CaseStore.get_case(case_id, user_id=auth_context.user_id)`；跨用户访问返回 `403 Forbidden`。

## 4. Web 上传输入的流向

用户在浏览器选择 PDF / Source Data / 结果文件。

前端逻辑：

```text
FileReader.readAsDataURL(file)
-> 去掉 data:*;base64, 前缀
-> POST /api/cases/{case_id}/inputs
```

请求格式：

```json
{
  "filename": "paper.pdf",
  "content_base64": "..."
}
```

写入前，后端先验证当前用户拥有 `{case_id}`。非 owner 不能通过上传输入篡改别人的 case，也不会更新 `input_count`。

后端调用：

```python
CaseStore.write_input_base64()
```

落盘结果：

```text
web_data/cases/{case_id}/inputs/paper.pdf
web_data/cases/{case_id}/inputs/<other_materials>
```

同时更新：

```text
web_data/cases/{case_id}/case.json
```

状态变化：

```text
Draft -> Uploaded
```

注意：当前 Web 上传是 JSON base64，不是 multipart。后续如果文件很大，应改为 multipart 或本地路径选择。

## 5. Web 启动审查的流向

用户点击“上传并启动审查”后，前端调用：

```text
POST /api/cases/{case_id}/runs
```

默认参数：

```json
{
  "agent_mode": "review",
  "fresh": true,
  "force": true,
  "agent_timeout_seconds": 300,
  "agent_max_retries": 1
}
```

启动前，后端先验证当前用户拥有 `{case_id}`。非 owner 不能创建 run，也不能触发审查线程消耗别人的输入材料。

后端调用：

```python
AuditRunner.start()
```

它会：

1. 创建 run record。
2. 写入 `web_data/cases/{case_id}/runs/{run_id}/run.json`。
3. 启动一个后台线程。
4. 立刻把 run 信息返回给浏览器。

落盘结果：

```text
web_data/cases/{case_id}/runs/{run_id}/run.json
```

状态变化：

```text
case.latest_run_id = run_id
run.status = queued
```

## 6. 后台线程如何调用审查引擎

后台线程进入：

```python
AuditRunner.run_sync(case_id, run_id, params)
```

它会把 run 和 case 更新为 running：

```text
run.status = running
case.status = Running
```

然后调用真正的审查函数：

```python
run_static_audit(
    paper_dir=web_data/cases/{case_id}/inputs,
    case_id={case_id},
    output_root=”outputs”,
    fresh=True,
    force=True,
    no_env_file=False,
    agent_mode=”review”,
    agent_model=”dashscope/qwen3.7-plus”,
    opencode_bin=”opencode”,
    agent_timeout_seconds=300,
    agent_max_retries=1,
    progress=progress_callback,
)
```

这里和 CLI 的关系是：

```bash
make audit-fresh PAPER_DIR=web_data/cases/{case_id}/inputs CASE_ID={case_id} AGENT_TIMEOUT_SECONDS=300
```

也就是说，Web 当前启动的是”CLI 等价审查”，但不是通过 subprocess 调 CLI，而是直接 import Python function。函数实际定义在 `engine/static_audit/pipeline.py`（`orchestrator.py` 是 backward-compat shim，re-export 同一符号）。

## 7. progress events 如何回到 Web

`run_static_audit()` 内部每个关键阶段都会调用：

```python
emit_progress(progress, ...)
```

### 7.1 Thread runner 路径（本地开发）

Web backend 传进去的 `progress_callback` 是：

```python
def progress(event):
    CaseStore.append_event(case_id, run_id, event)
```

进度会持续追加到 PostgreSQL `run_events` 表（生产路径）或 `web_data/cases/{case_id}/runs/{run_id}/events.jsonl`（file-based 路径）。

### 7.2 Celery worker 路径（生产部署）

Celery worker 调用 `sse.notify_progress()`，它同时：
1. 写入 `run_events` 表。
2. 执行 `pg_notify('audit_progress', json_payload)` 通知 PostgreSQL LISTEN/NOTIFY。

### 7.3 前端消费

前端有两种消费方式：

**SSE（首选）**：`MissionControlPage.jsx` 连接 `GET /api/cases/{case_id}/runs/{run_id}/sse`，后端通过 `sse_event_stream()` async generator 推送实时事件帧。

**Polling（fallback）**：前端每隔数秒轮询：

```text
GET /api/cases/{case_id}/runs/{run_id}
GET /api/cases/{case_id}/runs/{run_id}/events
GET /api/cases/{case_id}/artifacts
```

这些读取入口都先走 `app.py` 的 case owner 校验。知道别人的 `case_id` 或 `run_id` 不足以读取 run 状态、progress event 或 artifact readiness。

然后显示：

- run status
- started_at / completed_at
- progress event list
- artifact readiness
- failure surface

前端会把最近打开的工作区写入 `localStorage`：

```text
key = veritas.workspace.v1
value = {
  version: 1,
  activePage,
  caseId,
  runId,
  updatedAt
}
```

这个 localStorage 只表示“上次打开的工作区”，不是任务状态来源。页面启动后必须通过 backend 重新读取 case/run；如果 backend 不存在对应 case/run，前端会提示工作区失效或 run 不存在。

当前前端同时会把工作区同步到 URL query：

```text
?page=mission&case={case_id}&run={run_id}
```

恢复优先级是：

```text
URL query > localStorage veritas.workspace.v1 > legacy localStorage keys > empty workspace
```

因此链接可以直接打开某个工作区；但 run 是否存在、是否仍在执行，仍以 backend 查询结果为准。

## 8. 审查引擎内部数据流

`engine/static_audit/orchestrator.py` 当前主要阶段如下：

```text
paper_dir
  |
  v
discover_pdf()
  |
  v
paper_pdf
  |
  v
build_material_inventory()
  |
  v
material_inventory.json
  |
  v
agent_material_plan
  |
  v
optional_lanes
  |
  +-------------------------------+
  |                               |
  v                               v
MinerU PDF parse                  optional Source Data lane
  |                               |
  v                               v
full.md + images/                 source_data_profile.json
  |                               source_data_findings.json
  v                               source_data_pair_forensics.json
evidence_ledger.json
numeric_forensics.json
exact_image_duplicates.json
  |
  v
visual_evidence.json
panel_evidence.json
  |
  v
AgentInvestigationPlanner
  |
  v
investigation_rounds.jsonl
workdir/investigation/*
context_pack_investigation_plan.json
logs/*.log
  |
  v
image_relationships.json
visual_findings.json
  |
  v
agent_review.json
context_pack_review.json
agent_role_claim_extractor.json
agent_role_source_data_auditor.json
agent_role_judge.json
context_pack_<role>.json
  |
  v
static_audit_bundle.json
  |
  v
final_audit_report.md
final_audit_report.html
audit_run_manifest.json
```

对应落盘目录：

```text
outputs/{case_id}/research-integrity-audit/
```

## 9. 当前固定链路和可选链路

只要输入里有 PDF，理论上固定跑：

- `discover_pdf`
- `material_inventory`
- `agent_material_plan`
- `mineru`
- `evidence_ledger`
- `numeric_forensics`
- `paperfraud_rule_match`（如果 `full.md` 存在）
- `exact_image_duplicates`
- `visual_panel_extraction`（如果 `images/` 存在；当前是 OpenCV 启发式实现，可能退化为 whole-figure fallback panel）
- `visual_finding_pipeline`
- `agent_review`
- `ClaimExtractor`
- `SourceDataAuditor`
- `JudgeAgent`
- `context_pack_*.json`
- `logs/*.log`
- `static_audit_bundle`
- `final_audit_report.md`
- `final_audit_report.html`

不一定跑或可能 skipped：

- `source_data_profile`
- `source_data_findings`
- `source_data_pair_forensics`
- `source_data_cross_sheet`
- `image_similarity_candidates`
- `visual_copy_move`
- future ELIS-style tools（YOLOv5 panel-extractor、RootSIFT/MAGSAC、TruFor、CBIR/Milvus）

原因：

- Source Data 不一定存在。
- Source Data 不一定是当前工具支持的 XLSX/XLSM。
- `image_similarity_candidates` 当前是 Agent-selectable optional investigation tool。
- `visual.copy_move` 当前是 Agent-selectable optional investigation tool；只有被 AgentInvestigationPlanner 选择后才会在 `workdir/investigation/` 下生成 `visual_copy_move.json`。
- ELIS YOLOv5/RootSIFT/TruFor/CBIR adapter 尚未进入稳定主链路。

## 9.1 Agent 调用层

当前 Agent 入口不再直接把整个 workdir 喂给 opencode。`engine/investigation/context_pack.py` 会为 material plan、review 和 role layer 构建 bounded `AgentContextPack`，排除原始 PDF、图片、二进制和过大的 artifact，只保留当前步骤需要的结构化上下文。

`engine/investigation/agent_step_runner.py` 负责统一调用 opencode：

- 写入 `context_pack_*.json`。
- 通过 `--file <context_pack>` 传入 bounded context。
- 抽取 JSON 并执行 schema validation。
- 根据错误类别重试。
- 写入 `logs/*.log`，记录 validation、retry、error_category 和 log reference。

`opencode_agent.py` 暂时把新的 runner result 转回 legacy `AgentRunResult`，以保持 orchestrator、manifest 和报告渲染侧兼容。后续需要把 `error_category`、`log_ref` 和 context pack provenance 提升到报告与 manifest 的一等字段。

## 10. Artifact 如何被 Web 读取

Web backend 不扫描所有输出文件，目前只把少数关键文件暴露成 artifacts。

定义位置：

```text
web/backend/veritas_web/artifacts.py
```

当前 artifact 列表：

```text
run_manifest              -> audit_run_manifest.json
static_audit_bundle       -> static_audit_bundle.json
investigation_rounds      -> investigation_rounds.jsonl
final_markdown_report     -> final_audit_report.md
final_html_report         -> final_audit_report.html
visual_evidence           -> visual_evidence.json
panel_evidence            -> panel_evidence.json
image_relationships       -> image_relationships.json
visual_findings           -> visual_findings.json
```

前端调用：

```text
GET /api/cases/{case_id}/artifacts
GET /api/cases/{case_id}/artifacts/{artifact_id}
GET /api/cases/{case_id}/report/html
GET /api/cases/{case_id}/visual/figures
GET /api/cases/{case_id}/visual/panels
GET /api/cases/{case_id}/visual/relationships
GET /api/cases/{case_id}/visual/findings
GET /api/cases/{case_id}/visual/images/{relative_path}
```

这些 endpoint 读取的是 `outputs/` 中的审查产物，可能包含论文、source data 和审查结论摘要。因此访问控制不依赖 artifact 文件路径本身，而是在路由层先校验 `{case_id}` owner。未通过 owner gate 时返回 `403 Forbidden`，不会暴露 artifact 是否存在、大小或 HTML 内容。

其中：

- `EvidenceWorkspacePage.jsx` 读 JSON / JSONL / Markdown。
- `ReportCenterPage.jsx` 用 iframe 打开 HTML 报告。
- `VisualForensicsPage.jsx` 读取 visual JSON 和 panel/overlay 图片；图片路径由 backend 在 case workdir 内解析，不能越权到其他 case 或工作目录外。

## 11. 状态机

### Case 状态

```text
Draft
  |
  | upload input
  v
Uploaded
  |
  | start run
  v
Running
  |
  | run completed without failed_steps
  v
Report Ready

Running
  |
  | run failed or completed with failed_steps
  v
Review Needed
```

当前 `Planning`、`Archived` 是预留状态。

### Run 状态

```text
queued
  |
  | background thread starts
  v
running
  |
  | summary.exit_code == 0
  v
completed

running
  |
  | exception or summary.exit_code != 0
  v
failed

running / queued
  |
  | no heartbeat for >= 300s
  v
interrupted
  |
  +-- error = no_heartbeat_for_<seconds>_seconds
  +-- event = runner_interrupted

queued / running
  |
  | legacy run has no last_event_at
  v
failed
  |
  +-- error = interrupted_by_backend_restart
  +-- event = runner_interrupted
```

当前 Web P1 使用 thread runner。浏览器关闭不会影响 backend 线程继续跑；backend 进程退出会中断线程。`runner.py` 在 run 启动和每次 progress callback 时更新 `AuditRunRecord.last_event_at`。backend 下次启动时会扫描 `web_data/cases/*/runs/*/run.json`：若 `queued/running` run 超过 300 秒没有 heartbeat，则标记为 `interrupted` 并写入 `runner_interrupted` event；若是旧版本遗留 run 没有 `last_event_at`，则按兼容逻辑标记为 `failed/interrupted_by_backend_restart`。

## 12. 当前 Web 页面和数据的对应关系

```text
[Ops entry — ops.veritas.science / /ops]

CasesPage
  -> GET /api/cases
  -> PostgreSQL cases 表 / web_data/cases/*/case.json

NewAuditPage
  -> POST /api/cases
  -> POST /api/cases/{case_id}/inputs
  -> POST /api/cases/{case_id}/runs

MissionControlPage
  -> GET /api/cases/{case_id}/runs/{run_id}
  -> GET /api/cases/{case_id}/runs/{run_id}/events  (或 SSE stream)
  -> GET /api/cases/{case_id}/artifacts

EvidenceReviewPage
  -> GET /api/cases/{case_id}/artifacts
  -> GET /api/cases/{case_id}/artifacts/{artifact_id}

FindingsPage
  -> GET /api/cases/{case_id}/artifacts/static_audit_bundle
  -> visual findings data from bundle

ActionsPage
  -> GET /api/cases/{case_id}/artifacts (materials)
  -> GET /api/cases/{case_id}/review (review items)
  -> risk summary from bundle

ReverificationPage
  -> re-verification API

AdminPage
  -> GET /api/users
  -> POST /api/users
  -> DELETE /api/users/{user_id}

LoginPage
  -> POST /api/auth/login (Basic Auth)
  -> Cloudflare Access redirect

ReportCenterPage
  -> GET /api/cases/{case_id}/report/html

[Client entry — veritas.science]

ClientApp (ClientLayout)
  -> GET /api/cases/{case_id}/client-report  (aggregated BFF)
  -> GET /api/cases/{case_id}/artifacts
  -> GET /api/cases/{case_id}/visual/*
  -> client/ components: CertaintyLayer, FindingCard, GradeStrip, etc.

[Verify entry — verify.veritas.science / /verify]

VerifyPage
  -> GET /api/verify/{report_id}  (public, no auth)
  -> displays certification grade, dimensions, summary
```

## 13. 当前和 CLI 的差异

CLI 输入：

```text
input/paper1/
```

Web 输入：

```text
web_data/cases/{case_id}/inputs/
```

CLI 进度：

```text
stderr plain/jsonl
```

Web 进度：

```text
web_data/cases/{case_id}/runs/{run_id}/events.jsonl
```

Web 最近工作区：

```text
browser localStorage: veritas.workspace.v1
```

它只记录 UI 选择，不参与审查引擎状态判断。

CLI 输出：

```text
outputs/{case_id}/research-integrity-audit/
```

Web 输出：

```text
outputs/{case_id}/research-integrity-audit/
```

结论：

```text
Web 改变的是输入和进度展示方式，不改变核心审查输出目录。
```

## 14. 启动方式

### 本地开发模式（推荐）

```bash
# 终端 0: 启动 PostgreSQL + pgvector（首次或重启后）
make db-up

# 终端 1: 后端（auto-reload on code change）
make web-backend-reload
# 或
make dev   # 同时启动后端 + 前端

# 终端 2: 前端 Vite HMR（端口 5173, API proxy → :8765）
cd web/frontend && npm run dev

# 终端 3 (可选): Celery worker（测异步任务路径时开启）
make celery-worker
```

浏览器打开：

```text
http://127.0.0.1:5173
```

### 单进程演示模式

```bash
make web-build
make web-backend
```

浏览器打开：

```text
http://127.0.0.1:8765
```

### 生产部署

```bash
make deploy-rebuild    # Docker 构建 + 启动 + 自动冒烟测试
```

## 15. 当前容易混淆的点

### 15.1 `web_data/` 和 `outputs/` 不是一回事

`web_data/` 是 Web 任务状态和上传输入。

`outputs/` 是审查引擎生成的证据、报告和 manifest。

### 15.2 Web 当前不会直接读取 `input/paper1`

浏览器上传会把文件复制到：

```text
web_data/cases/{case_id}/inputs/
```

如果想直接复用本地目录而不是浏览器上传，需要新增“选择本地路径/导入目录”的 Web API。当前还没做。

### 15.3 Web backend 不是 subprocess CLI

当前 backend 直接 import：

```python
from engine.static_audit.pipeline import run_static_audit
```

好处是测试简单、状态可控。

代价是隔离性弱于 subprocess/job runner。生产部署通过 Celery worker 异步执行（`engine/tasks/audit_task.py`），backend 通过 `routers/audit_jobs.py` 提交任务，实现进程级隔离。

### 15.4 `web_data/` 和 PostgreSQL 存储的关系

当前 Web 存储处于迁移过渡期：

- **生产路径**：PostgreSQL + pgvector，通过 `VERITAS_DATABASE_URL` 配置。`case_store.py` 通过 `database.py` 的 SQLAlchemy session 读写 `cases`、`runs`、`run_events` 表。
- **开发 fallback**：`web_data/` file-based 存储仍存在，用于无 PostgreSQL 环境的快速启动。
- **迁移工具**：`scripts/migrate_web_data_to_postgres.py` 可将 file-based 数据迁移到 PostgreSQL。

### 15.5 前台关闭、后端关闭和任务生命周期

前台关闭：

```text
浏览器 tab 关闭 -> backend 仍在 -> thread runner / Celery worker 继续执行 -> 重新打开前端后通过 SSE 或 polling 继续读取进度
```

后端关闭：

```text
backend 进程退出 -> thread runner 被杀 -> run.json 可能停留在 running
Celery worker 退出 -> 任务状态在 PostgreSQL 中标记 -> 可重新调度
```

当前修复策略（thread runner 路径）：

```text
backend 启动
  -> 扫描 queued/running run
  -> last_event_at 距今 >= 300s: 标记 interrupted/no_heartbeat_for_<seconds>_seconds
  -> last_event_at 缺失: 标记 failed/interrupted_by_backend_restart
  -> 追加 runner_interrupted event
  -> 前端显示需要重新运行
```

生产目标（Celery 路径）：

```text
HTTP backend -> Celery worker (PostgreSQL result backend)
  -> backend 重启不影响 worker 中的任务
  -> 任务状态持久化在 PostgreSQL
  -> 前端通过 SSE 实时获取进度
```

### 15.6 前端依赖复用了 ELIS 的基础设施，不复用 ELIS 产品

我们复用的是：

- Vite
- React
- Tailwind
- ESLint/Vitest 组织
- AppLayout + Sidebar + Topbar + services/api 的形态

不复用的是：

- ELIS 的全局图库信息架构
- ELIS 的 FastAPI/Celery/MongoDB/Redis 主服务
- ELIS 的图片中心产品逻辑

## 16. 下一步建议

当前已具备完整 Web happy path 能力。验收路径：

1. `make db-up` 启动 PostgreSQL。
2. `make dev` 启动 backend + frontend。
3. 在 Web 里创建一个新的 case。
4. 上传 PDF 和必要材料。
5. 启动审查。
6. 在 Mission Control 通过 SSE 观察 progress events。
7. 在 EvidenceReview / FindingsPage 查看结构化证据。
8. 在 ActionsPage 审阅 Follow-up 行动。
9. 在 Report Center 打开最终 HTML。
10. 对比 CLI 运行同一个输入时的 `outputs/{case_id}/research-integrity-audit/` 产物是否一致。

待收敛项：

- SSE 在 Celery worker 路径下的端到端验证。
- `web_data/` file-based 路径的完整废弃计划。
- AdminPage 在 Cloudflare Access 模式下的完整权限流。
- artifact 列表对新工具产物的覆盖（`source_data_verdict`、`visual_image_quality`、`visual_overlap_reuse` 等）。
