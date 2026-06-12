# PRD：opencode Agent Function Runtime 与 Veritas 受控 Artifact 工具体系

## Problem Statement

Veritas 当前已经把 opencode 接入 `audit-paper` 流水线，用于材料计划、审查计划、调查规划、结构化审阅和 role layer 复核。但当前集成仍存在三个核心问题：

1. opencode 在非交互模式下仍可能尝试通过 bash 读取审查产物；一旦命中需要询问的权限，运行会 auto-reject，导致 Agent 输出不是期望 JSON，进而触发结构化校验失败。
2. Agent 失败详情会被压进进度事件的 `detail` 字段，造成 Web 事件流冗长、不可读，也让 UI 很难稳定区分权限失败、JSON 校验失败、模型失败和真实审查失败。
3. 如果直接通过 `--file` 把原始 PDF、完整 Markdown、大型 JSON、图片或散落产物交给 opencode，会造成上下文过大、推理焦点稀释、成本上升和结构化输出不稳定。

从用户视角看，导师和内部操作员需要的是一个稳定、可追溯、可复核的论文技术审查流水线，而不是一个会随机因为 Agent 自行读文件或输出格式漂移而卡住的系统。Veritas 必须把 opencode 从“可自由操作仓库的 Agent”收敛成“受控的结构化推理函数”，同时保留 Agent 对 claim 映射、良性解释压力测试和人工复核任务生成的价值。

## Solution

建设一个 Veritas Agent Function Runtime，将 opencode 封装为可审计、可重试、可替换的结构化推理节点。

### P0：稳定现有链路（2-3 周）

**目标**：解决三个核心故障模式，让 `audit-paper` happy path 稳定跑通。

1. **AgentContextPack**：bounded context 输入结构
   - 硬约束：max 200k tokens per pack，max 50k tokens per artifact excerpt
   - 截断策略：head+tail（保留开头和结尾，中间用 `[...truncated...]` 替代）或 summary（用 LLM 生成摘要）
   - 必须包含：artifact manifest、evidence refs、Top-N findings、limitations、bounded excerpts
   - 不包含：原始 PDF、图片、完整 evidence ledger、大型 investigation output

2. **AgentStepRunner**：统一 opencode 调用接口
   - 职责：写入 context pack → subprocess.run opencode → 提取 JSON → schema 校验 → 错误分类 → 日志落盘 → 返回 AgentRunResult
   - **不包含 cache lookup**：orchestrator 层在调用前查缓存，保留现有 `--force` 语义
   - 错误分类：timeout / schema_validation / permission_rejected / model_failure / non_zero_exit

3. **Progress Event 合约清理**
   - 只记录短事件：step、status、summary（max 200 chars）、log_ref
   - 长 stdout/stderr 写入日志 artifact，通过 `log_ref` 引用
   - 契约测试：验证 `step_result.detail` 不包含长文本

4. **Run Record 与 Stale Recovery**
   - run 启动时立即写入 workdir（status=running, started_at=now）
   - backend 启动时扫描 status=running 的 run，如果 last_event_at < now - 5min，标记为 failed/interrupted

### P1：增强可观测性与视觉调查集成（2-4 周）

**目标**：让 investigation 追加产物进入 Agent review 视野，完善失败分类。

1. **Agent Failure Taxonomy**
   - 分层：transient（可重试）/ permanent（需人工介入）/ partial（部分成功）
   - 报告中 limitations 分层展示，不伪装成完整结论

2. **Visual Investigation Integration**
   - investigation 追加产物（copy-move heatmap、TruFor regions、CBIR matches）纳入 compact context pack
   - Agent review 能读取已执行的视觉调查摘要，生成结构化 manual review tasks

3. **轻量 Artifact Slice Tool（可选）**
   - 如果 context pack 模式遇到瓶颈（Agent 需要多次迭代读取不同 slice），引入轻量工具
   - 不走完整 MCP，先作为 deterministic tool 注册到 Tool Registry
   - 接口：`read_artifact_slice(artifact_id, start_line, end_line, max_tokens)`

### P2：Agent-Native 架构演进（长期）

**目标**：提供受控的 artifact 访问能力，支持交互式人工复核，同时充分利用模型已有的 bash 能力。

