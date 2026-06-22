# Veritas

Updated: 2026-06-22

**Veritas 是一个实验室内部论文风控工具（当前聚焦干实验论文子集），帮助导师（通讯作者）在投稿前主动发现学生数据中的问题，填补监管真空，避免背锅。**

---

## 核心价值

| 能力 | 说明 |
|------|------|
| **Source Data 一致性检测** | 重复列、固定关系、数值异常、跨 sheet 重复 |
| **图像操控检测** | copy-move、伪造区域、跨图重复、panel-level 独立检测 |
| **Claim-to-data 映射** | 论文与数据不符的发现 |
| **Follow-up 行动生成** | 按风险分层生成人工复核任务 |

**问题分层**：所有 finding 按 `consistency`（最严重）> `matching` > `completeness`（材料缺失）分层。

---

## 当前状态

| 阶段 | 状态 | 说明 |
|------|------|------|
| **P0** | ✅ 完成 | `audit-paper` happy path 稳定，paper1 全量验证通过 |
| **P1** | ✅ 完成 | 视觉取证增强、ELIS adapter 落地、God File 拆分完成 |
| **P2** | 🔄 进行中 | 面向内测和演示 |

**关键指标**：
- 测试数量：1146 passed（uv 环境 Python 3.12）
- 代码质量：核心测试覆盖率 0.50，God File 已全部拆分
- paper1 全量审计：257 figures、811 panels、493 pair forensics findings、14 分钟完成

<details>
<summary><b>最近改进（2026-06-22）</b></summary>

- ✅ **html_report 拆分**：`_core.py` 从 4332→381 行，拆分为 11 个子模块
- ✅ **orchestrator 拆分**：从 1648→206 行，拆分为 pipeline/cli_driver/_pipeline_steps
- ✅ **高复杂度重构**：`generate_fallback_questions` CC 26→3（策略模式）
- ✅ **测试增强**：新增 10 个测试文件，测试覆盖率 0.38→0.50
- ✅ **PGlite 修复**：解决 142 个 web 测试的连接泄漏问题
- ✅ **CI 暂时禁用**：项目仍在大幅变动中，`.disabled` 后缀 mask

</details>

---

## 快速开始

```bash
# 同步依赖
make sync

# 运行论文审查（推荐 demo 命令）
make audit PAPER_DIR=<paper_dir> CASE_ID=<case_id>

# 查看报告
open outputs/<case_id>/research-integrity-audit/final_audit_report.html
```

<details>
<summary><b>更多命令</b></summary>

| 命令 | 说明 |
|------|------|
| `make sync` | 同步 uv 环境 |
| `make test` | 运行全部测试（1146 个） |
| `make test-fast` | 快速测试（排除重型视觉测试） |
| `make lint-python` | ruff lint 检查 |
| `make audit PAPER_DIR=... CASE_ID=...` | 运行论文审查 |
| `make audit-off PAPER_DIR=... CASE_ID=...` | 只跑确定性链路（无 Agent） |
| `make precheck` | 确定性预检查 |
| `make run` | 运行轻量 manifest demo |
| `make report` | 渲染报告 |
| `make web-backend` | 启动 Web 后端（127.0.0.1:8765） |
| `make web-frontend` | 启动 Web 前端（127.0.0.1:5173） |

### Agent Mode 四种取值

| Mode | Agent Plan | Agent Review | Role Layer | 典型场景 |
|------|------------|--------------|------------|----------|
| `off` | ❌ | ❌ | ❌ | 纯确定性管线；调试 / CI |
| `plan` | ✅ | ❌ | ❌ | 只让 Agent 做调查计划 |
| `review` | ❌ | ✅ | ✅ | **默认**：跳过 plan，直接 review |
| `full` | ✅ | ✅ | ✅ | 完整 Agent 流程 |

</details>

---

## 仓库结构

