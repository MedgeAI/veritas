# audit-paper Pipeline 说明

更新时间：2026-06-29

本文描述当前 `audit-paper` 的实际数据流、Agent 参与位置、真实 case 暴露的断点，以及下一版需要收敛的 pipeline contract。

2026-06-29 校准：报告生成已重构为 `report/` 子包（`generator.py`、`claims.py`、`evidence.py`、`findings.py`、`sections.py`）。新增 `report_id.py`（报告 ID 生成，格式 `VRT-YYYYMM-XXXXXX`）和 `verify_store.py`（公开验证数据存储）。前端已演进为三入口架构（client/ops/verify）。`orchestrator.py` 仍是 backward-compat shim。Tool Registry 当前 30 个 ToolDefinition，按 `ExecutionPhase` 四层分类：`MANDATORY_BASELINE` / `CONDITIONAL_BASELINE` / `AGENT_SELECTABLE` / `REPORT_ONLY`。

## 输入

```text
paper_dir/
  paper.pdf                 必需，当前默认选择目录下第一个 PDF
  *.xlsx / *.xlsm           可选，当前可进入 Source Data XLSX lane
  CSV/TSV/raw/archive       可选，当前只进入材料清单或 unsupported materials
  supplementary files       可选，材料清单只做发现，不直接形成结论
```

开发命令模板：

```bash
make sync
make audit-fresh PAPER_DIR=<paper_dir> CASE_ID=<case_id> AGENT_TIMEOUT_SECONDS=300
```

如果想复用已有 MinerU 解析产物，不要加 `--fresh --force`，并使用已有产物所在的同一个 `case_id`。

## 当前实际数据流

```text
CLI / Web runner / Celery worker
  -> discover_pdf
  -> material_inventory.json
  -> agent_material_plan.json

  -> mandatory bootstrap
       -> MinerU PDF parse
            -> mineru/full.md
            -> mineru/evidence_ledger.json
            -> visual/images/
       -> paper.numeric_forensics
            -> numeric/forensics.json
       -> paperfraud.rule_match
            -> numeric/paperfraud_rules.json
       -> image.exact_duplicates
            -> visual/exact_duplicates.json
       -> visual.panel_extraction
            -> visual/evidence.json
            -> visual/panel_evidence.json
            -> panels/<figure-id>/<panel>.png
       -> visual.image_quality
            -> visual/image_quality.json
       -> visual.tru_for (MANDATORY_BASELINE, skip-only without GPU)
            -> visual/forged_region_evidence.json
       -> visual.provenance_graph (MANDATORY_BASELINE)
            -> visual/provenance_graph.json

  -> Source Data conditional lane
       -> source_data/profile.json
       -> source_data/findings.json
       -> source_data/pair_forensics.json
       -> source_data/cross_sheet.json
       -> source_data/findings_verdict.json  (LLM 语义裁决)

  -> AgentInvestigationPlanner
       -> agent_investigation_plan_round_XX.json
       -> investigation/investigation_rounds.jsonl
       -> investigation/round_XX/ir_XX_aYYY/<tool artifact>
       -> optional: visual.copy_move / visual.copy_move_dense /
                    visual.overlap_reuse / image.similarity_candidates /
                    source_data.query / paperconan.numeric_forensics

  -> visual finding pipeline (REPORT_ONLY — 聚合已有 artifacts)
       -> visual/relationships.json
       -> visual/findings.json

  -> agent_review.json
  -> role layer
       -> ClaimExtractor
       -> SourceDataAuditor
       -> JudgeAgent
       -> agents/context_pack_<role>.json
       -> logs/*.log

  -> reports/static_audit_bundle.json
  -> reports/report_id.txt  (VRT-YYYYMM-XXXXXX)
  -> reports/verification_summary.json
  -> reports/audit_run_manifest.json
  -> reports/final_audit_report.md
  -> reports/final_audit_report.html
```

