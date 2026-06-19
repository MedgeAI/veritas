# ELIS `system_modules` 可复用点梳理

> 生成日期：2026-06-15
> 更新校准：2026-06-18（P0 模块已全部落地）
> 约束来源：`AGENTS.md` § 当前内测增强路线 + § 第三方仓库使用原则

> 状态校准：P0 四个模块（YOLOv5 panel-extractor、RootSIFT+MAGSAC++ copy-move、SILA dense、TruFor skip-only）已全部集成到主链路。本文档记录历史决策和 P1 后续规划。

---

## 战略约束（已决策）

| # | 决策维度 | 选择 | 推论 |
|---|---|---|---|
| Q1 | 内测时间窗口 | **B: 2-3 周** | P0 最多 4 个模块 |
| Q2 | GPU 环境 | **C: 无 GPU，重型模型 skip 写 limitations** | TruFor/YOLOv5 内测只能验证 pipeline 集成；keypoint 增强是唯一能真实验证视觉价值的 P0 模块 |
| Q3 | 许可证容忍度 | **A: 内部工具，不开源** | 所有 ELIS 模块可碰；AGPL-3.0 传染性在不开源场景下不触发 |

---

## 当前 Veritas 视觉取证能力基线（P0 已落地）

| tool_id | 实现位置 | 算法 | 状态 |
|---|---|---|---|
| `visual.panel_extraction` | `engine/static_audit/tools/panel_extraction.py` | YOLOv5（ELIS panel-extractor） | ✅ 已替换 OpenCV |
| `visual.copy_move` | `engine/static_audit/tools/copy_move_detection.py` | RootSIFT + MAGSAC++（ELIS keypoint） | ✅ 已替换 ORB/BFMatcher |
| `visual.copy_move_dense` | `engine/static_audit/tools/sila_dense.py` | SILA Zernike/PCT/FMT（Docker） | ✅ 已接入 |
| `visual.tru_for` | `engine/static_audit/tools/tru_for.py` | SegFormer-B2 + Noiseprint++ | ✅ skip-only 已接入 |
| `visual.overlap_reuse` | `engine/static_audit/tools/overlap_reuse.py` | Tile-level dHash + RootSIFT+MAGSAC++ | ✅ P1 新增 |
| `visual.provenance_graph` | `engine/static_audit/tools/provenance_graph.py` | SSCD + RootSIFT+MAGSAC++ | ✅ 已接入 |
| `visual.image_quality` | `engine/static_audit/tools/image_quality.py` | 像素统计异常检测 | ✅ 已接入 |
| `image.exact_duplicates` | 字节哈希 | 完全相同文件检测 | ✅ baseline |
| `image.similarity_candidates` | `engine/static_audit/tools/image_similarity.py` | dHash 64bit 全局感知哈希 | ✅ agent-selectable |
| `visual.finding_pipeline` | `engine/static_audit/tools/visual_finding_pipeline.py` | 聚合 relationships → findings → clusters → review queue | ✅ 已接入 overlap_reuse |

---

## 一、P0 已完成模块

### 1. `panel-extractor` — YOLOv5 panel 检测 + 分类 ✅ 已落地

- **位置**：`third_party/elis/system_modules/panel-extractor/`
- **状态**：✅ 已集成。`panel_extraction.py` 通过 subprocess 调用 YOLOv5，`PanelEvidence` 含 `panel_type` 字段。
- **历史决策**：YOLOv5 完全替换 OpenCV（Q6=A）；全部重写测试。

### 2. `copy-move-detection-keypoint` — RootSIFT + MAGSAC++ ✅ 已落地

- **位置**：`third_party/elis/system_modules/copy-move-detection-keypoint/`
- **状态**：✅ 已集成。`copy_move_detection.py` 通过 `_elis_copy_move_runner` 调用。ORB 代码路径已删除，`flip_detected` 字段已加入 schema。
- **历史决策**：默认 method 改为 `rootsift_magsac`；直接删除 ORB 代码路径。

### 3. `copy-move-detection` (SILA) — 非 keypoint 方法 ✅ 已落地

- **位置**：`third_party/elis/system_modules/copy-move-detection/`
- **状态**：✅ 已集成。`sila_dense.py` 通过 Docker 运行。`visual.copy_move_dense` tool_id 已注册。

### 4. `TruFor` — 深度学习伪造检测 ✅ 已落地（skip-only）

- **位置**：`third_party/elis/system_modules/TruFor/`
- **状态**：✅ 已集成。`tru_for.py` 检测 GPU 可用性，无 GPU 时 skip 写入 limitations。`forged_region_evidence` schema 已实现。

