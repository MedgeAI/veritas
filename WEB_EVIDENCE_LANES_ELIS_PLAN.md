# Web P1 Refactored Implementation Plan

Updated: 2026-06-16（经 Grill Session 重写，替换原 Agentic ELIS-Style 方案）

## 决策日志

本计划经过 Grill Session 逐条对齐，以下是核心决策变更：

| 原计划决策 | 变更后决策 | 理由 |
|---|---|---|
| 6 个新领域对象（Hypothesis/ProposedAction/EvidenceDelta/ReviewTask/HumanDecision） | **零新领域对象**；InvestigationRecord 迁移到 SQL | 已有 InvestigationRecord 覆盖 60% 语义，并行数据模型是维护债 |
| 20+ API endpoints | **8 个新 endpoint** | 砍掉 agentic proposal/approval/delta 全部链路 |
| Agentic HITL loop（Agent 提议 → Human 审批 → 执行） | **P1 不做** | Human approval 的真实瓶颈是 1071 panels 跑 Docker 太重，正确解法是预筛不是审批 |
| Agent plan-next（POST /agent/plan-next） | **P1 不做，Phase 3 评估** | AgentInvestigationPlanner 是 prompt 不是服务，复用需要重写 orchestrator 循环 |
| EvidenceDelta 持久化到 JSONL | **不持久化**；从 InvestigationRecord 前后状态 diff 计算 | 派生数据不需要独立存储 |
| ReviewTask 数据模型 + review_tasks.py 服务 | **聚合视图** + PostgreSQL review_decisions 表 | Review 项是派生数据（从 artifacts 计算），决策是状态数据（需持久化），两者分离 |
| stdlib ThreadingHTTPServer | **FastAPI** | 1633 行手写路由无 async/无连接池/无原子写入/无线程上限，并发写 case.json 有数据丢失竞态 |
| JSON file CaseStore | **PostgreSQL** | write_json 非原子、无文件锁、TOCTOU 竞态，5+ 并发用户会丢数据 |
| dHash（64-bit 二值哈希）做 image similarity | **SSCD（Meta ResNet50 512-dim）embedding + pgvector HNSW** | dHash 只能检测近完全重复，无法发现裁剪/色彩偏移/旋转/局部重叠——恰恰是最常见的造假手法 |
| Milvus 向量数据库 | **pgvector 扩展** | 单 case 几十到几百张图，HNSW 毫秒级查询，不需要额外 3 个 Docker 容器 |
| Celery + Redis 任务队列 | **FastAPI BackgroundTasks + ThreadPoolExecutor(max_workers=3)** | Audit 是长时间任务不是高频短任务，Phase 3 再评估是否需要独立队列 |
| Sidebar 五个入口全部 agentic 化 | **Investigation Board P1 为只读历史查看器，Review Queue 为聚合视图，Advanced Lab 延后** | 先把已有能力在前端可见，验证用户需求后再加 agentic 层 |

## 结论先行

**技术栈**：FastAPI + PostgreSQL (pgvector) + Pydantic v2 + SSCD (PyTorch)

**架构**：

```text
FastAPI (async HTTP + Pydantic 校验)
  ↓
PostgreSQL + pgvector
  ├── 关系数据：cases, runs, events, investigation_records, review_decisions
  └── 向量数据：image_embeddings (SSCD 512-dim, HNSW index)
  ↓
engine/ (审查内核，接口改造不改实现)
  ├── orchestrator → FastAPI BackgroundTask 可调用
  ├── InvestigationRecord → SQLAlchemy model
  ├── opencode_agent.py → 拆分为 planner / role runners / validators
  ├── Tool Registry → DB seed + startup 加载
  └── context_pack / agent_step_runner → 不改动，直接复用
  ↓
PyTorch SSCD (embedding extraction，按需调用)
  ↓
SILA Dense Docker (仅在用户选中 panels 后触发)
```

**一句话定位**：P1 让已有审查能力在 Web 工作台可见、可操作、可追溯；用 SSCD 预筛替代 dHash 解决 1071 panels 跑 Docker 的性能瓶颈；为后续 Agent-driven 调查预留接口但不实现。

## ELIS 参考点（保留）

参考路径不变：

