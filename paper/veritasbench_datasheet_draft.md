# VeritasBench — Datasheet for Datasets (draft skeleton)

> 格式：Gebru et al. 2021 "Datasheets for Datasets"。**我(总指挥)按已知项填满;`[吴关渡填]` = 只有你能提供的数据特定信息。** 用途：D&B track 要求的 dataset documentation → 放论文 Appendix 或 repo。

## 1. Motivation
- **为何创建**：AI 审计科学论文的能力缺少系统评测;现有工作只测复现/图表QA/文本claim支持,没有"claim-provenance consistency"(证据链跨表征一致性)的 relation-level benchmark。
- **谁创建/资助**：`[吴关渡填]` 作者+单位+资助(camera-ready 填,投稿匿名)。

## 2. Composition
- **实例是什么**：一个 case = 一篇真实论文;每 case 含 artifacts(源数据/代码/表/图/PDF)+ observations(cell级抽取的事实)+ claims(typed relation L1–L4 + verdict)。
- **规模**：68 case(manifest v1.0);217 claim;verdict 分布：140 consistent / 40 inconsistent / 37 insufficient。relation type：216 L1 / 1 L3。四桶：verifier_conflict 19 / false_positive_trap 19 / mixed_boundary 18 / grounding 12。
- **发表年份**：2019–2026（众数 2020–2025；median 2022）。
- **期刊/来源分布**：Nature Cell Biology 16 / Nature Communications 9 / Nature 7 / eLife 3 / Nature Cancer 3 / OSF/bioRxiv/Zenodo 11 / 其他 19（共 25+ 来源，见逐 case DOI 附录）。
- **领域分布**（基于论文标题启发式分类）：Reproducibility/methods 15 / Neuroscience 12 / Oncology 9 / Cell biology/molecular biology 7 / Immunology 6 / RNA biology 5 / Microbiology/immunology 3 / 其余7类共11 case。
- **是否覆盖全体**:否;真实公开诚信案例的便利样本(见 §Limitations 采样偏差)。
- **label**:claim 的 verdict(consistent/inconsistent/insufficient)+ evidence_span;GT 双验证(结构 validator + 逐值 cross-check,0 mismatch)。
- **inter-annotator**:抽样双标 16案/50claim,**Cohen's κ = 0.924**（pre-codebook κ=0.755；codebook 发布后 κ=0.924；有效一致 49/50）。
- **敏感性**:命名真实论文/作者,但只用**已公开**的诚信状态(撤稿/更正/PubPeer);不引入私有数据。

## 3. Collection Process
- **来源**：两类来源混合：
  1. **诚信问题案（inconsistent/verifier_conflict bucket）**：PubPeer 评论 → 作者更正通知（Author/Publisher Correction）→ 撤稿通知（Retraction Notice）。触发条件：有可锚定的 source data xlsx/csv + DOI 公开 + 已公开诚信状态。
  2. **诚实可复现案（consistent/grounding bucket）**：CODECHECK 审核通过论文 + 其他有开放代码/数据且结果可独立复现的论文。
- **逐 case DOI 清单**（68 案，按 case_id 字母序，`*` 标 inconsistent 主案）：