所有 opencode Agent 调用都应通过 `AgentStepRunner` 进入：先由 `context_pack.py` 构建有边界的 `AgentContextPack`，再调用 opencode、抽取 JSON、做 schema validation、按错误类别重试并写入日志。`engine/investigation/opencode_agent.py` 仍保留 legacy adapter，保证 orchestrator 和报告消费侧不用一次性迁移。

路径解析已提取到 `engine/static_audit/paths.py`（`resolve_artifact_path`、`artifact_path_candidates`、`existing_artifact_path`），消除 `orchestrator.py` 中的路径散落。

## 真实 case 反校准

历史 case（如 `case-20260616T154322Z-d693198d`）暴露的断点推动了以下改进：

### 跑通的部分

- MinerU、evidence ledger、material inventory、XLSX optional lane 能稳定产出结构化 artifact。
- Source Data consistency 方向有可保留价值：
  - `source_data/pair_forensics.json` 发现 row-offset、fixed-ratio、paired-ratio、duplicate-row-vector 等候选模式。
  - `source_data/cross_sheet.json` 发现跨 workbook / sheet 的重复列。
- AgentInvestigationPlanner 能写入调查计划和 `investigation_rounds.jsonl`，但工具可执行边界仍需收紧。

### 暴露的断点

- 旧产物的最终 HTML 未达到 Visual Evidence Package：`final_audit_report.html` 没有 `<img>`，没有 panel crop、copy-move overlay、TruFor heatmap、CBIR/provenance 图。当前 `engine/static_audit/html_report/_core.py` 已有 visual figure/finding/review queue 渲染，需重跑该 case 验证 report consumer。
- `visual.copy_move` 产生大量不可采信的视觉 finding：
  - 326 条 relationships 全部是 `copy_move_single`。
  - 高分 critical 多来自 `Graphs` 或 `panel_type=None`，例如 Kaplan-Meier 曲线被标为 critical copy-move。
  - overlay 路径大量复用，`copy_move_elis/single/a_mask.png` 可被多条 relationship 共用，finding 无法人工复核。
- canonical id 断裂：
  - dHash relationship 使用绝对图片路径作为 `source_panel_id` / `target_panel_id`。
  - cluster 的 `figure_ids` 可能被截成 `/workspace/.../research-integrity`，不是 `figure-content-*`。
- TruFor 没跑通：缺 `timm`，`visual/forged_region_evidence.json` 为 failed，0 forged regions。
- Agent-selectable 工具与实际 dispatch 不一致：
  - Agent 选择过 `visual.provenance_graph`、`paperconan.numeric_forensics`，但 investigation 记录中被标 unsupported。
  - 同时 orchestrator 又固定跑了 provenance graph，形成双重口径。
- Claim 链路需要回归保护：
  - 旧 `static_audit_bundle.claims` 中出现过工具 finding 句式，导致产物层看起来像 finding-to-finding。
  - 当前 `roles.py` 中 `ClaimExtractor` 只读取 `full.md` 和 `evidence_ledger.json`，不读取 Source Data / visual findings；该问题不再按当前 ClaimExtractor 代码缺陷处理。
  - 下一版需要重跑验证 bundle claims 选择逻辑，并补 validator/test 禁止工具 finding 进入 canonical claims。
- PaperFraud rule match 噪声较高：泛化 RCT/PRISMA/STROBE/Benford 等规则不能默认进入 Top consistency findings。

## Pipeline Contract

下一版 `audit-paper` 必须按以下 contract 收敛。

### 1. Canonical Visual Evidence

所有视觉工具都必须围绕同一套 canonical id：

```text
visual/evidence.json          figure_evidence
visual/panel_evidence.json    panel_evidence
visual/relationships.json     image_relationship
visual/findings.json          visual_finding
```

约束：

- `figure_id` 必须稳定，例如 `figure-content-0097`。
- `panel_id` 必须稳定，例如 `figure-content-0097-01`。
- 不允许把绝对图片路径写入 `source_panel_id` / `target_panel_id`。
- mask、overlay、heatmap、CBIR match 必须回链到 canonical figure/panel id。
- 无法回链 canonical id 的 relationship 只能进入 limitation 或 low-priority debug artifact，不得进入 high/critical finding。

