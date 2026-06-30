# 端到端测试 SOP (Standard Operating Procedure)

> **目标**: 提供标准化的端到端测试流程，帮助 Agent 快速执行测试、发现问题、迭代优化
> **适用范围**: Web API 测试 + 浏览器 UI 测试
> **最后更新**: 2026-06-30
> **维护者**: Linus Torvalds (AI Agent)

---

## 目录

1. [快速开始 (Quick Start)](#1-快速开始-quick-start)
2. [测试路径概览](#2-测试路径概览)
3. [Phase 0: 环境与基础设施检查](#3-phase-0-环境与基础设施检查)
4. [Phase 1: 单元测试（5 分钟）](#4-phase-1-单元测试5-分钟)
5. [Phase 2: Web API + Browser E2E 测试（核心）](#5-phase-2-web-api--browser-e2e-测试核心)
6. [Phase 3: CLI Pipeline 测试](#6-phase-3-cli-pipeline-测试)
7. [Phase 4: 性能与质量验证](#7-phase-4-性能与质量验证)
8. [已知问题模式与快速诊断](#8-已知问题模式与快速诊断)
9. [截图基线与视觉回归](#9-截图基线与视觉回归)
10. [检查清单](#10-检查清单)
11. [附录](#11-附录)

---

## 1. 快速开始 (Quick Start)

### 2 分钟冒烟测试（推荐每次代码变更后执行）

```bash
# 1. 健康检查
curl -s --noproxy '*' http://127.0.0.1:8765/api/health/deep | jq .

# 2. 关键单元测试
uv run python -m pytest \
  tests/unit/test_figure_classification.py \
  tests/unit/test_copy_move_detection.py \
  -x --tb=short -q

# 3. 快速 Web API 冒烟
curl -s --noproxy '*' http://127.0.0.1:8765/api/health | jq .status
curl -s --noproxy '*' -o /dev/null -w "%{http_code}" http://127.0.0.1:5173
```

### 30 分钟完整 E2E（Web + API + CLI）

```bash
# 见 Phase 2 + Phase 3
```

---

## 2. 测试路径概览

Veritas 有三条独立的测试路径，**每条路径发现问题的类型不同**：

| 路径 | 覆盖范围 | 典型问题 | 耗时 |
|------|----------|----------|------|
| **Web API** | FastAPI 路由、Celery 任务分发、数据库读写 | 接口契约不一致、超时、状态机错误 | 2 min |
| **Browser UI** | 前端渲染、用户交互、实时进度 | Placeholder 不匹配、路由错误、控制台报错 | 5 min |
| **CLI Pipeline** | 完整审计流水线（MinerU→分类→取证→报告） | LLM 解析失败、缓存缺失、步骤超时 | 30+ min |

**关键原则**：先 Web API → 再 Browser UI → 最后 CLI Pipeline。越早发现问题，修复成本越低。

---

## 3. Phase 0: 环境与基础设施检查

### 3.1 服务状态检查

```bash
# 后端（必须）
curl -s --noproxy '*' --max-time 5 http://127.0.0.1:8765/api/health
# 预期: {"status":"ok","runner_mode":"celery"}

# 后端深度检查（必须）
curl -s --noproxy '*' --max-time 5 http://127.0.0.1:8765/api/health/deep | jq '.checks | to_entries[] | "\(.key): \(if .value.ok then "✓" else "✗" end)"'

# 前端 Vite（必须）
curl -s --noproxy '*' -o /dev/null -w "Frontend: %{http_code}\n" http://127.0.0.1:5173
# 预期: Frontend: 200

# PostgreSQL（必须）
docker ps --filter "name=postgres" --format "{{.Names}}: {{.Status}}"
# 预期: healthy

# Redis（必须，Celery broker）
docker ps --filter "name=redis" --format "{{.Names}}: {{.Status}}"

# Celery Worker（必须）
ps aux | grep "celery.*worker" | grep -v grep | wc -l
# 预期: ≥ 1

# ELIS Forensic 服务（可选，:8771）
curl -s --noproxy '*' --max-time 3 http://127.0.0.1:8771/health || echo "ELIS: 未启动（可选）"

# SILA Service（可选，:8770）
curl -s --noproxy '*' --max-time 3 http://127.0.0.1:8770/health || echo "SILA: 未启动（可选）"
```

### 3.2 常见环境问题

| 症状 | 原因 | 解决方案 |
|------|------|----------|
| curl 卡住无输出 | `http_proxy` 环境变量代理了本地请求 | 加 `--noproxy '*'` 或 `unset http_proxy` |
| 后端无响应但进程在 | uvicorn --reload 卡在 "Waiting for connections to close" | `kill -9 <pid>` 后重启 |
| Celery 任务 queued 不执行 | Worker 未启动或已死 | `make celery-worker` |
| 前端 502 | Vite dev server 未启动 | `cd web/frontend && npm run dev` |

### 3.3 重启服务的正确方式

```bash
# 后端
kill -9 $(pgrep -f "uvicorn.*8765") 2>/dev/null
nohup uv run uvicorn web.backend.veritas_web.app:app \
  --host 127.0.0.1 --port 8765 \
  --reload --reload-dir engine --reload-dir web/backend \
  > logs/app/backend.log 2>&1 &
sleep 5
curl -s --noproxy '*' http://127.0.0.1:8765/api/health

# Celery Worker
kill $(pgrep -f "celery.*worker") 2>/dev/null
nohup uv run celery -A engine.tasks.celery_app worker \
  --loglevel=info > logs/worker/celery.log 2>&1 &
```

---

## 4. Phase 1: 单元测试（5 分钟）

```bash
# 关键测试（每次必跑）
uv run python -m pytest \
  tests/unit/test_figure_classification.py \
  tests/unit/test_copy_move_detection.py \
  -x --tb=short -q

# 全量单元测试（提交前必跑）
make test-fast
# 预期: 1200+ passed, 0 failed
```

### 不可修改的验收资产

以下测试和数据集**不允许修改**，只能修复实现：

| 资产 | 用途 |
|------|------|
| `tests/unit/test_figure_classification.py` | Figure classification golden test |
| `tests/unit/test_copy_move_detection.py` | Copy-move 检出率 |
| `tests/unit/test_certainty_enrichment.py` | LLM enrichment 质量 |
| `tests/unit/test_visual_finding_pipeline.py` | Visual pipeline 集成 |
| `input/paper2/` | E2E 输入数据 |
| `ground_truth/paper2/annotations.yaml` | 9 个已标注 claims |

---

## 5. Phase 2: Web API + Browser E2E 测试（核心）

> 这是发现 UI/UX 问题和前后端集成问题的主要手段。使用 Chrome MCP 工具操作浏览器。

### 5.1 Web API 冒烟测试

```bash
# 1. 创建 Case
CASE_ID=$(curl -s --noproxy '*' -X POST http://127.0.0.1:8765/api/cases \
  -H 'Content-Type: application/json' \
  -d '{"paper_title":"E2E Smoke Test"}' | jq -r '.case_id')
echo "Case: $CASE_ID"

# 2. 上传文件（paper2 子集）
cd /mnt/disk1/LZJ/project/veritas
for f in input/paper2/s41588-025-02253-8.pdf input/paper2/41588_2025_2253_MOESM6_ESM.xlsx; do
  curl -s --noproxy '*' -X POST "http://127.0.0.1:8765/api/cases/${CASE_ID}/inputs" \
    -F "file=@$f" > /dev/null
done

# 3. 提交审计
RUN_RESP=$(curl -s --noproxy '*' -X POST http://127.0.0.1:8765/api/audit \
  -H 'Content-Type: application/json' \
  -d "{\"case_id\":\"${CASE_ID}\",\"reproducibility_tier\":\"full\"}")
RUN_ID=$(echo "$RUN_RESP" | jq -r '.job_id')
echo "Run: $RUN_ID"

# 4. 监控状态（每 30 秒）
for i in $(seq 1 60); do
  sleep 30
  STATUS=$(curl -s --noproxy '*' "http://127.0.0.1:8765/api/audit/${RUN_ID}" \
    | jq -r '"\(.status)|\(.current_stage // "none")"')
  echo "$(date +%H:%M:%S) $STATUS"
  echo "$STATUS" | grep -qE "^completed|^failed" && break
done

# 5. 验证报告生成
curl -s --noproxy '*' -o /dev/null -w "HTML Report: %{http_code}\n" \
  "http://127.0.0.1:8765/api/cases/${CASE_ID}/report/html"
```

### 5.2 Browser UI 测试（Chrome MCP）

**Step 1: Client Workspace（默认入口 `localhost:5173`）**

```
导航到 http://localhost:5173
截图: docs/demos/screenshots/01-client-home.png

检查项:
- [ ] 4-step 表单正常渲染（Reproducibility / Submission / Confidentiality / Service）
- [ ] 6 个 Tab 可点击（提交/进度/报告/问题/重核/验证）
- [ ] 无控制台 JS 错误
- [ ] Verify Tab placeholder 格式: "VRT-YYYYMM-XXXXXX"（如 VRT-202606-A3F92C）
```

**Step 2: Ops Workspace（`localhost:5173/ops`）**

```
导航到 http://localhost:5173/ops
截图: docs/demos/screenshots/02-ops-dashboard.png

检查项:
- [ ] Auth 自动登录（dev 模式 operator auto-login）
- [ ] Dashboard 正确显示 case 数量
- [ ] 侧边栏导航分组正确（CASE FLOW / 调查流程 / 认证服务 / 管理）
- [ ] 无 case 选中时相关页面按钮 disabled
- [ ] "运行监控" 和 "审查报告" 在未选中 case 时 disabled
```

**Step 3: Mission Control（选中 case 后）**

```
从侧边栏点击 case → 进入 Mission Control
截图: docs/demos/screenshots/03-mission-control.png

检查项:
- [ ] 进度条正确显示（各阶段 X/Y 数字）
- [ ] **无 "Unknown" 阶段名**（如果有，说明某步骤缺少 stage_name）
- [ ] 实时事件流（SSE/WebSocket 连接正常）
- [ ] 材料完整性面板（PDF/Source Data/代码/环境）
- [ ] 产物准备清单（运行中 → 产物逐步出现）
```

**Step 4: Verify Page（`localhost:5173/verify`）**

```
导航到 http://localhost:5173/verify
截图: docs/demos/screenshots/04-verify-page.png

检查项:
- [ ] Placeholder 格式: "输入报告编号，如 VRT-202606-A3F92C"
- [ ] 格式校验: 输入 "INVALID" → 应触发 400 错误
- [ ] 未找到: 输入 "VRT-202606-FFFFFF" → 应显示 "未找到报告"
- [ ] 两个 VerifyPage 组件（standalone + client-embedded）placeholder 一致
```

**Step 5: 审计完成后的报告页**

```
审计完成后刷新 Mission Control
截图: docs/demos/screenshots/05-mission-completed.png

检查项:
- [ ] 状态显示 "已完成"
- [ ] HTML 报告链接可点击
- [ ] Dashboard 上 case 状态已更新
```

### 5.3 控制台错误检查

在每一步浏览器操作后，检查 JS 控制台：

```javascript
// 通过 Chrome MCP list_console_messages 检查
// 预期: 无 error 级别的消息
// 允许: warning（第三方库）、info
```

---

## 6. Phase 3: CLI Pipeline 测试

### 6.1 完整审计运行

```bash
# 清理旧产物（可选）
rm -rf outputs/*

# 运行 paper2 端到端测试（fast profile）
uv run python cli/commands/audit_paper.py \
  --paper-dir input/paper2 \
  --profile fast \
  --progress plain 2>&1 | tee /tmp/audit_paper2.log

# 监控进度
tail -f /tmp/audit_paper2.log
```

### 6.2 日志分析

```bash
# 提取步骤耗时
grep -E "pipeline step|runtime_seconds" /tmp/audit_paper2.log | \
  awk -F'—' '{print $1, $3}'

# 检查错误
grep -E "ERROR|WARNING|FAIL" /tmp/audit_paper2.log | \
  grep -v "DEBUG" | tail -20

# 检查 LLM 相关错误
grep -E "VeritasLLMParseError|JSON extraction failed|max_tokens" /tmp/audit_paper2.log

# 检查 opencode Agent 错误
grep "opencode.*failed\|schema_validation" /tmp/audit_paper2.log
```

### 6.3 Celery Worker 日志

```bash
# 实时查看
tail -f logs/worker/celery.log

# 检查关键事件
grep -E "pipeline step|ERROR|WARNING|Hard time limit" logs/worker/celery.log | tail -30

# 检查 LLM 调用参数（验证 max_tokens 修复）
grep "max_tokens" logs/worker/celery.log | tail -5
```

---

## 7. Phase 4: 性能与质量验证

### 7.1 性能基线

| 指标 | 旧基线 | 目标 | 验证方式 |
|------|--------|------|----------|
| **总耗时** (paper2, CLI fast) | 42 min | **≤ 20 min** | Wall time |
| **Web E2E 总耗时** (API→完成) | 60+ min | **≤ 35 min** | API 轮询 |
| Figure classification | 8m30s (18×LLM) | **≤ 2 min** (1×LLM) | 日志 |
| Visual 阶段 | 30+ min | **≤ 5 min** | 日志 |
| HTML 报告生成 | ~28 min | **≤ 15 min** | curl |

### 7.2 质量基线

| 指标 | 基线 | 验证方式 |
|------|------|----------|
| **Findings 总数** | ≥ 54 | `jq '.findings \| length'` |
| PubPeer 覆盖率 | ≥ 73% (8/11) | Ground truth 对比 |
| Source Data findings | ≥ 39 | 分类统计 |
| Visual findings | ≥ 13 | 分类统计 |
| Figure classification 准确率 | ≥ 95% | Golden test |

### 7.3 提取结果

```bash
# 找最新 bundle
BUNDLE=$(ls -t outputs/*/bundle.json | head -1)

# Findings 统计
echo "Total: $(cat $BUNDLE | jq '.findings | length')"
cat $BUNDLE | jq -r '.findings | group_by(.issue_category) | map("\(. [0].issue_category): \(length)") | .[]'

# 按风险等级
cat $BUNDLE | jq -r '.findings | group_by(.risk_level) | map("\(. [0].risk_level): \(length)") | .[]'
```

---

## 8. 已知问题模式与快速诊断

> 这些是从实际 E2E 测试中沉淀出的问题模式。**遇到类似症状时，直接按诊断路径排查。**

### 模式 A: LLM JSON 解析失败

| 维度 | 内容 |
|------|------|
| **症状** | `VeritasLLMParseError: Failed to parse JSON from LLM response` |
| **日志特征** | `max_tokens` 值偏小（如 1024），JSON 被截断 |
| **根因** | `chat_json` 默认 `max_tokens` 不足，大 prompt 的响应被截断 |
| **诊断** | `grep "max_tokens" logs/worker/celery.log` 检查每次 LLM 调用的 max_tokens |
| **修复方向** | 增大 `chat_json` 默认 max_tokens；对大 prompt 显式传 `max_tokens` |
| **验证** | `grep "VeritasLLMParseError" logs/worker/celery.log` 应为空 |

### 模式 B: 循环内重复 LLM 调用

| 维度 | 内容 |
|------|------|
| **症状** | 某阶段耗时异常长（30+ min），Mission Control 事件流停止 |
| **日志特征** | 同一函数被重复调用 N 次，参数完全相同 |
| **根因** | 循环内调用昂贵函数但无缓存，输入在循环期间不变 |
| **诊断** | 对比循环次数 vs 唯一参数组合数 |
| **修复方向** | 将循环内的纯函数结果缓存到循环外 |
| **验证** | 日志中该函数只出现 1 次 |

### 模式 C: 前后端契约不一致

| 维度 | 内容 |
|------|------|
| **症状** | 用户按 placeholder 输入 → 400 错误；或输入正确格式 → 前端不显示结果 |
| **日志特征** | 后端 400 响应，前端 404 响应 |
| **根因** | 前端 placeholder 格式与后端校验 regex 不一致 |
| **诊断** | 对比 `placeholder="..."` 与后端 schema validation |
| **修复方向** | 统一 placeholder 示例为后端期望格式 |
| **验证** | 按 placeholder 输入 → 不触发 400 |

### 模式 D: 阶段名 "Unknown"

| 维度 | 内容 |
|------|------|
| **症状** | Mission Control 进度条出现 "Unknown" 阶段 |
| **根因** | Pipeline step 的 `stage_name` 或 `stage` 字段未设置 |
| **诊断** | 在 events API 中查找 `stage` 为空的步骤 |
| **修复方向** | 为所有 pipeline step 设置明确的 `stage` |
| **验证** | Mission Control 无 "Unknown" |

### 模式 E: opencode Agent JSON 提取失败

| 维度 | 内容 |
|------|------|
| **症状** | `opencode material plan failed: schema_validation: JSON extraction failed` |
| **日志特征** | `ValueError: no JSON object found in opencode output` |
| **根因** | opencode 返回的是 markdown 或其他非 JSON 格式 |
| **诊断** | 检查 opencode 输出内容 |
| **修复方向** | 增强 JSON 提取鲁棒性（strip markdown, fallback parser） |
| **验证** | Agent 步骤不再报 warning |

### 模式 F: Celery 硬超时 (Hard time limit exceeded)

| 维度 | 内容 |
|------|------|
| **症状** | `Hard time limit (3600s) exceeded for run_audit`, worker SIGKILL |
| **日志特征** | `Process 'ForkPoolWorker-N' exited with signal 9 (SIGKILL)` |
| **根因** | 审计任务运行超过 1 小时（通常由缓存缺失或 LLM 重试风暴导致） |
| **诊断** | 检查同 case 的前序日志是否有重复调用 |
| **修复方向** | 修复根因（缓存、max_tokens）；必要时调整 `task_time_limit` |
| **验证** | 审计在合理时间内完成 |

### 模式 G: curl/HTTP 客户端走代理

| 维度 | 内容 |
|------|------|
| **症状** | `curl` 卡住无输出，或连接到 `127.0.0.1:18808`（代理端口） |
| **日志特征** | `Connected to 127.0.0.1 (127.0.0.1) port 18808` |
| **根因** | `http_proxy` 环境变量导致本地请求被代理 |
| **诊断** | `echo $http_proxy` |
| **修复方向** | 加 `--noproxy '*'` 或 `unset http_proxy` |
| **验证** | curl 直连 127.0.0.1 |

### 快速诊断决策树

```
审计任务异常？
├─ 卡在 visual 阶段 > 10 min？
│  ├─ 日志有 VeritasLLMParseError → 模式 A (max_tokens)
│  ├─ 同一 LLM 函数重复调用 → 模式 B (缓存)
│  └─ 无日志输出 → 检查 LLM API 连通性
│
├─ Mission Control 显示 "Unknown"？
│  └─ 模式 D (stage_name 缺失)
│
├─ Agent 步骤 warning？
│  └─ 模式 E (opencode JSON 提取)
│
├─ Worker 进程被 SIGKILL？
│  └─ 模式 F (硬超时，通常由 A/B 引发)
│
└─ 前端 API 调用 400？
   └─ 模式 C (placeholder 格式) 或 curl 代理问题 (模式 G)
```

---

## 9. 截图基线与视觉回归

### 截图保存位置

```
docs/demos/screenshots/
├── 01-client-home.png        # Client 首页
├── 02-ops-dashboard.png      # Ops Dashboard
├── 03-mission-control.png    # Mission Control（运行中）
├── 04-verify-page.png        # Verify 独立页面
├── 05-mission-completed.png  # Mission Control（完成）
├── 06-mission-agent-stage.png
└── 07-mission-completed.png
```

### 截图规范

- 文件名带序号，方便排序
- 每次完整 E2E 测试后更新截图
- 截图时确保页面已完全加载（`sleep 3` 或 `wait_for` 关键文本）
- 使用 Chrome MCP `take_screenshot` 工具，指定 `filePath`

### 视觉回归检查

对比新旧截图，关注：
- 布局是否错位
- 文字是否截断
- 颜色/主题是否一致
- 按钮/Tab 状态是否正确

---

## 10. 检查清单

### 测试前

- [ ] 所有服务在线（backend :8765, frontend :5173, PostgreSQL, Redis, Celery）
- [ ] `curl` 不走代理（`--noproxy '*'`）
- [ ] 环境变量正确（`DASHSCOPE_API_KEY`）
- [ ] 测试数据存在（`input/paper2/`）

### 单元测试

- [ ] `test_figure_classification.py` 通过
- [ ] `test_copy_move_detection.py` 通过
- [ ] `make test-fast` 全通过（1200+ tests）

### Web API 测试

- [ ] `/api/health` → 200
- [ ] `/api/health/deep` → 所有检查 ok
- [ ] 创建 Case → 返回 case_id
- [ ] 上传文件 → 返回 200
- [ ] 提交审计 → 返回 job_id
- [ ] 监控进度 → 最终 completed
- [ ] HTML 报告可访问

### Browser UI 测试

- [ ] Client 首页 4-step 表单正常
- [ ] Ops Dashboard 显示 case 列表
- [ ] Mission Control 无 "Unknown" 阶段
- [ ] 进度实时更新
- [ ] Verify 页面 placeholder 格式正确
- [ ] 无 JS 控制台错误


### 提交前

- [ ] 所有测试通过
- [ ] 截图已更新
- [ ] 风险清单已输出
- [ ] 回滚方案已准备

---

## 11. 附录

### A. 关键文件路径

| 文件 | 用途 |
|------|------|
| `cli/commands/audit_paper.py` | CLI E2E 入口 |
| `engine/static_audit/pipeline.py` | Pipeline 编排 |
| `engine/static_audit/figure_classification.py` | Figure classification |
| `engine/llm/client.py` | LLM 客户端（`chat_json` max_tokens） |
| `engine/static_audit/visual_pipeline/panel_extraction.py` | Panel extraction（缓存） |
| `web/backend/veritas_web/app.py` | FastAPI 后端 |
| `web/frontend/src/services/api.js` | 前端 API 层 |
| `web/frontend/src/pages/VerifyPage.jsx` | Verify 独立页 |
| `web/frontend/src/pages/client/VerifyPage.jsx` | Verify 嵌入页 |
| `web/frontend/src/utils/entrypoint.js` | 入口检测逻辑 |
| `logs/app/backend.log` | 后端日志 |
| `logs/worker/celery.log` | Celery worker 日志 |
| `input/paper2/` | 测试数据 |
| `ground_truth/paper2/annotations.yaml` | Ground truth |
| `outputs/*/bundle.json` | 审计结果 |
| `docs/demos/screenshots/` | E2E 截图 |

### B. 常用 Chrome MCP 命令

| 操作 | 工具 |
|------|------|
| 导航 | `navigate_page(url)` |
| 截图 | `take_screenshot(filePath)` |
| 快照 | `take_snapshot()` |
| 点击 | `click(uid)` |
| 填表 | `fill(uid, value)` |
| 检查控制台 | `list_console_messages(types=["error"])` |
| 检查网络 | `list_network_requests()` |

### C. 常用 API 端点

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/health/deep` | GET | 深度健康检查 |
| `/api/cases` | GET/POST | 列表/创建 Case |
| `/api/cases/{id}/inputs` | POST | 上传文件 |
| `/api/audit` | POST | 提交审计 |
| `/api/audit/{id}` | GET | 查询审计状态 |
| `/api/cases/{id}/report/html` | GET | HTML 报告 |
| `/api/verify/{report_id}` | GET | 公开验证 |
| `/api/me` | GET | 当前用户信息 |
| `/api/audit/queue` | GET | 队列状态 |

### D. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v2.0 | 2026-06-30 | 新增 Web API + Browser E2E 测试路径；新增已知问题模式库；新增 Chrome MCP 操作指南；更新性能基线 |
| v1.0 | 2026-06-29 | 初始版本，CLI Pipeline 测试 |

---

## 快速参考卡片

```
┌─────────────────────────────────────────────────────────┐
│ E2E 测试快速参考                                         │
├─────────────────────────────────────────────────────────┤
│ 1. 健康检查:                                             │
│    curl -s --noproxy '*' http://127.0.0.1:8765/api/health/deep │
│                                                         │
│ 2. 单元测试:                                             │
│    uv run python -m pytest tests/unit/ -x --tb=short -q │
│                                                         │
│ 3. Web API 冒烟:                                        │
│    POST /api/cases → POST /api/audit → GET /api/audit/{id} │
│                                                         │
│ 4. Browser UI:                                          │
│    Chrome MCP → :5173 → :5173/ops → :5173/verify        │
│                                                         │
│ 5. CLI Pipeline:                                        │
│    uv run python cli/commands/audit_paper.py --paper-dir input/paper2 │
│                                                         │
│ 6. 日志诊断:                                             │
│    grep -E "ERROR|WARNING|ParseError" logs/worker/celery.log │
│                                                         │
│ 7. 截图保存:                                             │
│    docs/demos/screenshots/01-xxx.png                     │
└─────────────────────────────────────────────────────────┘
```
