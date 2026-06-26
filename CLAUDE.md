@AGENTS.md

# Claude Entry Point

Read and follow `AGENTS.md`. It is the single source of truth for this repository.

Do not duplicate project rules in `CLAUDE.md`; duplicated rules will drift. If Claude cannot expand `@AGENTS.md`, open `AGENTS.md` directly before making changes.

Current local operations are documented in `README.md` and the root `Makefile`. Python dependencies are managed by `uv`; the usual checks are `make sync`, `make test`, and `make lint-python`.

**⚠️ 环境约束**：本项目使用 `uv` 管理 Python 环境和依赖。所有 Python 命令（`python`、`pytest`、`ruff` 等）必须通过 `uv run` 执行，或先激活 uv 虚拟环境。**禁止使用系统 Python**（`/usr/bin/python`），因为系统环境缺少项目依赖且 Python 版本不兼容（系统为 3.8，项目要求 ≥3.11）。常用命令：
- `uv run python -m pytest tests/` — 运行测试
- `uv run ruff check .` — lint 检查
- `make sync` — 同步依赖到 uv 环境

For current module/data-flow orientation, read `CodeMAP.md` and `Dataflow.md` before making cross-module changes. Visual forensics is currently a first-party beta with ELIS adapters planned, not a fully replaced ELIS pipeline.

** 代码探索优先使用 codebase-memory-mcp**：需要探索代码仓库、理解模块关系、追踪调用链、定位符号定义时，**优先使用 `codebase-memory-mcp` 工具**而非裸 Grep/Read。项目已启用 `auto_index`。常用操作：
- `search_graph` — 按名称/标签/语义搜索函数、类、路由
- `trace_path` — 追踪调用链（calls）、数据流（data_flow）、跨服务路径（cross_service）
- `get_code_snippet` — 用 qualified_name 精确取源码（带精确行号范围）
- `query_graph` — Cypher 查询，处理复杂多跳模式
- `get_architecture` — 项目结构、聚类、依赖全景
- `search_code` — 文本模式搜索（graph-augmented grep），按结构重要性排序

流程：若项目未索引，先 `index_repository` 再查询。查询结果不足时再用 Grep/Glob/Read 补充细节。

**核心产品设计哲学**：只讲事实，不讲观点。报告解释层只呈现从结构化数据动态生成的事实描述，不输出主观判断。不引入 LLM 生成自由文本进入报告正文。详见 `AGENTS.md` → "只讲事实，不讲观点"。

## 分层架构

```
UI → Engine (Service) → Runtime → Config/Types
```

依赖只能自上而下流动，禁止反向/横向/循环依赖。违反即架构错误。

| 层级 | 目录 | 职责 | 禁止 |
|---|---|---|---|
| **UI** | `cli/`, `web/backend/`, `web/frontend/` | 输入输出、协议边界、展示 | 不放业务逻辑 |
| **Engine** | `engine/` | 业务逻辑唯一归属，按领域分子模块 | 不直接调 subprocess/网络 I/O（通过 Runtime） |
| **Runtime** | `runtime/` | 命令执行、副作用隔离、证据记录 | 不承载业务推理 |
| **Config/Types** | `configs/`, schema 文件, `engine/tools/registry.py` | 横向事实源，约束行为边界 | 不承载流程逻辑 |

**关键约束**：
- **Tool Registry** (`engine/tools/registry.py`) 是 Engine 与 Runtime 之间的唯一边界；`audit-paper` 只能执行 registry 允许的 tool_id
- **Engine 内部**按领域分模块（`static_audit/`, `investigation/`, `reporting/`, `tools/`），模块间只能单向依赖
- **禁止 `os.getenv()` 散落在业务代码中**：环境变量通过 `engine/env.py` 集中管理
- **禁止上层直接跳过 registry/runtime 调第三方工具**：必须通过 adapter/tool 包装并注册
