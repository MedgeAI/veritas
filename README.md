# Veritas

**实验室内部论文风控工具**——帮助导师（通讯作者）在投稿前主动发现学生数据中的问题，填补监管真空。

当前聚焦干实验论文（Python/R 医学生信与生物医药），投稿前技术复核，不是学术价值评价。

---

## 当前状态

**内部测试阶段**。核心能力已稳定，正在收集真实用户反馈并持续优化。

- ✅ 异步审计任务系统（Celery + Redis + PostgreSQL，1216 测试通过）
- ✅ Source Data PRD v2（Agent-centric 检测，Sheet Briefing）
- ✅ 视觉取证增强（ELIS adapter 接入，overlap/reuse detection）
- ✅ Web P1 工作台（Visual Forensics Gallery）

---

## 快速开始

```bash
make sync                                      # 同步依赖
make audit PAPER_DIR=<paper_dir> CASE_ID=<id>  # 运行论文审查
open outputs/<id>/research-integrity-audit/final_audit_report.html  # 查看报告
```

<details>
<summary><b>更多命令</b></summary>

| 命令 | 说明 |
|------|------|
| `make sync` | 同步 uv 环境 |
| `make test` | 运行全部测试 |
| `make test-fast` | 快速测试（排除重型视觉测试） |
| `make lint-python` | ruff lint 检查 |
| `make audit PAPER_DIR=... CASE_ID=...` | 运行论文审查 |
| `make audit-off PAPER_DIR=... CASE_ID=...` | 只跑确定性链路（无 Agent） |
| `make audit-fresh PAPER_DIR=... CASE_ID=...` | 强制重跑（忽略缓存） |
| `make precheck` | 确定性预检查 |
| `make run` | 运行轻量 manifest 测试 |
| `make report` | 渲染报告 |
| `make web-backend` | 启动 Web 后端（127.0.0.1:8765） |
| `make web-frontend` | 启动 Web 前端（127.0.0.1:5173） |
| `make celery-worker` | 启动 Celery worker（异步审计） |
| `make check-prompts` | 验证运行时提示词未漂移 |
| `make lock-prompts` | 更新提示词锁文件 |

### Agent Mode

| Mode | Agent Plan | Agent Review | Role Layer | 典型场景 |
|------|------------|--------------|------------|----------|
| `plan` | ✅ | ❌ | ❌ | 只让 Agent 做调查计划 |
| `review` | ❌ | ✅ | ✅ | **默认**：跳过 plan，直接 review |
| `full` | ✅ | ✅ | ✅ | 完整 Agent 流程 |

</details>

---

## 核心能力

| 能力 | 说明 |
|------|------|
| **Source Data 一致性检测** | 重复列、固定差值/比例、行偏移重复、跨 sheet 重复、数值分布异常 |
| **Source Data Agent 裁决** | Sheet Briefing 压缩上下文 → LLM 判定真假阳性 + 优先级赋值；`source_data.query` 语义工具支持跨组比较 |
| **图像操控检测** | copy-move、TruFor 伪造区域、跨图 reuse/overlap、panel-level 独立检测 |
| **Claim-to-data 映射** | 论文声明与 source data 数值不一致的发现 |
| **风险分层** | consistency（数据矛盾）> matching（claim 不符）> completeness（材料缺失） |

---

## 异步审计系统

Veritas 支持异步审计任务执行，适用于长时间运行的审计（30-60 分钟）。异步系统使用 Celery + Redis 作为 broker，PostgreSQL 作为状态存储和结果后端。

<details>
<summary><b>架构概览</b></summary>

```
用户 → POST /api/audit → Celery worker 异步执行 → SSE 实时进度推送
         ↓
    Redis (broker) + PostgreSQL (状态存储 + 结果后端 + 进度)
```

**核心特性**：
- **进程隔离**：Celery worker 独立进程，不阻塞 Web 服务
- **幂等性保证**：4 层防护（唯一索引 + FOR UPDATE + task_id 绑定 + 状态机）
- **并发控制**：独立限制 running（worker 槽位）和 queued（队列容量）
- **进程清理**：取消/失败时自动清理子进程、Docker 容器、临时文件、GPU 显存
- **实时进度**：PostgreSQL LISTEN/NOTIFY + SSE 推送