**核心原则**：**不发明新协议，利用模型已有的 bash 能力**。bash 已经在 LLM 的预训练知识里，MCP 需要重新学习。正确的方向是**约束 bash 的能力边界**，而不是替换 bash。

1. **Veritas Artifact CLI（受控命令行工具）**
   - 提供 `veritas-artifact` CLI，Agent 通过 bash 调用
   - 命令白名单：
     ```bash
     veritas-artifact list --run-id <run_id>
     veritas-artifact read <artifact_id> --lines 10-50 --max-tokens 50000
     veritas-artifact summary <artifact_id>
     veritas-artifact write --role claim_extractor --output output.json
     ```
   - 通过命令行参数约束能力边界（`--max-tokens`、`--lines`）
   - 通过 sandbox 白名单限制只能调用 `veritas-artifact`，不允许 `cat paper.pdf`、`rm -rf outputs/`、`curl http://...`
   - **保留 bash 的灵活性**：Agent 可以 `veritas-artifact read xxx | jq '.findings[:5]'`

2. **交互式人工复核工作区**
   - 用户围绕 evidence refs 向 Agent 追问，而不是重跑完整审查
   - Agent 可以通过 `veritas-artifact` CLI 读取更多 artifact slice
   - 但不修改 deterministic evidence，只生成 agent_artifact

### 最终边界

```text
输入材料
  ↓
deterministic tools / Tool Registry
  ↓
structured artifacts
  ↓
compact Agent context pack（bounded, validated）
  ↓
opencode Agent Function（AgentStepRunner）
  ↓
validated agent artifact（schema-checked）
  ↓
static_audit_bundle / report / Web event stream
```

## User Stories

### P0 必须（解决核心故障模式）

1. **[P0] 作为内部操作员**，我希望 opencode 非交互运行时不再因为 bash permission auto-reject 破坏 JSON 输出，以便 Web happy path 可以稳定跑通。→ Implementation Decision: AgentStepRunner 统一调用；Testing Decision: fake opencode tests

2. **[P0] 作为开发者**，我希望所有 opencode 调用走统一的 AgentStepRunner，以便 timeout、retry、schema validation 和错误分类不再分散在多个调用点。→ Implementation Decision: AgentStepRunner；Testing Decision: unit tests for all error categories

3. **[P0] 作为开发者**，我希望 Agent 输入由 compact context pack 管理，以便控制上下文大小、成本和输出稳定性。→ Implementation Decision: AgentContextPack with hard limits；Testing Decision: fixture-based unit tests

4. **[P0] 作为开发者**，我希望可以独立测试 compact context pack 生成逻辑，以便确认大 artifact 不会直接进入 Agent 上下文。→ Testing Decision: fixture tests for PDF-only, Source Data, visual investigation cases

5. **[P0] 作为内部操作员**，我希望 Web progress event 保持短小结构化，以便 Mission Control 页面可以稳定展示。→ Implementation Decision: Progress Event 合约；Testing Decision: contract tests

6. **[P0] 作为内部操作员**，我希望长 stdout/stderr 自动落盘为日志 artifact，以便必要时可以深入排查，但不污染事件流。→ Implementation Decision: log_ref；Testing Decision: contract tests

7. **[P0] 作为内部操作员**，我希望 run 在后台中断后能自动恢复为 failed/interrupted 状态，以便不会长期停留在 running。→ Implementation Decision: Run Record + Stale Recovery；Testing Decision: integration tests

### P1 重要（增强可观测性与视觉调查）

8. **[P1] 作为 PI**，我希望审查进度稳定可读，以便判断当前 case 是否已经完成、卡住或需要人工复核。→ Implementation Decision: short progress events；Testing Decision: event stream tests

9. **[P1] 作为 PI**，我希望 Agent 失败被明确写成 limitation，而不是伪装成完整审查结论，以便正确理解报告可信度。→ Implementation Decision: Agent Failure Taxonomy；Testing Decision: report rendering tests

10. **[P1] 作为 PI**，我希望报告仍然区分 deterministic evidence 和 Agent interpretation，以便把技术事实和推理建议分开判断。→ Implementation Decision: 三层分层；Testing Decision: report rendering tests

