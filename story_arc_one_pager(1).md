# Veritas 论文 Story Arc（一页纸 v4）

> **论文标题**：VeritasBench: Benchmarking Claim-Provenance Consistency Auditing in Scientific Papers  
> **目标会议**：AAAI 2027（deadline ~2026 年 8 月）  
> **版本**：v3.3 | 2026-07-09  
> **一句话**：Scientific auditing is not open-ended QA. It is risk-controlled inference over a claim-provenance graph.  
> **逻辑结构**：Task → Benchmark → **Observation** → Method → Evaluation（因果链，不是顺序链）

---

## 三个贡献（因果链，不是顺序链）

| 贡献 | 定义 | 具体内容 | 因果驱动 |
|---|---|---|---|
| **1. 重新定义审计对象** | Redefine scientific auditing as provenance consistency | 四层 binary relation（C→T, S↔C, T/F→S, T/D→F），全部是跨表示一致性检查 | 论文 claim 来自证据传播链（D→C→T→F→S），错误发生在边而不是节点 |
| **2. 构建关系级 benchmark + 揭示失败模式** | Edge-centric benchmark + systematic error analysis | 50 papers → N claims → M **relation-level** annotations，含 clean claims；benchmark 作为**科学发现工具**，暴露 cross-representation reasoning 是核心瓶颈 | 现有 benchmark（Paper QA / FactReview / ChartQA）统计单位都是**节点**，无法度量**边**上的一致性 |
| **3. 针对失败模式提出方法** | Provenance-structured, risk-controlled auditor | 核心 = evidence graph aggregation + FAR-constrained selective prediction；每个设计决策对应一个 benchmark observation | Benchmark 暴露了三个系统性失败模式 → 方法三层结构一一回应 |

**命名区分**：VeritasBench = benchmark，Veritas-Auditor = method。

**因果闭环**：
```
贡献 1 重新定义对象（provenance consistency）
    ↓ 对象变了，已有 benchmark 不够用
贡献 2 构建关系级 benchmark，并发现 grounding failure 是核心瓶颈
    ↓ benchmark 暴露的错误模式决定了方法设计
贡献 3 针对这些失败模式提出 provenance-structured + risk-controlled 方法
```

---

## 四层评估框架（全部为 binary relation）

| Level | 名称 | 审计关系 | 说明 |
|---|---|---|---|
| **L1** | Computational-Report Consistency | C → T / C → S | 代码输出与表格/文本报告的数值是否一致 |
| **L2** | Method-Implementation Consistency | S_method ↔ C | 论文描述的方法与代码实现是否一致 |
| **L3** | Report-Claim Consistency | T/F → S | 表格/图像证据与文字 claim 是否一致（图像篡改检测作为 L3 的 verifier 工具） |
| **L4** | Visual Encoding Fidelity | T/D → F | 图是否忠实编码表格或底层数据 |

**设计原则**：四层全部是**两个表示之间的关系**，不是单一对象检查。原 "Visual Integrity"（单目图像取证）降级为 L3 的辅助 verifier + appendix。

---

## 贡献 3 的核心：Evidence Graph Aggregation + FAR-Constrained Selective Prediction

**不是"四个模块同等创新"**。核心方法贡献是：

> 给定若干 typed verifiers 的边级审计报告，如何在 claim-provenance graph 上聚合证据，并在 FAR 约束下决定 flag / pass / abstain。

**核心算法**：max Recall s.t. FAR ≤ α

**聚合函数 A 需处理三件事**：
1. Evidence independence（多个 signal 是否来自独立 artifact / verifier）
2. Discrepancy convergence（多个 signal 是否指向同一 semantic mismatch）
3. False accusation risk（当前证据是否足够支持 flag）

---

## 🔗 关键桥梁：Benchmark 揭示了什么（第三幕 Observation）

> **没有 Observation，Method 就像凭空出现。**

Benchmark 不只是为了评分——它是**科学发现工具（discovery），不只是测量工具（measurement）**。

在 VeritasBench 上运行 Bare Agent（B1），观察到三类系统性失败模式：

| 失败模式 | 具体表现 | → 方法回应 |
|---|---|---|
| **Evidence grounding 不稳定** | Agent 擅长 reasoning，但找不到真正支持 claim 的 table/figure；或者 method 和 code 对不上 | **Claim normalization**（B2 的结构化协议，强制 evidence span） |
| **跨 verifier 证据冲突** | 不同 verifier 对同一 claim 给出矛盾结论，孤立信号导致误报 | **Evidence graph aggregation**（B4 融合冲突证据，利用 independence 和 convergence） |
| **假阳性风险不可控** | LLM 审计的最大风险是错误指控（false accusation），尤其在证据不充分时仍强行给出 verdict | **FAR-constrained selective decision**（B5 在 FAR ≤ α 约束下 abstain） |

**因果链闭合**：

```
Benchmark 暴露 Failure 1 → 方法必须有 claim normalization
Benchmark 暴露 Failure 2 → 方法必须有 evidence graph aggregation
Benchmark 暴露 Failure 3 → 方法必须有 risk-controlled decision
```

每个方法设计决策都有经验证据支撑，不是凭空想出来的。这是 AAAI 偏好的论文结构：

```
Benchmark → Error Analysis → Design Principles → Method
（不是：Benchmark → 我们想到一个方法）
```

---

## 实验设计：三个假设驱动（对应 Observation 的三大失败模式）