</details>

<details>
<summary><b>API 端点</b></summary>

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/audit` | POST | 提交审计任务（PDF 必选） |
| `/api/audit/{job_id}` | GET | 查询任务状态 |
| `/api/audit/{job_id}` | DELETE | 取消任务（含进程清理） |
| `/api/audit/{job_id}/stream` | GET | SSE 进度推送（JWT query param） |
| `/api/audit/queue` | GET | 队列状态（running/queued/max_concurrent/max_queue_size） |

</details>

<details>
<summary><b>环境变量</b></summary>

```bash
# 数据库（必须显式设置，无默认值）
# 开发环境：
VERITAS_DATABASE_URL=postgresql://veritas_dev:veritas_dev_pass@localhost:5433/veritas_dev
# 生产环境：在 deploy/.env 中设置 POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB

# Celery 配置（Redis broker + PostgreSQL result backend）
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=db+postgresql://veritas_dev:veritas_dev_pass@localhost:5433/veritas_dev

# 并发限制
AUDIT_MAX_CONCURRENT_JOBS=2      # 最大同时运行任务数（默认 2）
AUDIT_MAX_QUEUE_SIZE=10          # 最大队列长度（默认 10）
AUDIT_TASK_TIMEOUT_SECONDS=3600  # 任务超时时间（默认 3600 秒）

# 启用 Celery（可选，默认使用线程池）
VERITAS_USE_CELERY=false
```

</details>

<details>
<summary><b>数据库环境隔离</b></summary>

开发和生产使用**完全独立的数据库凭据**，防止串数据：

| 维度 | 本地开发 | 生产部署 |
|------|---------|---------|
| **用户名** | `veritas_dev` | `${POSTGRES_USER}` (从 `deploy/.env` 读取) |
| **密码** | `veritas_dev_pass` | `${POSTGRES_PASSWORD}` (**必填**，未设则启动失败) |
| **数据库** | `veritas_dev` | `${POSTGRES_DB:-veritas_prod}` |
| **端口** | `5433`（暴露到宿主机） | `5432`（容器内部，不暴露） |

**三层防御**：

1. **代码层** — `database.py` 无默认 URL，未设 `VERITAS_DATABASE_URL` 时启动失败（fail-loud）
2. **部署层** — 每个环境独立凭据，生产凭据在 `deploy/.env`（gitignored），不硬编码在 compose 文件中
3. **网络层** — 生产数据库不暴露端口到宿主机，容器间通过内部网络通信

</details>

<details>
<summary><b>使用方式</b></summary>

**1. 启动 Celery worker**：
```bash
make celery-worker
```

**2. 提交异步审计**：
```bash
curl -X POST http://localhost:8765/api/audit \
  -H "Content-Type: application/json" \
  -d '{"case_id": "paper1", "options": {}}'
```

**3. 查询进度**：
```bash
curl http://localhost:8765/api/audit/{job_id}
```

**4. SSE 实时进度**：
```javascript
const eventSource = new EventSource(`/api/audit/${jobId}/stream?token=${jwt}`);
eventSource.addEventListener('stage_changed', (e) => {
  console.log('Stage:', JSON.parse(e.data));
});
```

**5. 取消任务**：
```bash
curl -X DELETE http://localhost:8765/api/audit/{job_id}
```

</details>

<details>
<summary><b>数据库迁移</b></summary>

异步审计系统需要新增字段和索引。**迁移是幂等的，可安全多次执行**：

```bash
# 方法 1：直接在 PostgreSQL 容器中执行
docker exec veritas-postgres psql -U veritas -d veritas -c "
ALTER TABLE runs ADD COLUMN IF NOT EXISTS celery_task_id VARCHAR(255);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS stages JSON;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS current_stage VARCHAR(50);
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_active_case 
  ON runs (case_id) WHERE status IN ('queued', 'running');
"

