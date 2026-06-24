# AGENTS.md

> **受众**：开发 Agent（Claude Code 等 AI 编码助手）。
> 本文档是 Veritas 项目的开发宪法——架构、分层规则、设计约束、开发/部署工作流。
> 运行时审计上下文（opencode 提示词）不在本文件，见 `opencode.json` → `instructions`。
> 产品细节见 `README.md`；变更历史见 `CHANGELOG.md`。

## 项目定位

Veritas 是实验室内部论文风控工具，帮助导师（通讯作者）在投稿前发现学生数据中的问题。核心能力：Source Data 内部一致性检测（重复列/固定差值/跨 sheet 重复）、图像操控检测（copy-move/TruFor）、claim-to-source-data 映射。Finding 按 consistency > matching > completeness 分层呈现。详见 `README.md`。

## 分层架构

```text
Web / CLI / API   (web/, cli/)        — 输入输出、协议边界、展示，不放业务逻辑
    ↓
Orchestrator       (engine/static_audit/) — 编排、schema、role、报告
    ↓
Domain / Evidence  (engine/ investigation/ reporting/) — 业务逻辑唯一归属
    ↓
Tool Registry      (engine/tools/registry.py) — Engine↔Runtime 唯一边界
    ↓
Runtime            (runtime/)          — 命令执行、副作用隔离、证据记录
    ↓
Config / Types     (configs/, schema)  — 横向事实源，不承载流程逻辑
    ↓
Third-party        (third_party/)      — 能力吸收区，必须通过 adapter 包装
```

- `engine/tools/registry.py` 是运行时允许执行的 tool_id 的 source of truth
- 禁止上层跳过 registry/runtime 直接调第三方工具
- 禁止 `os.getenv()` 散落在业务代码中：环境变量通过 `engine/env.py` 集中管理
- 不要把 `runtime/` 移到 `engine/` 下面

## 核心设计规则

### Evidence First

报告必须从结构化 evidence event 生成，不能从 Agent 自然语言总结生成。至少支持：`file_evidence`、`execution_evidence`、`claim_match`、`figure_evidence`。

### 只讲事实，不讲观点

报告解释层只呈现从结构化数据动态生成的事实描述。LLM 只允许输出结构化 JSON（trace、claim mapping、finding review），不进入报告正文。每个 finding 给出"建议行动"（如"要求学生解释"），不给结论。

### Agent 边界

Agent **可以**：映射 claim→代码、选 Tool Registry 允许的 tool_id、生成结构化 JSON trace、写入 `outputs/`。
Agent **不可以**：编辑源码、应用 patch、判定学术不端、绕过 Tool Registry。
输出必须结构化；校验失败时反馈给 Agent 重试，仍失败则记录 failed trace，不覆盖确定性证据。

### Runtime 边界

Runtime 负责执行命令和记录证据（command manifest、stdout/stderr、exit code、runtime seconds、result files、file hashes）。Runtime 不是 Agent。

### 早失败原则

关键上游依赖失败时（如 MinerU 无法产出 `full.md`），**立即终止整个流水线**并标记后续步骤为 `failed`。没有论文全文上下文，下游 Agent 计划、claim 提取、PaperFraud 规则匹配都是高假阳性噪声。早失败、早暴露、早修复，比用 fallback 维持表面完整更重要。

详见 `engine/static_audit/pipeline.py` 中 `_run_mineru_forensics_section` 的返回值处理。

### 契约更新顺序

新增字段/状态/事件/artifact 时：契约/registry → producer → consumer → report/render → tests/golden fixture。单边修改协议是架构错误。

## 本地开发与生产部署

### 差异总览

| 维度 | 本地开发 | 生产部署 (Docker + Cloudflare) |
|---|---|---|
| 数据库 | PGlite（内存，用完即弃） | PostgreSQL 16 + pgvector |
| 审计执行 | 线程池（同步） | Celery worker（异步） |
| 前端 | Vite dev server（HMR）或 `npm run build` | Docker 构建阶段 `npm run build` |
| Auth | `none` | `none`（可在 `.env` 中切换） |
| 文件路径 | 相对路径 `web_data/`、`outputs/` | 容器内绝对路径 `/app/web_data/` |

### 本地开发工作流

```bash
# 终端 1: 后端（auto-reload on code change, PGlite 内存数据库）
make dev
# 或分别启动:
make web-backend-reload   # 后端 auto-reload
cd web/frontend && npm run dev   # 前端 Vite HMR (端口 5173, API → :8765)

# 终端 2 (可选): Celery worker（测异步路径时开启）
make celery-worker
```

