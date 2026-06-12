# Veritas ELIS-style 视觉取证增强初步 PRD

## 文档信息

- 文档状态：已决策 PRD（2026-06-12 决策冻结）
- 目标阶段：内测 happy path / P1 增强
- 目标读者：产品负责人、研发、内部 operator、PI 演示评审
- 参考对象：ELIS Scientific Integrity System 的图像取证栈与交互模式
- 产品边界：Veritas first-party 审查任务系统，不直接并入 ELIS 主服务
- **技术路线**：CPU-only 传统 CV（OpenCV + scikit-image），不依赖 ELIS 代码，不依赖 GPU
- **检测粒度**：Panel-level（跳过整图模式，直接进入 panel 检测）
- **Web Gallery**：Phase 1 必需（交互式），不是 Phase 2

## Problem Statement

Veritas 当前已经能通过 `audit-paper` 跑通论文静态审查闭环：材料清单、MinerU PDF 解析、evidence ledger、数字取证、Source Data 一致性检查、exact image duplicate、dHash 近似图片候选、AgentInvestigationPlanner、Agent role layer、Markdown/HTML 报告。

但视觉取证能力还停留在较浅层：图片证据没有形成 canonical figure/panel 证据模型，copy-move、TruFor、CBIR、panel extraction 尚未进入 Tool Registry 和 static audit bundle。对于 PI 最关心的“图像是否可能被复制、拼接、伪造或跨 panel 重用”，当前报告只能给出有限候选，无法形成可复核的视觉证据包。

ELIS 已经在科学图片完整性方向积累了较完整的能力栈：PDF image extraction、YOLO panel extraction、single/cross copy-move、TruFor heatmap、CBIR/Milvus similarity、relationship graph 和图库式复核交互。Veritas 下一步需要充分借鉴这些能力，但必须保持自身 case-first、Evidence First、Tool Registry 受控执行和谨慎风险语言。

## Solution

为 Veritas 增加一条 panel-level 视觉取证增强链路，**自己实现 CPU-only 传统 CV 方案，不依赖 ELIS 代码**。

### 核心技术决策（2026-06-12 冻结）

| 决策点 | 选择 | 理由 |
|---|---|---|
| **检测粒度** | Panel-level（跳过整图模式） | 造假者不会用低级整图复制；整图模式误报率过高（legal controls, scale bars, repeated templates） |
| **Panel extraction** | 传统 CV（OpenCV 边缘检测 + 轮廓分析） | CPU-only，无 GPU 依赖，速度快（< 1 秒/图）；避免 YOLO 的 AGPL/GPL 许可证风险 |
| **Copy-move** | SIFT/ORB 特征匹配 + RANSAC（OpenCV） | CPU-only，成熟算法，Apache 2.0 许可证 |
| **ELIS 依赖** | 不直接依赖，自己实现 | AGPL 许可证风险；subprocess 调用仍可能被视为衍生作品；自己实现可精确控制 |
| **GPU 依赖** | 无（CPU-only） | 内测环境无 GPU；传统 CV 足够 |
| **许可证** | Apache 2.0 / MIT / BSD 库 | OpenCV（Apache 2.0）、scikit-image（BSD）、Pillow（MIT）；避免 GPL/AGPL |
| **Fixture** | 真实论文（retracted papers）+ 合成 fixture | 真实论文从 PubMed retract watch / PubPeer 获取；合成 fixture 用于单元测试 |
| **Web Gallery** | Phase 1 必需 | 需要交互式演示；PI 需要快速浏览和筛选 |
| **Agent 工具选择** | Panel extraction mandatory, copy-move agent-selectable | Panel extraction 是基础能力；copy-move 可根据论文类型决定 |
| **报告语言** | 模板约束 + 词库检查 + 人工审核 | 软件层面用模板和词库约束，最终靠人工审核 |
| **开发模式** | 6 个 agent 并行，3 周完成 Phase 1 | 最大化并行度 |

### Phase 1：Panel-Level 视觉取证闭环（3 周）

**目标**：实现 panel-level copy-move 检测，产出可复核的视觉证据包。

**核心原则**：**Panel-level 检测，CPU-only 传统 CV，不依赖 ELIS 代码。**

1. **Visual Evidence Schema Module**（Agent 1）
   - 定义 `figure_evidence`、`panel_evidence`、`visual_finding`、`image_relationship` 的 schema
   - `panel_evidence` 是必需（不是可选），因为检测粒度是 panel-level
   - 实现 MinerU 输出到 `figure_evidence` 的映射
   - Schema validation tests

