# UI / UX 体验必知

> 前端当前存在的"假配置"——用户以为自己在选择，但实际不改变系统行为的部分。
> 更新：2026-07-01

---

## SubmitPage（客户端提交页）三个选择器的真实数据流

### 1. 声明可复现条件等级（`tier`）

| 等级 | 徽章 | 设计意图 |
|------|------|----------|
| `full` | A | 数据 + 代码 + 环境 + 完整 run 历史 |
| `partial` | B | 数据 + 代码 + 环境，无 run 历史 |
| `code_only` | C | 代码 + 数据接口（数据因隐私不公开） |
| `static` | C− | 仅论文 + 关键结果文件，无法重跑代码 |

**数据流**：前端 → API 接收 → DB 持久化 → engine 入口接收 → grade_engine 作为评级天花板消费

- 设计意图：认证等级天花板——材料越完整，可授予的最高等级越高。
- 实际状态：`reproducibility_tier` 会随创建 case 和提交 audit 写入 case 记录，并透传给 `run_static_audit()`；`grade_engine.py` 会按 `full=A`、`partial=B`、`code_only=C`、`static=C` 对最终评级做天花板截断。
- 结论：**已改变最终评级上限，但尚不控制 pipeline 步骤集合。**

### 2. 选择数据安全级别（`security`）

| 级别 | 设计意图 |
|------|----------|
| 标准（Standard） | 云端 API，零数据保留，24h 内销毁 |
| 加密（Confidential） | 端到端加密，作者持有密钥 |
| 私有（Private VPC） | 本地部署开源模型，数据不出网 |

**数据流**：❌ 从未传给后端，❌ 未持久化，纯 UI 状态。

只影响按钮高亮和标签文案，不改变任何系统行为。

### 3. 选择核查服务（`service`）

| 服务 | 设计意图 |
|------|----------|
| 基础扫描（免费） | 静态检查，仅显示问题数量摘要 |
| 完整认证（¥680） | 完整证据链 + 修改建议 + PDF 证书 |
| 认证+修复（¥1,280） | 完整认证 + 5 次重跑 + 代码自动修复 |

**数据流**：❌ 从未传给后端，❌ 未持久化，纯 UI 状态。

当前系统只有一种执行路径（`agent_mode: 'full'` 硬编码），不区分服务等级。

---

## 风险

这三个选择器给用户造成"我配置了审查参数"的错觉。如果产品面向外部用户上线，这些**假选择器会造成信任风险**——用户以为自己选择了安全级别和服务等级，但系统行为完全不变。

## 未来生效路径

当这些参数需要真正生效时，需要补齐：

| 参数 | 需要做的事 |
|------|-----------|
| `tier` | grade 天花板已生效；后续如需要，再按 tier 启用/禁用 pipeline 步骤 |
| `security` | 加入 API body → 后端按级别路由到不同执行环境 → 持久化到 case 记录 |
| `service` | 加入 API body → 控制 `agent_mode`、pipeline 步骤集合、报告输出格式 |

---

## 前端全量 API 端点清单（测试用）

> 大多数 JSON API 经过 `src/services/api.js` 的 `request()` 统一封装，自动附加 Basic Auth 头和错误翻译。
> 例外：上传走 `XMLHttpRequest` 以支持进度；HTML/图片直链返回 URL；artifact 文本和 SSE/steps 轮询直接用 `fetch` / `EventSource`。
> 标记 🔒 的端点需要认证；标记 ⭐ 的为写操作（POST/PUT/DELETE），测试时注意副作用。
> 默认端口：开发环境 Vite → `:5173`（proxy 到 backend `:8765`），直接访问 backend → `:8765`。

---

### A. 系统级（无需 case 上下文）

