# audit-paper 当前通用流程说明

更新时间：2026-06-15

本文描述当前 `audit-paper` 闭环的数据流和 Agent 参与位置，不绑定任何具体论文 case。

## 输入

```text
paper_dir/
  paper.pdf                 必需，当前默认选择目录下第一个 PDF
  Source Data / *.xlsx      可选，可能不存在
  CSV/TSV/raw/archive       可选，当前只进入材料清单和 unsupported materials
  supplementary files       可选，材料清单只做发现，不做结论
```

开发命令模板：

```bash
make sync
make audit-fresh PAPER_DIR=<paper_dir> CASE_ID=<case_id> AGENT_TIMEOUT_SECONDS=300
```

如果想复用已有 MinerU 解析产物，不要加 `--fresh --force`，并使用已有产物所在的同一个 `case_id`。

## 数据流

```text
CLI
  -> discover_pdf
  -> material_inventory.json
  -> agent_material_plan.json
  -> mandatory bootstrap
       -> MinerU PDF parse
       -> evidence_ledger.json
       -> numeric_forensics.json
       -> paperfraud_rule_matches.json
       -> exact_image_duplicates.json
       -> visual_evidence.json
       -> panel_evidence.json
  -> Source Data optional lane
       -> source_data_profile.json
       -> source_data_findings.json
       -> source_data_pair_forensics.json
       -> source_data_cross_sheet.json
  -> AgentInvestigationPlanner
       -> agent_investigation_plan_round_XX.json
       -> investigation_rounds.jsonl
       -> investigation/round_XX/action_YY/<tool artifact>
  -> visual finding pipeline
       -> image_relationships.json
       -> visual_findings.json
  -> agent_review.json
  -> ClaimExtractor / SourceDataAuditor / JudgeAgent
       -> context_pack_*.json
       -> logs/*.json
  -> static_audit_bundle.json
  -> final_audit_report.md
  -> final_audit_report.html
```

当前所有 opencode Agent 调用都通过 `AgentStepRunner` 进入：先由 `context_pack.py` 构建有边界的 `AgentContextPack`，再调用 opencode、抽取 JSON、做 schema validation、按错误类别重试并写入 `logs/*.json`。`engine/investigation/opencode_agent.py` 仍保留 legacy `AgentRunResult` adapter，保证 orchestrator 和现有报告消费侧不用一次性迁移。

## Mandatory Bootstrap

只要输入有 PDF，系统就尝试执行以下基础层：

- `mineru.parse_pdf`：生成 `full.md`、`images/`、`mineru_manifest.json`。
- `paper.evidence_ledger`：生成论文内容、表格、图片、caption 的结构化索引。
- `paper.numeric_forensics`：从 PDF 解析结果里提取数字取证线索。
- `paperfraud.rule_match`：对解析后的论文文本执行 PaperFraud 方法论规则匹配，生成复核提示。
- `image.exact_duplicates`：对 MinerU 抽取图片做字节级重复检查。
- `visual.panel_extraction`：生成 canonical `visual_evidence.json` 和 `panel_evidence.json`。当前是 first-party OpenCV/Canny/contour 启发式实现，失败时允许 whole-figure fallback panel，并写入 limitation。
- `visual.finding_pipeline`：聚合 exact duplicate、dHash、可选 copy-move 输出，生成 `image_relationships.json` 和 `visual_findings.json`。

这些步骤不由 Agent 决定是否跳过。MinerU 是远端服务，若接口断连，Veritas 侧会做 3 次尝试和退避等待，但不能保证远端服务一定可用。

## Optional Lane

Source Data 不再按固定目录名硬编码执行。

当前链路先生成 `material_inventory.json`，对提交目录中的文件做材料发现：

- XLSX/XLSM 结构化表格
- CSV/TSV 表格
- R/HDF5/MTX 等原始数据
- 图片、压缩包、补充 PDF
- 其他可能的数据材料

随后 `agent_material_plan` 基于材料清单选择 optional lane。当前可执行 lane 主要是：

```text
source_data_xlsx
  -> source_data.profile
  -> source_data.findings
  -> source_data.pair_forensics
```

CSV/TSV、raw data、archive 等材料会进入 `unsupported_materials`，不被伪装成已审查。

