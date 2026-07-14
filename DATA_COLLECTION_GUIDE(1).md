# VeritasBench 数据收集指南

> **版本**：v1.0 | 2026-07-09  
> **目标**：定向收集能触发三大 failure modes 的论文数据，确保 benchmark 有足够区分度  
> **负责人**：吴关渡  
> **审核**：论文作者（验证因果链闭合）

---

## 0. 为什么需要定向收集

VeritasBench 的论文叙事依赖一条因果链：

```
Benchmark 运行 Bare Agent → 观察到三大 failure modes → 方法一一回应
```

如果 benchmark 数据不能触发这三种 failure modes，因果链断裂，论文最核心的叙事（"方法针对 benchmark 揭示的问题而设计"）就不成立。

**这不是 cherry-pick 造假**。一个好的 benchmark 必须：
- 覆盖已知的困难场景（否则没有区分度）
- 包含能触发不同 failure modes 的 cases（否则消融实验没有意义）
- 同时包含 clean claims（否则 FAR 无法测量）

本指南的目的是：**确保 50 cases 在三种 failure mode 维度上有足够 coverage。**

---

## 1. 三大 Failure Modes 定义

### Failure Mode 1：Evidence Grounding 不稳定

**定义**：Agent 擅长 reasoning，但找不到真正支持（或反驳）claim 的 evidence。

**触发条件**：
- Claim 的真实 evidence 分散在多个 artifact 中（multi-hop）
- Paper 中有多张表/多个 figure，claim 只引用其中一个，但其他表/figure 看起来也相关
- Evidence 需要跨模态追踪（data → code → table → claim，中间经过 3+ 跳）
- 代码输出是中间结果，不是最终表格值（需要额外的 aggregation/rounding）

**B1 预期失败方式**：
- 找不到正确的 table cell，引用了错误的表
- 找到了表但定位错了 cell/row
- 编造了一个看起来合理但不存在的 evidence span（hallucination）

### Failure Mode 2：跨 Verifier 证据冲突

**定义**：不同 verifier 对同一 claim 给出矛盾结论。

**触发条件**：
- 数值一致（L1 pass）但方法描述与代码不一致（L2 fail）——例如论文说"t-test"但代码实际用了 Welch's t-test
- 表格支持 claim（L3 pass）但图表编码有误导性（L4 fail）——例如 Y 轴截断夸大效应
- 代码输出与表格一致（L1 pass）但图表与表格不一致（L4 fail）——例如数据对但画图出错
- 论文 claim 在统计上正确但效应量很小（L3 technically pass），但 figure 视觉上看差异很大（L4 fail）

**B1 预期失败方式**：
- 只检查了一种 relation（如 L1），忽略其他 relation 的冲突
- 被局部一致误导，忽略跨层不一致
- 给出矛盾 verdict（说"一致"但证据里有冲突信号）

### Failure Mode 3：假阳性风险不可控

**定义**：Agent 在证据不充分时仍强行给出 verdict（特别是 flag），导致错误指控。

**触发条件**：
- Claim 看起来有问题但实际上是一致的（surface discrepancy, real consistency）：
  - 数值差异是因为 rounding/precision（如 0.0501 vs 0.05）
  - 方法名称不同但实质相同（如 "OLS regression" vs "linear regression"）
  - 单位不同但换算后一致（如 kg vs lbs, Celsius vs Fahrenheit）
  - 样本量差异是因为 excluded observations（有合理说明）
- Claim 确实是 clean 的，但看起来"太完美"让人怀疑
- Evidence 存在但不完整（部分缺失，不是篡改）

**B1 预期失败方式**：
- 看到数值不完全匹配就 flag（忽略 rounding）
- 看到方法名称不同就 flag（忽略同义词）
- 在证据不足时强行给出 "inconsistent" 而不是 "insufficient evidence"

---

## 2. 数据收集目标

### 总量：50 cases

