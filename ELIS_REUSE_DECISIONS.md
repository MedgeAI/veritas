# ELIS `system_modules` 可复用点梳理

> 生成日期：2026-06-15
> 决策完成：2026-06-15（grill-me 会话）
> 约束来源：`AGENTS.md` § 当前内测增强路线 + § 第三方仓库使用原则

---

## 战略约束（已决策）

| # | 决策维度 | 选择 | 推论 |
|---|---|---|---|
| Q1 | 内测时间窗口 | **B: 2-3 周** | P0 最多 4 个模块 |
| Q2 | GPU 环境 | **C: 无 GPU，重型模型 skip 写 limitations** | TruFor/YOLOv5 内测只能验证 pipeline 集成；keypoint 增强是唯一能真实验证视觉价值的 P0 模块 |
| Q3 | 许可证容忍度 | **A: 内部工具，不开源** | 所有 ELIS 模块可碰；AGPL-3.0 传染性在不开源场景下不触发 |

---

## 当前 Veritas 视觉取证能力基线

| tool_id | 实现位置 | 算法 | 局限 |
|---|---|---|---|
| `image.exact_duplicates` | 字节哈希 | 只能检测完全相同的文件 |
| `image.similarity_candidates` | `engine/static_audit/tools/image_similarity.py` | dHash 64bit 全局感知哈希 | 裁剪/旋转/对比度调整均无法检测 |
| `visual.panel_extraction` | `engine/static_audit/tools/panel_extraction.py` | OpenCV Canny + 轮廓边缘检测 | 无 panel 分类能力；复杂布局易失败；**将被删除** |
| `visual.copy_move` | `engine/static_audit/tools/copy_move_detection.py` | ORB/SIFT + BFMatcher + RANSAC | 无翻转检测；精度低；**ORB 路径将被删除** |
| `visual.finding_pipeline` | `engine/static_audit/tools/visual_finding_pipeline.py` | 聚合 relationships → findings → clusters → review queue | 已有完整 pipeline，新模块只需接入 relationship 输出 |

**TruFor（深度学习伪造检测）和跨论文 CBIR 检索当前完全空白。**

---

## 一、P0 已决策模块

### 1. `panel-extractor` — YOLOv5 panel 检测 + 分类 ✅ 接入

- **位置**：`third_party/elis/system_modules/panel-extractor/`
- **决策**：
  - ✅ **接入**，优先级 P0 第 1 位
  - ✅ **YOLOv5 完全替换 OpenCV**，删除 OpenCV panel 提取代码（Q6=A，OpenCV 效果差，不保留 fallback）
  - ✅ `PanelEvidence` schema 增加 `panel_type` 字段
  - ✅ **全部重写测试**，用 YOLOv5 真实行为生成 golden fixture（Q8=A）
- **落地**：
  - 重写 `engine/static_audit/tools/panel_extraction.py`，内部调 YOLOv5 `extract.run()`
  - `PanelEvidence` 增加 `panel_type: Optional[str]`（enum: `blots` / `graphs` / `microscopy` / `body_imagery` / `flow_cytometry` / `unknown`）
  - 删除 OpenCV Canny/contour/filter_contours 代码
  - 删除/重写 `tests/unit/test_panel_extraction.py` 和 `tests/unit/test_visual_fixtures.py` 中绑定 OpenCV 行为的测试

### 2. `copy-move-detection-keypoint` — RootSIFT + MAGSAC++ ✅ 接入

- **位置**：`third_party/elis/system_modules/copy-move-detection-keypoint/`
- **决策**：
  - ✅ **接入**，优先级 P0 第 2 位
  - ✅ **升级默认**：默认 method 改为 RootSIFT+MAGSAC++
  - ✅ **直接删除 ORB 代码路径**，不保留 deprecated（Q4=C → Q11=D）
  - ✅ `image_relationship` schema 增加 `flip_detected: bool` 字段
- **落地**：
  - 重写 `engine/static_audit/tools/copy_move_detection.py`，内部调 ELIS keypoint 模块
  - 删除 `_detect_keypoints_descriptors` 中 ORB 分支和 `_match_descriptors` 中 BFMatcher 逻辑
  - `param_schema` 的 `method` enum 删除 `"orb"`
  - registry 默认 `method` 改为 `"rootsift_magsac"`
  - 增加 `flip_detected` 到 `image_relationship` schema 和 `visual_finding_pipeline`

### 3. `copy-move-detection` (SILA) — 非 keypoint 方法 ✅ 接入

- **位置**：`third_party/elis/system_modules/copy-move-detection/`
- **决策**：
  - ✅ **接入**，优先级 P0 第 3 位（Q7=A）
  - ✅ 与 keypoint 版一起进入 P0
- **落地**：
  - 新增 `engine/static_audit/tools/copy_move_dense.py`
  - registry 注册 `tool_id="visual.copy_move_dense"`，`agent_selectable=True`
  - 输出 relationship 格式与 `visual.copy_move` 对齐
  - `visual_finding_pipeline` 增加对 dense 方法 relationship 的归一化消费

### 4. `TruFor` — 深度学习伪造检测 ✅ 接入（skip-only）

