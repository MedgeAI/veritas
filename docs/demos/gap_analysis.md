# Veritas 原型差距分析（v2 — 基于 codegraph 代码探索更新）

> 对照来源：`veritas_prototype.html`（6 页交互原型）+ `QA.md`（产品设计对话录）
> 探索工具：codegraph MCP（894 文件 / 13322 节点 / 25439 边）
> 分析日期：2026-06-27
> **状态：核心引擎已落地，前端存在 2 个运行时 bug + 多处视觉断裂**

---

## 一、当前代码状态：引擎完备，前端有断裂

### 1.1 引擎层（完备）

| 能力 | 文件 | 状态 |
|---|---|---|
| 认证等级 A/B/C/D + 4 维度 | `grade_engine.py:272` compute_grade | ✅ 完备，`_pipeline_steps.py` 已调用 |
| 三层确定性 fact/inference/suggestion | `certainty_enrichment.py:96` enrich_certainty_layers | ✅ 完备，pipeline 集成 |
| 报告编号 VRT-YYYYMM-XXXXXX | `report_id.py:13` generate_report_id | ✅ 完备 |
| 公开验证存储 | `verify_store.py:42` save_verification_summary | ✅ 完备，含版本历史 |
| HTML 报告等级章 + 4 维度 | `html_report/_core.py:358-360` grade_badge + dimension_summary | ✅ 已接通 |
| HTML 报告三层确定性 | `html_report/_core.py:326-328` _build_certainty_index + _merge_certainty_layers | ✅ 已合并 |
| 作者/把关者 CSS 类 | `html_report/_core.py:373` data-view + .author-only/.gatekeeper-only | ✅ 完备 |

### 1.2 后端 API（完备）

| 端点 | 路由文件 | 状态 |
|---|---|---|
| `/api/verify/{report_id}` | `routers/verify.py:37` | ✅ 公开，无需 auth |
| `/api/verify?q=...` | `routers/verify.py:79` | ✅ 查询式验证 |
| `/api/cases/{id}/risk-summary` | `routers/cases.py` | ✅ 含 follow_ups |
| `/api/cases/{id}/artifacts/certainty_data` | `routers/artifacts.py` | ✅ 通过 KNOWN_ARTIFACTS |
| `/api/cases/{id}/report/html` | `routers/artifacts.py:46` | ✅ |

### 1.3 前端页面（存在 bug）

| 页面 | 状态 | 问题 |
|---|---|---|
| MissionControlPage | ✅ GradeBadge 已集成 | — |
| ReportCenterPage | ✅ GradeBadge + VersionHistorySection + ViewModeToggle | ⚠️ VersionHistorySection 使用 `accent-*` 颜色（未定义） |
| FindingsPage | ✅ CertaintyLayers 组件已集成 | — |
| VerifyPage | ✅ 公开路由，功能完整 | 🔴 使用 Tailwind 默认灰色（`bg-gray-50`/`bg-blue-600`），品牌断裂 |
| ReverificationPage | ✅ 版本链路 + 费用 UI | 🔴 `getVersionHistory` import 不存在于 api.js（运行时崩溃） |
| CasesPage (Dashboard) | ✅ 看板 + 统计卡片 + 风险分布 | ⚠️ 无等级分布，CaseCard 无 GradeBadge |
| NewAuditPage | ✅ ReproducibilityTierPicker | — |
| EvidenceReviewPage | ✅ 图像取证画廊 | ⚠️ OverlapDetailDrawer 使用灰色调 |

### 1.4 已确认的运行时 Bug

| # | Bug | 位置 | 严重度 |
|---|---|---|---|
| **BUG-1** | `accent` 颜色未在 `tailwind.config.js` 定义 | GradeBadge.jsx:10,42 + ReverificationPage.jsx:59,92,102 + VersionHistorySection | 🔴 B 级徽章不可见 |
| **BUG-2** | `getVersionHistory` 未在 `api.js` 导出 | ReverificationPage.jsx:3 import | 🔴 页面加载即报错 |
| **BUG-3** | VerifyPage 使用 Tailwind 默认灰色 | VerifyPage.jsx 全文 | 🟡 品牌不一致 |
| **BUG-4** | CasesPage 统计卡片英文标签 | CasesPage.jsx:190,203,218,229 | 🟢 中英文混用 |