## ELIS-Style 图像取证内测扩展

当前代码已具备 canonical visual artifacts、OpenCV panel extraction、Agent-selectable ORB/SIFT copy-move、字节级重复和 dHash 近似候选。下一阶段内测路线决定借鉴 ELIS (Scientific Integrity System) 的完整图像取证栈，在 happy path 下替换或增强这些传统 CV 路径。

当前已落地数据流：

```text
MinerU images
  -> visual.panel_extraction
       -> visual_evidence.json
       -> panel_evidence.json
       -> panel crops
  -> AgentInvestigationPlanner
       -> may select visual.copy_move
       -> investigation/round_XX/action_YY/visual_copy_move.json
  -> visual.finding_pipeline
       -> image_relationships.json
       -> visual_findings.json
  -> HTML Visual Evidence Package
  -> Web Visual Forensics Gallery
```

目标数据流：

```text
MinerU images / ELIS pdf-extractor images
  -> canonical figure_evidence.json
  -> panel_extractor
       -> panel_evidence.json
       -> panel crops
  -> copy_move_detection / copy_move_detection_keypoint
       -> visual_findings.json
       -> masks / overlays
  -> TruFor
       -> trufor_findings.json
       -> heatmaps
  -> CBIR + Milvus
       -> image_relationships.json
       -> internal similarity graph
  -> AgentInvestigationPlanner
       -> selects follow-up visual tools and parameters
  -> HTML visual evidence package
       -> manual review checklist
```

边界：

- `figure_evidence` 是唯一 canonical 图像证据入口；后续 panel、mask、heatmap、CBIR match 都必须引用 canonical figure/panel id。
- ELIS 工具作为 Veritas adapter/tool 接入 Tool Registry，不直接把 ELIS FastAPI/Celery/MongoDB/Redis 主服务并入主链路。
- 图像取证工具输出只生成候选事实和人工复核任务，不自动形成最终诚信判定。
- 重型工具必须有超时、失败记录、artifact hash 和 limitations；单个工具失败不应阻断 Markdown/HTML 报告生成。
- TruFor、CBIR/Milvus、YOLOv5 panel-extractor 和 RootSIFT/MAGSAC copy-move 在 adapter、registry、fixture 和报告消费完成前，不是当前稳定输出。

## AgentInvestigationPlanner

`AgentInvestigationPlanner` 已接入 P0 最小闭环。它运行在 mandatory bootstrap 和 baseline Source Data 工具之后、`agent_review` 之前。

职责：

- 读取已有 artifacts 和 Tool Registry。
- 最多 3 轮生成后续调查 action。
- 每个 action 必须声明 `tool_id`、`params`、`hypothesis`、`depends_on_artifacts`、`expected_evidence_type`。
- Python orchestrator 校验工具是否为 `agent_selectable=True` 且 deterministic。
- 通过参数边界、artifact 依赖和重复 action 去重后才执行。

当前 Agent-selectable 工具第一版只复用已有确定性工具，例如：

- `image.similarity_candidates`
- `source_data.profile`
- `source_data.findings`
- `source_data.pair_forensics`
- `source_data.cross_sheet`
- `visual.copy_move`

ELIS-style 内测增强后，Agent-selectable visual tools 预计扩展为：

- `visual.panel_extraction` 的 ELIS YOLOv5 adapter 或独立 pdf/panel extraction tool。
- `visual.copy_move` 的 RootSIFT/MAGSAC 版本。
- `visual.copy_move_dense`。
- `visual.tru_for`。
- `visual.cbir_index` / `visual.cbir_search`。

追加调查输出不会覆盖 baseline artifacts，而是写入：

```text
workdir/investigation/round_XX/action_YY/
```

每个 action 的计划、校验、执行和产物记录写入：

```text
investigation_rounds.jsonl
```

HTML 报告中展示 `Agent Investigation Path` 摘要表，完整 JSONL 作为 artifact 链接。

## Agent Review 和 Role Layer

在 `--agent-mode review` 下，Agent 智能主要出现在以下位置：

1. `agent_material_plan`

- 读取 `material_inventory.json`。
- 通过 `context_pack_material_plan.json` 限定输入上下文。
- 选择可执行 optional lane。
- 标记 missing / unsupported materials。

