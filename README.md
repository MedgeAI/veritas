# Veritas

Updated: 2026-06-21

**Veritas 是一个实验室内部论文风控工具（当前聚焦干实验论文子集），帮助导师（通讯作者）在投稿前主动发现学生数据中的问题，填补监管真空，避免背锅。**

**核心动机**：问题论文频发，导师由于脱离科研一线，导致监管真空，导师本人并不知情，无法核实数据真伪。

**核心价值**：
- Source Data 内部一致性检测（重复列、固定关系、数值异常）
- 图像操控检测（copy-move、伪造区域、跨图重复）
- Claim-to-source-data 映射（论文与数据不符的发现）

**问题分层**：所有 finding 按 `consistency`（一致性，最严重）> `matching`（匹配性）> `completeness`（完整性，材料缺失）分层，帮助导师判断优先级。

当前仓库以 `audit-paper` 审查闭环为核心，同时提供 Web P1 工作台：在浏览器里创建 case、上传输入、启动与 CLI 等价的审查、观察进度、打开最终 HTML 报告，并在 Visual Forensics Gallery 中对选中的 panel 手动触发受 Tool Registry 约束的重型视觉调查。

## 当前范围

MVP 聚焦：

- **干实验论文**：Python/R 医学生信与生物医药干实验论文（不泛化到湿实验、临床试验等）
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
- 湿实验、临床试验、材料科学等非干实验论文（后续再泛化）

## 当前执行口径

- **P0 已完成**：`audit-paper` happy path 已稳定走通，能产出完整的结构化证据和报告（Source Data、PaperFraud rule match、visual artifacts、HTML 报告）。paper1 全量审计验证通过（257 figures、811 panels、493 pair forensics findings、14 分钟完成）。
- **P1 当前重点**：面向内测和演示。视觉取证能力已增强，ELIS-style adapter 已落地。
- `precheck` / `run` / `report` 和 `runtime/subprocess` 已有基础能力；但 `audit-paper` 仍以静态证据、Source Data 和 Agent 结构化复核为主，claim-to-code/runtime replay 还不是稳定主链路。
- 缺少代码、环境或结果文件时，报告应按 `execution_status: not_provided`、`skipped` 或 completeness issue 呈现，不伪造成已验证复现。
- Web P1 是内测工作台，不是完整 SaaS、多租户任务系统或远程 worker 集群。
- **视觉取证已落地**：canonical `figure_evidence` / `panel_evidence` / `visual_finding` / `image_relationship` schema、`visual.panel_extraction`（YOLOv5 adapter）、`visual.copy_move`（RootSIFT+MAGSAC++ adapter）、`visual.finding_pipeline`、`visual.overlap_reuse`、HTML Visual Evidence Package 和 Web Visual Forensics Gallery（含 overlap graph + detail drawer）。
- `visual.copy_move_dense` / SILA dense 是重型可选调查工具，支持 Web Visual Forensics Gallery 中按选中 panel 手动触发；不得在 `audit-paper` baseline 中对所有 panels 无条件全量运行。
- `visual.overlap_reuse` 已从 baseline 移除，仅通过 Agent investigation 或手动选择触发。

## 当前内测增强路线

**P0 已完成**：`audit-paper` happy path 已稳定走通，能产出完整的结构化证据和报告（Source Data、PaperFraud rule match、visual artifacts、HTML 报告）。paper1 全量审计验证通过（257 figures、811 panels、493 pair forensics findings、14 分钟完成）。394 个测试全部通过（uv 环境 Python 3.12）。

**进入 P1 阶段**：面向内测，允许完整借鉴 ELIS (Scientific Integrity System) 的图像取证栈，优先增强静态审查的视觉证据能力，重点是视觉 overlap/reuse detection 和 ELIS adapter 接入。

当前代码状态需要区分清楚：

- **已落地**：canonical `figure_evidence` / `panel_evidence` / `visual_finding` / `image_relationship` schema、`visual.panel_extraction`（YOLOv5 adapter）、`visual.copy_move`（RootSIFT+MAGSAC++ adapter）、`visual.finding_pipeline`、`visual.overlap_reuse`、HTML Visual Evidence Package 和 Web Visual Forensics Gallery（含 overlap graph + detail drawer）。
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

**模型权重下载**（仅用于后续 YOLOv5 panel-extractor adapter 开发；当前主链路不要求该权重）：

```bash
# 下载 YOLOv5 panel extraction 模型（~50MB，需要科学上网）
make download-models

# 或手动下载
pip install gdown
gdown --id 1CuSUYUF0uTbcANFRffzoMUllCP8Du-HT
unzip panel_extraction_models.zip -d models/panel_extraction/
```

## 仓库结构

```text
cli/          CLI demo 入口
engine/       claim 审计、静态审查内核、Agent 调查、报告逻辑
runtime/      本地执行后端，未来可独立成服务
protocols/    垂直领域规则，先从医学生信开始
configs/      opencode 与运行配置
docs/         产品、开发和决策文档工作区；新文件默认仍被 .gitignore 忽略，重要文档需显式跟踪
capabilities/ 能力目录定义
ground_truth/ Ground truth 数据和标注
examples/     demo manifest 和轻量样例
scripts/      可复用本地工具脚本
web/          Web P1：stdlib backend + Vite React frontend
tests/        单测、集成测试和 e2e 测试
third_party/  外部能力仓库，通过 git submodule 跟踪并锁定 commit hash
outputs/      本地运行产物与报告，不进入提交
web_data/     Web P1 上传输入和运行文件，不进入提交
```

