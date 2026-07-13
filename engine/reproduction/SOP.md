# Veritas-Auditor 端到端评测 SOP

> **版本**：v1.0 | 2026-07-09  
> **目的**：从输入到输出完整走一遍评测系统，理解每个概念和设计哲学  
> **前置条件**：`uv` 已安装，依赖已同步

---

## 0. 核心设计哲学（先读再做）

在做任何操作之前，理解三个设计原则。这些原则贯穿整个系统：

**原则 1：Evidence First — 没有证据不下结论**

每个 verdict（flag/pass/abstain）都必须锚定到具体的 evidence span。如果系统说不清楚"基于什么证据做出的判断"，它就应该 abstain。这直接体现在 `ClaimVerdict.evidence_graph` 中——verdict 不是独立产生的，而是从 graph 上的 verifier outputs 聚合而来。

**原则 2：FAR-Constrained — 宁可不说也不乱说**

在研究完整性审计场景中，误报（false accusation）的代价远高于漏报。因此系统的目标函数不是 `max Accuracy`，而是 `max Recall s.t. FAR ≤ α`。`EvidenceGraphEngine._make_decision()` 实现了这个约束——如果 `far_risk > α`，即使 flag_score 最高也会 abstain。

**原则 3：契约先行 — 数据模型定义系统边界**

`models.py` 中的 9 个数据类不是"辅助结构"，而是系统的契约。每个数据类定义了输入/输出格式、允许的值域、必填/可选字段。理解了数据模型，就理解了系统的边界。

---

## 1. 系统全景

```
┌───────────────────────────────────────────────────────────────────┐
│                         CLI 入口                                   │
│  veritas reproduce benchmark --suite smoke_test --far-alpha 0.05  │
└─────────────────────────┬─────────────────────────────────────────┘
                          │
                          ▼
┌───────────────────────────────────────────────────────────────────┐
│                    BenchmarkCaseLoader                             │
│                                                                    │
│  输入：suite_name (str)                                            │
│  输出：list[BenchmarkCase]                                         │
│                                                                    │
│  真实数据：benchmarks/veritas_bench_v1/suites/{suite}.json         │
│           → cases/{case_id}/case.json                              │
│  Mock fallback：generate_mock_benchmark_case() × 3                │
└─────────────────────────┬─────────────────────────────────────────┘
                          │ list[BenchmarkCase]
                          ▼
┌───────────────────────────────────────────────────────────────────┐
│                       BenchmarkRunner                              │
│                                                                    │
│  for each case:                                                    │
│    VeritasAuditor.audit_case(case) → list[ClaimVerdict]            │
│                                                                    │
│  最终：MetricsCalculator.calculate(verdicts, annotations)          │
│  输出：BenchmarkResult(metrics)                                    │
└─────────────────────────┬─────────────────────────────────────────┘
                          │
                          ▼
┌───────────────────────────────────────────────────────────────────┐
│                      VeritasAuditor                                │
│                                                                    │
│  输入：BenchmarkCase (artifacts + annotations)                     │
│  输出：list[ClaimVerdict]                                          │
│                                                                    │
│  Step 1: 按 claim_id 分组 annotations                              │
│  Step 2: 对每个 claim 构建 EvidenceGraph                           │
│          - one EvidenceNode per unique artifact_ref                │
│          - one EvidenceEdge per annotation                         │
│  Step 3: 对每条 edge 运行 TypedVerifier                            │
│          - L1: NumericComparator(source_val, target_val)           │
│          - L2/L3/L4: 无 verifier → insufficient                    │
│  Step 4: EvidenceGraphEngine.aggregate(graph)                      │
│          - 聚合 verifier outputs                                   │
│          - FAR-constrained decision: flag / pass / abstain          │
└───────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌───────────────────────────────────────────────────────────────────┐
│                    MetricsCalculator                               │
│                                                                    │
│  输入：list[ClaimVerdict] + list[ClaimRelationAnnotation]          │
│  输出：dict[str, float] (8 个指标)                                  │
│                                                                    │
│  claim_f1          F1 of flag detection (positive=inconsistent)   │
│  evidence_precision #correct spans / #predicted spans              │
│  evidence_recall    #correct spans / #GT spans                     │
│  far                flagged clean / total clean                    │
│  recall_at_far_05   recall under FAR ≤ 5%                         │
│  recall_at_far_10   recall under FAR ≤ 10%                        │
│  coverage           (flag+pass) / total                            │
│  abstention_rate    abstain / total                                │
└───────────────────────────────────────────────────────────────────┘
```

