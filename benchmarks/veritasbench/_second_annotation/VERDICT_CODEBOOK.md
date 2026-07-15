# VeritasBench Verdict Codebook (v1)

你判的是每个 claim 的 **溯源完整性 (provenance integrity)** —— 报告的数值/关系是否真实、正确地来自其证据,
而 **不是** 数值之间是否相等。

## consistent (溯源成立 · 不该 flag)
claim 的数值/关系被证据正确支持,数据完整性无问题。**包括「表面可疑但有合法解释」**:
- 量化/离散计数导致的尾数或值重合(面积%量化、事件数/60s、共用分母比例);
- 归一化/标准曲线/共用对照导致的值巧合;
- 同一测量在多处正当复用(图注/Source Data 已说明)。
→ 审计者查证后 **不应报异常**。

## inconsistent (溯源失败 · 应 flag)
证据与「独立、正当推导」矛盾。**关键:两个本应独立的条件/实验产生完全相同(或恒定偏移)的数值 = inconsistent** ——
因为独立测量不可能逐位相同。
- ⚠️ **「数值相等」≠ consistent**。D 列 = B 列(不同处理组)逐位相同 → **inconsistent**(复制粘贴签名),不是「数据一致」。
- 恒定偏移(整列 −0.30)、跨条件整块复制、错位(同鱼不同体长)、伪重复(细胞当独立 n)= inconsistent。
- 作者已承认的复制/错值、机构认定造假 = inconsistent。

## insufficient (证据不足 · 待定)
现有证据无法判定溯源成立还是失败:原始数据/trace 未存档只有派生表;正式更正未发布/重分析未公开;需额外实验或交互检验。

## 一句话决策
- 值**该**相等且相等 → consistent;值**不该**相等却逐位相等 → **inconsistent**;判不了 → insufficient。
- 「看着可疑但有合法机制解释」→ consistent;「看着可疑且无合法解释/已认造假」→ inconsistent。

---
本轮重标:22 个 claim(来自 mixed+verifier_conflict 的 8 个抽样案,verdict 分布平衡 10/8/4,
你无法从选案反推答案)。读 codebook 后独立填 `YOUR_VERDICT_v2`。填完我重算 κ 对比 v1(0.755)。