11. **[P1] 作为内部操作员**，我希望每个 Agent step 都有明确的输入、输出、状态、耗时和错误摘要，以便快速定位失败原因。→ Implementation Decision: AgentRunResult metadata；Testing Decision: unit tests

12. **[P1] 作为审查员**，我希望可选视觉调查工具的输出被合并进 canonical evidence 图谱，以便视觉候选事实能进入统一报告。→ Implementation Decision: Visual Investigation Integration；Testing Decision: fixture tests

13. **[P1] 作为审查员**，我希望 Agent 只读取必要 evidence slice，而不是一次性读取全量 artifacts，以便输出更聚焦。→ Implementation Decision: bounded excerpts in context pack；Testing Decision: truncation strategy tests

14. **[P1] 作为产品负责人**，我希望新增 Agent 能力主要通过 prompt、schema 和 context pack 演进，以便减少分散代码改动。→ Implementation Decision: context pack 模式

### P2 长期（Agent-Native 架构演进）

15. **[P2] 作为开发者**，我希望 Agent review 和 role Agent 在默认情况下不需要 bash，以便非交互模式下不会出现权限询问。→ Implementation Decision: context pack only；Testing Decision: fake opencode tests

16. **[P2] 作为开发者**，我希望 deterministic tool 执行仍然只能通过 Tool Registry，以便 Agent 无法绕过产品工具边界。→ Implementation Decision: Tool Registry 边界；Testing Decision: Tool Registry boundary tests

17. **[P2] 作为开发者**，我希望每个 Agent 输出都必须通过 schema 校验，以便报告不会消费裸自然语言或错误事件。→ Implementation Decision: schema validation in AgentStepRunner；Testing Decision: schema validation tests

18. **[P2] 作为审查员**，我希望 Agent 生成的 claim、finding review 和 manual review task 都能回指 evidence refs，以便人工复核可以追溯到原始证据。→ Implementation Decision: evidence refs in Agent artifact

19. **[P2] 作为产品负责人**，我希望提供受控的 `veritas-artifact` CLI，让 Agent 通过 bash 访问 artifacts，以便充分利用模型已有的 bash 能力，而不是发明新协议。→ Implementation Decision: Veritas Artifact CLI（P2）

20. **[P2] 作为安全审查者**，我希望 Agent 不能修改用户输入、deterministic evidence 或审查工具源码，以便避免审查链路被非确定性推理污染。→ Implementation Decision: Agent 只写 agent_artifact，不改 deterministic evidence

21. **[P2] 作为测试维护者**，我希望 fake opencode fixture 能覆盖主要 Agent step，以便 CI 不依赖真实模型或外部 API。→ Testing Decision: fake opencode tests

22. **[P2] 作为测试维护者**，我希望事件流契约可测试，以便确保 Web 不再出现包含长 stdout/stderr 的单行事件。→ Testing Decision: contract tests

23. **[P2] 作为未来 Web 用户**，我希望在审查未完成时也能看到 artifact readiness，以便查看已经生成的中间证据。→ Implementation Decision: Run Record 早期写入

24. **[P2] 作为未来 Web 用户**，我希望可以基于 evidence refs 进一步向 Agent 提问，以便进入交互式人工复核工作区。→ Implementation Decision: 交互式人工复核工作区（P2）

## Implementation Decisions

### 核心决策

- 建立 Agent Function Runtime，把 opencode 视为受控结构化推理函数，而不是自由 shell Agent。
- 新增统一 AgentStepRunner 概念接口，负责执行 opencode、传入 context files、提取 JSON、校验 schema、分类错误、记录日志、返回 AgentRunResult。
- 建立 AgentContextPack，作为 opencode 的主要输入。
- 对 review 和 role Agent，默认禁止依赖 bash 读取 artifact；这些 Agent 应消费 context pack 并返回 JSON。
- 对 investigation planner，Agent 只能输出 Tool Registry 允许的 deterministic tool action；实际执行仍由 Python orchestrator 完成。
- deterministic evidence、Agent interpretation、report rendering 三者保持分层，报告不得直接从 Agent 自然语言总结生成。
- 未来如果替换 opencode 或接入其他 LLM runtime，只需要替换 AgentStepRunner 的 backend，不改变上层 orchestrator 契约。

