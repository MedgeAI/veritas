# 通用科研技术复核方法论

本文件是 Veritas 静态审查的通用方法论层，不绑定 opencode，也不针对任何单一论文 case。

## 产品边界

- 只做投稿前技术事实核查，不做学术价值判断。
- 不做最终科研诚信判定。
- 不从单一信号推出“造假”或“学术不端成立”。
- 报告技术事实、异常线索、证据强弱、材料缺口和人工复核入口。

## Evidence First

所有正式 finding 必须回指到结构化证据：

- PDF page、figure、table、caption、Markdown line、content block。
- Source Data workbook、sheet、row、column、cell、formula。
- image path、crop/panel、hash/similarity candidate。
- command、stdout/stderr、exit code、result file、file hash。

Agent 输出只能解释、映射、压力测试和综合，不得替代 primary evidence。

## 审查顺序

1. 材料清单：先确认论文、Source Data、代码、环境、结果文件、复现声明是否存在。
2. 盲审材料：先看 Source Data、图片、表格、代码和结果文件的内部结构。
3. 抽取 claim：数字型、方法声明型、图表溯源型、代码执行型、材料完整性型。
4. claim-to-evidence：把 claim 映射到可复核材料，不足处标记材料缺口。
5. 良性解释压力测试：先排除工具伪影、表格结构、设计矩阵、公式派生、合法复用。
6. 综合报告：只给技术复核结论和人工复核任务。

## 风险语言

- `info`: 材料事实或结构信息。
- `low`: 弱信号或高度可解释信号。
- `medium`: 需要人工复核的中等强度候选。
- `high`: 多条独立证据链指向同一 claim 或 artifact。
- `critical`: 仅用于非常强的技术冲突组合；仍不能写成最终诚信裁决。

推荐措辞：

- “技术事实候选”
- “需要人工复核”
- “当前证据不足”
- “与论文 claim 存在待核对差异”
- “材料缺口限制了核查深度”

