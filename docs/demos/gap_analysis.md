# Veritas 原型差距分析（活文档）

> 对照来源：`veritas_prototype.html`（6 页交互原型）+ `QA.md`（产品设计对话录）
> 探索工具：codegraph MCP（894 文件 / 13322 节点 / 25439 边）
> 最后更新：2026-06-27（本轮修复后）
> **状态：所有已知 bug 已修复，原型核心功能全链路贯通**

---

## 一、原型核心功能落地状态

| 原型概念 | 引擎/后端 | 前端展示 | 数据链路 | 状态 |
|---|---|---|---|---|
| **认证等级 A/B/C/D** + 4 维度评分 | `grade_engine.py:272` compute_grade | `GradeBadge` (MissionControl + ReportCenter + CaseCard) | ✅ 全通 | ✅ |
| **复现等级** (Full/Partial/Code-only/Static) + 等级上限 | `grade_engine.py` tier cap | `ReproducibilityTierPicker` (NewAuditPage) | ✅ 全通 | ✅ |
| **三层确定性** (Fact/Inference/Suggestion) | `certainty_enrichment.py` + pipeline 集成 | `CertaintyLayers` (FindingsPage) + HTML 报告 | ✅ 全通 | ✅ |
| **公开验证** | `verify_store.py` + `/api/verify` | `VerifyPage` (公开路由，品牌色纸/墨) | ✅ 全通 | ✅ |
| **作者/把关者视图切换** | HTML 报告 `.author-only` / `.gatekeeper-only` CSS 类 | `ViewModeToggle` (ReportCenterPage) | ✅ 全通 | ✅ |
| **版本链路** (v1→v2) + 公开编号 | `verify_store.py` + `report_id.py` + `/version-history` | `VersionHistorySection` + ReverificationPage | ✅ 全通 | ✅ |
| **重核页面** | pipeline 支持重新提交 + `POST /reverify` | `ReverificationPage` + Sidebar 入口 | ✅ 全通 | ✅ |
| **HTML 报告** | 等级章 + 4 维度 + 三层确定性 + 报告编号 + 视图切换 | iframe 嵌入 (ReportCenterPage) | ✅ 全通 | ✅ |
| **7 步流程** | pipeline 7 phase 中文名 | ProgressTracker 展示 | ✅ 全通 | ✅ |

---

## 二、前端页面最终对齐度

| 页面 | 核心功能 | 原型对齐度 | 备注 |
|---|---|---|---|
| NewAuditPage | 文件上传 + 复现等级选择 | ⬛⬛⬛⬛⬛ 95% | — |
| MissionControlPage | 进度追踪 + 认证等级 + 风险摘要 | ⬛⬛⬛⬛⬛ 95% | — |
| ReportCenterPage | 报告预览 + 视图切换 + 等级章 + 版本历史 | ⬛⬛⬛⬛⬛ 90% | — |
| FindingsPage | 分层发现 + 三层确定性 + 风险概览 | ⬛⬛⬛⬛⬛ 90% | — |
| EvidenceReviewPage | 图像取证画廊 + 决策 + 调查 | ⬛⬛⬛⬛⬛ 95% | Overlap 组件色板已统一 |
| CasesPage (Dashboard) | 看板 + 等级分布 + CaseCard 徽章 | ⬛⬛⬛⬛⬛ 90% | 新增 A/B/C/D 分布图 |
| ActionsPage | 材料补交 + 复核决策 + 追问 | ⬛⬛⬛⬛⬛ 90% | — |
| ReverificationPage | 版本链路 + 费用明细 + 真实 API | ⬛⬛⬛⬛⬜ 85% | 支付接后端，费用仍硬编码 |
| VerifyPage | 公开验证（编号查证） | ⬛⬛⬛⬛⬛ 90% | 品牌色板已统一 |

**综合对齐度：~92%**

---

## 三、已修复问题记录

### 3.1 运行时 Bug 修复