| # | 方法 | 端点 | 调用位置 | 说明 |
|---|------|------|----------|------|
| A1 | GET | `/api/health` | AppLayout（每 15s 轮询） | 健康检查，返回 `status`、`runner_mode`、`recovered_interrupted_runs` |
| A1b | GET | `/api/health/deep` | 部署/诊断 | 深度健康检查，验证依赖、模型权重和数据目录 |
| A2 | GET | `/api/me` 🔒 | AppLayout（挂载时） | 获取当前用户：`user_id`、`email`、`roles`、`is_admin` |
| A3 | GET | `/api/cases` 🔒 | CasesPage / AppLayout | 列出所有 case，返回 `cases[]` |
| A3b | GET | `/api/cases/stats` 🔒 | 后端可用 | case 总数、finding 总数、高风险和运行中计数 |
| A4 | POST | `/api/cases` 🔒 ⭐ | NewAuditPage / SubmitPage | 创建 case，body: `{case_id?, paper_title?, reproducibility_tier?}` |
| A5 | GET | `/api/audit/queue` 🔒 | MissionControlPage | 查询审计任务队列 |

---

### B. 文件上传（SubmitPage / NewAuditPage）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| B1 | POST | `/api/cases/:caseId/inputs` 🔒 ⭐ | 单文件上传（multipart/form-data），字段：`file` + 可选 `relative_path` |
| B2 | POST | `/api/audit` 🔒 ⭐ | 提交审计任务，body: `{case_id, options: {reproducibility_tier, ...}}` |
| B3 | GET | `/api/audit/:jobId` 🔒 | 查询审计任务状态 |
| B4 | DELETE | `/api/audit/:jobId` 🔒 ⭐ | 取消审计任务 |
| B5 | GET | `/api/audit/:jobId/stream` 🔒 | 审计任务 SSE 进度流 |

---

### C. 运行监控（MissionControlPage）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| C1 | GET | `/api/cases/:caseId/runs/:runId` 🔒 | 获取运行详情（状态、耗时、stages） |
| C2 | GET | `/api/cases/:caseId/runs/:runId/events` 🔒 | 获取原始运行事件列表 |
| C2b | GET | `/api/cases/:caseId/runs/:runId/steps` 🔒 | 获取结构化步骤和进度汇总 |
| C2c | GET | `/api/cases/:caseId/runs/:runId/stream` 🔒 | run-scoped SSE 进度流 |
| C3 | GET | `/api/cases/:caseId/materials` 🔒 | 材料完整性检查（是否缺失必要文件） |
| C4 | GET | `/api/cases/:caseId/risk-summary` 🔒 | 风险概览（各等级 finding 计数） |

---

### D. 审查报告（ReportCenterPage）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| D1 | GET | `/api/cases/:caseId/artifacts` 🔒 | 列出所有 artifact |
| D2 | GET | `/api/cases/:caseId/artifacts/:artifactId` 🔒 | 获取 artifact 文本内容 |
| D3 | GET | `/api/cases/:caseId/report/html` 🔒 | HTML 报告直链（iframe 嵌入） |
| D4 | GET | `/api/cases/:caseId/client-report` 🔒 | 客户端报告聚合视图（BFF） |

---

### E. 审查发现（FindingsPage）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| E1 | GET | `/api/cases/:caseId/visual/findings` 🔒 | 视觉取证发现列表 |
| E2 | GET | `/api/cases/:caseId/artifacts/certainty_data` 🔒 | Certainty 层数据（fact / inference / suggestion） |

---

### F. 证据审查（EvidenceReviewPage）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| F1 | GET | `/api/cases/:caseId/visual/figures` 🔒 | 论文中的图片列表 |
| F2 | GET | `/api/cases/:caseId/visual/panels` 🔒 | 提取的 panel 列表 |
| F3 | GET | `/api/cases/:caseId/visual/relationships` 🔒 | 图片间关系图（相似/复用） |
| F4 | GET | `/api/cases/:caseId/visual/images/:path` 🔒 | 图片资源（直接渲染） |
| F5 | GET | `/api/cases/:caseId/artifacts/visual_overlap_reuse` 🔒 | 重叠/复用分析数据 |
| F6 | GET | `/api/cases/:caseId/artifacts/provenance_graph` 🔒 | 来源溯源图 |

---

### G. 调查（EvidenceReviewPage 内触发）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| G1 | GET | `/api/cases/:caseId/investigations` 🔒 | 列出已有调查 |
| G2 | POST | `/api/cases/:caseId/investigations` 🔒 ⭐ | 启动新调查，body: 调查参数 |

