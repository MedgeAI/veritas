# Veritas 下一步行动计划 PRD

> 基于 codegraph 代码探索（894 文件 / 13322 节点）+ 原型差距分析
> 日期：2026-06-27
> 前置文档：`gap_analysis.md`（v2）、`ui_ux_redesign_plan.md`、`QA.md`

---

## 〇、执行摘要

**核心发现**：引擎层已完备（等级引擎、三层确定性、公开验证、HTML 报告），但前端存在 **2 个运行时崩溃 bug** 和 **多处视觉断裂**。修复这些 bug 后，原型核心功能即可全链路贯通。

**行动路线**：
1. **Week 1**：修复崩溃 bug + 视觉统一 → Demo 可运行
2. **Week 2**：Dashboard 增强 + 报告精修 → Demo 可演示
3. **Week 3+**：战略级改造（七步映射、重核真实化）→ 按需推进

---

## 一、Phase 0：修复运行时崩溃（P0 · 0.5 天）

### 1.1 BUG-1：`accent` 颜色未定义

**现象**：GradeBadge B 级（`bg-accent-500`）、ReverificationPage（`bg-accent-100`/`text-accent-700`）、VersionHistorySection 全部引用了不存在的 `accent-*` Tailwind 类。这些元素在页面上不可见或样式异常。

**修复**：在 `web/frontend/tailwind.config.js` 的 `theme.extend.colors` 中新增：

```javascript
accent: {
  50:  '#eefbf6',
  100: '#d8efe8',
  200: '#b3dfd1',
  300: '#8fcdbc',
  400: '#5aab93',
  500: '#227863',  // = signal-500
  600: '#1e6b58',
  700: '#185847',  // = signal-700
},
```

**影响范围**（codegraph blast radius）：
- `GradeBadge.jsx:10,42` — B 级徽章 + pass_with_notes 维度标签
- `ReverificationPage.jsx:59,92,102,206` — 图标背景、版本链路高亮、订阅链接
- `ReportCenterPage.jsx:315` — VersionHistorySection 版本标签

**验证**：`npm run build` 无 warning + GradeBadge B 级显示 teal 色

### 1.2 BUG-2：`getVersionHistory` 不存在

**现象**：`ReverificationPage.jsx:3` import 了 `getVersionHistory`，但 `api.js` 中无此函数。页面加载时抛出 `TypeError: getVersionHistory is not a function`。

**修复**：

1. `web/frontend/src/services/api.js` 新增：
```javascript
export async function getVersionHistory(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/version-history`);
}
```

2. `web/backend/veritas_web/routers/cases.py` 新增端点：
```python
@router.get("/cases/{case_id}/version-history")
async def get_version_history(case_id: str, ...):
    """Return version history for a case (from verify_store)."""
    # 从 verify_store 读取该 case 的所有版本记录
    # 返回 { versions: [...], current_version: int }
```

3. `engine/static_audit/verify_store.py` 新增：
```python
def list_version_history(case_id: str, *, verify_dir=None) -> list[dict]:
    """List all verification versions for a case."""