- **位置**：`third_party/elis/system_modules/TruFor/`
- **决策**：
  - ✅ **接入**，优先级 P0 第 4 位（最后）
  - ✅ **无 GPU 直接 skip 写入 limitations**，不实际跑推理（Q5=A）
  - ✅ 只写 adapter + 注册 tool_id + pipeline 集成
- **落地**：
  - 新增 `engine/static_audit/tools/tru_for.py`
  - registry 注册 `tool_id="visual.tru_for"`，`agent_selectable=True`
  - adapter 检测 GPU 可用性：无 GPU → 返回 `_empty_result("not_available", ...)`
  - 输出 schema 预留 `forged_region_evidence`（localization_map_path / integrity_score / reliability_map_path）
  - `visual_finding_pipeline` 增加对 `forged_region_evidence` 的归一化消费
  - 内测验证目标：schema 正确、registry 可发现、pipeline 能消费空结果、limitations 正确写入

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
| **GPU 策略** | 无 GPU 时 TruFor skip 写入 limitations；YOLOv5 / RootSIFT 为传统 CV，CPU 可跑 |
| **许可证** | Veritas 不开源（内部工具），AGPL-3.0 传染性不触发；可安全使用所有 ELIS 模块 |
| **模型权重管理** | `make download-models` Makefile target（Q10=D），与 `make sync` 分离 |
| **失败隔离** | 重型工具失败写入 manifest + `investigation_rounds.jsonl` + 报告 limitations，不阻塞 happy path |
| **测试策略** | 全部重写 golden fixture，绑定新实现的真实行为（Q8=A） |

---

## 六、落地顺序与任务清单

落地顺序：**先 YOLOv5 → 再 keypoint/SILA → 最后 TruFor**（Q9=A）。

理由：YOLOv5 改变 `PanelEvidence` schema（加 `panel_type`），下游 copy-move 和 finding pipeline 都要适配。先稳定 schema，一次改到位，避免返工。

### Phase 1: YOLOv5 Panel Extraction

- [ ] 1.1 阅读 `third_party/elis/system_modules/panel-extractor/` 源码，确认 Python API 和输出格式
- [ ] 1.2 `scripts/download_models.sh` → 改为 `Makefile` target `download-models`
- [ ] 1.3 `PanelEvidence` schema 增加 `panel_type: Optional[str]` 字段（更新 `visual_schemas.py`）
- [ ] 1.4 重写 `engine/static_audit/tools/panel_extraction.py`，内部调 YOLOv5
- [ ] 1.5 删除 OpenCV Canny/contour/filter_contours 代码
- [ ] 1.6 重写 `tests/unit/test_panel_extraction.py` 和 `tests/unit/test_visual_fixtures.py`
- [ ] 1.7 适配下游：`copy_move_detection.py` 和 `visual_finding_pipeline.py` 适配新 `PanelEvidence`
- [ ] 1.8 验证：`make test` 全部通过

### Phase 2: Keypoint Copy-Move 增强

- [ ] 2.1 阅读 `third_party/elis/system_modules/copy-move-detection-keypoint/` 源码，确认 RootSIFT+MAGSAC++ API
- [ ] 2.2 重写 `engine/static_audit/tools/copy_move_detection.py`
- [ ] 2.3 删除 ORB/BFMatcher/RANSAC 代码路径
- [ ] 2.4 `image_relationship` schema 增加 `flip_detected: bool`
- [ ] 2.5 registry 更新：`method` enum 删除 `"orb"`，默认改为 `"rootsift_magsac"`
- [ ] 2.6 重写 `tests/unit/test_copy_move_detection.py`
- [ ] 2.7 `visual_finding_pipeline.py` 适配 `flip_detected` 字段
- [ ] 2.8 验证：`make test` 全部通过

### Phase 3: SILA Dense Copy-Move

- [ ] 3.1 阅读 `third_party/elis/system_modules/copy-move-detection/` 源码，确认 Zernike/PCT/FMT API
- [ ] 3.2 新增 `engine/static_audit/tools/copy_move_dense.py`
- [ ] 3.3 registry 注册 `tool_id="visual.copy_move_dense"`
- [ ] 3.4 `visual_finding_pipeline.py` 增加 dense relationship 归一化
- [ ] 3.5 新增 `tests/unit/test_copy_move_dense.py`
- [ ] 3.6 验证：`make test` 全部通过

### Phase 4: TruFor Adapter (skip-only)

- [ ] 4.1 阅读 `third_party/elis/system_modules/TruFor/` 源码，确认推理 API 和输出格式
- [ ] 4.2 `forged_region_evidence` schema 设计（`visual_schemas.py`）
- [ ] 4.3 新增 `engine/static_audit/tools/tru_for.py`（adapter + GPU 检测 + skip 语义）
- [ ] 4.4 registry 注册 `tool_id="visual.tru_for"`，`agent_selectable=True`
- [ ] 4.5 `visual_finding_pipeline.py` 增加 `forged_region_evidence` 归一化
- [ ] 4.6 新增 `tests/unit/test_tru_for.py`（验证 skip 语义和空结果 schema）
- [ ] 4.7 验证：`make test` 全部通过；`make audit` 跑通 happy path，TruFor 写入 limitations

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
