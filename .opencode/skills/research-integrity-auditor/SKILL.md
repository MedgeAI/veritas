---
name: research-integrity-auditor
description: Use for Veritas paper technical fact-checking with the local research-integrity-auditor toolbox: MinerU PDF parsing, evidence ledger construction, deterministic numeric forensics, source-data profiling/findings, image duplicate checks, and cautious claim-to-evidence review.
license: MIT
compatibility: opencode
metadata:
  project: veritas
  source: third_party/research-integrity-auditor
---

# Research Integrity Auditor Adapter

本 skill 是 Veritas 对 `third_party/research-integrity-auditor` 的 opencode 适配层。

在 Veritas 项目中，本 skill 不是可选提示词。`opencode.json` 会把它作为常驻 instructions 加载，确保临时启动的 opencode 也知道第三方工具箱、工具边界和 artifact 合约。

但产品主链路的流程一致性不依赖 opencode 是否“自觉触发 skill”。`veritas audit-paper` 内部由 Python orchestrator 和 Veritas Tool Registry 控制确定性工具执行；opencode 只输出结构化 plan/review JSON，不直接执行这些工具。

它只负责工具能力目录、输入变量、命令顺序和 artifact 合约。领域审查先验统一维护在：

```text
configs/methodology/
```

`configs/opencode/biomed-research-audit-methodology.md` 只是 opencode 常驻方法论索引。不要把生物医药/生物信息审查方法论复制进本 skill。需要新增领域规则时，先改 `configs/methodology/`；需要新增工具步骤时，先改 Veritas Tool Registry，再同步更新本 skill 的能力说明。

## 与 Veritas Tool Registry 的关系

当前 `audit-paper` 静态审查链路中的确定性工具以 `tool_id` 形式注册在：

```text
engine/tools/registry.py
```

核心 tool_id：

- `mineru.parse_pdf`
- `paper.evidence_ledger`
- `paper.numeric_forensics`
- `source_data.profile`
- `source_data.findings`
- `image.exact_duplicates`
- `agent.review`
- `report.render_markdown`

opencode Agent 可以在 `agent_plan` 中选择 tool_id 和填写参数，但只有 registry 允许的 tool_id 会被 Python orchestrator 执行。

## 什么时候使用

- 用户要求审查论文 PDF、图表、Source Data、实验数据表格或科研诚信风险。
- 用户要求把论文 claim 映射到可复核证据、代码、数据或结果文件。
- 用户要求对任意本地论文目录做 demo 前的技术复核。
- 用户提到 MinerU、PDF 解析、evidence ledger、numeric forensics、Source Data findings、图表溯源、claim mismatch。

## 依赖关系

- 项目规则：`AGENTS.md`
- opencode 路由：`configs/opencode/veritas-agent.md`
- 领域先验：`configs/methodology/`
- 方法论索引：`configs/opencode/biomed-research-audit-methodology.md`
- 维护拓扑：`configs/opencode/README.md`
- 第三方工具箱：`third_party/research-integrity-auditor/`

## 输入变量约定

优先根据用户本轮提供的论文目录、PDF、Source Data、代码仓库和输出目录设置变量。不要默认套用任何单一论文的异常模式。

`input/paper1` 只是 demo fixture，可用于验证流程是否跑通；除非用户明确指定它，否则不要把它当成默认审查对象。

推荐变量：

```bash
PROJECT_ROOT="/home/lzj/project/veritas"
PAPER_DIR="<user-provided-paper-dir>"
PAPER_PDF="<paper-pdf-path>"
SOURCE_DATA_DIR="<source-data-dir-or-empty>"
CODE_REPO_DIR="<code-repo-dir-or-empty>"
AUDITOR_ROOT="$PROJECT_ROOT/third_party/research-integrity-auditor"
CASE_ID="<case-id-derived-from-input>"
WORKDIR="$PROJECT_ROOT/outputs/$CASE_ID/research-integrity-audit"
```

示例 fixture：