| case_id | DOI | 主要异常/类型 |
|---|---|---|
| elife_neurexin_fig1b* | 10.7554/eLife.78649 | provenance_mismatch |
| fp_raoyi | 10.1038/s42003-024-07449-y | false_positive_trap |
| lin_grounding | 10.1038/s41551-022-00846-w | grounding |
| natcomm_florido_tac2* | 10.1038/s41467-021-22911-9 | label_swap |
| natcomm_nguyen_mirna* | 10.1038/s41467-020-15674-2 | provenance_mismatch |
| natcomm_petruk_tlr* | 10.1038/s41467-023-41702-y | figure_vs_sourcedata_count |
| ncb_akg | 10.1038/s41589-025-02013-z | — |
| ncb_aldometanib | 10.1038/s41422-025-01195-4 | — |
| ncb_alkbh7 | 10.1038/s41556-021-00709-7 | — |
| ncb_baseeditor | 10.1038/s41556-020-0518-8 | — |
| ncb_brd9* | 10.1038/s41467-023-37116-5 | — |
| ncb_cav2* | 10.1038/s41467-025-66914-2 | label_swap |
| ncb_clonalfish* | 10.1038/ncomms15361 | misaligned_records |
| ncb_eet | 10.1038/s41556-021-00762-2 | — |
| ncb_ercc | 10.1038/s41556-025-01760-4 | — |
| ncb_fbp1 | 10.1038/s41556-020-0511-2 | — |
| ncb_glud1 | 10.1038/s41586-021-03661-6 | — |
| ncb_gpx4 | 10.1038/s43018-025-00937-y | — |
| ncb_h19 | 10.1038/s41556-020-00595-5 | — |
| ncb_h3v3 | 10.1038/s41556-021-00795-7 | — |
| ncb_hdac6 | 10.1038/s41586-024-08248-5 | — |
| ncb_lactate | 10.1038/s41556-025-01839-y | — |
| ncb_lgr4 | 10.1038/s43018-023-00715-8 | — |
| ncb_lphn3* | 10.1038/s41586-023-06913-9 | mislabeled_panel |
| ncb_mito | 10.1038/s41556-021-00724-8 | — |
| ncb_mowei | 10.1038/s41586-020-2127-x | — |
| ncb_nelfa | 10.1038/s41556-019-0453-8 | — |
| ncb_neurexin* | 10.7554/eLife.78649 | duplicated_row |
| ncb_nickelate* | 10.1038/s41586-024-07996-8 | assignment_inconsistency |
| ncb_pkcb | 10.1038/s41556-021-00818-3 | — |
| ncb_psen2 | 10.1038/s41467-022-29653-2 | — |
| ncb_rab22a | 10.1038/s41556-020-0522-z | — |
| ncb_radioligand* | 10.1038/s41586-024-07461-6 | assignment_inconsistency |
| ncb_rybp | 10.1038/s41556-020-0484-1 | — |
| ncb_sirt1 | 10.1038/s41556-020-00579-5 | — |
| ncb_spp1* | 10.1038/s41593-023-01257-z | pseudoreplication |
| ncb_sting | 10.1038/s41556-021-00659-0 | — |
| ncb_teneurin | 10.1038/s41467-022-29751-1 | — |
| ncb_wnt | 10.1038/s41556-020-0507-y | — |
| rep_a8rmu | 10.31222/osf.io/a8rmu | — |
| rep_actmeta | 10.1186/s12991-023-00462-1 | — |
| rep_brainmicrobiome | 10.1038/s41591-025-03957-4 | — |
| rep_catcolors | 10.31234/osf.io/gj76p | — |
| rep_coexpr | 10.1038/s41467-025-65060-z | — |
| rep_covtracing | 10.1016/S1473-3099(20)30457-6 | — |
| rep_detorakis | 10.5281/zenodo.1003214 | — |
| rep_iteval | 10.1002/sim.10186 | — |
| rep_lazar | 10.1098/rsos.191613 | — |
| rep_mb11 | 10.24072/pcjournal.414 | — |
| rep_mediator | 10.1038/s41594-026-01779-7 | — |
| rep_methclock | 10.1101/2024.10.29.620782 | — |
| rep_mqg86 | 10.31234/osf.io/mqg86 | — |
| rep_pbc_surv | 10.71240/lcyc.66O7260 | — |
| rep_photoreceptor | 10.1016/j.isci.2026.116661 | — |
| rep_piccolo | 10.1093/gigascience/giaa026 | — |
| rep_pone | 10.1371/journal.pone.0308768 | — |
| rep_rtkfeedback | 10.1038/s41589-024-01761-8 | — |
| rep_samplesize | 10.31234/osf.io/cz32t | — |
| rep_sarscov2 | 10.1038/s41598-021-85363-7 | — |
| rep_spatialniche | 10.1038/s41588-025-02080-x | — |
| rep_spatialtx | 10.1101/2025.08.12.669903 | — |
| rep_svaretro | 10.46471/gigabyte.70 | — |
| rep_triangulation | 10.1038/s41467-025-66046-7 | — |
| rep_velolineage | 10.1101/2024.03.21.586160 | — |
| rep_winnerscurse | 10.1038/s41586-024-07663-y | — |
| rep_wkzsn | 10.31219/osf.io/wkzsn | — |
| rep_zebrafish | 10.7554/eLife.54937 | — |
| usp15_grounding | 10.1038/s43018-023-00535-w | — |

