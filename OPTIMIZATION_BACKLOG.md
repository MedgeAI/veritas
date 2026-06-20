# OPTIMIZATION_BACKLOG.md

Updated: 2026-06-17（经 grilling 决策校准版）

基于 `outputs/case-20260616T154322Z-d693198d/research-integrity-audit` 的实际产物审计、2026-06-17 代码核实、以及 grilling 决策会话。

**本文件是下一个实现 Agent 的操作上下文。** 所有架构决策已锁定，实现 Agent 按 4 阶段顺序执行，不要重新讨论已锁定的决策。

---

## 项目范围澄清

**关键修正**：Veritas 聚焦的"干实验生物信息学论文"**包含**使用流行病学/临床试验数据的计算论文（横断面研究、病例对照、队列研究、TCGA/GEO 临床数据分析等）。PaperFraud `study_design.yaml` 的所有规则对 Veritas 全部相关，不禁用任何规则。

需要更新 `AGENTS.md` 中"当前聚焦干实验论文"的描述，明确包含流行病学/临床试验数据分析。

---

## 已锁定决策清单

以下决策已经过 grilling 确认，实现 Agent 直接执行，不重新讨论。

### D-1. paper_figure_label schema 字段 + 裁剪文件命名

**决策**：在 `panel_evidence` schema 中新增 `paper_figure_label` 字段（如 "Figure 3b"），来源为 MinerU evidence ledger 或 caption mapping。

**文件名格式**：`{paper_figure_label}_panel{idx:02d}_{modality}.png`
- 有 label：`Fig3b_p01_Blots.png`
- 无 label 退回：`figure-content-0097_p01_Graphs.png`

**消费方**：文件名、HTML renderer、Web gallery、finding pipeline 统一使用 `paper_figure_label`。

**涉及文件**：
- `engine/static_audit/tools/panel_extraction.py` — 生成 paper_figure_label、修正裁剪文件名
- `engine/static_audit/models.py` 或 schema 定义 — 新增 paper_figure_label 字段
- `engine/static_audit/html_report/_core.py` — 渲染 paper_figure_label
- `web/frontend/` — 展示 paper_figure_label

### D-2. 5-class YOLOv5 模型

**决策**：使用 `models/panel_extraction/model_5_class.pt`。

**5 类标签**：`Blots`, `Graphs`, `Microscopy`, `Body Imaging`, `Flow Cytometry`

**涉及文件**：
- `engine/static_audit/tools/panel_extraction.py` — 模型路径指向 5-class

### D-3. 双维风险模型

**决策**：替代当前一维 `score_to_risk_level()`，引入 modality_weight：

```
final_risk_score = raw_score × modality_weight[panel_type]
```

| modality | weight | 理由 |
|---|---|---|
| Blots | 1.0 | 主要造假目标 |
| Microscopy | 0.9 | 克隆细胞/组织区域 |
| Body Imaging | 0.6 | 大体图像有篡改可能 |
| Flow Cytometry | 0.2 | 类似 Graph 的几何图案 |
| Graphs | 0.2 | 坐标轴/曲线天然重复 |
| unknown/None | 0.5 | 保守，不 escalation 到 critical |

**涉及文件**：
- `engine/static_audit/visual_constants.py` — `score_to_risk_level()` 重构为 `compute_risk_level(score, modality)`
- `engine/static_audit/tools/visual_finding_pipeline.py` — 传入 panel_type

### D-4. ExecutionPhase 枚举

**决策**：替代 `agent_selectable` 布尔值，引入 `ExecutionPhase` 枚举：

```python
class ExecutionPhase(str, Enum):
    MANDATORY_BASELINE   = "mandatory_baseline"   # 无条件运行
    CONDITIONAL_BASELINE = "conditional_baseline"  # 有前置条件时运行
    AGENT_SELECTABLE     = "agent_selectable"       # 只通过 investigation round
    REPORT_ONLY          = "report_only"            # 消费已有 artifact
```

**映射**：
- `tru_for`, `provenance_graph` → `MANDATORY_BASELINE` + `agent_selectable=False`
- `source_data.*` → `CONDITIONAL_BASELINE`
- `copy_move`, `image_similarity`, `sila_dense`, `paperconan` → `AGENT_SELECTABLE`
- `finding_pipeline`, `report` → `REPORT_ONLY`

**涉及文件**：
- `engine/tools/registry.py` — ToolDefinition 新增 execution_phase，更新 agent_selectable
- `engine/investigation/validators.py` — 清理废弃的 ALLOWED_STEPS 或对齐
- `engine/static_audit/orchestrator.py` — dispatch 逻辑对齐

### D-5. TruFor 三层判断

