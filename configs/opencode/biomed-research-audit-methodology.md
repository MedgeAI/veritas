# 生物医药 / 生物信息论文技术复核方法论索引

本文件是 opencode 常驻 instructions 的入口索引。Veritas 产品级方法论已经拆到 `configs/methodology/`，不要继续把大段领域规则复制到本文件。

opencode 在论文审查时必须同时遵循：

- `configs/methodology/general.md`
- `configs/methodology/source-data.md`
- `configs/methodology/biomed-wetlab.md`
- `configs/methodology/bioinfo.md`
- `configs/methodology/visual-forensics.md`

核心原则：

- Veritas 只做投稿前技术事实核查，不做学术价值判断，不做最终科研诚信判定。
- PDF 是发表呈现层，Source Data、代码、环境、结果文件才是高价值证据层。
- 先做材料盲审，再做 claim-to-evidence 映射，避免被论文叙事带偏。
- 能用确定性程序完成的统计、解析、复算、文件检查，不交给 LLM。
- LLM 只处理不确定任务：claim 抽取、语义映射、良性解释压力测试、报告措辞。
- 所有 finding 必须能回指到文件、页码、图号、sheet、列、行、单元格、代码位置、命令或输出产物。

单一 demo fixture 不得成为常驻默认审查逻辑。
