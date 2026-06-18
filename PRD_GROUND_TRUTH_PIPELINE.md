# PRD: Ground Truth → Detection Capability Pipeline

> **状态**: Draft v2 (简化版)
> **目标**: 将"从单一案例提炼通用检测能力"的模式抽象为可重复、可扩展的工程流程

---

## 1. 问题陈述

Veritas 的检测能力需要持续增强。PubPeer、Retraction Watch、作者勘误等外部信号包含高价值的 ground truth——**真实造假模式的具体描述**。当前手动分析案例、识别缺口、实现检测器的过程需要系统化。

**核心约束**: 每个 ground truth 案例必须产出**通用检测原语**，不允许为特定论文写特判逻辑。

## 2. 设计目标

| 目标 | 说明 |
|------|------|
| **可重复** | 相同类型的 ground truth 输入触发相同的分析和实现流程 |
| **不过拟合** | 产出的检测器对任意论文有效，不对特定案例硬编码 |
| **可追溯** | 每个检测能力可回溯到哪些 ground truth 案例驱动了它的设计 |
| **可验证** | 每次增强后自动验证：ground truth 案例命中率 + 回归测试 + 对照论文验证 |
| **可组合** | 新的检测原语可插入现有 pipeline，不需要重构上下游 |

## 3. 与现有系统的关系

### 3.1 Capability Catalog 与 Tool Registry 的关系

```
engine/tools/registry.py          ← 可执行工具的注册表（source of truth）
  ↓ 关联 capability_id
capabilities/capability_catalog.yaml ← 能力元数据（provenance、演化历史）
```

- `registry.py`：管执行边界（tool_id、参数约束、输出契约）
- `capability_catalog.yaml`：管能力演化（版本、provenance、测试覆盖）
- 两者通过 `capability_id` 关联，不维护重复数据

### 3.2 Pipeline 在系统中的位置

```
audit-paper happy path
  ↓ 产出结构化 findings
  ↓
ground truth pipeline
  ↓ 对比 findings vs ground truth claims
  ↓ 识别 gap
  ↓ 设计 + 实现新能力
  ↓ 更新 registry + capability_catalog
  ↓
audit-paper happy path（增强后）
```

## 4. Pipeline 设计（5 阶段）

```
┌─────────────────────────────────────────────────────────────┐
│ Phase 1: PARSE + MAP                                         │
│   PubPeer post → structured claims → capability mapping      │
│   输出: [{claim, mapped_capability, detected: bool}]         │
│   关键: LLM extraction + 人工确认，定义最小可执行规格          │
└───────────────────────────┬─────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Phase 2: GAP ANALYSIS                                        │
│   detected=false 的 claims → gap 分类:                       │
│   A. NEW_DETECTOR — 需要新的检测工具                          │
│   B. CALIBRATION — 现有工具参数/阈值需要调整                   │
│   C. INTEGRATION — 数据流断裂（产出没被消费）                  │
│   D. COVERAGE — 输入材料缺失                                 │
│   输出: [{gap_type, claim, recommended_action}]              │
└───────────────────────────┬─────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Phase 3: DESIGN (human checkpoint)                           │
│   对每个 gap，设计通用检测原语:                                │
│   - 输入契约（什么数据进来）                                  │
│   - 输出契约（什么 finding 出去）                             │
│   - 反过拟合检查（对随机论文有意义吗？）                      │
│   - 测试契约（基于 ground truth，非实现细节）                 │
│   人工审批后才进入实现                                        │
└───────────────────────────┬─────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Phase 4: IMPLEMENT + REGISTER                                │
│   半自动实现:                                                │
│   - workflow agent 生成代码骨架 + 测试模板                    │
│   - 人工 review 核心逻辑（防止过拟合）                        │
│   - 注册到 registry.py + capability_catalog.yaml             │
│   - 输出: 新工具 + 测试 + registry 更新                      │
└───────────────────────────┬─────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Phase 5: VERIFY                                              │
│   A. 回归测试: make test 全量通过                             │
│   B. Ground truth 重跑: 对该论文的检出率 before vs after      │
│   C. 反过拟合验证: 至少 3 篇论文（1 ground truth + 2 对照）   │
│   D. Lint: ruff 通过                                         │
└─────────────────────────────────────────────────────────────┘
```

## 5. 反过拟合机制（强制约束）

### 5.1 五条规则

| 规则 | 约束 | 执行方式 |
|------|------|----------|
| **通用接口** | 检测器接口必须接受通用输入（任意 XLSX/image dir），不接受特定论文参数 | 代码 review：函数签名中是否有 paper-specific 参数？→ 拒绝 |
| **无硬编码** | 不允许硬编码特定论文的 figure number / sheet name / row offset | 静态分析：代码中是否有 'Fig.7i' / 'MOESM10' / 'row 25' 等字面量？→ 拒绝 |
| **跨论文验证** | 新检测器必须至少在 3 篇论文上验证（1 ground truth + 2 对照） | CI 检查：是否包含对照论文的验证报告？→ 拒绝 |
| **阈值分布** | 阈值必须从统计分布推导，且分布分析文档作为 artifact 提交 | 提交检查：是否包含 `distribution_analysis.md`？→ 拒绝 |
| **测试先行** | 测试必须先于实现创建，且基于 ground truth 契约而非实现细节 | Git 检查：测试文件创建时间 < 实现文件创建时间？→ 警告 |