### AgentContextPack 数据结构与量化标准

```python
class AgentContextPack:
    """
    Bounded context for Agent reasoning.
    Hard constraints prevent context overflow and cost explosion.
    """
    artifact_manifest: list[ArtifactSummary]  # id, type, size_bytes, summary
    evidence_refs: list[EvidenceRef]  # 关键 evidence 的引用，指向 artifact_id + line range
    top_n_findings: list[Finding]  # Top-N findings，N 可配置（默认 5）
    limitations: list[Limitation]  # 已知限制
    bounded_excerpts: dict[str, BoundedExcerpt]  # key: artifact_id, value: 截断后的内容
    truncation_config: TruncationConfig

class TruncationConfig:
    max_tokens_per_pack: int = 200_000  # 单个 pack 的硬上限
    max_tokens_per_excerpt: int = 50_000  # 单个 artifact excerpt 的硬上限
    strategy: Literal["head_tail", "summary", "sample"] = "head_tail"
    # head_tail: 保留开头 30% + 结尾 30%，中间用 [...truncated...] 替代
    # summary: 用 LLM 生成摘要（需要额外调用，P1 可选）
    # sample: 随机采样（不推荐，会丢失结构信息）
```

**判断标准**：Agent 是否需要"完整原文"才能完成当前角色。如果不需要，就传摘要和 evidence refs；如果确实需要局部原文，通过 bounded_excerpts 精确控制。

### AgentStepRunner 职责边界

```python
class AgentStepRunner:
    """
    统一 opencode 调用接口。
    不包含 cache lookup：orchestrator 层在调用前查缓存。
    """
    def run(
        self,
        role: str,
        context_pack: AgentContextPack,
        output_schema: type[BaseModel],
        timeout_seconds: int = 300,
        max_retries: int = 2,
    ) -> AgentRunResult:
        """
        1. 写入 context pack 到临时文件
        2. subprocess.run opencode --file context_pack.json --file prompt.md
        3. 提取 JSON（从 stdout 或输出文件）
        4. schema 校验
        5. 成功：写入 agent_artifact，返回 AgentRunResult(status=success)
        6. 失败：分类错误，写入日志 artifact，返回 AgentRunResult(status=failed, error_category=..., log_ref=...)
        """

class AgentRunResult:
    status: Literal["success", "failed", "skipped"]
    role: str
    output: BaseModel | None  # schema-validated Agent artifact
    error_category: Literal["timeout", "schema_validation", "permission_rejected", "model_failure", "non_zero_exit"] | None
    runtime_seconds: float
    log_ref: str | None  # 指向日志 artifact
    metadata: dict  # prompt_version, schema_version, model, token_usage
```

### 迁移路径：保留现有 trace 复用逻辑

当前 `engine/investigation/opencode_agent.py` 的 `run_agent_role()` 已经存在，且成功 role 在未指定 `--force` 时会复用已有 output/trace。迁移策略：

1. **AgentStepRunner 不包含 cache lookup**。orchestrator 层在调用 `AgentStepRunner.run()` 之前先查缓存。
2. **保留 `--force` 语义**。如果 `--force` 未指定，orchestrator 先检查已有 output；如果存在且 status=success，直接复用，不调用 AgentStepRunner。
3. **现有 `run_agent_role()` 逐步迁移**。先让 AgentStepRunner 和 `run_agent_role()` 并存，新 role 直接用 AgentStepRunner，旧 role 逐步迁移。
4. **迁移验证**：跑现有的 `audit-paper` 端到端测试，确保输出不变，trace 复用逻辑未被破坏。

### Progress Event 合约

```python
class ProgressEvent:
    step: str  # 例如 "agent_review", "claim_extraction"
    status: Literal["started", "success", "failed", "skipped"]
    summary: str  # 短摘要，max 200 chars
    log_ref: str | None  # 指向日志 artifact，失败时必填
    # 不包含：stdout, stderr, full traceback, context_pack, agent_output
```

### Run Record 与 Stale Recovery

