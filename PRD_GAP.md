# Veritas 当前实现与 PRD 差距

更新时间：2026-05-29

参照目标文档：`docs/product/Veritas完整项目PRD.md`

## 一句话结论

当前代码已经完成了一个可演示的 `audit-paper` 静态审查闭环：PDF/MinerU 解析、材料清单、Source Data XLSX 检查、图片字节重复、AgentInvestigationPlanner、opencode 多角色复核、Markdown/HTML 报告。

老板演示阶段已经完成。下一阶段目标是给内测用户跑 happy path，因此允许借鉴 ELIS (Scientific Integrity System) 的完整图像取证栈，让静态审查先形成明显更强的视觉证据包。

但它距离 PRD 核心的“`paper + repo + veritas.yml -> runtime 执行 -> artifact capture -> claim matching -> 正式技术核查报告`”仍有明显差距。当前最强的是静态审查 demo 和即将增强的图像取证内测路径，不是完整执行型核查服务。

## 已接近 PRD 的部分

- CLI 已有 `audit-paper`、`precheck`、`run`、`report` 入口。
- `audit-paper` 已能从本地论文目录启动端到端静态审查。
- PDF 解析接入 MinerU，产出 `full.md`、`images/`、`mineru_manifest.json`。
- evidence ledger 已能将 PDF 解析产物转成结构化索引。
- numeric forensics 已进入 mandatory bootstrap。
- `material_inventory.json` 已能发现论文目录内的 optional materials。
- `agent_material_plan` 已能让 opencode 选择可执行 optional lane。
- XLSX Source Data 已有 profile、findings、pair/row-offset forensics。
- `AgentInvestigationPlanner` 已接入 P0 最小闭环：最多 3 轮规划、Tool Registry 校验、独立 investigation artifacts、`investigation_rounds.jsonl` 和 HTML 摘要展示。
- `agent_review`、`ClaimExtractor`、`SourceDataAuditor`、`JudgeAgent` 已经是真实 opencode 调用，不只是 fake trace。
- `static_audit_bundle.json` 已成为一层结构化 bundle。
- HTML 报告已具备 demo 展示能力，包含 Top-N evidence cards、Agent role trace、Agent Investigation Path、人工复核任务和 artifact links。
- subprocess runtime 有雏形，toy manifest 可以跑轻量 `precheck/run/report`。

## 主要差距

### 1. `veritas.yml` 主协议尚未落地

PRD 期望用户提交：

```text
paper.pdf
repo/
veritas.yml
data / results / environment files
```

当前仍是：

- `audit-paper <paper_dir>` 静态审查路径。
- `examples/bioinfo_python_case/veritas.json` toy manifest。
- `audit-paper` 不读取 `veritas.yml`，也没有把论文、代码仓库、环境和复现声明统一到一个主协议。

### 2. 真实 runtime 主链路尚未打通

当前 `audit-paper` 不执行用户代码仓库：

- 不构建环境。
- 不运行 reproduce/eval 命令。
- 不捕获结果文件 hash。
- 不审计网络、依赖、stdout/stderr、exit code。
- 不把 runtime evidence 合并进 static audit bundle。

PRD 的核心差异化是“真实去环境构建和代码执行”，这一块目前仍处于接口和 toy demo 阶段。

### 3. Artifact capture 体系不完整

PRD 要求执行证据至少包括：

- command manifest
- stdout/stderr
- exit code
- runtime seconds
- result files
- file hashes
- network audit
- environment snapshot

当前静态工具有 step command 和若干 JSON artifacts，但尚未形成统一 execution evidence JSONL，也没有覆盖完整 runtime artifact capture。

### 4. Claim-to-code mapping 尚未实现

当前 Agent 主要做：

- claim-to-source-data
- finding review
- manual review task
- technical risk summary

尚未系统性完成：

- claim -> repo file/function/script
- claim -> command
- claim -> result artifact
- claim -> generated figure/table
- claim -> execution evidence

### 5. Evidence event 协议还未统一

当前报告和 bundle 仍从多种 ad hoc JSON 产物汇总：

- `evidence_ledger.json`
- `source_data_findings.json`
- `source_data_pair_forensics.json`
- `agent_*`
- `investigation_rounds.jsonl`

PRD 期望报告从统一 evidence event 生成。当前已经向结构化 bundle 靠近，但还不是完整 evidence event model。

### 6. Investigation 产物尚未并入 canonical finding 图

`AgentInvestigationPlanner` 当前已能规划和执行追加确定性工具，但追加输出写在：

```text
workdir/investigation/round_XX/action_YY/
```

这些产物目前主要展示在 HTML 的 `Agent Investigation Path` 和 artifact links 中，尚未自动合并进：

- canonical `EvidenceItem`
- canonical `Finding`
- canonical `ClaimMapping`

下一步需要设计去重和优先级规则，避免重复刷屏或覆盖 baseline evidence。

### 7. 图表视觉取证仍是早期状态

当前已有：

- 字节级图片重复检查。
- dHash 近似图片候选工具，可由 AgentInvestigationPlanner 选择。

尚未完成：

