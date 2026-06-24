# AGENTS.md

> **受众**：开发 Agent（Claude Code 等 AI 编码助手）。
> 本文档是 Veritas 项目的开发宪法——仓库结构、分层规则、工程方法论、历史决策。
> 运行时审计上下文（opencode 加载的提示词）不在本文件，见 `opencode.json` → `instructions`。

本文件是后续 AI 编码 Agent 进入本仓库时必须先读的项目操作指南。目标是避免上下文丢失后把项目方向拉偏。

## 项目定位

**Veritas 是一个实验室内部论文风控工具（当前聚焦干实验论文子集），帮助导师（通讯作者）在投稿前主动发现学生数据中的问题，填补监管真空，避免背锅。**

### 核心动机

**问题论文频发，导师由于脱离科研一线，导致监管真空，导师本人并不知情，无法核实数据真伪。**

- 导师给学生挂名通讯作者，但学生可能存在数据造假
- 导师脱离一线，不知道"该查什么"、不知道"是否正常"
- 导师和学生之间存在信息不对称
- 投稿前缺乏有效的自查机制

**Veritas 要解决的是：导师"不知情"的问题。** 工具主动暴露问题模式，打破信息不对称。

### 核心价值（必须强化）

1. **Source Data 内部一致性检测**（最关键）
   - Duplicate columns（不同列名，相同数据）
   - Fixed difference / fixed ratio（固定差值/比例，可能是人为编码或公式派生）
   - Row-offset patterns（行偏移重复，可能是复制粘贴）
   - 跨 sheet 重复（同一实验被包装成多个实验）
   - 数值分布异常（过于完美的正态分布、过少的异常值）

2. **图像操控检测**（高优先级）
   - Exact duplicates（字节级完全重复）
   - Copy-move detection（图内区域复制粘贴，如 Western blot 条带复制）
   - TruFor 伪造检测（神经网络检测图像篡改区域）
   - Panel-level 独立检测（拆分 panel 后对每个子图独立检测）

3. **Claim-to-source-data 映射**（重要）
   - 从 sheet 级推进到 column-block 级
   - 数值复算对比（论文说 mean=2.3±0.4，source data 算出来是 mean=2.1±0.5）
   - Claim 无法被数据支撑的发现

### 问题分层（Issue Categories）

所有 finding 必须分层，帮助导师判断优先级：

| 类别 | 含义 | 示例 | 典型风险级别 |
|---|---|---|---|
| **consistency**（一致性） | 数据内部矛盾，可能造假信号 | 重复列、固定关系、图像 copy-move | high/critical |
| **matching**（匹配性） | 论文与数据不符，claim 无法支撑 | 数值不一致、图表对不上 | medium/high |
| **completeness**（完整性） | 监管真空，学生未提交该有的东西 | 缺 Source Data、缺代码、缺环境文件 | low/medium |

**优先级**：consistency > matching > completeness

**原因**：
- consistency（数据造假）最严重，直接指向学术不端
- matching（claim 不符）次之，可能是笔误或理解偏差
- completeness（材料缺失）最轻，可能只是学生疏忽，但也可能是刻意隐瞒

### 当前能力边界（诚实声明）

- **材料缺失检测**：保留作为 completeness issue，是监管真空的信号（"学生没提交 Source Data → 可能数据不存在、被篡改、或学生在隐瞒"）
- **代码/环境文件**：PI 可以直接让学生补充，但系统仍然标记"未提供"作为完整性问题
- **代码执行审查**：`precheck` / `run` / `report` 和 `runtime/subprocess` 已有基础能力；但 `audit-paper` happy path 仍以静态证据、Source Data 和 Agent 结构化复核为主，claim-to-code/runtime replay 还不是稳定主链路。缺少代码、环境或结果文件时，仍按 `execution_status: not_provided`、`skipped` 或 completeness issue 呈现，不伪造成已验证复现。

### 工程约束

- 报告按 issue_category 分层呈现：高危发现（consistency）→ 匹配问题（matching）→ 完整性问题（completeness）
- 每个 finding 给出明确的"建议行动"（如"立即要求学生解释"、"核对计算过程"、"要求学生提交代码"）
- 报告重点呈现"高危发现 Top 5"和"人工复核任务清单"
- 当前聚焦干实验论文（Python/R 医学生信与生物医药，含使用流行病学/临床试验数据的计算论文：横断面研究、病例对照研究、队列研究、TCGA/GEO 临床数据分析等）

## 当前范围

MVP 聚焦：

- **干实验论文**：Python/R 医学生信与生物医药干实验论文，包含使用流行病学/临床试验数据的计算论文（横断面研究、病例对照研究、队列研究、TCGA/GEO 临床数据分析等）
- 投稿前技术复核，而不是学术价值评价
- 服务式流程：用户提交材料，我们代跑
- CLI-first，同时提供 Web P1 工作台用于内测 happy path
- opencode Agent 编排不确定推断，确定性脚本负责可重复检查

当前明确不做：

- 最终科研诚信判定
- 自动修改论文、Source Data 或代码
- 自动提交 patch
- 完整 SaaS 任务系统和多租户运营后台
- 远程 worker 集群

