# 交接：rep_ 计算型 obs 补 recompute 契约（w1 → 数据窗口）

**背景**：QC 核验发现 rep_ 复现型案里一批 obs 是**计算型指标**（聚合量，非单元查找），现有验证器管不了 → 标为 `non-addr`。解法不是写万能验证器，而是**给这些 obs 补一个 `recompute` 契约块**，验证器就能确定性打分。完整设计见同目录 `REP_RECOMPUTE_CONTRACT.md`。

## w1 决策（2026-07-15）

- **cell_lookup 族：批准** ✅。deposited-cell(~150) 用 `metric_type: cell_lookup`（验 claim 值 == code_output 格子，确定性输出 `rel_tol=1e-6`、随机量给 `ci_interval`），不重跑管线。
- **护栏（硬）**：**discriminator（决定 verdict 的量）必须走真 recompute，绝不许 cell_lookup**。判据：被 `inconsistent` claim 引用、或 correct↔naive 的区分点 = discriminator。cell_lookup 只给非 discriminator 明细 obs。
- **不要求全 180 补齐才进 B1-B5**：门槛是 **claim 引用的 obs 可验**。优先级 ① 全 discriminator（recompute）→ ② 其余 claim-referenced → ③ 剩余明细（cell_lookup，机械批，不阻塞）。
- **现在就并行**：你继续补真 recompute 那 20-30 个（关键路径，已 greenlight）；cell_lookup 大头等 w1 把 verifier + QC dispatch 加好再机械批量补。

## 你要做的（一件事）

给下列 obs 增补 `recompute` 块（不动 `value`/`source_artifact`/`source_span`），四要素：`metric_type` · `inputs` · `method` · `tolerance`。

**先做两族（覆盖最多、最关键）：**
- `ci_bounded_stat`（统计量 + bootstrap CI）——**最关键**，CI 数据你们已写进 CSV，直接引用即可。
- `count`（整数计数）——`tolerance: exact`。

## 优先清单（QC 标为 non-addr / CI 型的 obs）

| 案 | obs（示例） | metric_type | 备注 |
|---|---|---|---|
| rep_pbc_surv | xgb_C_mean（+ boot_lo/hi 已在 CSV） | `ci_bounded_stat` | CI 现成，引用 lo/hi obs |
| rep_coexpr | n_sig_donor_padj05, mechanism_fdr_sig … (6) | `count` | 多为 padj<阈值 的计数 |
| rep_winnerscurse | n_drivers …(2) | `count` | 跨肿瘤复现 + 富集后计数 |
| rep_rtkfeedback | 2 个聚合 obs | `count`/`fraction` | 按实际归族 |

（其余 rep_ 案的计算型 obs 同法补；每族参考算法 w1 只写一次。）

## 填法样例（直接抄改）

CI 型（pbc_surv）：
```jsonc
"summary_metrics.csv#xgb_C_mean": {
  "value": 0.8452,
  "source_artifact": "artifacts/summary_metrics.csv",
  "source_span": "row model=xgb, column C_mean",
  "recompute": {
    "metric_type": "ci_bounded_stat",
    "inputs": ["artifacts/pbc.csv"],
    "method": {"reference_fn": "c_index", "code_entry": "pbc_surv_tcav.py::c_index_xgb"},
    "tolerance": {"kind": "ci_interval",
                  "lo_obs": "summary_metrics.csv#xgb_C_boot_lo",
                  "hi_obs": "summary_metrics.csv#xgb_C_boot_hi"}
  }
}
```

计数型（coexpr）：
```jsonc
"de_analysis_correct.csv#n_sig_donor_padj05": {
  "value": 0,
  "source_artifact": "artifacts/de_analysis_correct.csv",
  "source_span": "per-donor pseudobulk DE, padj<0.05 的基因数",
  "recompute": {
    "metric_type": "count",
    "inputs": ["artifacts/de_analysis_correct.csv"],
    "method": {"reference_fn": "count_where", "args": {"column": "padj", "op": "<", "thresh": 0.05}},
    "tolerance": {"kind": "exact"}
  }
}
```

## 硬要求（别漏）

1. **discriminator 对照**：每案 correct 版所有 recompute obs 落容差内；naive 版**恰在声明的那个指标**上落容差外（不是随便哪个数不同）。
2. **CI 型绝不用 exact**——统计量要 `ci_interval`，否则把 bootstrap 正常波动误判成造假，废掉 FP 案区分度。
3. `inputs` 指向 source_data 文件（相对路径），不要写散文。

## ★ 权威 REFERENCE_REGISTRY（照此填 `method.reference_fn` + `args`，别自造名/schema）

| reference_fn | args | 返回 | 用于 |
|---|---|---|---|
| `count_where` | `{column, op, thresh}` | 满足条件的行数 | count |
| `fraction_where`（别名 `frac_where`） | `{column, op, thresh}` | 比例 | fraction |
| `mean` | `{column}` | 列均值 | continuous_stat |
| `pearson` | `{x_column, y_column, y_in_second?}` | r | continuous_stat |
| `count_in_top_n` | `{rank_col, top_n, gene_col, gene_strip, gene_in:[...]}` | top-N 命中集合数（`gene_strip` 按分隔符**截断取前段**） | count |
| `rule_classify` | `{rule, key_col, key, ...rule 参数}` | 分类标签 | categorical_call |
| `top_n_per_group` | `{group_col, score_col, n, target:{...}, pos, neg}` | pos/neg 标签 | categorical_call |
| `cell_lookup` | `{line, column}` 或 `{row:{...}, column}` | 单元值 | cell_lookup |

**已注册的 `rule_classify` 具名规则**（新规则须 w1 先加进 `RULE_IMPLS` 再用；未注册 → QC 标 `REGISTRY-GAP`）：
- `mediator_call_correct` : `{key_col, key, n_deg_col, mtdna_col, depl_thr, n_deg_thr}`
- `mediator_call_naive` : `{key_col, key, n_deg_col, n_deg_thr}`

`op` ∈ `< <= > >= == !=`。要用表里没有的函数/规则 → **先找 w1 加**，别自造（否则 QC 报 `REGISTRY-GAP`，obs 视为未验证）。

## 之后（w1 做，不用你管）

w1 建 `REFERENCE_REGISTRY`（3–5 个族函数：count_where / c_index / pearson …）+ 通用验证器 + 单测，接进 `scripts/qc_veritasbench.py`，rep_ 家族即可进 B1–B5。