# 方法 2：使用迁移脚本
DATABASE_URL=postgresql://veritas:veritas@localhost:5432/veritas \
  uv run python scripts/migrate_async_audit.py
```

</details>

---

## 仓库结构

```text
cli/          CLI 入口
engine/       核心业务逻辑（按领域分模块）
├── static_audit/   静态审查内核
│   ├── html_report/    HTML 报告（11 个子模块）
│   ├── pipeline.py     核心编排逻辑
│   ├── cli_driver.py   CLI 入口
│   └── tools/          确定性工具集
├── investigation/  Agent 调查编排
├── follow_up/      Follow-up 行动生成
└── tools/registry.py   Tool Registry（核心契约）
runtime/      本地执行后端
web/          Web 工作台（backend + frontend）
tests/        测试套件
third_party/  外部能力仓库（git submodule）
configs/      opencode 与运行配置
scripts/      工具脚本
docs/         产品和开发文档
outputs/      本地运行产物（不进入提交）
```

<details>
<summary><b>关键模块说明</b></summary>

| 模块 | 职责 | 关键文件 |
|------|------|----------|
| `engine/tools/registry.py` | Tool Registry — 工具集合的 source of truth | `ToolDefinition`, `ExecutionPhase` |
| `engine/static_audit/pipeline.py` | 核心编排逻辑 | `run_static_audit()` |
| `engine/static_audit/html_report/` | HTML 报告（11 个子模块） | `_core.py` 入口 |
| `engine/static_audit/visual_pipeline.py` | 视觉取证管线 | `run_visual_*()` |
| `engine/static_audit/investigation_dispatch.py` | Agent 调查分发 | `run_investigation_rounds()` |
| `engine/static_audit/tools/source_data_sheet_briefing.py` | Sheet Briefing — Agent 上下文压缩 | `build_sheet_briefing()` |
| `engine/static_audit/tools/source_data_query.py` | Source Data 语义查询工具 | `run_source_data_query()` |
| `engine/static_audit/tools/source_data_verdict.py` | LLM 语义裁决（briefing 驱动） | `run_source_data_verdict()` |
| `engine/investigation/agent_step_runner.py` | Agent 步骤执行器 | `AgentStepRunner` |
| `engine/investigation/context_pack.py` | Agent bounded context 构建 | `AgentContextPack` |
| `web/backend/veritas_web/` | Web 后端 | FastAPI + SQLAlchemy |
| `web/frontend/` | Web 前端 | Vite + React + Tailwind |

</details>

---

## 进一步阅读

| 文档 | 受众 | 说明 |
|------|------|------|
| [`AGENTS.md`](AGENTS.md) | 开发 Agent | 项目宪法——仓库规则、工程方法论、历史决策 |
| [`CodeMAP.md`](CodeMAP.md) | 开发者 | 模块职责和调用关系索引 |
| [`Dataflow.md`](Dataflow.md) | 开发者 | 数据流概览 |
| [`docs/product/`](docs/product/) | 产品 | 产品设计和决策文档 |
| [`docs/development/`](docs/development/) | 开发者 | 开发指南和技术文档 |
| [`configs/opencode/README.md`](configs/opencode/README.md) | 开发者 | opencode 提示词维护指南 |

---

<details>
<summary><b>Web P1 数据层</b></summary>

| 前端操作 | API | 写入位置 |
|----------|-----|----------|
| 创建 case | `POST /api/cases` | DB `cases` 表 |
| 上传输入 | `POST /api/cases/<id>/inputs` | `web_data/cases/<id>/inputs/` |
| 启动审查 | `POST /api/cases/<id>/runs` | DB `runs` / `run_events` 表 |
| 查看报告 | `GET /api/cases/<id>/report/html` | 读取 `outputs/` |

| 存储位置 | 用途 |
|----------|------|
| PostgreSQL / pgvector | Web 结构化状态、人工复核决策 |
| `web_data/cases/<id>/inputs/` | 用户上传的原始输入 |
| `outputs/<case_id>/` | 审查证据和报告 |

数据库：PostgreSQL 16 + pgvector（`make db-up` 启动本地 Docker 实例）。

</details>

<details>
<summary><b>认证</b></summary>

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `none` | 无认证（默认） | 本地开发、内网部署 |
| `bearer` | JWT 验证 | 嵌入模式 |
| `basic` | 用户名密码 | 独立模式 |

通过 `VERITAS_AUTH_MODE` 环境变量切换。

</details>

<details>
<summary><b>第三方能力吸收</b></summary>

| submodule | 可借鉴 | 禁止 |
|-----------|--------|------|
| `research-integrity-auditor` | MinerU 流程、evidence ledger、numeric forensics | 不把 vendor 格式当长期协议 |
| `elis` | panel-extractor、copy-move、TruFor、CBIR | 不直接接入 ELIS 主服务 |
| `deepwiki-open` | repo 理解、wiki 组织 | 不把 Next.js 应用搬进主架构 |
| `AsyncReview` | recursive investigation、工具调用 | 不允许绕过 Tool Registry |
| `paperconan` | 数值取证检测器集合 | 不直接执行 paperconan 二进制 |

能力进入主链路的顺序：license review → adapter → registry 注册 → 结构化 artifact → fixture test → report 消费。

详见 [`ELIS_REUSE_DECISIONS.md`](ELIS_REUSE_DECISIONS.md)。

</details>

<details>
<summary><b>audit-paper 数据流</b></summary>

```text
paper_dir
  -> material_inventory -> agent_material_plan
  -> MinerU PDF parse -> evidence_ledger -> numeric_forensics
  -> source_data (profile / findings / pair_forensics / cross_sheet / briefings / verdict)
  -> visual (panel_extraction / exact_duplicates / copy_move / overlap_reuse)
  -> agent_investigation (up to 3 rounds)
  -> agent_review -> role layer (ClaimExtractor -> SourceDataAuditor -> Judge)
  -> static_audit_bundle -> HTML/Markdown report
