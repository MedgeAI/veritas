# Veritas Linus-style Code Review

评审基准：当前磁盘 worktree，不是某个干净 commit。`git status` 显示大量未提交修改和未跟踪文件，所以以下结论评价的是当前状态。别拿 README 里的历史“已通过”当挡箭牌，当前代码必须按当前状态负责。

## 一句话结论

这是一个有正确产品嗅觉、也有不少硬工程动作的研究型原型；但当前实现已经长出几个大肿瘤：`orchestrator.py`、HTML report renderer、Source Data/visual forensics 工具函数复杂度爆炸，分层边界被 `engine -> web` 反向依赖打穿，而且当前 worktree 连 `ruff` 都过不了。这个项目值得学它的证据契约和工具注册表，不值得学它把流程编排堆成 4500 行单文件的习惯。

评分：**5.5 / 10**

同类项目水平：**中**。在科研审查原型里偏高，因为它有明确证据链、工具注册表、fixture 测试和 Web owner gate；在生产级审计系统里偏低，因为 lint 失败、主流程复杂度失控、CI 缺失、重型工具和 Agent fallback 边界还不够硬。

## 验证命令与结果

| 项目 | 命令 | 结果 |
|---|---|---|
| 圈复杂度 | `UV_CACHE_DIR=.uv-cache uv run radon cc cli engine runtime protocols web/backend scripts -s -a -n C --exclude engine/static_audit/upstream/*` | 150 个 C 或更差 block。热点集中在 `engine/static_audit/orchestrator.py`、`engine/static_audit/html_report/_core.py`、Source Data/visual 工具。 |
| Maintainability Index | `UV_CACHE_DIR=.uv-cache uv run radon mi cli engine runtime protocols web/backend scripts -s --exclude engine/static_audit/upstream/*` | 多数文件 A，但关键文件是 C 或 0：`orchestrator.py`、`source_data_pair_forensics.py`、`source_data_findings.py`、`visual_finding_pipeline.py`、`html_report/_core.py`。 |
| 认知复杂度 | `UV_CACHE_DIR=.uv-cache uv run --with cognitive-complexity ...` | 874 个函数/方法。Top 1 是 `generate_report`，认知复杂度 124。Top 2 是 `_run_static_audit_from_args`，87。 |
| import 图 | `UV_CACHE_DIR=.uv-cache uv run pydeps engine -o doc/veritas-pydeps-engine.svg --noshow --max-bacon 2` | 已生成：[veritas-pydeps-engine.svg](veritas-pydeps-engine.svg)。图里能看到 `engine.static_audit.tools.provenance_graph` 依赖 `web.backend.veritas_web.database/models`。 |
| lint | `UV_CACHE_DIR=.uv-cache PYTHONPATH=. uv run ruff check cli engine runtime protocols web/backend tests scripts` | **失败，10 个错误**，其中有未定义变量，不是单纯格式问题。 |
| tests collection | `UV_CACHE_DIR=.uv-cache PYTHONPATH=. uv run pytest --collect-only -q` | 433 tests collected。测试规模不错。 |
| full pytest | `UV_CACHE_DIR=.uv-cache PYTHONPATH=. uv run pytest -q` | 跑了 5 分钟以上仍未完成，人工中断。不能认定失败，但反馈链路太慢。 |

## 优点

### 1. Tool Registry 是真正的架构骨架

`engine/tools/registry.py:24` 定义了 `ExecutionPhase`，把 mandatory baseline、conditional baseline、agent selectable、report only 分开；`ToolDefinition` 在 `engine/tools/registry.py:44` 记录 `tool_id`、输入 artifact、输出 artifact、默认参数和 param schema。这比“让 Agent 想跑什么就跑什么”的玩具系统强得多。

更重要的是，`validate_investigation_tool_action()` 在 `engine/tools/registry.py:581` 明确拒绝未知 tool、非 agent-selectable tool、非 deterministic tool，并强制 `hypothesis`、`depends_on_artifacts`、`expected_evidence_type`。这是对 Agent 的必要约束。很多所谓 AI 工程项目在这里直接裸奔，这个项目没有。

### 2. Evidence First 不是只写在文档里

