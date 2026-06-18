# Veritas Visual Overlap Forensics PRD

Updated: 2026-06-18
Status: Draft for review
Owner: Veritas

## 1. 背景

Veritas 当前定位是投稿前论文风控工具，核心任务是帮助导师在投稿前主动发现学生材料中的异常模式、证据缺口和人工复核任务。图片重复使用是生物医药论文中最容易被导师理解、也最接近高风险一致性问题的场景之一：同一张显微图、Western blot 条带、组织切片或局部区域可能被裁剪、缩放、旋转、翻转、亮度调整后用于不同 figure、panel、实验条件或样本标签。

现有视觉链路已经具备 `figure_evidence`、`panel_evidence`、`image_relationship`、`visual_finding`、HTML Visual Evidence Package 和 Web Gallery 的基础，但视觉复用检测仍偏过渡态：

- `image.exact_duplicates` 只能发现字节级完全重复。
- `image.similarity_candidates` / SSCD / dHash 适合近似相似候选召回，但不能直接证明局部 overlap。
- `visual.copy_move` / `visual.copy_move_dense` 能检测复用，但当前产品语义仍偏 copy-move 工具，而不是面向 PI 的“跨图重叠证据”主干。
- `visual.provenance_graph` 已有 “SSCD 预筛 + RootSIFT/MAGSAC++ 验证”雏形，但尚未沉淀成稳定的 overlap evidence、报告展示和决策分层。

本 PRD 建议将图片 overlap / reuse detection 提升为 Veritas 视觉取证主线之一。开发阶段允许较大幅度重构视觉证据引擎，但外部仍必须保持 Evidence First、Tool Registry、manifest、structured artifacts、HTML report 和人工复核边界。

## 2. 产品目标

### 2.1 用户目标

导师或复核人员希望快速回答：

- 两个 panel 是否共享同一原始图像区域？
- 重叠区域在哪里，是否经过裁剪、缩放、旋转、翻转或亮度调整？
- 两个 panel 在论文中是否声称代表不同实验条件、样本、时间点或处理组？
- 是否存在合理解释，例如 shared control、same field of view、merge/channel view、合法重复展示？
- 需要向学生索要哪些原始材料来完成复核？

### 2.2 产品目标

1. 将图片重复/overlap 作为 `consistency` 高价值发现入口。
2. 产出可视化证据，而不是只产出相似分数。
3. 把“候选召回”和“几何验证”分开，降低误报。
4. 报告语言保持谨慎：发现重叠候选和复核任务，不下最终科研诚信判定。
5. 为后续接入 MONet/BioFors、TruFor、ELIS copy-move、CBIR/Milvus 留出 adapter 边界。

### 2.3 非目标

- 不自动判定“造假”或“学术不端成立”。
- 不把 fluorescence colocalization 结果等同于图片复用。
- 不在第一阶段依赖远程 worker、完整 SaaS、多租户队列或外部数据库。
- 不要求第一阶段全量接入 MONet 或重型深度学习模型。
- 不直接接入 ELIS FastAPI/Celery/MongoDB/Redis 主服务。

## 3. 核心概念

### 3.1 Overlap Reuse

`visual.overlap_reuse` 指跨 figure、跨 panel 或同一 panel 内的局部图像区域复用。典型变换包括：

- exact duplicate
- crop
- resize / scale
- rotate
- flip
- brightness / contrast adjustment
- partial local reuse
- same field-of-view reused under different labels

该能力优先解决“图片重复使用”重灾区。

### 3.2 Channel Overlap

`visual.channel_overlap` 指荧光图、多通道 microscopy 或 merge 图中的通道共定位/重叠分析。它和图片复用不是同一问题。ImageJ Coloc 2 文档也明确提示 colocalization 有大量 ROI、背景、noise、bleed-through 和 threshold pitfalls。因此本能力只作为后续人工复核辅助，不进入第一阶段主线。

## 4. 方案判断

### 4.1 推荐路线

第一阶段做 `visual.overlap_reuse`，定位为视觉取证主干的 baseline-lite + optional deep verification：

```text
visual/images/
  -> figure_evidence.json
  -> panel_evidence.json
  -> panel tiles
  -> candidate retrieval
       exact hash / dHash / SSCD / tile hash
  -> geometric verification
       RootSIFT + MAGSAC++ / RANSAC
  -> dense fallback
       SILA dense / phase correlation / MONet adapter later
  -> overlap evidence
       masks / warped overlays / keypoint visualizations
  -> image_relationship + visual_finding
  -> HTML report + Web Gallery review task
```