- **如何采**:重复检测扫描器 → 8-agent 并行 adjudication(~12min) → 参数化 builder → 官方 validator gate。诚实可复现案经 Docker-R 跑代码产 results/*.csv。
- **判据独立于暴露信号**:GT 靠数据本身可计算关系 + 独立状态,不靠"某帖说是假的"。
- **收集时间窗**：2026-07-14 ~ 2026-07-18（git 首提交至最后提交）。论文发表年范围：2019–2026（论文本身发表时间，非收集时间）。

## 4. Preprocessing / Cleaning / Labeling
- observations 从原始 artifact 抽取,**禁止从 verdict 反推**。
- **去标识处理**：
  - *合成辅助线（synthetic helper columns）*：audit-task 类案例中注入的辅助样本列使用随机前缀/哈希替换了原始样本 ID，不含真实患者/动物标识符。
  - *真实层（ncb_/rep_/elife_/natcomm_ 案）*：artifacts 均为原始论文公开的 Source Data xlsx/csv，与期刊页面一致，不含 per-sample 个人信息（原始数据本身即为已发表公开数据，无需额外去标识）。`[吴关渡确认]` 如果有任何 case 含个人可识别信息（如姓名、患者 ID），请标注并评估是否需要脱敏处理。
  - *泄漏防控*：claim_atom 中的 cell_id/sample_id 已匿名化处理（以哈希或 cellN 替换），防止 verdict 泄漏到 claim 描述文本。
- 每 case 官方 validator（9 项：sha256/observation-hash/枚举/≥1 clean/…），0 mismatch。

## 5. Uses
- **已用于**:B1–B5 tool-layer 消融(L1,oracle-conditioned)。
- **可用于**:评测 AI 审计器的一致性/FAR 表现;L2–L4 作为 annotated GT 供未来 verifier 研究。
- **不应用于**:判定学术不端(只报事实,见 Ethics);L2/L4 的自动评测(尚无 verifier)。

## 6. Distribution
- **license 框架**（建议方案，待你拍板）：
  - *Benchmark metadata*（case.json / observations / claims / manifest / schema）：**CC BY 4.0**（最宽松，允许商用、衍生、再分发，要求署名）。
  - *Source data artifacts*（xlsx/csv 文件）：逐 case 分类如下——
    - **Nature/Springer Open Access 文章的 Source Data**（ncb_*/natcomm_* 大多数）：原文标注 CC BY 4.0；可随 benchmark 再分发，须标注原文 DOI + 期刊版权声明。
    - **eLife Source Data**（elife_neurexin_fig1b, ncb_neurexin, rep_zebrafish）：CC BY 4.0；同上。
    - **OSF/Zenodo 存档**（rep_a8rmu 等）：需逐案核 deposit license；多数为 CC BY 4.0 或 CC0，但须确认。`[吴关渡逐案确认]`
    - **论文 figure 截图 / PDF 内容**：**高风险**——Nature/Cell 的出版商版权，**不可再分发**；benchmark 中不含 PDF 正文截图，仅含 Source Data 文件，风险可控。
  - **风险标记**：若某 case 的 artifact 只能通过截图获取（无公开 Source Data），该 case 不放入公开 repo，仅保留 claim metadata。`[吴关渡填]` 目前有无此类 case？
  - **建议 benchmark 整体 license**：**CC BY 4.0**（metadata 层）+ 逐 artifact 声明（artifact 层）。
- **发布**：投稿匿名 repo → camera-ready 公开 + Zenodo DOI（GitHub Releases 同步 tag）。
- **不含**：真实论文 PDF（版权）、API key、内部工具。

## 7. Maintenance
- **维护人**：`[吴关渡填]` 姓名 + 联系邮箱（camera-ready 填，投稿匿名期留 anonymous）。建议同时挂一个 GitHub Issues 入口。
- **更新频率 / 版本策略**（建议方案）：语义化版本 v{major}.{minor}。每新增一批 case 打 minor tag（如 v1.1）；schema 破坏性变更打 major tag（如 v2.0）。当前版本：**v1.0**（68 案，2026-07-18 冻结）。
- **贡献渠道**：GitHub Issues / PR；新 case 须过官方 validator（9项 gate）+ 双验证（κ 抽样或逐 claim 核查）。
- **勘误**：发现 GT 错误经 issue 反馈，validator 回归后修订并版本递增（patch tag）。

---
## 待你(吴关渡)拍板/确认的空（缩减版）

已由我从 case.json + git log 填入：§2 规模/年份/期刊/领域分布、§3 DOI 清单+收集时间窗、§4 去标识说明（合成辅助线+真实层）、§6 license 框架建议、§7 版本策略建议。

**你仍需决定的 5 项**：

1. **§1 作者/资助**：camera-ready 填真实姓名+单位+基金号（投稿期保持匿名）。
2. **§4 真实层去标识确认**：是否有任何 case artifact 含患者/动物可识别信息？如有请标注。
3. **§6 逐 case license 拍板**：
   - OSF/Zenodo 存档案（rep_a8rmu/rep_catcolors/rep_mqg86/rep_samplesize/rep_wkzsn/rep_detorakis）：逐案到 deposit 页面核实 license（CC0 还是 CC BY？）。
   - 确认整体 benchmark license = **CC BY 4.0**（或你有其他选择）。
   - 若有任何 artifact 只能截图获取（无公开 Source Data），告知我—该 case 移出公开 repo。
4. **§7 维护人姓名/联系邮箱**：camera-ready 填。
5. **§2 Composition `[吴关渡确认]`**：domain 分类是启发式的，如有明显分类错误请告知修正。