视觉证据有 canonical schema。`VisualFinding` 在 `engine/static_audit/visual_schemas.py:222` 明确要求 finding id、category、risk level、panel refs、relationship id、score，并在 `validate()` 里检查 score 范围和禁用语言。这是对“报告不能直接变成 LLM 胡说八道”的实际防线。

`AgentStepRunner.run()` 在 `engine/investigation/agent_step_runner.py:49` 统一处理 opencode 调用、超时、stderr 分类、JSON extraction、schema validation、retry 和 log artifact。这是对 LLM 边界的正确抽象。虽然它也开始变复杂了，但方向是对的。

### 3. Web 权限边界有基本工程意识

Web 不是完全裸接口。`CaseStore.get_case(..., user_id=...)` 做 owner check；测试里有 cross-user isolation。视觉图片读取在 `web/backend/veritas_web/artifacts.py:63` 通过 `resolve()` 确保路径留在 workdir 下。上传入口 `web/backend/veritas_web/case_store.py:260` 只取 `Path(filename).name` 再 `safe_id`。这些都是具体实现，不是口号。

### 4. 测试不是摆设

`pytest --collect-only` 收集到 433 个测试，覆盖 Agent context pack、tool registry、source data forensics、visual schemas、Web auth、case isolation、visual endpoints、fixture/golden 等。测试结构也至少分了 unit/integration/e2e。对于研究原型，这个规模比同类项目常见水平高。

### 5. 失败隔离意识存在

重型视觉工具、Agent material plan、investigation fallback、MinerU 缺 token 等路径都有 skipped/warning/limitations 的表达。这个产品领域不能把“没跑成”伪装成“没问题”，代码至少在朝正确方向走。

## 致命问题

### 1. 当前 worktree 不能通过 lint，而且有真实运行时错误

`ruff` 失败里最严重的是这几个：

```text
engine/static_audit/orchestrator.py:4048 F821 Undefined name `model`
engine/static_audit/orchestrator.py:4049 F821 Undefined name `opencode_bin`
engine/static_audit/orchestrator.py:4067 F821 Undefined name `logger`
engine/static_audit/tools/overlap_reuse.py:627 F821 Undefined name `argparse`
```

对应源码在 `engine/static_audit/orchestrator.py:4043` 调用 `run_source_data_verdict()` 时传了 `model=model` 和 `opencode_bin=opencode_bin`，但这个作用域只有 `args.agent_model` 和 `args.opencode_bin`。异常处理里又调用未定义的 `logger`。这不是“代码风格”，这是会在 Source Data verdict 路径上直接炸的 bug。

`engine/static_audit/tools/overlap_reuse.py:626` 的 CLI `main()` 使用 `argparse.ArgumentParser`，但文件顶部没有 import `argparse`。这说明新增命令入口没有被 lint 或 CLI test 门禁挡住。

改进建议：先让 `ruff check` 成为不可绕过门禁。未定义变量这种东西如果能进主分支，说明流程没有门。

### 2. 主流程编排文件已经失控

`engine/static_audit/orchestrator.py` 当前 4581 LOC，`_run_static_audit_from_args()` 从 `engine/static_audit/orchestrator.py:3646` 开始，radon 圈复杂度 **F(63)**，认知复杂度 **87**。`generate_report()` 从 `engine/static_audit/orchestrator.py:2126` 开始，radon **F(103)**，认知复杂度 **124**。

这就是典型的“所有业务状态都往一个函数里塞”。现在它还能跑，是因为开发者记得每个 if/else 是干什么的；再过几轮需求，没人会记得。

改进建议：不要先抽象成花哨框架。先拆最硬的边界：

- `material_plan_stage.py`
- `pdf_parse_stage.py`
- `source_data_stage.py`
- `visual_stage.py`
- `investigation_stage.py`
- `report_stage.py`

每个 stage 输入 `AuditContext`，输出 `StageResult + artifacts`。现在 `steps`、`agent_manifest`、`workdir`、`source_data_dir` 到处飘，应该收进一个显式 context。

### 3. HTML report renderer 是第二个大泥球