```python
class RunRecord:
    run_id: str
    status: Literal["queued", "running", "success", "failed", "interrupted"]
    started_at: datetime
    last_event_at: datetime  # 每次写入 progress event 时更新
    artifacts: list[str]  # 已生成的 artifact 路径

# backend 启动时：
# for run in all_runs:
#     if run.status == "running" and now() - run.last_event_at > 5 minutes:
#         run.status = "interrupted"
#         append_event(run, "runner_interrupted", "Backend restart detected")
```

### 为什么选择 CLI 而不是 MCP

**核心判断**：bash 已经在 LLM 的预训练知识里，MCP 需要重新学习。正确的方向是**约束 bash 的能力边界**，而不是替换 bash。

**第一性原理分析**：

LLM 的能力边界 = 预训练知识 + 上下文学习

- **bash 是预训练知识**：模型见过海量的 bash 脚本、命令行交互、管道操作。它对 `cat`、`grep`、`jq`、`head`、`tail` 的理解是"肌肉记忆"。
- **MCP 需要上下文学习**：模型需要在 prompt 里学习 `list_artifacts`、`read_artifact_slice` 的语义，消耗 context window，而且容易出错。

**Linus 的判断**：不要重新发明轮子，除非你有充分的理由。自己发明 MCP 协议 = "Not Invented Here" 综合征。

**真正的问题**：bash 的问题不是"bash 本身不好"，而是"bash 给了 Agent 太多自由，可能绕过 Tool Registry"。解决方案应该是**约束 bash 的能力边界**，而不是**替换 bash**。

**对比方案**：

| 方案 | 优点 | 缺点 |
|---|---|---|
| **MCP / Domain Tools** | 细粒度权限控制 | 模型需要学习新协议，消耗 context window，容易出错 |
| **Veritas Artifact CLI** | 利用模型已有的 bash 能力，灵活（可以 pipe 到 jq） | 需要 sandbox 白名单限制调用范围 |
| **完全禁止 bash** | 最安全 | 失去 bash 的灵活性，模型无法做复杂查询 |

**结论**：选择 **Veritas Artifact CLI + sandbox 白名单**。既能利用模型的 bash 能力，又能防止绕过 Tool Registry。

### Veritas Artifact CLI（P2，受控命令行工具）

**核心原则**：不发明新协议，利用模型已有的 bash 能力。bash 已经在 LLM 的预训练知识里，MCP 需要重新学习。正确的方向是**约束 bash 的能力边界**，而不是替换 bash。

提供 `veritas-artifact` CLI，Agent 通过 bash 调用：

```bash
# Agent 可以执行（白名单）
veritas-artifact list --run-id <run_id>
veritas-artifact read <artifact_id> --lines 10-50 --max-tokens 50000
veritas-artifact summary <artifact_id>
veritas-artifact write --role claim_extractor --output output.json

# Agent 不能执行（sandbox 黑名单）
cat paper.pdf
rm -rf outputs/
curl http://...
```

**设计要点**：

1. **命令行参数约束能力边界**
   - `--max-tokens 50000`：限制单次读取的 token 数
   - `--lines 10-50`：限制读取的行范围
   - `--run-id`：限制只能访问当前 run 的 artifacts

2. **sandbox 白名单限制调用范围**
   - 只允许调用 `veritas-artifact` 和基础只读命令（`jq`、`grep`、`head`、`tail`）
   - 禁止 `rm`、`mv`、`cp`（不允许修改 artifacts）
   - 禁止 `curl`、`wget`（不允许网络访问）
   - 禁止 `python`、`node`（不允许执行任意代码）

3. **保留 bash 的灵活性**
   - Agent 可以 `veritas-artifact read xxx | jq '.findings[:5]'`
   - Agent 可以 `veritas-artifact list | grep claim`
   - 不需要学习新协议，bash 是模型的"母语"

4. **输出结构化**
   - `veritas-artifact list` 输出 JSON，方便 `jq` 处理
   - `veritas-artifact read` 输出文本或 JSON（根据 artifact 类型）
   - `veritas-artifact summary` 输出短摘要（max 1000 chars）

**边界**：`veritas-artifact` 是 artifact primitive，不是 workflow tool。它不能执行 MinerU、Source Data forensics、image forensics 或报告生成。

## Testing Decisions

### 核心原则