**决策**：TruFor 保持 `MANDATORY_BASELINE`，启动时：
1. 检查 `timm` — 缺失 → 加入 pyproject.toml，`make sync` 安装
2. 检查模型权重 `models/trufor/trufor.pth.tar` — 缺失 → 整体 `skipped`，写一条 limitation
3. GPU/CPU — 有 GPU 用 GPU，无 GPU 用 CPU（不因缺 GPU skip）

**禁止**：对 254 张图逐张报同一错误。整体 skip 时只产生一条 limitation。

**涉及文件**：
- `engine/static_audit/tools/tru_for.py` + `_elis_trufor_runner.py`
- `pyproject.toml` — 添加 `timm` 依赖
- `Makefile` — 预留权重初始化入口

### D-6. PaperFraud 全量吸收 + text_evidence

**决策**：
- `text_evidence` 作为第五种证据类型（与 `file_evidence`、`figure_evidence`、`execution_evidence`、`claim_match` 并列）
- 有 excerpt 的 rule → 生成 Finding，`evidence_refs` 指向 `full.md` 文本位置，`evidence_source: "text_match"`
- 无 excerpt 的 rule → 写入 `methodology_checklist.json`，不进 findings
- 所有 rule_type（fraud_detection + methodology_review）全部保留

**涉及文件**：
- `engine/static_audit/tools/paperfraud_rules.py` — `paperfraud_findings_from_matches()` 生成 evidence_refs
- `engine/static_audit/models.py` — Finding model 新增 evidence_source 字段
- Evidence schema — 新增 text_evidence 类型

### D-7. pgvector 替代 dhash

**决策**：
- provenance graph 候选搜索从 dhash 改为 SSCD embedding + pgvector cosine similarity
- SSCDEncoder 从 `web/backend/` 下沉为 shared module（`engine/` 或 `web/shared/`）
- CLI 不强依赖 PG：embedding 先存 `visual/image_embeddings.json` artifact，有 PG 连接时同时写入 pgvector
- pgvector 扩展注册失败 → raise，不 warn-and-continue

**涉及文件**：
- `web/backend/veritas_web/embeddings.py` → 移到 `engine/embeddings/` 或 `engine/shared/`
- `engine/static_audit/tools/provenance_graph.py` — 接入 SSCDEncoder + pgvector/JSON
- `web/backend/veritas_web/database.py` — `_register_vector_extension` 改为 raise
- `engine/tools/image_similarity.py` — 输出 canonical ID（D-8）

### D-8. image_similarity canonical ID

**决策**：`image_similarity.py` 输出从 `left_image`/`right_image`（绝对路径）改为 `source_figure_id`、`source_panel_id`、`target_figure_id`、`target_panel_id`。

**涉及文件**：
- `engine/static_audit/tools/image_similarity.py` — 输出 schema 改造
- `engine/static_audit/tools/visual_finding_pipeline.py` — 消费 canonical ID，移除 `_lookup_panel_id()` 模糊路径匹配

### D-9. SSCD 依赖策略

**决策**：PyTorch 缺失 → 直接失败（非 graceful skip）。SSCD 是基础设施级依赖，不是可选增强。

---

## 4 阶段执行计划

### 阶段 1 — 停止制造假阳性

**目标**：消除当前最大的视觉证据噪声源。

| 任务 | 涉及文件 | 验收标准 |
|---|---|---|
| 修 panel_extraction 裁剪文件名（D-1） | `panel_extraction.py` | fallback panel 裁剪图不再叫 `a.png`，而是 `{figure_id}_panel{idx:02d}.png` |
| 新增 paper_figure_label schema 字段（D-1） | `models.py` / schema | panel_evidence 有 paper_figure_label 字段 |
| 接入 5-class 模型（D-2） | `panel_extraction.py` | 模型路径指向 model_5_class.pt |
| 双维风险模型（D-3） | `visual_constants.py`, `visual_finding_pipeline.py` | Graph panel score=1.0 → risk ≤ medium |
| image_similarity canonical ID（D-8） | `image_similarity.py`, `visual_finding_pipeline.py` | 输出无绝对路径 panel id |

**不可修改的验收资产**：
- `tests/fixtures/visual/` 下的 synthetic fixture 和 ground_truth.json
- schema test 中 panel_evidence 的已有必选字段

### 阶段 2 — 证据链闭合

**目标**：确保所有 finding 有 evidence refs，Agent/Registry/orchestrator 口径一致。

| 任务 | 涉及文件 | 验收标准 |
|---|---|---|
| ExecutionPhase 枚举（D-4） | `registry.py`, `validators.py`, `orchestrator.py` | context pack 工具列表与 orchestrator dispatch 一致 |
| PaperFraud text_evidence（D-6） | `paperfraud_rules.py`, `models.py` | 有 excerpt 的 rule → evidence_refs 非空；无 excerpt → checklist only |
| overlay 路径唯一性（D-1 延伸） | `copy_move_detection.py` 或 `panel_extraction.py` | 每条 relationship 有唯一 overlay/mask 路径 |
| 更新 AGENTS.md 范围描述 | `AGENTS.md` | 明确包含流行病学/临床试验论文 |