关键设计：从“整图相似”升级为“tile-level overlap retrieval”。局部复用可能只占整张图的一小块，整图 embedding 会被背景和非重叠区域稀释。tile-level 检索可以先找到局部候选，再回到 panel 坐标系做几何验证。

### 4.2 不推荐路线

- 只用 SSCD 全图 embedding：召回快，但不能证明局部 overlap。
- 只用 dHash/perceptual hash：对裁剪、局部复用和复杂变换不够稳。
- 第一阶段直接押宝 MONet：学术方向匹配，但模型、权重、部署、阈值和 fixture 需要验证，不应阻塞第一版。
- 把 channel colocalization 当 overlap fraud detector：误报风险高，且需要生物学上下文。

## 5. 能力分层

| 层级 | 能力 | 目标 | 第一阶段状态 |
| --- | --- | --- | --- |
| L0 | exact duplicate | 字节级重复 | baseline |
| L1 | near duplicate retrieval | 全图近似候选 | baseline-lite |
| L2 | tile-level retrieval | 局部 overlap 候选召回 | P1 主线 |
| L3 | geometric verification | 证明两个区域有稳定几何映射 | P1 主线 |
| L4 | dense overlap | 低纹理/显微图/条带补充验证 | optional |
| L5 | deep overlap model | MONet/BioFors-style duplicated region model | research adapter |
| L6 | channel overlap | fluorescence colocalization / same field review | later optional |

## 6. 用户体验

### 6.1 报告摘要

报告 Top findings 中应显示：

- finding category: `overlap_reuse_cross_panel`
- issue category: `consistency`
- risk level: `medium` / `high`
- source panel / target panel
- overlap area ratio
- transform type
- verification method
- strongest evidence image: overlay or side-by-side warped view
- benign explanations
- required manual review actions

推荐措辞：

- “检测到跨 panel 的局部重叠候选。”
- “该结果提示两个 panel 可能共享同一原始图像区域，需要人工复核。”
- “当前证据不足以单独构成最终科研诚信判定。”

禁止措辞：

- “确认造假”
- “学术不端成立”
- “伪造概率为 X%”

### 6.2 Web Gallery

Web Visual Forensics Gallery 应提供：

- overlap graph：panel 节点和 overlap edge。
- edge detail：source/target panel、score、transform、area ratio、method。
- overlay image：重叠区域可视化。
- matched keypoints：关键点匹配图。
- warped comparison：source warp 到 target 的对齐图。
- review checklist：shared control、same field-of-view、channel merge、caption conflict、raw image request。

## 7. 数据契约

### 7.1 新 artifact

建议新增：

```text
visual/overlap_reuse.json
visual/overlap/
  OVL-0001_overlay.png
  OVL-0001_keypoints.png
  OVL-0001_warped.png
  OVL-0001_mask.png
```

`visual/overlap_reuse.json` 示例：

```json
{
  "schema_version": "1.0",
  "tool_id": "visual.overlap_reuse",
  "status": "completed",
  "relationships": [
    {
      "relationship_id": "OVL-0001",
      "source_type": "overlap_reuse_cross_panel",
      "source_panel_id": "fig2_panel_b",
      "target_panel_id": "fig5_panel_d",
      "candidate_method": "sscd_tile",
      "verification_method": "rootsift_magsac",
      "transform_type": "homography",
      "inlier_count": 42,
      "inlier_ratio": 0.71,
      "overlap_area_ratio_source": 0.38,
      "overlap_area_ratio_target": 0.44,
      "score": 0.82,
      "overlay_path": "visual/overlap/OVL-0001_overlay.png",
      "keypoints_path": "visual/overlap/OVL-0001_keypoints.png",
      "warped_path": "visual/overlap/OVL-0001_warped.png",
      "mask_path": "visual/overlap/OVL-0001_mask.png",
      "evidence_refs": [
        "panel:fig2_panel_b",
        "panel:fig5_panel_d"
      ],
      "benign_explanations": [
        "可能是同一原始视野的不同通道、合法 shared control 或重复展示的 reference panel。"
      ],
      "manual_review_questions": [
        "两个 panel 是否声称代表不同实验条件、样本、时间点或处理组？",
        "图注或方法是否声明 shared control / same field of view？",
        "作者能否提供原始显微图、仪器导出文件或未裁剪图？"
      ]
    }
  ],
  "limitations": []
}
```

### 7.2 Canonical relationship 映射

`visual.overlap_reuse` 输出应被 `visual.finding_pipeline` 归一化为 `image_relationship`：