2. **Panel Extraction Adapter**（Agent 2）
   - 实现传统 CV panel extraction（OpenCV 边缘检测 + 轮廓分析）
   - 输出 `panel_evidence`（bbox, crop_path, label, parent_figure_id）
   - Fixture-backed tests
   - 目标准确率 > 80%（清晰 panel 布局）

3. **Copy-Move Adapter**（Agent 3）
   - 实现 panel-level copy-move 检测（SIFT/ORB 特征匹配 + RANSAC）
   - 输出 overlay 图像和 `image_relationship`
   - Fixture-backed tests

4. **Visual Finding Pipeline**（Agent 4）
   - 实现 relationship builder：copy-move 输出 → `image_relationship`
   - 实现 finding builder：高 score relationship → `visual_finding`
   - Pipeline tests

5. **Report + Web Gallery**（Agent 5）
   - HTML 报告增加 Visual Evidence Package 章节
   - 实现 Web Visual Forensics Gallery（交互式）
   - 展示 figure/panel grid、overlay 比较、relationships、人工复核 checklist
   - Report rendering tests + Web artifact tests

6. **Fixture Preparation**（Agent 6）
   - 准备 2-3 个真实论文 fixture（retracted papers from PubMed/PubPeer）
   - 准备 1-2 个合成 fixture（手动制作 copy-move 案例）
   - Fixture validation tests

### Phase 2：增强视觉取证（可选）

**目标**：如果 Phase 1 验证需要，接入 TruFor（如果有 GPU）或 CBIR。

**决策点**：Phase 1 完成后评估：
- 如果传统 CV 的 panel extraction 准确率 < 70%，考虑接入 YOLO CPU 版本
- 如果有 GPU 且需要 heatmap 检测，接入 TruFor
- 如果需要跨论文检索，接入 CBIR/Milvus

### 最终边界

```text
PDF / MinerU images
  ↓
figure_evidence（canonical figure ids）
  ↓
panel extraction（传统 CV：边缘检测 + 轮廓分析）
  ↓
panel_evidence（bbox, crop_path, label）
  ↓
panel-level copy-move（SIFT/ORB + RANSAC）
  ↓
image_relationship（事实关系）
  ↓
高 score relationship → visual_finding（候选问题）
  ↓
static_audit_bundle / HTML visual evidence package / Web Gallery
  ↓
人工复核 checklist
```

## Current Baseline

当前实现可直接承接本 PRD 的基础能力：

- 已有 case-first `audit-paper` pipeline，输出 workdir、manifest、bundle 和单文件 HTML 报告。
- 已有 Tool Registry，Agent 只能选择 registry 中 `agent_selectable=True` 且 deterministic 的工具。
- 已有 investigation rounds 记录，追加工具输出写入 investigation 子目录，不覆盖 baseline artifacts。
- 已有 `StaticAuditBundle`，可承载 evidence、claim、finding、claim mapping、tool run、agent trace、limitations。
- 已有 Web P1 基础：case list、new audit、run bridge、progress events、artifact list、final HTML report preview。
- 已有 dHash near-duplicate tool，但它只是轻量候选，无法覆盖 panel-level、local copy-move、heatmap 和 relationship graph。

当前缺口：

- `EvidenceKind` 还没有明确区分 figure、panel、mask、heatmap、relationship。
- 视觉 artifacts 尚未成为 first-class bundle 数据。
- 报告没有视觉证据包章节。
- Web artifact service 只列核心 JSON/HTML，不识别视觉证据包。
- ELIS 工具尚未被封装成 Veritas adapter，也没有失败隔离、schema 校验和 fixture tests。

## Goals

1. 让 Veritas 在内测 happy path 中显著增强图像操控风险发现能力。
2. 将视觉证据从“图片文件列表”升级为“可回溯的 figure/panel/evidence graph”。
3. 让 ELIS-style 工具输出变成候选事实、人工复核任务和报告证据，而不是最终诚信裁决。
4. 保持现有 `audit-paper` 主链路稳定：视觉重型工具失败时不阻断基础报告。
5. 为 Web P1 增加可演示的 Visual Forensics Gallery，而不是完整复制 ELIS 图库产品。

## Non-Goals

- 不直接运行或嵌入 ELIS 的完整 FastAPI/Celery/MongoDB/Redis 主服务。
- 不把 ELIS 全局图库、账号、配额、任务系统替换 Veritas Web。
- 不在第一阶段做跨论文全库检索；优先做 single-paper internal similarity。
- 不把 copy-move、TruFor、CBIR 分数写成最终学术不端结论。
- 不自动修改论文、图片、Source Data 或报告结论。
- 不把湿实验、临床试验、材料科学等完整扩展为新产品范围。
- 不承诺所有 Docker/GPU/Milvus 工具在任意环境都可用。

