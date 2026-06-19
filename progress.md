截至当前实现，Veritas 已经能跑一个 **paper audit happy path**，但还不是刚才计划里的 agentic HITL 工作台。

**当前已支持**
1. **CLI / Web 启动审查**
   - CLI：`cli/main.py audit-paper <paper_dir> --case-id <case_id>`
   - Web：创建 case、上传 PDF/Source Data/材料文件、启动真实 audit run。
   - Web run 是 thread runner；backend 重启会把未完成 run 标成 interrupted。

2. **PDF 解析和证据底座**
   - 调 MinerU 解析 PDF。
   - 生成 `full.md`、`mineru_manifest.json`、`evidence_ledger.json`。
   - 输出统一放到 `outputs/<case_id>/research-integrity-audit/`。

3. **Source Data 审查**
   - 识别 XLSX/XLSM Source Data。
   - 生成 profile。
   - 检查 duplicate columns、fixed difference/ratio、pair/row-offset、cross-sheet duplicates。
   - 缺 Source Data 会作为 completeness / skipped 记录，不伪造成已验证。

4. **数值和规则审查**
   - PDF numeric forensics。
   - PaperFraud rule match。
   - paperconan numeric forensics 也已接入工具注册表和链路。

5. **视觉证据**
   - MinerU 图片提取。
   - exact image duplicate。
   - ELIS adapter panel extraction（YOLOv5），失败会 fallback 到 whole-figure panel。
   - ELIS adapter copy-move（RootSIFT+MAGSAC++），Agent investigation 可选触发。
   - **overlap/reuse detection**（tile-level dHash retrieval + RootSIFT+MAGSAC++ verification），已修复数据契约，从 baseline 移除，仅 investigation 触发。
   - visual finding pipeline 会把 exact duplicate / copy-move / overlap_reuse / similarity 结果聚合成 `image_relationships.json` 和 `visual_findings.json`。
   - TruFor / provenance graph 当前有执行入口，但依赖环境，失败或缺依赖会记录到 manifest/limitations。
   - `visual.copy_move_dense` / SILA dense 已从 baseline 移出，只能 Web 手动选择 panel 触发。
   - Web Visual Forensics Gallery 支持 Overlap Graph（面板关系可视化）和 Detail Drawer（relationship 详情）。

6. **Agent 层**
   - `agent_material_plan`
   - 最多 3 轮 `AgentInvestigationPlanner`
   - `agent_review`
   - role layer：`ClaimExtractor`、`SourceDataAuditor`、`JudgeAgent`
   - 都通过 context pack / schema validation / logs 走，失败不会覆盖确定性证据。

7. **报告和 Web 查看**
   - 生成 `static_audit_bundle.json`
   - 生成 Markdown / HTML 报告
   - Web 可看 Cases、Mission Control、Evidence Workspace、Report Center、Visual Forensics Gallery
   - `Investigation Board / Review Queue / Advanced Lab` 当前还是 placeholder。

**一个真实使用感受**

假设 PI 拿到学生准备投稿的一篇生信干实验论文，材料里有：

```text
paper.pdf
source_data.xlsx
supplementary_tables.xlsx
```

PI 在 Web 里创建 case：`crc-transcriptomics-precheck`，上传这些文件，点“上传并启动审查”。

系统会先做材料清单：发现有 PDF，有两个 Excel。然后 MinerU 解析论文，把正文、表格、图像拆出来。接着 Source Data 审查开始跑。

假设 `source_data.xlsx` 里有两个 sheet：

```text
Figure2_DEG
Figure4_survival
```

系统发现一个高危 consistency 候选：

```text
Figure2_DEG sheet 中：
列名不同：Tumor_logFC / Normal_logFC
但 126 行数值完全相同
```

这会进入 Source Data findings。报告不会说“造假成立”，而是写成：

```text
不同实验条件列存在完全相同数值序列。
需要要求学生解释这些列是否来自同一计算结果、公式派生、复制粘贴，或是否存在数据提交错误。
```

同时，pair forensics 可能发现：

```text
某两个数值列存在固定比例 2.0000，支持率 100%
```

这会被归为 consistency，因为它可能是合法标准化，也可能是人为派生，需要人工复核。

视觉部分，MinerU 抽出 Figure 3 和 Figure 4 图片。panel extraction 把复合图拆成多个 panel。Visual Forensics 页面里 PI 可以看到每张 figure、每个 panel、已有 relationships/findings。

如果 PI 看到 Figure 4 的两个 blot-like panel 很可疑，可以手动勾选这两个 panel，点击运行 `SILA Dense Copy-Move`。当前实现会：

```text
只处理选中的 panel
按 max_panels 预算截断
调用 dense copy-move 工具
把结果写入 investigation/web/<action_id>/copy_move_dense.json
把记录追加到 investigation_rounds.jsonl
```

然后 Visual Forensics 会显示这次 investigation 的结果摘要。如果工具产出 mask/overlay，页面会展示对应候选区域。这里仍然只是“候选事实”，不是最终结论。

最后，Agent review 会读取这些结构化产物，帮 PI 整理：

```text
Top priority findings
manual review tasks
benign explanations
limitations
```

最终 HTML 报告会给 PI 一个行动清单，例如：

```text
1. 要求学生解释 Figure2_DEG 中两列完全重复的来源。
2. 核对固定比例列是否来自合法 normalization。
3. 要求提交 Figure 4 原始未裁剪图片。
4. 对 SILA dense 命中的 panel 做人工视觉复核。
```

**当前还没支持**
- Agentic proposal queue：还没有“Agent 提案 -> Human 审批 -> 执行”的 Web 闭环。
- Review Queue 的真实状态管理还没实现。
- Advanced Lab 还没实现 registry-driven 工具面板。
- 没有完整异步 job 系统，重型工具仍依赖当前 backend 进程。
- 不做最终科研诚信判定。当前输出是技术事实、异常候选和人工复核任务。