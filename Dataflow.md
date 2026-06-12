# Veritas 当前端到端数据流

本文只描述当前已落地的 `audit-paper` + Web P1 数据流，目的是快速恢复项目掌控感。

当前核心事实：

- Web 不是一套新的审查引擎。
- Web 只是把“创建 case、上传输入、启动审查、查看进度、打开报告”包了一层浏览器界面。
- 真正审查仍然调用 `engine.static_audit.orchestrator.run_static_audit()`。
- 输入临时落在 `web_data/`。
- 审查产物仍然落在 `outputs/`。

## 1. 总览图

```text
Browser
  |
  |  Vite frontend: web/frontend
  |  POST /api/cases
  |  POST /api/cases/{case_id}/inputs
  |  POST /api/cases/{case_id}/runs
  v
Stdlib Web Backend
  |
  |  web/backend/veritas_web/app.py
  |  web/backend/veritas_web/case_store.py
  |  web/backend/veritas_web/runner.py
  v
Local Web Store
  |
  |  web_data/cases/{case_id}/case.json
  |  web_data/cases/{case_id}/inputs/*
  |  web_data/cases/{case_id}/runs/{run_id}/run.json
  |  web_data/cases/{case_id}/runs/{run_id}/events.jsonl
  v
Static Audit Orchestrator
  |
  |  engine.static_audit.orchestrator.run_static_audit(
  |    paper_dir=web_data/cases/{case_id}/inputs,
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
  |    investigation_rounds.jsonl
  |    context_pack_*.json
  |    logs/*.json
  |    agent_review.json
  |    agent_role_*.json
  |    static_audit_bundle.json
  |    final_audit_report.md
  |    final_audit_report.html
  |    audit_run_manifest.json
  v
Browser
  |
  |  GET /api/cases/{case_id}/runs/{run_id}/events
  |  GET /api/cases/{case_id}/artifacts
  |  GET /api/cases/{case_id}/report/html
  v
Mission Control / Evidence Workspace / Report Center
```

## 2. 目录职责

```text
web/frontend/
```

浏览器端界面。复用了 ELIS 前端的 Vite + React + Tailwind 基础设施形态，但业务页面是 Veritas first-party。

关键文件：

- `web/frontend/src/pages/NewAuditPage.jsx`：创建 case、上传文件、启动审查。
- `web/frontend/src/pages/MissionControlPage.jsx`：轮询 run 状态和 progress events。
- `web/frontend/src/pages/EvidenceWorkspacePage.jsx`：读取结构化 artifacts。
- `web/frontend/src/pages/ReportCenterPage.jsx`：iframe 预览最终 HTML 报告。
- `web/frontend/src/services/api.js`：封装所有 `/api/*` 调用。

```text
web/backend/veritas_web/
```

stdlib Python Web backend，不引入 FastAPI/Celery/MongoDB/Redis。当前用于内测 happy path。

关键文件：

- `app.py`：HTTP 路由、CORS、JSON 响应、artifact/report 静态返回、前端 dist 托管。
- `case_store.py`：本地 case/run/event 存储。
- `runner.py`：后台线程调用 `run_static_audit()`。
- `artifacts.py`：把 `outputs/{case_id}/research-integrity-audit/` 中的关键文件映射成 Web artifacts。
- `models.py`：`CaseRecord`、`AuditRunRecord`、`ArtifactRef` 数据结构。

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
- `owner`

前端调用：

```text
POST /api/cases
```

请求由 `web/backend/veritas_web/app.py` 接收，然后调用：

```python
CaseStore.create_case()
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
  "status": "Draft",
  "latest_run_id": null,
  "input_count": 0
}
```

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
    output_root="outputs",
    fresh=True,
    force=True,
    no_env_file=False,
    agent_mode="review",
    agent_model="dashscope/qwen3.7-max",
    opencode_bin="opencode",
    agent_timeout_seconds=300,
    agent_max_retries=1,
    progress=progress_callback,
)
```

这里和 CLI 的关系是：

```bash
make audit-fresh PAPER_DIR=web_data/cases/{case_id}/inputs CASE_ID={case_id} AGENT_TIMEOUT_SECONDS=300
```

也就是说，Web 当前启动的是“CLI 等价审查”，但不是通过 subprocess 调 CLI，而是直接 import Python function。

## 7. progress events 如何回到 Web

`run_static_audit()` 内部每个关键阶段都会调用：

```python
emit_progress(progress, ...)
```

Web backend 传进去的 `progress_callback` 是：

```python
def progress(event):
    CaseStore.append_event(case_id, run_id, event)