`engine/static_audit/html_report/_core.py` 当前 3684 LOC。`_parameterized_benign_explanation()` 在 `engine/static_audit/html_report/_core.py:2631` radon **F(85)**，认知复杂度 **78**；`context_aware_review_question()` radon **F(61)**；`render_static_audit_html()` radon **F(45)**。

报告层本来应该消费结构化 artifact，做模板渲染。现在它在做大量业务归类、良性解释拼接、pattern 聚合、claim impact matrix。换句话说，业务规则正在从 engine 漏进 presentation。AGENTS.md 明确说业务规则不要散落在报告模板里；当前实现已经踩线。

改进建议：把 report view model 生成从 HTML 字符串拼接中拆出来，写成 `report_model_builder.py`，让 HTML 只渲染 `ReportViewModel`。否则报告里的规则会变成第二套事实源。

### 4. 分层边界被 engine -> web 依赖打穿

pydeps 图显示 `engine.static_audit.tools.provenance_graph` 依赖 `web.backend.veritas_web.database` 和 `web.backend.veritas_web.models`。源码在 `engine/static_audit/tools/provenance_graph.py:182` 直接 import：

```python
from web.backend.veritas_web.database import get_db_session
from web.backend.veritas_web.models import ImageEmbeddingModel
```

这和项目文档的单向边界相反。`engine` 是领域/工具层，`web` 是展示/API 层。engine 写 pgvector 可以，但不能 import web 的 database model。否则 CLI 审计、Web 后端、DB schema、embedding persistence 全绑死。

改进建议：定义一个 engine 侧 port，例如 `EmbeddingSink` 或 `ProvenanceEmbeddingStore`，默认写 JSON artifact；Web 侧提供 adapter 把 artifact 同步进 DB。不要让静态审查工具知道 FastAPI app 的 ORM model。

### 5. 测试反馈链路太慢，当前全量测试不适合日常门禁

433 个 tests 是优点，但 `pytest -q` 跑了 5 分钟以上没有完成，我中断了。不是说测试失败，而是说反馈太慢。再加上 `ruff` 明确失败，当前工程实践不够硬。

改进建议：把测试命令拆成明确门禁：

- `test-fast`: 不加载模型、不跑外部工具、不跑重型视觉，目标 30 秒内。
- `test-integration`: Web/SQLite/CLI smoke。
- `test-visual`: OpenCV/fixture-heavy。
- `test-model`: TruFor/SSCD/SILA/Docker/GPU，默认不进快速门禁。

## 一般问题

### 1. 复杂度热点太多，不只是一个函数坏了

radon C 或更差热点包括：

- `engine/static_audit/orchestrator.py:2126 generate_report`，F(103)
- `engine/static_audit/orchestrator.py:3646 _run_static_audit_from_args`，F(63)
- `engine/static_audit/orchestrator.py:3004 collect_claims_and_findings`，F(47)
- `engine/static_audit/html_report/_core.py:2631 _parameterized_benign_explanation`，F(85)
- `engine/static_audit/html_report/_core.py:2260 context_aware_review_question`，F(61)
- `engine/static_audit/tools/source_data_pair_forensics.py:754 cross_block_paired_diff_findings`，E(34)
- `engine/static_audit/tools/provenance_graph.py:414 build_provenance_graph`，E(32)
- `engine/static_audit/tools/visual_finding_pipeline.py:557 build_visual_findings`，D(30)
- `engine/static_audit/tools/source_data_findings.py:781 claim_mappings`，D(28)

这说明问题不是“一个文件偶然长了”。模式是：业务规则、artifact glue、report text、fallback、工具调用、异常处理混在同一个函数里。

### 2. registry 很好，但 param coercion 已经开始变成 if/else 菜单

`coerce_tool_params()` 从 `engine/tools/registry.py:615` 开始，用一串 `if tool_id == ...` 做参数归一化。现在还能读，但每加一个工具就往这里塞一段。registry 作为 source of truth 是好事，但 coercion 应该挂到 tool definition 或 per-tool schema handler 上，否则这个文件会从“注册表”变成“万能 switchboard”。

改进建议：保留 registry，但让 `ToolDefinition` 支持 `coerce_params: Callable` 或 `param_model`。不要引入大框架，先把每个 tool 的 coercion 放回相邻 tool module。