- ELIS-style `pdf-extractor` / `panel-extractor` adapter。
- copy-move dense/keypoint 检测 adapter。
- TruFor 神经网络伪造检测 adapter。
- CBIR + Milvus 单论文内部相似检索 adapter。
- canonical `figure_evidence` / `panel_evidence` / `visual_finding` / `image_relationship` schema。
- vLLM/VLM 图表初筛。
- panel-level crop 和 figure-caption-source-data 绑定。
- 人工复核用的视觉证据包。

### 8. CSV/TSV 和更多 Source Data 类型未执行

当前可执行 Source Data lane 主要是 XLSX/XLSM。

CSV/TSV、raw data、archive 会进入材料清单和 unsupported materials，但还没有正式：

- profile
- duplicate/fixed-ratio/row-offset findings
- claim-to-source-data mapping
- Agent-selectable table facade

### 9. 报告还未达到 PRD 正式报告形态

当前 HTML demo 已经可展示，但 PRD 中的正式报告要求还未完全实现：

- V0-V4 核查深度。
- pass/warning/fail 结果语义。
- 作者视图 / PI 视图。
- Execution Log Summary。
- Claim Match Table 与代码执行证据绑定。
- PDF 报告导出。
- 更强的不可篡改 provenance 和 artifact hash。

### 10. 4 个验收 case 尚未标准化

当前有真实论文静态审查 case 和 toy manifest case，但还缺：

- Python 生信真实执行 case。
- R 生信真实执行 case。
- 构造 claim mismatch case。
- 无 Source Data / CSV-TSV / 多材料目录 / 损坏材料等 non-happy-path fixture。
- 已打假强展示 case 的标准化验收脚本。

## 当前已解决的旧问题

- `audit-paper` 不再只依赖固定 Source Data 目录名。
- `Source Data` 静态审查不再只看整列重复/固定差/固定比，已增加通用 pair/row-offset forensics。
- `agent_review` 之外已接入真实 role agents。
- claim-to-source-data 主视图已改为优先 Agent refined mapping，deterministic mapping 作为 provenance scaffolding。
- 临时 opencode 是否触发 skill 的不稳定性已通过常驻上下文和 Tool Registry 约束部分缓解。
- `image_similarity_candidates` 已从固定 baseline 改为 Agent-selectable optional investigation tool。
- MinerU 远端断连时，orchestrator 已增加 3 次尝试、退避等待和失败摘要。

## 推荐 P0/P1

### P0: ELIS-style 图像取证内测闭环

1. 定义 canonical `figure_evidence`、`panel_evidence`、`visual_finding`、`image_relationship` schema。
2. 用 adapter 方式接入 ELIS `pdf-extractor`、`panel-extractor`、copy-move、TruFor、CBIR/Milvus，不直接复用 ELIS 主服务。
3. 把视觉工具注册进 Tool Registry，标记 `agent_selectable=True`、参数边界、输入输出 artifact。
4. 在 `AgentInvestigationPlanner` prompt 中暴露 visual tool catalog，让 Agent 选择后续视觉调查工具。
5. HTML 报告增加视觉证据包：原图、panel crop、overlay/heatmap、候选对、score、caption/condition、人工复核 checklist。
6. 任一重型工具失败时，报告应生成 warning/limitation，而不是中断整个审查。
7. 对一个内测 happy path case 跑通完整视觉链路，证明比纯 opencode + skill 审查更强。

### P1a: 稳定当前静态 demo 与泛化

1. 把 `AgentInvestigationPlanner` 的真实输出纳入 fixture-based eval。
2. 将 investigation 追加产物中的高价值 findings 合并进 canonical evidence/finding 表。
3. 把轻量 validator 升级为 Pydantic schema。
4. 补 non-happy-path fixtures：no Source Data、CSV/TSV、多个候选目录、损坏材料、benign repeated pattern。
5. 继续完善 HTML 报告的空态、失败态、Agent 失败态和 investigation path 展示。

### P1b: 扩展静态审查 Tool Registry

1. `material.completeness_check`
2. `figure_sheet_mapper`
3. `source_data_table` facade，支持 XLSX/CSV/TSV
4. 更强 image similarity / pHash / transform candidates
5. vLLM/VLM 视觉初筛，只作为候选发现器
6. math consistency check：n、百分比、p value、均值/SEM/SD、fold-change、ratio 复算

### P2: 回到执行型 PRD 主线

1. 定义并实现 `veritas.yml` schema。
2. 将 `audit-paper` 与 `run` 合并为同一条主链路：PDF 解析 + repo runtime + claim match。
3. 做 execution evidence JSONL。
4. 做一个构造 mismatch case，稳定证明“自动发现 claim mismatch”。
5. 报告从 evidence events 渲染，而不是临时拼接各脚本产物。

## 当前判断

短期对老板展示：当前项目已经像一个“可信的静态科研技术复核 demo”，尤其是 AgentInvestigationPlanner 让它区别于一次性 Claude + skill 审查。

中期对 PRD：还必须补 runtime、veritas.yml、claim-to-code、execution evidence，才能兑现“执行型科研事实核查服务”的核心承诺。
