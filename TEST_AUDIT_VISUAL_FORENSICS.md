# Test Audit: Visual Forensics / Agent / Source Data Changes

审计日期：2026-06-15
状态校准：2026-06-15 根目录文档更新时复核，本文件是一次测试可信度审计记录，不是当前全部测试的最新运行报告。下面的 154 passed 只对应当时列出的目标命令；当前验证仍应以 `make test` / `make lint-python` 为准。

范围：当前工作区 staged/untracked 改动中的测试可信度审计，重点包括视觉取证 schema/tool/orchestrator/report/Web、Agent context/runner、Source Data pair forensics 和相关 CLI/registry 测试。

当前代码事实：canonical visual artifacts 和 Web Gallery 已进入主链路，但底层 panel extraction / copy-move 仍是 OpenCV + ORB/SIFT 过渡实现。ELIS YOLOv5、RootSIFT/MAGSAC、TruFor、CBIR 仍属于待接入 adapter 路线；本审计中的“不可按视觉取证 Phase 1 已可信完成合并”结论仍适用。

验证命令：

```bash
uv run pytest tests/unit/test_visual_schemas.py tests/unit/test_visual_finding_pipeline.py tests/unit/test_copy_move_detection.py tests/unit/test_visual_orchestrator.py tests/unit/test_visual_tool_registry.py tests/unit/test_visual_report.py tests/unit/test_web_visual_endpoints.py tests/unit/test_env.py tests/unit/test_agent_step_runner.py tests/unit/test_agent_context_pack.py tests/unit/test_source_data_pair_forensics.py tests/unit/test_source_data_cross_sheet.py tests/e2e/test_audit_paper_static_bundle.py
```

结果：154 passed。

## 需求理解

Veritas 这轮改动真正要保证的是：视觉取证进入受控 `audit-paper` 证据链，生成 `figure_evidence` / `panel_evidence` / `image_relationship` / `visual_finding`，并能从报告和 Web 回溯到 figure、panel、工具输出、分数、方法、人工复核动作。

文档还要求：

- 视觉工具失败隔离，状态进入 manifest / limitations。
- 禁止最终裁决措辞。
- Agent 只能选择 Tool Registry 中允许的 deterministic tool。
- Web 只能访问 case-scoped artifacts。
- 高优先级视觉 finding 必须提供原图/裁图、相似候选对、方法、分数、overlay/relationship artifact、figure/panel/caption、良性解释和人工复核问题。

不清楚处：PRD 写了 panel extraction >80%、copy-move >70%、误报 <30%，但没有定义 fixture 评估集、bbox tolerance、precision/recall 计算口径。这会削弱算法测试的合并标准。

## 测试可信度评分

**5.5 / 10**

测试数量不少，且目标测试全通过。但核心风险仍没被可靠验证：没有真实 `audit-paper` golden 视觉闭环；panel extraction 只断言 `panel_count >= 1`；copy-move 有条件断言和理想合成数据；bundle/report/Web 只弱断言存在性，没有严格验证追溯链、失败状态和 artifact contract。

## 已覆盖内容

- schema 基础校验：有效/无效 figure、panel、relationship、finding。
- Tool Registry：视觉工具注册、agent-selectable 边界、参数上下限。
- relationship 合并：exact > copy-move、copy-move > dHash 的部分优先级。
- finding 生成：score 阈值、风险映射、fallback 降级、禁用措辞过滤。
- HTML：空状态、基础视觉 section、部分 forbidden phrase 隐藏。
- Web：基础 visual JSON endpoint、图片读取、一个 path traversal case。
- Agent runner：opencode error event、长 prompt 日志脱敏、`.env` 注入。
- Source Data pair forensics：一个聚类和 review task 生成 happy path。

## 主要缺口

- 没有 golden `audit-paper` 视觉闭环测试验证 `visual_evidence.json`、`panel_evidence.json`、`image_relationships.json`、`visual_findings.json`、manifest、HTML 一起稳定产出。
- panel extraction 没按 fixture ground truth 验证 2x2 应切 4 个 panel、bbox/label/crop_path 正确；当前只断言 `panel_count >= 1`。
- copy-move 没有用 5 个 synthetic fixture 计算命中/误报；clean fixture 没跑实际 detector。
- 追溯性只检查 `evidence_refs` 非空，没验证包含两个 panel evidence、relationship artifact、工具参数、method/version/status。
- 失败路径不足：copy-move `failed/not_available` 是否进入 manifest、bundle limitations、HTML limitations 未测。
- Web endpoint 直接调用 handler，没测真实 HTTP status、case 不存在、artifact 缺失、坏 JSON、URL encoding。
- 前端 `VisualForensicsPage.jsx` 没有组件测试或浏览器测试。
- Source Data cluster 测试只覆盖单一同 sheet/offset 聚合，没测高风险排序、跨 sheet 分组、max representatives、evidence refs 去重。
- `.env` 禁用只测 helper，没测 `--no-env-file` 到 AgentStepRunner 的端到端行为；日志脱敏不覆盖 stdout/stderr 泄密。

## 可疑测试

- `tests/unit/test_visual_orchestrator.py::test_investigation_tool_action_runs_visual_copy_move`
  - 允许输出状态是 `skipped/not_available/ran`，基本证明不了 copy-move 可用。
- `tests/unit/test_copy_move_detection.py::test_overlay_generated`
  - `if relationship_count > 0` 让 overlay 关键断言可被跳过。
- `tests/unit/test_copy_move_detection.py::test_cross_figure_source_type`
  - `if relationship_count > 0` 让 cross-figure 分类关键断言可被跳过。