`engine/tools/registry.py` 是当前静态审查工具集合的 source of truth。opencode 可以在 `agent_plan` 中选择 tool_id 和填写参数，但只有 Tool Registry 允许的 tool_id 会被 Python orchestrator 执行。

`engine/static_audit/` 是 Veritas first-party 静态审查内核，负责 schema、protocol、roles、tools、orchestrator 和 `static_audit_bundle.json`。2026-06-20 重构后，orchestrator 已拆分为模块化架构：
- `orchestrator.py`: 主编排逻辑（~350 行）
- `_shared.py`: 共享常量、工具函数和类型定义
- `report.py`: 报告生成逻辑
- `investigation_dispatch.py`: 调查分发和 Agent 调用
- `visual_pipeline.py`: 视觉取证管道编排
- `html_report/`: HTML 报告模块

`third_party/research-integrity-auditor` 仍作为 upstream reference，已吸收到 `engine/static_audit/upstream/research_integrity_auditor/` 的只读镜像中。

各模块职责和调用关系详见 [CodeMAP.md](CodeMAP.md)。

不进入提交：

- `input/`：真实论文与用户输入材料。
- `outputs/`：本地运行产物与报告。
- `web_data/`：Web 本地上传输入和运行文件；结构化状态以数据库为准。
- `web/frontend/dist/`：前端本地构建产物。
- `web/frontend/node_modules/`：前端依赖。
- `.env`：本地密钥。
- `.gitmodules` / `third_party/`：通过 git submodule 跟踪并锁定 commit hash，`git clone --recursive` 完整还原；升级必须由维护者显式 commit 新 gitlink。
- `docs/`：产品、开发和决策文档工作区。当前 `.gitignore` 仍默认忽略新文件，因此只有显式纳入版本控制的 docs 可被提交版流程依赖；真实论文、运行产物和密钥不能写入。

## 第三方参考和能力吸收

`third_party/` 是能力吸收区，不是主产品源码。所有进入 `third_party/` 并被 Veritas 引用的外部仓库必须通过 git submodule 跟踪并锁定 commit hash。

当前通过 git submodule 跟踪的第三方仓库：

| submodule | 可借鉴 | 禁止 |
|---|---|---|
| `third_party/research-integrity-auditor` | MinerU 流程、evidence ledger、numeric forensics、证据标注图、谨慎风险语言 | 不把 vendor 输出格式当 Veritas 长期协议；不在 vendor 目录表达产品规则 |
| `third_party/elis` | pdf-extractor、panel-extractor、copy-move、TruFor、CBIR/Milvus、视觉证据包思路 | 不直接接入 ELIS FastAPI/Celery/MongoDB/Redis/Web UI 主服务；引入重型模型或 AGPL 组件前先评估许可证、部署和失败隔离 |
| `third_party/deepwiki-open` | repo 理解、wiki 组织、Mermaid/结构图表达 | 不把 Next.js 主应用或通用 repo-wiki 产品形态搬进 Veritas 主架构 |
| `third_party/AsyncReview` | recursive investigation、工具调用和验证循环、代码审查式上下文探索 | 不允许 Agent 绕过 Tool Registry 任意执行 sandbox 代码；不把 GitHub token / 外部 PR 流程变成 Veritas 主依赖 |
| `third_party/geng-academic-fraud-detector` | AI Agent Skill 形态、"耿同学六式"打假方法论（图片复用、数据造假、统计异常等检测维度） | 不直接把 skill 脚本当作 Veritas 主链路；方法论要转化为 Veritas 的 tool registry 条目或 methodology 配置 |
| `third_party/paperconan` | 数值取证检测器集合、`scan.json` + `report.html` 输出结构、source data sanity check 流程 | 不直接执行 paperconan 的二进制/脚本，要通过 adapter 包装；不与 Veritas 现有 numeric forensics 重复造轮子 |

第三方能力进入主链路的顺序：

```text
license / data-boundary review
-> first-party adapter or tool wrapper
-> engine/tools/registry.py 注册 tool_id、参数边界、输出契约
-> 写入结构化 artifact
-> manifest / investigation_rounds / limitations 记录成功、跳过或失败
-> fixture 或 golden test 固定行为
-> report / HTML visual package 消费结构化结果
```

`engine/static_audit/upstream/research_integrity_auditor/` 是对 `third_party/research-integrity-auditor` 的只读能力镜像。不要直接修改镜像来表达 Veritas 产品行为；需要 patched behavior 时在 first-party adapter 或 tool 中实现。

## audit-paper 数据流 / Data Flow

The following diagram traces the full `audit-paper` pipeline from raw paper input to final report generation. Each box is a pipeline stage; arrows show data dependencies and artifact outputs written to the workdir.

