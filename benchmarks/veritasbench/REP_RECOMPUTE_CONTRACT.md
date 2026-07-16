# VeritasBench — rep_ 复现型案 recompute 契约（草案 v0.1）

> **目的**：让复现型（reproduction / honest-FP）案的**计算型 obs**（聚合指标，非单元查找）可被一个**通用小验证器**确定性打分，无需为每案写 bespoke 抽取器。
> **原则**（verifier-not-path）：验证接口在造数据时冻结成契约；验证器只**执行契约**，不逆向猜测散文 span。
> **同源教训**：ncb_ 案靠"显式 A1 range 契约"把抽取从歧义变确定；rep_ 案靠本契约把"重算"从重活变通用执行器。

---

## 1. 问题：计算型 obs 读格子读不出来

| 案 | obs 例 | 值 | 为什么读格子不够 |
|---|---|---|---|
| rep_coexpr | `n_sig_donor_padj05` | 0 | 要跑差异表达再数 padj<0.05 的基因 |
| rep_winnerscurse | `n_drivers` | 3 | 要跨肿瘤复现性 + 富集判定后数行 |
| rep_pbc_surv | `xgb_C_mean` | 0.845 | C-index 有 bootstrap 波动，**精确相等会误判** |
| rep_methclock | `pearson_r` | 0.963 | 时钟预测年龄的相关系数 |

这些值确实**产生在 case 自带的 `code_output` CSV 里**，但要判"复现是否成立 / 是否 FP 陷阱"，得知道**这个数该怎么来、容差多少、谁是对照**——这三样就是契约。

---

## 2. 契约：每个计算型 obs 增补字段

在 observation 上增补一个 `recompute` 块（不破坏现有 `value`/`source_artifact`/`source_span`）：

```jsonc
"summary_metrics.csv#xgb_C_mean": {
  "value": 0.8452,
  "source_artifact": "artifacts/summary_metrics.csv",
  "source_span": "row model=xgb, column C_mean",
  "recompute": {
    "metric_type": "ci_bounded_stat",          // 指标族（见 §3）
    "inputs": ["artifacts/pbc.csv"],     // 从哪算（指向 source_data，非散文）
    "method": {                                 // 怎么算：二选一
      "code_entry": "pbc_surv_tcav.py::c_index_xgb",   // A. case 自带代码入口
      "reference_fn": null                              // B. 具名参考实现（§5 注册表）
    },
    "tolerance": {
      "kind": "ci_interval",                    // 判定容差（见 §4）
      "lo_obs": "summary_metrics.csv#xgb_C_boot_lo",   // CI 下界（同案另一 obs）
      "hi_obs": "summary_metrics.csv#xgb_C_boot_hi",   // CI 上界
      "bootstrap": {"n": 1000, "seed": 0}       // 若需现场重算 CI
    }
  }
}
```

**契约必填四要素**：`metric_type`（归族）· `inputs`（算什么）· `method`（怎么算：代码入口 or 参考实现）· `tolerance`（容差 + CI 来源）。

---

## 3. 指标族（从真实 rep_ 案归纳，同族共用参考算法）

| metric_type | 例 | 默认容差 |
|---|---|---|
| `count` | n_sig_donor_padj05=0, n_drivers=3, n_deg=685 | `exact`（整数） |
| `continuous_stat` | pearson_r=0.963, MAE_years=4.02, fc_mean=22.162 | `rel_tol=1e-3` |
| `fraction` | frac_transcriptome_p_lt_1e4=0.25 | `rel_tol=1e-3` |
| `ci_bounded_stat` | C_index=0.845 (±bootstrap) | **`ci_interval`** |
| `categorical_call` | KO_13_call="gene_specific"/"shared" | `exact`(字符串) |
| `cell_lookup` | deposited-cell（复现输出里的某个明细格子，~150） | `rel_tol=1e-6`（随机量给 `ci_interval`） |

新指标出现时**先归族再补案**（同族只写一次参考算法）。

### ★ 护栏：discriminator 必须 recompute，不许 cell_lookup（w1 2026-07-15 拍板）

`cell_lookup` 只验"claim 值 == code_output 格子"（转录一致），**不重跑管线、不验科学**。因此：

> **任何决定 verdict 的 obs（discriminator = correct/naive 判定所依赖的那个量）必须用真 recompute 族（`count`/`continuous_stat`/`fraction`/`ci_bounded_stat`）从 `inputs`(source_data) 重算；绝不能用 `cell_lookup`。**

判据：obs 被某 `inconsistent` claim 的 source/target 引用、或是 correct↔naive 的区分点 → 它是 discriminator → 强制 recompute。`cell_lookup` 仅用于**非 discriminator 明细 obs**（per-sample 输出、单个系数）。理由：cell_lookup 抓不到"手改 code_output 制造的假区分"。