## Success Metrics

### Phase 1 成功标准（必须）

- **Pipeline 成功率**：基础 `audit-paper` 在无重型视觉依赖环境中 100% 完成报告生成；视觉工具状态 100% 清晰标记为 skipped/not_available/failed
- **证据可追溯性**：100% 的 visual findings 能回链到 panel id、原始图片、工具输出、参数、score、人工复核问题
- **Panel extraction 准确率**：多 panel 图的 panel 切分准确率 > 80%（通过人工复核验证）
- **Copy-move 检测准确率**：> 70%（panel-level，通过 fixture 验证）
- **误报率控制**：< 30%（良性解释：legal controls, repeated templates, legends, axes, scale bars）
- **报告体验**：HTML 报告包含 Visual Evidence Package 章节，展示 Top visual findings、overlay 缩略图和人工复核 checklist
- **Web Gallery**：operator 可在 Visual Forensics Gallery 中查看 figure/panel、工具状态、相似关系和复核任务
- **风险语言**：报告中 0 处”确认造假/学术不端成立”等越界措辞
- **Fixture 验证**：2-3 个真实论文 fixture + 1-2 个合成 fixture 能正确检测出已知问题

### Phase 2 成功标准（如果实施）

- **TruFor 可用性**：如果有 GPU，TruFor 能生成 heatmap，标注伪造区域
- **YOLO panel extraction**：如果传统 CV 准确率 < 70%，YOLO CPU 版本准确率 > 85%
- **CBIR**：跨论文检索能正确识别相似 panel

### 量化指标

| 指标 | Phase 1 目标 | Phase 2 目标 |
|---|---|---|
| Pipeline 成功率 | 100%（基础报告） | 100%（基础报告） |
| Visual findings 可追溯性 | 100% | 100% |
| Panel extraction 准确率 | > 80%（传统 CV） | > 85%（YOLO CPU，如果需要） |
| Copy-move 检测准确率 | > 70%（panel-level） | > 80%（panel-level + TruFor） |
| 误报率 | < 30% | < 20% |
| 报告越界措辞 | 0 处 | 0 处 |
| Fixture 验证通过率 | 100%（3-5 个 fixture） | 100%（5-10 个 fixture） |

## User Stories

### P0 必须（Phase 1，解决核心视觉取证能力）

1. **[P0] As a PI**, I want to see the highest-risk image manipulation candidates first, so that I know what to ask the student before submission.
2. **[P0] As a PI**, I want every visual concern to link back to the original figure, so that I can verify the concern in the paper context.
3. **[P0] As a PI**, I want the report to separate consistency, matching, and completeness issues, so that image concerns are not mixed with lower-priority material gaps.
4. **[P0] As a PI**, I want copy-move findings to include marked regions or overlays, so that I can understand the suspicious visual pattern quickly.
5. **[P0] As a PI**, I want benign explanations listed beside each image finding, so that normal reuse, controls, or parser artifacts are considered before escalation.
6. **[P0] As an internal operator**, I want visual tools to run through the existing audit pipeline, so that I do not manage a separate ELIS job manually.
7. **[P0] As an internal operator**, I want heavy visual tools to fail independently, so that a missing GPU or Docker image does not destroy the whole audit.
8. **[P0] As an internal operator**, I want a clear manifest of which visual tools ran, skipped, reused, or failed, so that I can explain report limitations.
9. **[P0] As an internal operator**, I want visual artifacts to be case-scoped, so that one paper’s images never leak into another paper’s search or report.
10. **[P0] As a student/author**, I want the report to specify the exact figure being questioned, so that I can provide the correct raw image or explanation.

### P1 重要（Phase 2，增强视觉取证体验）

11. **[P1] As a PI**, I want TruFor heatmaps to be shown as screening evidence, so that I can prioritize manual review without treating the model as final judgment.
12. **[P1] As an internal operator**, I want AgentInvestigationPlanner to select only registered visual tools, so that Agent cannot call arbitrary ELIS commands.
13. **[P1] As an internal operator**, I want tool parameters bounded by schema, so that accidental expensive or unsafe visual jobs are rejected.
14. **[P1] As a reviewer**, I want panel extraction to split multi-panel figures into inspectable units, so that duplicated panels are not hidden inside large figure images.
15. **[P1] As a reviewer**, I want each panel to preserve bbox, label, page, figure, caption, and source image references, so that I can audit extraction quality.
16. **[P1] As a reviewer**, I want single-image copy-move and cross-image copy-move separated, so that local duplication and cross-panel reuse have different review workflows.
17. **[P1] As a reviewer**, I want CBIR results represented as image relationships, so that related panels can be reviewed as a graph rather than isolated pairs.
18. **[P1] As a reviewer**, I want tool outputs to include score, method, threshold, model version, and parameters, so that findings remain reproducible.
19. **[P1] As a reviewer**, I want every finding to generate a concrete review question, so that manual review produces actionable next steps.
20. **[P1] As a student/author**, I want the system to distinguish missing raw images from suspicious manipulation, so that material gaps are not overstated as misconduct.

