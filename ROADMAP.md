# Veritas Roadmap

Updated: 2026-07-01

Veritas 当前定位是投稿前的实验室内部论文风控工具，先聚焦干实验论文，帮助 PI 在投稿前发现 Source Data、图像、claim/evidence 对账和材料完整性上的高风险信号。它不是最终科研诚信裁决系统，也不是论文价值评价工具。

---

## Current Product Effect

当前产品已经可以达到的效果是：

1. **把一篇论文审查跑成可复核的证据包。**
   - 输入一个 `paper_dir`，通过 `audit-paper` 生成 `outputs/<case_id>/research-integrity-audit/`。
   - 输出包括 `static_audit_bundle.json`、`audit_run_manifest.json`、Markdown 报告和单文件 HTML 报告。
   - 报告按 `consistency`、`matching`、`completeness` 分层，不直接给出“学术不端成立”结论。

2. **为 PI 暴露投稿前最值得追问的问题。**
   - Source Data 内部一致性：重复列、固定关系、公式派生、行偏移、比例复用、重复行、跨 sheet 重复等。
   - PDF/论文文本证据：MinerU 解析、evidence ledger、数字取证、PaperFraud 方法论规则匹配。
   - 图像证据：字节级重复、dHash 近似候选、figure/panel canonical evidence、panel-level copy-move 候选、image relationship、visual finding。
   - 材料完整性：缺 Source Data、缺代码、缺环境、缺结果文件时按 completeness issue 或 execution status 呈现。

3. **把 Agent 限制在受控调查闭环里。**
   - opencode Agent 可以做材料计划、调查规划、claim/finding 复核和 role layer 综合。
   - Python orchestrator 只执行 `engine/tools/registry.py` 中允许的 deterministic tool。
   - Agent 调用保留 bounded context pack、结构化输出、日志、重试和失败语义。

4. **提供内测 operator 可用的 Web P1 工作台雏形。**
   - Web 后端可以创建 case、上传输入、启动与 CLI 等价的审查、读取进度、打开 artifacts 和最终 HTML 报告。
   - 前端已演进为**三入口架构**：`client`（客户服务门户，veritas.science）、`ops`（运营后台，ops.veritas.science）、`verify`（公开验证，verify.veritas.science），通过 `utils/entrypoint.js` 按 hostname/pathname 分流。
   - Client Report BFF 聚合接口（`/api/cases/{case_id}/client-report`）和公开验证接口（`/api/verify/{report_id}`）已上线。
   - 前端实现 React 视图过渡、SSE 重连内存泄漏修复、空状态统一、内联样式提取与懒加载优化。
   - 审计档案（Audit Profiles）机制落地：fast/standard/full 三档控制工具执行深度。
   - Stale run watchdog 监控长时间无心跳运行，自动恢复或标记失败。
   - Visual Forensics Gallery 可以展示 figures、panels、relationships、visual findings，并支持按 risk/category 筛选。

5. **给内部 demo 一个可讲清楚的价值闭环。**
   - 对 PI 的话术：这是一份投稿前技术风控报告，帮助你知道“该向学生追问什么”。
   - 对 operator 的话术：这是一条本地 case-scoped 审查流水线，输出结构化 artifacts 和谨慎语言报告。
   - 对研发的事实源：`static_audit_bundle.json`、Tool Registry、manifest 和 report artifacts 是后续扩展的合同。

---

## Current Boundaries

当前不能过度承诺：

- 不做最终科研诚信判定，不写“确认造假”“学术不端成立”等结论。
- 不做学术价值评价。
- 不自动修改论文、Source Data、代码或报告结论。
- `precheck` / `run` / `report` 和 subprocess runtime 已有基础能力，但 claim-to-code/runtime replay 还不是 `audit-paper` 稳定主链路。
- VLM 批量图表初筛当前在 `audit-paper` 中仍是 skipped 状态。
- TruFor、CBIR/Milvus、跨论文检索还不是稳定主链路。
- 视觉取证已形成 first-party beta 代码闭环，但当前底层仍是 OpenCV panel extraction 与 ORB/SIFT copy-move 过渡实现；真实撤稿论文 fixture、精度评估和误报基线还没有达到 PRD 中的产品验收标准。
- Web P1 是内测 operator 工作台，不是完整 SaaS、多租户任务系统、远程 worker 集群或协作审阅平台。

---

## Roadmap Overview

```text
Now
  -> P0 audit-paper happy path hardening
  -> P1 visual forensics beta
  -> P1 Web operator workflow
  -> P1 claim-to-code/runtime replay
  -> P2 pilot-grade platform
  -> P2 advanced visual intelligence
```

优先级规则：先保证 `audit-paper` happy path 稳，再增加重型视觉、Web 协作和 runtime 能力。任何增强项如果威胁基础报告生成，都必须失败隔离并写入 manifest、limitations 和人工复核入口。

---

## P0: Stabilize Audit-Paper Happy Path

目标：一篇干实验论文输入后，基础静态审查可以稳定完成，并产出 PI 能看的结构化报告。

### Must Have