### 补契约优先级（B1-B5 门槛打的是 claim，不是每个 obs）

1. 全部 **discriminator**（→ recompute）
2. 其余 **claim-referenced** obs（→ recompute 或 cell_lookup 按性质）
3. 剩余明细 obs（→ cell_lookup，机械批量，**不阻塞 B1-B5**）

---

## 4. 容差（tolerance.kind）—— CI-aware 是重点

| kind | 判定 | 用于 |
|---|---|---|
| `exact` | 重算值 == obs.value | 计数 / 分类判定 |
| `rel_tol` | `isclose(recomputed, value, rel_tol)` | 确定性连续量 |
| `ci_interval` | **obs.value ∈ [lo, hi]**（lo/hi 取自同案 CI obs，或 bootstrap 现算） | 统计量（C-index、生存分析…） |

**为什么 CI-aware 是核心区分度**：rep_ 案专门测"系统会不会把 CV/bootstrap 的**正常随机波动**误判成造假"。用 `exact` 判统计量 = 必然假阳性；必须 `ci_interval`。pbc_surv 已把 `C_boot_lo/hi` 写进 CSV → **容差数据现成，验证器直接用**。

---

## 5. method 二选一 —— 决定验证器有多重

| 路 | method 写法 | 验证器做什么 | 代价 |
|---|---|---|---|
| **B. 参考实现（推荐先做）** | `reference_fn: "count_padj_lt(0.05)"` | 调注册表里的具名函数，对 `inputs` 现算 | 每族写一份，可控 |
| **A. 重跑代码** | `code_entry: "solve.py::main"` | runtime 沙箱执行 code artifact，比对输出 | 需 Docker 隔离，重 |

**注册表**（`reference_fn`）= `{名字 → 纯函数(inputs)->值}`，如 `count_significant`、`c_index`、`pearson`。多数 rep_ 案落 3–5 个族即可覆盖，避免逐案执行代码。

---

## 6. discriminator 对照（必填，防"碰巧正确"）

每案须同时交 **correct 版**（→ verdict=consistent）和 **naive 版**（→ 在**具体某指标**上 inconsistent），验证器断言：
- correct 版所有 recompute obs 落容差内；
- naive 版**恰在声明的那个 discriminator 指标**上落容差外（不是随便哪个数不同）。

这样"区分度"是被验证过的，不是标注者口述。

---

## 7. 通用验证器骨架（"小执行器"，非逐案 bespoke）

```python
def recompute_verify(obs_key, obs, case_dir, obs_index):
    rc = obs.get("recompute")
    if not rc:
        return "nonaddr"                      # 无契约 → 人工复核
    if rc["metric_type"] == "cell_lookup":    # 明细格子：读复现输出对上即可，不重算
        got = cell_lookup(case_dir/rc["inputs"][0], rc["method"]["args"])  # row/column 或 json_path
        return "ok" if isclose(got, obs["value"], rel_tol=1e-6) else f"fail:{got}!={obs['value']}"
    recomputed = _run_method(rc["method"], [case_dir/i for i in rc["inputs"]])
    tol = rc["tolerance"]
    if tol["kind"] == "exact":
        return "ok" if recomputed == obs["value"] else f"fail:{recomputed}!={obs['value']}"
    if tol["kind"] == "rel_tol":
        return "ok" if isclose(recomputed, obs["value"], rel_tol=tol.get("rel_tol",1e-3)) else "fail:..."
    if tol["kind"] == "ci_interval":
        lo = obs_index[tol["lo_obs"]]["value"]; hi = obs_index[tol["hi_obs"]]["value"]
        return "ok" if lo <= obs["value"] <= hi else f"fail:{obs['value']} not in [{lo},{hi}]"

def _run_method(method, inputs):
    if method.get("reference_fn"):
        return REFERENCE_REGISTRY[method["reference_fn"]](*inputs)   # 路 B：纯函数
    return run_in_sandbox(method["code_entry"], inputs)              # 路 A：执行代码
```

**这就是"设计对了之后"的验证器**：一个 dispatch，几十行，覆盖所有 rep_ 案；重活（沙箱执行）只在 `reference_fn` 覆盖不了时才走。

---

## 8. 落地顺序（建议）

1. 数据窗口按 §2–§4 给现有 rep_ 计算型 obs 补 `recompute` 块（先 `ci_bounded_stat` 和 `count` 两族，覆盖最多）。
2. w1 建 `REFERENCE_REGISTRY`（3–5 个族函数）+ §7 验证器 + 单测。
3. QC 工具（`scripts/qc_veritasbench.py`）接入：`non-addr` obs 若带 `recompute` 块则转 recompute 校验，不再只标注。
4. 全绿后，rep_ 家族进 B1–B5 评测（复现型失败模式上表）。
