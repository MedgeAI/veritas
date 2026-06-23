# Veritas

**实验室内部论文风控工具**——帮助导师（通讯作者）在投稿前主动发现学生数据中的问题，填补监管真空。

当前聚焦干实验论文（Python/R 医学生信与生物医药），投稿前技术复核，不是学术价值评价。

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
| `make run` | 运行轻量 manifest demo |
| `make report` | 渲染报告 |
| `make web-backend` | 启动 Web 后端（127.0.0.1:8765） |
| `make web-frontend` | 启动 Web 前端（127.0.0.1:5173） |
| `make check-prompts` | 验证运行时提示词未漂移 |
| `make lock-prompts` | 更新提示词锁文件 |

### Agent Mode

| Mode | Agent Plan | Agent Review | Role Layer | 典型场景 |
|------|------------|--------------|------------|----------|
| `off` | ❌ | ❌ | ❌ | 纯确定性管线；调试 / CI |
| `plan` | ✅ | ❌ | ❌ | 只让 Agent 做调查计划 |
| `review` | ❌ | ✅ | ✅ | **默认**：跳过 plan，直接 review |
| `full` | ✅ | ✅ | ✅ | 完整 Agent 流程 |

</details>

---

## 核心能力

| 能力 | 说明 |
|------|------|
| **Source Data 一致性检测** | 重复列、固定差值/比例、行偏移重复、跨 sheet 重复、数值分布异常 |
| **图像操控检测** | copy-move、TruFor 伪造区域、跨图 reuse/overlap、panel-level 独立检测 |
| **Claim-to-data 映射** | 论文声明与 source data 数值不一致的发现 |
| **风险分层** | consistency（数据矛盾）> matching（claim 不符）> completeness（材料缺失） |

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
<summary><b>Docker 开发环境</b></summary>

```bash
./scripts/dev.sh up      # 一键启动（首次构建 ~5 分钟）
./scripts/dev.sh status  # 查看状态
./scripts/dev.sh down    # 停止
```

| 服务 | 端口 | 说明 |
|------|------|------|
| PostgreSQL | 5433 | Veritas 专用 |
| FastAPI 后端 | 8765 | 容器内热重载 |
| Vite 前端 | 5173 | 宿主机 HMR |

开发环境：PostgreSQL 在容器，后端在容器（代码挂载），前端在宿主机。
生产环境：前端打包进后端镜像，后端以非 root 用户运行。

</details>

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

策略：PostgreSQL > PGlite（轻量开发）。

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
  -> source_data (profile / findings / pair_forensics / cross_sheet / verdict)
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