- `audit-paper --agent-mode review` 在常见内测材料包上稳定生成 HTML 报告。
- 所有 finding 都有 `issue_category`、risk level、evidence refs、manual review note。
- Source Data 检查继续强化为核心差异化能力，而不是被视觉能力盖住。
- Agent 失败不阻断确定性报告，失败信息进入 manifest 和 limitations。
- 报告语言持续保持“候选风险 / 需要人工复核 / 建议追问”，不写最终裁决。

### Work Items

- 补齐真实内测 case 的 golden artifacts，不提交真实论文和隐私材料。
- 为 `static_audit_bundle.json` 增加更严格的 schema/fixture 回归测试。
- 将 Source Data 检查结果和 visual findings 都稳定纳入 Top priority findings 和人工复核清单。
- 强化 opencode JSON schema retry 与 failed trace 呈现，避免成功 artifact 被失败重跑覆盖。
- 对 `audit-paper` 运行产物做 artifact inventory，明确哪些是 canonical、哪些是 debug/log。
- **已完成**：审计档案（fast/standard/full）机制落地，控制工具执行深度。
- **已完成**：Stale run watchdog 监控长时间无心跳运行。
- **已完成**：Investigation dependency layering 从 O(R²×A) 优化至 O(R×A)。

### Exit Criteria

- 5-10 个内部干实验样本可以完成基础报告生成。
- 基础报告生成成功率达到 100%，重型或可选工具失败不会中断报告。
- 报告中禁用结论性措辞为 0。
- Top findings 能回溯到结构化 evidence，而不是只来自 Agent 自然语言。

---

## P1: Visual Forensics Beta

目标：把视觉取证从“图片候选列表”升级为可复核的 figure/panel evidence graph。

### Already in Current Workspace

- `figure_evidence`、`panel_evidence`、`visual_finding`、`image_relationship` schema。
- `visual.panel_extraction` mandatory bootstrap tool。
- `visual.copy_move` agent-selectable deterministic tool。
- `visual.finding_pipeline` report-only aggregation tool。
- `visual_evidence.json`、`panel_evidence.json`、`image_relationships.json`、`visual_findings.json` canonical artifacts。
- HTML Visual Evidence Package 和 Web Visual Forensics Gallery。
- 当前算法基线：`visual.panel_extraction` 使用 OpenCV/Canny/contour 启发式，`visual.copy_move` 使用 ORB/SIFT + BFMatcher + RANSAC，并由 AgentInvestigationPlanner 可选触发。
- 已决策但未落地：ELIS YOLOv5 panel-extractor、RootSIFT/MAGSAC keypoint copy-move、SILA dense copy-move、TruFor skip/adapter、CBIR/Milvus。

### Must Have

- Current visual v1 在清晰多 panel 图上能产出可复核 panel artifacts，并明确 fallback limitations。
- Copy-move 检测输出 overlay、method、score、inlier count、relationship source type；如果 Agent 未选择 `visual.copy_move`，报告必须清楚显示该检查未执行。
- exact duplicate、dHash、copy-move 都能统一映射到 panel-level `image_relationship`。
- 每个 visual finding 都回链到 panel id、原始 figure、工具输出和人工复核问题。
- 视觉工具失败时写入 skipped/not_available/failed，不影响基础报告。

### Work Items

- 准备合规的真实撤稿论文或公开样本 fixture，只提交可公开、可再分发或元数据化的测试素材。
- 建立 panel extraction accuracy、copy-move precision/recall、false positive rate 的评估脚本。
- 增强 overlay/mask 资产的报告展示和 Web 预览。
- 在 Web Gallery 增加 tool status、review status、figure、risk、source type 过滤。
- 将 visual finding 的良性解释和人工复核问题整理成 PI 可执行话术。
- **已完成**：视觉取证 pipeline 和 figure classification 完成大规模重构。
- **已完成**：HTML 报告 hero header + certainty layers 视觉样式增强。
- **已完成**：Copy-move 检测和 provenance runner 测试覆盖增强。

### Exit Criteria

- 真实样本和合成 fixture 均能跑通视觉闭环。
- 100% visual findings 能从报告回溯到 panel/image/tool artifact。
- Panel extraction 和 copy-move 指标达到 PRD 中 Phase 1 验收阈值，或明确记录未达标原因和 fallback。

---

## P1: Web Operator Workflow

目标：让内部 operator 不靠命令行也能完成内测 happy path。

### Must Have

- Case list、New Audit、材料上传、启动审查、进度查看、artifact 浏览、HTML 报告预览。
- Visual Forensics Gallery 进入 case 内导航，而不是独立图片产品。
- Run status、failed tool、last event heartbeat 和 stale recovery 清晰显示。
- Operator 能定位失败步骤、下载关键 JSON、打开最终报告。

### Work Items

- 完成 case status 映射：Draft、Uploaded、Planning、Running、Review Needed、Report Ready、Archived。
- **已完成**：三入口架构落地（client/ops/verify），通过 hostname/pathname 分流。
- **已完成**：Client Report BFF 聚合接口和公开验证接口上线。
- **已完成**：扩展运行状态枚举和 decision type 模型。
- 增加 material inventory 页面，展示缺材料和 optional lane 选择结果。
- 增加 report center，支持报告版本、重新生成和交付视图。
- 增加 review queue 雏形，把 findings 和 manual review tasks 变成可处理事项。
- 把 Web API 的 artifact contract 固定到测试中，避免前端解释 raw JSON 变成第二套事实源。

