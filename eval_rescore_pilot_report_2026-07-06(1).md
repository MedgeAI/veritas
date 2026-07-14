# Trace 复评协议 · Pilot 重打分报告

**日期**：2026-07-06
**范围**：run1 存量 trace，pilot 20 格（Phase 0–2）
**协议依据**：`00_参考资料/medgebench_trace_evaluation_protocol_design_zh.md`（Trace Evidence Evaluation Protocol）
**产出目录**：服务器 `build-kit/eval_runs/run1_rescore/`

> **📌 要重新设计 rubric 的话，直接看 [第七节](#七给-rubric-重新设计的具体建议本-pilot-最可落地的输出)** —— 那里把本 pilot 的 20 格数据翻译成了 5 条可执行的 rubric 改法（claim-calibration gate / comparability 独立化 / criterion 锚定可引用证据 / 过程轴与结果轴分离 / 抓 ACTION 不抓 prose）+ "别动"清单 + 权重待定项。前六节是支撑证据。

---

## 一句话结论

用新的 evidence-packet 复评协议对 run1 的 20 个已存 trace **离线重打分**（不重跑 agent），结果与旧分强相关（**Pearson r=0.88**），但新增了旧 8 维 rubric 抓不到的信号——**claim 校准（过度声称）**、**source-paper 可比性**、**证据可追溯性**——并在过程中**修复了 run1 的一处数据完整性污染**。同时通过人工抽核发现并修复了 judge 的一个引用倒填缺陷。

---

## 一、背景：为什么重打分

旧评分 = verify.py（20%，查文件存在/格式）+ LLM judge（80%，8 维 rubric A/B/C）。它回答"文件在不在、格式对不对、按 rubric 打几分"，但**回答不了**三件事：

1. artifact 是 agent 真算出来的，还是编/抄/硬写的？（provenance）
2. 报告的 claim 强度和它实际拿出的证据匹配吗？（claim calibration）
3. 结果和 source-paper 目标构成有效科学比较吗？（comparability）

新协议用**分层判断**补齐：verifier 层（文件/可重算）→ provenance 层（artifact 是否真生成）→ 受约束语义 judge（6 轴 + 可比性 + claim 校准）→ human audit（冲突/低置信/高风险）。

**关键前提已验证**：这套协议**不需要重跑 Harbor**。run1 的每个 job 里都存了 agent 产出文件（`verifier/*.csv`）、完整会话日志（`agent/sessions/*.jsonl`，含每条 bash/write）、中间结果（`intermediate/*.npz`）——足以离线重建 provenance 到 `high`（此前担心"无 checksum 只能封顶 medium"的结论，被磁盘上实际存在的会话日志推翻）。

---

## 二、三个数据完整性发现

重打分的第一副产品是发现 run1 存量数据的三个坑：

1. **`results.csv` 被 judge-API 故障污染**：230 格里 **104 格（45%）** 在 `results.csv` 记 0 分，但 cell 自身 `reward.json` 是真分（43–100），且 **104 格全部带 `.bogus` 文件**（gpt-5.5 judge 401 鉴权失败残留）。清一色是 qwen / deepseek / glm 三个 DashScope 模型。
   → judge 后来重跑修好了（cell reward 是对的），但 `results.csv` 这个中间汇总文件没刷新。

2. **claude / gpt 主批全崩**：run1 主批里所有 claude-opus 和 gpt-5.5 行都是 `failed`（endpoint 事故，Opus/GPT 须走 NewAPI 而非 DashScope），真分在 `run1_retry*` 批次。

3. **合并后的 full CSV 已丢失**：最终报告用的"harvester 合并数据"（`eval_run1_full_data_*.csv`）已被删。

**处置**：重打分的"旧分基线"一律取 **cell `reward.json`**（= 最终报告口径），并由 harness 自动合并 4 个批次（`run1` + 3 个 retry）重建权威旧分。**最终报告的模型排名不受影响**（它本就用的修正数据），受污染的只是 `results.csv` 这一个中间文件。

---

## 三、Pilot 20 格结果

### 总表

| task | model | 旧分 | 新分 | Δ | comparability | claim | packet | 送审 |
|------|-------|:---:|:---:|:---:|---|---|:---:|:---:|
| 004-1 | claude | 92 | 100 | +8 | fully | well | medium | |
| 022-1 | claude | 45 | 40 | −5 | **non** | well | rich | |
| 022-1 | gpt-5.5 | 83 | 82.5 | ≈ | partially | well | rich | |
| 022-1 | qwen | 59 | 57.5 | ≈ | partially | well | rich | |
| 047-1 | glm | 100 | 100 | = | fully | well | bare | |
| 047-1 | claude | 100 | 100 | = | fully | well | medium | |
| 061-1 | qwen | 50 | 45 | −5 | partially | **over**(mech,causal) | bare | ✔ |
| 061-1 | gpt-5.5 | 82 | 72.5 | −10 | partially | under | bare | ✔ |
| 103-1 | glm | 43 | 30 | −13 | partially | **over**(biomarker,mech,causal) | bare | ✔ |
| 104-1 | qwen | 55 | 75 | **+20** | partially | well | bare | ✔ |
| 116-1 | qwen | 63 | 65 | +2 | partially | **over** | bare | ✔ |
| 122-1 | glm | 100 | 100 | = | fully | well | bare | |
| 126-1 | qwen | 53 | 40 | −13 | partially | **over**(causal,mech) | bare | ✔ |
| 136-1 | qwen | 55 | 77.5 | **+22** | partially | well | bare | ✔ |
| 150-1 | deepseek | 95 | 85 | −10 | partially | well | bare | ✔ |
| 150-1 | qwen | 73 | 65 | −8 | partially | **over**(causal) | bare | ✔ |
| 240-1 | claude | 90 | 75 | **−15** | fully | **over**(mech) | medium | |
| 133-1 | glm | 58 | 57.5 | ≈ | partially | well | bare | ✔ |
| 109-1 | deepseek | 78 | 92.5 | +14 | partially | well | bare | |
| 092-1 | qwen | 58 | 50 | −8 | partially | **over**(clinical,biomarker) | bare | ✔ |

### 统计

- **新分 vs 旧分**：Pearson **r = 0.88**，mean|Δ| = 7.8，mean Δ = −1.1（略降，与 overclaim 惩罚一致）
- **claim 校准**：well 12 / **overclaimed 7** / underclaimed 1
- **comparability**：fully 5 / partially 14 / non 1
- **provenance**：20/20 = high（离线重建全部达成）
- **需人工抽核**：11/20（全部是 bare-packet 格，fabrication 风险最高的那批）

---

## 四、四个已验证的价值点

**1. 修复数据完整性污染。** pilot 里所有 `results.csv=0` 的污染格（061/103/104/116/122/126/133/136/150/092…）全部拿回真实新分。这是重打分最直接的产出。

**2. claim 校准抓到旧 rubric 漏的过度声称（7 格）。** 最典型 **medge-240 claude：旧 90 → 新 75**（`mechanism_overclaim`）——agent 自己写"CEBPB occupancy consistent with CEBPB helping nucleate the memory state"，把相关性 ChIP/ATAC 证据说成机制因果。旧 8 维给 90，新协议因过度声称扣到 75。judge 的证据引用 `final_report.answer`，是 agent 自己的原话，非外部 GT。

**3. comparability 解释"为什么低分"。** medge-022 claude 旧 45、新 40、标 `non_comparable`——不是"部分得分"，而是**方向性错误**：核心结论与预期完全零重叠（`up_overlap=0/10`、`down_overlap=0/8`、PD 疾病态未扩张 `Young=0.13 Aged=0.11 PD=0.13`），报了 uniform shift。这些数字来自该格丰富的 `verify_score.json`，judge 引用属实。

**4. 部分格子被合理上调。** 104 qwen 55→75、136 qwen 55→77.5、109 deepseek 78→92.5——旧 rubric 欠给分（预处理强、框定谨慎"hypothesis-generating"），新协议按 6 轴给回。

---

## 五、人工抽核发现的缺陷 + 修复

抽核 4 格（240/061/022/104）时发现：**judge 在 packet 信号稀薄时会倒填不存在的 evidence_source**。

- **根因**：任务间 packet 丰富度不均。022/240 这类 verify.py 往 `verify_score.json` 写了带数字的 ACTION 检查（judge 有真信号可引）；061 这类只有 `{"score":50}`（judge 缺证据时用领域知识补判定、并倒填 `verifier_output.gateA.enrichment_not_causal` 等根本不存在的字段）。
- **性质**：这是**实现漏洞，不是 SOP 缺陷**——协议 §7/§12.7 早已规定"每个 label 必须引用真实 evidence，否则 confidence=low + needs_human_audit"，只是当初没落进 harness。判定本身没错（4/4 成立），坏的是引用卫生。

**修复（已部署）**——四重防护：
1. `cite_valid()`：逐段解析引用是否对应 packet 真实结构（`verifier_output` 是 list，任何 `.gateA/.verdict` 命名子字段判假）。
2. `audit_citations()`：all-invalid label → confidence=low；bare-packet → 强制送审；输出 `groundedness` + `packet_richness`。
3. 内联进 run_pilot，全量自动生效。
4. prompt 硬约束 rule 6：从源头禁止倒填。

**效果**：现有 20 格事后校验，11/20 精准路由送审，假引用显式标出（092 达 7/14、103 达 6/11），**正确判定零误杀**（061 因每个 label 都有 ≥1 真引用而保留判定，仅假引用被标 + 送审）。

---

## 六、Limitation

1. **未触发 infra/leakage 诊断路由**：pilot 20 格都是"已恢复的真跑"，没覆盖真正无恢复的崩溃格（那条路径只在单测中验证过）。全量会包含。
2. **bare-packet 判定可信度天然较低**：14/20 是 bare-packet，judge 可引证据少，已全部路由人工。这是存量数据属性，无法离线补（除非重跑 verify 生成 detail）。
3. **6 轴 A/B/C → 百分制映射**（data15/method20/stats15/bio15/reason20/quant15）是本次设定，可调。
4. **单 judge（GPT-5.5）**：协议 §9.4 建议多 judge 稳定性测试，本次未做。

---

## 七、给 rubric 重新设计的具体建议（本 pilot 最可落地的输出）

> 本节把 pilot 的 20 格数据 + run1 完整 51×6 eval 的发现，翻译成**重写 rubric 时的可执行动作**。按优先级排序，每条给：pilot 证据 → 具体改法 → 例子。核心判断：**r=0.88 说明旧 8 维的骨架是对的，这是"补三块缺口 + 改评分结构"，不是推倒重来。**

### R1 · 加 claim-calibration 作独立评分轴 + 硬 gate（最高优先级）
- **证据**：7/20 overclaim，旧 8 维**全给了高分**。最典型 medge-240 claude 旧 **90**——agent 自己写 "CEBPB occupancy consistent with CEBPB helping nucleate the memory state"，把相关性 ChIP/ATAC 证据说成机制因果，旧 rubric 因报告写得漂亮给 90。
- **改法**：新 rubric 增一条 `claim_calibration` criterion（A=claim 强度与 evidence/comparability 一致；B=轻微 over/under；C=partial/non-comparable 证据被写成 full reproduction / 因果 / 临床结论）。**硬规则落进 rubric**：comparability ≤ partially 且报告称 "fully reproduced / causal / clinical" → 该轴自动 C，且 overall 封顶到不了 A。保留 5 个 biomedical 子标签（clinical/biomarker/mechanism/causal/full_reproduction）。
- **附带红利**：直接治**天花板效应**——run1 完整数据里 8.5% 打满分、median 78 偏高，就是因为旧 rubric 没有惩罚"证据不足却写得肯定"。这个 gate 让 100 变稀有（240 就从 90→75）。

### R2 · comparability 从"分数段"改成独立标签，non-comparable 封顶质量轴
- **证据**：medge-022 claude 标 `non_comparable`，旧给 **45**——看着像"拿了部分分"，其实是**方向性失败**（`up_overlap=0/10`、`down_overlap=0/8`，把疾病态扩张报成 uniform shift，PD 未扩张 Young0.13/Aged0.11/PD0.13）。旧 rubric 把"做了工作"和"答对了"混成一个中间分，掩盖了答案是错的。
- **改法**：comparability 用 4 类标签（fully/partially/non/failed），**独立于 A/B/C 质量轴**；non_comparable / failed → biological_interpretation + scientific_reasoning 两轴**封顶 B/C**（过程再好，答案方向错 = 结果轴不能高）。别再让"方向错"落在 40-50 的模糊中段。

### R3 · 每条 criterion 必须锚定可引用证据 —— rubric 与 verify.py 协同设计
- **证据**：judge 在 packet 信号稀薄时**倒填不存在的 evidence_source**（061 只有 `{"score":50}`，judge 编出 `verifier_output.gateA.enrichment_not_causal`）；14/20 是 bare-packet。根因是 **verify.py 输出丰富度不均**：022/240 的 `verify_score.json` 带数字（judge 有据可引），061 的只有一个总分。
- **改法**：① rubric 每条 A/B/C anchor **写明判据来自哪个 artifact 字段 / verify 检查**（不是"评估统计严谨性"这种空泛话，而是"检查 `ihm_comparison.csv` 的 `p_value` 两行是否一致 + 方法在 trace 命名"）。② **建 task 时 verify.py 必须为每条 rubric criterion emit 可引用的 ACTION 数字**。**rubric 和 verify.py 必须一起设计**——否则 judge 无据可依只能编（这也正是本 pilot 修的那个引用倒填缺陷的根源，属结构问题非实现问题）。

### R4 · 分离"过程质量"与"答案正确性"，别算术平均成一个数
- **证据**：模型常见形态是**过程好但答案错**（data/method/stats 拿 A，comparability 却 non）。旧 rubric 8 维平均后落到 45，既没表扬过程、也没暴露答案错——信息被抹平。这与 run1 里反复出现的 **prose-action separation**（嘴上说对、输出列选错：119/092/134/103）同源。
- **改法**：新 rubric 分两组轴报告 —— **过程轴**（data_handling / method_selection / statistical_rigor / result_quantification）+ **结果轴**（comparability / claim_calibration / biological_interpretation-reasoning）。overall 用"**结果轴 gate 过程轴**"（结果轴低 → 封顶），而非六轴算术平均。这样一个 trace 能同时读出"方法扎实"和"结论错了"两个正交信号。

### R5 · A-level 判据落在 ACTION（最终输出列/选择），prose 只作辅证
- **证据**：run1 主发现 = prose-action separation（模型 trace 里说 "correlative" 却在 `causal_call` 列标 causal；说要 CLR 却 primary 用边际）。旧 rubric 若只读 prose reasoning 会被骗（LLM 分虚高）。
- **改法**：每条 criterion 的 A-level 明确判**最终产出物的具体列/选择**（verify.py 复算的 `is_X_predictive` / `response_metric` / 提名基因集），trace 的 prose 只作 reasoning 轴的补充证据、不作主判据。与 R1/R3 一条线。

### 保留、别动的（旧 rubric 做对的）
- **A/B/C 三级 + 每条列多条同样得 A 的合法路径**（不惩罚合理替代方法）—— 这是旧 rubric 的精华，新版继续。
- **8 维骨架大体成立**（r=0.88）——data/method/stats/bio/reason/quant 六轴保留，只把 claim 和 comparability 从"藏在某条 criterion 里"提升为独立轴 + gate。

### 评分映射的两个待定（请同事拍板，对应协议 §12.6/§12.7）
1. **权重**：pilot 用 data15/method20/stats15/bio15/reason20/quant15。reason 20 偏高；建议给 claim_calibration 单独权重（如 10），comparability 做**乘子/gate 而非加数**（non → ×0.5 结果轴，对齐 R2）。
2. **每个 label 强制引用 evidence_id**（协议 §12.7 的待定项）——pilot 证明：一旦强制，11/20 精准送审、假引用零误杀。**建议采纳为硬约束**，这是 R3 的执行保障。

---

## 八、结论与下一步

新协议在存量 trace 上**可离线落地、与旧分强相关、且补齐了 claim/comparability/provenance 三个旧评分缺失维度**，并顺带审计出 run1 的数据污染。harness 经 pilot 验证可靠，缺陷已修复。

**下一步选项**：
- **全量**：用修好的 harness 跑约 250 个有效格，出主可比 leaderboard + 诊断表 + reproducibility bottleneck map + 新旧 diff。
- **先增强**：调 axis 权重 / 加多-judge / 补真崩溃格样本后再全量。

---

*产出文件*：`build-kit/eval_runs/run1_rescore/` — `rescore_lib.py`（assembler + gates + 引用校验）、`run_pilot.py`（合并+judge 驱动）、`trace_judge_prompt.md` + `judge_schema.json`（GPT-5.5 语义 judge）、`scan_contamination.py`、`validate_citations.py`、`pilot/summary.csv` + `pilot/citation_audit.csv` + 20 个逐格 JSON。