PaperFraud 规则适用性：PaperFraud `study_design.yaml` 中的所有规则对 Veritas 全部相关，包括流行病学/临床试验数据分析的检测规则，不禁用任何规则。

历史决策：先做最简单的一版验证，不急着铺完整 runtime；但 `audit-paper` 入口必须接入 opencode，不能退化成纯确定性脚本。

最小验证目标是：

```text
输入论文
-> opencode agent_plan 生成审查计划和确定性脚本参数
-> Python orchestrator 校验 Tool Registry 中允许的 tool_id
-> research-integrity-auditor / MinerU 做 PDF 解析和静态 evidence ledger
-> 确定性脚本做 numeric/source-data/image checks
-> opencode AgentInvestigationPlanner 基于已生成 artifacts 选择最多 3 轮后续确定性调查工具
-> opencode agent_review 读取结构化产物做 claim/finding 复核
-> opencode role layer 顺序执行 ClaimExtractor / SourceDataAuditor / JudgeAgent
-> AgentStepRunner 为所有 Agent 调用写入 bounded context_pack_*.json 和 logs/*.log
-> 产出结构化证据草案和 Markdown/HTML 报告
-> 再把 runtime / claim-to-code verification 纳入更稳定的 happy path
```

补充约束：PDF 解析、evidence ledger、numeric forensics、exact image duplicate 属于论文输入后的固定静态链路；image similarity 属于 Agent-selectable optional investigation tool。Source Data 不再假设一定存在或一定是 CSV/XLSX。当前实现先写 `material_inventory.json`，再由 `agent_material_plan` 或确定性 fallback 选择 optional evidence lane；只有被 Tool Registry 支持且根目录合法的 lane 才能进入执行。

最新补充：`image_similarity_candidates` 已从固定 baseline 移到 Agent-selectable investigation tool。`AgentInvestigationPlanner` 只能选择 Tool Registry 中 `agent_selectable=True` 且 deterministic 的工具；执行记录写入 `investigation_rounds.jsonl`，追加工具输出写入 `workdir/investigation/`，不得覆盖 baseline artifacts。

Agent 调用层最新状态：`engine/investigation/context_pack.py` 为 material plan、review 和 role layer 构建 bounded `AgentContextPack`；`engine/investigation/agent_step_runner.py` 统一执行 opencode、JSON extraction、schema validation、retry、错误分类和 `logs/*.log` 写入。`opencode_agent.py` 仍通过 legacy adapter 保持 orchestrator 兼容。后续若修改 Agent 行为，优先维护 context pack、runner result 和 manifest/report provenance 的契约，不要回退到裸自然语言输出。

也就是说，当前第一刀不是直接做完整 `veritas.yml -> runtime -> report`，而是先验证：

> opencode + `third_party/research-integrity-auditor` skill 是否能支撑论文输入后的证据抽取、确定性脚本编排和结构化调查闭环。

用户会自行寻找输入论文。拿到论文后，优先围绕这条最小路线做验证。

## 当前内测增强路线

**P0 已完成**：`audit-paper` happy path 已稳定走通，能产出完整的结构化证据和报告（Source Data、PaperFraud rule match、visual artifacts、HTML 报告）。paper1 全量审计验证通过（257 figures、811 panels、493 pair forensics findings、14 分钟完成）。

**进入 P1 阶段**：面向内测，允许完整借鉴 ELIS (Scientific Integrity System) 的图像取证栈，优先增强静态审查的视觉证据能力，重点是视觉 overlap/reuse detection 和 ELIS adapter 接入。

当前代码状态需要区分清楚：

- 已落地：canonical `figure_evidence` / `panel_evidence` / `visual_finding` / `image_relationship` schema、`visual.panel_extraction`（YOLOv5 adapter）、`visual.copy_move`（RootSIFT+MAGSAC++ adapter）、`visual.finding_pipeline`、`visual.overlap_reuse`、HTML Visual Evidence Package 和 Web Visual Forensics Gallery（含 overlap graph + detail drawer）。
- 当前 `visual.copy_move_dense` / SILA dense 是重型可选调查工具，支持 Web Visual Forensics Gallery 中按选中 panel 手动触发；不得在 `audit-paper` baseline 中对所有 panels 无条件全量运行。
- `visual.overlap_reuse` 已从 baseline 移除，仅通过 Agent investigation 或手动选择触发。数据契约已修复：ELIS runner 输出字段与下游消费者对齐，shared_area 作为 homography 缺失时的 fallback。
- 文档中提到的 TruFor、CBIR/Milvus 能力在进入 `engine/tools/registry.py` 并产出 fixture-backed artifact 前，不得写成稳定主链路。

目标能力：

```text
PDF / MinerU images
-> canonical figure_evidence
-> ELIS-style pdf-extractor / panel-extractor
-> copy-move dense/keypoint detection
-> TruFor forged-region heatmap
-> CBIR + Milvus single-paper internal similarity
-> AgentInvestigationPlanner 选择后续视觉调查工具
-> HTML visual evidence package
-> human review checklist
```

工程边界：