### 2. Visual Finding Schema

`visual/relationships.json` 和 `visual/findings.json` 必须显式包含：

```text
relationship_type
finding_type
issue_category
scope
image_modality
risk_level
confidence
score
source_figure_id / source_panel_id
target_figure_id / target_panel_id
artifact_refs
evidence_refs
benign_explanations
manual_review_questions
```

推荐枚举：

```text
relationship_type:
  exact_duplicate
  near_duplicate
  copy_move_single
  copy_move_cross_panel
  copy_move_cross_figure
  forged_region
  cbir_similar

scope:
  same_panel
  same_figure
  cross_figure
  cross_file

image_modality:
  microscopy
  blot
  flow
  graph
  heatmap
  unknown
```

Graph / Kaplan-Meier / UMAP / boxplot / barplot 等统计图默认不能升级为 biological copy-move high/critical，除非有明确跨 panel 同源证据和可审 overlay。

### 3. Visual Evidence Package

HTML 报告必须消费 canonical visual artifacts，而不是只展示文字摘要。

Top visual finding 至少展示：

- source figure image。
- source/target panel crop。
- mask / overlay / matches / heatmap。
- figure id、panel id、caption excerpt。
- relationship type、score、risk basis。
- benign explanations。
- manual review question。

如果某次 run 的 HTML 中没有图片证据，则该产物只能称为 static summary，不能称为 Visual Evidence Package。当前代码已有视觉渲染入口，但必须用真实 case 和 fixture 回归证明它能消费 canonical visual artifacts。

### 4. Tool Registry 是唯一执行事实源

Agent、orchestrator、manifest、report 必须使用同一套 Tool Registry 事实。当前 Tool Registry 包含 30 个 `ToolDefinition`，按 `ExecutionPhase` 四层分类：

```text
MANDATORY_BASELINE    — 无条件执行（MinerU、evidence_ledger、numeric_forensics、
                        paperfraud_rule_match、exact_duplicates、panel_extraction、
                        image_quality、tru_for、provenance_graph）
CONDITIONAL_BASELINE  — 条件满足时执行（source_data.profile/findings/pair_forensics/
                        cross_sheet/verdict）
AGENT_SELECTABLE      — 仅在 Agent investigation rounds 中选择执行
REPORT_ONLY           — 消费已有 artifacts 生成报告（finding_pipeline、bundle、
                        render_markdown、render_static_html）
```

约束：

- AgentInvestigationPlanner 只能看到真实可执行的 `agent_selectable=True` 且 `deterministic=True` 的工具。
- context pack 中的 investigation tool catalog 必须与 orchestrator dispatch 表一致。
- registry 里存在但 dispatch 未实现的工具，不得暴露给 Agent。
- unsupported action 不能标 `validation_status=accepted`。
- 固定链路中执行的工具也必须在 registry 中有 execution phase、input/output artifact 和失败语义。

### 5. Claim-To-Source-Data

Claim 链路必须保持以下方向：

```text
paper text / caption
  -> paper-derived claim
  -> figure/panel/source-data mapping
  -> source data column-block / row-range
  -> deterministic recomputation or consistency finding
  -> matching / consistency / completeness finding
```

禁止方向：

```text
tool finding
  -> Agent rewrites finding as claim
  -> bundle.claims
```

角色边界：

- `ClaimExtractor`：只从论文正文、图注、表格标题抽取可核查 claim。
- `SourceDataAuditor`：把 paper-derived claim 映射到 workbook/sheet/column-block，并引用 deterministic findings。
- `JudgeAgent`：综合风险语言和人工复核任务，不做最终诚信判定。

## Mandatory Bootstrap

只要输入有 PDF，系统尝试执行以下基础层（`ExecutionPhase.MANDATORY_BASELINE`）：