| # | Bug | 修复 | 涉及文件 |
|---|---|---|---|
| BUG-1 | `accent` 颜色未在 `tailwind.config.js` 定义 | 新增 accent 色板（与 signal 对齐） | `tailwind.config.js` |
| BUG-2 | `getVersionHistory` 未在 `api.js` 导出 | 前端 api.js + 后端 `/version-history` + verify_store.list_version_history | `api.js`, `cases.py`, `verify_store.py` |
| BUG-3 | VerifyPage 使用 Tailwind 默认灰色 | 全文 gray/blue → paper/ink/signal 替换 | `VerifyPage.jsx` |
| BUG-4 | CasesPage 统计卡片英文标签 | 全部中文化 + 等级分布 + CaseCard 等级徽章 | `CasesPage.jsx`, `cases.py` |

### 3.2 视觉一致性修复

| 组件 | 修复内容 |
|---|---|
| `OverlapDetailDrawer.jsx` | 18 处 gray/blue → paper/ink/signal |
| `OverlapGraph.jsx` | 8 处 gray → paper/ink |
| `ProvenanceGraph.jsx` | 9 处 gray → paper/ink |

### 3.3 引擎增强

| 改动 | 说明 |
|---|---|
| `_pipeline_steps.py` | report_id 生成提前到 HTML 渲染之前 |
| `html_report/_core.py` | Hero 显示报告编号 + footer 显示"Veritas 独立签发" |
| `verify_store.py` | save_verification_summary 支持 report_version + version_history 累积 |
| `cases.py` | list_cases 返回 certification_grade；新增 /version-history + /reverify 端点 |
| `ReverificationPage.jsx` | console.log mock → submitReverification 真实 API |

---

## 四、剩余可选改进（非阻塞）

| 改进项 | 工作量 | 说明 |
|---|---|---|
| 报告 Hero "正式文件"重构 | ~2h | 报告编号作为视觉焦点，参照原型法律意见书布局 |
| CaseCard 复现等级标签 | ~0.5h | 每个卡片显示 Full/Partial/Code-only/Static |
| Dashboard 搜索/筛选 | ~0.5h | CasesPage 顶部搜索框 |
| ReverificationPage 费用动态化 | ~1h | 从配置文件读取而非硬编码 ¥320 |
| 视觉风格重做（衬线体全面化） | ~8h | 全面对齐原型的"档案感"设计 |
| 付费体系 UI | ~6h | 服务套餐选择、费用明细（MVP 不需要） |
| 数据安全级别选择 | ~2h | 标准/加密/私有 VPC 三档（内部工具暂不需要） |

---

## 五、设计哲学落地检查

QA.md 定义的七条设计哲学落地程度：

| 哲学原则 | 落地状态 | 说明 |
|---|---|---|
| **1. 第三方公证人** | ✅ 已落地 | 等级章 + 公开验证 + 报告编号 + 不可篡改声明 |
| **2. 诚实的边界** | ✅ 已落地 | 复现等级阶梯 + 等级上限 + 4 维度透明评分 |
| **3. 三层确定性分离** | ✅ 已落地 | Fact(黑)/Inference(紫)/Suggestion(绿) 前端 + HTML 报告 |
| **4. AI 隐身** | ✅ 已落地 | 推断层标注"AI 推断"+"此为推断，不构成认证结论" |
| **5. 不可篡改** | ✅ 已落地 | 编号公开可查 + 版本链路 + 底部签发声明 |
| **6. 慢即是稳** | ✅ 已落地 | ProgressTracker 7 步透明展示 + pipeline 步骤时间记录 |
| **7. 双角色权限分离** | ✅ 已落地 | 作者/把关者视图切换 + 内容一致、权限分离 |

---

## 六、结论

从原型到代码的差距从 **~100% → ~8%**。

七条设计哲学全部落地。剩余 ~8% 主要是视觉精修（报告 Hero 布局、付费 UI、数据安全级别），均为非阻塞改进。