- ELIS 是能力来源和架构参考，不是 Veritas 主服务。
- 不直接把 ELIS FastAPI/Celery/MongoDB/Redis/Web UI 接进主链路。
- 可以复用 `third_party/elis/system_modules/elis-frontend` 的 Vite/React/Tailwind/布局基础设施，但 Veritas 前端必须放在 `web/frontend/`，业务流程和视觉语言必须是一方实现。
- 先把 ELIS 能力封装成 adapter/tool，注册到 `engine/tools/registry.py`，再由 orchestrator/runtime 执行。
- `figure_evidence` 是 canonical 图像证据入口；panel、mask、heatmap、CBIR match 都必须回链到 canonical figure/panel id。
- 重型视觉工具可以在 happy path 内测中失败隔离；失败必须写入 manifest、`investigation_rounds.jsonl` 和报告 limitations。
- 视觉工具输出只作为候选事实和人工复核任务，不构成最终科研诚信判定。

**ELIS 复用决策（2026-06-15）**：

- **Veritas 不开源（内部工具）**：AGPL-3.0 传染性不触发，可安全使用所有 ELIS 模块。
- **以 adapter 方式复用 ELIS `system_modules`**：panel-extractor（YOLOv5）、copy-move-detection（RootSIFT+MAGSAC++ / dense）、TruFor、CBIR 等。
- **ELIS adapter 已替换传统 CV 实现**：YOLOv5 panel extraction、RootSIFT+MAGSAC++ copy-move、TruFor skip-only、SILA dense 均已通过 subprocess adapter 接入主链路。`visual.overlap_reuse` 为 P1 新增工具。详见 [`ELIS_REUSE_DECISIONS.md`](ELIS_REUSE_DECISIONS.md)。
- **详见 [`ELIS_REUSE_DECISIONS.md`](ELIS_REUSE_DECISIONS.md)**。

## 当前能力与测试重点

**当前核心能力**（`make audit PAPER_DIR=<dir> CASE_ID=<case_id>`）：

```text
论文 PDF + Source Data 输入
-> MinerU PDF 解析（evidence ledger）
-> Source Data 内部一致性检测（duplicate columns / fixed difference / fixed ratio / pair forensics / cross-sheet）
-> Sheet Briefing（结构摘要 + pattern 聚类 + sample data 去重）
-> Source Data LLM 语义裁决（briefing 驱动，cluster→finding 展开）
-> PaperFraud rule match
-> 视觉取证全链路：panel extraction (YOLOv5) -> exact duplicate -> copy-move (RootSIFT+MAGSAC++) -> overlap/reuse (tile dHash + keypoint verification) -> TruFor skip-only
-> Agent investigation（最多 3 轮，可选触发 source_data.query / visual.overlap_reuse / image_similarity 等）
-> HTML 报告（Top-N findings、证据定位、良性解释、人工复核清单）
-> Web 工作台（Visual Forensics Gallery、Overlap Graph、Detail Drawer）
-> 异步审计任务（Celery + PostgreSQL，SSE 实时进度，进程清理）
```

**验证数据**：paper1 全量审计（257 figures、811 panels、493 pair forensics findings、14 分钟完成）。1216 个测试全部通过（uv 环境 Python 3.12）。

**测试注意事项**：
- 报告呈现的是结构化证据和人工复核任务，不是最终科研诚信判定
- TruFor / SILA dense / CBIR 为重型可选工具，测试时可验证入口但不强求全量运行
- `visual.overlap_reuse` 仅在 investigation 中触发，不在 baseline 全量运行
- 异步审计系统已就绪，测试并发场景和进程清理机制

## 开发前先读

做任何实质改动前，先读：

1. `README.md`
2. `AGENTS.md`
3. `configs/opencode/README.md`
4. `configs/opencode/veritas-agent.md`
5. `configs/opencode/biomed-research-audit-methodology.md`
6. `configs/methodology/`
7. `engine/tools/registry.py`

`docs/` 是产品、开发和决策文档的工作区；当前 `.gitignore` 仍默认忽略新文件，只有显式纳入版本控制的文档才可假设存在。后续 Agent 可优先读取相关 `docs/product/` 和 `docs/development/` 文档辅助判断，但不要让提交版功能依赖未跟踪的本地 docs，也不要把真实论文、真实运行产物或密钥写入 `docs/`。

如果要修改 opencode 论文审查上下文、skill 或领域先验，先读：

- `configs/opencode/README.md`

## 工程推进方法论

本节用于让后续 Agent 更快、更稳地推进当前项目。它补充本文件中的产品边界、Evidence First、Tool Registry 和 Agent 边界；如有冲突，以 Veritas 的产品边界和结构化证据约束为准。

### 工作判断

- 接到任务后，先用一句话确认真实目标和成功标准；只有当目标、成功标准或破坏面无法从仓库上下文判断时，才停下来问一个关键问题。
- 每项改动都要服务明确目标：P0 是 `audit-paper` happy path 能稳定走通并产出结构化证据和报告；P1 是视觉取证、Web P1、可靠性和关键差异化；P2 是打磨、性能、可观测性和非核心增强；不服务当前目标的默认不做。
- 如果 P0 仍不稳定，优先砍掉增强项，回到最短可验证闭环。
- 优先选择更简单、更直接的实现路径；不要为假想未来增加抽象层、插件化、配置化或策略框架。
- 每一行修改都应能追溯到当前目标；不要顺手重构无关模块。

