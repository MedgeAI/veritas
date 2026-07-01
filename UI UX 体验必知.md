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

**数据流**：前端 → API 接收 → DB 持久化 → **engine 不消费**

- 设计意图：认证等级天花板——材料越完整，可授予的最高等级越高。
- 实际状态：`reproducibility_tier` 被写入 case 记录，但 `grade_engine.py` 的等级判定只基于维度评分，**没有读取 tier 做天花板截断**。
- 结论：**存储了但不改变审计行为。**

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
| `tier` | engine 读取 tier 作为 grade 天花板；不同 tier 启用/禁用 pipeline 步骤 |
| `security` | 加入 API body → 后端按级别路由到不同执行环境 → 持久化到 case 记录 |
| `service` | 加入 API body → 控制 `agent_mode`、pipeline 步骤集合、报告输出格式 |

---

## 前端全量 API 端点清单（测试用）

> 所有端点均经过 `api.js` 的 `request()` 统一封装，自动附加 Basic Auth 头和错误翻译。
> 标记 🔒 的端点需要认证；标记 ⭐ 的为写操作（POST/PUT/DELETE），测试时注意副作用。
> 默认端口：开发环境 Vite → `:5173`（proxy 到 backend `:8765`），直接访问 backend → `:8765`。

---

### A. 系统级（无需 case 上下文）

| # | 方法 | 端点 | 调用位置 | 说明 |
|---|------|------|----------|------|
| A1 | GET | `/api/health` | AppLayout（每 15s 轮询） | 健康检查，返回 `status`、`recovered_interrupted_runs` |
| A2 | GET | `/api/me` 🔒 | AppLayout（挂载时） | 获取当前用户：`email`、`roles`、`is_admin` |
| A3 | GET | `/api/cases` 🔒 | CasesPage / AppLayout | 列出所有 case，返回 `cases[]` |
| A4 | POST | `/api/cases` 🔒 ⭐ | NewAuditPage / SubmitPage | 创建 case，body: `{paper_title?, owner?}` |
| A5 | GET | `/api/audit/queue` 🔒 | MissionControlPage | 查询审计任务队列 |

---

### B. 文件上传（SubmitPage / NewAuditPage）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| B1 | POST | `/api/cases/:caseId/inputs` 🔒 ⭐ | 单文件上传（multipart/form-data），字段：`file` + 可选 `relative_path` |
| B2 | POST | `/api/audit` 🔒 ⭐ | 提交审计任务，body: `{case_id, reproducibility_tier, ...options}` |
| B3 | GET | `/api/audit/:jobId` 🔒 | 查询审计任务状态 |
| B4 | POST | `/api/audit/:jobId/cancel` 🔒 ⭐ | 取消审计任务 |

---

### C. 运行监控（MissionControlPage）

| # | 方法 | 端点 | 说明 |
|---|------|------|------|
| C1 | GET | `/api/cases/:caseId/runs/:runId` 🔒 | 获取运行详情（状态、耗时、步骤列表） |
| C2 | GET | `/api/cases/:caseId/runs/:runId/events` 🔒 | 获取运行事件流（用于进度条和日志） |
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
→ C1 查看运行 → C2 事件流 → D1 artifacts → D3 HTML 报告
→ E1 findings → F1-F6 证据审查 → H1-H2 行动项 → J1 公开验证
```