---

## 二、原型功能落地状态

| 原型概念 | 引擎/后端 | 前端展示 | 数据链路 | 状态 |
|---|---|---|---|---|
| **认证等级 A/B/C/D** + 4 维度 | ✅ grade_engine.py | ⚠️ GradeBadge 存在但 accent 色缺失 | ⚠️ 部分断裂 | **需修 BUG-1** |
| **复现等级** Full/Partial/Code-only/Static | ✅ grade_engine tier cap | ✅ ReproducibilityTierPicker | ✅ 全通 | ✅ |
| **三层确定性** Fact/Inference/Suggestion | ✅ certainty_enrichment.py | ✅ CertaintyLayers (FindingsPage) + HTML 报告 | ✅ 全通 | ✅ |
| **公开验证** | ✅ verify_store + /api/verify | 🔴 VerifyPage 功能 OK 但品牌断裂 | ✅ 数据通 | **需修 BUG-3** |
| **作者/把关者视图** | ✅ HTML CSS 类 | ✅ ViewModeToggle | ✅ 全通 | ✅ |
| **版本链路** v1→v2 | ✅ case.report_version + parent_report_id | 🔴 VersionHistorySection + ReverificationPage 都依赖 accent 色 + getVersionHistory | 🔴 断裂 | **需修 BUG-1,2** |
| **重核页面** | ✅ pipeline 支持 | 🔴 支付纯 mock + BUG-2 | 🔴 断裂 | **需修 BUG-2** |
| **HTML 报告重设计** | ✅ 等级章 + 维度 + 三层 + 视图切换 | ✅ iframe 嵌入 | ✅ 全通 | ✅ |
| **7 步流程** | ⚠️ pipeline 步骤名不同 | ⚠️ ProgressTracker 显示步骤 | ⚠️ 映射不完整 | **需映射** |

---

## 三、剩余差距（按 ROI 排序）

### 3.1 P0 — 运行时崩溃修复（0.5 天）

| 改进项 | 说明 |
|---|---|
| 定义 `accent` 色板 | tailwind.config.js 新增 accent 颜色（与 signal 对齐） |
| 新增 `getVersionHistory` API | api.js + 后端 `/cases/{id}/version-history` 端点 |

### 3.2 P1 — 高 ROI 展示增强（1-2 天）

| 改进项 | 说明 |
|---|---|
| Dashboard 等级分布 | CasesPage 统计卡片增加 A/B/C/D 分布 |
| CaseCard 等级徽章 | 每个 case 卡片展示 GradeBadgeCompact |
| VerifyPage 品牌化 | 灰 → paper/ink/signal 色板替换 |
| CasesPage 中文化 | "Total Cases" → "审查总数" 等 |

### 3.3 P2 — 视觉精修（3-5 天）

| 改进项 | 说明 |
|---|---|
| HTML 报告 Hero 重构 | 报告编号 + 等级章为视觉焦点（参照原型"正式文件"） |
| OverlapDetailDrawer/Graph 色板统一 | gray → paper/ink |
| 7 步流程名称映射 | 在 ProgressTracker 中显示原型定义的 7 步名称 |
| ReverificationPage 支付真实化 | 接后端 API 替代 console.log |

### 3.4 P3 — 暂缓

| 改进项 | 理由 |
|---|---|
| 付费体系 UI | 内部工具阶段不需要 |
| 数据安全级别 | 内部工具暂不需要 |
| 视觉风格全面重做 | 当前 Fraunces + 纸张色已接近方向 |

---

## 四、结论

**引擎层完备，前端存在 2 个阻塞性 bug + 品牌一致性问题。**

修复 BUG-1（accent 色板）和 BUG-2（getVersionHistory）后，原型核心功能即可全链路贯通。之后按 P1 → P2 优先级推进 Dashboard 增强和 VerifyPage 品牌化，可在 1 周内达到 Demo 可演示状态。