```text
paper_dir
  |
  +-- discover_pdf()
  |     |
  |     v
  |   paper_pdf
  |
  +-- build_material_inventory()
        |
        v
      material_inventory.json

material_inventory.json + workdir + env
  |
  v
+-----------------------------+
| agent_material_plan         |
| agent_mode != off           |
| AgentStepRunner + context   |
| pack -> optional lanes      |
+-----------------------------+
  |
  +-- writes agent_material_plan.json
  +-- writes context_pack_material_plan.json and logs/*.log
  +-- selects source_data_xlsx if executable
  +-- records missing/unsupported materials
  |
  v
selected optional lanes + paper_pdf + workdir + env
  |
  v
+-----------------------------+
| agent_plan                  |
| when agent_mode=plan/full   |
| AgentStepRunner + context   |
| pack -> tool_id JSON        |
+-----------------------------+
  |
  +-- writes agent_audit_plan.json
  +-- writes context_pack_agent_plan.json and logs/*.log
  +-- validates tool_id via Tool Registry
  +-- provides source_data_findings params
  |
  v
+-----------------------------+
| MinerU PDF parse            |
| third_party tool            |
+-----------------------------+
  |
  +-- full.md
  +-- images/
  +-- mineru_manifest.json
  |
  v
+-----------------------------+
| deterministic evidence      |
+-----------------------------+
  |
  +-- evidence_ledger.json
  +-- numeric_forensics.json
  +-- source_data_profile.json      (only if selected optional lane is executable)
  +-- source_data_findings.json     (only if selected optional lane is executable)
  +-- source_data_pair_forensics.json (only if selected optional lane is executable)
  +-- exact_image_duplicates.json
  +-- vlm_triage_selected.json  (currently reused or skipped)
  |
  v
+-----------------------------+
| visual panel evidence       |
| ELIS YOLOv5 adapter         |
+-----------------------------+
  |
  +-- canonical figure_evidence.json
  +-- panel_evidence.json
  +-- YOLOv5 panel extraction (MAX_PANELS_PER_FIGURE = 12)
  |
  v
+-----------------------------+
| AgentInvestigationPlanner   |
| agent_mode != off           |
| AgentStepRunner + context   |
| pack -> tool actions        |
+-----------------------------+
  |
  +-- validates deterministic tool_id via Tool Registry
  +-- writes context_pack_investigation_plan.json and logs/*.log
  +-- writes agent_investigation_plan_round_XX.json
  +-- writes investigation_rounds.jsonl
  +-- writes investigation/round_XX/action_YY artifacts
      e.g. image_similarity_candidates.json
      e.g. visual_copy_move.json when visual.copy_move is selected
  |
  v
+-----------------------------+
| visual finding pipeline     |
+-----------------------------+
  |
  +-- consumes panel_evidence + exact duplicates + optional visual_copy_move + optional dHash outputs
  +-- writes image_relationships.json
  +-- writes visual_findings.json
  +-- renders visual evidence package in HTML/Web
  +-- ELIS RootSIFT / TruFor / CBIR adapters are planned extensions
  |
  v
+-----------------------------+
| agent_review                |
| when agent_mode=review/full |
| AgentStepRunner + context   |
| pack -> JSON schema         |
+-----------------------------+
  |
  +-- writes agent_review.json
  +-- writes context_pack_review.json and logs/*.log
  +-- candidate claims
  +-- finding reviews
  +-- manual review tasks
  |
  v
+-----------------------------+
| static audit role layer     |
| when agent_mode=review/full |
| role-specific context packs |
+-----------------------------+
  |
  +-- ClaimExtractor -> agent_claim_extractor.json
  +-- SourceDataAuditor -> agent_source_data_auditor.json
  +-- JudgeAgent -> agent_judge.json
  +-- context_pack_<role>.json and logs/*.log
  +-- reserved roles -> skipped trace JSON
  +-- writes agent_traces/*.json
  |
  v
+-----------------------------+
| generate_report             |
+-----------------------------+
  |
  +-- final_audit_report.md
  +-- final_audit_report.html
  +-- audit_run_manifest.json
  +-- static_audit_bundle.json
  +-- agent_traces/
```

### 图像产物清单与必要性

`audit-paper` 的视觉取证管线会产生四类图像产物。以下为 paper1（257 figures）的实际测量：

| 目录 | 大小 | 文件数 | 内容 | 必要性 |
|---|---|---|---|---|
| `visual/images/` | 7.7 MB | 261 | MinerU 提取的原始 figure 图片 | ✅ **必须** — 所有视觉工具的源数据 |
| `panels/` | ~24 MB | ~811 | YOLOv5 panel 裁剪图（每图 1–12 个 panel） | ✅ **必须** — HTML 报告展示 + copy-move 检测输入 |
| `tru_for/` | ~5 MB | ~66 | TruFor 伪造热力图（仅保留 `is_suspicious=True` 的图） | ⚠️ **按需** — skip-only 模式，每张保留 pred_map + conf_map |
| `provenance/` | 0 MB | 0 | RootSIFT 验证中间数据 | ❌ **无 edges 时不生成** — 0 edges 时自动清理 |