```

### Step status

| 状态 | 含义 |
|------|------|
| `ran` | 本轮真实执行成功 |
| `reused` | 产物已存在且未指定 `--force` |
| `skipped` | 前置材料或能力缺失 |
| `warning` | Agent 失败，降级继续 |
| `failed` | 确定性命令失败 |

</details>

<details>
<summary><b>环境依赖</b></summary>

| 依赖 | 说明 | 必需 |
|------|------|------|
| **uv** | Python 环境管理 | ✅ |
| **opencode** | Agent 角色层 | ✅（agent_mode != off） |
| **MinerU API** | PDF 解析 | ⚠️ 没有则跳过 |
| **Docker** | 开发环境 | ⚠️ 可选 |
| **NVIDIA GPU** | 模型推理 | ⚠️ 可选 |

```bash
make download-models   # 下载模型权重（YOLOv5 + TruFor）
```

</details>

<details>
<summary><b>生产诊断与 Agent 交接</b></summary>

生产环境出现异常时，先生成结构化现场包，而不是手动翻 `docker compose logs`：

```bash
make prod-diagnose
```

输出位置：

```text
web_data/diagnostics/latest.json
web_data/diagnostics/latest.md
```

把 `latest.json` 交给 Agent，可直接获得：容器状态、deep health、最近错误日志、host bind mount、模型权重、最新 audit manifest 和失败节点。该命令只读生产容器，不会重启或修改服务。

生产视觉取证长驻服务已纳入主 compose 网络：`sila-dense:8770` 负责 SILA dense copy-move，`elis-forensic:8771` 负责 ELIS provenance graph。生产容器必须通过 `SILA_DENSE_URL=http://sila-dense:8770` 和 `ELIS_FORENSIC_URL=http://elis-forensic:8771` 访问，不要使用容器内 `localhost:8770/8771`。

</details>

<details>
<summary><b>测试</b></summary>

```bash
make test          # 全部测试
make test-fast     # 快速测试（排除重型视觉测试）
make lint-python   # ruff check
```

</details>

---

## 不进入提交

- `input/`、`outputs/`、`web_data/`：输入和运行产物
- `web/frontend/dist/`、`web/frontend/node_modules/`：前端构建和依赖
- `.env`：密钥