---

### H. 行动项（ActionsPage）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| H1 | GET | `/api/cases/:caseId/review-items` 🔒 | 获取待审核条目列表 |
| H2 | POST | `/api/cases/:caseId/review-items/:sourceRef/decision` 🔒 ⭐ | 保存审核决策，body: `{decision, reason?}` |

---

### I. 重新核查（ReverificationPage）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| I1 | GET | `/api/cases/:caseId/version-history` 🔒 | 版本历史（修订链路） |
| I2 | GET | `/api/cases/:caseId/reverification-cost` 🔒 | 重核查费用/时间预估 |
| I3 | POST | `/api/cases/:caseId/reverify` 🔒 ⭐ | 提交重新核查任务 |

---

### J. 公开验证（VerifyPage — 无需认证）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| J1 | GET | `/api/verify/:reportId` | 公开验证报告真伪（任何人可访问） |

---

### K. 用户管理（AdminPage — 仅管理员）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| K1 | GET | `/api/users` 🔒🔑 | 列出所有用户 |
| K2 | POST | `/api/users` 🔒🔑 ⭐ | 创建用户，body: `{username, password, email, roles}` |
| K3 | PUT | `/api/users/:userId` 🔒🔑 ⭐ | 更新用户，body: `{email?, roles}` |
| K4 | DELETE | `/api/users/:userId` 🔒🔑 ⭐ | 删除用户 |
| K5 | POST | `/api/users/:username/password` 🔒🔑 ⭐ | 修改密码，body: `{password}` |

---

### L. 其他（CasesPage）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| L1 | DELETE | `/api/cases/:caseId` 🔒 ⭐ | 删除 case 及其所有运行数据 |
| L2 | GET | `/api/cases/:caseId` 🔒 | 获取单个 case 详情 |
| L3 | GET | `/api/tools/catalog` 🔒 | Tool Registry 目录 |
| L4 | GET | `/api/tools/health` 🔒 | 工具健康状态 |
| L5 | GET | `/api/diag` 🔒 | 后端诊断报告 |
| L6 | GET | `/api/metrics` 🔒 | Prometheus 指标 |

---

### 测试速查表

| 🔒 标记 | 含义 |
|---------|------|
| 🔒 | 需要 Basic Auth（`Authorization: Basic base64(user:pass)`） |
| 🔒🔑 | 需要管理员角色（`is_admin: true`） |
| ⭐ | 写操作，会产生副作用，测试前确认目标环境 |

**快速冒烟路径**（建议按此顺序测试）：

```
A1 健康检查 → A2 登录态 → A4 创建 case → B1 上传文件 → B2 提交审计
→ C1 查看运行 → C2b 步骤汇总 / C2c SSE → D1 artifacts → D3 HTML 报告
→ E1 findings → F1-F6 证据审查 → H1-H2 行动项 → J1 公开验证
```

---

## 前端 UI 测试要点

> 以下按页面列出需要验证的交互状态、边界条件和数据展示点。
> 每个检查项标注预期行为，通过 = 符合预期，不通过 = 需要修复。

---

### 1. 全局状态（AppLayout）

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| G1 | 未登录访问 | 跳转到 LoginPage，无侧边栏 | 清除 sessionStorage 后刷新 |
| G2 | 后端在线 | Topbar 显示正常，无错误横幅 | 启动 backend 后访问 |
| G3 | 后端离线 | 显示"Backend 已断开"横幅，侧边栏仍可切换页面 | 关闭 backend 进程 |
| G4 | 恢复中断任务 | 显示黄色横幅提示恢复了 N 个 interrupted run | backend 重启后访问 |
| G5 | 健康检查轮询 | 每 15 秒调用 `/api/health`，网络面板可见 | DevTools Network 过滤 `health` |
| G6 | 页面切换 URL 同步 | 切换 TAB 时 URL 的 `?page=` 参数更新 | 复制 URL 在新标签打开，应恢复同一页 |
| G7 | 浏览器前进/后退 | 正确恢复页面状态（activePage、caseId、runId） | 点击浏览器后退按钮 |
| G8 | 加载态 | 页面切换时显示 LoadingFallback（骨架屏或 spinner） | 在 Slow 3G 模式下切换页面 |
| G9 | 错误边界 | 子组件抛错时不白屏，显示 ErrorBoundary 降级 UI | 在 React DevTools 中断言抛错 |