### 3. 依赖管理有锁，但运行依赖太重且缺少可选组

`pyproject.toml` 把 FastAPI、SQLAlchemy、torch、torchvision、OpenCV、scikit-image、matplotlib、pgvector、psycopg2、timm 都放在主依赖。对于 CLI-first 工具，这意味着最小安装会拉一堆视觉/深度学习/Web/DB 依赖。内部 demo 可以忍，生产部署和 CI 会痛。

改进建议：拆 extras 或 dependency groups：

- `core`: CLI、schemas、Source Data、basic reports。
- `web`: FastAPI/SQLAlchemy/auth。
- `visual`: OpenCV/scikit-image/Pillow。
- `models`: torch/torchvision/timm/TruFor/SSCD。
- `pg`: psycopg2/pgvector。

### 4. 文档状态和代码现实有漂移

README 仍有“stdlib backend”的历史描述，但代码已经是 FastAPI。README/AGENTS 提到历史 394 tests pass，而当前 collection 是 433 tests，当前 lint 失败。文档很多，方向也清楚，但它已经不能完全代表当前代码状态。

改进建议：把“当前状态”从叙述文档中抽出来，生成或维护一个短的 `STATUS.md`，只记录可验证事实：tests collected、last audit command、known failing checks、tool status。

### 5. 异常吞掉太多，容易把 bug 包装成 limitation

项目需要失败隔离，但 `except Exception` 分布很广。比如 `_relocate_mineru_outputs()` 在 `engine/static_audit/orchestrator.py:4522` 失败后直接 `pass`。视觉/DB/embedding 相关路径也有大量 warning/fallback。对外部工具，这是合理的；对内部数据迁移和 artifact path update，这会藏 bug。

改进建议：区分 `ExpectedExternalFailure` 和 `InternalInvariantViolation`。外部失败写 limitation；内部 invariant 失败应该 fail fast 或至少写 manifest 中的 hard warning。

### 6. runtime executor 太薄，和 audit-paper 主链路脱节

`runtime/executors/subprocess_executor.py` 只是 `shlex.split(request.command)` 加 `subprocess.run()`，只保留 stdout/stderr tail。AGENTS 里说 runtime 要记录 command manifest、stdout/stderr、exit code、runtime seconds、result files、file hashes。当前 runtime 和 `audit-paper` 里的 `run_command()` 是两套世界。

改进建议：把 `run_command()` 的证据记录语义下沉到 runtime，audit-paper 只消费 runtime result。否则 runtime 永远是摆设。

### 7. 没看到 CI

`.github/` 不存在。可能你们在别的系统跑 CI，但仓库里看不到。对这个项目目前状态，这很要命：一个未定义变量已经进了工作树，说明没有可靠门禁。

改进建议：哪怕只有最小 CI，也要有：

```text
ruff check
pytest --collect-only
pytest tests/unit/test_tool_registry.py tests/unit/test_agent_step_runner.py tests/unit/test_static_audit_models.py
```

## 性能与潜在风险

1. `audit-paper` pipeline 是长同步流程。Web 里 `AuditRunner` 用 `ThreadPoolExecutor(max_workers=3)` 直接跑 `run_static_audit()`。内测可以，生产不行。进程重启会靠 heartbeat recovery 标记 interrupted，但没有真正 job queue、resource scheduling、cancellation、per-tool quota。

2. 视觉工具可能是 O(N^2) 候选对扩张。registry 有 `max_candidate_pairs`、`max_relationships` 这种边界，这是好事；但只要某个路径绕过 registry 或 fallback 参数写死不合理，CPU/GPU 会被打爆。

3. `provenance_graph` 同时做 embedding、JSON artifact、可选 DB write、RootSIFT subprocess、MST、cleanup。这个函数一旦慢或失败，很难定位是哪一层。性能观测点应该按 phase 记录。

4. Source Data 工具复杂度高，且大量逻辑在单函数内做启发式判断。误报/漏报风险不是靠再堆 if/else 解决的，需要 golden fixtures 和每类 detector 的 precision/recall 回归集。

5. 依赖里包含 torch/vision/model 权重路径。没有清晰 optional install 的情况下，CI、Docker image、CPU-only 环境都会变重。