**不可修改的验收资产**：
- Tool Registry 中已有 tool_id 的命名和语义
- Evidence First 不变量：finding 必须回指结构化 evidence event

### 阶段 3 — 基础设施

**目标**：修好 TruFor、provenance graph、embedding pipeline。

| 任务 | 涉及文件 | 验收标准 |
|---|---|---|
| TruFor 三层判断（D-5） | `tru_for.py`, `_elis_trufor_runner.py`, `pyproject.toml` | 缺权重 → 一条 limitation，不刷重复错误 |
| SSCDEncoder 下沉为 shared module（D-7） | `engine/embeddings/` | CLI 和 Web 都能 import SSCDEncoder |
| pgvector 错误修复（D-7） | `database.py` | 扩展注册失败 → raise |
| provenance graph 接入 embedding（D-7） | `provenance_graph.py` | 用 SSCD embedding + pgvector/cosine 替代 dhash |
| SSCD 依赖策略（D-9） | 启动逻辑 | PyTorch 缺失 → 直接失败 |

**不可修改的验收资产**：
- `docker-compose.yml` 的 pgvector 镜像配置
- 现有 PG schema 中非 embedding 相关的表

### 阶段 4 — 验证闭环

**目标**：用测试和重跑证明前 3 阶段的修复有效。

| 任务 | 验收标准 |
|---|---|
| fixture/golden tests | Graph/KM 负例不进 critical copy-move |
| panel extraction golden test | YOLOv5 对 fixture 图片的提取结果与 ground truth 一致 |
| TruFor skip fixture test | 缺权重时产出 skipped + 一条 limitation |
| PaperFraud text_evidence test | 有 excerpt 的 rule 产出的 finding 有 evidence_refs |
| 重跑真实 case | HTML 报告包含 Top visual findings 的图片证据 |
| ClaimExtractor 回归测试 | 工具 finding 不进入 canonical claims |
| overlay 唯一性 test | relationship_count == unique(mask relationship mapping) |

---

## 最低验收清单（更新版）

下一次同类 case 至少要满足：

- [ ] `final_audit_report.html` 包含 Top visual findings 的图片、panel crop、overlay，且有回归测试覆盖
- [ ] `visual/relationships.json` 没有绝对路径形式的 panel id
- [ ] Graph/Kaplan-Meier panel 不会进入 critical copy-move（modality_weight 生效）
- [ ] 每条 high/critical visual finding 有唯一 artifact refs
- [ ] TruFor 成功产出 heatmap，或明确整体 skipped（一条 limitation）
- [ ] Agent investigation 里没有 unsupported action 被标 accepted
- [ ] `static_audit_bundle.claims` 是论文 claim，不是工具 finding（回归测试守住）
- [ ] Top priority findings 优先展示 Source Data consistency、视觉证据和 text_evidence
- [ ] 所有正式 finding 有 evidence_refs；PaperFraud 无 excerpt 的规则只进入 checklist
- [ ] provenance graph 使用 SSCD embedding，edges > 0（若有相似图像）或明确 limitation
- [ ] pgvector 扩展注册失败时 CLI 和 Web 都立即报错

---

## 不再作为当前缺陷的已校准项

### C-1. Visual HTML 渲染

当前 `engine/static_audit/html_report/_core.py` 已有 `_visual_figure_cards()`、`_visual_finding_cards()` 和 review queue 渲染。需重跑真实 case 验证（阶段 4），不作为当前代码缺陷。

### C-2. ClaimExtractor finding 污染

当前 `roles.py` 中 `ClaimExtractor.input_artifacts = ("full.md", "evidence_ledger.json")`，不从工具 finding 包装 claim。需加回归测试守住（阶段 4），不作为当前代码缺陷。

### C-3. ALLOWED_STEPS 废弃

`engine/investigation/validators.py` 中的 `ALLOWED_STEPS` 常量无活跃代码引用，实际 Agent 工具准入来自 `registry.py` 的 `tool_catalog_for_investigation()`。D-4 的 ExecutionPhase 枚举将正式替代此废弃常量。

---

## 技术决策备注

### 关于"提早报错"原则的一致性

| 组件 | 缺依赖行为 | 理由 |
|---|---|---|
| SSCD embedding | PyTorch 缺失 → 硬失败 | 基础设施级依赖，环境应该完整 |
| pgvector 扩展 | 注册失败 → raise | 基础设施级依赖 |
| TruFor | 缺权重 → graceful skip | 可选数据，权重不一定有 |
| TruFor timm | pip install | 硬依赖，`make sync` 解决 |