- `mineru.parse_pdf`：生成 `mineru/full.md`、图片和 MinerU manifest。
- `paper.evidence_ledger`：生成论文内容、表格、图片、caption 的结构化索引。
- `paper.numeric_forensics`：从 PDF 解析结果里提取数字取证线索。
- `paperfraud.rule_match`：生成方法论 checklist 和复核提示；默认不进入 Top consistency findings。
- `image.exact_duplicates`：对 MinerU 抽取图片做字节级重复检查。
- `visual.panel_extraction`：生成 canonical `visual/evidence.json` 和 `visual/panel_evidence.json`。
- `visual.image_quality`：检测图片质量异常（uniform border、solid-color figures）。
- `visual.tru_for`：TruFor SegFormer-B2 伪造检测。需要 GPU；无 GPU 时整体 skipped。
- `visual.provenance_graph`：跨 figure 内容共享溯源图构建（recursive BFS expansion）。

`visual.finding_pipeline` 当前是 `REPORT_ONLY`——它消费已有 artifacts（panel_evidence、copy_move、exact_duplicates）聚合为 canonical relationships/findings，不在 bootstrap 阶段独立执行。

MinerU 是远端服务，若接口断连，Veritas 侧会做重试和退避等待，但不能保证远端一定可用。

## Optional Lane

Source Data 不再按固定目录名硬编码执行。

当前链路先生成 `material_inventory.json`，对提交目录中的文件做材料发现：

- XLSX/XLSM 结构化表格。
- CSV/TSV 表格。
- R/HDF5/MTX 等原始数据。
- 图片、压缩包、补充 PDF。
- 其他可能的数据材料。

随后 `agent_material_plan` 基于材料清单选择 optional lane。当前可执行 lane 主要是：

```text
source_data_xlsx
  -> source_data.profile
  -> source_data.findings
  -> source_data.pair_forensics
  -> source_data.cross_sheet
```

CSV/TSV、raw data、archive 等材料会进入 `unsupported_materials` 或 completeness limitation，不被伪装成已审查。

## ELIS-Style 图像取证路线

ELIS 是能力来源和架构参考，不是 Veritas 主服务。Veritas 不直接接入 ELIS FastAPI/Celery/MongoDB/Redis/Web UI；所有能力必须通过 adapter/tool、Tool Registry、canonical artifacts 和 report consumer 进入主链路。

### 当前能力状态

```text
MinerU images
  -> visual.panel_extraction
       -> visual/evidence.json
       -> visual/panel_evidence.json
       -> panel crops
  -> visual.image_quality
       -> visual/image_quality.json
  -> visual.tru_for (MANDATORY_BASELINE, GPU required)
       -> visual/forged_region_evidence.json
  -> visual.provenance_graph (MANDATORY_BASELINE)
       -> visual/provenance_graph.json
  -> AgentInvestigationPlanner
       -> may select image.similarity_candidates
       -> may select visual.copy_move
       -> may select visual.copy_move_dense
       -> may select visual.overlap_reuse
  -> visual.finding_pipeline (REPORT_ONLY)
       -> visual/relationships.json
       -> visual/findings.json
  -> final report
       -> HTML visual renderer in engine/static_audit/html_report/
```

TruFor 和 provenance graph 已提升为 `MANDATORY_BASELINE`。TruFor 需要 GPU（`timm` + SegFormer-B2 权重），无 GPU 时整体 skipped。copy-move（RootSIFT+MAGSAC++）仍是 optional investigation tool。SILA dense copy-move 和 overlap_reuse 是 Agent-selectable。

### 目标能力状态

```text
MinerU images / ELIS pdf-extractor images
  -> canonical figure_evidence
  -> ELIS-style panel_extractor
       -> panel_evidence
       -> panel crops
       -> panel quality / fallback reason
  -> keypoint copy-move
       -> cross-panel / intra-panel relationships
       -> unique masks / overlays / matches
  -> dense copy-move
       -> selected-panel investigation only
       -> dense masks / scores
  -> TruFor
       -> forged-region heatmaps
       -> model metadata / threshold / device
  -> CBIR / internal similarity
       -> candidate pairs
       -> similarity graph
  -> visual finding pipeline
       -> typed relationships
       -> typed visual findings
       -> review queue
  -> HTML Visual Evidence Package
       -> image evidence display
       -> human review checklist
```