- `third_party/elis/system_modules/elis-frontend/`：Vite/React/Tailwind 基础设施模式
- `third_party/elis/system_modules/copy-move-detection/`：SILA dense 特征提取参考
- `third_party/elis/system_modules/copy-move-detection-keypoint/`：RootSIFT+MAGSAC++ 参考
- `third_party/elis/system_modules/cbir-system/`：SSCD embedding + Milvus 架构参考（Veritas 用 pgvector 替代 Milvus）
- `third_party/elis/app/routes/`：REST API 设计参考

不照搬（不变）：

- 不接 ELIS MongoDB / Celery / Redis / FastAPI 主服务
- 不把 ELIS Web UI 嵌入 Veritas
- 不让前端绕过 Tool Registry 调第三方工具
- 不把 visual tool 分数写成最终科研诚信判定

## 数据模型

### 不再引入新领域对象

原计划中的 6 个 Canonical Agentic Objects（Hypothesis、ProposedAction、InvestigationRecord 扩展、EvidenceDelta、ReviewTask、HumanDecision）**全部取消**。

理由：

- `InvestigationRecord` 已有 `hypothesis`、`tool_id`、`params`、`status`、`output_artifacts`、`depends_on_artifacts`、`expected_evidence_type`、`metadata` 字段，覆盖原 Hypothesis 全部语义和 ProposedAction 80% 语义。
- `EvidenceDelta` 是派生数据，从 InvestigationRecord 前后状态 diff 计算即可。
- `ReviewTask` 的 review 项来自 artifact（派生），决策状态单独存储——两者分离。

### PostgreSQL Schema

```sql
-- 核心关系表
CREATE TABLE cases (
    id VARCHAR(64) PRIMARY KEY,
    owner_id VARCHAR(64) NOT NULL,
    paper_title TEXT,
    status VARCHAR(32) DEFAULT 'created',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE runs (
    id VARCHAR(64) PRIMARY KEY,
    case_id VARCHAR(64) NOT NULL REFERENCES cases(id),
    status VARCHAR(32) DEFAULT 'queued',
    agent_mode VARCHAR(32) DEFAULT 'full',
    workdir TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_event_at TIMESTAMPTZ
);

CREATE TABLE run_events (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL REFERENCES runs(id),
    event_type VARCHAR(32),
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 调查记录（从 InvestigationRecord dataclass 迁移）
CREATE TABLE investigation_records (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(64) NOT NULL REFERENCES cases(id),
    round_id INTEGER,
    action_id VARCHAR(128),
    tool_id VARCHAR(128) NOT NULL,
    status VARCHAR(32),
    validation_status VARCHAR(32) DEFAULT 'not_validated',
    hypothesis TEXT,
    expected_evidence_type VARCHAR(128),
    params JSONB,
    depends_on_artifacts JSONB,
    output_artifacts JSONB,
    detail TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Review 决策状态
CREATE TABLE review_decisions (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(64) NOT NULL REFERENCES cases(id),
    source_ref VARCHAR(256) NOT NULL,  -- e.g. "visual_findings:fig-4-b-copy-move"
    status VARCHAR(32) DEFAULT 'open',  -- open/resolved/dismissed/needs_author_response
    note TEXT DEFAULT '',
    decided_by VARCHAR(64),
    decided_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(case_id, source_ref)
);

-- SSCD 图像向量（pgvector）
CREATE TABLE image_embeddings (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(64) NOT NULL REFERENCES cases(id),
    panel_id VARCHAR(128) NOT NULL,
    figure_id VARCHAR(128),
    image_path TEXT NOT NULL,
    embedding vector(512),
    indexed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_image_embeddings_hnsw
ON image_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE INDEX idx_image_embeddings_case
ON image_embeddings (case_id);

-- Tool Registry seed 表
CREATE TABLE tool_registry (
    tool_id VARCHAR(128) PRIMARY KEY,
    step_key VARCHAR(128) NOT NULL,
    title TEXT,
    source TEXT,
    description TEXT,
    deterministic BOOLEAN DEFAULT TRUE,
    agent_selectable BOOLEAN DEFAULT FALSE,
    input_artifacts JSONB,
    output_artifacts JSONB,
    parameter_defaults JSONB,
    param_schema JSONB,
    execution_phase VARCHAR(32)
);
```