```

**测试**：已有 `tests/unit/test_verify_store_version.py` 覆盖了 `list_version_history`。

**验证**：ReverificationPage 加载不报错 + 版本链路正确显示

---

## 二、Phase 1：高 ROI 展示增强（P1 · 1-2 天）

### 2.1 Dashboard 等级分布 + CaseCard 等级徽章

**目标**：老板打开 Dashboard 一眼看到"多少 A、多少 B、多少 C"——产品价值直观可见。

**改动**：

| 文件 | 改动 |
|---|---|
| `CasesPage.jsx` | stats 增加 gradeDist 统计 + 第 5 个统计卡片展示 A/B/C/D 分布 |
| `CasesPage.jsx` CaseCard | import GradeBadgeCompact，在 paper_title 旁显示等级 |
| `routers/cases.py` | list_cases 返回每个 case 的 certification_grade（从 run.summary 提取） |

**数据来源**：`run.summary.certification_grade` 已在 pipeline 完成后写入。cases API 只需在返回时关联 latest_run 的 grade 数据。

### 2.2 VerifyPage 品牌化

**目标**：VerifyPage 是外部用户（期刊编辑）的唯一触点。当前使用 Tailwind 默认灰色（`bg-gray-50`/`bg-blue-600`），与 Veritas 的纸张/墨色/信号绿设计语言完全脱节。

**改动**：全文色板替换：

| 当前（灰色） | 目标（品牌色） |
|---|---|
| `bg-gray-50` | `bg-paper-50` |
| `text-gray-900` | `text-ink-900` |
| `text-gray-600` | `text-ink-500` |
| `bg-blue-600` | `bg-signal-500` |
| `bg-blue-700` | `bg-signal-700` |
| `bg-green-500` | `bg-signal-500` |
| `bg-red-500` | `bg-risk-500` |
| `bg-green-100` | `bg-signal-100` |
| `bg-red-100` | `bg-risk-100` |
| `border-gray-200` | `border-ink-900/10` |
| `border-gray-300` | `border-ink-300` |
| `shadow-md` | `shadow-dossier` |
| `rounded-lg` / `rounded-md` | `rounded-2xl` / `rounded-xl` |

### 2.3 CasesPage 中文化

**改动**：

| 当前（英文） | 目标（中文） |
|---|---|
| `Total Cases` | `审查总数` |
| `Total Findings` | `发现总数` |
| `Critical / High` | `高风险` |
| `Running` | `进行中` |
| `cases at risk` | `个高风险 case` |

---

## 三、Phase 2：报告精修 + 视觉统一（P2 · 3-5 天）

### 3.1 HTML 报告 Hero 重构

**目标**：报告 Hero 区域从"信息堆砌"升级为"正式文件结构"——报告编号 + 等级章为视觉焦点。

**当前状态**（codegraph 确认）：`_core.py:375-409` 的 hero section 已有 grade_html 和 dimensions_html，但布局是纵向堆砌，缺少报告编号。

**改动**：

| 文件 | 改动 |
|---|---|
| `_executive.py` | hero 模板增加报告编号行（`VRT-YYYYMM-XXXXXX` mono 字体） |
| `_core.py` | 传递 report_id 到渲染上下文 |
| `_styles.py` | 新增 `.report-id` 样式（mono 字体、letter-spacing） |

### 3.2 视觉一致性修复

| 组件 | 问题 | 修复 |
|---|---|---|
| `OverlapDetailDrawer.jsx` | 使用 `bg-gray-50`/`border-gray-200` | → `bg-paper-100`/`border-ink-900/10` |
| `OverlapGraph.jsx` | SVG 容器 `bg-gray-50` | → `bg-paper-100` |
| `ProvenanceGraph.jsx` | SVG 容器 `bg-gray-50` | → `bg-paper-100` |

### 3.3 七步流程名称映射

**目标**：ProgressTracker 显示原型定义的 7 步名称（环境→数据→静态→执行→数字→方法学→解读），而非当前的 pipeline 技术步骤名。

**改动**：

| 文件 | 改动 |
|---|---|
| `engine/static_audit/step_labels.py` | 新增 `SEVEN_STEP_MAPPING` 将 pipeline key 映射到七步中文名 |
| `web/frontend/src/components/ProgressTracker.jsx` | 使用映射后的名称显示 |

---

## 四、Phase 3：重核真实化（P2 · 2 天）

### 4.1 ReverificationPage 支付对接后端

**目标**：替换 `console.log` mock，对接真实 API。

**改动**：

| 文件 | 改动 |
|---|---|
| `routers/cases.py` | 新增 `POST /cases/{id}/reverify` 端点 |
| `api.js` | 新增 `submitReverification(caseId, payload)` |
| `ReverificationPage.jsx` | `handleConfirm` 调用真实 API |

### 4.2 增量审计（MVP）

MVP 阶段不需要真正的 diff-based 增量。简单实现：
1. 创建新 case（`report_version = old + 1`，`parent_report_id = old_report_id`）
2. 重新跑完整 audit
3. 报告中注明"v2 修订版"

---

## 五、不做清单（明确排除）

| 不做 | 理由 |
|---|---|
| 付费体系 UI | 内部工具阶段，无外部用户 |
| 数据安全级别选择 | 内部工具暂不需要 |
| Dark mode | 纸张/档案感设计不适合暗色 |
| 键盘快捷键 / Command Palette | Demo 阶段 ROI 不够 |
| 像素级对齐原型 | 原型是方向指引，不是像素稿 |

---

## 六、执行时间表

```
Week 1 (P0+P1 — 修复 + 增强):
  Day 1:   Phase 0 (accent 色板 + getVersionHistory API)
  Day 2-3: Phase 1 (Dashboard 等级分布 + VerifyPage 品牌化 + CasesPage 中文化)

Week 2 (P2 — 精修):
  Day 1-2: Phase 2.1-2.2 (报告 Hero 重构 + 视觉一致性)
  Day 3-4: Phase 2.3 (七步流程名称映射)
  Day 5:   Phase 3 (ReverificationPage 真实化)
```

---

## 七、验证标准

### 不可修改的验收资产
- 现有单元测试全部通过（`make test`）
- `make lint-python` 零新增 warning
- 现有 API 端点行为不变（向后兼容）

### 每个 Phase 的独立验证

| Phase | 验证方式 |
|---|---|
| 0 | ReverificationPage 加载不崩 + GradeBadge B 级有颜色 + `npm run build` 无 warning |
| 1 | Dashboard 显示等级分布 + CaseCard 有等级徽章 + VerifyPage 用纸张色 + 统计卡片全中文 |
| 2 | 报告 Hero 有报告编号 + Overlap 组件与页面色板一致 + ProgressTracker 显示七步名 |
| 3 | 点击"确认支付"创建新版本 case + VersionHistorySection 显示 v1→v2 |

---

## 八、风险清单

| 风险 | 影响 | 缓解 |
|---|---|---|
| accent 色板与 signal 重复 | 低 | tailwind.config.js 注释说明语义区分 |
| version-history API 对无历史 case 返回空 | 中 | 前端已处理空数组 |
| 报告 Hero 重构破坏现有布局 | 中 | 报告每次重新生成，无旧报告兼容问题 |
| 七步映射与 pipeline 步骤 1:1 不对应 | 中 | 允许多对一映射，后续可拆分 |

---

## 九、与已有文档的关系

| 文档 | 关系 |
|---|---|
| `gap_analysis.md` | 本 PRD 的输入——差距清单和优先级 |
| `ui_ux_redesign_plan.md` | Phase 0-1 已被本 PRD 覆盖（实施完毕），Phase 3 视觉精修参考其设计规格 |
| `QA.md` | 设计哲学来源——七步流程、三层确定性、公证人定位 |
| `veritas_prototype.html` | 视觉参考来源 |