| 类别 | 目标数量 | 主要触发 | 说明 |
|---|---|---|---|
| **Grounding 困难** | 15 cases | Failure 1 | Multi-hop evidence, 多表/多图, 跨模态追踪 |
| **Verifier 冲突** | 12 cases | Failure 2 | 部分一致 + 部分不一致, 跨层矛盾 |
| **假阳性陷阱** | 8 cases | Failure 3 | Surface discrepancy but real consistency |
| **Clean claims** | 10 cases | FAR 基线 | 完全一致, 用于测量 FAR |
| **混合/边界** | 5 cases | 全部 | 多种 failure mode 叠加 |

### 语言覆盖

- Python：至少 20 cases
- R：至少 10 cases
- 其他（MATLAB, Julia, Stata）：可选

---

## 3. 每类 Case 的具体收集标准

### 3.1 Grounding 困难（15 cases）

**选择标准**（至少满足 2 条）：

- [ ] Paper 有 3+ 张 table，claim 只引用其中一张的特定 cell
- [ ] Paper 有 2+ 个 figure，需要区分哪个 figure 支持哪个 claim
- [ ] Claim 的 evidence 需要跨 3+ 跳（data → code → intermediate output → table → claim）
- [ ] Code 输出是 raw result（如 model coefficients），table 里是 processed result（如 odds ratios），需要额外转换
- [ ] Claim 引用的是 "supplementary material" 或 "appendix" 中的 table
- [ ] 代码中有多个 analysis pipeline，claim 对应其中一个特定 pipeline 的输出

**标注要求**：
```
对于每个 claim：
- claim_id
- claim_text（原文）
- correct_evidence_artifact：真正支持/反驳该 claim 的文件路径
- correct_evidence_span：精确到 table cell / figure panel / code line
- evidence_chain_length：从 claim 到最终 evidence 需要几跳
- distractor_artifacts：看起来相关但不是真正 evidence 的文件列表
- grounding_difficulty：why is this hard to ground?（具体说明）
```

### 3.2 Verifier 冲突（12 cases）

**选择标准**（必须满足不同层次的冲突组合）：

| 冲突类型 | 目标数量 | 具体场景 |
|---|---|---|
| L1 pass + L2 fail | 4 | 数值对，但方法不对（如论文说 t-test，代码用 Mann-Whitney） |
| L1 pass + L4 fail | 3 | 数值对，但图有误导（如 Y 轴截断、log 伪装 linear） |
| L3 pass + L4 fail | 2 | 文字 claim 与 table 一致，但 figure 编码错误 |
| L1 fail + L3 pass | 2 | 数值不匹配，但文字 claim 做了合理解释（如 "trend" 不是精确数值） |
| 多层混合 | 1 | 3+ 层有冲突信号 |

**标注要求**：
```
对于每个 claim：
- claim_id
- claim_text
- Per-level verdicts:
  - L1_verdict: consistent / inconsistent / N/A
  - L2_verdict: consistent / inconsistent / N/A
  - L3_verdict: consistent / inconsistent / N/A
  - L4_verdict: consistent / inconsistent / N/A
- conflict_type: 哪些 level 之间冲突
- conflict_description: 具体说明冲突是什么
- overall_verdict: 综合判断（inconsistent，因为 ___）
- resolution_hint: 冲突应如何解决（哪个 level 的 signal 更可靠）
```

### 3.3 假阳性陷阱（8 cases）

**选择标准**（必须每个都属于以下陷阱类型之一）：

| 陷阱类型 | 目标数量 | 具体场景 |
|---|---|---|
| Rounding/precision | 2 | 0.0501 报成 0.05；1.234 vs 1.23 |
| 同义表述 | 2 | "OLS" vs "linear regression"；"propensity score matching" vs "PSM" |
| 单位换算 | 2 | kg vs lbs；% vs proportion；Celsius vs Fahrenheit |
| 合理的样本量差异 | 1 | 论文说 N=200，代码从 N=210 开始（排除了 10 个 outlier，有说明） |
| "太完美"的 clean claim | 1 | 所有数值精确匹配，但 agent 可能因为"太顺利"而怀疑 |