---

## 二、P1 候选（内测后增强，未决策）

### 5. `cbir-system` — SSCD + Milvus 向量检索

- **位置**：`third_party/elis/system_modules/cbir-system/`
- **能力**：SSCD 自监督特征提取 + Milvus 向量数据库；支持**跨论文**检索
- **当前差距**：dHash 无法检测裁剪/旋转/对比度调整；无法跨论文检索
- **依赖**：Docker Compose（etcd + MinIO + Milvus + CBIR API + Attu）
- **待决策**：是否接入 / Docker 部署接受度 / 跨论文检索是否在当前产品范围

### 6. `provenance-analysis` — 溯源图构建

- **位置**：`third_party/elis/system_modules/provenance-analysis/`
- **能力**：G2NN 匹配 + MAGSAC++ + 溯源图（MST + 连通分量）
- **当前差距**：Veritas 只产出 pairwise relationships，没有溯源图
- **待决策**：是否接入 / 是否依赖 CBIR / 溯源图是否进入 HTML 报告

### 7. `pdf-image-extraction` — PyMuPDF 图像提取

- **位置**：`third_party/elis/system_modules/pdf-image-extraction/`
- **能力**：三种提取模式（safe/normal/unsafe）；损坏 PDF 处理；去重/去单色
- **当前差距**：MinerU 失败时无 fallback
- **待决策**：是否作为 MinerU 的 fallback / 是否需要独立 tool_id

---

## 三、基础设施复用（未决策）

### 8. `elis-frontend` — Vite / React / Tailwind

- **位置**：`third_party/elis/system_modules/elis-frontend/`
- **复用点**：AGENTS.md 已明确"前端基础设施复用 ELIS 的 Vite/React/Tailwind 模式"
- **待决策**：当前 `web/frontend/` 是否已经复用？需要补哪些组件/布局？

---

## 四、不做

### 9. `watermark-removal` — 撤稿水印去除 ❌

- **位置**：`third_party/elis/system_modules/watermark-removal/`
- **决策**：暂不接入。属于取证后预处理，不是核心审计能力。

---

## 五、跨模块共性决策

| 维度 | 决策 |
|---|---|
| **GPU 策略** | 无 GPU 时 TruFor skip 写入 limitations；YOLOv5 可先 CPU/GPU 验证但不承诺性能；RootSIFT/MAGSAC 和 dense copy-move 优先 CPU 可跑路径 |
| **许可证** | Veritas 不开源（内部工具），AGPL-3.0 传染性不触发；可安全使用所有 ELIS 模块 |
| **模型权重管理** | `make download-models` Makefile target（Q10=D），与 `make sync` 分离 |
| **失败隔离** | 重型工具失败写入 manifest + `investigation_rounds.jsonl` + 报告 limitations，不阻塞 happy path |
| **测试策略** | 全部重写 golden fixture，绑定新实现的真实行为（Q8=A） |

---

## 六、落地顺序（P0 全部完成）

P0 落地顺序：**先补 visual v1 golden/失败隔离测试 → YOLOv5 → keypoint/SILA → TruFor skip-only**。

所有 P0 Phase 1-4 任务已全部完成（2026-06-18 校准）。

### Phase 1: YOLOv5 Panel Extraction ✅

- [x] 1.1 阅读 ELIS panel-extractor 源码
- [x] 1.2 Makefile target `download-models`
- [x] 1.3 `PanelEvidence` 增加 `panel_type` 字段
- [x] 1.4 重写 `panel_extraction.py` 调 YOLOv5
- [x] 1.5 删除 OpenCV 代码
- [x] 1.6 重写测试
- [x] 1.7 适配下游
- [x] 1.8 `make test` 通过

### Phase 2: Keypoint Copy-Move 增强 ✅

- [x] 2.1-2.8 全部完成

### Phase 3: SILA Dense Copy-Move ✅

- [x] 3.1-3.6 全部完成

### Phase 4: TruFor Adapter (skip-only) ✅

- [x] 4.1-4.7 全部完成

---

## 七、标准接入路径

```
third_party/elis/system_modules/<module>/
  ↓ (adapter 包装)
engine/static_audit/tools/<module_name>.py
  ↓ (registry 注册)
engine/tools/registry.py  →  tool_id / param_schema / output_artifacts
  ↓ (orchestrator 执行)
workdir/investigation/<output>.json
  ↓ (pipeline 消费)
visual_finding_pipeline → visual_findings → HTML report
  ↓
manifest + investigation_rounds.jsonl + limitations
```