```

所以进度会持续追加到：

```text
web_data/cases/{case_id}/runs/{run_id}/events.jsonl
```

前端 `MissionControlPage.jsx` 每隔数秒轮询：

```text
GET /api/cases/{case_id}/runs/{run_id}
GET /api/cases/{case_id}/runs/{run_id}/events
GET /api/cases/{case_id}/artifacts
```

然后显示：

- run status
- started_at / completed_at
- progress event list
- artifact readiness
- failure surface

当前不是 WebSocket / SSE，是 polling。

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
AgentInvestigationPlanner
  |
  v
investigation_rounds.jsonl
workdir/investigation/*
context_pack_investigation_plan.json
logs/*.json
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
- `exact_image_duplicates`
- `agent_review`
- `ClaimExtractor`
- `SourceDataAuditor`
- `JudgeAgent`
- `context_pack_*.json`
- `logs/*.json`
- `static_audit_bundle`
- `final_audit_report.md`
- `final_audit_report.html`

不一定跑或可能 skipped：

- `source_data_profile`
- `source_data_findings`
- `source_data_pair_forensics`
- `image_similarity_candidates`
- `vlm_triage`
- future ELIS-style tools

原因：

- Source Data 不一定存在。
- Source Data 不一定是当前工具支持的 XLSX/XLSM。
- `image_similarity_candidates` 当前是 Agent-selectable optional investigation tool。
- `vlm_triage` 目前 orchestrator 中还是占位。

## 9.1 Agent 调用层

当前 Agent 入口不再直接把整个 workdir 喂给 opencode。`engine/investigation/context_pack.py` 会为 material plan、review 和 role layer 构建 bounded `AgentContextPack`，排除原始 PDF、图片、二进制和过大的 artifact，只保留当前步骤需要的结构化上下文。

`engine/investigation/agent_step_runner.py` 负责统一调用 opencode：

- 写入 `context_pack_*.json`。
- 通过 `--file <context_pack>` 传入 bounded context。
- 抽取 JSON 并执行 schema validation。
- 根据错误类别重试。
- 写入 `logs/*.json`，记录 validation、retry、error_category 和 log reference。

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
```

前端调用：

```text
GET /api/cases/{case_id}/artifacts
GET /api/cases/{case_id}/artifacts/{artifact_id}
GET /api/cases/{case_id}/report/html
```

其中：

- `EvidenceWorkspacePage.jsx` 读 JSON / JSONL / Markdown。
- `ReportCenterPage.jsx` 用 iframe 打开 HTML 报告。

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
CasesPage
  -> GET /api/cases
  -> web_data/cases/*/case.json

NewAuditPage
  -> POST /api/cases
  -> POST /api/cases/{case_id}/inputs
  -> POST /api/cases/{case_id}/runs

MissionControlPage
  -> GET /api/cases/{case_id}/runs/{run_id}
  -> GET /api/cases/{case_id}/runs/{run_id}/events
  -> GET /api/cases/{case_id}/artifacts

EvidenceWorkspacePage
  -> GET /api/cases/{case_id}/artifacts
  -> GET /api/cases/{case_id}/artifacts/{artifact_id}

ReportCenterPage
  -> GET /api/cases/{case_id}/report/html
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

开发模式：

```bash
make sync
make web-backend
make web-install
make web-frontend
```

浏览器打开：

```text
http://127.0.0.1:5173
```

单进程演示模式：

```bash
make web-build
make web-backend
```

浏览器打开：

```text
http://127.0.0.1:8765
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
from engine.static_audit.orchestrator import run_static_audit
```

好处是测试简单、状态可控。

代价是隔离性弱于 subprocess/job runner。后续如果进入多用户或长任务，应改成 job runner。

### 15.4 前台关闭、后端关闭和任务生命周期

前台关闭：

```text
浏览器 tab 关闭 -> backend 仍在 -> thread runner 继续执行 -> 重新打开前端后继续从 web_data/events.jsonl 读取进度
```

后端关闭：

```text
backend 进程退出 -> thread runner 被杀 -> run.json 可能停留在 running
```

当前修复策略：

```text
backend 启动
  -> 扫描 queued/running run
  -> last_event_at 距今 >= 300s: 标记 interrupted/no_heartbeat_for_<seconds>_seconds
  -> last_event_at 缺失: 标记 failed/interrupted_by_backend_restart
  -> 追加 runner_interrupted event
  -> 前端显示需要重新运行
```

后续目标：

```text
HTTP backend -> durable job runner/subprocess worker -> backend 重启可 reattach pid/job_id -> 任务真正跨 backend 重启继续跑
```

### 15.5 前端依赖复用了 ELIS 的基础设施，不复用 ELIS 产品

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

第一步建议先做一次真实 Web happy path 验收：

1. 启动 backend。
2. 启动 frontend。
3. 在 Web 里创建一个新的 case，例如 `paper2-web-v1`。
4. 上传 `input/paper2` 下的 PDF 和必要材料。
5. 启动审查。
6. 在 Mission Control 看 progress events。
7. 在 Report Center 打开最终 HTML。
8. 对比 CLI 运行同一个输入时的 `outputs/{case_id}/research-integrity-audit/` 产物是否一致。

如果这一步卡住，优先修：

- 大文件上传方式。
- Web progress 可读性。
- 失败事件展示。
- artifact 列表覆盖范围。