### Review Queue 聚合视图（无独立表）

Review 项不存储在数据库中，每次请求时从已有 artifact 实时计算：

```python
def list_review_items(db: Session, case_id: str, workdir: Path) -> dict:
    """从 artifact 聚合 review 建议，合并 DB 中的决策状态。"""
    items = []
    items.extend(_from_visual_findings(workdir))      # visual/findings.json
    items.extend(_from_pair_forensics(workdir))        # source_data/pair_forensics.json
    items.extend(_from_agent_review(workdir))          # agents/review.json

    decisions = {
        d.source_ref: d
        for d in db.query(ReviewDecision)
            .filter(ReviewDecision.case_id == case_id)
            .all()
    }
    for item in items:
        dec = decisions.get(item["source_ref"])
        item["decision"] = dec.to_dict() if dec else None

    items.sort(key=lambda x: RISK_ORDER.get(x["risk_level"], 99))
    return {"items": items}
```

`source_ref` 格式：`"visual_findings:fig-4-b-copy-move"`、`"pair_forensics:fixed-ratio-col-3-7"`。

### Investigation Board 数据源

左栏数据源：`investigation_records` 表（从 `investigation_rounds.jsonl` 迁移而来）。

展示规则：

- 按 `round_id` 分组
- `metadata.trigger` 区分来源（`"web_manual"` / `"cli_orchestrator"` / `"agent_investigation"`）
- `output_artifacts` 指向的文件不存在时标记 `status=failed`，显示错误信息
- 详情区展示 tool 执行结果（relationships、scores、mask overlay）

### Visual Forensics 两步流程

```text
Step 1: SSCD 预筛（纯 PyTorch，不跑 Docker）
  - 对所有 panels 提取 SSCD 512-dim embedding
  - pgvector HNSW 查询相似 panel 对（cosine similarity > threshold）
  - 前端展示可疑 panel 对列表（带相似度分数和缩略图）

Step 2: SILA Dense 精确检测（跑 Docker，按需触发）
  - 用户对 Step 1 筛出的子集选择是否跑 SILA dense
  - 只发送选中的 panel IDs → 后端执行 Docker 容器
  - 结果写入 investigation_records + output artifacts
```

## API 设计

### 已有 endpoints（保持语义，重写实现）

| Method | Path | 变更 |
|---|---|---|
| GET | `/api/health` | 改为查 PostgreSQL 连接 |
| GET | `/api/cases` | JSON 文件扫描 → SQL query |
| POST | `/api/cases` | 同上 |
| GET | `/api/cases/{id}` | 同上 |
| POST | `/api/cases/{id}/inputs` | 文件存储不变，metadata 进 DB |
| POST | `/api/cases/{id}/runs` | daemon Thread → BackgroundTask + ThreadPoolExecutor |
| GET | `/api/cases/{id}/runs/{runId}` | SQL query |
| GET | `/api/cases/{id}/runs/{runId}/events` | SQL query |
| GET | `/api/cases/{id}/artifacts` | SQL 查 artifact metadata + 文件路径解析 |
| GET | `/api/cases/{id}/artifacts/{name}` | 文件读取不变 |
| GET | `/api/cases/{id}/report/html` | 文件读取不变 |
| GET | `/api/cases/{id}/visual/figures` | 不变 |
| GET | `/api/cases/{id}/visual/panels` | 不变 |
| GET | `/api/cases/{id}/visual/relationships` | 不变 |
| GET | `/api/cases/{id}/visual/findings` | 不变 |
| GET | `/api/cases/{id}/visual/images/{path}` | 不变 |
| GET | `/api/cases/{id}/investigations` | JSONL 读取 → SQL query |
| POST | `/api/cases/{id}/investigations` | 保持手动触发 SILA dense |

### 新增 endpoints（8 个）