---

## 2. 数据模型（系统的契约）

### 2.1 输入侧

```python
# 一个 BenchmarkCase 是系统的完整输入单元
BenchmarkCase:
    case_id: str                     # 唯一标识
    paper_title: str                 # 论文标题
    paper_authors: list[str]         # 作者列表
    artifacts: dict[str, str]        # artifact_type → 文件路径
    claims: list[ClaimRelationAnnotation]  # 所有 GT 标注
    metadata: dict                   # 语言、统计方法等

# 一个 ClaimRelationAnnotation 是一个 claim-relation 的 GT 标注
ClaimRelationAnnotation:
    annotation_id: str               # 唯一标识
    claim_id: str                    # 所属 claim
    claim_atom: str                  # 结构化的 claim 描述
    source_artifact: str             # 源 artifact 路径
    target_artifact: str             # 目标 artifact 路径
    relation_type: "L1"|"L2"|"L3"|"L4"  # 关系层级
    verdict: "consistent"|"inconsistent"|"insufficient"  # GT 判断
    discrepancy_type: str | None     # 不一致类型
    evidence_span: str | None        # 证据位置（canonical 格式）
    severity: "low"|"medium"|"high"|"critical" | None
    is_clean_claim: bool             # 是否为 clean claim（FAR 测量用）
```

### 2.2 中间表示

```python
# 证据图：claim 级别的结构化证据
EvidenceGraph:
    claim_id: str
    nodes: list[EvidenceNode]        # artifact 节点
    edges: list[EvidenceEdge]        # 关系边

EvidenceNode:
    node_id: str
    artifact_type: "data"|"code_output"|"table_cell"|"figure_mark"|"text_span"
    artifact_ref: str                # 指向具体 artifact
    artifact_hash: str | None        # SHA256

EvidenceEdge:
    edge_id: str
    source_node: str                 # node_id
    target_node: str                 # node_id
    relation_type: "L1"|"L2"|"L3"|"L4"
    verifier_output: VerifierOutput | None

# Typed verifier 输出
VerifierOutput:
    verdict: "consistent"|"inconsistent"|"insufficient"
    confidence: float                # 0-1
    evidence_span: str | None        # canonical 格式：L1:src->tgt
    discrepancy_type: str | None
    severity: "low"|"medium"|"high"|"critical" | None
    abstain_reason: str | None
```

### 2.3 输出侧

```python
# 最终的 claim-level 决策
ClaimVerdict:
    claim_id: str
    verdict: "flag"|"pass"|"abstain"  # ← 系统最终判断
    confidence: float                 # 0-1
    evidence_graph: EvidenceGraph     # 完整证据图（可审计）
    aggregated_signals: list[VerifierOutput]  # 聚合的 verifier 输出
    far_risk: float                   # 误报风险估计
    abstain_reason: str | None        # abstain 时的原因

# Benchmark 结果
BenchmarkResult:
    suite_name: str
    num_cases: int
    num_claims: int
    num_relations: int
    metrics: dict[str, float]         # 8 个指标
    claim_verdicts: list[ClaimVerdict]
```

---

## 3. 操作 SOP

### Step 1: 运行 benchmark（零配置）

```bash
cd /mnt/disk1/LZJ/project/veritas

uv run python -m cli.main reproduce benchmark
```

**你会看到**：
```
Benchmark directory benchmarks/veritas_bench_v1 not found; falling back to mock data
============================================================
VeritasBench  suite=smoke_test
============================================================
  cases:     3
  claims:    15
  relations: 15

Metrics:
  claim_f1                 1.0000
  evidence_precision       1.0000
  evidence_recall          1.0000
  far                      0.0000
  recall_at_far_05         1.0000
  recall_at_far_10         1.0000
  coverage                 1.0000
  abstention_rate          0.0000
```