---

### 2. SubmitPage（客户端提交页）

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| S1 | 文件类型校验 | 仅允许 PDF/XLSX/CSV/TSV/PNG/JPG/TIFF/BMP/WEBP/ZIP/TAR.GZ，其他类型显示红色错误 | 上传 `.exe` 或 `.txt` |
| S2 | 文件大小校验 | 单文件 > 200MB 时显示"文件过大"错误，不发起上传 | 上传 > 200MB 文件 |
| S3 | 拖放上传 | 拖入文件时：① 整个虚线框放大 1% + 阴影 ② 图标放大 125% 并旋转 6° ③ 背景变 accent-100 ④ 文字变"松开鼠标上传文件"且变色 | 拖放文件到上传区 |
| S3b | 悬停态 | 鼠标悬停时虚线框边框变为 accent-500/40 + 淡阴影 | 鼠标移入未拖入时 |
| S4 | 拖放目录 | 拖入文件夹后递归包含所有文件 | 拖放一个目录 |
| S5 | 选择目录上传 | 点击"或选择整个目录上传"后打开目录选择器 | 点击该按钮 |
| S5b | 点击提示区上传 | 点击上传提示区任意位置（图标、文字、按钮视觉区域）均触发文件选择器；文件列表、删除按钮、分类槽不触发文件选择器 | 点击提示区与文件列表区域 |
| S6 | 文件分类槽 | 上传后自动分为"论文稿件""代码仓库""数据"三个槽 | 上传 PDF + ZIP + XLSX |
| S7 | 拖放到指定槽 | 拖文件到某个槽会强制归为该分类 | 拖 `.xlsx` 到"论文稿件"槽 |
| S8 | 删除文件 | 点击文件旁的 ✕ 从列表移除 | 添加后删除一个文件 |
| S9 | 上传进度 | 上传时显示总进度条 + 每个文件的百分比 | 上传多个文件，观察进度 |
| S10 | 上传中禁用操作 | 上传/提交进行中，按钮 disabled，不可重复点击 | 上传大文件时尝试再次点击 |
| S11 | 取消上传 | 点击取消按钮中止所有进行中的上传 | 上传大文件时点击取消 |
| S12 | 离开页面提醒 | 有未保存文件时关闭/刷新页面，浏览器弹确认对话框 | 添加文件后按 F5 |
| S13 | 无 PDF 提交 | 显示"输入中必须包含论文 PDF"错误 | 只上传 XLSX 后点击提交 |
| S14 | 空文件提交 | 显示"请至少上传一个 PDF 或材料文件" | 不上传任何文件直接点提交 |
| S15 | 提交成功 | 跳转到 ProgressPage，URL 含 caseId 和 runId | 正常上传并提交后观察 |
| S16 | tier 选择器 | 四个等级可切换，选中状态有高亮 | 逐一点击四个等级 |
| S17 | security 选择器 | 三个级别可切换，但切换不影响提交结果 | 切换后提交，检查 API body |
| S18 | service 选择器 | 三档服务可切换，但切换不影响提交结果 | 切换后提交，检查 API body |

---

### 3. CasesPage（Dashboard 看板）

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| CP1 | 空状态 | 无 case 时显示"暂无 case"或引导创建 | 清空数据库后访问 |
| CP2 | case 列表 | 显示所有 case，包含论文标题、状态、创建时间 | 创建多个 case 后刷新 |
| CP3 | 风险分组 | case 按风险等级（critical/high/medium/low）分组显示 | 有不同风险等级的 case |
| CP4 | 点击 case | 选中 case，URL 更新 `?case=xxx`，右侧展示详情 | 点击列表中的 case |
| CP5 | 删除 case | 显示确认对话框，确认后删除，列表刷新 | 点击删除按钮 |
| CP6 | 状态徽标 | Running / Completed / Failed 有对应颜色徽标 | 有各种状态的 case |