| Method | Path | 职责 | 优先级 |
|---|---|---|---|
| GET | `/api/cases/{id}/review-items` | 聚合视图：从 artifacts 计算 review 建议 + 合并 DB 决策状态 | P1 |
| POST | `/api/cases/{id}/review-items/{source_ref}/decision` | 写入/更新人工复核决策到 review_decisions 表 | P1 |
| POST | `/api/cases/{id}/embeddings/index` | 触发 SSCD embedding 提取（BackgroundTask），写入 image_embeddings 表 | P1 |
| GET | `/api/cases/{id}/embeddings/status` | 查询索引状态（是否已完成、已索引 panel 数） | P1 |
| GET | `/api/cases/{id}/similarity` | 查 pgvector 相似 panel 对（query params: panel_id, top_k, threshold） | P1 |
| GET | `/api/tools/catalog` | 从 tool_registry 表返回可 investigation 工具列表 | P1 |
| GET | `/api/cases/{id}/visual/graph` | 轻量视觉关系图（nodes + edges from relationships + findings） | P2 |
| GET | `/api/tools/health` | Docker/GPU/model 健康检查 | P2 |

### API 总计

- 已有 endpoints 重写：18 个（实现从 JSON/文件迁移到 SQL，语义不变）
- 新增 P1 endpoints：8 个
- 新增 P2 endpoints：2 个
- 总计：28 个（原计划 20+ 新 endpoint，现砍到 8 个新增）

## 后端重构范围

### 重写文件

| 文件 | 当前行数 | 变更 |
|---|---|---|
| `web/backend/veritas_web/app.py` | 319 | **全部重写**：FastAPI app + router，路由从 if-chain 改为 FastAPI path operations |
| `web/backend/veritas_web/case_store.py` | 232 | **全部重写**：JSON 文件 → SQLAlchemy models + session management |
| `web/backend/veritas_web/runner.py` | 162 | **全部重写**：daemon Thread → BackgroundTasks + ThreadPoolExecutor(max_workers=3) |
| `web/backend/veritas_web/auth.py` | 288 | **重写**：手动 header 解析 → FastAPI Depends + OAuth2PasswordBearer |
| `web/backend/veritas_web/investigations.py` | 207 | **重写**：JSONL 读写 → SQL queries，保持 WebInvestigationService 接口 |
| `web/backend/veritas_web/artifacts.py` | 108 | **改造**：文件路径解析不变，artifact metadata 进 DB |
| `web/backend/veritas_web/models.py` | 104 | **重写**：dataclass → SQLAlchemy declarative models + Pydantic schemas |

### 新增文件

| 文件 | 职责 |
|---|---|
| `web/backend/veritas_web/database.py` | PostgreSQL engine + session factory + pgvector setup |
| `web/backend/veritas_web/review_queue.py` | Review 聚合视图函数 + decision CRUD |
| `web/backend/veritas_web/embeddings.py` | SSCD model 加载 + embedding extraction + pgvector upsert + similarity query |
| `web/backend/veritas_web/tool_catalog.py` | Tool Registry DB seed + catalog query |
| `web/backend/veritas_web/dependencies.py` | FastAPI Depends：get_db、get_current_user、require_case_access |
| `web/backend/veritas_web/routers/cases.py` | Cases router |
| `web/backend/veritas_web/routers/artifacts.py` | Artifacts router |
| `web/backend/veritas_web/routers/investigations.py` | Investigations router |
| `web/backend/veritas_web/routers/visual.py` | Visual endpoints router |
| `web/backend/veritas_web/routers/review.py` | Review items router |
| `web/backend/veritas_web/routers/embeddings.py` | Embeddings + similarity router |
| `web/backend/veritas_web/routers/tools.py` | Tool catalog router |

### Engine 层改造