```json
{
  "relationship_id": "OVL-0001",
  "source_type": "overlap_reuse_cross_panel",
  "source_panel_id": "fig2_panel_b",
  "target_panel_id": "fig5_panel_d",
  "score": 0.82,
  "overlay_path": "visual/overlap/OVL-0001_overlay.png",
  "metadata": {
    "candidate_method": "sscd_tile",
    "verification_method": "rootsift_magsac",
    "transform_type": "homography",
    "inlier_count": 42,
    "inlier_ratio": 0.71,
    "overlap_area_ratio_source": 0.38,
    "overlap_area_ratio_target": 0.44
  }
}
```

## 8. 风险分级

风险等级表达“人工复核优先级”，不是造假概率。

| 条件 | 建议风险 |
| --- | --- |
| exact duplicate，且两个 panel 声称不同样本/条件 | high |
| 跨 figure / 跨 panel 几何验证强，overlap area 明显 | high |
| 同一 figure 内局部 overlap，caption 语义不清 | medium |
| whole-figure fallback、panel extraction 质量差 | medium 上限 |
| 明确 shared control / same field-of-view / merge channel | low/info |
| channel colocalization 单独信号 | info/low |

`critical` 暂不作为 overlap 默认输出。只有在后续 claim/caption/source-data 多证据链形成强冲突时，综合层才可考虑。

## 9. 工程方案

### 9.1 允许重构范围

允许较大幅度重构：

- `engine/static_audit/tools/visual_*`
- visual schema normalization
- visual finding pipeline
- report visual section
- Web Visual Forensics Gallery

不建议破坏：

- Tool Registry 作为可执行工具 source of truth。
- artifacts 必须写入 workdir。
- manifest / limitations / investigation_rounds 记录失败和跳过。
- `figure_evidence` / `panel_evidence` 作为 canonical 入口。
- Agent 不得绕过 Tool Registry 直接调外部服务。

### 9.2 Tool Registry

新增 tool_id：

```python
TOOL_ID_OVERLAP_REUSE = "visual.overlap_reuse"
```

建议参数：

```json
{
  "tile_size": {"type": "integer", "minimum": 64, "maximum": 512},
  "tile_stride": {"type": "integer", "minimum": 32, "maximum": 512},
  "candidate_method": {
    "type": "string",
    "enum": ["dhash_tile", "sscd_tile", "hybrid"]
  },
  "max_candidate_pairs": {"type": "integer", "minimum": 10, "maximum": 10000},
  "min_inliers": {"type": "integer", "minimum": 4, "maximum": 200},
  "min_overlap_area": {"type": "number", "minimum": 0.0, "maximum": 1.0},
  "max_relationships": {"type": "integer", "minimum": 1, "maximum": 5000}
}
```

Execution phase 建议：

- P1 alpha: `AGENT_SELECTABLE`
- P1 beta: baseline-lite for small/medium papers, heavy verification optional
- P1 stable: `MANDATORY_BASELINE` with strict resource budget and graceful skip

### 9.3 Pipeline

第一版内部实现：

```text
1. Load panel_evidence.
2. Filter invalid panels and whole-figure fallbacks.
3. Generate overlapping tiles per panel.
4. Compute cheap tile hashes.
5. If SSCD model available, compute tile embeddings.
6. Retrieve candidate tile pairs.
7. Merge candidate tile pairs into panel pairs.
8. Verify panel pairs using RootSIFT + MAGSAC++ / RANSAC.
9. Estimate transform and overlap polygon.
10. Generate overlay/keypoints/warped/mask images.
11. Emit visual/overlap_reuse.json.
12. Merge into image_relationships.json and visual_findings.json.
```

Fallback：

- SSCD model missing: use dHash/tile hash + keypoint verification.
- Keypoints insufficient: mark candidate as unverified, optionally route to dense tool.
- Panel extraction low quality: cap risk level and surface limitation.
- GPU unavailable: skip MONet/TruFor-style deep verification without failing audit.

## 10. 分期计划

### Phase 0: Benchmark and Fixtures

目标：建立验证集，不先堆复杂模型。

交付：

- 3-5 个 synthetic overlap fixtures：crop、scale、rotation、flip、brightness。
- 2-3 个 negative fixtures：相似但不重叠、同模板图、低纹理背景。
- fixture schema：panel ids、expected relationship、expected transform rough bounds。
- baseline metrics：recall、false positives、runtime。

验收：

- synthetic crop/scale/flip 能稳定召回并验证。
- negative fixtures 不产出 high-risk finding。

### Phase 1: First-party `visual.overlap_reuse`

目标：形成可用的跨 panel overlap evidence。

交付：

- Tool Registry 注册。
- `visual/overlap_reuse.json` artifact。
- overlay/keypoints/warped/mask 输出。
- `visual.finding_pipeline` 消费 overlap relationship。
- HTML report 展示 overlap finding。
- 单测和 golden tests。