### 业务模型先于实现模型

先把问题翻译成 Veritas 的业务主体和事实，再决定代码结构。常用主体包括：

- case、paper、submitted material、Source Data、code/environment、claim、evidence event、tool action、finding、manual review task、audit run、report。

建模时必须明确：

- 哪个主体被创建、改变或终止。
- 哪些不变量必须成立，例如 finding 必须回指结构化 evidence、Agent 不得绕过 Tool Registry、报告不得直接从自然语言总结生成。
- 哪个文件或契约是事实源，例如 `engine/tools/registry.py`、`static_audit_bundle.json`、`audit_run_manifest.json`、`configs/methodology/` 或具体 schema/test fixture。

实现模型只能服务业务模型，不能为了实现方便新增模糊概念。新增 issue category、evidence type、tool_id、run status 或 report field 时，先确认它是否属于现有模型；能复用现有语义就不要新增。

### 分层与依赖

默认按以下单向边界理解系统；配置、schema 和类型契约是横向事实源，不是另一套流程入口：

```text
Config / Schema / Type contract

Web / CLI / API
  ↓
Orchestrator / Workflow
  ↓
Domain / Evidence / Claim / Finding model
  ↓
Tool Registry / Runtime / Adapter
  ↓
Third-party toolbox / external service
```

落到仓库中：

- `web/` 和 `cli/` 处理输入输出、展示和协议边界，不放审查规则。
- `engine/static_audit/` 负责编排、schema、role、报告和 first-party 静态审查内核。
- `engine/tools/registry.py` 是 deterministic tool、tool_id、参数边界和输出契约的 source of truth。
- `runtime/` 负责命令执行、证据记录和副作用隔离，不承载 Agent 推理。
- `configs/methodology/` 承载领域方法论，Prompt/skill 只引用和路由，不复制成第二套事实源。
- `third_party/` 是能力吸收区，进入主链路前必须通过 adapter/tool 包装。

禁止上层直接跳过 registry/runtime 调第三方工具，禁止把业务规则散落在 UI、脚本、Prompt 或报告模板里。确实需要跨层时，先调整边界和契约。

### 契约与数据流

核心功能必须能画出数据流：

```text
输入材料
  ↓
材料清单 / 校验
  ↓
确定性工具或 Agent 受控选择
  ↓
结构化 artifacts
  ↓
static_audit_bundle / manifest
  ↓
Markdown / HTML report
  ↓
人工复核任务
```

新增字段、状态、事件、错误码或 artifact 时，按顺序更新：契约/类型或 registry → producer → consumer → report/render → tests/golden fixture。单边修改协议是架构错误。

事实必须来自可信数据源：PDF parse、Source Data、工具输出、命令记录、manifest、schema 校验或人工复核记录。没有证据就写“未知 / 未提供 / 当前证据不足”，不要让 Agent 补事实。

### AI、Prompt 与外部系统边界

- Prompt 只负责组织语言、抽取结构化意图、语义映射、良性解释压力测试和报告措辞。
- 路由规则、工具选择边界、状态机、权限、文件根目录、参数上下限、风险分层和 evidence schema 必须代码化、配置化或契约化。
- LLM 调用必须任务化、结构化、可替换；返回 JSON trace 或 schema 对齐结果，不让上层解析裸自然语言作为事实。
- 外部服务失败时应写入 manifest、limitations 和人工复核入口；不能静默降级成看似完整的结论。

### 编码前最小流程

动手前按最小成本完成：

1. 读现有文档、契约、相邻代码和相关测试。
2. 确认目标属于 P0、P1、P2 还是不做。
3. 列出关键假设、破坏面和需要保留的已有行为。
4. 画清输入到输出的数据流，确认事实源和副作用边界。
5. 选择最小实现，只触碰必要文件。
6. 先定义验证方式，再实现；外部集成优先 fixture-based test。

如果某一步无法完成，先缩小范围或补上下文，不要靠堆代码推进。

### Bug 排查流程

修 Bug 时先定位状态从哪一层开始偏离预期：

```text
复现问题
  ↓
定位层级
  ↓
追踪数据流和状态变化
  ↓
找到 root cause
  ↓
写最小修复
  ↓
补能失败的测试
  ↓
验证旧行为未破坏
```

禁止在没看清状态演变前堆 if/else。修复应修正模型、契约或边界，而不是只补一个特殊情况。

### 测试原则

- 测试必须验证真实源码行为，而不是验证 mock 行为。
- Mock 只打在 I/O 边界，例如网络、外部 API、文件系统、时钟或模型调用。
- 修 Bug 优先添加能在修复前失败的最小测试。
- 协议、schema、artifact、report 和 Agent structured output 要测序列化、非法输入和契约对齐。
- 涉及外部服务的能力，先用 fixture/golden case 固定行为，再接真实服务。