### 5.2 对照论文要求

- **数量**: 至少 2 篇对照论文
- **选择标准**:
  - 1 篇"正常论文"：已知无问题的 baseline
  - 1 篇"边界论文"：疑似正常但接近边界的 case（用于测试假阳性率）
- **验证指标**:
  - 对照论文的假阳性数 < 阈值（默认 5%）
  - 如果超过阈值，需要调整参数或重新设计

## 6. PubPeer 解析策略

### 6.1 最小可执行规格（Minimum Executable Specification）

每个 claim 必须包含以下字段，否则不予处理：

```yaml
claim:
  type: string              # 必须匹配 capability taxonomy
  target: string            # 论文中的定位（如 "Fig. 4h", "Sheet 3"）
  description: string       # 必须包含可验证的事实
  evidence_type: string     # "image" | "source_data" | "numeric" | "completeness"
```

**description 字段的最小规格**:
- 必须包含可量化的描述（如"90° 旋转"、"1.2 倍"、"完全相同"）
- 不允许主观判断（如"看起来有点奇怪"、"数据似乎不对"）
- 如果原始描述不符合规格，人工确认时必须补充

### 6.2 格式变体处理

常见格式变体及标准化方式：

| 原始表述 | 标准化 |
|---------|--------|
| "Fig. 4h", "Figure 4H", "Fig 4h" | `Fig. 4h` |
| "Extended Data Fig. 4h", "ED Fig. 4h" | `Extended Data Fig. 4h` |
| "Sheet 3", "MOESM10", "Supplementary Table 3" | 保留原始引用，但标准化为 `workbook: sheet` 格式 |
| "rows 21-40", "Rows 21 to 40" | `rows 21-40` |

### 6.3 人工确认环节

- LLM extraction 后**必须人工确认**，确认环节不能跳过
- 确认重点：
  - claim 的 `description` 是否符合最小可执行规格
  - `type` 是否正确匹配 capability taxonomy
  - `target` 是否能唯一定位到论文中的某个元素

## 7. CLI 接口

```bash
# 完整 pipeline
veritas learn-from-ground-truth \
  --pubpeer-url "https://www.pubpeer.com/publications/..." \
  --paper-dir "input/paper2" \
  --output-dir "outputs/ground_truth_learning/paper2" \
  --cross-validate "input/paper1,input/paper3" \
  --interactive  # 人工确认 claim 提取和设计

# 仅分析不实现
veritas learn-from-ground-truth \
  --pubpeer-url "..." \
  --paper-dir "input/paper2" \
  --gap-report-only

# 从手动标注学习
veritas learn-from-ground-truth \
  --annotations "ground_truth/paper3_annotations.yaml" \
  --paper-dir "input/paper3" \
  --cross-validate "input/paper1,input/paper2"
```

## 8. 文件结构

```
engine/
  ground_truth/
    __init__.py
    parser.py              # PubPeer post → structured claims (Phase 1)
    mapper.py              # claims → capability taxonomy mapping (Phase 1)
    gap_analyzer.py        # 未检出 claims → gap 分类 (Phase 2)
    design_spec.py         # 设计规格模板 (Phase 3)
    anti_overfit.py        # 反过拟合检查器 (Phase 5)
    
capabilities/
  capability_catalog.yaml  # 能力元数据（provenance、版本、测试覆盖）
  
ground_truth/              # 本地 ground truth 测试集
  paper2/
    pubpeer_post.md        # 原始 PubPeer 帖子
    annotations.yaml       # 结构化标注
    expected_findings.yaml # 期望检出列表
    distribution_analysis.md # 阈值分布分析（新增能力的 artifact）
  paper3/
    ...
```

## 9. 开放问题决策

| # | 问题 | 决策 | 理由 |
|---|------|------|------|
| Q1 | PubPeer 解析方式 | LLM extraction + **强制人工确认** | 格式多样，纯规则不够；人工确认确保 claim 符合最小可执行规格 |
| Q2 | 反过拟合对照论文来源 | 维护"正常论文"测试集（至少 2 篇） | 需要已知无问题的 baseline + 边界 case |
| Q3 | capability catalog 是否版本化 | 每次增强追加记录 | 需要追溯能力演化历史 |
| Q4 | 实现阶段自动化程度 | **半自动**（agent 生成骨架，人工 review 核心逻辑） | 防止 agent 产出过拟合的检测器 |
| Q5 | ground truth 测试集是否提交 | 只提交 annotations，论文在 input/ 不提交 | 版权风险 |
| Q6 | capability_catalog.yaml 与 registry.py 的关系 | capability_catalog.yaml 是 registry.py 的元数据层，通过 capability_id 关联 | 避免数据重复维护，确保状态一致 |