**发生了什么**：
1. `BenchmarkCaseLoader` 发现 `benchmarks/veritas_bench_v1/` 不存在
2. 自动 fallback 到 mock data（3 个 case，每个 5 个 annotation）
3. `BenchmarkRunner` 对每个 case 调用 `VeritasAuditor.audit_case()`
4. `VeritasAuditor` 构建 EvidenceGraph，运行 NumericComparator，聚合 verdict
5. `MetricsCalculator` 计算 8 个指标
6. CLI 打印结果

**理解要点**：
- 这是 **mock data → engine → metrics** 的完整链路
- 所有 verdict 都经过了真实 engine（不是直接读 GT）
- F1=1.0 是因为 mock data 的数值被刻意构造为 consistent→pass, inconsistent→flag
- evidence_precision/recall=1.0 是因为 evidence_span 格式在 GT 和 predicted 之间完全匹配

### Step 2: 查看 mock data 的结构

```bash
uv run python -m cli.main reproduce mock --num-claims 5
```

**输出文件**：`outputs/mock_claims/mock_claims_5.json`

```bash
uv run python -c "
import json
with open('outputs/mock_claims/mock_claims_5.json') as f:
    claims = json.load(f)

for claim in claims:
    print(f'=== {claim[\"claim_id\"]} (fraud_pattern={claim[\"fraud_pattern\"]}) ===')
    for ann in claim['annotations']:
        print(f'  {ann[\"relation_type\"]}: {ann[\"verdict\"]}')
        print(f'    source: {ann[\"source_artifact\"]}')
        print(f'    target: {ann[\"target_artifact\"]}')
        print(f'    evidence_span: {ann[\"evidence_span\"]}')
        print(f'    is_clean_claim: {ann[\"is_clean_claim\"]}')
    print()
"
```

**你会看到**：每个 claim 有 fraud_pattern（clean/numeric_tampering/method_mismatch/data_transform_undeclared）和对应的 annotations。每个 annotation 有 canonical evidence_span（格式：`{relation_type}:{source}->{target}`）。

**理解要点**：
- `fraud_pattern` 决定了 annotations 的 verdict 分布
- `evidence_span` 是 stable identifier，不是比对细节
- `is_clean_claim` 只在 `fraud_pattern == "clean"` 时为 True

### Step 3: 交互式探索 Evidence Graph Engine

```bash
uv run python
```

```python
from engine.reproduction.evidence_graph import EvidenceGraphEngine
from engine.reproduction.mock_data import generate_mock_evidence_graph

engine = EvidenceGraphEngine(far_alpha=0.05)

# 观察不同 inconsistency_rate 下的决策行为
print("=== Evidence Graph Engine 决策边界 ===")
for rate in [0.0, 0.2, 0.5, 0.8, 1.0]:
    graph = generate_mock_evidence_graph(
        claim_id=f"test_{rate}",
        num_nodes=4,
        num_edges=3,
        inconsistent_rate=rate,
    )
    verdict = engine.aggregate(graph)
    print(f"  rate={rate:.1f} → verdict={verdict.verdict}, "
          f"conf={verdict.confidence:.2f}, far_risk={verdict.far_risk:.2f}")
    if verdict.abstain_reason:
        print(f"    reason: {verdict.abstain_reason}")
```

**预期输出**：
```
rate=0.0 → verdict=pass,    conf=0.95, far_risk=0.22
rate=0.2 → verdict=pass,    conf=0.46, far_risk=0.16
rate=0.5 → verdict=pass,    conf=0.53, far_risk=0.11
rate=0.8 → verdict=abstain, conf=0.57, far_risk=0.35
rate=1.0 → verdict=abstain, conf=0.51, far_risk=0.24
```