测试只验证外部可观察行为：artifact、manifest、event stream、AgentRunResult、schema validation 和 report limitations；不测试 prompt 内部措辞。

### P0 测试（必须）

1. **AgentContextPack fixture-based unit tests**
   - 覆盖：PDF-only case、Source Data case、visual investigation case
   - 验证：context pack 大小不超过 max_tokens_per_pack，excerpts 按 truncation strategy 截断
   - golden fixture：为每种 case 准备一个标准输入和期望输出

2. **AgentStepRunner unit tests**
   - 覆盖：成功 JSON、invalid JSON、schema validation failure、timeout、non-zero exit、permission rejected、empty output
   - mock：只打在 opencode subprocess 边界，验证错误分类和日志落盘
   - 验证：每种错误类型返回正确的 error_category 和 log_ref

3. **Progress Event contract tests**
   - 验证：`step_result.detail` 不包含长 stdout/stderr（max 200 chars）
   - 验证：失败事件包含 log_ref 指向日志 artifact
   - 验证：日志 artifact 文件存在且包含完整 stdout/stderr

4. **Web runner integration tests**
   - 验证：run 启动后立即写入 workdir（status=running, started_at=now）
   - 验证：running 状态下 artifacts 可被发现（通过 list artifacts API）
   - 验证：last_event_at 每次写入 progress event 时更新

5. **Stale run recovery tests**
   - 验证：queued/running run 在 backend 重启后（last_event_at > 5min）被标记为 interrupted
   - 验证：追加 `runner_interrupted` event，summary 包含 "Backend restart detected"
   - 验证：原有 artifacts 不被删除或覆盖

6. **迁移验证**
   - 跑现有的 `audit-paper` 端到端测试，确保输出不变
   - 验证：trace 复用逻辑未被破坏（未指定 `--force` 时复用已有 output）
   - 验证：`--force` 语义保留（强制重新调用 opencode）

### P1 测试（重要）

7. **Agent Failure Taxonomy tests**
   - 验证：transient 错误可重试（例如 timeout, model_failure）
   - 验证：permanent 错误不重试（例如 schema_validation, permission_rejected）
   - 验证：partial 成功写入 limitations，报告分层展示

8. **Visual Investigation Integration tests**
   - 验证：investigation 追加产物（copy-move heatmap, TruFor regions, CBIR matches）纳入 context pack
   - 验证：Agent review 能读取视觉调查摘要，生成结构化 manual review tasks
   - 验证：视觉工具失败写入 limitations，不伪装成完整结论

9. **Artifact Slice Tool tests（如果实现）**
   - 验证：read_artifact_slice 返回正确行范围，不超过 max_tokens
   - 验证：artifact_id 不存在时返回 404，不崩溃

### P2 测试（长期）

10. **Veritas Artifact CLI tests**
    - 验证：Agent 只能通过 `veritas-artifact` CLI 访问 artifacts
    - 验证：sandbox 白名单限制，不能执行 `rm`、`curl`、`python` 等
    - 验证：`--max-tokens` 参数生效，不能读取超过限制的 token 数

11. **Tool Registry boundary tests**
    - 验证：Agent 只能选择 agent-selectable deterministic tools
    - 验证：Agent 不能选择 Agent tools、report-only tools 或 mandatory bootstrap tools

12. **Report rendering tests**
    - 验证：Agent failed/warning 进入 limitations，不被当成 deterministic finding
    - 验证：报告区分 deterministic evidence 和 Agent interpretation

13. **Fake opencode tests**
    - 验证：Agent review 和 role Agent 不需要 bash 也能基于 context pack 产出合法 JSON
    - 验证：fake opencode 覆盖主要 Agent step（claim_extraction, source_data_audit, judge）

### 通用原则

复用现有测试风格：优先 fixture/golden case，mock 只打在 opencode subprocess、外部 API、时钟和文件系统边界。

## Out of Scope