**设计决策**：

- **Panel 裁剪上限**：`MAX_PANELS_PER_FIGURE = 12`。YOLOv5 会将网格图（空间转录组 4×10）和 blot montage 过度拆分为 20–40 个 "panel"，实际应为 1 张整图。超过上限时退回 `whole_figure_fallback`。
- **TruFor 瘦身**：非 suspicious 图的 pred_map / conf_map 在推理完成后立即删除。
- **Provenance 按需生成**：embedding 预筛选 → RootSIFT 验证 → 0 edges 时清理中间数据。避免为无相似图的论文保留无用的 RootSIFT 输出。
- **Panel 目录清理**：orchestrator 在 panel extraction 重跑前清理 `panels/` 目录，防止旧 run 的残留文件（orphaned crops）积累。

**典型总量**：一份 250 图论文的视觉产物约 **37 MB**（7.7 + 24 + 5 MB）。

## audit-paper 状态机 / State Machine

The state machine below governs the step-by-step execution order of `audit-paper`. Each node represents a pipeline stage; transitions depend on agent mode, artifact availability, and command exit codes.

```text
START
  |
  v
PARSE_ARGS
  |
  v
DISCOVER_INPUTS
  |
  +-- no PDF ---------------------------> FAILED_EXCEPTION
  |
  v
CREATE_WORKDIR
  |
  +-- fresh=true -> SAFE_REMOVE_WORKDIR
  |
  v
MATERIAL_INVENTORY
  |
  +-- scans paper_dir excluding paper PDF
  +-- writes material_inventory.json
  +-- classifies xlsx/csv/raw/image/archive/supplement materials
  |
  v
AGENT_MATERIAL_PLAN?
  |
  +-- agent_mode != off
  |      |
  |      +-- opencode ok -----------> status=ran
  |      +-- opencode/schema fail --> status=warning + deterministic fallback
  |
  +-- agent_mode off --------------> deterministic fallback
  |
  v
AGENT_PLAN?
  |
  +-- agent_mode in plan/full
  |      |
  |      +-- opencode ok -----------> status=ran
  |      +-- opencode/schema fail --> status=warning
  |
  +-- agent_mode off/review -------> skip plan
  |
  v
MINERU
  |
  +-- outputs exist and force=false -> status=reused
  +-- token missing and no outputs -> status=skipped
  +-- command ok ------------------> status=ran
  +-- command/output fail ---------> status=failed
  |
  v
PDF_DERIVED_STEPS
  |
  +-- full.md exists -> evidence_ledger + numeric_forensics
  +-- full.md missing -> both skipped
  |
  v
SOURCE_DATA_STEPS
  |
  +-- selected source_data_xlsx root valid -> profile -> findings
  +-- no selected executable lane -> skipped
  +-- selected root invalid/outside paper_dir -> skipped
  +-- command/output fail -> status=failed
  |
  v
IMAGE_DUPLICATE_CHECK
  |
  +-- images dir exists -> exact duplicate run/reuse/fail
  +-- images dir missing -> skipped
  +-- image similarity is optional and may be selected by AgentInvestigationPlanner
  |
  v
VISUAL_PANEL_EVIDENCE
  |
  +-- images dir exists -> visual_evidence.json + panel_evidence.json
  +-- extraction emits no panel -> whole-figure fallback panel + limitation
  +-- images dir missing -> skipped
  +-- ELIS YOLOv5 adapter (MAX_PANELS_PER_FIGURE = 12)
  |
  v
AGENT_INVESTIGATION?
  |
  +-- agent_mode != off
  |      |
  |      +-- up to 3 rounds of opencode investigation planning
  |      +-- planner selects only deterministic agent_selectable Tool Registry entries
  |      +-- invalid/duplicate/missing-dependency actions -> recorded as rejected/skipped
  |      +-- accepted actions -> orchestrator executes and writes investigation_rounds.jsonl
  |
  +-- agent_mode off --------------> skipped
  |
  v
VISUAL_FINDING_PIPELINE
  |
  +-- consumes panel_evidence + exact duplicates + optional visual_copy_move + optional dHash outputs
  +-- writes image_relationships.json and visual_findings.json
  +-- ELIS TruFor/CBIR outputs are not yet stable inputs
  |
  v
VLM_TRIAGE
  |
  +-- existing artifact -> reused
  +-- otherwise -> skipped
  |
  v
AGENT_REVIEW?
  |
  +-- agent_mode in review/full
  |      |
  |      +-- opencode ok -----------> status=ran
  |      +-- opencode/schema fail --> status=warning
  |
  +-- agent_mode off/plan ---------> skip review
  |
  v
AGENT_ROLES?
  |
  +-- existing successful role trace and force=false -> status=reused
  +-- agent_mode in review/full -> ClaimExtractor -> SourceDataAuditor -> JudgeAgent
  +-- opencode ok -----------> trace status=ran
  +-- opencode/schema fail --> step status=warning, trace status=failed
  +-- reserved roles --------> trace status=skipped
  |
  v
GENERATE_REPORT
  |
  v
WRITE_MANIFEST
  |
  +-- any status=failed -> EXIT 1
  +-- no failed steps  -> EXIT 0
```

