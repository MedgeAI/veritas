# Veritas 当前实现与 PRD 差距

更新时间：2026-06-26

参照目标文档：`docs/product/Veritas完整项目PRD.md`

## 一句话结论

当前代码已经完成了一个可演示的 `audit-paper` 静态审查闭环：PDF/MinerU 解析、材料清单、Source Data XLSX 检查、PaperFraud 规则匹配、图片字节重复、canonical 视觉 artifacts、AgentInvestigationPlanner、opencode 多角色复核、Markdown/HTML 报告和 Web P1 工作台。

老板演示阶段已经完成。下一阶段目标是给内测用户跑 happy path，因此允许借鉴 ELIS (Scientific Integrity System) 的完整图像取证栈，让静态审查先形成明显更强的视觉证据包。

但它距离 PRD 核心的“`paper + repo + veritas.yml -> runtime 执行 -> artifact capture -> claim matching -> 正式技术核查报告`”仍有明显差距。当前最强的是静态审查 demo、Source Data 一致性检查和 first-party visual forensics beta，不是完整执行型核查服务。ELIS 深度/重型视觉工具已完成复用决策，但 adapter 还没有替换当前 OpenCV/ORB 过渡实现。

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
- Agent 调用层已进入 `AgentStepRunner + AgentContextPack` 形态：bounded context、JSON extraction、schema validation、retry、错误分类和 `logs/*.log` 已落地，`opencode_agent.py` 通过 legacy adapter 保持 orchestrator 兼容。
- Web P1 已加入 run heartbeat：`last_event_at` 会在启动和 progress 时更新，stale run 恢复为 `interrupted`，旧版无 heartbeat 的遗留 run 才恢复为 `failed/interrupted_by_backend_restart`。
- 本地开发工具链已切到 `uv + Makefile + ruff`：`make sync/test/lint-python/audit/web-*` 是当前推荐入口。
- `static_audit_bundle.json` 已成为一层结构化 bundle。
- HTML 报告已具备 demo 展示能力，包含 Top-N evidence cards、Agent role trace、Agent Investigation Path、人工复核任务和 artifact links。
- 视觉取证 first-party beta 已进入主链路：`visual_evidence.json`、`panel_evidence.json`、`image_relationships.json`、`visual_findings.json`、HTML Visual Evidence Package 和 Web Visual Forensics Gallery。
- `visual.copy_move` 已作为 Agent-selectable deterministic tool 注册，输出写入 `workdir/investigation/` 后由 visual finding pipeline 消费。
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

### 5.1 Agent Function Runtime 仍处在兼容迁移期

`AgentStepRunner` 已经统一了 context pack、validation、retry 和错误分类，但上层仍通过 `opencode_agent.py` 的 legacy `AgentRunResult` adapter 消费结果。

尚未完整上浮到 manifest / report / bundle 的字段包括：

- `error_category`
- `log_ref`
- `context_pack_path`
- validation failure 摘要
- retry history

这意味着 Agent 失败已经更可诊断，但报告层还没有完全把这些诊断信息暴露给 PI 或内部复盘。

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

### 7. 图表视觉取证仍是 beta 状态

当前已有：

- 字节级图片重复检查。
- dHash 近似图片候选工具，可由 AgentInvestigationPlanner 选择。
- canonical `figure_evidence` / `panel_evidence` / `visual_finding` / `image_relationship` schema。
- `visual.panel_extraction` mandatory bootstrap tool，当前是 OpenCV/Canny/contour 启发式实现，失败时可退化为 whole-figure fallback panel。
- `visual.copy_move` Agent-selectable tool，当前是 ORB/SIFT + BFMatcher + RANSAC 过渡实现。
- `visual.finding_pipeline` report-only 聚合工具。
- HTML Visual Evidence Package 和 Web Visual Forensics Gallery。

尚未完成：

- ELIS-style `pdf-extractor` / `panel-extractor` adapter。
- copy-move dense/keypoint 检测 adapter。
- TruFor 神经网络伪造检测 adapter。
- CBIR + Milvus 单论文内部相似检索 adapter。
- 真实撤稿论文或公开样本 fixture 下的 panel/copy-move 精度评估和误报基线。
- panel-level crop 和 figure-caption-source-data 强绑定。

### 7.1 运行观测与重型视觉任务稳定性决策（2026-06-26，待执行）

本节记录本地 case `case-20260625T154243Z-f0aa93ba` 暴露出的运行观测、日志和 ELIS 重型任务问题。目标是先修正产品/工程契约，再进入具体代码修改。

#### 日志与启动

- 本地开发日志统一写入 repo 下 `logs/`，标准文件为 `logs/dev-backend.log`、`logs/dev-celery.log`、`logs/dev-frontend.log` 和应用旋转日志 `logs/veritas.log`。
- `/tmp/veritas-*.log` 只作为临时手动调试路径，不作为标准开发日志入口。
- 生产环境以 `docker logs` 为主要排障入口，不额外要求应用在容器内写业务日志文件。
- 生产 Docker `json-file` 日志轮转目标调整为 `50m x 5`，避免容器重启后短期排障信息过早被覆盖；但 `compose down`、重建容器或轮转淘汰后仍不承诺永久保留。
- 数据库连接日志在开发环境保留“连到哪个库”的可见性，但只允许显示 `user`、`host`、`port`、`db` 和环境标签；密码必须脱敏。生产环境强制脱敏。
- 默认本地启动入口必须按“后端健康检查通过 -> 前端启动”的顺序执行。
- 前端 health check 也要具备初始退避/静默能力，避免用户手动先启动前端时刷出低价值 `ECONNREFUSED` proxy 噪声。