**标注要求**：
```
对于每个 claim：
- claim_id
- claim_text
- surface_discrepancy: 表面上看起来不一致的地方
- actual_verdict: consistent（真正的判断）
- why_consistent: 为什么实际上是一致的（具体说明）
- trap_type: rounding / synonym / unit_conversion / sample_exclusion / too_perfect
- expected_agent_error: B1 预期会犯什么错（为什么会误报）
```

### 3.4 Clean Claims（10 cases）

**选择标准**：
- 每个 paper case 中至少包含 1-2 个完全 clean 的 claim-relation
- Clean claim 的 evidence chain 应该简单直接（1-2 跳）
- Clean claim 使用的统计方法应该是常见的（t-test, correlation）

**标注要求**：
```
对于每个 clean claim：
- claim_id
- claim_text
- is_clean_claim: true
- evidence_artifact: 支持 evidence 的文件
- evidence_span: 精确位置
- why_clean: 为什么这是一致的（简要说明）
```

**关键约束**：clean claims 不能太"明显"——应该看起来和 inconsistent claims 一样需要检查，只是检查后确认一致。否则 FAR 测量没有意义（系统不会 flag 明显正确的东西）。

---

## 4. 论文选择标准

### 基本要求

- [ ] 已发表在正式期刊/会议（非 preprint-only）
- [ ] 有公开 source data（Zenodo / Dryad / GitHub / journal supplement）
- [ ] 有公开代码（GitHub / GitLab / journal supplement）
- [ ] 代码可运行（至少作者声明可复现）
- [ ] 论文包含至少 3 个 quantitative claims with numerical evidence

### 优先选择

- [ ] 论文包含多种统计方法（t-test + regression + correlation）
- [ ] 论文有 3+ 张 table 和 2+ figure（提供 grounding 难度）
- [ ] 论文有 supplementary material（增加 evidence chain 复杂度）
- [ ] 代码中有多个 analysis script / pipeline（增加 multi-hop 可能性）

### 避免

- [ ] 纯理论论文（没有 quantitative claims）
- [ ] 只有 1 张 table 的论文（grounding 太简单）
- [ ] 代码无法运行的论文（无法验证 L1）
- [ ] source data 缺失的论文（无法验证 evidence chain）

---

## 5. 标注质量控制

### 双人独立标注

- 每个 case 至少由 2 人独立标注
- 计算 inter-rater agreement（Cohen's Kappa）
- Kappa < 0.8 的 Level 需要重新定义标注标准

### 标注 checklist

标注完成后，对每个 case 检查：

- [ ] 每个 claim 的 evidence chain 是否完整标注？
- [ ] 每个 claim 的 per-level verdict 是否标注？
- [ ] Grounding 困难的 case 是否标注了 distractor artifacts？
- [ ] Verifier 冲突的 case 是否标注了冲突类型和解决方向？
- [ ] 假阳性陷阱的 case 是否标注了 trap type？
- [ ] Clean claims 是否标注为 is_clean_claim = true？
- [ ] evidence_span 是否使用 canonical 格式（`{relation_type}:{source}->{target}`）？

---

## 6. 因果链验证 Checklist

数据收集完成后，用以下 checklist 验证因果链是否成立：

### 验证 Failure Mode 1（Evidence Grounding）

- [ ] 至少 15 个 cases 的 evidence_chain_length ≥ 3
- [ ] 至少 10 个 cases 有 2+ distractor artifacts
- [ ] 人工确认：如果给 GPT-4 全部 artifacts 但不给结构化协议，它大概率找错 evidence

### 验证 Failure Mode 2（Verifier 冲突）