| 模块 | 变更 | 理由 |
|---|---|---|
| `engine/investigation/opencode_agent.py`（1553 行） | **拆分**为 `planner.py`（investigation plan prompt + validation）、`role_runners.py`（ClaimExtractor/SourceDataAuditor/JudgeAgent）、`validators.py`（JSON extraction + schema validation）、`legacy.py`（兼容适配） | 当前 1553 行单体文件是最大的维护债 |
| `engine/static_audit/orchestrator.py` | **不改内部**，改接口：`run_static_audit()` 封装为 FastAPI BackgroundTask 可调用的 async wrapper | 内部状态机 3500+ 行，重写风险高 |
| `engine/static_audit/investigation.py` | InvestigationRecord → **SQLAlchemy model**，JSONL read/write 函数保留为 migration utility | 数据模型进 DB |
| `engine/tools/registry.py` | `TOOLS` dict → **DB seed**（startup 时从 ToolDefinition 写入 tool_registry 表），`coerce_tool_params` 保持 | 工具元数据进 DB |
| `engine/investigation/context_pack.py` | **不改** | 已有 9 个单测，接口清晰 |
| `engine/investigation/agent_step_runner.py` | **不改** | 已有 11 个单测，接口清晰 |
| `engine/static_audit/paths.py` | **保留**，artifact 元数据（exists/status/size）进 DB | 文件系统路径不变 |
| `engine/static_audit/schemas/` | **迁移到 Pydantic v2**（如果当前是 v1） | FastAPI 强依赖 Pydantic v2 |

### 不改动

- `cli/`：CLI 入口不变，内部调用 engine 接口
- `runtime/`：一级产品原语，不移到 engine 下
- `engine/static_audit/tools/`（detection 工具实现）：不改内部逻辑
- `engine/static_audit/html_report/`：报告渲染不变
- `configs/`：opencode 配置不变
- `third_party/`：submodule 不变

## 前端改造

### 新页面（替换 PlaceholderPage）

| 页面 | 职责 | 数据源 |
|---|---|---|
| `InvestigationBoardPage.jsx` | 只读历史查看器：展示 investigation records + 执行结果 | `GET /investigations` |
| `ReviewQueuePage.jsx` | 聚合视图：review items 列表 + 决策操作 | `GET /review-items` + `POST /review-items/{ref}/decision` |
| `AdvancedLabPage.jsx` | **P1 不实现**，保持 PlaceholderPage | — |

### 升级页面

| 页面 | 变更 |
|---|---|
| `VisualForensicsPage.jsx` | 新增两步流程：SSCD 预筛按钮 → 相似 panel 对列表 → 选择子集 → 触发 SILA dense |
| `EvidenceWorkspacePage.jsx` | 升级展示 investigation records + review decisions |

### 前端 API 新增

```javascript
// review_queue.js
fetchReviewItems(caseId)
saveReviewDecision(caseId, sourceRef, { status, note })

// embeddings.js
triggerEmbeddingIndex(caseId)
getEmbeddingStatus(caseId)
fetchSimilarPanels(caseId, { panelId, topK, threshold })

// tools.js
fetchToolCatalog()
```

### 共用组件

```text
web/frontend/src/components/StatusBadge.jsx
web/frontend/src/components/PanelPairCard.jsx       # SSCD 相似 panel 对展示
web/frontend/src/components/ReviewItemCard.jsx      # Review 聚合项展示
web/frontend/src/components/InvestigationRecordCard.jsx  # Investigation record 展示
web/frontend/src/components/JsonInspector.jsx       # 只读 JSON 查看器
```

## SSCD Embedding 方案

### 模型

- **模型**：Meta SSCD `sscd_disc_mixup`（ResNet50-based，自监督 copy detection）
- **格式**：TorchScript (.pt)
- **Embedding 维度**：512
- **预处理**：Resize 224×224，ImageNet normalization
- **相似度**：Cosine similarity（L2-normalized embeddings 的 inner product）

### 工作流

```text
用户打开 Visual Forensics
  ↓
点击 "Index Panels"（触发 POST /embeddings/index）
  ↓
BackgroundTask:
  1. 读取 panel_evidence.json 获取所有 panel 路径
  2. 批量加载图片 → SSCD model → 512-dim embeddings
  3. pgvector UPSERT 到 image_embeddings 表
  4. 更新索引状态
  ↓
前端轮询 GET /embeddings/status
  ↓
索引完成后，前端自动调用 GET /similarity?threshold=0.85
  ↓
展示相似 panel 对列表（缩略图 + 相似度分数）
  ↓
用户选择可疑 panel 对 → 触发 SILA dense（POST /investigations）
```

### 性能估算

- 1071 panels × SSCD inference ≈ 2-5 分钟（GPU）/ 10-20 分钟（CPU）
- pgvector HNSW 查询 ≈ 毫秒级
- 索引只需跑一次（同一 case 的 panels 不变），结果持久化到 DB