状态含义 / Step status values：

- `ran`：本轮真实执行成功。/ Genuinely executed and succeeded in this run.
- `reused`：目标产物已存在且未指定 `--force`。/ Target artifact already exists and `--force` was not specified.
- `skipped`：前置材料或能力缺失，跳过但不视为失败。/ Prerequisite material or capability missing — skipped but not treated as a failure.
- `warning`：Agent 失败或输出不合规，降级继续确定性报告。/ Agent failed or produced non-compliant output — degraded gracefully, deterministic reporting continues.
- `failed`：确定性命令失败或预期产物缺失，最终进程返回 1。/ Deterministic command failed or expected artifact is missing — final process exits with code 1.

当前 `audit-paper` 的真实 Agent role 层顺序执行 3 个角色：`ClaimExtractor`、`SourceDataAuditor`、`JudgeAgent`。其余 role 先写入 `skipped` trace，占位给后续并行 subagent 和视觉/数字/数学/领域复核扩展。

The Agent role layer in `audit-paper` currently executes three roles in sequence: `ClaimExtractor`, `SourceDataAuditor`, and `JudgeAgent`. Remaining roles are written as `skipped` traces for now, reserving slots for future parallel sub-agents and visual, numerical, mathematical, and domain-specific review extensions.

`final_audit_report.html` 是当前老板 demo 的优先展示形态：单文件静态 HTML，突出本 case 结论、Top-N priority findings、证据定位、良性解释、人工复核动作和 role trace。Markdown 报告继续保留作为兼容输出。

`final_audit_report.html` is the primary deliverable for executive demos: a self-contained static HTML file that highlights the case verdict, Top-N priority findings, evidence anchoring, benign explanations, manual review actions, and role traces. The Markdown report is retained as a compatible fallback output.

## Web P1 数据层

Web P1 的结构化状态由 SQLAlchemy 管理。部署和 Docker 开发环境应通过 `VERITAS_DATABASE_URL` 指向 PostgreSQL / pgvector；非 Docker 本地开发由 `make web-backend` 显式启用 PGlite in-memory PostgreSQL-compatible server（`VERITAS_ENABLE_PGLITE=1`）。如果既没有 `VERITAS_DATABASE_URL`，也没有显式启用 PGlite，Web 数据层会启动失败；不再回退到 `web_data/veritas_web.sqlite3`。`web_data/` 只保留用户上传输入和运行目录等大文件/目录型内容；case、run、event、investigation、review decision、tool catalog 和 embedding metadata 都存入数据库。它与 `outputs/`（审计引擎产物目录）是两个独立概念：

```text
web_data/
└── cases/
    └── <case_id>/
        ├── inputs/          # 用户上传的论文 PDF 和 source data 文件
        └── runs/
            └── <run_id>/    # 预留给运行相关文件；结构化 run/event 状态在 DB 中
```

数据流关系：

| 前端操作 | API | 写入位置 |
|---|---|---|
| 创建 case | `POST /api/cases` | DB `cases` 表，并创建 `web_data/cases/<id>/` |
| 上传输入 | `POST /api/cases/<id>/inputs` | `web_data/cases/<id>/inputs/` |
| 启动审查 | `POST /api/cases/<id>/runs` | DB `runs` / `run_events` 表 |
| 查看调查记录 | `GET /api/cases/<id>/investigations` | DB 优先，兼容读取 `outputs/.../investigation/` |
| 保存人工复核决策 | `POST /api/cases/<id>/review-items/<ref>/decision` | DB `review_decisions` 表 |
| 查看产物 | `GET /api/cases/<id>/artifacts` | 读取 `outputs/`（通过 `run.workdir` 桥接） |
| 查看报告 | `GET /api/cases/<id>/report/html` | 读取 `outputs/<case_id>/.../final_audit_report.html` |

数据库中的 `AuditRunRecord.workdir` 字段桥接 Web 状态和审计产物：DB 记录"哪个 case 触发了哪次 run"，`outputs/` 存放"这次 run 产出了什么"。

存储职责边界：

| 存储位置 | 当前用途 | 备注 |
|---|---|---|
| PostgreSQL / pgvector | Web 结构化状态、人工复核决策、调查记录、工具目录、embedding metadata | Docker dev 使用 `veritas-pg-dev`；生产使用 `veritas-postgres` |
| `web_data/cases/<case_id>/inputs/` | 用户上传的论文 PDF、Source Data、补充材料等原始输入 | 由 `CaseStore.write_input()` 写入，不作为结构化状态源 |
| `web_data/cases/<case_id>/runs/` | 预留给 Web 运行相关文件 | run/event 状态仍以数据库为准 |
| `outputs/<case_id>/research-integrity-audit/` | `audit-paper` 生成的证据、manifest、报告和视觉产物 | 通过 DB 中的 `runs.workdir` 与 Web case/run 关联 |

