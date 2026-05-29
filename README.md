# Veritas

Veritas 是一个面向干实验论文 claim 的执行型技术复核原型。

它不是普通静态论文审查工具。当前核心差异化是：系统不仅阅读论文，还要尽量把论文 claim 对应到 PDF 解析结果、Source Data、代码、环境、执行日志和结果文件，并生成可复查的技术核查报告。

当前仓库仍以 `audit-paper` 审查闭环为核心，但已开始补 Web P1：在浏览器里创建 case、上传输入、启动与 CLI 等价的审查、观察进度并打开最终 HTML 报告。

## 当前范围

MVP 聚焦：

- Python/R 医学生信与生物医药干实验论文。
- 投稿前技术复核，而不是学术价值评价。
- 服务式流程：用户提交材料，我们代跑。
- CLI-first，同时提供 Web P1 工作台用于内测 happy path。
- opencode Agent 编排不确定推断，确定性脚本负责可重复检查。

当前明确不做：

- 最终科研诚信判定。
- 自动修改论文、Source Data 或代码。
- 自动提交 patch。
- 完整 SaaS 任务系统和多租户运营后台。
- 远程 worker 集群。

## 当前内测增强方向

老板演示 demo 已完成。下一阶段目标是让内测用户在 happy path 下体验更强的静态审查能力，尤其是图像和视觉取证。

Veritas 将借鉴 ELIS (Scientific Integrity System) 的完整图像取证思路：

- PDF 图片提取和 panel 拆分。
- copy-move dense/keypoint 图内复用检测。
- TruFor 神经网络伪造检测。
- CBIR + Milvus 单论文内部相似检索。
- 视觉证据包和人工复核 checklist。

边界是：ELIS 能力必须通过 Veritas adapter、Tool Registry 和 runtime 接口接入；不直接复用 ELIS 的 FastAPI/Celery/MongoDB/Redis 主服务。前端可以复用 `third_party/elis/system_modules/elis-frontend` 的 Vite/React/Tailwind 基础设施模式，但产品信息架构、视觉语言和审查流程必须是 Veritas first-party。所有视觉工具输出都只是候选证据和人工复核入口，不做最终科研诚信判定。

## 仓库结构

```text
cli/          CLI demo 入口
engine/       claim 审计、静态审查内核、Agent 调查、报告逻辑
runtime/      本地执行后端，未来可独立成服务
protocols/    垂直领域规则，先从医学生信开始
configs/      opencode 与运行配置
examples/     demo manifest 和轻量样例
scripts/      可复用本地工具脚本
web/          Web P1：stdlib backend + Vite React frontend
tests/        单测、集成测试和 e2e 测试
third_party/  外部参考仓库，以 git submodule 管理
```

`engine/tools/registry.py` 是当前静态审查工具集合的 source of truth。opencode 可以在 `agent_plan` 中选择 tool_id 和填写参数，但只有 Tool Registry 允许的 tool_id 会被 Python orchestrator 执行。

`engine/static_audit/` 是 Veritas first-party 静态审查内核，负责 schema、protocol、roles、tools、orchestrator 和 `static_audit_bundle.json`。`third_party/research-integrity-auditor` 仍作为 upstream reference，已吸收到 `engine/static_audit/upstream/research_integrity_auditor/` 的只读镜像中。

各模块职责和调用关系详见 [CodeMAP.md](CodeMAP.md)。

不进入提交：

- `input/`：真实论文与用户输入材料。
- `outputs/`：本地运行产物与报告。
- `web_data/`：Web 本地 case store 与运行状态。
- `web/frontend/dist/`：前端本地构建产物。
- `web/frontend/node_modules/`：前端依赖。
- `.env`：本地密钥。

## audit-paper 数据流

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
| opencode -> optional lanes  |
+-----------------------------+
  |
  +-- writes agent_material_plan.json
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
| opencode -> tool_id JSON    |
+-----------------------------+
  |
  +-- writes agent_audit_plan.json
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
| ELIS-style visual forensics |
| next internal beta path     |
+-----------------------------+
  |
  +-- canonical figure_evidence.json
  +-- panel_evidence.json
  +-- copy_move_findings.json
  +-- trufor_findings.json
  +-- image_relationships.json
  +-- visual evidence package
  |
  v