```text
cli/          CLI demo 入口
engine/       核心业务逻辑（按领域分模块）
├── static_audit/   静态审查内核
│   ├── html_report/    HTML 报告（11 个子模块）
│   ├── pipeline.py     核心编排逻辑
│   ├── cli_driver.py   CLI 入口
│   ├── report.py       报告生成
│   └── tools/          确定性工具集
├── investigation/  Agent 调查编排
├── follow_up/      Follow-up 行动生成
├── tools/registry.py   Tool Registry（核心契约）
└── ...
runtime/      本地执行后端
web/          Web P1（backend + frontend）
tests/        测试套件（1146 个测试）
third_party/  外部能力仓库（git submodule）
configs/      opencode 与运行配置
docs/         产品、开发和决策文档
outputs/      本地运行产物（不进入提交）
```

<details>
<summary><b>详细模块说明</b></summary>

| 模块 | 职责 | 关键文件 |
|------|------|----------|
| `engine/tools/registry.py` | Tool Registry — 工具集合的 source of truth | `ToolDefinition`, `ExecutionPhase` |
| `engine/static_audit/pipeline.py` | 核心编排逻辑 | `run_static_audit()` |
| `engine/static_audit/cli_driver.py` | CLI 入口 + 参数解析 | `main()` |
| `engine/static_audit/report.py` | 报告生成 | `generate_report()` |
| `engine/static_audit/html_report/` | HTML 报告（11 个子模块） | `_core.py` (381 行入口) |
| `engine/static_audit/visual_pipeline.py` | 视觉取证管线 | `run_visual_*()` |
| `engine/static_audit/investigation_dispatch.py` | Agent 调查分发 | `run_investigation_rounds()` |
| `engine/investigation/agent_step_runner.py` | Agent 步骤执行器 | `AgentStepRunner` |
| `engine/follow_up/` | Follow-up 行动生成 | `generate_fallback_questions()` |
| `web/backend/veritas_web/` | Web 后端 | FastAPI + SQLAlchemy |
| `web/frontend/` | Web 前端 | Vite + React + Tailwind |

各模块职责和调用关系详见 [CodeMAP.md](CodeMAP.md)。

</details>

---

## Docker 开发环境

```bash
# 一键启动（首次会构建镜像 ~5 分钟）
./scripts/dev.sh up

# 查看状态
./scripts/dev.sh status

# 一键停止
./scripts/dev.sh down
```

<details>
<summary><b>容器架构详情</b></summary>

| 服务 | 端口 | 说明 |
|------|------|------|
| PostgreSQL | 5433 | Veritas 专用，不碰生产 5432 |
| FastAPI 后端 | 8765 | Backend 容器（热重载） |
| Vite 前端 | 5173 | 宿主机 HMR |

**开发环境**：
- PostgreSQL + pgvector 在 Docker 容器
- Backend 在 Docker 容器（代码挂载热重载）
- Vite 前端在宿主机（HMR 秒级刷新）

**生产环境**：
- 前端打包进后端镜像
- 后端以非 root 用户 `veritas` 运行
- 数据通过 `/data/veritas/` 挂载

```text
┌─────────────────────────────────────────────────┐
│ 开发环境                                         │
├─────────────────────────────────────────────────┤
│  宿主机                                          │
│  ├─ Vite dev server (localhost:5173)            │
│  │   └─ /api/* ──┐                              │
│  │               │ 代理                         │
│  ├─ Docker       ▼                              │
│  │   ├─ backend:8765 ◄─┘                        │
│  │   │   └─ FastAPI + 热重载                    │
│  │   └─ postgres:5432                           │
│  │       └─ PostgreSQL + pgvector               │
└─────────────────────────────────────────────────┘
```

</details>

---

## Web P1 数据层

Web P1 的结构化状态由 SQLAlchemy 管理，支持 PostgreSQL / pgvector / PGlite 三种后端。

<details>
<summary><b>数据流和存储职责</b></summary>

| 前端操作 | API | 写入位置 |
|----------|-----|----------|
| 创建 case | `POST /api/cases` | DB `cases` 表 |
| 上传输入 | `POST /api/cases/<id>/inputs` | `web_data/cases/<id>/inputs/` |
| 启动审查 | `POST /api/cases/<id>/runs` | DB `runs` / `run_events` 表 |
| 查看报告 | `GET /api/cases/<id>/report/html` | 读取 `outputs/` |

