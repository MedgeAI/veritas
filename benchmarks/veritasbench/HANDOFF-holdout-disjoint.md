# HANDOFF: detector-disjoint holdout suite → w1 验证

**优先级:高(投稿命门)**  
**背景**:审稿人质疑 B3 FAR 下降是循环论证——训练案例和 benchmark 案例用同一套 duplicate/offset 规则构造。我们已筛出 7 个"detector-disjoint"案:异常类型不在 detector 覆盖范围内,来源是外部 PubPeer/更正声明。suite 文件已落盘:`suites/holdout_detector_disjoint_v1.json`

## w1 需要做的两件事

### 1. 官方 validator 通过确认
```bash
python3 scripts/validate_veritasbench.py \
  --suite suites/holdout_detector_disjoint_v1.json \
  --expected-cases 7
```
预期:全 7 案 ok=true。若有 FAIL,告知哪案哪字段。

### 2. B3 detector 在这 7 案上的 FAR 测试（核心）
把 B3 的 forensics detector(duplicate-column / fixed-offset / paired-ratio / cross-sheet)跑在这 7 个案的 artifacts 上:
- **预期结果(disjoint 成立)**:detector 对 7 案全部报 `clean`(或 `no_flag`),即 FAR=0/7
- **如果 detector 误触发**:说明 aldometanib 灰区判断有误,或某案异常类型实际被覆盖——报哪案触发、触发理由,我们把它从 holdout 集排除

### 7 案清单(异常类型 + detector 不触发理由)

| case | discrepancy_type | detector 不触发理由 |
|---|---|---|
| ncb_cav2 | label_swap | 标签颠倒在元数据层;detector 只比数值等式/偏移 |
| ncb_clonalfish | misaligned_records | 行级错位;detector 比的是列间值复制/线性关系 |
| ncb_lphn3 | mislabeled_panel | figure 图注字符串层;detector 不解析图像文字 |
| ncb_radioligand | provenance_mismatch | fitted-curve 替换 raw SPR;两来源无数值重复/偏移 |
| ncb_nickelate | assignment_inconsistency | 需晶体学先验;detector 只看数值大小关系 |
| ncb_spp1 | pseudoreplication | 统计单元设计层错误;detector 不判测量单元合法性 |
| ncb_aldometanib | undocumented_derivation | 差值来自公式(tumour-liver),非两独立量复制 — ⚠️灰区 |

### aldometanib 灰区判定
请把 `cases/ncb_aldometanib/artifacts/SourceData_Fig4.xlsx` 和 `SourceData_FigS10.xlsx` 跑进 fixed-offset detector:
- 若触发 → 从 holdout 集排除,holdout 缩为 6 案
- 若不触发 → 保留,理由:固定差来自同一只动物的两部位差值(公式),非独立组间复制

## 结果反馈格式
```
validator: ok=7/7 或 FAIL=[哪案]
detector FAR: 0/7 或 triggered=[哪案,理由]
aldometanib: triggered=yes/no
holdout最终确认案数: N
```

## 后续
外部搜索同步进行中(GRIM/N矛盾/版本漂移类),预计再补 6-11 案。w1 验证完这 7 个之后,新案逐批追加进 holdout_detector_disjoint_v2.json。