验收：

- CLI audit 能产出 overlap artifact。
- HTML report 能展示 evidence image 和 review checklist。
- 工具失败写入 limitations，不阻断 audit。

### Phase 2: Web Gallery Review Workflow

目标：让内测用户能高效复核。

交付：

- overlap graph。
- relationship detail drawer。
- overlay/warped/mask 视图。
- manual review status：needs_review / explained / unresolved。
- request raw data checklist。

验收：

- PI 能在 Web Gallery 中定位 source/target panel 和 overlap 区域。
- 可导出人工复核任务清单。

### Phase 3: Dense and Deep Adapters

目标：增强低纹理和显微图场景。

候选：

- ELIS SILA dense copy-move adapter。
- MONet/BioFors duplicated-region adapter。
- TruFor forged-region heatmap as complementary signal。
- CBIR/Milvus for large case retrieval。

验收：

- adapter 输出统一回链到 `figure_evidence` / `panel_evidence`。
- fixture-backed normalization tests。
- heavy tool failure isolation complete。

### Phase 4: Channel Overlap Optional Tool

目标：只处理 fluorescence/channel review，不和 duplication 混淆。

交付：

- `visual.channel_overlap` optional tool。
- Pearson/Manders/Costes-like metrics only when two-channel image or channel panels are identified.
- ROI/background/bleed-through limitations surfaced in report。

验收：

- 单独输出 `channel_overlap_review`，默认 risk 不高于 low/info。
- 不进入图片重复使用 Top findings，除非和 cross-panel reuse evidence 合并。

## 11. 成功指标

### 11.1 产品指标

- 内测 case 中，PI 能理解 overlap finding 的证据图和下一步动作。
- Top findings 中视觉 evidence 的可解释性明显强于单纯相似分数。
- 报告能区分 “confirmed exact duplicate” “verified overlap candidate” “unverified similarity candidate”。

### 11.2 技术指标

- Synthetic overlap fixture recall >= 0.8。
- Negative fixture high-risk false positive = 0。
- 单篇论文 baseline-lite runtime 可控，目标 < 3 分钟增量。
- 所有输出均能回链到 panel id 和 source image path。
- Tool missing / model missing / GPU missing 时 graceful skip。

## 12. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| panel extraction 错误 | 错误 crop 导致误报 | whole-figure fallback 限制风险上限；报告展示 extraction quality |
| 相似实验结构误报 | gel/blot 模板或细胞形态相似 | 必须几何验证；保留 benign explanations |
| SSCD 缺模型 | overlap 召回下降 | dHash/tile hash fallback；manifest 记录 limitation |
| 低纹理图 keypoint 不足 | 显微图/条带漏检 | optional dense / MONet adapter |
| 重型工具拖慢 audit | 影响 P0 happy path | baseline-lite + optional deep verification |
| 视觉输出被误读成结论 | 产品风险 | 固定报告措辞和风险语言，不写最终诚信判定 |

## 13. 待决策问题

1. `visual.overlap_reuse` 第一阶段是否进入 mandatory baseline，还是先作为 Agent/Web selectable tool？
2. 是否允许第一阶段引入 SSCD tile embedding 作为默认候选召回，还是先用 dHash/tile hash 保持轻依赖？
3. Phase 1 是否必须支持 Web Gallery，还是 CLI/HTML report 先行？
4. 是否把 MONet/BioFors adapter 作为明确 Phase 3 目标，还是仅保持 research spike？
5. Overlap findings 的默认最高风险是否限制为 `high`，不直接输出 `critical`？

## 14. 外部参考

- BioFors: A Large Biomedical Image Forensics Dataset. Defines biomedical external duplication, internal duplication, and cut/sharp-transition tasks, and notes that general natural-image forensics is not robust enough for biomedical images. https://arxiv.org/abs/2108.12961
- MONet: Multi-scale Overlap Network for Duplication Detection in Biomedical Images. Targets duplicated regions between biomedical images with multi-scale overlap detection. https://arxiv.org/abs/2207.09107
- A Self-Supervised Descriptor for Image Copy Detection. SSCD provides compact descriptors useful for image copy retrieval and candidate search. https://arxiv.org/abs/2202.10261
- TruFor: Leveraging all-round clues for trustworthy image forgery detection and localization. Provides localization map, image-level integrity score, and reliability map for forged-region screening. https://arxiv.org/abs/2212.10957
- ImageJ Coloc 2 documentation. Documents Pearson/Manders/Costes colocalization methods and common pitfalls such as ROI, background, noise, and bleed-through. https://imagej.net/plugins/coloc-2
