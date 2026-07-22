# VeritasBench Anomaly Families & LOAFO Protocol (frozen 2026-07-22)

> DAG 主作者科学复核项：*"anomaly family 定义和 multi-label/LOAFO 规则在查看新结果前冻结"*。本文在查看任何 E3 LOAFO 新结果前冻结定义，避免 post-hoc 调整。

## 1. In-family anomaly types（B3 node-forensics characterization family）

B3 的确定性 detector 在 source-data 上发火的结构信号（论文 §3.6 / appendix app:forensics）：

| family | 检测谓词 | 容差 |
|---|---|---|
| duplicate_columns / duplicate_rows | 跨列/行 exact-match hash | 0 |
| fixed_offset | $c_i = c_j + k$（常数 $k$） | $\pm 10^{-9}$ |
| paired_ratio / paired_difference | $c_i/c_j = k$ 或 $c_i - c_j = k$ | $\pm 10^{-9}$ |
| cross_sheet_reuse | 跨 sheet cell-range hash 一致 | 0 |
| numeric_consistency (GRIM/GRIMMER) | 报告统计量在 n/scale 下数学可能 | 整数/小数位 |

**Locus-identity guard**：同 sheet+同 range 不发火（self-comparison degeneracy）；elementwise-identical 跨 *不同* locus 仍 flag 为真 copy。

## 2. Off-family anomaly types（construction-disjoint holdout v5，B3 结构上无法 characterize）

holdout 15 cases / 9 types（`holdout_detector_disjoint_v5_results.json`，每 case 有外部 correction/PubPeer 背书，validator 15/15 PASS）：

`label_swap` · `misaligned_records` · `mislabeled_panel` · `provenance_mismatch` · `assignment_inconsistency` · `pseudoreplication` · `figure_vs_sourcedata_count_mismatch` · `undisclosed_imputation` · `value_substitution`

这些在 file 内**无 cross-locus 比较目标**，B3 adapter-fed src/tgt series 上 single-cell 不发火（len<2 guard）。v5 结果：B3 **0/25 clean claim 误报**（单侧 exact-binomial 95% 上界 11.3%），off-family positive recall = 0（scope boundary，非能力失败）。

## 3. Multi-label 规则

- 一个 case 的 inconsistency 可同时属于多个 family（如 duplicated_rows + fixed_offset 共现）→ primary_failure_mode 单标记主因，secondary_failure_modes 列其余。
- multi-label 计数：按 family 计 inconsistent claim 数，sum 可超过 inconsistent claim 总数（一案多 family）。
- hard-negative (false_positive_trap) 案：unit_conversion / shared_control / small_integer_coincidence——**不计入任何 in-family anomaly 计数**，它们是 clean。

## 4. LOAFO（leave-one-anomaly-family-out）协议 — E3

**冻结规则（查看结果前定，不得事后改）**：

1. 每次完整排除**一个 in-family type**（§1 的 5 类之一，或 §2 off-family 9 类之一，分两轮）。
2. 构造 detector/threshold 时**不得接触**该 held-out family 的任何 case（train/calibration split 上剔除该 family 的 inconsistent 案；clean 案保留）。
3. **不重新针对 held-out family 调阈值**——flag_threshold / abstain_threshold 固定为已冻结的 B5 decision（`b1b5_maintable.json` 的 `decision`）。
4. detector 不支持该 family 时，记为 **coverage miss**（该 family claim 的 verdict = insufficient/abstain），**不得悄悄算作正确 negative**。
5. 报告每轮：held-out-family recall（tp / 该 family 全部 inconsistent claim）、相同冻结 clean set 上的 FAR、coverage、涉及 paper/claim 数。
6. off-family 9 类因 B3 结构性不覆盖（§2），其 LOAFO 等价于已冻结的 v5 holdout 结果——直接引用 `0/25 clean / 0 recall`，不重复跑。

**预期诚实结论**（结果前写，事后不改）：in-family LOAFO 的 recall 会随 held-out family 下降（说明 detector 部分依赖该 family 的特征）；FAR 应保持低（clean claim 不依赖任何 family 的 positive，故 FAR-robustness 不受 LOAFO 影响）。

## 5. 与已有结果的关系

- v5 holdout = §2 off-family 的 LOAFO 等价（已跑，0/25/0）。
- §1 in-family 的 LOAFO = **E3 新实验**（需 detector 在剔除单 family 的 split 上重跑，待 E3 负责人）。
- 本冻结规则使 E3 的 in-family LOAFO 可在查看结果前无歧义执行。