### Exit Criteria

- 内部 operator 可以通过 Web 完成一次从上传到报告预览的审查。
- Web 展示内容全部来自 case-scoped artifacts 或 bundle，不绕过 evidence contract。
- Web 仍可在本地 file-based store 下运行，不引入多租户和远程 worker 复杂度。

---

## P1: Claim-To-Code And Runtime Replay

目标：把当前已有的 `precheck` / `run` / `report`、subprocess runtime 和 `audit-paper` 静态审查打通成更稳定的 claim-to-code verification 链路。

### Must Have

- `veritas.yml` 作为主 manifest，JSON 兼容保留。
- `precheck` 能稳定判断代码、环境、入口脚本、结果文件是否具备执行条件。
- `run` 通过 subprocess executor 记录 command manifest、stdout/stderr、exit code、runtime seconds、result files、file hashes。
- claim mapping 能区分 supported、mismatch、missing evidence、not executed。
- 缺代码或环境时呈现 completeness issue，而不是伪装成复现失败。

### Work Items

- 定义并冻结 `veritas.yml` schema。
- 将 runtime execution evidence 纳入 `static_audit_bundle.json`。
- 让 Agent claim-to-code mapping 只输出结构化候选，最终执行仍由 runtime 控制。
- 增加 Python/R bioinfo fixture，覆盖成功执行、缺环境、结果 mismatch、结果缺失。
- 报告增加 claim-to-code/runtime replay 小节，但保持它不是当前 happy path 的唯一入口。

### Exit Criteria

- 至少 Python 和 R 各 1 个干实验 demo case 可完成 runtime replay。
- 每条 runtime claim match 都能回溯到命令、输出、文件 hash 和 claim。
- 失败状态可解释，且不会和学术不端结论混淆。

---

## P2: Pilot-Grade Platform

目标：从本地内测工具升级为可服务付费试点的受控平台，但不急着做完整 SaaS。

### Work Items

- Auth、role、case permission：operator、reviewer、viewer、admin。
- PI view 和 author response view。
- Report versioning、review history、manual decision log。
- Background job queue 和 remote worker 抽象。
- Artifact storage、retention、case archive、audit log。
- Secret handling、PII/data boundary、deployment hardening。
- Intranet deployment 和有限组织空间管理。

### Exit Criteria

- 可以支持 1-3 个内部或友好实验室的受控试点。
- 每个 case 的材料、运行记录、人工复核、报告版本可审计。
- 平台行为不依赖单机临时文件路径，且密钥不进入报告、manifest 或日志。

---

## P2: Advanced Visual Intelligence

目标：在传统 CV panel-level 闭环稳定后，谨慎接入更强视觉模型和检索能力。

### Candidate Capabilities

- TruFor heatmap：只作为伪造区域初筛，不作为最终证据；无 GPU 或模型不可用时应 skip 并写 limitations。
- CBIR/Milvus：优先 single-paper internal similarity，再考虑跨论文检索。
- YOLOv5/ELIS panel extraction：已决策作为下一步 adapter 路线，用于替换当前 OpenCV 过渡实现。
- RootSIFT/MAGSAC 和 dense copy-move：已决策作为下一步 adapter 路线，用于替换或增强当前 ORB/SIFT 过渡实现。

### Decision Gates

- 许可证和商业使用风险清楚。
- GPU/模型依赖可以失败隔离。
- 输出能回链到 canonical figure/panel evidence。
- 有 fixture 或 golden case 固定行为。
- 报告语言仍符合谨慎风险边界。

---

## Milestone Gates

| Gate | Meaning | Required Evidence |
|---|---|---|
| Demo Ready | 可以给老板/PI 演示核心价值 | `audit-paper` 生成 HTML 报告；Top findings 有 evidence refs；视觉 evidence package 可打开 |
| Internal Beta Ready | 内部 operator 可连续代跑 | 5-10 个样本稳定完成；失败状态清晰；Web 能完成上传到报告预览 |
| Paid Pilot Ready | 可给友好实验室试点 | 权限、报告版本、人工复核记录、数据边界、部署方案到位 |
| Platform Ready | 可以考虑 SaaS 化 | 远程 worker、队列、存储、组织空间、审计日志、运营监控稳定 |

---

## Product Principles

- Evidence First：报告只能从结构化 evidence、artifact、manifest 和人工复核记录生成。
- Tool Registry First：Agent 只能选择 registry 允许的 deterministic tool。
- Case First：Veritas 的核心对象是论文审查 case，不是全局图库。
- Consistency First：一致性问题优先级高于 matching 和 completeness。
- Human Review Always：高风险候选必须给人工复核问题和良性解释，不做最终裁决。
- Fail Isolated：重型视觉、VLM、runtime、外部服务失败必须被记录，但不能破坏基础报告。
