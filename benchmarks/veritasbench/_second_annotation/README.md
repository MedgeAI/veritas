# VeritasBench 第二标注 (§5 双标 + κ)

## 你要做的
1. 打开 `blind_annotation_sheet.csv`（50 个 claim，来自分层抽样的 16 个案 = 26%）。
2. 每行读 `claim_atom` + `source_evidence`/`target_evidence`（含可抽取的 obs 值与 span）+ `evidence_span`。
3. **独立**在 `YOUR_VERDICT` 列填三选一：`consistent` / `inconsistent` / `insufficient`。
   - consistent：断言与证据一致（数据支持、或"看着可疑但有合法解释"）。
   - inconsistent：断言与证据不符（重复/复制/错值/矛盾）。
   - insufficient：现有证据无法判定（原始数据缺失/待更正/需额外实验）。
4. 可选填 `YOUR_CONFIDENCE`(high/med/low) 与 `YOUR_NOTES`。
5. 填完把 CSV 存回原路径，告诉我，我算 Cohen's κ（对 verdict）并出分歧复盘。

## 盲的口径
已隐去：wuguandu 的 verdict、discrepancy_type、is_clean_claim、`_adjudication` 推理、以及该案的 failure-mode 桶标签——你只凭 claim + 证据独立判。
κ 的"真值"来自各 case.json 里 wuguandu 的 verdict（我算时读，不用你提供）。

## 注意
- 部分 claim_atom 会描述发现（如"作者承认…"），这是被标注的对象本身；你仍需独立判 verdict。
- 抽样 seed=20260715，{'verifier_conflict': 4, 'false_positive_trap': 5, 'grounding': 3, 'mixed_boundary': 4}，可复现。