- Vite dev server 已配置 API proxy（`/api` → `http://127.0.0.1:8765`），改前端代码秒级 HMR
- PGlite 是内存数据库，重启即清空——适合快速迭代，不污染线上数据
- 需要持久化或 pgvector 特性时：`make db-up` 启动 PostgreSQL 容器，设置 `VERITAS_DATABASE_URL`

### 生产部署

```bash
make deploy-rebuild    # 构建 + 启动 + 自动冒烟测试
```

冒烟测试自动验证：
1. `/api/health` — 服务可达
2. `/api/health/deep` — MinerU 脚本、opencode 二进制、Python imports、数据目录权限
3. `/api/cases` — API 路由正常

**关键约束**：`.dockerignore` 放行 `third_party/research-integrity-auditor/`、`third_party/elis/system_modules/`、`third_party/paperconan/`（审计核心依赖）；排除 `AsyncReview/` 和 `deepwiki-open/`（参考仓库，运行时不需要）。`Dockerfile` 有对应的 `COPY` 行。新增 third_party 依赖时必须同步更新这两处。

### 验证一致性

- 本地 `make test`（1216 测试）通过后才能 `make deploy-rebuild`
- Docker 容器内运行同一份代码（`deploy/Dockerfile` COPY 所有源码 + third_party 核心子目录）
- `/api/health/deep` 在本地和生产环境都应返回 `"status": "ok"`

## 仓库结构

```text
cli/                  CLI demo 入口
engine/
── tasks/            Celery 异步任务（审计任务、进程清理）
├── static_audit/     静态审查内核（orchestrator、schema、role、报告）
├── investigation/    Agent 调查编排（context_pack、agent_step_runner、role_runners）
├── follow_up/        Follow-up 行动生成
└── tools/registry.py Tool Registry（核心契约）
runtime/              本地执行后端
protocols/            垂直领域规则
configs/              opencode 上下文、methodology、运行配置
web/
├── backend/          FastAPI backend + routers
└── frontend/         Vite + React + Tailwind
third_party/          git submodule 锁定的外部仓库（见 .gitmodules）
tests/                单测、集成测试、e2e 测试
outputs/              报告和本地运行产物（不提交）
web_data/             Web case store 和运行状态（不提交）
```

`CodeMAP.md` 是模块职责和调用关系索引。跨模块改动前先读它。

## 测试

- `make test` — 全量测试
- `make test-fast` — 快速单元测试（<30s）
- `make lint-python` — ruff 检查
- Mock 只打在 I/O 边界（网络、文件、时钟、模型调用），不 mock 核心业务逻辑
- 涉及外部服务先加 fixture-based test
- Golden tests、历史 bug 回归样例不可随意修改

## 第三方仓库

通过 git submodule 跟踪，commit hash 锁定。进入主链路的顺序：

```text
license review → adapter/tool wrapper → registry.py 注册 → 结构化 artifact
→ manifest/limitations 记录 → fixture/golden test → report 消费
```

| submodule | 用途 | 禁止 |
|---|---|---|
| `research-integrity-auditor` | MinerU、evidence ledger、numeric forensics | 不在 vendor 目录表达产品规则 |
| `elis` | panel-extractor、copy-move、TruFor、CBIR | 不直接接入 ELIS 主服务 |
| `paperconan` | GRIM/GRIMMER 数值取证 | 不直接执行，要通过 adapter |
| `deepwiki-open` | repo 理解、wiki 组织 | 不搬 Next.js 主应用 |
| `AsyncReview` | recursive investigation、代码审查 | 不允许 Agent 绕过 Tool Registry |

`engine/static_audit/upstream/research_integrity_auditor/` 是 `research-integrity-auditor` 的只读镜像，不直接修改。需要 patched behavior 时在 first-party adapter 中实现。

## 工程注意事项

- Python 依赖由 `uv` 管理；所有 Python 命令通过 `uv run` 执行
- secrets 不写入 manifest、报告、日志或文档
- `docs/` 是文档工作区，`.gitignore` 默认忽略新文件；重要产品约束必须同步到根目录文档或 `configs/`
- 真实论文、运行产物和密钥不写入 `docs/`
- 新增 Agent 步骤时同时定义：context pack 输入、schema validator、retry/failed 语义、log artifact、manifest/report 暴露方式
- 所有 `run_agent_*` 入口通过 `AgentStepRunner` + bounded context pack 调用 opencode