```bash
PAPER_DIR="/home/lzj/project/veritas/input/paper1"
PAPER_PDF="$PAPER_DIR/Human HDAC6 senses valine abundancy to regulate DNA damage.pdf"
SOURCE_DATA_DIR="$PAPER_DIR/Source Data"
CASE_ID="paper1"
WORKDIR="/home/lzj/project/veritas/outputs/paper1/research-integrity-audit"
```

## 不可违反的规则

- 不判定论文造假，只报告技术事实、异常线索、证据强弱和人工复核建议。
- 不把 `DASHSCOPE_API_KEY`、`MINERU_API_TOKEN` 或其他 token 写入仓库、报告、日志或示例。
- MinerU token 必须从环境变量 `MINERU_API_TOKEN` 读取。
- 百炼 key 必须从环境变量 `DASHSCOPE_API_KEY` 读取。
- 能用确定性脚本完成的提取、统计、文件检查，不交给 LLM。
- LLM 只做不确定推断：claim 抽取、claim-to-artifact mapping、图表语义初筛、良性解释压力测试、报告措辞整理。
- VLM 输出只能作为初筛，不作为 primary evidence。
- 每条正式 finding 必须能追溯到页码、图表/表格编号、Markdown 行、content block、图片路径、表格行列、原始单元格、代码位置、命令或输出产物。

## 标准工具流程

优先使用 Veritas 的本地 orchestrator 跑第一阶段端到端：

```bash
python3 "$PROJECT_ROOT/cli/main.py" audit-paper "$PAPER_DIR" --case-id "$CASE_ID" --agent-mode full
```

该命令默认让 opencode 参与两个阶段：

- `agent_plan`：根据输入材料生成审查计划，并为确定性脚本填充参数。
- `agent_review`：读取确定性产物，生成 claim/finding 结构化复核和人工复核任务。

确定性脚本仍然负责 PDF 解析、统计、Source Data finding 和图片哈希检查。只跑确定性链路时使用：

```bash
python3 "$PROJECT_ROOT/cli/main.py" audit-paper "$PAPER_DIR" --case-id "$CASE_ID" --agent-mode off
```

该命令会复用已存在的 MinerU/VLM 产物；缺失时按下列步骤调用工具。若要求不复用 MinerU PDF 解析产物，使用 fresh run：

```bash
python3 "$PROJECT_ROOT/cli/main.py" audit-paper "$PAPER_DIR" --case-id "$CASE_ID" --fresh --force --agent-mode full
```

从零重跑外部 API 步骤前，必须先确认 `.env` 或 shell 中存在所需 token，且不要打印密钥。

### 1. 预检查输入

```bash
test -f "$PAPER_PDF"
test -d "$AUDITOR_ROOT"
mkdir -p "$WORKDIR"
```

如果存在 Source Data：

```bash
find "$SOURCE_DATA_DIR" -maxdepth 1 -type f | sort
```

记录 PDF、Source Data、代码仓库、`veritas.yml`、环境文件、结果文件是否存在，形成材料清单。材料缺失写成 `missing_material`，不要伪造证据。

### 2. 检查密钥

```bash
test -n "${MINERU_API_TOKEN:-}"
test -n "${DASHSCOPE_API_KEY:-}"
```

如果 `MINERU_API_TOKEN` 缺失，只能做文件清点和 Source Data 静态预检，不能跑 MinerU 解析。

### 3. MinerU 解析 PDF

```bash
cd "$AUDITOR_ROOT"
python3 scripts/mineru_convert.py "$PAPER_PDF" --output "$WORKDIR"
```

期望产物：

- `full.md`
- `*_content_list.json`
- `*_middle.json`
- `images/`
- `mineru_manifest.json`

如果 `*_middle.json` 缺失，必须在报告里降低版面定位置信度。OCR/图像转出来的表格只能作为线索。

### 4. 构建 evidence ledger

```bash
cd "$AUDITOR_ROOT"
python3 scripts/build_evidence_ledger.py "$WORKDIR" \
  --output "$WORKDIR/evidence_ledger.json"
```

红线：没有 evidence ledger 或等价证据索引的 finding 不进入正式报告。

### 5. Source Data profile