## 是否值得学习

**值得学，但只学两块：**

1. 学它的产品建模：technical finding 必须回指 evidence，Agent 只能结构化输出，Tool Registry 控制可执行工具。这是正确方向。
2. 学它的测试意图：schema、tool registry、Agent runner、visual fixtures、Web owner isolation 都有测试。

**不要学这几块：**

1. 不要学 4500 行 orchestrator。
2. 不要学 3600 行 HTML renderer 里混业务规则。
3. 不要学 engine 反向 import web ORM。
4. 不要学“当前 lint 失败但继续堆功能”。

## 是否适合用于生产

**不适合开放式生产。**

原因很简单：当前 worktree 有未定义变量，CI 缺失，主流程复杂度太高，Web runner 仍是本地 thread pool，重型视觉/Agent 工具的资源隔离和失败语义还不够硬。

**适合的场景：**

- 实验室内部、受控输入、人工复核在环的 demo 或内测。
- PI 提交论文和 Source Data 后，由工程人员代跑并解释 limitations。
- 小规模 batch，不要求多租户隔离、SLA、远程 worker、严格审计日志不可篡改。

**不适合的场景：**

- 面向外部用户的 SaaS。
- 自动判定科研诚信。
- 无人工复核的批量裁决。
- 需要稳定 GPU/模型服务调度的生产视觉取证平台。

## 前端 React 组件级深审（补充）

前端单独评分：**5.0 / 10**。

前端同类水平：**中偏低**。它比随手糊的 demo 强：Vite、lazy loading、统一 API client、ErrorBoundary、基本可访问性和视觉取证工作台骨架都有。但它还不是一个可靠的 React 应用：核心视觉页 876 行，组件边界被打穿，交互路径没有测试，已经出现“按钮把 click event 当 panel list 传给 API”的低级 bug。

### 前端验证命令与结果

| 项目 | 命令 | 结果 |
|---|---|---|
| React lint | `npm run lint`（目录：`web/frontend`） | 通过。ESLint 至少能挡住基础语法和 hook 规则问题。 |
| React build | `npm run build`（目录：`web/frontend`） | 通过。主 bundle `221.53 kB / gzip 69.64 kB`，最大页面 chunk `VisualForensicsPage` 为 `27.62 kB / gzip 8.32 kB`。 |
| React tests | `npm run test -- --run`（目录：`web/frontend`） | **失败**：`No test files found, exiting with code 1`。不是测试红，是根本没有组件测试。 |
| 测试文件扫描 | `find web/frontend/src -type f \( -name '*.test.*' -o -name '*.spec.*' \) -print` | 无输出。`vitest` 和 Testing Library 装了，但没有被用起来。 |

### 前端优点

1. **代码分割是做了的，不是全塞进首屏。** `AppLayout.jsx:283` 根据 page switch 渲染各页面，`App.jsx:1` 保持薄入口，Vite build 也确认 `VisualForensicsPage` 被拆成独立 chunk。对 P1 工作台来说，这个方向对。

2. **API 入口集中在 `services/api.js`。** `listCases()`、`startRun()`、visual endpoints、review queue、embedding endpoints 都在同一个 client 文件里。虽然 client 还粗糙，但至少没有让每个组件自己拼 fetch。

3. **App shell 有基本产品意识。** `AppLayout.jsx:127` 维护 workspace、case/run 选择、backend health；`AppLayout.jsx:181` 每 5 秒检查 backend health；`AppLayout.jsx:201` 同步 URL/localStorage。这对内测工作台是实用的，不是纯静态壳子。

4. **视觉取证工作流没有无脑全量跑重型工具。** `VisualForensicsPage.jsx:188` 手动触发 `visual.copy_move_dense`，并带 `max_panels` 参数。这符合项目边界：SILA dense 是重型调查工具，不该 baseline 全量乱跑。

5. **部分长列表和图片加载有最低限度的性能意识。** figure/panel 图片用了 `loading="lazy"`，报告 iframe 用了 `content-visibility:auto`，这比完全不管滚动性能要好。

### 前端致命问题