### P2 长期（产品增强和 Web Gallery）

21. **[P2] As a product owner**, I want ELIS capabilities behind first-party adapters, so that Veritas can evolve without becoming an ELIS fork.
22. **[P2] As a product owner**, I want AGPL and module-specific licenses reviewed before commercial use, so that product risk is known early.
23. **[P2] As a product owner**, I want a fixture-backed demo path, so that investor or boss demos do not depend on GPU/Milvus availability.
24. **[P2] As a developer**, I want canonical visual schemas before tool integration, so that each adapter writes compatible artifacts.
25. **[P2] As a developer**, I want adapters to expose a small stable interface, so that Docker wrappers, local mock runners, and future services can be swapped.
26. **[P2] As a developer**, I want visual artifacts merged into the same static audit bundle, so that report rendering does not read random tool JSON directly.
27. **[P2] As a developer**, I want tests around schema, adapter normalization, report rendering, and Web artifact indexing, so that future tool changes do not break the evidence contract.
28. **[P2] As a Web user**, I want a Visual Forensics Gallery inside a case, so that I can browse image evidence without leaving the audit context.
29. **[P2] As a Web user**, I want overlay and heatmap images displayed beside the original panel, so that visual comparison is fast.
30. **[P2] As a Web user**, I want filters for tool status, risk, figure, panel type, and review status, so that large papers remain navigable.
31. **[P2] As a Web user**, I want final HTML reports to include visual evidence summaries, so that a PI can review without opening raw JSON.
32. **[P2] As a reviewer**, I want relationship edges to show source type and weight, so that manual, similarity, provenance, and copy-move relationships are distinguishable.

### Implementation Decisions

#### Product Architecture

- Veritas remains case-first. The primary object is an audit case, not a global image library.
- ELIS is treated as a capability source and architecture reference, not as a product module to mount wholesale.
- Visual tools enter through first-party adapters and Tool Registry. Upper layers do not call ELIS scripts, Docker images, or APIs directly.
- Static audit remains the owner of evidence contracts, orchestration, bundle creation, report rendering, and limitations.
- Web reads indexed artifacts and bundle-derived view models; it does not interpret raw visual tool outputs as product truth.

#### Evidence Model

Add first-class visual evidence concepts:

- `figure_evidence`: canonical figure-level image evidence from PDF parsing or image extraction.
- `panel_evidence`: detected panel crop with bbox, label, parent figure, source image, page, caption, and crop path（**Phase 1 必需**，因为检测粒度是 panel-level）.
- `visual_finding`: a candidate issue produced by copy-move, exact duplicate, dHash, or manual review.
- `image_relationship`: relationship between two panels, with source type, score/weight, source analysis, and review status.

Visual evidence invariants:

- Every panel must reference one parent figure or source image.
- Every visual finding must reference at least one figure or panel.
- Every relationship must reference two distinct panel ids.
- Every tool output must preserve input artifacts, parameters, method/version, status, errors, limitations, and output files.
- No visual finding may appear in the report without evidence refs and a manual review note.

**数据流**：

```text
figure_evidence（整图）
  ↓
panel extraction（传统 CV：边缘检测 + 轮廓分析）
  ↓
panel_evidence（bbox, crop_path, label）
  ↓
panel-level copy-move（SIFT/ORB + RANSAC）
  ↓
image_relationship（事实关系）
  ↓
高 score relationship → visual_finding（候选问题）
```

#### 模块设计：6 个核心模块（支持 6 个 agent 并行）

**为什么是 6 个模块**：每个模块职责清晰，测试覆盖完整，支持 6 个 agent 并行开发，最大化并行度。

1. **Visual Evidence Schema Module**（Agent 1）
   - 职责：定义 figure_evidence、panel_evidence、visual_finding、image_relationship 的 schema
   - 包含：MinerU 输出到 figure_evidence 的映射（Figure canonicalizer）
   - 测试：schema validation tests, canonicalizer tests
   - **依赖**：无（最先开发）
   - **输出**：schema 定义文件，被其他所有模块依赖