```bash
python3 "$PROJECT_ROOT/scripts/source_data_profile.py" \
  "$SOURCE_DATA_DIR" \
  --output "$WORKDIR/source_data_profile.json"
```

如果没有 Source Data，记录 `missing_material` 并继续 PDF/代码/结果文件审查。

### 6. Source Data findings

```bash
python3 "$PROJECT_ROOT/scripts/source_data_findings.py" \
  "$SOURCE_DATA_DIR" \
  --profile "$WORKDIR/source_data_profile.json" \
  --full-md "$WORKDIR/full.md" \
  --output "$WORKDIR/source_data_findings.json" \
  --min-overlap 12 \
  --min-support 0.98 \
  --max-findings-per-category 200
```

`source_data_findings.json` 应输出：

- duplicate columns
- fixed differences / fixed ratios
- formula-derived columns
- claim-to-source-data candidate mappings
- artifact likelihood
- benign explanations
- manual review notes

领域判读规则只引用 `configs/methodology/`。

### 7. PDF numeric forensics

```bash
cd "$AUDITOR_ROOT"
python3 scripts/numeric_forensics.py "$WORKDIR" \
  --output "$WORKDIR/numeric_forensics.json"
```

`numeric_forensics.json` 只作为 audit leads，不作为结论。必须按 methodology 做误报排除和压力测试。

### 8. 图片确定性候选

```bash
python3 "$PROJECT_ROOT/scripts/exact_image_duplicates.py" \
  "$WORKDIR/images" \
  --output "$WORKDIR/exact_image_duplicates.json"
```

后续可扩展近似相似候选，但 VLM 只能做语义初筛。图像结论必须回到 PDF 裁图、Source Data、相似度证据或人工复核。

### 9. Source Data 证据图

当需要展示高优先级 Source Data finding 时，优先使用确定性渲染，不用 AI 生成图作为 primary evidence：

```bash
cd "$AUDITOR_ROOT"
python3 scripts/render_evidence_tables.py \
  --audit-json "$WORKDIR/blind_source_audit.json" \
  --xlsx-root "$SOURCE_DATA_DIR" \
  --output "$WORKDIR/evidence_images"
```

如果当前 finding 来自 Veritas 自有 `source_data_findings.json`，先确认输入 JSON schema 是否兼容；不兼容时新增 adapter，不要手改原始 finding JSON。

### 10. Claim-to-evidence 初筛

基于以下材料生成 claim match table：

- `$WORKDIR/full.md`
- `$WORKDIR/evidence_ledger.json`
- `$WORKDIR/numeric_forensics.json`
- `$WORKDIR/source_data_profile.json`
- `$WORKDIR/source_data_findings.json`
- `$WORKDIR/exact_image_duplicates.json`
- `$SOURCE_DATA_DIR/*`
- `$CODE_REPO_DIR`
- `veritas.yml` / `veritas.json`
- 结果文件和环境文件

最小字段：

- `claim_id`
- `claim_text`
- `claim_type`: `numeric`、`method`、`figure_trace`、`code_execution`、`material_completeness`
- `paper_location`
- `evidence_refs`
- `source_data_refs`
- `code_refs`
- `execution_refs`
- `status`: `matched`、`mismatch`、`missing_material`、`needs_review`
- `risk_level`: `low`、`medium`、`high`
- `artifact_likelihood`
- `benign_explanations`
- `manual_review_note`

### 11. 报告

报告必须区分：

- 技术事实候选
- 材料缺口
- 工具/解析伪影可能性
- 良性解释压力测试结果
- 人工复核建议

报告措辞使用：

- “异常线索”
- “证据链”
- “需要人工复核”
- “当前材料无法确认”
- “与论文 claim 不一致”

避免：

- “造假”
- “学术不端已成立”
- “证明作者故意”
- “最终诚信判定”

## 输出位置

所有运行产物写入当前 case 的 `$WORKDIR`：

```bash
WORKDIR="$PROJECT_ROOT/outputs/$CASE_ID/research-integrity-audit"
```

不要写入 `third_party/research-integrity-auditor`，除非是在修改工具本身。