1. **`Run SILA Dense` 按钮是坏的，原因很蠢但后果很实在。**

`ManualInvestigationPanel` 在 `VisualForensicsPage.jsx:534` 写的是：

```jsx
<button type="button" className="btn-primary" onClick={onRunDense} disabled={disabled}>
```

父组件传入的是 `onRunDense={runDenseInvestigation}`（`VisualForensicsPage.jsx:400`），而 `runDenseInvestigation(panelIds = selectedPanelList)` 在 `VisualForensicsPage.jsx:188` 期待第一个参数是 panel id 数组。

React 点击时会把 click event 作为第一个参数传进去。于是 `panelIds` 变成 SyntheticEvent，不是数组。`panelIds.length === 0` 在 `VisualForensicsPage.jsx:189` 不会拦住，因为 event 没有数组 length；随后 `panel_ids: panelIds` 在 `VisualForensicsPage.jsx:195` 被塞进 JSON body。结果要么 JSON 序列化炸，要么发出垃圾 payload。这个路径没有测试，所以它能安静地躺在代码里。

改法很简单：子组件写 `onClick={() => onRunDense()}`，或者父组件传 `onRunDense={() => runDenseInvestigation(selectedPanelList)}`。再补一个 Testing Library 测试：选中两个 panel，点击按钮，断言 `startVisualInvestigation` 收到的是 `panel_ids: ['p1', 'p2']`，不是 event object。

2. **前端没有组件测试，关键工作流全靠手点。**

`npm run test -- --run` 直接报 `No test files found`。这在普通 CRUD 页也许还能忍；在这个项目里不行。视觉取证页、review queue、上传和报告预览都是面向“证据链”的交互，一旦 UI 发错 payload，后端可能记录一条看似合法但事实错误的 investigation。

最低限度要补：

- `VisualForensicsPage`：手动 dense investigation payload。
- `ReviewQueuePage`：保存 decision 后 selected item 刷新。
- `NewAuditPage`：没有 PDF 时拒绝启动；多文件上传失败时显示具体错误。
- `ReportCenterPage`：ready/pending/error 三态。
- `api.request`：JSON 错误、text 错误、network error。

3. **`VisualForensicsPage.jsx` 已经不是页面组件，是一锅状态机。**

这个文件 876 行。`VisualForensicsPage.jsx:45` 到 `:71` 一口气声明 figures、panels、relationships、findings、filters、selected panels、investigation records、artifact errors、dense params、overlap state、embedding state、similar pairs。`loadData()`、index polling、similarity search、dense investigation、figure grid、finding list、manual panel 都在同一个文件里。

这不是“组件大一点”。这是把数据获取、状态机、API mutation、错误语义和展示全塞一起。它已经导致上面的事件参数 bug。拆法不需要设计宇宙飞船：

- `useVisualArtifacts(caseId)`：figures/panels/relationships/findings/overlap/investigations。
- `useEmbeddingIndex(caseId)`：status、polling、similar pairs。
- `useDenseInvestigation(caseId, selectedPanelIds, maxPanels)`：run、records、errors。
- `FigurePanelGrid`、`VisualFindingList`、`ManualInvestigationPanel`、`SimilarityPanel` 分离展示。

拆完以后测试才有下手点。

### 前端一般问题

1. **`loadData()` 把失败吞成空数组，UI 会把“接口坏了”显示成“没有证据”。**

`VisualForensicsPage.jsx:82` 到 `:89` 对每个 artifact 请求都 `.catch(() => ({ ...: [] }))`。这会把 500、404、schema mismatch、权限错误全部伪装成空结果。对证据系统来说，这很危险：空证据和证据加载失败不是一回事。

改进：用 `Promise.allSettled`，每条 evidence lane 单独记录 `status/error`。缺 artifact 可以是 limitation；接口失败必须显示为加载失败，不能静默变成“未提取到 figure”。

2. **异步轮询没有取消语义，切 case 时可能写回旧状态。**

`handleIndexPanels()` 在 `VisualForensicsPage.jsx:157` 最多轮询 12 次，每次 `sleep(1500)`。`loadData()` 里 `getEmbeddingStatus(...).then(setEmbeddingStatus)` 在 `VisualForensicsPage.jsx:100` 也没有 await/cancel。用户切 case、卸载页面或触发新索引时，旧请求仍可写回新页面状态。