2. **Panel Extraction Adapter**（Agent 2）
   - 职责：实现传统 CV panel extraction（OpenCV 边缘检测 + 轮廓分析）
   - 接口：`run(figure_evidence) -> List[panel_evidence]`
   - 测试：fixture-backed tests
   - **依赖**：Visual Evidence Schema（Agent 1）
   - **输出**：panel_evidence artifacts

3. **Copy-Move Adapter**（Agent 3）
   - 职责：实现 panel-level copy-move 检测（SIFT/ORB + RANSAC）
   - 接口：`run(List[panel_evidence]) -> List[image_relationship]`
   - 测试：fixture-backed tests
   - **依赖**：Visual Evidence Schema（Agent 1）
   - **输出**：image_relationship artifacts, overlay images

4. **Visual Finding Pipeline**（Agent 4）
   - 职责：把工具输出转化为 visual findings
   - 包含：relationship builder + finding builder
   - 测试：pipeline tests
   - **依赖**：Visual Evidence Schema（Agent 1）, Panel Extraction（Agent 2）, Copy-Move（Agent 3）
   - **输出**：visual_finding artifacts

5. **Report + Web Gallery**（Agent 5）
   - 职责：把 visual findings 渲染到 HTML 报告和 Web Gallery
   - 包含：HTML visual evidence package + Web Visual Forensics Gallery
   - 测试：report rendering tests, Web artifact tests
   - **依赖**：Visual Evidence Schema（Agent 1）, Visual Finding Pipeline（Agent 4）
   - **输出**：HTML report section, Web Gallery UI

6. **Fixture Preparation**（Agent 6）
   - 职责：准备真实论文 fixture 和合成 fixture
   - 包含：fixture validation tests
   - **依赖**：Visual Evidence Schema（Agent 1）
   - **输出**：fixture files, validation tests

#### AGPL 许可证处理（决策已冻结）

**核心决策**：**不直接依赖 ELIS 代码，自己实现所有视觉工具。**

**理由**：
- ELIS 是 AGPLv3，subprocess 调用仍可能被视为衍生作品
- 商业化风险：如果 Veritas 未来要商业化，AGPL 依赖会阻碍融资或收购
- 控制力：自己实现可以精确控制功能、性能和失败模式

**技术栈**（全部 Apache 2.0 / MIT / BSD）：
- OpenCV（Apache 2.0）：特征匹配、边缘检测、轮廓分析
- scikit-image（BSD）：图像处理
- Pillow（MIT）：图像加载和保存
- NumPy（BSD）：数值计算

**不使用**：
- YOLO（AGPL/GPL）：避免许可证风险；用传统 CV 替代
- ELIS 代码（AGPL）：避免衍生作品风险
- GPU 依赖（CUDA/cuDNN）：内测环境无 GPU

**借鉴 ELIS 的内容**：
- 设计思路（panel-level 检测、relationship graph、visual evidence package）
- 算法思路（SIFT/ORB 特征匹配、RANSAC、边缘检测）
- 交互模式（gallery、overlay 比较、manual review checklist）
- 但不复制任何代码

#### Tool Registry

Register visual tools with bounded parameters and explicit execution phases:

- Figure evidence canonicalization as **mandatory** step after PDF parsing.
- Panel extraction（传统 CV）as **mandatory**, deterministic tool（所有论文都跑）.
- Copy-move（panel-level, SIFT/ORB + RANSAC）as deterministic, **agent-selectable**（Agent 根据论文类型决定是否运行）.
- Exact duplicate detection（hash-based）as mandatory.
- dHash near-duplicate detection as mandatory.

Tool outputs should append artifacts, not overwrite baseline outputs.

**Agent 工具选择逻辑**：
- Panel extraction 是基础能力，所有论文都跑（mandatory）
- Copy-move 可根据论文类型、领域、图像数量决定是否运行（agent-selectable）
- 未来如果有 VLM，可以先用 VLM 初筛可疑 figure，再跑 copy-move

#### Agent Behavior

AgentInvestigationPlanner may:

- Select visual tools from Tool Registry.
- Provide hypotheses, input artifact dependencies, and bounded params.
- Decide whether to stop after no new visual evidence.
- Explain tool output and generate review questions.

Agent may not:

- Call ELIS directly.
- Treat heatmaps or similarity scores as final misconduct judgments.
- Invent figure/panel ids not present in canonical evidence.
- Promote skipped or failed visual tools into findings.

#### Reporting

HTML report adds a Visual Evidence Package:

- Visual risk summary.
- Top visual findings.
- Panel evidence cards（Phase 1 必需）.
- Original image vs overlay comparison.
- Relationship table or graph summary.
- Tool status and limitations.
- Manual review checklist.

Findings remain grouped by issue category:

- copy-move, local reuse, exact duplicate, high-confidence suspicious relationship -> `consistency`.
- caption/label/claim mismatch against figure or Source Data -> `matching`.
- missing raw image, missing Source Data for figure, unsupported visual tool -> `completeness`.

**报告语言风险控制**（决策已冻结）：

**策略**：模板约束 + 词库检查 + 人工审核。

```python
# 软件层面的约束
FINDING_TEMPLATES = {
    "copy_move_high_score": {
        "risk_level": "high",
        "description": "Panel A 和 Panel B 存在高度相似的图像特征（相似度 {score:.2f}），可能存在复制粘贴。",
        "benign_explanations": [
            "合法的实验对照（如 loading control）",
            "重复的模板结构（如 gel lane layout）",
            "图像处理的 artifacts（如 background subtraction）"
        ],
        "review_question": "请确认 Panel A 和 Panel B 是否来自不同的实验区域，或者是否存在合法的重复模式？",
        "action": "要求学生提供原始图像或解释"
    }
}

# 禁止的措辞
FORBIDDEN_PHRASES = [
    "确认造假", "学术不端成立", "数据伪造", "故意篡改",
    "misconduct confirmed", "fabrication detected", "falsification proven"
]

# 允许的措辞
ALLOWED_PHRASES = [
    "高度可疑", "可能存在复制粘贴", "需要人工复核",
    "无法排除良性解释", "建议进一步核实",
    "highly suspicious", "potential copy-move", "requires manual review"
]
```

**最终靠人工审核**：软件只标记可疑的，不判定最终结论。

#### Web Experience

Web P1 exposes a case-scoped Visual Forensics Gallery（**Phase 1 必需**）:

- Figure/panel grid.
- Tool status badges.
- Filters for figure, panel type, risk, relationship source, review status.
- Original/overlay comparison.
- Relationship list or lightweight graph.
- Manual review task list.
- Link back to final report.

**为什么 Web Gallery 是 Phase 1 必需**（决策已冻结）：
- 需要交互式演示给老板和 PI
- PI 需要快速浏览和筛选大量 panel
- HTML 报告不够灵活，无法支持交互式探索
- Web Gallery 可以和 HTML 报告并行开发（Agent 5）

Web should not expose full ELIS Advanced Lab to PI users in the first iteration. Advanced parameter tuning stays operator/admin-only or remains CLI-only.

### Licensing And Deployment（决策已冻结）

**核心决策**：不直接依赖 ELIS 代码，自己实现所有视觉工具。

**技术栈**（全部 Apache 2.0 / MIT / BSD）：
- OpenCV（Apache 2.0）：特征匹配、边缘检测、轮廓分析
- scikit-image（BSD）：图像处理
- Pillow（MIT）：图像加载和保存
- NumPy（BSD）：数值计算

**部署约束**：
- CPU-only：内测环境无 GPU，不依赖 CUDA/cuDNN
- 不使用 YOLO（AGPL/GPL）：避免许可证风险
- 不使用 ELIS 代码（AGPL）：避免衍生作品风险
- Docker 镜像名称、超时和依赖可用性必须配置驱动，报告中敏感信息需脱敏

**借鉴 ELIS 的边界**：
- 可以借鉴：设计思路、算法思路、交互模式
- 不能复制：任何 ELIS 代码
- 必须自己写：所有视觉工具的实现

## Phasing

### Phase 0: Schema Freeze（3 天）

**目标**：冻结 schema 和接口契约，为 6 个 agent 并行开发铺平道路。

**交付物**：
1. **Canonical Visual Schema**
   - 定义 figure_evidence、panel_evidence、visual_finding、image_relationship 的 schema
   - Schema validation tests
   - 接口契约文档（每个模块的输入/输出）

2. **Fixture Specification**
   - 定义 fixture 格式和验证标准
   - 准备 1 个最小 fixture 用于早期测试

**时间**：3 天（不需要 1 周，因为许可证决策已冻结）

### Phase 1: Panel-Level 视觉取证闭环（3 周）

**目标**：实现 panel-level copy-move 检测，产出可复核的视觉证据包。

**开发模式**：6 个 agent 并行，最大化并行度。

**Agent 执行依赖图**：

