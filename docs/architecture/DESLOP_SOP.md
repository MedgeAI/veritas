# DESLOP SOP — Veritas 代码熵控标准操作流程

> **目标**：用确定性程序把 LLM 生成代码的熵增控制在可量化、可自动修复、可门禁拦截的范围内。
> **原则**：清理不靠另一个 agent 的直觉。所有规则必须代码化、配置化、可重复执行。

---

## 1. 三层防御模型

```
┌────────────────────────────────────────────────────────────────┐
│  Layer 3: 结构熵（依赖方向、API 契约、测试完整性）               │
│  → 半自动检测 + 人工裁决                                        │
│  工具: import-linter (Python), dependency-cruiser (JS/TS)      │
├────────────────────────────────────────────────────────────────┤
│  Layer 2: 表面熵（格式、死代码、unused imports、类型错误）       │
│  → 100% 确定性，可自动修复                                      │
│  工具: Ruff, Vulture, Pyright, Biome, Knip                     │
├────────────────────────────────────────────────────────────────┤
│  Layer 1: 即时反馈（post-edit hook 自动触发 Layer 2）           │
│  → 熵产生的瞬间拦住                                            │
│  工具: Claude Code hooks                                       │
└────────────────────────────────────────────────────────────────┘
```

---

## 2. Veritas 分层架构约束（来源：AGENTS.md）

依赖只能自上而下流动，禁止反向/横向/循环依赖。违反即架构错误。

```
Layer 4 (顶层): UI
  cli/          — CLI 入口
  web/backend/  — Web API
  web/frontend/ — 前端（JS/TS）
    ↓
Layer 3: Engine
  engine/       — 业务逻辑唯一归属
    engine/static_audit/    — 静态审查内核
    engine/investigation/   — Agent 调查
    engine/reporting/       — 报告渲染
    engine/tools/           — Tool Registry
    engine/ground_truth/    — Ground Truth pipeline
    ↓
Layer 2: Runtime
  runtime/      — 命令执行、副作用隔离
    ↓
Layer 1 (底层): Config/Types
  configs/      — 方法论配置
  protocols/    — 领域规则
  schema 文件    — 类型契约
```

### 禁止的依赖方向

| 禁止 | 原因 |
|---|---|
| `runtime/` → `engine/` | Runtime 不承载业务推理 |
| `configs/` → `engine/` | Config 不承载流程逻辑 |
| `cli/` → `web/` 或 `web/` → `cli/` | UI 层内部禁止横向依赖 |
| `engine/` → `cli/` 或 `engine/` → `web/` | Engine 不直接调 UI |
| 任何层 → `third_party/` 直接 import | 必须通过 adapter/tool 包装 |
| 任何层 → `engine/static_audit/upstream/` 直接修改 | 只读上游镜像 |

### 特殊排除域（工具必须跳过）

| 路径 | 原因 |
|---|---|
| `engine/static_audit/upstream/` | 上游只读镜像，ruff lint 已排除 |
| `third_party/` | 外部仓库，git submodule 管理 |
| `web/frontend/node_modules/` | 依赖目录 |
| `web/frontend/dist/` | 构建产物 |
| `outputs/`、`web_data/`、`input/` | 运行产物 |

---

## 3. 工具链配置

### 3.1 Python 表面熵（Layer 2）

#### Ruff（format + lint + unused imports）

已在 `pyproject.toml` 配置：

```toml
[tool.ruff]
exclude = [
    "engine/static_audit/upstream",
    "third_party",
]

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes (unused imports, undefined names)
    "I",    # isort
    "UP",   # pyupgrade
]
ignore = [
    "E501", # line too long (let formatter handle it)
]

[tool.ruff.lint.per-file-ignores]
"engine/static_audit/orchestrator.py" = ["E402"]
"__init__.py" = ["F401"]  # __init__.py re-exports are intentional
```

执行命令：

```bash
uv run ruff check --fix cli/ engine/ runtime/ protocols/ web/backend/ tests/ scripts/
uv run ruff format cli/ engine/ runtime/ protocols/ web/backend/ tests/ scripts/
```