开发和测试的目标策略是尽量保持 PostgreSQL 语义一致。优先级为：真实 PostgreSQL/pgvector（Docker dev、集成测试）> PGlite in-memory PostgreSQL-compatible backend（轻量单测和快速开发）。不要依赖 SQLite 特有行为作为 Web 数据层契约；新增 schema、约束、JSON 字段、embedding metadata 或事务行为时，应按 PostgreSQL 语义设计和验证。SQLite 只允许作为独立认证用户库或历史迁移源使用，不再作为 Web case/run/event 状态存储。

启用 `bearer` 或 `basic` 鉴权后，所有 case-scoped API 都必须先通过 `CaseRecord.owner == auth_context.user_id` 校验。该校验不只保护 `GET /api/cases/<id>`，也保护输入上传、启动 run、读取 run/events、artifact 列表、单个 artifact 和 HTML 报告，避免知道 `case_id` 后直接读取子资源。

## 常用命令

Python 环境由 `uv` 管理，根目录 `Makefile` 封装了常用本地入口。首次进入或依赖变更后先同步环境：

```bash
make sync
```

### 本地开发环境一键启停

开发阶段使用 `scripts/dev.sh` + `docker-compose.dev.yml` 管理本地服务。架构决策：

| 组件 | 运行位置 | 理由 |
|---|---|---|
| PostgreSQL (pgvector) | Docker 容器 | 数据库状态隔离，volume 持久化 |
| Backend (Python + PyTorch + CUDA + opencode) | Docker 容器 | GPU 环境复现；代码挂载热重载 |
| Vite 前端 | 宿主机 | HMR 秒级刷新，无需重建镜像 |

**打进镜像的**（变化极少，Docker 层缓存）：CUDA + Python + PyTorch runtime、pip 依赖、opencode CLI。

**运行时挂载的**（频繁变化）：代码（`./ → /workspace`，uvicorn --reload）、outputs/、web_data/、models/（模型权重 ~1GB+）。

端口刻意避开生产服务：

| 服务 | 端口 | 说明 |
|---|---|---|
| PostgreSQL | 5433 | Veritas 专用，不碰生产 5432 |
| FastAPI 后端 | 8765 | Backend 容器 |
| Vite 前端 | 5173 | 宿主机 HMR |

```bash
# 一键启动（首次会构建镜像 ~5 分钟，后续秒级）
./scripts/dev.sh up

# 重建镜像（pyproject.toml/uv.lock 变更后）
./scripts/dev.sh build

# 查看状态
./scripts/dev.sh status

# 查看日志
./scripts/dev.sh logs

# 一键停止（PG 数据保留）
./scripts/dev.sh down

# 重置数据库（清空数据重来）
docker compose -f docker-compose.dev.yml down -v && ./scripts/dev.sh up
```

日常开发循环：改代码 → 浏览器自动刷新（Vite HMR + uvicorn --reload 双热重载）。

> **前提**：宿主机需要 Docker + NVIDIA GPU driver。模型权重需提前放到 `models/` 目录（`make download-models` 或手动下载）。

### 容器架构

Veritas 有两套 Docker 编排配置：开发环境（`docker-compose.dev.yml`）和生产环境（`docker-compose.yml`）。两套配置都是 **2 个容器**（后端 + 数据库），前端处理方式不同。

#### 开发环境

```bash
docker compose -f docker-compose.dev.yml up
```

| 容器 | 镜像 | 用途 | 运行用户 |
|---|---|---|---|
| `veritas-backend-dev` | `veritas-backend` | 后端服务（热重载） | root |
| `veritas-pg-dev` | `pgvector/pgvector:pg16` | PostgreSQL 数据库 | postgres |

**前端**：宿主机上的 Vite dev server（不是容器），监听 `localhost:5173`，`/api` 请求代理到 `backend:8765`。

**架构特点**：
- 后端以 root 运行，简化 bind mount 权限处理
- 代码通过 bind mount 挂载到 `/workspace`，uvicorn --reload 热重载
- outputs/web_data 通过 bind mount 挂载，宿主机可直接观察产物

#### 生产环境

```bash
docker compose -f docker-compose.yml up
```

| 容器 | 镜像 | 用途 | 运行用户 |
|---|---|---|---|
| `veritas-web` | `veritas` | 后端服务 + 前端静态文件 | veritas (UID 1000) |
| `veritas-postgres` | `pgvector/pgvector:pg16` | PostgreSQL 数据库 | postgres |

**前端**：在 Dockerfile 多阶段构建时打包进后端镜像，由后端直接提供静态文件服务。

**架构特点**：
- 前端静态文件在构建时打包进镜像，不需要独立的前端容器
- 后端以非 root 用户 `veritas` 运行，符合最小权限原则
- 数据通过 `/data/veritas/` 挂载，与宿主机文件权限需要对齐 UID

#### UID 映射与 Bind Mount

生产环境中，如果后端容器以 `veritas` 用户（UID 1000）运行，而宿主机挂载目录的 owner 是不同 UID（如 1047），会导致权限问题。解决方案是构建时传入宿主机 UID：

```bash
# 构建镜像（自动传入当前用户 UID/GID）
make docker-build

# 验证容器内用户
docker run --rm veritas:latest id
# 输出：uid=1047(veritas) gid=1048(veritas) groups=1048(veritas)
```