```text
Week 1:
  Agent 1 (Schema) ─────────────────────────────────┐
       ↓                                            │
  Agent 2 (Panel Extraction) ─┐                    │
  Agent 3 (Copy-Move) ────────┤                    │
  Agent 6 (Fixture) ──────────┘                    │
                                                   ↓
Week 2:                                       Agent 4 (Finding Pipeline)
                                                   ↓
Week 3:                                       Agent 5 (Report + Web Gallery)
                                                   ↓
                                              Integration + Testing
```

**详细依赖**：
- Agent 1 (Schema): 无依赖，最先开发
- Agent 2 (Panel Extraction): 依赖 Agent 1 的 schema
- Agent 3 (Copy-Move): 依赖 Agent 1 的 schema
- Agent 4 (Finding Pipeline): 依赖 Agent 1, 2, 3
- Agent 5 (Report + Web Gallery): 依赖 Agent 1, 4
- Agent 6 (Fixture): 依赖 Agent 1 的 schema

**交付物**：

1. **Visual Evidence Schema Module**（Agent 1）
   - 实现 figure_evidence, panel_evidence, visual_finding, image_relationship schema
   - 实现 MinerU 输出到 figure_evidence 的映射
   - Schema validation tests

2. **Panel Extraction Adapter**（Agent 2）
   - 实现传统 CV panel extraction（OpenCV 边缘检测 + 轮廓分析）
   - 输出 panel_evidence
   - Fixture-backed tests
   - 目标准确率 > 80%

3. **Copy-Move Adapter**（Agent 3）
   - 实现 panel-level copy-move 检测（SIFT/ORB + RANSAC）
   - 输出 overlay 图像和 image_relationship
   - Fixture-backed tests

4. **Visual Finding Pipeline**（Agent 4）
   - 实现 relationship builder：copy-move 输出 → image_relationship
   - 实现 finding builder：高 score relationship → visual_finding
   - Pipeline tests

5. **Report + Web Gallery**（Agent 5）
   - HTML 报告增加 Visual Evidence Package 章节
   - 实现 Web Visual Forensics Gallery（交互式）
   - Report rendering tests + Web artifact tests

6. **Fixture Preparation**（Agent 6）
   - 准备 2-3 个真实论文 fixture（retracted papers）
   - 准备 1-2 个合成 fixture
   - Fixture validation tests

**验证标准**：
- `audit-paper` 能生成包含 visual evidence 章节的 HTML 报告
- Panel extraction 准确率 > 80%（清晰 panel 布局）
- Copy-move 能检测出 fixture 中的已知案例
- Overlay 图像能正确标注 copy-move 区域
- Web Gallery 能正常展示 figure/panel/overlay
- 报告中没有"确认造假"等越界措辞
- 视觉工具失败不会阻断基础报告生成

### Phase 2: 增强视觉取证（可选）

**目标**：如果 Phase 1 验证需要，接入 TruFor（如果有 GPU）或 CBIR。

**决策点**：Phase 1 完成后评估：
- 如果传统 CV 的 panel extraction 准确率 < 70%，考虑接入 YOLO CPU 版本
- 如果有 GPU 且需要 heatmap 检测，接入 TruFor
- 如果需要跨论文检索，接入 CBIR/Milvus

## Acceptance Criteria

- Running `audit-paper` on a paper with extracted images produces canonical figure evidence.
- If panel extraction runs, every panel has a parent figure/source image, bbox, crop path, and stable panel id.
- If exact duplicate, dHash, CBIR, or cross-copy-move finds a pair, the output becomes an image relationship.
- If copy-move or TruFor produces overlays/heatmaps, the output becomes a visual finding candidate with evidence refs.
- Tool failures are visible in manifest, investigation records, bundle limitations, and report limitations.
- Agent visual tool choices are rejected unless the tool is deterministic and registered.
- The HTML report includes a visual evidence section even when all heavy tools are skipped, with honest limitations.
- Web can list and display visual artifacts without reading outside the case/output roots.
- Tests cover schema validation, adapter normalization, Tool Registry validation, report rendering, and Web artifact indexing.

## Testing Decisions

Good tests should verify external behavior and artifact contracts, not private implementation details.

Required tests:

- Visual schema tests: valid and invalid figure, panel, finding, relationship objects.
- Canonicalizer tests: fixture MinerU images become stable figure evidence.
- Adapter normalization tests: fixture ELIS-style panel/copy-move/TruFor/CBIR outputs become Veritas artifacts.
- Tool Registry tests: visual tools appear only with allowed phase, parameter bounds, and expected outputs.
- Orchestrator tests: skipped/failed visual tools do not block report generation.
- Investigation tests: Agent-selected visual actions require existing artifacts and valid expected evidence type.
- Report tests: visual findings render with evidence refs, limitations, and manual review actions.
- Web artifact tests: visual evidence package is indexed and served only through case-safe artifact ids.
- Golden fixture test: one small paper/image fixture produces a stable visual evidence package and static HTML section.