- 不做最终科研诚信判定。
- 不允许 Agent 自动修改论文、Source Data、用户上传材料或 deterministic evidence。
- 不允许 Agent 绕过 Tool Registry 执行任意审查工具。
- 不把 opencode 改造成长期后台服务；当前仍以受控非交互调用为主。
- 不在 P0 中实现完整 MCP server；P0 先落地 context pack 和 AgentStepRunner。
- 不在 P0 中引入远程 worker、队列系统、多租户权限系统或完整 SaaS 任务系统。
- 不把全量 PDF、图片、大型 JSON 或完整 Markdown 直接传给模型作为默认行为。
- 不要求 Agent 在一次调用中完成所有审查推理；复杂审查可以拆成多个 bounded role step。

## Further Notes

### 分阶段落地路径

**P0（2-3 周）：稳定现有链路**
1. 实现 AgentContextPack（bounded context，硬约束 200k tokens per pack）
2. 实现 AgentStepRunner（统一 opencode 调用，错误分类，日志落盘）
3. 清理 Progress Event 合约（短事件，log_ref 引用日志 artifact）
4. Run Record 早期写入 + Stale Recovery（backend 启动时恢复 interrupted runs）
5. 迁移现有 `run_agent_role()` 到 AgentStepRunner，保留 trace 复用逻辑

**P1（2-4 周）：增强可观测性**
1. Agent Failure Taxonomy（transient / permanent / partial 分层）
2. Visual Investigation Integration（investigation 追加产物纳入 context pack）
3. 轻量 Artifact Slice Tool（可选，如果 context pack 模式遇到瓶颈）

**P2（长期）：Agent-Native 架构**
1. Veritas Artifact CLI（受控命令行工具，利用模型已有的 bash 能力）
2. 交互式人工复核工作区（用户围绕 evidence refs 向 Agent 追问）

**为什么不发明 MCP 协议**：
- bash 已经在 LLM 的预训练知识里，MCP 需要重新学习
- 正确的方向是**约束 bash 的能力边界**，而不是替换 bash
- 通过 `veritas-artifact` CLI + sandbox 白名单，既能利用模型的 bash 能力，又能防止绕过 Tool Registry

### `--file` 使用原则

| 类型 | 策略 | 示例 |
|---|---|---|
| **可以传** | compact context pack、小型 schema、少量 bounded excerpt | context_pack.json, prompt.md, schema.py |
| **谨慎传** | 中等大小的 JSON artifact（需要先截断或摘要） | static_audit_bundle.json（截断后） |
| **不应默认传** | 原始 PDF、图片、完整 Markdown、大型 evidence ledger | paper.pdf, full_evidence_ledger.json |

**判断标准**：Agent 是否需要”完整原文”才能完成当前角色。如果不需要，就传摘要和 evidence refs；如果确实需要局部原文，通过 bounded_excerpts 精确控制，或者 P1/P2 引入 artifact slice tool。

### 风险与缓解

| 风险 | 缓解措施 |
|---|---|
| Context pack 硬约束（200k tokens）可能不够某些复杂 case | P1 引入 summary strategy（用 LLM 生成摘要），或者 P1/P2 引入 artifact slice tool |
| 迁移现有 `run_agent_role()` 可能破坏 trace 复用逻辑 | 先让 AgentStepRunner 和 `run_agent_role()` 并存，逐步迁移；迁移验证用现有端到端测试 |
| Agent 可能仍然尝试调用 bash 读取 artifact | P0 先用 context pack 模式，Agent 不需要 bash；P2 用 `veritas-artifact` CLI + sandbox 白名单 |
| Stale run recovery 可能误判正常运行的 run | 5 分钟阈值可配置；heartbeat 机制可选（P1） |

### 成功标准

**P0 成功**：
- `audit-paper` happy path 稳定跑通，不再因为 bash permission auto-reject 破坏 JSON 输出
- Web progress event 保持短小（max 200 chars summary），长日志通过 log_ref 引用
- Run 启动时立即写入 workdir，stale runs 被正确恢复为 interrupted
- 现有 trace 复用逻辑未被破坏

**P1 成功**：
- Agent 失败被明确写成 limitation，报告中分层展示
- Visual investigation 追加产物进入 Agent review 视野
- 如果 context pack 模式遇到瓶颈，轻量 artifact slice tool 可用

**P2 成功**：
- MCP server 可用，Agent 可以按需读取 artifact slice
- 交互式人工复核工作区可用，用户可以围绕 evidence refs 向 Agent 追问