`make docker-build` 封装了 `--build-arg USER_UID=$(id -u) --build-arg USER_GID=$(id -g)`，确保容器内 UID 与宿主机一致，bind mount 无权限问题。

#### 镜像列表

| 镜像 | 大小 | 用途 | 构建方式 |
|---|---|---|---|
| `veritas:latest` | ~6.9GB | 生产环境后端 + 前端 | `make docker-build`（传入 UID/GID） |
| `veritas-backend:latest` | ~12.5GB | 开发环境后端（含 CUDA + PyTorch） | `docker compose -f docker-compose.dev.yml build` |
| `pgvector/pgvector:pg16` | ~250MB | PostgreSQL 数据库 | 官方镜像 |

#### 架构图

```text
┌─────────────────────────────────────────────────────────┐
│ 开发环境                                                 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  宿主机                                                  │
│  ├─ Vite dev server (localhost:5173)                    │
│  │   └─ /api/* ──────────┐                              │
│  │                       │ 代理                         │
│  ├─ Docker               ▼                              │
│  │   ├─ backend:8765 ◄──┘                               │
│  │   │   └─ FastAPI + 热重载（root 运行）                │
│  │   └─ postgres:5432                                   │
│  │       └─ PostgreSQL + pgvector                       │
│  │                                                      │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ 生产环境                                                 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Docker                                                 │
│  ├─ veritas-web:8765 → 映射到宿主机 :80                 │
│  │   ├─ FastAPI 后端（veritas 用户运行）                 │
│  │   └─ 前端静态文件（/build/dist）                      │
│  └─ postgres:5432                                       │
│      └─ PostgreSQL + pgvector                           │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

确定性预检查：

```bash
make precheck
```

运行轻量 manifest demo：

```bash
make run
```

渲染报告：

```bash
make report
```

运行论文审查 demo：

```bash
make audit PAPER_DIR=<paper_dir> CASE_ID=<case_id>
```

推荐先打开 `outputs/<case_id>/research-integrity-audit/final_audit_report.html` 做内部 demo。`--agent-mode full` 当前仍可能受 `agent_plan` JSON 输出不稳定影响。`audit-paper` 进度输出写入 `stderr`，最终 summary JSON 仍写入 `stdout`；需要机器消费进度时使用 `--progress jsonl`，需要安静运行时使用 `--progress off`。MinerU 子进程的 `state/pages` 输出会被转发为 `OUT mineru` 进度行。

只跑确定性链路：

```bash
make audit-off PAPER_DIR=<paper_dir> CASE_ID=<case_id>
```

### Agent Mode 四种取值

`audit-paper` 通过 `--agent-mode` 控制 opencode Agent 的参与程度。Makefile 默认 `AGENT_MODE ?= review`。

| Mode | Agent Plan<br>(InvestigationPlanner) | Agent Review<br>(agent_review) | Role Layer<br>(Claim/SDA/Judge) | 典型场景 |
|---|---|---|---|---|
| `off` | ❌ | ❌ | ❌ | 纯确定性管线；无需 LLM；调试 / CI |
| `plan` | ✅ | ❌ |  | 只让 Agent 做调查计划，不做 review |
| `review` |  | ✅ | ✅ | **默认**：跳过 plan，直接 review + role layer |
| `full` | ✅ | ✅ | ✅ | 完整 Agent 流程：plan → 调查 → review → role layer |

`full` 模式需要 opencode + LLM API 配置完成；`review` 模式可跳过 plan 步骤直接运行结构化复核。`audit-off` 等价于 `--agent-mode off`。

从零重跑并禁止复用既有 MinerU 产物：

```bash
make audit-fresh PAPER_DIR=<paper_dir> CASE_ID=<case_id>
```

启动 Web P1 后端（默认监听 `127.0.0.1:8765`）：

```bash
make web-backend
```

如果遇到 `OSError: [Errno 98] Address already in use`，说明有旧进程仍占用 8765 端口：

```bash
lsof -i :8765        # 找到占用进程的 PID
kill <PID>           # 终止旧进程后重新启动
```

启动 Web P1 前端：

```bash
make web-install
make web-frontend
```

打开 `http://127.0.0.1:5173`。Vite 会把 `/api` 代理到 `http://127.0.0.1:8765`。如果先在 `web/frontend` 执行 `npm run build`，Python backend 会在 `web/frontend/dist` 存在时托管构建产物。

### 运行时诊断

跑 audit 之前先检查环境就绪状态：

```bash
./scripts/diag.sh           # 彩色终端输出
./scripts/diag.sh --json    # JSON 格式（供机器消费）
```

Web API 同样提供诊断端点：

```bash
curl http://127.0.0.1:8765/api/diag
```

诊断覆盖：PostgreSQL / Docker / GPU / opencode 容器 / Python 依赖 / 模型权重 / Docker 镜像 / 环境变量 / 文件系统。`critical` 级别问题会阻断 audit 运行，`warning` 级别表示部分功能不可用（如 SSCD 模型缺失时 embedding 功能跳过）。

## 环境依赖

### opencode（Agent 角色层，必需）