---

### 4. MissionControlPage（运行监控）

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| MC1 | 无运行记录 | 显示"暂无运行记录" | 选中一个未运行过的 case |
| MC2 | 运行中状态 | 显示当前步骤、进度条、已用时间 | 提交审计后查看 |
| MC3 | 步骤展开 | 每个步骤可展开查看详细事件 | 点击步骤标题 |
| MC4 | 失败步骤 | 失败步骤标红，显示错误信息和退出码 | 制造一个失败场景（如上传空 PDF） |
| MC5 | SSE 实时推送 | 运行中时日志实时追加，无需手动刷新 | 观察运行中的任务 |
| MC6 | 运行完成 | 状态变为 Completed，显示总耗时和结果摘要 | 等待运行完成 |
| MC7 | 材料完整性 | 显示缺失的材料（如缺代码、缺数据） | 只上传 PDF 不上传代码 |

---

### 5. ReportCenterPage（审查报告）

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| RP1 | 无报告 | 显示"报告尚未生成" | 选中未完成运行的 case |
| RP2 | artifact 列表 | 显示所有生成的 artifact 文件 | 运行完成后查看 |
| RP3 | artifact 内容 | 点击 artifact 显示文本内容 | 点击某个 artifact |
| RP4 | HTML 报告 | iframe 嵌入显示完整 HTML 报告 | 点击"打开完整报告" |
| RP5 | 客户端报告 | BFF 聚合视图正确渲染 | 访问 client-report 标签 |

---

### 6. FindingsPage（审查发现）

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| F1 | 无发现 | 显示"暂无发现"或"未发现风险" | 选中无 finding 的 case |
| F2 | 风险概览 | 顶部显示 critical/high/medium/low 计数 | 有 finding 的 case |
| F3 | finding 列表 | 按严重程度排序显示 | 有多个 finding |
| F4 | certainty 分层 | fact / inference / suggestion 正确分类显示 | 查看 certainty 标签页 |
| F5 | finding 详情 | 点击展开显示证据和位置 | 点击某个 finding |

---

### 7. EvidenceReviewPage（证据审查）

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| EV1 | 图片列表 | 显示论文中提取的所有图片 | 上传含图片的论文 |
| EV2 | panel 提取 | 显示提取的 panel 及来源 | 有 panel 数据 |
| EV3 | 关系图 | 显示图片间的相似/复用关系（力导向图或列表） | 有相似图片 |
| EV4 | 图片加载 | 图片 URL 正确渲染，无 broken image | 查看图片列表 |
| EV5 | 重叠/复用分析 | 显示 overlap/reuse 分析结果 | 有分析数据 |
| EV6 | 溯源图 | provenance graph 正确渲染 | 有溯源数据 |
| EV7 | 启动调查 | 点击"启动调查"后弹出表单，提交后任务开始 | 点击调查按钮 |

---

### 8. ActionsPage（行动项）

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| AC1 | 待审核列表 | 显示待审核的 review items | 有 review items |
| AC2 | 空状态 | 无待审核项时显示"全部已处理" | 所有 items 已决策 |
| AC3 | 保存决策 | 点击"通过/拒绝"后状态更新，列表刷新 | 做一个决策 |
| AC4 | 决策理由 | 拒绝时要求填写理由（可选或必填） | 选择拒绝 |

---

### 9. ReverificationPage（重新核查）

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| RV1 | 版本历史 | 显示修订版链路（v1 → v2 → v3） | 有多次运行记录 |
| RV2 | 费用预估 | 显示重核查的时间和费用预估 | 查看预估面板 |
| RV3 | 提交重核查 | 点击提交后新任务开始，状态更新 | 提交重核查 |

---

### 10. VerifyPage（公开验证）

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| VP1 | 无需登录 | 不登录也能访问 | 清除 auth 后直接访问 `/verify` |
| VP2 | 有效报告 | 输入有效 reportId 显示验证通过 | 输入真实 reportId |
| VP3 | 无效报告 | 显示"报告不存在或已失效" | 输入不存在的 reportId |
| VP4 | 空输入 | 提交按钮 disabled 或提示"请输入报告编号" | 不输入直接提交 |