2. `AgentInvestigationPlanner`

- 基于已有 artifacts 选择后续确定性调查工具。
- 只规划，不直接执行。
- 所有执行由 Python orchestrator 控制。
- 运行 trace 和 AgentStepRunner 日志写入 `logs/`，供失败复盘。

3. `agent_review`

- 读取结构化产物。
- 通过 `context_pack_review.json` 读取 bounded context，不直接吞全量 workdir。
- 生成 candidate claims、claim-to-source-data review、finding reviews、manual review tasks、report notes。

4. 三个真实 role Agent

- `ClaimExtractor`：抽取可核查技术 claim。
- `SourceDataAuditor`：审阅 Source Data findings 和 claim mapping。
- `JudgeAgent`：生成技术风险建议，不做最终诚信判定。

每个 role 都会生成 `context_pack_<role>.json`。后续需要把 `error_category`、`log_ref` 和 context pack provenance 更完整地并入 manifest 和 HTML 报告，而不是只保留在低层日志。

## Evidence Ledger

`evidence_ledger.json` 是 MinerU 解析产物的证据索引，不是最终强证据图。

它主要包含：

- `markdown.lines`：Markdown 行号、文本、类型提示。
- `tables/cells`：Markdown 表格、content blocks、middle blocks 中抽出的表和单元格。
- `figures/images/captions`：图片文件、图片引用、caption-like 文本。
- `ledger_items`：页面、文本行、表格、单元格、图片、caption 等统一证据条目。
- `indexes`：按 type、page、image path、markdown line、table label、figure label 建索引。

当前若 `*_middle.json` 缺失，定位主要依赖 `full.md` 行号，而不是可靠 PDF bbox/page 坐标。

## Claim-To-Source-Data

当前 claim-to-source-data 是两层结构：

1. 确定性 scaffolding

- `source_data_findings.py` 从 workbook/sheet 名推断 figure key。
- 在 `full.md` 中搜索对应 figure 引用。
- 抽附近句子作为 candidate claims。
- 将同一 workbook/sheet 的 findings 挂到 mapping 上。

2. Agent refined mapping

- `ClaimExtractor` 抽取更像 claim 的技术声明。
- `SourceDataAuditor` 基于确定性 findings 和 Agent claims 做更精炼的映射。
- `static_audit_bundle.json` 优先采用 Agent refined mapping；没有 Agent 输出时才回退到 deterministic scaffolding。

## 输出

核心输出：

- `audit_run_manifest.json`：本次运行步骤、状态、命令和产物路径。
- `static_audit_bundle.json`：结构化审查 bundle，后续报告和服务化入口应优先依赖它。
- `investigation_rounds.jsonl`：AgentInvestigationPlanner 每个 action 的计划、校验、执行和产物记录。
- `context_pack_*.json`：AgentStepRunner 的 bounded input context。
- `logs/*.json`：Agent 调用、错误分类、重试和 validation 记录。
- `final_audit_report.md`：Markdown 兼容报告。
- `final_audit_report.html`：老板 demo 优先展示报告。

HTML 报告展示 Top-N priority findings，不假设某个 case 固定只有 3 个重点发现。

## 当前边界

- `image_similarity_candidates` 当前是 optional investigation tool，不再是固定 baseline。
- `visual.copy_move` 当前是 optional investigation tool，不是固定 baseline。
- investigation 追加产物目前只展示在 `Agent Investigation Path` 和 artifact 链接中，尚未自动合并进 canonical finding 表。
- CSV/TSV Source Data 还未正式执行，只进入材料清单和 unsupported materials。
- ELIS-style YOLO/RootSIFT/TruFor/CBIR、vLLM/VLM 视觉初筛仍未接入稳定 pipeline；已作为内测 happy path 下一阶段目标。
- 代码执行型 runtime 审查尚未并入 `audit-paper` 主链路。

## 泛化约束

- 不把任何单一论文 case 的异常模式写入默认逻辑。
- 不把固定文件名前缀、论文标题、图号或 finding id 写入运行代码。
- demo fixture 可以用于验收，但不能成为常驻方法论或默认报告结构。
- 新增 case 时优先验证材料发现、optional lane 选择、Agent investigation path 和报告空态是否合理。