### 降级策略

- SSCD model 下载失败或 PyTorch 不可用：退回到 dHash（已有实现）
- GPU 不可用：CPU fallback，但提示用户 "索引可能需要 10-20 分钟"
- Panel 数量 < 50：直接暴力 cosine，不建 HNSW 索引（pgvector 自动处理）

## 分阶段落地

### Phase 1: 后端重写 + 基础页面

**目标**：FastAPI + PostgreSQL 上线，已有 investigation/visual 能力在 Web 可见。

**后端**：

1. 新增 `database.py`：PostgreSQL engine + session + pgvector extension
2. 重写 `models.py`：SQLAlchemy declarative models
3. 重写 `app.py`：FastAPI app + routers
4. 重写 `case_store.py` → SQL queries
5. 重写 `runner.py` → BackgroundTasks + ThreadPoolExecutor
6. 重写 `auth.py` → FastAPI Depends
7. 重写 `investigations.py` → SQL queries
8. 改造 `artifacts.py` → SQL metadata + 文件路径

**Engine**：

9. `investigation.py` InvestigationRecord → SQLAlchemy model
10. `registry.py` TOOLS → DB seed
11. 拆分 `opencode_agent.py` → planner / role_runners / validators / legacy
12. Orchestrator 封装 async wrapper（不改内部）

**前端**：

13. `InvestigationBoardPage.jsx` 替换 PlaceholderPage
14. `ReviewQueuePage.jsx` 替换 PlaceholderPage
15. `api.js` 新增 review/embeddings/tools API calls

**测试**：

- 现有 `test_web_investigations.py` 适配新实现
- PostgreSQL schema migration test
- FastAPI endpoint smoke tests
- 前端 `npm run lint && npm run build`

**验收标准**：

- `make web-backend` 启动 FastAPI，连接 PostgreSQL
- 创建 case → 上传 → 启动 audit → 查看 artifacts → 查看 investigations → 全部走通
- Investigation Board 展示已有 investigation records
- Review Queue 展示已有 review 建议

### Phase 2: SSCD 预筛 + Visual Forensics 两步流程

**目标**：用 SSCD + pgvector 替代 dHash，解决 1071 panels 性能瓶颈。

**后端**：

1. 新增 `embeddings.py`：SSCD model 加载 + embedding extraction + pgvector upsert
2. 新增 `GET /embeddings/index`、`GET /embeddings/status`、`GET /similarity` endpoints
3. SSCD model 下载和缓存机制

**前端**：

4. `VisualForensicsPage.jsx` 新增 "Index Panels" 按钮
5. 相似 panel 对列表展示（`PanelPairCard.jsx`）
6. 选择子集 → 触发 SILA dense

**测试**：

- SSCD embedding extraction fixture test
- pgvector similarity query test
- 端到端：index → similarity query → SILA dense on subset

**验收标准**：

- 1071 panels 索引完成
- 相似 panel 对查询 < 100ms
- 用户能只对筛出的子集跑 SILA dense

### Phase 3: Agent plan-next 评估

**前置条件**：Phase 1 + Phase 2 稳定运行，收集到内测用户反馈。

**评估问题**：

- 用户是否真的需要 Agent 建议下一步调查方向？
- 用户手动选 panels 的频率 vs 希望 Agent 推荐的频率？
- SSCD 预筛是否已经足够？

**如果确认需要**：

- 拆分 orchestrator `run_investigation_rounds()` 的 plan/execute 循环
- 新增 proposal 存储（investigation_records 表加 `approval_status` 字段）
- 新增 approval endpoint
- 不改数据模型，只加状态字段

## 测试矩阵

### 后端

```text
tests/unit/test_database.py              # PostgreSQL connection + pgvector
tests/unit/test_web_cases_sql.py         # Case CRUD via SQL
tests/unit/test_web_investigations_sql.py # Investigation records via SQL
tests/unit/test_web_review_queue.py      # Review aggregation + decisions
tests/unit/test_web_embeddings.py        # SSCD extraction + pgvector upsert
tests/unit/test_web_similarity.py        # Similarity query correctness
tests/unit/test_tool_registry_sql.py     # Tool catalog from DB
tests/unit/test_agent_planner.py         # Split opencode_agent.py planner module
tests/unit/test_agent_role_runners.py    # Split role runners
tests/unit/test_orchestrator_wrapper.py  # Async wrapper for orchestrator
```