- [ ] 至少 8 个 cases 有 2+ 个 level 给出不同 verdict
- [ ] 冲突类型覆盖：L1+L2, L1+L4, L3+L4, 多层混合
- [ ] 人工确认：只看单一 level 会得出错误结论

### 验证 Failure Mode 3（假阳性）

- [ ] 至少 8 个 cases 有 surface discrepancy but real consistency
- [ ] 陷阱类型覆盖：rounding, synonym, unit_conversion, sample_exclusion
- [ ] 人工确认：B1 大概率会把这些 flag 为 inconsistent

### 验证 FAR 基线

- [ ] 至少 10 个 clean claims 分布在不同 paper cases 中
- [ ] Clean claims 看起来和 inconsistent claims 一样需要检查
- [ ] 如果系统全部 flag，FAR ≥ 20%（证明 FAR 控制有意义）

---

## 7. 时间线

| 阶段 | 内容 | 目标日期 |
|---|---|---|
| **Week 1** | 论文初筛（50+ → 30），确认 source data + code 可用 | 7/13 |
| **Week 1-2** | Grounding 困难 cases 标注（15 cases） | 7/16 |
| **Week 2** | Verifier 冲突 cases 标注（12 cases） | 7/20 |
| **Week 2-3** | 假阳性陷阱 + Clean claims 标注（18 cases） | 7/23 |
| **Week 3** | 双人交叉验证 + Kappa 计算 | 7/27 |
| **Week 3** | 因果链验证 checklist 执行 | 7/27 |
| **Week 3-4** | 数据交付 + 格式对齐 | 7/30 |

---

## 8. 数据交付格式

每个 case 一个 JSON 文件，放在 `data/veritasbench/cases/` 目录下：

```json
{
  "case_id": "paper_001",
  "paper_title": "...",
  "paper_doi": "...",
  "language": "python",
  "artifacts": {
    "source_data": "path/to/data.csv",
    "code": "path/to/analysis.py",
    "tables": ["path/to/table1.json", "path/to/table2.json"],
    "figures": ["path/to/fig1.png", "path/to/fig2.png"],
    "paper_text": "path/to/paper.md"
  },
  "claims": [
    {
      "claim_id": "paper_001_c1",
      "claim_text": "Treatment group showed significant improvement (p < 0.05)",
      "relation_type": "L1",
      "verdict": "inconsistent",
      "discrepancy_type": "p_value_mismatch",
      "evidence_span": "L1:analysis.py:output_p_value->table1.json:row3_col4",
      "severity": "high",
      "is_clean_claim": false,
      "failure_mode_trigger": "grounding",
      "notes": "p=0.0501 in code, reported as p<0.05 in paper. Actually borderline."
    }
  ],
  "failure_mode_coverage": {
    "grounding": true,
    "verifier_conflict": false,
    "false_positive_trap": false
  }
}
```

---

## 9. 常见问题

**Q：如果我找不够 15 个 grounding 困难的 cases 怎么办？**  
A：降低 evidence_chain_length 阈值（从 3 跳降到 2 跳），或者增加 distractor artifacts 的数量要求。如果还是不够，考虑合成 cases（从真实论文出发，增加额外的 table/figure 来制造 grounding 难度）。

**Q：如果 verifier 冲突的 cases 不够多怎么办？**  
A：优先考虑 L1+L4 冲突（数值对但图有误导）和 L1+L2 冲突（数值对但方法不对），这两类最常见。L3+L4 冲突比较少见，可以减少到 1-2 个。

**Q：假阳性陷阱的 cases 怎么找？**  
A：重点找 rounding 和同义表述。几乎每篇论文都有 rounding（p 值、效应量），几乎每篇论文都有方法的不同叫法。单位换算需要特意找（如英制单位、百分比 vs 小数）。

**Q：Clean claims 会不会太少？**  
A：每个 paper case 强制包含至少 1 个 clean claim。50 个 cases 就有 50+ clean claims。但注意：clean claims 不能太简单，否则 FAR 测量没有意义。

---

**文档结束**