**理解要点**：
- rate=0.0 → pass：全部一致，没有不一致信号
- rate=0.2-0.5 → pass：有少量不一致，但 flag_score 不够高
- rate=0.8-1.0 → abstain（不是 flag！）：不一致信号足够强，但 far_risk 超过了 α=0.05
- 这是 **FAR-constrained decision** 的核心行为：宁可 abstain 也不在高风险下 flag

### Step 4: 探索 Typed Verifier（NumericComparator）

```python
from engine.reproduction.verifiers.numeric_comparator import NumericComparator
from engine.reproduction.verifiers.base import ToleranceConfig

comparator = NumericComparator()

print("=== NumericComparator 行为 ===")

# 精确匹配
r = comparator.verify(0.001, 0.001)
print(f"0.001 vs 0.001: verdict={r.verdict}, span={r.evidence_span}")

# 在容差内（absolute_error=0.001）
r = comparator.verify(0.001, 0.0015)
print(f"0.001 vs 0.0015: verdict={r.verdict} (diff=0.0005 < 0.001)")

# 超出容差
r = comparator.verify(0.001, 0.050)
print(f"0.001 vs 0.050: verdict={r.verdict}, severity={r.severity}")
print(f"  span={r.evidence_span}")

# P-value 路径
r = comparator.verify(0.030, 0.033, context={"value_type": "p_value"})
print(f"p=0.030 vs p=0.033: verdict={r.verdict} (p_value diff=0.003 > 0.001)")

# 非数值
r = comparator.verify("N/A", 0.001)
print(f"'N/A' vs 0.001: verdict={r.verdict}, reason={r.abstain_reason}")

# 自定义容差
loose = NumericComparator(ToleranceConfig(p_value_absolute_error=0.005))
r = loose.verify(0.030, 0.033, context={"value_type": "p_value"})
print(f"p=0.030 vs p=0.033 (宽松): verdict={r.verdict} (diff=0.003 < 0.005)")
```

**理解要点**：
- NumericComparator 是 **deterministic**（确定性）的——给定相同的输入，永远产出相同的输出
- evidence_span 格式是 `{relation_type}:{source}->{target}`，这是 stable identifier
- severity 基于 relative_diff：>50% → critical, >20% → high, >5% → medium, else → low
- p_value 路径和普通数值路径使用不同的容差参数

### Step 5: 探索 Metrics 计算

```python
from engine.reproduction.benchmark.metrics import MetricsCalculator
from engine.reproduction.models import (
    ClaimVerdict, ClaimRelationAnnotation, EvidenceGraph,
    EvidenceEdge, EvidenceNode, VerifierOutput,
)

calc = MetricsCalculator()

# 构造一个简单场景：3 个 prediction，3 个 GT
# prediction: c1=flag, c2=pass, c3=abstain
# GT:         c1=inconsistent, c2=consistent(clean), c3=inconsistent

# 创建带 evidence_graph 的 verdicts
def make_verdict(claim_id, verdict, span):
    node_s = EvidenceNode(node_id="s", artifact_type="code_output", artifact_ref="src")
    node_t = EvidenceNode(node_id="t", artifact_type="table_cell", artifact_ref="tgt")
    edge = EvidenceEdge(
        edge_id="e1", source_node="s", target_node="t", relation_type="L1",
        verifier_output=VerifierOutput(
            verdict="inconsistent" if verdict == "flag" else "consistent",
            confidence=0.9, evidence_span=span,
            discrepancy_type="numeric_mismatch" if verdict == "flag" else None,
            severity="high" if verdict == "flag" else None,
            abstain_reason=None,
        ),
    )
    graph = EvidenceGraph(claim_id=claim_id, nodes=[node_s, node_t], edges=[edge])
    return ClaimVerdict(
        claim_id=claim_id, verdict=verdict, confidence=0.9,
        evidence_graph=graph, aggregated_signals=[edge.verifier_output],
        far_risk=0.1,
    )

preds = [
    make_verdict("c1", "flag", "L1:src->tgt"),     # TP: 正确 flag
    make_verdict("c2", "pass", "L1:src->tgt"),     # TN: 正确 pass
    make_verdict("c3", "abstain", "L1:src->tgt"),  # FN: 应该 flag 但 abstain
]

gt = [
    ClaimRelationAnnotation(
        annotation_id="a1", claim_id="c1", claim_atom="c1",
        source_artifact="src", target_artifact="tgt",
        relation_type="L1", verdict="inconsistent",
        evidence_span="L1:src->tgt", is_clean_claim=False,
    ),
    ClaimRelationAnnotation(
        annotation_id="a2", claim_id="c2", claim_atom="c2",
        source_artifact="src", target_artifact="tgt",
        relation_type="L1", verdict="consistent",
        evidence_span="L1:src->tgt", is_clean_claim=True,
    ),
    ClaimRelationAnnotation(
        annotation_id="a3", claim_id="c3", claim_atom="c3",
        source_artifact="src", target_artifact="tgt",
        relation_type="L1", verdict="inconsistent",
        evidence_span="L1:src->tgt", is_clean_claim=False,
    ),
]

m = calc.calculate(preds, gt)
print("=== Metrics 计算详解 ===")
print(f"  claim_f1:           {m['claim_f1']:.4f}  (TP=1, FP=0, FN=1 → P=1.0, R=0.5, F1=0.667)")
print(f"  evidence_precision: {m['evidence_precision']:.4f}  (2 pred spans, 2 correct → 1.0)")
print(f"  evidence_recall:    {m['evidence_recall']:.4f}  (3 GT spans, 2 correct → 0.667)")
print(f"  far:                {m['far']:.4f}  (1 clean claim, 0 flagged → 0.0)")
print(f"  coverage:           {m['coverage']:.4f}  (2 flag/pass, 1 abstain → 0.667)")
print(f"  abstention_rate:    {m['abstention_rate']:.4f}  (1 abstain → 0.333)")
```