#### 日志降噪

- 高频 polling 请求（如 `/runs`、`/events`、`/artifacts`）不应在 INFO 级别逐条刷屏；仅记录状态变化、错误、慢请求或周期性摘要。
- 重复 `Database connecting` 信息不应在每次 session/connection 时刷 INFO；应降到 DEBUG 或限制为进程启动/首次连接摘要。
- 图像 panel extraction 中大量 `0 panels` 或 code-generated panel 跳过明细不应逐条刷 INFO；应改为阶段汇总，必要时在 DEBUG 保留明细。

#### ELIS provenance graph

- ELIS provenance graph 超过固定时间不等同于失败。产品语义应区分 `running`、`stalled`、`needs_investigation`、`failed`。
- 当前观测到的问题不是 Docker 未启动，而是 ELIS 任务很慢且缺少 phase-level 观测；后续重点是定位瓶颈在哪个阶段。
- ELIS provenance graph 必须记录 phase 级耗时，至少包括：输入准备、Docker 启动、descriptor extraction、matching/BFS、MST/graph build、artifact 写入。
- 设置 `5min` inactivity watchdog：若 5 分钟没有 heartbeat、新 artifact 或 phase 进展，标记为 `stalled` 并写入 manifest/step metadata。
- 设置 `30min` hard cap：超过 30 分钟仍未完成时，标记为 `needs_investigation`，不等同于 deterministic failure，不应覆盖已产出的有效 artifact。
- 任务结束或 cap 触发后应复核 output directory；若存在完整可解析的 `provenance_graph.json`，应采纳并记录 limitation/diagnostic，而不是仅凭 wrapper timeout 写死失败。
- Docker 调用失败或慢任务必须记录 command、image、timeout/cap、output dir、stderr 摘要和最后进展点；默认继续使用 `--rm`，不保留容器。

#### Agent review grounding

- `agent_review` 的 hallucination check 不应只以 `top_n_findings` 作为合法 ID 白名单；`top_n_findings` 数量有限，不能代表底层 artifact 全量 finding 集。
- 合法 finding id 集合应来自全量 canonical artifacts / bounded artifact registry，而不是仅来自 Top-N 展示列表。
- Agent review 可以引用底层 artifact 中存在的 finding id；但报告和 metadata 必须能回链到对应 artifact path。
- 引用不存在于任何 canonical artifact / registry 的 finding id 仍应触发 retry 或 failed trace。
- `hallucination_checks.all_passed=false` 不应导致整个 audit run 失败；对应 review artifact 应标记为 `needs_review`，并把 grounding warning 暴露到 manifest/bundle/report metadata。

#### VLM 初筛删除范围

- 批量 VLM 图表初筛从 Veritas first-party pipeline、progress、report 和 PRD 路线中删除，不再作为 skipped/disabled 能力展示。
- 删除 first-party `visual_triage` / VLM triage 相关角色、reserved artifact、report section、progress step 和测试预期。
- 不删除 third_party/upstream 文档中的 VLM 字样。
- 不删除 MinerU 自身 `model_version=vlm` 能力说明，除非后续单独决定禁用 MinerU VLM 模式。
- 不删除 PaperConan 的 `triage` profile；该 profile 不是 VLM 能力。

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
- opencode 输入上下文已从裸 workdir 读取推进到 bounded `AgentContextPack`，降低了大文件、二进制、图片和无关产物污染 Agent 输出的概率。
- `image_similarity_candidates` 已从固定 baseline 改为 Agent-selectable optional investigation tool。
- MinerU 远端断连时，orchestrator 已增加 3 次尝试、退避等待和失败摘要。
- Web P1 已不再把所有遗留 running run 一律标记为失败；有 heartbeat 的 stale run 使用 `interrupted` 表达中断语义。

## 推荐 P0/P1

### P0: 稳定 visual v1 并接入 ELIS-style 图像取证 adapter

1. 先补 current visual v1 的 golden smoke：`visual_evidence.json`、`panel_evidence.json`、`image_relationships.json`、`visual_findings.json`、manifest、bundle、HTML、Web endpoints 一起验证。
2. 用公开或合成 fixture 固定 panel ground truth、copy-move 正例/负例、失败隔离和 strict evidence refs。
3. 用 adapter 方式接入 ELIS `pdf-extractor`、`panel-extractor`、copy-move keypoint/dense、TruFor、CBIR/Milvus，不直接复用 ELIS 主服务。
4. 把新增视觉工具注册进 Tool Registry，标记 `agent_selectable`、参数边界、输入输出 artifact 和失败语义。
5. 在 `AgentInvestigationPlanner` prompt 中暴露 visual tool catalog，让 Agent 选择后续视觉调查工具。
6. HTML 报告和 Web Gallery 展示原图、panel crop、overlay/heatmap、候选对、score、caption/condition、人工复核 checklist。
7. 任一重型工具失败时，报告应生成 warning/limitation，而不是中断整个审查。

### P1a: 稳定当前静态 demo 与泛化

1. 把 `AgentInvestigationPlanner` 的真实输出纳入 fixture-based eval。
2. 将 investigation 追加产物中的高价值 findings 合并进 canonical evidence/finding 表。
3. 把轻量 validator 升级为 Pydantic schema。
4. 补 non-happy-path fixtures：no Source Data、CSV/TSV、多个候选目录、损坏材料、benign repeated pattern。
5. 继续完善 HTML 报告的空态、失败态、Agent 失败态和 investigation path 展示。
6. 将 AgentStepRunner 的 `error_category`、`log_ref`、`context_pack_path` 和 validation/retry 摘要提升到 manifest、bundle 和 HTML limitations。

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
