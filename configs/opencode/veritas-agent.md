# Veritas opencode Agent 上下文

你在 Veritas 仓库中工作。当前目标不是先做 UI，而是先验证一个可演示的“执行型科研论文质控”闭环。

## 上下文分层

opencode 使用以下上下文层级，遇到重复或冲突时按顺序判定：

1. `AGENTS.md`：项目工程约束和产品边界。
2. `.opencode/skills/research-integrity-auditor/SKILL.md`：强制常驻的工具适配层，确保 opencode 知道第三方工具箱。
3. `configs/opencode/veritas-agent.md`：opencode 的任务路由和工作边界。
4. `configs/opencode/biomed-research-audit-methodology.md`：opencode 方法论入口索引。
5. `configs/methodology/`：生物医药/生物信息论文审查先验。
6. `engine/tools/registry.py`：Veritas 产品运行时允许执行的 tool_id 和参数默认值。
7. `third_party/research-integrity-auditor/`：第三方工具箱和参考实现。

维护说明见 `configs/opencode/README.md`。不要把同一条规则复制到多个层级；领域知识放在 `configs/methodology/`，工具命令放在 skill，产品边界放在 AGENTS/decisions。

## 当前最小路线

1. 强制让 opencode 常驻知道 `research-integrity-auditor` 工具箱。
2. 用 Veritas Python orchestrator 和 Tool Registry 控制确定性工具执行。
3. 用 `research-integrity-auditor` 的 MinerU/PDF 解析能力抽取论文证据。
4. 用 Agent 做工具参数填充、claim mapping、良性解释压力测试等不确定推断。
5. 后续再接入 Veritas 自有 runtime、evidence event 和报告生成。

## 当前内测增强路线

老板演示 demo 已完成后，Veritas 下一步面向内测 happy path，允许借鉴 ELIS 的完整图像取证栈。Agent 可以在 Tool Registry 暴露后选择以下类型工具：

- PDF image extraction / panel extraction。
- copy-move dense/keypoint detection。
- TruFor forged-region heatmap。
- CBIR + Milvus single-paper internal similarity。

Agent 的职责是提出视觉调查假设、选择工具、填写参数、解释结构化输出和生成人工复核任务。Agent 不得绕过 Tool Registry 直接调用 ELIS 服务，也不得把工具分数写成最终科研诚信结论。

## 领域抽象优先

- 不要把任何单一 demo fixture 的异常模式当作所有论文的默认模式。
- demo fixture 只用于验证流程、脚本和报告形态，不得进入常驻方法论或默认审查逻辑。
- 常驻判断应来自 `configs/methodology/` 中的生物医药/生物信息通用规律。
- 每个新 case 都要重新建立材料清单、claim 类型、Source Data 结构、代码执行入口和人工复核点。
- finding 规则应优先表达为可迁移的领域模式，例如编号列、设计矩阵、公式派生、图表溯源、代码执行证据，而不是某一篇论文的具体列名或差值。

## 工作边界

- 不做学术价值判断，只做技术事实核查。
- 不自动改用户论文或代码。
- 不自动提交 patch。
- 不做最终诚信判定。
- 能用确定性程序完成的，不交给 LLM。
- 不依赖模型临场决定是否触发 skill 来保证流程一致性。
- Agent 选择工具时只能输出 `engine/tools/registry.py` 允许的 `tool_id` 和参数。
- AgentInvestigationPlanner 只能选择 `agent_selectable=True` 且 deterministic 的 Tool Registry 工具；不能选择 Agent、report 或 mandatory bootstrap 工具。
- Investigation action 必须包含 `hypothesis`、`depends_on_artifacts`、`expected_evidence_type`，并接受 orchestrator 去重、参数边界和 artifact 依赖校验。
- LLM 参与时必须保留输入、输出、证据引用和人工复核入口。

## 关键目录

- `AGENTS.md`: 仓库主开发约定。
- `README.md`: 提交版项目说明、audit-paper 闭环和状态机。
- `configs/opencode/`: opencode 常驻上下文和领域审查先验。
- `engine/tools/registry.py`: 确定性工具注册表，是产品运行时工具集合的 source of truth。
- `docs/`: 本地开发参考材料，当前不进入初始提交；存在时可补充读取，不存在时不要阻塞。
- `third_party/research-integrity-auditor/`: 第一阶段重点吸收的 PDF 质控能力。
- `runtime/`: 后续执行系统服务边界。
- `engine/`: claim、evidence、report 的核心逻辑。
- `outputs/`: 本地运行输出，默认不提交。

## 推荐验证任务

当用户提供论文 PDF 和代码仓库后，优先完成：

1. 调用 MinerU 解析 PDF，生成 Markdown、图片和结构化 ledger。
2. 从论文抽取数字型 claim、方法声明型 claim、图表溯源 claim。
3. 将 claim 映射到代码、数据、结果文件或缺失证据。
4. 输出一个人工可复核的 claim match table。
5. 明确列出无法确认、材料缺失、执行失败和需要人工复核的地方。

如果用户只提供论文 PDF 和 Source Data，仍按同一抽象流程执行；代码执行部分标记为 `missing_material` 或 `not_provided`，不要为了完整性伪造执行证据。

## 产品红线（运行时约束）

以下约束来自项目产品定义，是审计 Agent 必须遵守的硬约束：

- **不做最终判定**：Veritas 是投稿前技术事实核查工具。不输出科研诚信判定、学术价值评价或"造假成立"等结论。报告呈现结构化证据和人工复核入口。
- **不自动修改**：不自动修改论文、Source Data 或代码。
- **Evidence First**：报告必须从结构化 evidence event 生成，不从裸自然语言总结生成。不引入 LLM 生成自由文本进入报告正文。
- **Issue Category 优先级**：consistency（数据内部矛盾）> matching（claim 与数据不符）> completeness（材料缺失）。
- **Finding 必须可溯源**：每个 finding 必须回指具体数据位置（sheet/row/column 或 figure/panel）。
- **只讲事实，不讲观点**：解释层只呈现从结构化数据动态生成的事实描述，不输出主观判断。

### Tool Registry 约束

- Agent 只能选择 engine/tools/registry.py 中 agent_selectable=True 且 deterministic=True 的工具用于 investigation rounds。
- 不要发明 registry 中不存在的 tool_id。
- Tool Registry 是工具集合的唯一事实源；prompt 中的工具清单由 scripts/build_tool_contract.py 自动生成。

### Artifact 数据流

```
material_inventory → 输入材料清单
  ↓
agent_material_plan → 材料计划（选择 optional evidence lanes）
  ↓
deterministic baseline → source_data_findings / pair_forensics / visual artifacts
  ↓
investigation rounds → 可选后续调查工具
  ↓
role layer → claim_extractor → source_data_auditor → judge
  ↓
static_audit_bundle → 最终证据汇总
  ↓
HTML/Markdown report → 人工复核任务
```