**理解要点**：
- `claim_f1` 以 claim 为单位（不是 annotation）——一个 claim 只要有任一 annotation 是 inconsistent，就算 dirty
- `evidence_precision/recall` 基于 evidence_span 的精确字符串匹配
- `far` 只计算 clean claims 上的误报率
- `coverage + abstention_rate = 1.0`（互补）
- `recall_at_far` 通过排序 far_risk 来找到最佳阈值

### Step 6: 保存完整结果到 JSON

```bash
uv run python -m cli.main reproduce benchmark \
  --suite smoke_test \
  --output-dir outputs/benchmark_results \
  --far-alpha 0.05
```

查看 JSON 结果：

```bash
uv run python -c "
import json
with open('outputs/benchmark_results/benchmark_smoke_test.json') as f:
    data = json.load(f)

print(f'Suite: {data[\"suite_name\"]}')
print(f'Cases: {data[\"num_cases\"]}, Claims: {data[\"num_claims\"]}')
print(f'Metrics:')
for k, v in data['metrics'].items():
    print(f'  {k}: {v:.4f}')
print()
print('Verdict details (first 3):')
for v in data['claim_verdicts'][:3]:
    print(f'  {v[\"claim_id\"]}: verdict={v[\"verdict\"]}, conf={v[\"confidence\"]:.2f}, far_risk={v[\"far_risk\"]:.2f}')
"
```

### Step 7: 用真实数据格式创建 benchmark（准备 future work）

创建最小真实数据目录结构：

```bash
mkdir -p benchmarks/veritas_bench_v1/suites
mkdir -p benchmarks/veritas_bench_v1/cases/case_001
```

