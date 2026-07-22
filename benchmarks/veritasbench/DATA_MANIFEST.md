# VeritasBench 数据清单与统一映射

> 2026-07-22 整理。本文是 VeritasBench 全部数据的**单一清单**：本地 canonical、服务器上游、匿名仓库发布副本、Overleaf 论文。D0 冻结 commit = `6c4ad0a`（v5 建立于 `ac576cd`）。所有数据以本地 veritas 仓库为 canonical，其余为其派生/镜像。

## 1. Canonical（本地 veritas 仓库 = 唯一真源）

路径：`/Users/chaco/Desktop/medgebench/veritas`，分支 `w1/veritasbench-validator`，HEAD `6c4ad0a`。

| 数据 | 路径 | 量 |
|---|---|---|
| 基准 cases | `benchmarks/veritasbench/cases/*/case.json` | 73 cases / 232 claims（231 L1 + 1 L3） |
| 实验 suites | `benchmarks/veritasbench/suites/` | 45（holdout v1-v5+results、contamination_title_only、b1b5_bootstrap_ci、paper_level_far、trial5-63） |
| κ 双标数据 | `benchmarks/veritasbench/_second_annotation/` | blind_sheet/reannotation_v2/kappa_report/disagreements/sample_manifest/codebook |
| schema | `benchmarks/veritasbench/case.schema.json` | case.json v2.0 schema |
| manifest | `benchmarks/veritasbench/manifest.json` | case_count + inter_annotator_reliability |
| 主表（Table 2） | `outputs/experiments/veritasbench/b1b5_maintable.json` | 3 backbone × B1-B5 + CI + decision |
| 逐 claim 轨迹 | `outputs/experiments/veritasbench/b1b5_predictions/{qwen3.7-plus,deepseek-v4-pro,glm-5.2}.json` | 每 backbone × B1-B5+B5_raw × 115 test claim |
| run log | `outputs/experiments/veritasbench/b1b5_full3_run.log` | full 3-backbone run（leak-guard→逐 call 计时） |
| pilot | `outputs/experiments/veritasbench/eval_pilot_*.json` | 3 backbone pilot + repeatability_B1 + 750-run estimate |
| leak guard | `outputs/experiments/veritasbench/b1b5_leak_guard.json` | 186 prompts 扫描，gold_leak_free |
| value crosscheck | `outputs/experiments/veritasbench/value_crosscheck.json` + `data_validation.json` | obs 值 vs 原始 xlsx |
| E2 risk-coverage | `outputs/experiments/veritasbench/e2_risk_coverage.csv` + `.README.md` | 3 bb × B1-B5 全阈值 sweep |
| E4 slice | `outputs/experiments/veritasbench/e4_slice_failuremode.csv` | 按 failure_mode 切片 |
| 评测代码 | `engine/benchmark/*.py` | metrics / backbones / verifiers / decision / provenance / bridge / recompute_verifier / schema 等 16 模块 |
| scripts | `scripts/` | run_veritasbench_b1b5 / run_bX_audit / validate / qc / download_real_paper / rescore / crosscheck / run_veritasbench_eval |

## 2. 服务器（192.168.10.40 = medge-server-5，`/srv/Research/share/medgebench`）

服务器是 **raw source data 上游**，不是 veritasbench canonical（veritas 仓库不在服务器）。

| 数据 | 路径 | 说明 |
|---|---|---|
| **原始 source data（上游）** | `downloads/real-papers/<DOI>/source_data/` | 54 个 DOI 目录，原始 xlsx/csv + paper pdf + fetch_manifest。本地 case 的 artifacts 即从此复制 |
| case 镜像（**stale**） | `downloads/real-papers/_veritasbench_cases/` | 仅 40 case（应 73）+ 2 散落 = 42。过期/不完整 |
| veritasbench 输出 | — | **服务器无**任何 veritasbench 评测产物（结果只在本地） |
| broader MedgeBench | `build-kit/`（tasks/jobs/scaffolding/forensics-raw-data/paper_list xlsx） | 非 veritasbench，是 MedgeBench Harbor eval |

## 3. 匿名仓库（GitHub `MedgeAI/veritasbench-anonymous`，本地 clone `/tmp/veritasbench-anonymous-github`）

发布快照（anonymized，`e1e98fc` wuguandu→annotator_1）。

| 数据 | 路径 | 状态 |
|---|---|---|
| cases | `data/cases/` | 73（anonymized）✓ |
| suites | `data/suites/` | 45 ✓ |
| splits | `data/splits/l1_dev_test.json` | ✓ |
| schema + manifest | `data/case.schema.json`, `data/manifest.json` | ✓ |
| 评测代码 | `code/src/`（metrics/runner/dataset_validator/experiment_runner/verifiers） | ✓ |
| README + LICENSE | 根 | 有 install/validator/eval 指引 ✓ |
| 🔴 **逐 claim 预测** | — | **缺** `b1b5_predictions/` + `b1b5_maintable.json` + E2/E4 CSV |

## 4. Overleaf（论文仓库，`/tmp/overleaf-push`）

| 数据 | 路径 |
|---|---|
| case-teaser 数据（Fig.1） | `figures/results/case-teaser-data.json`（ncb_sting duplication，openpyxl-verified） |
| 协调总计划 | `KDD-REVISION-DAG.md`（source of truth） |
| 论文 | `sections/*.tex` + `main.tex` + `figures/*.tex` |

## 5. Provenance 链（已 sha256 验证）

```
服务器 downloads/real-papers/<DOI>/source_data/*.xlsx
    └─(sha256 逐位相同)─→ 本地 cases/<case>/artifacts/*.xlsx
                              └─(anonymized 复制)─→ 匿名仓库 data/cases/<case>/
```

spot-check：ncb_sting `41556_2021_659_MOESM17_ESM.xlsx` 两端 sha256 前缀均 `d946f95188cb0b56`。本地 case artifact 就是服务器 raw source data 的字节副本。

## 6. 一致性 / 缺口

| 项 | 状态 |
|---|---|
| 本地 73 cases == 匿名仓库 73 cases | ✅ 一致（匿名仓库已 anonymize） |
| 本地 case artifact sha256 == 服务器 raw source data | ✅ 一致 |
| 本地 outputs（b1b5 预测/主表） | ✅ canonical，本地独有 |
| 🔴 匿名仓库缺逐 claim 预测 + 主表 + E2/E4 | ❌ 需补 `data/results/`（复现缺口，违反 DAG 规则2） |
| 🟡 服务器 case 镜像 stale（40 vs 73） | ⚠️ 需同步到 73 或退役 |
| 🔴 4open（论文 canonical 链接）空 `not_connected` | ❌ 需接 public 后端 GitHub repo 或直传 |

## 7. 统一方案（建议）

1. **Canonical 不动**：本地 veritas 仓库（`6c4ad0a`）是唯一真源，所有派生从这里出。
2. **服务器定位明确**：只作 raw source data 上游（54 DOI）。stale 的 `_veritasbench_cases/` 镜像→**退役或同步到 73**（二选一，数据负责人定），避免和 canonical 73 混淆。
3. **匿名仓库补齐**：加 `data/results/`（b1b5_maintable + b1b5_predictions/{3 bb} + e2/e4 CSV + results README），使发布快照复现完整（满足 DAG"逐 claim 原始预测可追溯"）。
4. **4open 修复**：把匿名仓库接一个 **public** GitHub 后端（4open 只同步 public），或网页直传；4open 自动匿名 serve。修复前论文链接指向空仓库=致命伤。
5. **本清单随 D0 hash 发全员**：所有人以 `6c4ad0a` + 本 manifest 为数据基准。