判断测试价值的问题是：如果源码里这行逻辑写错了，这个断言会失败吗？不会失败的测试不要写成核心保障。

### 熵增止损

出现以下信号时，暂停堆功能，先整理模型或契约：

- 同一业务语义出现 3 种以上命名或表示方式。
- 一个字段、状态、事件或类型被赋予多重含义。
- 无法画出清晰数据流。
- 单个函数、组件、Prompt 或配置文件承担多个职责。
- if/else 主要在弥补糟糕的数据结构。
- 业务规则散落在 UI、脚本、Repo、Prompt 或报告模板中。
- 测试大量依赖内部 mock，无法证明真实行为。
- 新需求总是需要复制粘贴相似代码。
- 修 Bug 总是在加特殊情况，而不是修正模型。

## 仓库结构

本仓库是孵化仓，不是成熟 SDK 包。

```text
cli/          CLI demo 入口
engine/       claim 审计、静态审查内核、Agent 调查和报告逻辑
├── tasks/    Celery 异步任务（审计任务、进程清理）
├── static_audit/   静态审查内核
├── investigation/  Agent 调查编排
├── follow_up/      Follow-up 行动生成
└── tools/registry.py   Tool Registry（核心契约）
runtime/      本地执行后端，未来可能独立成服务
protocols/    垂直领域规则，先从医学生信开始
configs/      opencode 上下文、领域 methodology 和运行配置
docs/         产品、开发、决策和本地参考文档
examples/     demo 输入和 manifest
scripts/      可复用本地工具脚本；不要承载产品规则
web/          Web P1：stdlib backend + Vite React frontend
third_party/  外部参考仓库和能力吸收区
outputs/      报告和本地运行产物
web_data/     Web P1 本地 case store 和运行状态
tests/        单测、集成测试和 e2e 测试
```

`engine/tools/registry.py` 是产品运行时允许执行的确定性工具集合。opencode skill 和 methodology 可以描述工具，但 `audit-paper` 只能执行 registry 允许的 tool_id。

`engine/static_audit/` 是当前 `audit-paper` 的 first-party 静态审查内核。后续新增静态审查 schema、role、tool、orchestrator 行为，优先放在这里，不要继续把产品逻辑堆进 `scripts/`。

`engine/tasks/` 是 Celery 异步任务模块，支持长时间审计任务（30-60 分钟）的异步执行。核心组件：
- `celery_app.py`：Celery 配置（PostgreSQL 作为 broker，无需 Redis）
- `audit_task.py`：审计任务实现（4 层幂等保证：唯一索引 + FOR UPDATE + task_id 绑定 + 状态机）
- `process_cleanup.py`：进程清理模块（MinerU 子进程、Docker 容器、临时文件、GPU 显存）

异步审计系统通过 `VERITAS_USE_CELERY` 环境变量启用，默认使用线程池。API 端点：POST/GET/DELETE `/api/audit`，GET `/api/audit/{id}/stream`（SSE），GET `/api/audit/queue`。并发控制：`AUDIT_MAX_CONCURRENT_JOBS`（running 任务数）和 `AUDIT_MAX_QUEUE_SIZE`（queued 任务数）独立限制。

`CodeMAP.md` 是模块职责和调用关系索引。做跨模块改动前优先读取它，避免凭目录名猜边界。

当前 role 层不是从 `agent_review` 派生的假 trace。`ClaimExtractor`、`SourceDataAuditor`、`JudgeAgent` 已通过 `engine.investigation.opencode_agent.run_agent_role()` 独立调用 opencode；成功 role 在未指定 `--force` 时会复用已有 output/trace，避免重复调用把成功结果覆盖成失败结果。

当前所有 `run_agent_*` 入口都应通过 `AgentStepRunner` 和 bounded context pack 调用 opencode。新增 Agent 步骤时要同时定义 context pack 输入、schema validator、retry/failed 语义、log artifact 和 manifest/report 暴露方式。

不要把 `runtime/` 移到 `engine/` 下面。`runtime/` 是一级产品原语。

### 本地产物和提交边界

- `input/`、`outputs/`、`web_data/`、`web/frontend/dist/`、`web/frontend/node_modules/` 和 `.env*` 默认是本地输入、运行产物、构建产物或密钥，不要提交。
- `.gitmodules` 和 `third_party/` 通过 git submodule 跟踪，commit hash 锁定；升级必须由维护者显式 `git submodule update --remote` 后 commit 新 gitlink，走 PR review。新人 `git clone --recursive` 即可完整还原。
- `docs/` 当前是维护型文档工作区，但 `.gitignore` 默认忽略新文件；只有显式跟踪的文档才进入提交。重要产品边界和工程约束必须同步到根目录文档或 `configs/`，不能只存在本地 docs。
- 真实论文、真实运行产物和密钥不能写入 `docs/`、报告模板或示例 fixture。

## 当前执行口径

上文”当前范围”是产品边界，本节只补工程执行口径：