---

### 11. AdminPage（用户管理）

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| AD1 | 权限控制 | 非管理员访问显示 Dashboard 而非 AdminPage | 用普通用户登录 |
| AD2 | 用户列表 | 显示所有用户、角色、邮箱 | 管理员登录 |
| AD3 | 创建用户 | 填写表单后用户出现在列表 | 创建新用户 |
| AD4 | 重复用户名 | 显示"该记录已存在，请勿重复提交" | 创建已存在的用户名 |
| AD5 | 修改角色 | 修改后用户角色更新 | 将 user 改为 admin |
| AD6 | 修改密码 | 旧密码失效，新密码可登录 | 修改后重新登录 |
| AD7 | 删除用户 | 确认后用户从列表消失 | 删除一个用户 |
| AD8 | 删除自己 | 不允许删除当前登录用户，或给出警告 | 尝试删除自己 |

---

### 12. 表单与输入通用验证

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| FM1 | 必填字段 | 空必填字段提交时按钮 disabled 或显示提示 | 不填任何内容提交 |
| FM2 | 超长输入 | 超长文本不截断，不溢出，不崩溃 | 输入 10000 字符 |
| FM3 | 特殊字符 | `<script>`, `"`, `'`, `&`, emoji 正确显示，不 XSS | 输入特殊字符 |
| FM4 | 并发提交 | 快速双击提交不会创建两个 case/job | 快速连续点击 |
| FM5 | 网络错误 | 断网时显示友好错误，不白屏 | 在 DevTools 中 Offline |
| FM6 | 超时处理 | 长时间无响应显示"请稍后重试" | 用 Slow 3G + 延迟 |

---

### 13. 响应式与无障碍

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| R1 | 移动端布局 | 侧边栏折叠为汉堡菜单，页面内容不溢出 | 浏览器宽度 < 768px |
| R2 | 触控操作 | 按钮/链接可点击区域 ≥ 44×44px | 在 DevTools 设备模拟中点击 |
| R3 | 键盘导航 | Tab 键可遍历所有交互元素，Enter/Space 可触发 | 只用键盘操作 |
| R4 | 焦点指示 | 聚焦元素有可见的 focus ring（`focus-visible:ring`） | Tab 键遍历 |
| R5 | 屏幕阅读器 | 关键元素有 `aria-label`，图标有 `aria-hidden` | 用 Lighthouse 检查 |
| R6 | 跳转链接 | "跳转到主要内容"链接可聚焦并生效 | Tab 键首次按下 |

---

### 14. 错误处理与边界

| # | 测试点 | 预期行为 | 验证方式 |
|---|--------|----------|----------|
| E1 | 401 未授权 | 自动跳转 LoginPage，清除 sessionStorage | Token 过期后访问 |
| E2 | 403 无权限 | 显示"没有权限执行此操作" | 普通用户访问 admin API |
| E3 | 404 资源不存在 | 显示友好错误，不白屏 | 访问不存在的 caseId |
| E4 | 500 服务端错误 | 显示"服务内部错误，请稍后重试" | 制造后端 500 |
| E5 | 空响应体 | 不报 JSON 解析错误 | 模拟空响应 |
| E6 | 并发刷新 | 快速连续刷新不产生竞态（请求取消/去重） | 快速连按 F5 |
| E7 | 窗口关闭恢复 | 重新打开后 URL 恢复到上次工作的 case/run | 关闭浏览器重新打开 |

---

### 测试执行建议

1. **冒烟测试**：先走"快速冒烟路径"，确保主流程通畅
2. **边界测试**：按表单通用验证（FM1-FM6）检查输入边界
3. **错误测试**：逐一验证错误处理（E1-E7）
4. **响应式**：在 375px / 768px / 1440px 三个断点检查布局
5. **无障碍**：用 Lighthouse Accessibility 审计跑一次
6. **回归**：每次发版前，至少走一遍冒烟路径 + 全量边界测试