+-----------------------------+
| AgentInvestigationPlanner   |
| agent_mode != off           |
| opencode -> tool actions    |
+-----------------------------+
  |
  +-- validates deterministic tool_id via Tool Registry
  +-- writes agent_investigation_plan_round_XX.json
  +-- writes investigation_rounds.jsonl
  +-- writes investigation/round_XX/action_YY artifacts
      e.g. image_similarity_candidates.json
  |
  v
+-----------------------------+
| agent_review                |
| when agent_mode=review/full |
| opencode -> JSON schema     |
+-----------------------------+
  |
  +-- writes agent_review.json
  +-- candidate claims
  +-- finding reviews
  +-- manual review tasks
  |
  v
+-----------------------------+
| static audit role layer     |
| when agent_mode=review/full |
+-----------------------------+
  |
  +-- ClaimExtractor -> agent_claim_extractor.json
  +-- SourceDataAuditor -> agent_source_data_auditor.json
  +-- JudgeAgent -> agent_judge.json
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

## audit-paper 状态机

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
ELIS_VISUAL_FORENSICS?              (planned internal beta)
  |
  +-- adapter/runtime available -> panel/copy-move/TruFor/CBIR tools
  +-- partial tool failure ------> warning + limitations + continue
  +-- unavailable --------------> skipped
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

状态含义：

- `ran`：本轮真实执行成功。
- `reused`：目标产物已存在且未指定 `--force`。
- `skipped`：前置材料或能力缺失，跳过但不视为失败。
- `warning`：Agent 失败或输出不合规，降级继续确定性报告。
- `failed`：确定性命令失败或预期产物缺失，最终进程返回 1。

当前 `audit-paper` 的真实 Agent role 层顺序执行 3 个角色：`ClaimExtractor`、`SourceDataAuditor`、`JudgeAgent`。其余 role 先写入 `skipped` trace，占位给后续并行 subagent 和视觉/数字/数学/领域复核扩展。

`final_audit_report.html` 是当前老板 demo 的优先展示形态：单文件静态 HTML，突出本 case 结论、Top-N priority findings、证据定位、良性解释、人工复核动作和 role trace。Markdown 报告继续保留作为兼容输出。

## 常用命令

确定性预检查：

```bash
PYTHONPATH=. python3 cli/main.py precheck examples/bioinfo_python_case/veritas.json
```

运行轻量 manifest demo：

```bash
PYTHONPATH=. python3 cli/main.py run examples/bioinfo_python_case/veritas.json --output-dir outputs/demo
```

渲染报告：

```bash
PYTHONPATH=. python3 cli/main.py report outputs/demo/report.json --output-dir outputs/demo
```

运行论文审查 demo：

```bash
PYTHONPATH=. python3 cli/main.py audit-paper <paper_dir> --case-id <case_id> --agent-mode review --agent-timeout-seconds 180 --agent-max-retries 1 --progress plain
```

推荐先打开 `outputs/<case_id>/research-integrity-audit/final_audit_report.html` 做内部 demo。`--agent-mode full` 当前仍可能受 `agent_plan` JSON 输出不稳定影响。`audit-paper` 进度输出写入 `stderr`，最终 summary JSON 仍写入 `stdout`；需要机器消费进度时使用 `--progress jsonl`，需要安静运行时使用 `--progress off`。MinerU 子进程的 `state/pages` 输出会被转发为 `OUT mineru` 进度行。

只跑确定性链路：

```bash
PYTHONPATH=. python3 cli/main.py audit-paper <paper_dir> --case-id <case_id> --agent-mode off
```

从零重跑并禁止复用既有 MinerU 产物：

```bash
PYTHONPATH=. python3 cli/main.py audit-paper <paper_dir> --case-id <case_id> --fresh --force --agent-mode review --progress plain
```

启动 Web P1 后端：

```bash
PYTHONPATH=. python3 -m web.backend.veritas_web.app
```

启动 Web P1 前端：

```bash
cd web/frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。Vite 会把 `/api` 代理到 `http://127.0.0.1:8765`。如果先在 `web/frontend` 执行 `npm run build`，Python backend 会在 `web/frontend/dist` 存在时托管构建产物。

## 环境变量

不要把密钥写入 git。

```bash
DASHSCOPE_API_KEY=...
MINERU_API_TOKEN=...
```

`scripts/run_paper_audit.py` 默认会读取仓库根目录 `.env`，但 `.env` 必须保持未提交。

## 测试

```bash
pytest -q
```

当前 pytest 只收集本仓 `tests/`，不会扫描 `third_party/` 上游仓库测试。