- **P0 已完成**：`audit-paper` happy path 已稳定走通，能产出完整的结构化证据和报告。paper1 全量审计验证通过。
- **P1 已完成**：God File 拆分、ELIS adapter 接入、视觉取证增强、Source Data PRD v2 实现、异步审计任务系统。1216 个测试全部通过。
- **当前阶段**：内部测试。重点收集真实用户反馈、修复问题、优化体验。
- **PubPeer Ground Truth Pipeline**：代码框架已就绪（`engine/ground_truth/`），测试阶段继续迭代。
- `precheck` / `run` / `report` 已存在，但不要因此把当前产品表述成完整 SaaS 或完整 runtime 审查系统。
- PI / 课题组是第一付费方和主要报告读者；报告要保持谨慎风险语言和人工复核入口。

### 最近改进（2026-06-24）

- ✅ **异步审计任务系统**：Celery + PostgreSQL（broker）架构，支持长时间审计任务（30-60 分钟）异步执行。4 层幂等保证、并发控制（running + queued 独立限制）、进程清理、SSE 实时进度推送。详见 `docs/product/Veritas-异步审计任务系统PRD.md`。
- ✅ **Source Data PRD v2 实现**：Agent-centric Source Data 检测架构。确定性工具压缩搜索空间 → Agent 理解语义并裁决 → 结构化输出进入报告。详见 `docs/product/Veritas-Source-Data-检测能力演进-PRD.md`。
- ✅ **Sheet Briefing**：`source_data_sheet_briefing.py` — 每个 sheet 的结构化情报摘要（组数、列块、pattern 聚类、sample data 去重）。替代逐条 findings 注入 LLM context，解决 287 findings 导致 fig7 verdict 失败的 context 爆炸问题。
- ✅ **`source_data.query` 语义工具**：`source_data_query.py` — 高层语义输入（group name, column block label）+ 底层确定性实现。支持 `compare_groups` / `extract_block` / `find_cross_group_reuse`。已注册到 Tool Registry（agent-selectable）。
- ✅ **Claim extractor enrich**：`claim_decisiveness`（high/medium/low）+ `figure_refs` + `expected_source_data` 字段加入 claim extractor 输出。向后兼容。
- ✅ **Findings raw data samples**：每个 finding 附带 `raw_data_samples`（前 50 行完整列值），让 Agent 裁决时能看到原始数据。
- ✅ **Verdict 升级**：`source_data_verdict.py` 改用 Sheet Briefing 驱动；cluster→finding verdict 展开保持 per-finding 输出兼容；priority 字段（critical/high/medium/low）。
- ✅ **paper4 Fig3 golden fixture**：34 个实验组、9 个跨组 CFU 相同行对、列语义标注。`test_source_data_golden.py` 11 个测试。
- ✅ **测试增长**：1146 → 1218 个测试。
- ✅ **html_report 拆分**：`_core.py` 从 4332→381 行，拆分为 11 个子模块
- ✅ **orchestrator 拆分**：从 1648→206 行，拆分为 pipeline/cli_driver/_pipeline_steps
- ✅ **高复杂度重构**：`generate_fallback_questions` CC 26→3（策略模式）
- ✅ **PGlite 修复**：解决 142 个 web 测试的连接泄漏问题
- ✅ **CI 暂时禁用**：项目仍在大幅变动中，`.disabled` 后缀 mask

## 当前开发优先级

**内部测试阶段（当前重点）**：

1. **Source Data PRD v2（Agent-centric 检测）** ✅ 已完成：Sheet Briefing + `source_data.query` 语义工具 + claim extractor enrich + verdict 升级 + paper4 Fig3 golden fixture。1216 测试通过。详见 `docs/product/Veritas-Source-Data-检测能力演进-PRD.md`。
2. **异步审计任务系统** ✅ 已完成：Celery + PostgreSQL broker，4 层幂等保证，并发控制（running/queued 独立限制），进程清理，SSE 实时进度。API 端点：POST/GET/DELETE `/api/audit`，GET `/api/audit/{id}/stream`，GET `/api/audit/queue`。详见 `docs/product/Veritas-异步审计任务系统PRD.md`。
3. **视觉 overlap/reuse detection** ✅ 已实现：`visual.overlap_reuse` tool 已注册，tile-level dHash retrieval + RootSIFT+MAGSAC++ verification，产出 `visual/overlap_reuse.json`，5 个 synthetic fixtures，19 个单测通过。数据契约已修复，investigation dispatch 已接入。详见 `VISUAL_OVERLAP_PRD.md`。
4. **ELIS adapter 接入** ✅ 已完成：panel-extractor (YOLOv5)、copy-move keypoint (RootSIFT+MAGSAC++)、copy-move dense (SILA Docker)、TruFor (skip-only) 均已通过 subprocess adapter 接入主链路。详见 `ELIS_REUSE_DECISIONS.md`。
5. **Tool Registry 扩展** ✅ 已完成：所有 ELIS-style 工具已注册到 `engine/tools/registry.py`，`visual.overlap_reuse` 为 agent-selectable。
6. **Source Data pattern_strength 增强** ✅ 已完成：`fixed_difference` / `fixed_ratio` 已有 `pattern_strength` 字段（complete/strong/moderate/weak），HTML 报告已渲染。
7. **investigation 产物整合** ✅ 已完成：`_read_overlap_reuse_outputs()` 合并 baseline + investigation 产出，通过 `seen_pairs` 去重。
8. **opencode Agent 层** ✅ 已完成：`engine/investigation/` 完整实现，AgentStepRunner、context_pack、role_runners 正常工作。