#### Vulture（dead code）

```bash
uv run vulture cli/ engine/ runtime/ protocols/ web/backend/ scripts/ \
    --exclude engine/static_audit/upstream/ \
    --min-confidence 80 \
    --sort-by-size
```

**Vulture 假阳性白名单**（Pydantic 模型字段、TypedDict 字段等元类驱动的属性，Vulture 无法识别）：

```
# 以下类型的 "unused" 是假阳性，不删除：
# - Pydantic BaseModel 字段（序列化契约）
# - TypedDict 字段（schema 契约）
# - dataclass 字段
# - @property / @cached_property（动态访问）
# - 被 **kwargs 或 getattr() 间接访问的属性
```

#### Pyright（类型检查）

```bash
uv run pyright cli/ engine/ runtime/ protocols/ web/backend/
```

关注 `error` 级别（`✘`），`warning`（`★`）可作为参考但不阻断。

### 3.2 JS/TS 表面熵（Layer 2）

#### Biome（format + lint）

```bash
cd web/frontend && npx biome check --write .
```

#### Knip（unused exports / deps / files）

```bash
cd web/frontend && npx knip
```

### 3.3 Python 结构熵（Layer 3）

#### import-linter（依赖方向验证）

安装：`uv add --dev import-linter`

配置文件 `.importlinter`：

```ini
[importlinter]
root_packages =
    cli
    engine
    runtime
    protocols
    web

[importlinter:contract:layered-architecture]
name = Layered architecture: UI → Engine → Runtime → Config
type = layers
layers =
    cli | web
    engine
    runtime
    protocols | configs

# 额外约束：UI 层内部禁止横向依赖
[importlinter:contract:ui-independence]
name = CLI and Web must not depend on each other
type = independence
modules =
    cli
    web

# Runtime 不依赖 Engine（关键架构约束）
[importlinter:contract:runtime-independence]
name = Runtime must not import Engine
type = forbidden
source_modules = runtime
forbidden_modules = engine

# Config/Types 不依赖 Engine
[importlinter:contract:config-independence]
name = Config/Types must not import Engine or Runtime
type = forbidden
source_modules = protocols | configs
forbidden_modules = engine | runtime
```

执行：

```bash
uv run lint-imports
```

### 3.4 JS/TS 结构熵（Layer 3）

#### dependency-cruiser（前端依赖方向）

安装：`cd web/frontend && npm install --save-dev dependency-cruiser`

配置文件 `.dependency-cruiser.cjs`（项目为 ESM，必须用 `.cjs` 扩展名）：

```javascript
module.exports = {
  forbidden: [
    {
      name: "no-direct-service-import-from-component",
      comment: "Components should not directly import service internals",
      severity: "error",
      from: { path: "^src/components/" },
      to: { path: "^src/services/", pathNot: "^src/services/api\\.js$" },
    },
    {
      name: "no-test-in-production",
      comment: "Production code must not import from test code",
      severity: "error",
      from: { pathNot: "^src/__tests__/" },
      to: { path: "^src/__tests__/" },
    },
    {
      name: "no-node-modules-leak",
      comment: "Internal modules should not reach into node_modules subpaths",
      severity: "warn",
      from: {},
      to: { dependencyTypes: ["npm-no-pkg", "npm-unknown"] },
    },
  ],
};
```

执行：

```bash
cd web/frontend && npx depcruise --validate .dependency-cruiser.cjs src/
```

---

## 4. `make deslop` 目标定义

统一入口，整合所有确定性工具。

### 行为规格

