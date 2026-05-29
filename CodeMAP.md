# CodeMAP

Veritas 代码仓库结构总览。

## 整体架构

Veritas 是一个**干实验论文 claim 执行型技术复核**原型，核心流程：论文输入 -> PDF 解析 -> claim-to-code 映射 -> precheck -> 执行验证 -> claim 对账 -> 报告生成。

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
| `investigation/` | opencode Agent 多轮调查规划，JSON 校验 + 重试 |
| `repo_intel/` | Git repo 扫描，识别入口脚本、配置文件、结果文件 |
| `tools/registry.py` | 确定性工具注册表（PDF 解析、数值取证、图像相似度等） |
| `static_audit/` | 核心审计流水线，14 阶段 pipeline（material inventory -> MinerU -> evidence ledger -> numeric forensics -> agent investigation -> roles -> 报告） |
| `reporting/` | 报告数据模型 + MD/HTML/JSON 渲染 |
| `workflows/` | precheck 和 execution_verify 流程编排 |

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

- `opencode.json`：指向阿里云 DashScope 模型（`qwen3.7-max` / `qwen3.6-plus`）
- `configs/methodology/`：5 份领域取证方法文档（general、source-data、biomed-wetlab、bioinfo、visual-forensics）
- `configs/opencode/`：Agent 任务路由、审计方法索引、工具职责说明

## 关键设计约束

- **Evidence First**：报告必须从结构化 evidence event 生成
- **Agent 边界**：Agent 不编辑源码、不自动提交、不绕过 Tool Registry
- **Tool Registry**：`audit-paper` 只能执行 `registry.py` 允许的 tool_id
- **PDF 解析**：通过 MinerU，token 从环境变量读取