Mocking policy:

- Mock Docker, GPU, Milvus, network, and file-system-heavy external calls.
- Do not mock schema validation, artifact normalization, bundle merging, report rendering, or Web artifact indexing.

## Risks

- AGPL/module licenses may restrict direct code reuse or commercial deployment.
- TruFor and CBIR may require GPU, large images, models, Docker, or Milvus; availability will vary across internal environments.
- Panel extraction can introduce false bbox boundaries, especially for complex figure layouts.
- Copy-move and similarity tools can produce false positives for legal controls, repeated templates, legends, axes, scale bars, and batch layouts.
- Heatmaps can be over-interpreted by non-expert readers; report language must stay cautious.
- Large papers may generate many panels and relationships; Web needs filtering and result caps.

## Open Questions（已关闭）

以下问题已在 2026-06-12 决策冻结中关闭：

| 问题 | 决策 | 理由 |
|---|---|---|
| First internal beta should execute which heavy tools by default? | Panel extraction (mandatory) + copy-move (agent-selectable) | Panel extraction 是基础能力；copy-move 可根据论文类型决定 |
| CBIR should use Milvus in beta, or stay with local/dHash? | Phase 1 只用 dHash，Phase 2 再考虑 CBIR/Milvus | 简化依赖，聚焦核心能力 |
| Should visual tools run automatically for all figures, or only after Agent/operator selects? | Panel extraction mandatory, copy-move agent-selectable | 平衡检测覆盖度和性能 |
| What is the first demo fixture for visual evidence? | 真实论文（retracted papers）+ 合成 fixture | 真实论文反映实际问题；合成 fixture 用于单元测试 |
| How much of ELIS frontend interaction should be borrowed? | 借鉴设计思路，但自己实现 Web Gallery | 避免 AGPL 风险；保持 Veritas 产品语言 |

### 执行依赖图（6 个 agent 并行）

```text
Phase 0: Schema Freeze (3 days)
  └─ Agent 1 (Schema) ─────────────────────────────────────────────┐
       ↓                                                            │
Phase 1 Week 1:                                                    │
  ├─ Agent 2 (Panel Extraction) ──┐                               │
  ├─ Agent 3 (Copy-Move) ─────────┤ 依赖 Agent 1                  │
  └─ Agent 6 (Fixture) ───────────┘                               │
       ↓                                                            │
Phase 1 Week 2:                                                    │
  └─ Agent 4 (Finding Pipeline) ──┐                               │
       ↓                          依赖 Agent 1, 2, 3              │
Phase 1 Week 3:                                                    │
  └─ Agent 5 (Report + Web) ──────┘                               │
       ↓                          依赖 Agent 1, 4                 │
Integration + Testing                                              │
```

**最大化并行度的关键**：
- Agent 1 必须先完成 schema 定义（Phase 0）
- Agent 2, 3, 6 可以在 Week 1 并行开发
- Agent 4 需要等 Agent 2, 3 完成
- Agent 5 需要等 Agent 4 完成
- Agent 6 只依赖 schema，可以早期并行

**接口契约**（Phase 0 交付）：
- `figure_evidence` schema：Agent 1 → Agent 2, 3, 6
- `panel_evidence` schema：Agent 1 → Agent 3, 4
- `image_relationship` schema：Agent 1 → Agent 4
- `visual_finding` schema：Agent 1 → Agent 4, 5
- Fixture 格式：Agent 6 → Agent 2, 3, 4

## Out Of Scope

- Full ELIS product migration.
- Global image provenance database.
- Multi-tenant SaaS image library.
- User-authored visual annotations as primary evidence.
- Watermark removal in the first Veritas visual beta.
- OpenAlex or external literature graph integration.
- Automated final misconduct determination.
- Wetlab-wide product expansion beyond the current dry-experiment-focused Veritas positioning.

## Further Notes

This PRD intentionally puts schema and evidence graph ahead of tool integration. The product value is not “we can call ELIS tools”; it is “Veritas can turn image forensic signals into cautious, traceable, PI-actionable review evidence inside the same audit report.”

The first engineering slice should be small: canonical visual evidence + panel extraction + panel-level copy-move + report visual section + Web Gallery. That gives a stable surface for future enhancements (TruFor, CBIR, YOLO) without risking the existing `audit-paper` happy path.

**决策冻结日期**：2026-06-12
**下一步**：进入规划执行环节，按 6 个 agent 并行开发，3 周完成 Phase 1。