- `tests/unit/test_visual_orchestrator.py::test_run_visual_panel_extraction_writes_canonical_artifacts`
  - `panel_count >= 1` 会让 whole-figure fallback 伪装成 panel extraction 成功。
- `tests/unit/test_visual_fixtures.py`
  - 主要验证 fixture 自洽，不验证生产代码行为。
- `tests/unit/test_visual_report.py`
  - 多为字符串存在性断言，未验证 evidence refs、limitations、overlay img 语义。
- `tests/unit/test_web_visual_endpoints.py`
  - 绕过真实 HTTP 层，状态码和错误处理覆盖弱。

## Mutation 审计

| Mutation | 当前测试是否能抓住 | 原因 | 建议新增测试 |
|---|---:|---|---|
| panel extraction 永远 whole-figure fallback | 否 | `panel_count >= 1` 仍通过 | 2x2 fixture 断言 4 panels + bbox tolerance |
| visual finding 只引用 relationship，不引用 panel | 否 | 只断言 `evidence_refs` 非空 | bundle finding 必须含 source/target panel evidence + relationship artifact |
| copy-move tool 永远 skipped | 部分 | detector 单测会抓，orchestrator 测试不会 | investigation action 用真实可检测 panels，期望 `ran` 且 relationship >0 |
| cross-figure 关系被标成 single | 不稳定 | 实际 cross test 有条件跳过 | 强制可检测 cross fixture，必须产生 `copy_move_cross` |
| visual tool failed 不进入 limitations | 否 | 没有 failed/not_available aggregation 测试 | 构造 failed `visual_copy_move.json`，断言 manifest/bundle/HTML limitations |
| Web case 不存在触发 500 | 否 | 没测 missing case | HTTP/handler 测试未知 case 返回 404 JSON |
| exact duplicate 被 dHash 覆盖 | 否 | 只测 exact vs copy、copy vs dHash | 同一 pair exact+dHash，期望 `exact_duplicate` score 1.0 |
| 去掉 Tool Registry agent_selectable 检查 | 是 | not-selectable tests 会失败 | 已覆盖，保留 |
| 风险阈值 high/critical 反转 | 是 | risk mapping 边界测试较好 | 已覆盖，保留 |
| `--no-env-file` 仍加载 `.env` | 否 | 只测 helper，不测 CLI/runner 链路 | `run_static_audit` / runner 传 `no_env_file` 后 env 不含 dotenv secret |

## 建议新增测试

### 1. Golden visual audit smoke

- 测试目标：验证真实视觉数据流。
- 输入：含两张 fixture images 的最小 paper/workdir，agent off 或 fake。
- 期望结果：四个 visual artifacts、manifest visual status、HTML visual section、bundle finding/evidence graph 全部存在。
- 重要性：验证真实数据流，不只是函数拼接。

### 2. Panel extraction ground truth

- 测试目标：验证 panel extraction 不是 fallback 伪成功。
- 输入：`tests/fixtures/visual/synthetic_2x2_clean/images/Figure1.png`。
- 期望结果：4 个 panels，labels `a-d`，bbox 与 ground truth 在容忍范围内，crop 文件存在。
- 重要性：防止 fallback 被当成 panel-level extraction。

### 3. Copy-move fixture matrix

- 测试目标：验证 copy-move 命中和 clean 负例。
- 输入：clean/exact/scaled/rotated/brightness fixtures。
- 期望结果：clean `relationship_count == 0`；copy fixtures 至少命中 expected pair，source_type 正确，score 超阈值。
- 重要性：覆盖准确率和误报风险。

### 4. Failed visual tool propagation

- 测试目标：验证失败隔离和限制披露。
- 输入：`visual_copy_move.json` status=`failed`，带 errors/limitations。
- 期望结果：`visual_findings.json` 保留 limitations，manifest/bundle/HTML 显示失败，不阻断报告。
- 重要性：这是 PRD P0 失败隔离要求。

### 5. Strict evidence refs

- 测试目标：验证 100% 可追溯。
- 输入：一个 visual finding 源/目标 panel + relationship artifact。
- 期望结果：bundle finding evidence_refs 精确包含两个 panel evidence id 和 `image_relationships.json` artifact id，manual_review_note 非空。
- 重要性：避免 report 中出现无法回溯的 finding。

### 6. Web missing/unsafe cases

- 测试目标：验证 case-scoped 安全访问。
- 输入：未知 case、缺 artifact、`..%2F..` 编码 traversal、带空格/# 的 image path。
- 期望结果：404 或正确编码访问，不读 case 外文件。
- 重要性：防止数据泄漏和前端图片断链。

### 7. Judge context visual queue

- 测试目标：验证 Judge 能看到视觉高优先级复核入口。
- 输入：`visual_findings.json` 含 high-risk review_queue/clusters。
- 期望结果：`context_pack_judge.json` compact summary 保留 top visual queue，并按风险截断。
- 重要性：避免 Judge 只看 Source Data，漏掉视觉证据。

## 最终判断

**不建议按“视觉取证 Phase 1 已可信完成”合并。**

当前测试适合作为 schema/工具骨架的初步保护，但不足以证明需求已经满足。

合并前必须补：

1. Golden visual audit smoke。
2. Panel extraction ground truth。
3. Copy-move fixture matrix。
4. Failed visual tool propagation。
5. Strict evidence refs。

Web/前端测试可以稍后补，但 case-scoped 访问和 missing-case 404 至少要先覆盖。

可接受风险：真实论文准确率暂时没有达到 PRD 指标，只要明确标记 beta。

不可接受风险：报告/Bundle 追溯链不严格、失败状态不透明、Web 可能跨 case/路径读取、panel extraction fallback 被当成成功。