## AgentInvestigationPlanner

`AgentInvestigationPlanner` 运行在 mandatory bootstrap 和 baseline Source Data 工具之后、`agent_review` 之前。

职责：

- 读取已有 artifacts 和 Tool Registry。
- 最多 3 轮生成后续调查 action。
- 每个 action 必须声明 `tool_id`、`params`、`hypothesis`、`depends_on_artifacts`、`expected_evidence_type`。
- Python orchestrator 校验工具是否为真实可执行的 `agent_selectable=True` 且 deterministic。
- 通过参数边界、artifact 依赖和重复 action 去重后才执行。

当前可选工具应严格来自 `tool_catalog_for_investigation()` 和实际 dispatch 交集。例如：

- `image.similarity_candidates`
- `source_data.profile`
- `source_data.findings`
- `source_data.pair_forensics`
- `source_data.cross_sheet`
- `source_data.query`（语义查询：compare_groups / extract_block / find_cross_group_reuse）
- `paperconan.numeric_forensics`（只有 dispatch 实现后才可暴露）
- `visual.copy_move`（RootSIFT+MAGSAC++ keypoint matching）
- `visual.copy_move_dense`（SILA dense features，需 Docker）
- `visual.overlap_reuse`（tile-level retrieval + geometric verification）
- `visual.tru_for`（MANDATORY_BASELINE，需 GPU，无 GPU 时 skip-only）
- `visual.provenance_graph`（MANDATORY_BASELINE，recursive BFS expansion）

追加调查输出不会覆盖 baseline artifacts，而是写入：

```text
workdir/investigation/round_XX/ir_XX_aYYY/
```

每个 action 的计划、校验、执行和产物记录写入：

```text
investigation/investigation_rounds.jsonl
```

HTML 报告应展示 `Agent Investigation Path`，但更重要的是把成功产出的 investigation artifacts 合并进 canonical finding/evidence 图。只展示路径摘要不等于审查闭环。

## Agent Review 和 Role Layer

在 `--agent-mode review` 下，Agent 智能主要出现在以下位置：

### 1. `agent_material_plan`

- 读取 `material_inventory.json`。
- 通过 `context_pack_material_plan.json` 限定输入上下文。
- 选择可执行 optional lane。
- 标记 missing / unsupported materials。

### 2. `AgentInvestigationPlanner`

- 基于已有 artifacts 选择后续确定性调查工具。
- 只规划，不直接执行。
- 所有执行由 Python orchestrator 控制。
- 运行 trace 和 AgentStepRunner 日志写入 `logs/`，供失败复盘。

### 3. `agent_review`

- 读取结构化产物。
- 通过 `context_pack_review.json` 读取 bounded context，不直接吞全量 workdir。
- 生成 paper-derived candidate claims、claim-to-source-data review、finding reviews、manual review tasks、report notes。

### 4. 三个 role Agent

- `ClaimExtractor`：抽取论文正文/图注中的可核查技术 claim。
- `SourceDataAuditor`：审阅 Source Data findings 和 paper-derived claim mapping。
- `JudgeAgent`：生成技术风险建议，不做最终诚信判定。

旧产物暴露的问题是 bundle claims 中出现过工具 finding 句式。当前 `ClaimExtractor` 角色输入已限定为论文文本和 evidence ledger，因此下一版重点是重跑验证 bundle claims 选择逻辑，并用 role schema / validator / regression test 禁止工具 finding 进入 canonical claims。

## Evidence Ledger

`evidence_ledger.json` 是 MinerU 解析产物的证据索引，不是最终强证据图。

它主要包含：

- `markdown.lines`：Markdown 行号、文本、类型提示。
- `tables/cells`：Markdown 表格、content blocks、middle blocks 中抽出的表和单元格。
- `figures/images/captions`：图片文件、图片引用、caption-like 文本。
- `ledger_items`：页面、文本行、表格、单元格、图片、caption 等统一证据条目。
- `indexes`：按 type、page、image path、markdown line、table label、figure label 建索引。