| 存储位置 | 用途 |
|----------|------|
| PostgreSQL / pgvector | Web 结构化状态、人工复核决策、调查记录 |
| `web_data/cases/<id>/inputs/` | 用户上传的原始输入 |
| `outputs/<case_id>/` | `audit-paper` 生成的证据和报告 |

**目标策略**：尽量保持 PostgreSQL 语义一致。优先级：真实 PostgreSQL > PGlite（轻量开发）> ~~SQLite~~（不再作为 Web 状态存储）。

</details>

---

## 认证

Veritas Web 支持三种认证模式，通过 `VERITAS_AUTH_MODE` 切换。

<details>
<summary><b>认证详情</b></summary>

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `none` | 无认证（默认） | 本地开发、内网部署 |
| `bearer` | JWT 验证 | 嵌入模式，与主产品共享 JWT |
| `basic` | 用户名密码 | 独立模式，SQLite 用户管理 |

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VERITAS_AUTH_MODE` | 认证模式 | `none` |
| `VERITAS_JWT_SECRET` | Bearer 模式 JWT 密钥 | 空 |
| `VERITAS_USERS_DB` | Basic 模式用户数据库路径 | `web_data/users.db` |

### 用户管理 CLI（Basic 模式）

```bash
# 添加用户
PYTHONPATH=. python -m web.backend.veritas_web.cli add-user alice --roles admin

# 列出用户
PYTHONPATH=. python -m web.backend.veritas_web.cli list-users

# 修改密码
PYTHONPATH=. python -m web.backend.veritas_web.cli change-password alice
```

</details>

---

## 第三方能力吸收

`third_party/` 通过 git submodule 跟踪外部能力仓库。

<details>
<summary><b>Submodule 列表</b></summary>

| submodule | 可借鉴 | 禁止 |
|-----------|--------|------|
| `research-integrity-auditor` | MinerU 流程、evidence ledger、numeric forensics | 不把 vendor 格式当长期协议 |
| `elis` | panel-extractor、copy-move、TruFor、CBIR | 不直接接入 ELIS 主服务 |
| `deepwiki-open` | repo 理解、wiki 组织 | 不把 Next.js 应用搬进主架构 |
| `AsyncReview` | recursive investigation、工具调用 | 不允许绕过 Tool Registry |
| `geng-academic-fraud-detector` | "耿同学六式"方法论 | 不直接把 skill 当主链路 |
| `paperconan` | 数值取证检测器集合 | 不直接执行 paperconan 二进制 |

**能力进入主链路的顺序**：

```text
license review
-> adapter or tool wrapper
-> engine/tools/registry.py 注册
-> 写入结构化 artifact
-> fixture 或 golden test 固定行为
-> report 消费结构化结果
```

详见 [`ELIS_REUSE_DECISIONS.md`](ELIS_REUSE_DECISIONS.md)。

</details>

---

## audit-paper 数据流

<details>
<summary><b>完整数据流图</b></summary>

```text
paper_dir
  |
  +-- discover_pdf() -> paper_pdf
  +-- build_material_inventory() -> material_inventory.json
  |
  v
agent_material_plan (AgentStepRunner)
  |
  +-- agent_material_plan.json
  +-- selects source_data_xlsx if executable
  |
  v
agent_plan (when agent_mode=plan/full)
  |
  +-- agent_audit_plan.json
  +-- validates tool_id via Tool Registry
  |
  v
MinerU PDF parse
  |
  +-- full.md, images/, mineru_manifest.json
  |
  v
deterministic evidence
  |
  +-- evidence_ledger.json
  +-- numeric_forensics.json
  +-- source_data_findings.json (if selected)
  +-- exact_image_duplicates.json
  |
  v
visual panel evidence (ELIS YOLOv5 adapter)
  |
  +-- figure_evidence.json, panel_evidence.json
  |
  v
AgentInvestigationPlanner (up to 3 rounds)
  |
  +-- investigation_rounds.jsonl
  +-- investigation/round_XX/action_YY artifacts
  |
  v
visual finding pipeline
  |
  +-- image_relationships.json, visual_findings.json
  |
  v
agent_review (when agent_mode=review/full)
  |
  +-- agent_review.json
  +-- candidate claims, finding reviews
  |
  v