改进：给 API client 支持 `AbortController`，或者至少用 generation token：每次 caseId 改变递增 token，异步返回时只允许当前 token 写状态。

3. **上传实现不适合真实 Source Data。**

`NewAuditPage.jsx:71` 逐个文件顺序上传；`uploadInput()` 在 `services/api.js:67` 把文件转 base64；`fileToBase64()` 在 `services/api.js:187` 用 `FileReader.readAsDataURL()` 一次性读完整文件。PDF、Excel、ZIP、图片包稍微大一点，浏览器内存和 JSON body 都会变得难看。`NewAuditPage.jsx:155` 的 input 也只是 `multiple`，没有目录上传；虽然 `services/api.js:72` 读 `webkitRelativePath`，实际 UI 没开 `webkitdirectory`。

改进：上传改成 `multipart/form-data` 或 chunked upload；加 progress、cancel、失败重试；如果要支持 source-data 目录，就显式支持 directory input，并在后端保留受控的相对路径/去重策略，而不是只靠 basename。

4. **API client 还只是 demo 级别。**

`request()` 在 `services/api.js:32` 每个请求都塞 `Content-Type: application/json`，GET 也塞；没有 `credentials`、没有 auth token hook、没有 timeout/abort、没有重试策略。`getArtifactText()` 在 `services/api.js:97` 绕过共享错误解析。`visualImageUrl()` 在 `services/api.js:142` 只 strip leading slash，没有按 path segment 做 encode，路径里有空格、`#`、`?` 时 URL 行为会变脏。

改进：让 `request(path, { signal, headers, rawText })` 成为唯一入口；GET 不发 JSON content type；图片 path 用 `imagePath.split('/').map(encodeURIComponent).join('/')`。

5. **Review Queue 保存后用了旧闭包状态。**

`ReviewQueuePage.jsx:55` 先 `await loadData()`，然后 `ReviewQueuePage.jsx:57` 用旧的 `items.find(...)` 找更新项。React state 更新不是同步赋值，这里的 `items` 仍是旧闭包。`setSelectedItem()` 在 `:59` 又手动拼 decision，容易和后端真实返回脱节。

改进：让 `loadData()` 返回 fresh payload，或者保存接口直接返回更新后的 item；selected item 根据 `selectedItem.source_ref` 从 fresh items 中派生。

6. **Overlap graph 是临时 SVG，不是可扩展组件。**

`OverlapGraph.jsx:14` 构造了 `panelMap` 但没用。`OverlapGraph.jsx:71` 到 `:73` 每条 edge 都 `nodes.find()` 两次，是 O(E*N)。`OverlapGraph.jsx:76` 用 index 做 key。布局是固定圆形，节点稍多就文字互相盖住。你们已经装了 `d3`，但这里没有真正用图布局。

改进：构造 `nodeById` map；edge key 用 `relationship_id || source-target`；超过阈值时切换列表/聚类视图，别假装一个 400x300 的圆能展示复杂关系图。

7. **Detail drawer 没有达到“审查工具”的交互标准。**

`OverlapDetailDrawer.jsx:36` 是固定 `w-96` 右侧抽屉，移动端容易溢出；没有 focus trap，没有 Escape 关闭，没有遮罩点击关闭。`ReviewItem` 在 `OverlapDetailDrawer.jsx:125` 是非受控 checkbox，勾选不会持久化。`Benign Explanations` 在 `OverlapDetailDrawer.jsx:102` 写死三条解释，没有绑定 relationship artifact、figure label、caption 或 rule source。

Evidence First 的系统里，解释文本不能变成“看起来专业的静态安慰剂”。要么这些解释来自结构化 artifact/rule source，要么明确标成通用 checklist，不要混成证据解释。

8. **App shell 的手写路由现在能用，再长就会疼。**

`AppLayout.jsx:127` 手写 `activePage`、case/run、URL sync、localStorage restore、health polling、page switch。P1 内测可以；继续加 deep link、权限、route-level loader、error boundary、query params 时，这个会变成第二个小 orchestrator。