**测试阶段重点**：

9. **Web P1 工作台**：收集内测反馈，修复问题，优化 Visual Forensics Gallery、overlap graph、relationship detail drawer、manual review workflow。
10. **视觉 fixture/golden 测试**：根据内测发现的问题，补强 visual v1 的 fixture/golden 测试，尤其是 panel ground truth、copy-move 负例、overlap 正负例、失败隔离和 strict evidence refs。
11. **用户体验优化**：根据真实用户反馈改进报告可读性、交互流程、错误提示。

**测试后推进**：

9. **Ground Truth Pipeline**：从 PubPeer ground truth 提炼通用检测原语的 5 阶段 pipeline（parser → mapper → gap_analyzer → design_spec → anti_overfit）。paper2 数据已就绪，代码框架已实现（`engine/ground_truth/`），测试阶段继续迭代。
10. 验证 opencode SDK / opencode 风格 Agent 能否接入 claim-to-code mapping。
11. 定义 `veritas.yml` schema，YAML 主、JSON 兼容。
12. 增强 subprocess runtime，产出结构化 execution evidence。
13. 接百炼 Qwen vLLM 做图表初筛。
14. 生成 Markdown/PDF 报告，支持作者视图和 PI 视图。

加入真实外部集成时，如果短期阻塞测试，先做 typed adapter + mock fixture，并在文档中写清缺口。

## 核心设计规则

### Evidence First

报告必须从结构化 evidence event 生成，不能直接从 Agent 自然语言总结生成。

至少支持：

- `file_evidence`
- `execution_evidence`
- `claim_match`
- `figure_evidence`

### 只讲事实，不讲观点

报告的解释层（benign explanation、review question、executive narrative）只呈现从结构化数据动态生成的事实描述，不输出主观判断、观点或建议。

核心约束：

- **解释必须引用具体数据**：每段解释必须包含 finding ID、sheet 名、列对、数值、score 等可验证参数，不允许出现无数据支撑的泛泛描述。
- **不引入 LLM 生成自由文本**：报告正文的所有文本必须由确定性代码生成（模板 + 参数化数据），不允许 LLM 直接生成报告段落。LLM 只允许输出结构化 JSON（trace、claim mapping、finding review），不进入最终报告叙事。
- **来源可追溯**：每段解释文本必须标注来源类型（ 规则定义 /  数据关联 /  Agent 分析），让读者清楚知道哪些是确定性规则、哪些是数据计算结果、哪些是 Agent 结构化输出。
- **制造问题，不提供答案**：工具的目标是帮 PI 产生具体的追问（"E/G 列 ratio=0.01 在 18 行全部满足，为什么没有测量噪声？"），而不是给 PI 一个舒服的结论（"这可能是 normalization 的常见做法"）。
- **不预判学术不端**：报告呈现的是结构化证据和人工复核任务，不是最终科研诚信判定。所有 finding 都是"技术事实候选"，不是"造假证据"。

如果未来需要引入 LLM 增强解释层：

- 只允许 structured output（JSON schema 约束），不允许自由文本进入报告。
- 输出必须标注为 ` AI 推断（未验证）`，与确定性事实明确区分。
- 不覆盖、不替代、不混合到确定性证据链路中。

### Agent 边界

Agent 可以：

- 把 claim 映射到代码和产物
- 识别入口脚本和结果文件候选
- 生成结构化 JSON trace
- 在 `agent_plan` 中选择 Tool Registry 允许的 tool_id 并填写参数
- 写入 `outputs/`

Agent 不可以：

- 自动编辑源码
- 自动应用 patch
- 自动提交 commit
- 判定最终学术价值或学术不端
- 写入 `outputs/` 之外的目录
- 绕过 Tool Registry 直接执行任意工具或命令

Agent 输出必须结构化。不符合 schema 时，用 Pydantic 校验错误反馈给 Agent 重试。

当前实现用轻量 Python validator 做 schema 校验；如果后续引入 Pydantic，保持“校验失败 -> 把错误反馈给 Agent 重试 -> 仍失败则 warning/failed trace，不覆盖确定性证据”的语义。

### Runtime 边界

Runtime 负责执行命令和记录证据。Runtime 不是 Agent。

MVP 最终需要支持 subprocess 执行。Docker 先保留接口。

执行层需要记录：

- command manifest
- stdout/stderr
- exit code
- runtime seconds
- result files
- file hashes

### PDF 解析

PDF 解析优先参考：

- `third_party/research-integrity-auditor`

它使用 MinerU 做 PDF 转换和 evidence ledger 构建。

不要把 token 写入文件、报告或日志。`MINERU_API_TOKEN` 从环境变量读取。

### 图表初筛

图表视觉初筛计划使用百炼 Qwen vLLM。