static audit role layer
  |
  +-- ClaimExtractor -> SourceDataAuditor -> JudgeAgent
  +-- agent_traces/*.json
  |
  v
generate_report
  |
  +-- final_audit_report.md, final_audit_report.html
  +-- audit_run_manifest.json, static_audit_bundle.json
```

### 图像产物清单

| 目录 | 大小 | 内容 | 必要性 |
|------|------|------|--------|
| `visual/images/` | 7.7 MB | MinerU 提取的原始 figure 图片 | ✅ 必须 |
| `panels/` | ~24 MB | YOLOv5 panel 裁剪图 | ✅ 必须 |
| `tru_for/` | ~5 MB | TruFor 伪造热力图 | ⚠️ 按需 |
| `provenance/` | 0 MB | RootSIFT 验证中间数据 | ❌ 无 edges 时不生成 |

**典型总量**：一份 250 图论文的视觉产物约 **37 MB**。

</details>

---

## audit-paper 状态机

<details>
<summary><b>状态机详情</b></summary>

```text
START -> PARSE_ARGS -> DISCOVER_INPUTS -> CREATE_WORKDIR
  -> MATERIAL_INVENTORY -> AGENT_MATERIAL_PLAN? -> AGENT_PLAN?
  -> MINERU -> PDF_DERIVED_STEPS -> SOURCE_DATA_STEPS
  -> IMAGE_DUPLICATE_CHECK -> VISUAL_PANEL_EVIDENCE
  -> AGENT_INVESTIGATION? -> VISUAL_FINDING_PIPELINE
  -> VLM_TRIAGE -> AGENT_REVIEW? -> AGENT_ROLES?
  -> GENERATE_REPORT -> WRITE_MANIFEST -> EXIT
```

### Step status 含义

| 状态 | 含义 |
|------|------|
| `ran` | 本轮真实执行成功 |
| `reused` | 目标产物已存在且未指定 `--force` |
| `skipped` | 前置材料或能力缺失，跳过但不视为失败 |
| `warning` | Agent 失败或输出不合规，降级继续 |
| `failed` | 确定性命令失败，最终进程返回 1 |

### Agent Role Layer

当前顺序执行 3 个角色：`ClaimExtractor`、`SourceDataAuditor`、`JudgeAgent`。其余 role 占位给后续扩展。

</details>

---

## 环境依赖

| 依赖 | 说明 | 必需 |
|------|------|------|
| **uv** | Python 环境管理 | ✅ |
| **opencode** | Agent 角色层 | ✅（agent_mode != off） |
| **MinerU API** | PDF 解析 | ⚠️ 没有则跳过 |
| **Docker** | 开发环境 | ⚠️ 可选 |
| **NVIDIA GPU** | 模型推理 | ⚠️ 可选 |

<details>
<summary><b>安装说明</b></summary>

### opencode

```bash
npm install -g opencode-ai
# 或
curl -fsSL https://opencode.ai/install | bash
```

### MinerU

PDF 解析依赖 MinerU API，通过 `MINERU_API_TOKEN` 环境变量提供 token。

### 模型权重

```bash
make download-models
```

</details>

---

## 测试

```bash
make test          # 1146 个测试
make lint-python   # ruff check
```

<details>
<summary><b>测试详情</b></summary>

| 类型 | 数量 | 说明 |
|------|------|------|
| 单元测试 | ~1000 | 核心模块测试 |
| 集成测试 | ~50 | 模块间交互 |
| 端到端测试 | ~30 | 完整管线 |
| Web 测试 | ~140 | FastAPI + React |

**测试覆盖率**：0.50（目标 0.6）

**CI 状态**：暂时禁用（项目仍在大幅变动中）

</details>

---

## 不进入提交

- `input/`：真实论文与用户输入材料
- `outputs/`：本地运行产物与报告
- `web_data/`：Web 上传输入和运行文件
- `web/frontend/dist/`：前端构建产物
- `web/frontend/node_modules/`：前端依赖
- `.env`：本地密钥
- `docs/`：默认被 `.gitignore` 忽略，重要文档需显式跟踪
