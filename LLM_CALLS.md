# Veritas LLM 调用类型

本文件列出了 Veritas 自研的静态审计 LLM 调用；每一行用一句话说明了输入、输出以及所解决的问题。

| 调用类型 | 一句话说明 |
|---|---|
| 源数据列语义分类 (`classify_columns_with_llm`) | 输入为最多 20 个源数据列名及其示例值，输出为 `{column_name: metadata\|measurement\|index}` 格式的 JSON 映射，旨在下游数值过滤前区分标识符/分组与实际测量值。 |
| 图表图例面板分类 (`classify_all_figures_batch` / `classify_figure`) | 输入为论文图表图例，输出为针对每个图表或面板的描述及类别（`wet_lab\|bioinformatics\|mixed\|other`），旨在确定哪些视觉取证路径适用于特定的图表面板。 |
| 图像与论文标签映射 (`build_image_to_paper_label_mapping`) | 输入为 MinerU `full.md` 中的图像引用及相关的图表图例上下文，输出为 `{image_filename: paper_figure_label}`，旨在将提取出的图像文件与论文中的图表 ID 建立关联。 |
| 发现项文本丰富化 (`enrich_single_finding_async`) | 输入为包含证据 ID、元数据和示例值的结构化发现项，输出包括 `review_question`（审查问题）、`benign_explanations`（良性解释）、`relation_text`（关联文本）和 `evidence_cited`（引用证据），旨在将结构化证据转化为事实性报告文本，同时避免得出关于不当行为的结论。 |
| 材料规划智能体 (`run_agent_material_plan`) | 输入为案例的材料清单上下文包，输出为选定的可选路径及缺失/不支持材料的说明，旨在确定哪些可用材料应纳入审计工作流。 |
| 初始审计规划智能体 (`run_agent_plan`) | 输入为材料清单及论文/源数据位置信息，输出为包含所选工具及依据的结构化审计计划，旨在将可用输入转化为可执行的静态审计计划。 |
| 调查规划智能体 (`run_agent_investigation_plan`) |输入为精简的审查上下文及既往调查记录，输出为针对当前轮次的允许工具操作列表及其理由；任务在于选择下一步的针对性调查步骤，且不得绕过工具注册表（Tool Registry）。 |
| 源数据工作表判定代理 (`get_sheet_verdict`) | 输入为包含表格结构、确定性发现、简报及可选相关主张的工作表上下文 JSON；输出为工作表层级的判定结果及针对各项发现的判断；任务在于判定源数据中的确定性信号究竟属于真实问题、良性伪影（benign artifacts）还是不确定情况。 |
| 材料审查代理 (`run_agent_review`) | 输入为案例的精简审查上下文；输出为候选主张、主张与源数据的关联、发现审查结果、人工审查任务、报告备注及局限性说明；任务在于将积累的证据转化为可供人工审查的工作项。 |
| 主张提取角色代理 (`run_agent_role: claim_extractor`) | 输入为限定范围的论文文本及证据台账上下文；输出为可核查的主张（包含主张 ID、位置、类型、证据引用、图表引用及预期源数据）；任务在于识别出能够对照现有材料（artifacts）进行审计的论文主张。 |
| 源数据审计角色代理 (`run_agent_role: source_data_auditor`) | 输入为源数据概况/发现结果及提取出的主张；输出为主张与源数据的映射关系、发现审查结果、良性解释及人工审查任务；任务在于将电子表格中的确定性证据与论文主张及审查问题关联起来。 |
| 裁决角色代理 (`run_agent_role: judge`) | 输入为各角色先前的精简输出及高优先级证据摘要；输出为技术风险摘要、风险建议、报告备注及局限性说明；任务在于综合证据以撰写报告，同时不推翻确定性材料的结论，也不做出关于不当行为的最终裁决。 |
| 占位符静态审计角色代理 (`digit_pattern`, `math_consistency`, `domain_sanity`, `defense`) | 输入为 `ROLE_DEFINITIONS` 中列出的特定角色材料；输出为特定角色的 JSON 材料；任务在于预留未来的专家审查空间；这些角色在当前流程中并非实际的 v1 LLM 调用。 |