Veritas 是 agent 驱动的应用，opencode 是核心依赖。opencode CLI 已预装在 Backend 容器中，无需额外安装。

`scripts/opencode-docker.sh` wrapper 通过 `docker compose exec -T backend opencode ...` 在容器内调用。后端通过 `OPENCODE_BIN` 环境变量指向 wrapper。`dev.sh up` 自动设置此变量。

**备选：直接安装在宿主**

如果不用 Docker 跑 Backend（例如纯 CLI 模式）：

```bash
npm install -g opencode-ai
# 或
curl -fsSL https://opencode.ai/install | bash
```

然后设置 `OPENCODE_BIN=opencode`（或不设，默认就是 PATH 中的 `opencode`）。

**优先级**：`params.opencode_bin`（Web API）> `$OPENCODE_BIN` 环境变量 > 默认值 `"opencode"`。

### MinerU（PDF 解析）

PDF 解析依赖 MinerU API，通过 `MINERU_API_TOKEN` 环境变量提供 token。没有 token 时 MinerU 步骤会被 `skipped`，后续依赖 PDF 解析的步骤（evidence_ledger、numeric_forensics 等）也会跳过。

## 环境变量

不要把密钥写入 git。

```bash
DASHSCOPE_API_KEY=...
MINERU_API_TOKEN=...
```

`scripts/run_paper_audit.py` 默认会读取仓库根目录 `.env`，但 `.env` 必须保持未提交。

## Authentication

Veritas Web 后端支持三种认证模式，通过环境变量 `VERITAS_AUTH_MODE` 切换。默认模式为 `none`（无认证），适合本地开发和内网部署。生产部署建议启用 `bearer`（对接主产品 JWT）或 `basic`（独立用户名密码）。

### 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `VERITAS_AUTH_MODE` | 认证模式：`none`、`bearer`、`basic` | `none` |
| `VERITAS_JWT_SECRET` | Bearer 模式下 JWT 签名密钥（与主产品共享） | 空 |
| `VERITAS_JWT_ISSUER` | Bearer 模式下 JWT 签发者（`iss` claim） | `veritas` |
| `VERITAS_USERS_DB` | Basic 模式下 SQLite 用户数据库路径 | `web_data/users.db` |

### 两种部署模式

**嵌入模式**：Veritas Web 作为主产品（如 gin-blog）的子服务，共享 JWT 密钥。设置 `VERITAS_AUTH_MODE=bearer` 和 `VERITAS_JWT_SECRET` 即可验证主产品签发的 token。

**独立模式**：Veritas Web 独立运行，使用自带的 Basic Auth 用户管理。设置 `VERITAS_AUTH_MODE=basic`，然后用 CLI 创建用户。

### 用户管理 CLI

当 `VERITAS_AUTH_MODE=basic` 时，使用以下命令管理用户：

```bash
# 添加用户（交互式输入密码）
PYTHONPATH=. python -m web.backend.veritas_web.cli add-user alice --email alice@lab.org --roles admin,operator

# 添加用户（非交互式）
PYTHONPATH=. python -m web.backend.veritas_web.cli add-user bob --password secret123 --roles operator

# 列出所有用户
PYTHONPATH=. python -m web.backend.veritas_web.cli list-users

# 删除用户
PYTHONPATH=. python -m web.backend.veritas_web.cli delete-user bob

# 修改密码
PYTHONPATH=. python -m web.backend.veritas_web.cli change-password alice

# 指定自定义数据库路径
PYTHONPATH=. python -m web.backend.veritas_web.cli --db /path/to/users.db list-users
```

用户数据存储在 SQLite 数据库中（路径由 `VERITAS_USERS_DB` 指定），密码使用 bcrypt 哈希存储。

### 认证流程

每个 API 请求在路由分发前先经过 `_authenticate()`：

1. `none` 模式：直接设置 `auth_context = {user_id: "operator", roles: ["admin"]}`。
2. `bearer` 模式：从 `Authorization: Bearer <token>` 头提取 JWT，验证 HS256 签名、`iss`、`exp`，并要求非空字符串 `userId` 作为 `auth_context.user_id`；`userName` 只进入 metadata，不作为授权依据。
3. `basic` 模式：从 `Authorization: Basic <base64>` 头提取用户名密码，查询 SQLite 并验证 bcrypt 哈希。

认证失败时返回 `401 Unauthorized`；Basic 模式额外返回 `WWW-Authenticate: Basic realm="Veritas"` 头。

`CaseStore` 的方法按 `user_id` 隔离数据：每个用户只能看到和操作自己的 case，跨用户访问返回 `403 Forbidden`。Web 路由层通过 `_require_case_access()` 对所有 case 子资源复用这条规则，包括 `/runs`、`/events`、`/artifacts`、`/report/html` 和 `/inputs`。

## 测试

```bash
make test
make lint-python
```

当前测试套件包含 446 个测试用例（uv 环境 Python 3.12），覆盖单测、集成测试和 e2e 测试。pytest 只收集本仓 `tests/`，不会扫描 `third_party/` 上游仓库测试。`ruff` 作为 `uv` dev 依赖管理，lint 默认排除 `engine/static_audit/upstream/` 上游镜像。