```makefile
deslop: ## Run full entropy control pipeline
	@echo "=== Layer 2: Python surface entropy ==="
	@echo "--- Ruff: auto-fix unused imports + lint ---"
	-$(PY_ENV) $(RUFF) check --fix $(PYTHON_SRC_DIRS)
	@echo "--- Ruff: format ---"
	-$(PY_ENV) $(RUFF) format $(PYTHON_SRC_DIRS)
	@echo "--- Vulture: dead code scan (80%+ confidence) ---"
	-uv run vulture $(PYTHON_SRC_DIRS) \
		--exclude engine/static_audit/upstream/ \
		--min-confidence 80 --sort-by-size
	@echo ""
	@echo "=== Layer 2: JS/TS surface entropy ==="
	@echo "--- Biome: format + lint ---"
	-cd $(FRONTEND_DIR) && npx biome check --write .
	@echo "--- Knip: unused exports/deps ---"
	-cd $(FRONTEND_DIR) && npx knip
	@echo ""
	@echo "=== Layer 3: Structural entropy ==="
	@echo "--- import-linter: Python dependency direction ---"
	-uv run lint-imports
	@echo "--- dependency-cruiser: JS/TS dependency direction ---"
	-cd $(FRONTEND_DIR) && npx depcruise --validate .dependency-cruiser.js src/
	@echo ""
	@echo "=== Done ==="
```

### 输出分类

| 标记 | 含义 | 处理方式 |
|---|---|---|
| `[auto-fixed]` | 工具已自动修复 | 无需人工介入 |
| `[needs-human]` | 需要人工判断（如 Vulture dead code、函数签名变更） | 人工确认后删除 |
| `[blocked]` | 架构违规（依赖方向错误、API 契约破坏） | 必须修复后才能合入 |

### 约束

- 每个工具以 `-` 前缀执行（失败不中断 pipeline）
- 最终退出码：如果有任何 `[blocked]` 项则非零
- 所有工具的输出必须可直接管道到文件

---

## 5. `/deslop` Claude Code Skill 定义

### 触发条件

用户输入 `/deslop` 或 "帮我清理代码"、"deslop"。

### 执行流程

```
1. 运行 `make deslop` 收集所有工具输出
2. 分类处理：
   a. auto-fixed 项：git diff 展示变更，跑 `make test` 确认无回归
   b. needs-human 项：逐项呈现，等待用户确认
   c. blocked 项：列出违规详情，给出修复建议
3. 用户确认 needs-human 项后，执行删除
4. 最终跑一次 `make test` + `make lint-python` + `make lint-web` 确认全绿
5. 输出风险清单（同 AGENTS.md 要求的标准格式）
```

### Skill 禁止行为

- 不删除 `__init__.py` 中的 re-export（这是 API 契约）
- 不删除 Vulture 80% 以下置信度的项（假阳性率过高）
- 不删除 Pydantic 模型字段（序列化契约）
- 不修改 `engine/static_audit/upstream/` 或 `third_party/`
- 不为让测试通过而修改测试期望
- 不顺手"改进"无关代码

---

## 6. Phase 落地计划

| Phase | 内容 | 依赖 |
|---|---|---|
| **Phase 1** | `.importlinter` 配置 + `import-linter` 集成 + 首次违规扫描 | 无 |
| **Phase 2** | `make deslop` Makefile target，整合所有工具 | Phase 1 |
| **Phase 3** | 前端 `dependency-cruiser` + `Knip` 配置 | 无 |
| **Phase 4** | `/deslop` Claude Code skill | Phase 2 + 3 |
| **Phase 5** | Claude Code post-edit hook（Layer 1 即时反馈） | Phase 2 |

---

## 7. 风险清单

| 项目 | 详情 |
|---|---|
| **import-linter 首次扫描可能发现大量违规** | 当前代码未经依赖方向检查，可能有隐藏的跨层 import。首次扫描只做报告，不自动修复 |
| **Vulture 白名单需要维护** | 新增 Pydantic 模型时需同步更新白名单（或接受假阳性噪音） |
| **`__init__.py` re-export 误删** | Ruff F401 对 `__init__.py` 的 unused import 需要特别排除（已在 pyproject.toml 配置） |
| **dependency-cruiser 仅覆盖前端** | Python 侧结构熵由 import-linter 覆盖，两者互补 |
| **回滚方式** | `git checkout -- .` 恢复所有格式化/删除变更 |
