# CodeMAP

Veritas 代码仓库结构总览。

Updated: 2026-06-15

## 整体架构

Veritas 是一个**干实验论文投稿前技术复核**原型。当前主链路仍是 `audit-paper` 静态审查闭环：论文输入 -> 材料清单 -> PDF/MinerU 解析 -> Source Data/图像/数值取证 -> Agent 受控调查与复核 -> 结构化 bundle -> Markdown/HTML 报告。`precheck/run/report` 和 subprocess runtime 已有基础能力，但 claim-to-code/runtime replay 还不是 `audit-paper` 的稳定主链路。

当前视觉取证处在 first-party beta：canonical `figure_evidence` / `panel_evidence` / `image_relationship` / `visual_finding` artifact、HTML Visual Evidence Package 和 Web Visual Forensics Gallery 已落地；底层 panel/copy-move 算法仍是 OpenCV + ORB/SIFT 过渡实现。ELIS YOLOv5、RootSIFT/MAGSAC、TruFor、CBIR/Milvus 仍是 adapter 路线，不是当前稳定主链路。

本地 Python 环境由 `uv` 管理，根目录 `Makefile` 是当前推荐操作入口：`make sync` 同步依赖，`make test` 跑 Python 测试，`make lint-python` 跑 ruff，`make audit PAPER_DIR=<paper_dir> CASE_ID=<case_id>` 启动论文审查。

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
| `investigation/` | opencode Agent 多轮调查规划、bounded context pack、AgentStepRunner、JSON 校验、重试和错误分类 |
| `repo_intel/` | Git repo 扫描，识别入口脚本、配置文件、结果文件 |
| `tools/registry.py` | 确定性工具注册表（PDF 解析、数值取证、Source Data、PaperFraud rule match、图像相似度、visual panel/copy-move/finding pipeline 等） |
| `static_audit/` | 核心审计流水线，多阶段 pipeline（material inventory -> MinerU -> evidence ledger -> numeric/PaperFraud -> Source Data -> visual artifacts -> agent investigation -> roles -> bundle/report）。内部结构：`orchestrator.py`（pipeline 编排）、`_shared.py`（共享工具函数，消除循环依赖）、`investigation_dispatch.py`（investigation 轮次执行和 tool 选择）、`visual_pipeline.py`（视觉取证 pipeline）、`report.py`（报告数据聚合和渲染）、`tools/`（18 个静态审查工具）、`html_report/`（HTML 报告生成） |
| `reporting/` | 报告数据模型 + MD/HTML/JSON 渲染 |
| `workflows/` | precheck 和 execution_verify 流程编排 |

## Web 层 (`web/`)

| 模块 | 职责 |
|---|---|
| `backend/veritas_web/app.py` | stdlib HTTP API、CORS、鉴权入口、case 子资源 owner 校验、artifact/report 返回和前端 dist 托管 |
| `backend/veritas_web/auth.py` | `NoAuthProvider` / `BearerTokenProvider` / `BasicAuthProvider`，把请求头转换为 `AuthContext` |
| `backend/veritas_web/config.py` | 从环境变量构造 Web 鉴权配置和 provider |
| `backend/veritas_web/cli.py` | Basic Auth 用户管理 CLI（SQLite + bcrypt） |
| `backend/veritas_web/case_store.py` | file-based case/run/event 存储，按 `owner` / `user_id` 隔离，落盘到 `web_data/` |
| `backend/veritas_web/runner.py` | thread runner 直接调用 `run_static_audit()`，维护 `last_event_at` heartbeat 和 stale recovery |
| `backend/veritas_web/artifacts.py` | 将 `outputs/<case_id>/research-integrity-audit/` 的关键产物映射给 Web；访问控制由 `app.py` 的 case gate 负责 |
| `frontend/` | Vite + React + Tailwind 内测工作台：创建 case、上传输入、查看进度、浏览 evidence、Visual Forensics Gallery 和 HTML 报告 |

## Runtime 层 (`runtime/`)

| 模块 | 职责 |
|---|---|
| `executors/` | `subprocess_executor.py`（本地执行）已实现，`docker_executor.py` 为 stub |
| `jobs/` | JobRecord 生命周期模型 |
| `policies/` | 占位包 |
| `artifacts/` | 占位包 |

## 协议层 (`protocols/`)

| 协议 | 检查项 |
|---|---|
| `bioinfo_python` | 环境文件、入口脚本、结果文件 |
| `bioinfo_r` | 同上 + dry_run 定义检查 |
| `common/` | 验证级别、manifest schema |

## 配置层 (`configs/`)

- `opencode.json`：指向阿里云 DashScope 模型（当前默认 `qwen3.7-plus`）
- `configs/methodology/`：5 份领域取证方法文档（general、source-data、biomed-wetlab、bioinfo、visual-forensics）
- `configs/opencode/`：Agent 任务路由、审计方法索引、工具职责说明

`docs/` 是产品、开发和决策文档工作区；当前 `.gitignore` 默认忽略新文件，只有显式纳入版本控制的 docs 可被提交版流程依赖。重要工程边界仍应同步到根目录文档或 `configs/`。

## 本地工具链

| 文件 | 职责 |
|---|---|
| `Makefile` | 当前推荐本地操作入口：`sync`、`test`、`lint-python`、`audit`、`web-*` 等 |
| `pyproject.toml` | Python 包、runtime 依赖、dev 依赖和 ruff 配置 |
| `uv.lock` | `uv` 生成的 Python 依赖锁文件 |
| `.gitignore` | 忽略 `outputs/`、`web_data/`、`.uv-cache/`、前端构建产物和本地密钥 |

## 关键设计约束

- **Evidence First**：报告必须从结构化 evidence event 生成
- **Agent 边界**：Agent 不编辑源码、不自动提交、不绕过 Tool Registry
- **Tool Registry**：`audit-paper` 只能执行 `registry.py` 允许的 tool_id
- **Web 鉴权边界**：`app.py` 先认证得到 `AuthContext`，所有 case-scoped route 必须通过 `CaseStore.get_case(case_id, user_id=auth_context.user_id)` 校验；artifact/report/run/event/input 不能绕过 owner gate
- **PDF 解析**：通过 MinerU，token 从环境变量读取
- **视觉取证状态**：visual v1 artifacts 已落地；ELIS 重型/深度学习 adapter 未落地前只能写成计划或 limitations