当前若 `*_middle.json` 缺失，定位主要依赖 `full.md` 行号，而不是可靠 PDF bbox/page 坐标。

## Source Data Pipeline

当前 Source Data 是 Veritas 最接近核心价值的证据层。

```text
source_data.profile
  -> workbook/sheet/cell/formula profile

source_data.findings
  -> duplicate columns
  -> fixed relationship
  -> formula-derived columns
  -> deterministic claim-to-source-data scaffolding

source_data.pair_forensics
  -> row-offset scalar multiple
  -> paired-ratio reuse
  -> duplicate-row-vector
  -> partial copy + rounding bias

source_data.cross_sheet
  -> cross workbook/sheet duplicate columns

source_data.verdict  (LLM 语义裁决, CONDITIONAL_BASELINE, deterministic=False)
  -> 对 source_data findings 做 true_positive / false_positive / uncertain 裁决
  -> 依赖 column context from XLSX files

source_data.query  (AGENT_SELECTABLE)
  -> 语义级确定性查询: compare_groups / extract_block / find_cross_group_reuse
```

后续增强重点：

- 对 high Source Data finding 建立 paper claim 映射。
- 从 sheet 级推进到 column-block / row-range 级。
- 对 paired design、design matrix、编号列、样本 ID、合法复用做误报排除。
- 对 duplicate-row-vector 的低宽度偶然匹配降权。

## Claim-To-Source-Data

当前 claim-to-source-data 应收敛为两层：

### 1. 确定性 scaffolding

- `source_data_findings.py` 从 workbook/sheet 名推断 figure key。
- 在 `full.md` 中搜索对应 figure 引用。
- 抽附近句子作为 candidate claims。
- 将同一 workbook/sheet 的 findings 挂到 mapping 上。

### 2. Agent refined mapping

- `ClaimExtractor` 抽取 paper-derived claim。
- `SourceDataAuditor` 基于 deterministic findings 和 paper-derived claims 做映射。
- `static_audit_bundle.json` 优先采用 paper-derived claim mapping；没有 Agent 输出时才回退到 deterministic scaffolding。

禁止把 deterministic finding 文本直接升级为 claim。

## 输出

核心输出：

- `reports/audit_run_manifest.json`：本次运行步骤、状态、命令和产物路径。
- `reports/static_audit_bundle.json`：结构化审查 bundle，后续报告和服务化入口应优先依赖它。
- `reports/report_id.txt`：报告 ID（格式 `VRT-YYYYMM-XXXXXX`），由 `engine/static_audit/report_id.py` 生成。
- `reports/verification_summary.json`：公开验证数据，由 `engine/static_audit/verify_store.py` 加载。
- `investigation/investigation_rounds.jsonl`：AgentInvestigationPlanner 每个 action 的计划、校验、执行和产物记录。
- `agents/context_pack_*.json`：AgentStepRunner 的 bounded input context。
- `logs/*.log`：Agent 调用、错误分类、重试和 validation 记录。
- `reports/final_audit_report.md`：Markdown 兼容报告。
- `reports/final_audit_report.html`：PI demo 优先展示报告。

HTML 报告必须按 issue category 分层：

```text
consistency   Source Data 内部一致性、可信视觉操控候选
matching      paper claim 与 source data / figure / result 不匹配
completeness  材料缺失、代码/环境/原始数据未提供
```

若某次 run 的视觉证据没有被图片 artifact 消费，HTML 只能展示 Source Data / textual summary，不能标榜 Visual Evidence Package。当前 renderer 已有视觉入口，但必须以重跑产物和回归测试证明。

## 当前边界