| 组 | Agent 系统 | 架构特征 | 假设 | 对应 Observation |
|---|---|---|---|---|
| **B1** | Bare Agent | LLM + artifacts → verdict（无工具、无协议） | Baseline | 暴露三大失败模式的基线 |
| **B2** | Constrained Agent | + Structured Protocol（强制 claim normalization + evidence span） | **H1**: 结构化约束提升 evidence grounding | 回应 Failure 1：grounding 不稳定 |
| **B3** | Tool-Augmented Agent | + Typed Verifiers（NumericComparator, MethodChecker） | **H2**: 类型化工具减少模态特定错误 | 回应 Failure 1+2：verifier 冲突 |
| **B4** | Graph-Augmented Agent | + Evidence Graph Aggregation | **H3a**: 证据图聚合降低孤立误报 | 回应 Failure 2：跨 verifier 冲突 |
| **B5** | Risk-Controlled Agent | + FAR-Constrained Selective Decision | **H3b**: 风险控制 abstention 提升 Recall@FAR | 回应 Failure 3：假阳性不可控 |

**关键**：五组使用同一个 LLM backbone，区别在于 agent 架构复杂度。比较的是 **agent 架构**，不是 LLM。

**主表**（含 Coverage 防作弊）：

| Agent 系统 | Claim F1 | Evidence Precision | FAR | Recall@FAR≤5% | Coverage | Abstention |
|---|---|---|---|---|---|---|
| B1-B5 | | | | | | |

**关键图表**（按说服力排序）：

1. **risk-coverage curve**：证明 B5 不是靠少回答来降低误报
2. **Error breakdown by relation type**（L1/L2/L3/L4）：证明 typed verifier 在每种 relation 上都有针对性提升（比 Overall F1 更有说服力）
3. **Ablation chain**（B1→B2→B3→B4→B5）：证明每层结构对应一个 benchmark 揭示的失败模式

---

## 统计单位

- 50 **paper-level cases**（30 真实 + 20 合成）
- N **claim-level instances**（预计 200-500）
- M **typed evidence-relation annotations**（预计 500-2000）
- 含 **matched clean claims** 用于 FAR 测量

---

## 避坑清单

| 坑 | 正确做法 |
|---|---|
| 说 "paper fraud detection" / "打假" | 说 "claim-provenance consistency auditing" |
| Veritas 同时指 benchmark 和 method | VeritasBench = benchmark, Veritas-Auditor = method |
| 合成案例同时用于开发和测试 | 分 synthetic-dev / synthetic-test / real-test |
| Level 3 是 unary check（图像取证） | 改为 T/F → S 的 binary relation，图像取证降为 L3 verifier |
| B5 通过大量 abstain 降低 FAR | 必须同时报告 Coverage + Recall@FAR≤α |
| AAAI 正文超 7 页 | 贡献 3 聚焦到 evidence graph aggregation + FAR-constrained prediction |
| **三个贡献写成"定义→benchmark→方法"的顺序链** | **必须写成因果链：任务重新定义 → benchmark 揭示失败模式 → 方法回应失败模式** |
| **只报 Overall F1** | **必须同时报 Error breakdown by relation type (L1/L2/L3/L4)** |
| **说 "我们收集了 50 篇论文"** | **说 "首次把 scientific auditing 的统计单位从 document 变成 provenance relation"** |
| **Method 凭空出现，没有 empirical motivation** | **每个方法设计决策必须对应一个 benchmark observation** |

---

## 分工与时间线

| 工作 | 负责人 | 状态 |
|---|---|---|
| Benchmark 数据集构建 | 同事（吴关渡） | 数据已收集 |
| Ground truth 标注 | 同事 | 待确认进度 |
| 框架整合 + 实验 pipeline | 我 | 待开发（mock data 先行） |
| 实验执行 | 我 | 等 framework + ground truth |
| 论文写作 | 我 | 等实验结果 |

**时间线**：~5 周（AAAI 2027 deadline）。兜底：ICLR 2027。

---

## 需要 leader 把关的决策点

1. **因果链表述**："任务重新定义 → benchmark 揭示失败模式 → 方法回应失败模式" 是否站得住？还是 reviewer 会认为这是过度包装？

2. **Observation 的数据基础**：第三幕（Benchmark 揭示失败模式）需要真实实验数据。如果同事的 benchmark 数据延迟，是否用 task structure analysis（分析性论证）替代 empirical evidence？

3. **三层贡献表述**：Contribution 2 从"我们构建了 benchmark"变成"我们首次把统计单位从 document 变成 relation"——这个高度 reviewer 会买账吗？

---

## Takeaway（论文最终想说的话）

**不要写**：
> We propose VeritasBench and Veritas-Auditor.

**要写**：
> Scientific auditing should be formulated as **structured provenance consistency verification** instead of **open-ended reasoning**.

逻辑闭环：

```
Scientific claims come from provenance chains (D→C→T→F→S)
    ↓
Auditing should verify provenance consistency, not reason about facts
    ↓
Need a new task formulation (Contribution 1)
    ↓
Need a relation-centric benchmark, not a document-centric one (Contribution 2)
    ↓
Benchmark reveals systematic grounding failures
    ↓
Need provenance-structured, risk-controlled auditing (Contribution 3)
    ↓
Better Recall under fixed FAR → safer scientific auditing
```

VeritasBench 证明：这种 formulation 可以**评价**。
Veritas-Auditor 证明：这种 formulation 可以**利用**。

