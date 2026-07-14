# Veritas 代码复现能力 PRD

> **版本**：v1.0  
> **日期**：2026-07-03  
> **状态**：Draft  
> **作者**：Veritas Team

---

## 目录

1. [问题与动机](#1-问题与动机)
2. [改进思路](#2-改进思路)
3. [产品设计](#3-产品设计)
4. [技术设计](#4-技术设计)
5. [MVP 范围](#5-mvp-范围)
6. [风险与缓解](#6-风险与缓解)
7. [附录](#7-附录)

---

## 1. 问题与动机

### 1.1 当前问题

Veritas 当前的审计能力集中在**静态分析**：
- Source Data 内部一致性检测（重复列/固定差值/跨 sheet 重复）
- 图像操控检测（copy-move/TruFor）
- claim-to-source-data 映射

**缺失的能力**：无法验证论文中的表格数据是否可以从代码复现。

典型场景：
- 学生提交论文，Table 2 显示"CRP 与疾病严重度显著相关（p=0.001）"
- 导师想知道：这个 p 值是真的跑出来的，还是随便写的？
- 当前 Veritas 无法回答这个问题

### 1.2 目标用户

**主要用户**：导师（通讯作者），在投稿前检查学生数据的可靠性。

**用户痛点**：
- 学生声称"Table 2 的结果是代码跑出来的"，但导师无法验证
- 导师没有时间读代码、配环境、跑复现
- 即使导师愿意跑，也可能因为环境配置问题跑不通

### 1.3 成功标准

- 导师上传论文 + 代码，系统自动推断 Table → 代码映射
- 系统执行代码，提取结果，与论文表格比对
- 导师看到：每个 cell 的复现结果（match/mismatch/inconclusive）
- 整个过程不超过 30 分钟（含用户确认时间）

---

## 2. 改进思路

### 2.1 借鉴 FactReview 的核心思想

FactReview 是一篇科研可信性验证的论文和开源实现，其核心思想：

| 思想 | FactReview 实现 | Veritas 借鉴 |
|---|---|---|
| **Claim-centric** | 把论文拆成 claims，逐个验证 | 把表格拆成 TableClaims，逐个验证 |
| **Evidence gradient** | verdict 不是 binary，而是 supported/partially/inconclusive | cell-level verdict：match/mismatch/inconclusive |
| **Agentic execution loop** | `prepare → plan → run → judge → fix → finalize`，默认多轮尝试 | 复用该循环作为代码复现主干 |
| **Repair loop** | 执行失败时自动修复环境/依赖 | 执行失败时尝试修复 Docker 环境，修复只落在 overlay |
| **三源证据** | 文本/文献/执行 | Veritas 只关注执行证据（文献源成本太高，不做） |

### 2.2 与 FactReview 的关键差异

| 维度 | FactReview | Veritas |
|---|---|---|
| **目标** | Review assistance（帮审稿人） | Execution-backed consistency check（投稿前代码复现一致性检查） |
| **Claim→Code** | Task inference（生成 shell 命令） | Claim→code mapping（定位代码位置） |
| **执行范围** | 完整 ML 实验（训练+评估） | 生物医学数据处理（不训练模型） |
| **执行隔离** | Docker per-paper image | Docker（参考 FactReview） |
| **Output 格式** | 固定 `metrics/*.json` | LLM 可从任意格式提取，但每个值必须带 provenance |

**为什么 Veritas 选择 Claim→Code Mapping 而非 Task Inference？**

Task Inference（FactReview 方式）：
- 从 repo 推断可执行任务（shell 命令列表）
- 不关心"哪行代码生成 Table 2"
- 适合 ML 论文（表格是整个训练流程的结果）

Claim→Code Mapping（Veritas 方式）：
- 定位生成 Table 2 的具体代码位置
- 执行该代码，提取结果
- 适合生物医学数据处理（表格通常是某个函数的直接输出）

**决策理由**：
- Veritas 的目标用户是生物医学实验室，不做 ML 训练
- 生物医学数据处理代码通常更简单，可以定位到具体函数
- ML repo 的复杂度（训练流程、超参数、GPU 依赖）会让系统变成"另一个 ML 框架"

**实现取向**：
- 最大化复用 FactReview 的 execution stage，而不是重新手写 Docker orchestrator、repair loop、attempt history、execution manifest
- Veritas 在 FactReview 之上增加生物医学表格语义：TableClaim、cell-level 对齐、容差配置、Veritas Finding/evidence 集成
- 系统默认 agentic：Agent 自动推断代码位置、执行计划、输出提取方式和修复策略；只有低置信度、高风险操作或无法继续时才请求用户确认

### 2.3 设计原则

1. **Claim-centric，不是 paper-centric**
   - 每个表格是一个 Claim
   - 每个 cell 有独立的 verdict

2. **Evidence first**
   - 所有结论必须有执行证据支撑
   - LLM 推断必须标注置信度，用户可修正

3. **Fail-loud，不是 fail-silent**
   - 执行失败时明确标记 inconclusive
   - 展示失败原因，不吞掉错误

4. **用户可控**
   - 默认自动推进，不把用户确认作为每一步的必经环节
   - LLM 推断的代码映射、执行计划和结果提取必须可追溯，用户可在必要时修正
   - 容差可配置，适应不同数据类型

---

## 3. 产品设计

### 3.1 用户流程

```
┌─────────────────────────────────────────────────────────────────────┐
│ Step 1: 上传输入                                                      │
│   - 论文 PDF（MinerU 提取表格）                                        │
│   - 或：手动上传表格截图/CSV                                           │
│   - 代码仓库（本地目录）                                               │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Step 2: Table 识别                                                   │
│   - 系统从论文中提取所有表格                                           │
│   - 展示表格列表，用户确认要复现哪些                                   │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Step 3: Claim→Code 推断                                              │
│   - LLM 分析每个表格 + 代码结构                                       │
│   - 输出候选代码位置 + 执行计划（带置信度）                             │
│   - 高置信度自动进入执行；低置信度/高风险时请求用户确认或手动指定        │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Step 4: 执行 + Repair Loop                                           │
│   - 复用 FactReview execution loop 构建/运行 Docker                    │
│   - 执行代码                                                        │
│   - 失败时尝试 overlay 修复（依赖/路径/配置），不修改用户仓库             │
│   - 最多重试 5 次（沿用 FactReview 默认预算）                           │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Step 5: 结果比对                                                      │
│   - LLM 从执行输出中提取结构化数据，并给出 source span/confidence        │
│   - 与论文表格逐 cell 比对                                            │
│   - 生成 cell-level verdict                                          │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Step 6: 展示结果                                                      │
│   - 每个表格的复现结果                                                │
│   - 每个 cell 的 verdict（match/mismatch/inconclusive）               │
│   - 执行证据（log、输出文件）                                         │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 数据结构

#### 3.2.1 Claim Schema

```python
@dataclass
class CellVerdict:
    """单个 cell 的复现结果"""
    row: int
    col: str
    paper_value: str | float  # 论文中的值
    execution_value: str | float | None  # 复现的值，None 表示无法提取
    verdict: Literal["match", "mismatch", "unextractable"]
    diff: float | None  # 数值差异，字符串为 None
    tolerance: float = 0.01  # 容差（相对误差 1%）
    extraction_confidence: float | None = None
    source_artifact: str | None = None  # 输出文件、stdout/stderr 或 notebook cell
    source_span: str | None = None  # 原始输出中的定位，如行号、JSON path、表格坐标
    source_snippet: str | None = None  # 支撑 execution_value 的短片段

@dataclass
class CodeCandidate:
    """LLM 推断的代码候选"""
    file_path: str
    line_range: tuple[int, int]
    function_name: str | None
    confidence: float  # 0-1
    reasoning: str  # LLM 的推断理由

@dataclass
class ExecutionPlan:
    """Agent 推断的执行计划，真正驱动 Runtime 执行"""
    entry_command: list[str]  # 如 ["python", "analysis/correlation.py"]
    cwd: str
    input_paths: list[str]
    expected_outputs: list[str]  # 文件路径、glob、stdout table hint
    timeout_sec: int = 1800
    env: dict[str, str] = field(default_factory=dict)  # 禁止包含 secret
    random_seed: int | None = None
    confidence: float = 0.0
    reasoning: str = ""

@dataclass
class CodeCandidateWithPlan:
    """代码位置和执行计划的绑定候选"""
    code: CodeCandidate
    execution_plan: ExecutionPlan
    confidence: float
    requires_user_confirmation: bool = False
    confirmation_reason: str = ""

@dataclass
class TableClaim:
    """Table-level claim，cell-level verdict"""
    claim_id: str
    table_id: str  # "Table 2", "Supplementary Table S1"
    caption: str  # 表格标题/描述
    location: PaperLocation  # page, section
    paper_table: list[dict]  # 论文中的表格数据
    
    # LLM 推断的代码位置
    inferred_code: list[CodeCandidate]  # 候选代码，带置信度
    inferred_candidates: list[CodeCandidateWithPlan]
    selected_code: CodeCandidate | None  # 用户选择的代码
    inferred_execution_plans: list[ExecutionPlan]
    selected_execution_plan: ExecutionPlan | None
    
    # 复现结果
    cell_verdicts: list[CellVerdict]
    
    # 整体 verdict
    @property
    def verdict(self) -> Literal["match", "partial_match", "mismatch", "inconclusive"]:
        if not self.cell_verdicts:
            return "inconclusive"
        mismatches = sum(1 for v in self.cell_verdicts if v.verdict == "mismatch")
        unextractable = sum(1 for v in self.cell_verdicts if v.verdict == "unextractable")
        if mismatches == 0 and unextractable == 0:
            return "match"
        elif mismatches == len(self.cell_verdicts):
            return "mismatch"
        elif mismatches > 0:
            return "partial_match"
        else:
            return "inconclusive"
```

#### 3.2.2 Execution Schema

```python
@dataclass
class ExecutionAttempt:
    """单次执行尝试"""
    attempt_id: int
    phase: Literal["prepare", "plan", "run", "judge", "fix", "finalize"]
    status: Literal["success", "failed", "timeout", "skipped"]
    return_code: int | None
    stdout: str
    stderr: str
    output_files: list[str]  # 执行产出的文件
    duration_sec: float
    fix_applied: str | None  # 应用的修复（如果有）
    command_manifest: dict
    artifact_hashes: dict[str, str]

@dataclass
class ExecutionEvidence:
    """执行证据"""
    claim_id: str
    status: Literal["success", "partial", "inconclusive", "failed"]
    docker_image: str  # 使用的 Docker 镜像
    docker_image_digest: str | None
    execution_plan: ExecutionPlan
    sandbox_policy: dict  # MVP 可为 Docker-only，生产前必须补资源/网络/挂载限制
    overlay_dir: str | None  # repair 只允许写入 overlay，不修改用户仓库
    attempts: list[ExecutionAttempt]  # 执行历史
    final_output_files: list[str]  # 最终成功的输出文件
    extracted_table: list[dict]  # LLM 从输出中提取的表格，必须带 source span/confidence
    error: str | None  # 最终错误（如果失败）
```

#### 3.2.3 与现有 Finding 的集成

```python
@dataclass
class ReproducibilityFinding:
    """代码复现产生的 Finding"""
    finding_id: str
    table_claim: TableClaim
    execution_evidence: ExecutionEvidence
    risk_level: Literal["high", "medium", "low", "info"]
    
    def to_finding(self) -> Finding:
        """转换为现有 Finding 格式"""
        return Finding(
            finding_id=self.finding_id,
            category="code_reproducibility",
            risk_level=self.risk_level,
            summary=self._generate_summary(),
            issue_category="matching",
            evidence_source="execution",
            evidence_refs=[...],  # 指向 execution.json、attempt manifest、输出文件等 EvidenceItem
            claim_refs=[self.table_claim.claim_id],
            metadata={
                "table_id": self.table_claim.table_id,
                "table_verdict": self.table_claim.verdict,
                "code_candidate": (
                    asdict(self.table_claim.selected_code)
                    if self.table_claim.selected_code
                    else None
                ),
                "execution_plan": (
                    asdict(self.table_claim.selected_execution_plan)
                    if self.table_claim.selected_execution_plan
                    else None
                ),
            },
        )
```

契约更新顺序：新增 `tool_id=code_reproduction` 和 artifact schema → FactReview adapter producer → bundle/evidence consumer → report/html render → fixture/golden tests。

#### 3.2.4 Verdict 分层

| 层级 | 字段 | 取值 | 含义 |
|---|---|---|---|
| Run | `ExecutionEvidence.status` | `success` / `partial` / `inconclusive` / `failed` | 代码复现流程是否完成 |
| Table | `TableClaim.verdict` | `match` / `partial_match` / `mismatch` / `inconclusive` | 表格整体复现一致性 |
| Cell | `CellVerdict.verdict` | `match` / `mismatch` / `unextractable` | 单个 cell 是否与执行结果一致 |

### 3.3 用户界面

#### 3.3.1 Table 选择页面

```
┌─────────────────────────────────────────────────────────────────────┐
│ 代码复现 - 选择要验证的表格                                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│ [✓] Table 1: Patient Demographics (Page 3)                          │
│     [预览] [展开]                                                    │
│                                                                      │
│ [✓] Table 2: Correlation Analysis (Page 5)                          │
│     [预览] [展开]                                                    │
│                                                                      │
│ [ ] Table 3: Regression Results (Page 7)                            │
│     [预览] [展开]                                                    │
│                                                                      │
│ [开始推断代码位置]                                                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

#### 3.3.2 代码映射/执行计划页面

```
┌─────────────────────────────────────────────────────────────────────┐
│ Table 2: Correlation Analysis - Agent 执行计划                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│ 论文表格:                                                            │
│ ┌──────────┬────────────┬──────────┬─────────────┐                  │
│ │ biomarker│ correlation│ p_value  │ significant │                  │
│ ├──────────┼────────────┼──────────┼─────────────┤                  │
│ │ CRP      │ 0.45       │ 0.001    │ yes         │                  │
│ │ IL6      │ 0.32       │ 0.045    │ yes         │                  │
│ │ TNF      │ 0.18       │ 0.12     │ no          │                  │
│ └──────────┴────────────┴──────────┴─────────────┘                  │
│                                                                      │
│ Agent 选择:                                                          │
│                                                                      │
│ 代码位置: analysis/correlation.py:45 - compute_crp_correlation()      │
│ 执行命令: python analysis/correlation.py --input data/raw.csv         │
│ 预期输出: outputs/table2.csv                                          │
│ 置信度: 85%                                                          │
│ 状态: 自动执行中                                                      │
│                                                                      │
│ 候选备选:                                                            │
│                                                                      │
│ 1. analysis/correlation.py:45 - compute_crp_correlation()            │
│     置信度: 85%                                                      │
│     理由: "函数返回 DataFrame，列名与 Table 2 匹配"                   │
│                                                                      │
│ 2. stats/regression.py:120 - run_regression_analysis()               │
│     置信度: 60%                                                      │
│     理由: "涉及 CRP 变量，但输出格式不完全匹配"                       │
│                                                                      │
│ [暂停并修改计划] [查看推断依据]                                       │
│                                                                      │
│ 仅当置信度低、计划缺失、执行涉及高风险操作时，系统要求用户确认。          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

#### 3.3.3 复现结果页面

```
┌─────────────────────────────────────────────────────────────────────┐
│ Table 2: Correlation Analysis - 复现结果                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│ 整体结果: PARTIAL MATCH (2/3 cells match)                           │
│                                                                      │
│ 代码位置: analysis/correlation.py:45                                │
│ Docker 镜像: paper-abc123                                           │
│ 执行时间: 12.3s                                                     │
│                                                                      │
│ ┌──────────┬────────────┬──────────┬─────────────┬──────────┐       │
│ │ biomarker│ paper_val  │ exec_val │ verdict     │ diff     │       │
│ ├──────────┼────────────┼──────────┼─────────────┼──────────┤       │
│ │ CRP      │ 0.001      │ 0.001    │ ✓ match     │ 0.00%    │       │
│ │ IL6      │ 0.045      │ 0.048    │ ✗ mismatch  │ 6.67%    │       │
│ │ TNF      │ 0.12       │ 0.12     │ ✓ match     │ 0.00%    │       │
│ └──────────┴────────────┴──────────┴─────────────┴──────────┘       │
│                                                                      │
│ 容差设置: 相对误差 1% + p 值绝对容差 0.001                           │
│                                                                      │
│ [查看执行日志] [下载证据包]                                           │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. 技术设计

### 4.1 架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Web UI / CLI                               │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    engine/reproduction/                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ TableClaim   │  │ CodeMapper   │  │ FactReview   │              │
│  │ (数据结构)   │  │ (LLM 推断)   │  │ Adapter       │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ ResultExtract│  │ VerdictCalc  │  │ RepairLoop   │              │
│  │ (LLM+溯源)   │  │ (比对)       │  │ (FactReview) │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│               Tool Registry: tool_id=code_reproduction               │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│                        Runtime (Docker)                              │
│  - 调用/封装 FactReview execution stage                              │
│  - 构建 per-paper image                                              │
│  - 执行代码、记录 attempt history                                     │
│  - 收集输出、hash、manifest                                           │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.1.1 FactReview 复用策略

FactReview 是代码复现主干，Veritas 不重新实现以下能力：
- Docker per-paper workspace/image 管理
- `prepare → plan → run → judge → fix → finalize` execution loop
- 多 attempt history、执行 summary、alignment/execution artifact 写盘
- 环境/依赖/路径类 repair loop

Veritas 新增的部分：
- 面向生物医学表格的 `TableClaim` 和 cell-level verdict
- Claim→Code→ExecutionPlan 的 Agent prompt 和 schema
- LLM extraction provenance：每个提取值必须给出 source artifact、source span、confidence、snippet
- `tool_id=code_reproduction` 的 Tool Registry 契约，以及与现有 `Finding` / `EvidenceItem` / HTML report 的集成

MVP 采用 Docker-only 隔离以加快落地；生产前必须增加网络、资源、挂载、secret 和输出目录白名单策略。

### 4.2 关键模块

#### 4.2.1 Table Extraction（表格提取）

**输入**：论文 PDF 或用户上传的表格

**处理**：
1. 使用 MinerU 提取论文中的表格（Veritas 已有 MinerU）
2. 解析表格结构（行、列、表头）
3. 生成 `TableClaim` 列表

**输出**：`list[TableClaim]`（paper_table 字段已填充）

#### 4.2.2 Code Mapper（代码映射）

**输入**：TableClaim + 代码仓库目录

**处理**：
1. 扫描代码仓库结构（文件列表、函数签名、README、requirements/environment、常见输出目录）
2. 对每个 TableClaim，LLM 推断候选代码位置
3. Agent 进一步生成 `ExecutionPlan`：entry command、cwd、输入路径、预期输出、超时、seed
4. 高置信度计划自动进入执行；低置信度、缺少输入数据或潜在高风险命令时请求用户确认
5. 输出 `CodeCandidate` + `ExecutionPlan` 列表（带置信度）

**LLM Prompt 设计**：
```
你是一个生物医学数据分析专家。给定一个论文表格和代码仓库结构，推断哪个代码位置生成了这个表格，并生成可执行的复现计划。

论文表格:
{table_content}

代码仓库结构:
{repo_structure}

请输出候选代码位置和执行计划（最多 3 个），每个包含：
- file_path: 文件路径
- line_range: 行号范围
- function_name: 函数名（如果有）
- entry_command: 可执行命令，数组形式
- cwd: 工作目录
- input_paths: 需要的输入文件/目录
- expected_outputs: 预期输出文件、glob 或 stdout table hint
- timeout_sec: 超时时间
- confidence: 置信度 0-1
- reasoning: 推断理由

输出 JSON 格式。
```

**输出**：`list[CodeCandidateWithPlan]`

#### 4.2.3 Executor（执行器）

**输入**：TableClaim + 选中的 CodeCandidate + ExecutionPlan + 代码仓库

**处理**：
1. 通过 `tool_id=code_reproduction` 进入 Runtime
2. 调用/封装 FactReview execution stage
3. 构建 Docker 镜像并执行 `ExecutionPlan.entry_command`
4. 收集输出文件、stdout/stderr、manifest、hash
5. 失败时进入 FactReview repair loop，修复仅写入 overlay

**Docker 策略**（参考 FactReview）：
- per-paper image：为每个论文构建独立镜像
- 自动检测环境类型（requirements.txt → venv, environment.yml → conda）
- 基础镜像：python:3.11-slim
- MVP 安全策略：Docker-only 隔离；生产前必须补网络、挂载、资源和 secret 策略

**Repair Loop**：
```python
MAX_ATTEMPTS = 5

for attempt in range(MAX_ATTEMPTS):
    result = factreview_execution_stage.run(execution_plan)
    
    if result.success:
        break
    
    # 分析错误
    error = classify_error(result.stderr)
    
    if error == "dependency_missing":
        fix = f"overlay pip install {missing_package}"
    elif error == "path_not_found":
        fix = "overlay adjust_path"
    elif error == "import_error":
        fix = "overlay add_to_requirements"
    else:
        break  # 无法自动修复
    
    apply_fix_to_overlay(fix)

return result
```

**输出**：`ExecutionEvidence`

#### 4.2.4 Result Extractor（结果提取器）

**输入**：执行输出文件 + 论文表格

**处理**：
1. 优先使用确定性 parser 读取 CSV/JSON/XLSX/HTML/stdout table
2. LLM 可从任意输出中提取结构化数据，但每个值必须给出 source artifact、source span、source snippet、confidence
3. 与论文表格对齐（行、列匹配）
4. 生成 `extracted_table`

**LLM Prompt 设计**：
```
你是一个数据提取专家。给定代码执行输出和论文表格，从输出中提取与论文表格对应的数据。

执行输出文件:
{output_content}

论文表格:
{paper_table}

请提取与论文表格结构相同的数据，输出 JSON 格式。
每个 cell 必须包含：
- value: 提取值，无法提取时为 null
- source_artifact: 来源文件或 stdout/stderr
- source_span: 行号、JSON path、表格坐标或 notebook cell
- source_snippet: 支撑该值的原始短片段
- confidence: 0-1
```

**输出**：`list[dict]`（值 + provenance）

#### 4.2.5 Verdict Calculator（判定计算器）

**输入**：paper_table + extracted_table + tolerance

**处理**：
1. 逐 cell 比对
2. 计算 diff
3. 判断 verdict（match/mismatch/unextractable）

**比对逻辑**：
```python
def compare_cell(paper_val, exec_val, tolerance: ToleranceConfig):
    if exec_val is None:
        return "unextractable"
    
    # 数值比对
    if isinstance(paper_val, (int, float)) and isinstance(exec_val, (int, float)):
        abs_diff = abs(paper_val - exec_val)
        rel_diff = abs_diff / abs(paper_val) if paper_val != 0 else None

        matched_by_absolute = (
            tolerance.absolute_error is not None
            and abs_diff <= tolerance.absolute_error
        )
        matched_by_relative = (
            rel_diff is not None
            and rel_diff <= tolerance.relative_error
        )
        matched_by_rounding = values_round_to_same_display(
            paper_val, exec_val, tolerance.display_precision
        )

        if matched_by_absolute or matched_by_relative or matched_by_rounding:
            return "match", rel_diff if rel_diff is not None else abs_diff
        else:
            return "mismatch", rel_diff
    
    # 字符串比对
    if str(paper_val).strip().lower() == str(exec_val).strip().lower():
        return "match", 0.0
    else:
        return "mismatch", None
```

**输出**：`list[CellVerdict]`

### 4.3 容差配置

默认容差：相对误差 1%，绝对误差 1e-9；p 值默认绝对容差 0.001。

```python
@dataclass
class ToleranceConfig:
    relative_error: float = 0.01  # 相对误差 1%
    absolute_error: float | None = 1e-9  # 避免 paper_val=0 时误判
    
    # 特殊数据类型的容差
    p_value_tolerance: float = 0.001  # p 值的绝对容差
    percentage_tolerance: float = 0.01  # 百分比的相对容差
    display_precision: int | None = None  # 论文展示值的四舍五入精度
```

用户可在界面上调整容差。

### 4.4 失败降级

| 失败类型 | 处理方式 |
|---|---|
| Docker 构建失败 | 标记 inconclusive，展示错误日志 |
| 代码执行失败（重试 5 次后） | 标记 inconclusive，展示错误日志、attempt history、overlay 修复记录 |
| LLM 无法提取结果 | cell 标记 unextractable，展示原始输出和缺失的 source span |
| LLM 推断不出候选代码或 ExecutionPlan | Agent 请求用户手动指定代码位置/命令 |
| 高风险命令或缺少关键输入 | 暂停执行，请求用户确认或补充输入 |

---

## 5. MVP 范围

### 5.1 包含

| 功能 | 说明 |
|---|---|
| Table 提取 | MinerU 自动提取 + 用户上传 CSV/截图 |
| Code 仓库 | 用户上传本地目录 |
| Claim→Code 映射 | LLM/Agent 推断代码位置和 ExecutionPlan，必要时才请求用户确认 |
| 执行 | 复用 FactReview execution stage，Docker-only 隔离，自动检测环境（venv/conda） |
| Repair loop | 复用 FactReview repair loop；只允许 overlay 修复依赖缺失、路径错误，不修改用户仓库 |
| 结果提取 | LLM 从任意格式提取，但每个值必须包含 source span/confidence/snippet |
| 比对 | 逐 cell 比对，支持相对误差、绝对误差、p 值、百分比、四舍五入 |
| 展示 | Web UI 展示复现结果 |

### 5.2 不包含

| 功能 | 原因 |
|---|---|
| ML 训练 | 复杂度太高，不在本次范围 |
| GitHub URL 克隆 | MVP 先用本地目录 |
| 多语言支持 | 只做 Python |
| 分布式执行 | 单机执行足够 |
| 自动修复代码 | 只修复环境和配置 |

### 5.3 Golden Case

MVP 验证用例：
- 1 篇真实生物医学论文
- 2-3 个表格
- 数据处理类代码（pandas/scipy/statsmodels）
- 总执行时间 < 30 分钟

MVP 验收门槛：
- 至少覆盖 match、mismatch、inconclusive 三类 table verdict
- 每个 matched/mismatched cell 都必须能追溯到 source artifact + source span
- 每次执行必须产出 command manifest、attempt history、artifact hash、overlay 修复记录
- Docker-only 隔离只允许进入 MVP；生产发布前必须完成安全硬化

---

## 6. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| **LLM 推断代码位置不准** | 用户需要手动修正，体验差 | 展示置信度，低置信度时提示用户确认 |
| **Docker 构建慢** | 用户等待时间长 | 缓存基础镜像，增量构建 |
| **代码执行环境复杂** | 修复失败，无法复现 | 复用 FactReview repair loop；最多重试 5 次，失败后标记 inconclusive |
| **LLM 提取结果不准** | 比对结果错误 | 每个值必须带 source span/confidence/snippet；低置信度 cell 标记 unextractable 或请求用户确认 |
| **MVP 只靠 Docker 隔离** | 任意代码执行存在安全风险 | MVP 限内测；生产前补网络、资源、挂载、secret、输出白名单策略 |
| **全量 MVP 范围过大** | 交付周期和集成风险上升 | 最大化复用 FactReview；按 Table extraction、mapping、execution、extraction、report 分阶段验收 |
| **FactReview 依赖/许可证变化** | 复用受阻或引入维护成本 | 做 adapter 层隔离；锁定 commit；记录许可证和变更边界 |
| **表格结构复杂** | 无法正确解析 | 支持用户上传 CSV 作为 ground truth |
| **破坏现有 Finding 结构** | 影响现有功能 | ReproducibilityFinding 作为新类型，兼容现有结构 |

---

## 7. 附录

### 7.1 参考实现

- **FactReview**: https://github.com/DEFENSE-SEU/FactReview
  - Claim schema: `src/schemas/claim.py`
  - Execution orchestrator: `src/fact_generation/execution/graph.py`
  - Docker 实现: `src/fact_generation/execution/tools/docker.py`
  - Repair loop: `src/fact_generation/execution/nodes/fix.py`
  - Stage runner: `src/fact_generation/execution/stage_runner.py`

### 7.2 术语表

| 术语 | 定义 |
|---|---|
| **Claim** | 论文中的一个声明（本文档中指一个表格） |
| **TableClaim** | 表格级别的 claim，包含多个 cell |
| **CellVerdict** | 单个 cell 的复现结果 |
| **CodeCandidate** | LLM 推断的代码位置候选 |
| **Repair Loop** | 执行失败时自动修复环境的循环 |
| **ExecutionEvidence** | 执行证据（log、输出文件、hash） |

### 7.3 决策记录

| 决策 | 理由 |
|---|---|
| Claim→Code Mapping（而非 Task Inference） | 生物医学数据处理代码简单，可定位到具体函数；ML repo 复杂度太高 |
| 最大化复用 FactReview execution stage | 已有 `prepare → plan → run → judge → fix → finalize`、Docker、attempt history、repair loop，不重复造轮子 |
| Agentic 优先，必要时才人机交互 | 降低导师操作负担；低置信度、高风险、缺少输入时再请求用户确认 |
| MVP 采用 Docker-only 隔离 | 先验证端到端价值；生产前必须补完整安全硬化 |
| LLM 提取结果（而非预设格式） | 生物医学代码输出格式多样，无法穷举；但每个值必须带 source span/confidence/snippet |
| Table-level claim + cell-level verdict | 平衡粒度和复杂度 |
| 不做 ML 训练 | 复杂度爆炸，不在本次范围 |
| 修复只写 overlay | 保留 agentic repair 能力，同时不修改用户仓库、不污染原始证据 |
| 报告定位为 execution-backed consistency check | 只展示执行证据和一致性事实，不宣称学术认证或学术不端判断 |

---

**文档结束**