### 已有测试适配

```text
tests/unit/test_web_investigations.py    # 适配 SQL 实现
tests/unit/test_web_visual_endpoints.py  # 适配 FastAPI TestClient
tests/unit/test_tool_registry.py         # 适配 DB seed
tests/unit/test_agent_step_runner.py     # 不改
tests/unit/test_agent_context_pack.py    # 不改
```

### 前端

```bash
npm run lint
npm run build
```

### E2E（后续 Playwright）

```text
创建 case → 上传 PDF → 启动 audit → 等待完成
→ 打开 Investigation Board → 查看 investigation records
→ 打开 Visual Forensics → Index Panels → 查看相似 panel 对
→ 选择子集 → 触发 SILA dense → 查看结果
→ 打开 Review Queue → 查看 review items → 写入 decision
```

## 存储布局

### PostgreSQL（新增）

```text
Database: veritas
  Tables:
    cases, runs, run_events
    investigation_records
    review_decisions
    image_embeddings (pgvector)
    tool_registry
```

### 文件系统（不变）

```text
outputs/<case_id>/research-integrity-audit/
  investigation/
    investigation_rounds.jsonl    # 保留为 CLI 产出，migration utility 读入 DB
    web/<action_id>/              # SILA dense 输出 artifacts
  visual/
    evidence.json, panel_evidence.json, findings.json, relationships.json
  reports/
    static_audit_bundle.json, final_audit_report.html
  agents/
    review.json, context_pack_*.json

web_data/                         # Phase 1 后废弃（迁移到 PostgreSQL）
```

### 迁移工具

```python
# scripts/migrate_web_data_to_postgres.py
# 读取 web_data/cases/*/case.json → INSERT INTO cases
# 读取 web_data/cases/*/runs/*/run.json → INSERT INTO runs
# 读取 outputs/*/investigation/investigation_rounds.jsonl → INSERT INTO investigation_records
```

## 非目标（不变）

- 不把 ELIS 主服务嵌入 Veritas
- 不让 Agent 直接执行重型工具
- 不把 visual tool 输出写成最终科研诚信判定
- 不在 audit-paper baseline 中全量运行 SILA dense
- 不自动修改论文、Source Data 或代码
- P1 不引入 Celery/Redis
- P1 不引入 Milvus
- P1 不做 Agent plan-next / approval workflow
- P1 不实现 Advanced Lab 页面

## 风险清单

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| PostgreSQL schema 设计遗漏字段 | 中 | 需要 migration | 先 freeze schema 再写代码 |
| opencode_agent.py 拆分引入回归 | 中 | Agent role 调用失败 | 拆分后跑全量单测 + e2e test |
| SSCD model 体积过大（~400MB） | 低 | 首次启动慢 | 懒加载 + 缓存到本地 |
| pgvector 扩展在某些 PostgreSQL 版本不可用 | 低 | 无法建向量索引 | Docker PostgreSQL 镜像预装 pgvector |
| FastAPI 重写遗漏已有 endpoint 行为 | 中 | 前端调用失败 | 逐个 endpoint 写 smoke test |
| 前端 api.js 适配新 response 格式遗漏 | 低 | 页面报错 | 前端 TypeScript 类型定义对齐 Pydantic schema |

## 最小可验收闭环

Phase 1 完成后：

```text
make web-backend  # FastAPI + PostgreSQL
→ 浏览器打开 http://127.0.0.1:5173
→ 创建 case → 上传 PDF → 启动 audit
→ 等待 audit 完成
→ 打开 Investigation Board → 看到 investigation records + 执行结果
→ 打开 Review Queue → 看到 review 建议 → 写入 decision
→ 打开 Visual Forensics → 看到 panels + findings
```

Phase 2 完成后：

```text
→ Visual Forensics 中点击 "Index Panels"
→ 等待 SSCD 索引完成
→ 看到相似 panel 对列表
→ 选择子集 → 触发 SILA dense
→ 查看 SILA dense 结果
```