- `image_similarity_candidates` 当前是 optional investigation tool，不是固定 baseline。
- `visual.copy_move` 当前是 optional investigation tool（RootSIFT+MAGSAC++），不是固定 baseline。
- `visual.copy_move_dense`（SILA dense features）需要 Docker 环境，`AGENT_SELECTABLE`。
- `visual.overlap_reuse`（tile-level retrieval）当前是 `AGENT_SELECTABLE`。
- `visual.tru_for` 已提升为 `MANDATORY_BASELINE`；无 GPU 时整体 skipped，不刷重复错误。
- `visual.provenance_graph` 已提升为 `MANDATORY_BASELINE`。
- `visual.finding_pipeline` 是 `REPORT_ONLY`——消费已有 artifacts 聚合为 canonical findings。
- `visual.image_quality` 是 `MANDATORY_BASELINE`，检测 uniform border / solid-color figures。
- `source_data.verdict` 是 `CONDITIONAL_BASELINE`（LLM 语义裁决），`deterministic=False`。
- `source_data.query` 是 `AGENT_SELECTABLE`，提供语义级确定性查询。
- `paperconan.numeric_forensics` 是 `AGENT_SELECTABLE`（GRIM/GRIMMER 等）。
- investigation 追加产物目前仍需要显式合并进 canonical finding/evidence 图，不能只展示在 Agent Investigation Path。
- CSV/TSV Source Data 还未正式执行，只进入材料清单和 unsupported materials。
- ELIS-style panel/RootSIFT/TruFor adapters 已有入口；CBIR/Milvus 与 vLLM/VLM 视觉初筛仍未接入稳定 pipeline。
- 代码执行型 runtime 审查尚未并入 `audit-paper` 主链路。
- `engine/ground_truth/` 提供标注解析（`parser.py`）、claim-finding 映射（`mapper.py`）、PRD gap 分析（`gap_analyzer.py`）和过拟合防护（`anti_overfit.py`），用于验证 pipeline 输出质量，不是审查主链路。
- `engine/follow_up/` 生成 Follow-up 行动建议，通过 Web `ActionsPage` 展示。
- `engine/tasks/` 提供 Celery 异步任务路径（`audit_task.py`、`embedding_task.py`、`stale_run_watchdog.py`），生产部署使用。
- `engine/static_audit/report/` 子包负责报告数据聚合和渲染：`generator.py`（主入口 `generate_report`）、`claims.py`（claim 数据）、`evidence.py`（evidence 数据）、`findings.py`（finding 数据）、`sections.py`（报告章节构建）。
- `engine/static_audit/report_id.py` 生成报告 ID（格式 `VRT-YYYYMM-XXXXXX`）。
- `engine/static_audit/verify_store.py` 提供公开验证数据加载和 report_id 校验。
- 前端三入口架构通过 `utils/entrypoint.js` 分流：`client`（客户服务门户）、`ops`（运营后台）、`verify`（公开验证）。
- Client Report BFF（`/api/cases/{case_id}/client-report`）聚合认证等级、风险摘要、certainty layers、复核项等数据供客户服务门户消费。
- 公开验证接口（`/api/verify/{report_id}`）无需认证，外部用户可通过 report_id 查询认证状态。

## 下一版最低验收

下一次真实 case 至少满足：

- `final_audit_report.html` 在当前代码重跑后包含 Top visual findings 的图片、panel、overlay/heatmap，并有 report consumer 回归测试。
- `visual/relationships.json` 没有绝对路径形式的 panel id。
- Graph/Kaplan-Meier panel 不会进入 critical copy-move。
- 每条 high/critical visual finding 有唯一 artifact refs。
- TruFor 成功产出 heatmap，或明确整体 skipped，不刷重复错误。
- Agent investigation 里没有 unsupported action 被标 accepted。
- `static_audit_bundle.claims` 是论文 claim，不是工具 finding；该项通过 bundle/role 回归测试守住。
- Top priority findings 优先展示 Source Data consistency 和可审视觉证据。
- 所有正式 finding 有 evidence refs；没有 evidence refs 的规则只进入 checklist 或 limitations。

## 泛化约束

- 不把任何单一论文 case 的异常模式写入默认逻辑。
- 不把固定文件名前缀、论文标题、图号或 finding id 写入运行代码。
- demo fixture 可以用于验收，但不能成为常驻方法论或默认报告结构。
- 新增 case 时优先验证材料发现、optional lane 选择、Agent investigation path、canonical evidence 回链和报告空态是否合理。