vLLM 输出只是初筛信号，不是最终证据。高风险项必须进入人工复核字段。

## CLI 合约

目标命令：

```bash
veritas init <project_dir>
veritas precheck <veritas.yml>
veritas run <veritas.yml>
veritas report <report.json>
```

当前可运行开发命令：

```bash
make sync
make audit PAPER_DIR=<paper_dir> CASE_ID=<case_id>
make precheck
make run
make report
```

当前内部测试推荐使用：

```bash
make audit PAPER_DIR=<paper_dir> CASE_ID=<case_id>
```

优先验证 `outputs/<case_id>/research-integrity-audit/final_audit_report.html`。该 HTML 是单文件静态报告，围绕 Top-N priority findings、证据定位、良性解释、人工复核动作和 role trace 展示；不要把它表述成最终科研诚信判定。`audit-paper` 进度写入 `stderr`，最终 summary JSON 写入 `stdout`，不要把进度事件混入最终 JSON；MinerU 子进程输出可以作为 `command_output` 进度事件转发。

`veritas run` 默认按 `eval` 深度设计。

## 测试要求

核心行为要测试驱动。

MVP 最低测试范围：

- schema test
- CLI smoke test
- claim matcher test
- runtime subprocess test
- report render test
- Agent structured-output validation test

本地 Python 环境由 `uv` 管理；`uv.lock` 是 Python 依赖锁文件，常用验证入口是 `make test` 和 `make lint-python`。`ruff` 已纳入 dev 依赖，lint 默认排除 `engine/static_audit/upstream/` 上游镜像，避免把只读 upstream 代码纳入 first-party lint 约束。

涉及外部服务的集成，先加 fixture-based test。

## 第三方仓库使用原则

`third_party/` 是能力吸收区，不是主产品源码。所有进入 `third_party/` 并被 Veritas 引用的外部仓库必须通过 git submodule 跟踪并锁定 commit hash；不允许以本地 clone 形式游离于 git 之外。

当前通过 git submodule 跟踪的第三方仓库：

| submodule | 可借鉴 | 禁止 |
|---|---|---|
| `third_party/research-integrity-auditor` | MinerU 流程、evidence ledger、numeric forensics、证据标注图、谨慎风险语言 | 不把 vendor 输出格式当 Veritas 长期协议；不在 vendor 目录表达产品规则 |
| `third_party/elis` | pdf-extractor、panel-extractor、copy-move、TruFor、CBIR/Milvus、视觉证据包思路 | 不直接接入 ELIS FastAPI/Celery/MongoDB/Redis/Web UI 主服务；引入重型模型或 AGPL 组件前先评估许可证、部署和失败隔离 |
| `third_party/deepwiki-open` | repo 理解、wiki 组织、Mermaid/结构图表达 | 不把 Next.js 主应用或通用 repo-wiki 产品形态搬进 Veritas 主架构 |
| `third_party/AsyncReview` | recursive investigation、工具调用和验证循环、代码审查式上下文探索 | 不允许 Agent 绕过 Tool Registry 任意执行 sandbox 代码；不把 GitHub token / 外部 PR 流程变成 Veritas 主依赖 |
| `third_party/paperconan` | 数值取证检测器集合、`scan.json` + `report.html` 输出结构、source data sanity check 流程 | 不直接执行 paperconan 的二进制/脚本，要通过 adapter 包装；不与 Veritas 现有 numeric forensics 重复造轮子 |

不要把大型第三方内部实现直接 import 进主链路。先用本地 adapter 包起来。

第三方能力进入主链路的顺序必须是：

```text
license / data-boundary review
-> first-party adapter or tool wrapper
-> engine/tools/registry.py 注册 tool_id、参数边界、输出契约
-> 写入结构化 artifact
-> manifest / investigation_rounds / limitations 记录成功、跳过或失败
-> fixture 或 golden test 固定行为
-> report / HTML visual package 消费结构化结果
```

`engine/static_audit/upstream/research_integrity_auditor/` 是对 `third_party/research-integrity-auditor` 的只读能力镜像。不要直接修改镜像来表达 Veritas 产品行为；需要同步 upstream 时应明确记录 upstream commit，需要 patched behavior 时在 first-party adapter 或 tool 中实现。

## 文档驱动开发

本项目采用文档驱动开发，`docs/` 是需要维护的项目文档区。

如果改动影响产品行为，请优先同步更新：

- `README.md`
- `AGENTS.md`
- `configs/opencode/`

如果改动影响已落地的 Web/Agent/runtime 计划，也要同步更新 `docs/product/` 或 `docs/development/` 中对应文档。

如果新决策改变了旧决策，新增一份 decision record，不要静默覆盖历史。

## 工程注意事项

- 后端、Agent、runtime、reporting 优先使用 Python
- Web 已被用户明确要求进入 P1；前端基础设施复用 ELIS 的 Vite/React/Tailwind 模式，后端仍保持 Python 主导
- 生成报告和运行产物放在 `outputs/`
- 不要把 secrets 写进 manifest、报告、日志或文档
- 不要提交 `__pycache__` 等缓存产物