改进：P1 先别大改。等页面数继续增长时，引入 React Router，把 URL 作为 source of truth；case/run selection 放到小的 workspace store/hook，不要继续塞进 layout。

### 前端性能与风险

1. **当前 build 体积可以接受。** main chunk gzip 约 70 kB，最大页面 chunk gzip 约 8 kB。前端性能问题不在 bundle size，而在运行时数据和图片渲染。

2. **Figure grid 全量渲染风险会随真实 paper 变大。** `FigureGrid` 在 `VisualForensicsPage.jsx:589` 遍历所有 figures，每个 figure 最多渲染 9 个 panels。paper1 级别的 257 figures / 811 panels 还能靠 lazy image 勉强撑，但再上一个量级就该分页、虚拟列表或按 figure group 展开。

3. **iframe report 预览是安全优先，但行为要写清。** `ReportCenterPage.jsx:172` 的 sandbox 没有 `allow-scripts`。如果 HTML 报告是纯静态，这是对的；如果报告依赖交互 JS，预览会坏。不要两头都想要：要么报告保持无脚本，要么把 sandbox 能力和风险写成显式契约。

4. **上传 base64 是明显的浏览器端内存膨胀点。** base64 本身约 33% 膨胀，再加 DataURL 和 JSON 字符串，会让大文件上传很快变成内存问题。这不是理论洁癖，论文 PDF + source data zip 很容易踩到。

### 前端是否值得学习

**值得学一点，但别照抄。**

值得学的是：P1 工作台的页面切分方向、backend health 提示、视觉证据 workflow 的基本信息架构、重型工具手动触发入口。

不值得学的是：把复杂页面写成 876 行状态机、无测试地接证据类 mutation、用 base64 JSON 上传真实材料、把证据解释硬编码在 drawer 里。

### 前端是否适合用于生产

**不适合。**

适合内部 P1 demo 和受控内测：工程人员知道怎么解释失败、数据量有限、用户不多、操作路径可控。

不适合真实生产：没有组件测试，上传路径粗糙，关键视觉 mutation 有实 bug，错误状态会被吞成空数据，case 切换存在 stale async 写回风险，复杂图和大材料输入没有足够的运行时保护。

## 缺失点与不确定性

- 没看到 CI 配置；如果 CI 在外部系统，需要把结果和配置纳入仓库可见范围。
- 前端深审只覆盖 `web/frontend/src` 的 React 组件、API client、lint/build/test 入口；没有用 Playwright 打开浏览器做视觉回归，也没有连接真实 backend 手动跑完整 Web flow。
- `pydeps` 图只对 `engine` 画图，足以发现 engine -> web 反向依赖，但不是全仓 import 图。
- full pytest 未完成，被我在 5 分钟后中断；不能据此说测试失败，只能说当前全量测试反馈不适合作为快速门禁。
- 评审基于 dirty worktree。若这些未提交改动只是临时实验，应先清理到一个可 lint 的状态再谈质量。

## 最短修复清单

1. 先修 `ruff` 的 10 个错误，尤其是 `orchestrator.py:4048`、`4049`、`4067` 和 `overlap_reuse.py:627`。
2. 加最小 CI：`ruff check`、`pytest --collect-only`、核心 unit tests。
3. 把 `engine/static_audit/tools/provenance_graph.py` 对 `web.backend` 的 import 切掉，改成 artifact-first 或 port/adapter。
4. 从 `_run_static_audit_from_args()` 里切出 stage modules，不要重写，按现有 artifact 边界搬。
5. 把 `html_report/_core.py` 中的 pattern/report view model 生成拆出，HTML 只渲染。
6. 拆依赖组，别让 CLI core 强制拉完整 Web/DB/Torch 栈。
7. 给 `test-fast` 一个 30 秒内完成的目标，重型视觉和模型测试单独跑。
8. 修 `VisualForensicsPage.jsx` 的 `Run SILA Dense` click event payload bug，并补组件测试。
9. 给 `VisualForensicsPage` 拆 hook：artifact loading、embedding polling、dense investigation 分开。
10. 把前端上传从 base64 JSON 改成 multipart/chunked，并加 progress/cancel/error state。