```python
import json

# 创建 suite 文件
suite = {
    "name": "smoke_test",
    "description": "Smoke test suite with 1 case",
    "case_ids": ["case_001"]
}
with open("benchmarks/veritas_bench_v1/suites/smoke_test.json", "w") as f:
    json.dump(suite, f, indent=2)

# 创建 case 文件（最小格式）
case = {
    "case_id": "case_001",
    "paper_title": "Example Paper",
    "paper_authors": ["Author A"],
    "artifacts": {
        "paper_pdf": "/path/to/paper.pdf",
        "code": "/path/to/code/",
        "source_data": "/path/to/data.xlsx"
    },
    "claims": [
        {
            "annotation_id": "ann_001",
            "claim_id": "claim_001",
            "claim_atom": "Treatment A improves survival (p=0.03)",
            "source_artifact": "/code/output.csv",
            "target_artifact": "/paper/Table 1",
            "relation_type": "L1",
            "verdict": "inconsistent",
            "discrepancy_type": "numeric_mismatch",
            "evidence_span": "L1:/code/output.csv->/paper/Table 1",
            "severity": "high",
            "is_clean_claim": False
        },
        {
            "annotation_id": "ann_002",
            "claim_id": "claim_001",
            "claim_atom": "Clean baseline measurement",
            "source_artifact": "/code/baseline.csv",
            "target_artifact": "/paper/Table 1",
            "relation_type": "L1",
            "verdict": "consistent",
            "evidence_span": "L1:/code/baseline.csv->/paper/Table 1",
            "is_clean_claim": True
        }
    ],
    "metadata": {
        "language": "python",
        "statistical_methods": ["t-test"]
    }
}
with open("benchmarks/veritas_bench_v1/cases/case_001/case.json", "w") as f:
    json.dump(case, f, indent=2)
```

现在重新运行 benchmark（这次走真实数据路径）：

```bash
uv run python -m cli.main reproduce benchmark --suite smoke_test
```

**理解要点**：
- `case.json` 的必填字段只有 `case_id` 和 `claims`
- 每个 claim annotation 必须有 `claim_id`, `source_artifact`, `target_artifact`, `relation_type`, `verdict`
- `evidence_span` 必须使用 canonical 格式 `{relation_type}:{source}->{target}`
- `is_clean_claim` 必须正确设置（FAR 测量依赖它）
- 当前系统只有 L1 verifier——L2/L3/L4 的 annotations 会产生 `insufficient` verdict

---

## 4. 关键设计决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| evidence_span 格式 | `{relation_type}:{source}->{target}` | 稳定标识符，GT 和 predicted 可精确匹配 |
| Verdict 生成 | 经过 engine，不直接读 GT | 即使 mock data 也要走算法路径 |
| Mock 数值生成 | SHA256 hash → deterministic float | 相同 artifact_ref 总是生成相同值 |
| inconsistent 数值构造 | source × 2.5 | 产生 ~150% 差异 → critical severity |
| FAR-constrained decision | flag_score 最高但 far_risk > α → abstain | 宁可不说也不乱说 |
| claim_f1 粒度 | claim-level（不是 annotation-level） | 一个 claim 有一个 annotation 不一致就算 dirty |
| Runner 绕过 build_graph() | 直接构建 graph | 避免 artifacts dict 形状不匹配 |

---

## 5. 已知局限（当前系统做不到什么）

| 局限 | 原因 | 影响 |
|---|---|---|
| 只有 L1 verifier | L2/L3/L4 verifier 未实现 | L2/L3/L4 annotations 全部 insufficient |
| mock 数值 | SHA256 hash，不是真实数据 | 无法验证真实场景下的行为 |
| FAR risk 公式 | 硬编码加权公式 | 过于保守（rate=1.0 → abstain） |
| evidence_independence | 硬编码 1.0 | 所有 signals 被视为独立 |
| evidence_span 精确匹配 | 字符串交集 | 无法处理语义等价但文本不同的 span |
| `reproduce run` | stub，未连接 pipeline | 无法对单篇论文做端到端审计 |
| 真实 artifact 解析 | 无 PDF/Excel/代码解析 | 只能处理 mock 数值 |

---

## 6. 命令速查

| 命令 | 用途 | 关键参数 |
|---|---|---|
| `uv run python -m cli.main reproduce benchmark` | 运行 benchmark（默认 mock data） | `--suite`, `--far-alpha`, `--output-dir` |
| `uv run python -m cli.main reproduce mock` | 生成 mock claims | `--num-claims`, `--output-dir` |
| `uv run python -m cli.main reproduce run` | 端到端审计（stub） | `--paper`, `--code`, `--output-dir` |

---

**文档结束**