## 10. 里程碑

| 阶段 | 内容 | 复杂度 | 预计时间 |
|------|------|--------|----------|
| **M1** | `parser.py` + `mapper.py` — PubPeer 解析 + 能力映射 | 中 | 2 天 |
| **M2** | `gap_analyzer.py` — 自动 gap 分析 + 报告生成 | 低 | 1 天 |
| **M3** | `design_spec.py` — 设计规格模板 + 反过拟合检查 | 中 | 2 天 |
| **M4** | CLI 入口 `veritas learn-from-ground-truth` | 低 | 1 天 |
| **M5** | 用 paper2 端到端验证 Phase 1-4（手动实现检测器） | 中 | 2 天 |
| **M6** | 半自动实现框架（agent 生成骨架 + 人工 review） | 中 | 3 天 |
| **M7** | 反过拟合 cross-paper validation 框架 | 高 | 3 天 |
| **M8** | 第二个 ground truth 案例验证 pipeline 通用性 | 中 | 2 天 |

**建议路径**: M1 → M2 → M3 → M4 → M5（端到端验证） → M6 → M7 → M8

**总计**: ~16 天（约 3 周）

## 11. 可行性评估

**可行，且价值明确。** 理由：

1. **模式已验证**: 我们刚用 paper2 完整走了一遍 Phase 1-6 的手工版，证明了从 ground truth 到通用检测器的路径是通的。
2. **模块化程度足够**: Veritas 的 tool registry、orchestrator、finding schema 提供了清晰的扩展点。新能力可以通过注册 → 集成 → 产出的标准路径插入。
3. **简化后更可控**: 5 阶段 pipeline 比 7 阶段更清晰，减少了状态转换和不必要的抽象。

**主要风险**:

| 风险 | 缓解措施 |
|------|----------|
| PubPeer 帖子格式不统一 | 定义最小可执行规格，强制人工确认 |
| "通用 vs 过拟合"的边界需要人工判断 | Phase 3 design checkpoint + 人工 review |
| 反过拟合需要"正常论文"测试集 | 维护至少 2 篇对照论文 |
| 半自动实现可能降低效率 | 接受效率损失，换取质量保障；等积累经验后再提高自动化 |

**不是银弹**: 这个 pipeline 不能自动发现全新的造假模式——它需要人类先识别 ground truth 中的 claim，然后系统才能增强对应能力。它是**能力放大器**，不是**发现引擎**。

---

## 附录 A: Capability Taxonomy（持续扩展）

```yaml
capabilities:
  visual:
    exact_duplicate:        # 字节级完全重复
    copy_move_keypoint:     # RootSIFT+MAGSAC++ 几何复制
    copy_move_dense:        # SILA dense copy-move
    tru_for_forgery:        # TruFor 神经网络伪造检测
    image_quality:          # 图像质量异常（无背景/纯色/均匀）
    provenance_sscd:        # SSCD embedding 跨图相似性
    
  source_data:
    formula_derived_column: # Excel 公式派生列
    row_offset_scalar:      # 行偏移固定倍数
    row_offset_exact_reuse: # 行偏移完全复用
    paired_ratio_reuse:     # 配对比率复用
    duplicate_row_vector:   # 重复行向量
    long_format_paired_ratio: # 长格式配对比率复用
    rounding_bias:          # 舍入偏差
    paired_difference_spread: # 配对差异分布过窄
    fixed_ratio:            # 固定比率关系
    fixed_difference:       # 固定差值关系
    duplicate_columns:      # 重复列
    
  completeness:
    missing_source_data:    # 论文引用但无对应 source data
    missing_code:           # 论文引用但无代码
    missing_environment:    # 无环境文件
    
  numeric:
    terminal_digit_anomaly: # 末位数字分布异常
    variance_anomaly:       # 方差异常
    benfords_law:           # Benford 定律偏离
```

每个 capability 在 `capability_catalog.yaml` 中的记录格式：

```yaml
- capability_id: "CAP-PDS-001"
  name: "paired_difference_spread"
  category: "source_data"
  description: "Detect anomalously narrow paired difference distributions"
  registry_tool_id: "source_data_paired_forensics"  # 关联 registry.py
  version: "1.0.0"
  driven_by:
    - "pubpeer:D62F4176543D09E95E22FA5C304BDA/#12"
  test_coverage:
    - "tests/unit/test_paired_difference_spread.py"
  validation_papers:
    - "input/paper2"  # ground truth
    - "input/paper1"  # 对照
    - "input/paper3"  # 对照
  distribution_analysis: "ground_truth/paper2/distribution_analysis.md"
  created_at: "2026-06-15"
  changelog:
    - version: "1.0.0"
      date: "2026-06-15"
      change: "Initial implementation"
      driven_by: "pubpeer:D62F4176543D09E95E22FA5C304BDA/#12"
```
