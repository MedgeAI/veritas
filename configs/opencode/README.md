# opencode 上下文维护说明

本目录维护 Veritas 给 opencode 的常驻上下文。目标是让论文审查先验可维护、可迁移，而不是散落在多个 prompt、skill 和第三方仓库里。

## 加载链路

`opencode.json` 当前加载：

1. `AGENTS.md`
2. `.opencode/skills/research-integrity-auditor/SKILL.md`
3. `configs/opencode/veritas-agent.md`
4. `configs/opencode/biomed-research-audit-methodology.md`
5. `configs/methodology/general.md`
6. `configs/methodology/source-data.md`
7. `configs/methodology/biomed-wetlab.md`
8. `configs/methodology/bioinfo.md`
9. `configs/methodology/visual-forensics.md`

`.opencode/skills/research-integrity-auditor/SKILL.md` 是常驻上下文。这样临时启动的 opencode 不需要靠模型自行发现 skill，也能知道 `third_party/research-integrity-auditor` 工具箱和 artifact 合约。

注意：常驻加载 skill 只解决“opencode 知道工具箱”的问题，不负责产品流程可靠性。`audit-paper` 的确定性工具执行由 `engine/tools/registry.py` 和 Python orchestrator 控制。

`third_party/research-integrity-auditor/` 不是 Veritas 的长期协议。它是 vendor/toolbox，用来提供 MinerU、evidence ledger、numeric forensics、evidence rendering 等第一阶段工具能力。

## 分层职责

| 层级 | 文件/目录 | 职责 | 不应包含 |
| --- | --- | --- | --- |
| 项目工程约束 | `AGENTS.md` | 仓库开发规则、产品边界、runtime/engine/report 方向 | 具体论文 case 细节 |
| opencode 运行路由 | `configs/opencode/veritas-agent.md` | opencode 在 Veritas 中的工作路线、上下文分层、边界 | 大段领域方法论、工具命令细节 |
| 方法论入口索引 | `configs/opencode/biomed-research-audit-methodology.md` | opencode 常驻方法论索引和核心原则 | 大段领域规则、单 case 专属发现 |
| 领域审查先验 | `configs/methodology/` | 通用科研诚信、Source Data、干实验/湿实验、生信、视觉取证方法论 | 具体命令、产品 PRD、单 case 专属发现 |
| skill 适配层 | `.opencode/skills/research-integrity-auditor/SKILL.md` | 触发条件、输入变量、工具命令、artifact 合约 | 领域方法论本体、产品 PRD、第三方源码说明 |
| Tool Registry | `engine/tools/registry.py` | 产品运行时允许执行的确定性工具、tool_id、参数默认值和输出契约 | Agent 自由决策、领域解释 |
| 第三方工具箱 | `third_party/research-integrity-auditor/` | 可调用脚本、上游参考方法、vendor 实现 | Veritas 产品决策、长期协议 |
| 第三方图像取证参考 | `third_party/elis/` | ELIS-style 图像取证工具、panel/copy-move/TruFor/CBIR 思路 | Veritas 主服务、SaaS 状态存储、产品结论 |
| 本地参考文档 | `docs/` | 开发期 PRD、决策记录、素材和老板沟通资料 | 初始提交内容、常驻上下文依赖 |

## Source of truth 规则

- 产品和工程边界改 `README.md` 或 `AGENTS.md`。
- opencode 如何工作改 `configs/opencode/veritas-agent.md`。
- 生物医药/生信审查知识改 `configs/methodology/`。
- opencode 方法论加载入口改 `configs/opencode/biomed-research-audit-methodology.md`。
- 产品运行时工具集合、tool_id 和参数默认值改 `engine/tools/registry.py`。
- opencode 可见的工具说明、输入输出路径、artifact 合约改 `.opencode/skills/research-integrity-auditor/SKILL.md`。
- 不要直接改 `third_party/research-integrity-auditor/` 来表达 Veritas 产品规则；需要吸收能力时，先通过 adapter、script 或 skill 包起来。
- 不要直接把 `third_party/elis/` 的 FastAPI/Celery/MongoDB/Redis/Web UI 主服务接入 Veritas；需要吸收能力时，先封装成 Tool Registry adapter，并让输出回链到 canonical `figure_evidence`。
- `docs/` 当前是本地参考材料，不进入初始提交；不要把提交版功能依赖建立在 `docs/` 必然存在的假设上。

## 去重原则

- 同一条领域规则只能在 `configs/methodology/` 的一个文件中维护一次。
- skill 里可以引用领域规则，但不要复制展开。
- 单一 demo fixture 不得成为默认审查逻辑。
- 原文材料如本地 `docs/assets/致敬.md` 是方法来源，不是常驻 instructions，也不进入初始提交。

## 当前本地入口

推荐入口：

```bash
python3 cli/main.py audit-paper <paper_dir> --case-id <case_id> --agent-mode review
```

`--agent-mode review` 表示：

- `agent_material_plan`：opencode 基于 `material_inventory.json` 选择可执行 optional evidence lane，Source Data 不再依赖固定目录名硬编码。
- 本地确定性脚本：执行 MinerU、evidence ledger、numeric forensics、Source Data profile/findings、图片重复检查。
- `agent_investigation_plan`：opencode 基于已生成 artifacts 选择最多 3 轮后续确定性 investigation tools；Python 只执行 Tool Registry 中 `agent_selectable=True` 的 deterministic tool。
- `agent_review`：opencode 读取结构化产物，生成 claim/finding 复核 JSON 和人工复核任务。

`--agent-mode full` 会额外执行 `agent_plan`，用于探索确定性脚本参数和工具选择；它不是稳定 demo 的默认入口。

只跑确定性链路时使用 `--agent-mode off`。Agent 失败不阻断确定性报告，但会进入 `audit_run_manifest.json` 和 `final_audit_report.md` 的 warning/limitation。
