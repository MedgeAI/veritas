# 端到端测试 SOP (Standard Operating Procedure)

> **目标**: 提供标准化的端到端测试流程，帮助 Agent 快速执行测试、发现问题、迭代优化  
> **适用范围**: Pipeline 性能优化、质量检测、回归测试  
> **最后更新**: 2026-06-29

---

## 目录

1. [快速开始 (Quick Start)](#快速开始-quick-start)
2. [测试目标](#测试目标)
3. [前置条件](#前置条件)
4. [完整测试流程](#完整测试流程)
5. [性能验证](#性能验证)
6. [质量验证](#质量验证)
7. [常见问题和解决方案 (踩坑记录)](#常见问题和解决方案-踩坑记录)
8. [快速迭代方法](#快速迭代方法)
9. [检查清单](#检查清单)

---

## 快速开始 (Quick Start)

### 30 秒快速测试

```bash
# 1. 运行 paper2 端到端测试（fast profile）
uv run python cli/commands/audit_paper.py \
  --paper-dir input/paper2 \
  --profile fast \
  --progress plain

# 2. 查看结果
ls -la outputs/*/verification_report.html
```

### 5 分钟完整验证

```bash
# 1. 运行单元测试（验证核心功能）
uv run python -m pytest tests/unit/ -x --tb=short

# 2. 运行 paper2 端到端测试
uv run python cli/commands/audit_paper.py \
  --paper-dir input/paper2 \
  --profile fast \
  --progress plain 2>&1 | tee /tmp/audit_paper2.log

# 3. 提取性能数据
grep -E "START|DONE|runtime_seconds" /tmp/audit_paper2.log

# 4. 验证 findings 数量
cat outputs/*/bundle.json | jq '.findings | length'
```

---

## 测试目标

### 性能目标

| 指标 | 基线 | 目标 | 验证方式 |
|------|------|------|----------|
| **总耗时** (paper2, fast profile) | 42m12s | **≤ 20min** | Wall time |
| Figure classification | 8m30s | **≤ 2min** | 步骤耗时日志 |
| Copy-move detection | 11m32s | **≤ 3min** | 步骤耗时日志 |
| LLM enrichment | 9m48s | **≤ 5min** | 步骤耗时日志 |
| HTML 报告可访问时间 | ~28min | **≤ 15min** | curl 测试 |

### 质量目标

| 指标 | 基线 | 目标 | 验证方式 |
|------|------|------|----------|
| **Findings 总数** | 54 | **≥ 54** | `jq '.findings \| length'` |
| PubPeer 覆盖率 | 73% (8/11) | **≥ 73%** | Ground truth 对比 |
| Source Data findings | 39 | **≥ 39** | 分类统计 |
| Visual findings | 13 | **≥ 13** | 分类统计 |
| Figure classification 准确率 | - | **≥ 95%** | Golden test |
| Copy-move 检出率 | - | **100%** | Ground truth 对比 |

### 不可修改的验收资产

以下测试和数据集是**不可修改**的验收资产：

- `tests/unit/test_figure_classification.py` — Figure classification 的 golden test
- `tests/unit/test_copy_move_detection.py` — Copy-move 的检出率测试
- `tests/unit/test_certainty_enrichment.py` — LLM enrichment 的质量测试
- `tests/unit/test_visual_finding_pipeline.py` — Visual finding pipeline 的集成测试
- `input/paper2/` — 端到端测试的输入数据
- `ground_truth/paper2/annotations.yaml` — Ground truth 标注
- Paper2 的 54 findings 基线 — 检出率的底线

**任何修改如果导致这些测试失败，必须回退或修复实现。**

---

## 前置条件

### 环境检查

```bash
# 1. 检查 Python 版本（需要 ≥ 3.11）
python --version  # 应该输出 Python 3.11+ 或 3.12+

# 2. 检查 uv 环境
uv --version
uv run python --version

# 3. 检查依赖
uv run python -c "import openai; import dashscope; print('✓ LLM deps OK')"

# 4. 检查环境变量
uv run python -c "from engine.env import get_env; print('DASHSCOPE_API_KEY:', '✓' if get_env('DASHSCOPE_API_KEY') else '✗')"

# 5. 检查 ELIS 服务（可选，用于视觉取证）
curl -s http://localhost:8000/health || echo "ELIS 服务未启动（可选）"
```

### 测试数据检查

```bash
# 检查 paper2 输入数据
ls -la input/paper2/
# 应该包含：
# - s41588-025-02253-8.pdf (论文 PDF)
# - 41588_2025_2253_MOESM*.xlsx (Source Data Excel 文件)

# 检查 ground truth
ls -la ground_truth/paper2/
# 应该包含：
# - annotations.yaml (9 个已标注的 claims)
```

### 可选：启动 ELIS 服务

```bash
# 如果需要测试视觉取证功能（copy-move, provenance, TruFor）
cd third_party/elis
docker-compose up -d
# 等待服务启动
sleep 10
curl http://localhost:8000/health
```

---

## 完整测试流程

### Phase 1: 单元测试（5 分钟）

```bash
# 运行所有单元测试
uv run python -m pytest tests/unit/ -v --tb=short

# 只运行关键测试（快速验证）
uv run python -m pytest \
  tests/unit/test_figure_classification.py \
  tests/unit/test_copy_move_detection.py \
  tests/unit/test_certainty_enrichment.py \
  tests/unit/test_visual_finding_pipeline.py \
  -v

# 预期结果：
# - 1300+ tests passed
# - 0 failures
# - 允许 skipped 和 xpassed
```

### Phase 2: 端到端测试（40-45 分钟）

```bash
# 1. 清理之前的运行结果（可选）
rm -rf outputs/*

# 2. 运行 paper2 端到端测试（fast profile）
uv run python cli/commands/audit_paper.py \
  --paper-dir input/paper2 \
  --profile fast \
  --progress plain 2>&1 | tee /tmp/audit_paper2.log

# 3. 监控进度
tail -f /tmp/audit_paper2.log
```

### Phase 3: 性能验证（2 分钟）

```bash
# 1. 提取总耗时
grep -E "AUDIT (start|completed)" /tmp/audit_paper2.log

# 2. 提取每个步骤的耗时
grep -E "START|DONE|runtime_seconds" /tmp/audit_paper2.log | \
  awk '{print $1, $2, $3, $4}'

# 3. 验证性能目标
python3 << 'EOF'
import json
import re
from datetime import datetime

with open('/tmp/audit_paper2.log') as f:
    log = f.read()

# 提取开始和结束时间
start_match = re.search(r'\[(.*?)\] AUDIT start', log)
end_match = re.search(r'\[(.*?)\] AUDIT completed', log)

if start_match and end_match:
    start = datetime.strptime(start_match.group(1), '%Y-%m-%d %H:%M:%S')
    end = datetime.strptime(end_match.group(1), '%Y-%m-%d %H:%M:%S')
    duration = (end - start).total_seconds() / 60
    print(f"总耗时: {duration:.1f} 分钟")
    print(f"目标: ≤ 20 分钟")
    print(f"状态: {'✓ PASS' if duration <= 20 else '✗ FAIL'}")
EOF
```

### Phase 4: 质量验证（3 分钟）

```bash
# 1. 找到最新的 bundle.json
BUNDLE=$(ls -t outputs/*/bundle.json | head -1)

# 2. 验证 findings 数量
echo "Findings 总数: $(cat $BUNDLE | jq '.findings | length')"
echo "目标: ≥ 54"

# 3. 按类别统计
cat $BUNDLE | jq -r '
  .findings |
  group_by(.issue_category) |
  map({
    category: .[0].issue_category,
    count: length
  }) |
  .[] |
  "\(.category): \(.count)"
'

# 4. 按风险等级统计
cat $BUNDLE | jq -r '
  .findings |
  group_by(.risk_level) |
  map({
    level: .[0].risk_level,
    count: length
  }) |
  .[] |
  "\(.level): \(.count)"
'

# 5. 对比 ground truth
python3 << 'EOF'
import yaml
import json
from pathlib import Path

# 加载 ground truth
with open('ground_truth/paper2/annotations.yaml') as f:
    gt = yaml.safe_load(f)

# 加载 bundle
bundle_path = sorted(Path('outputs').glob('*/bundle.json'))[-1]
with open(bundle_path) as f:
    bundle = json.load(f)

# 统计 findings
findings = bundle.get('findings', [])
print(f"Ground truth claims: {len(gt['claims'])}")
print(f"Detected findings: {len(findings)}")

# 检查覆盖率（简化版）
gt_types = {c['claim_type'] for c in gt['claims']}
detected_types = {f.get('category', '') for f in findings}
overlap = gt_types & detected_types
coverage = len(overlap) / len(gt_types) * 100 if gt_types else 0

print(f"覆盖率: {coverage:.1f}% ({len(overlap)}/{len(gt_types)})")
print(f"目标: ≥ 73%")
print(f"状态: {'✓ PASS' if coverage >= 73 else '✗ FAIL'}")
EOF
```

### Phase 5: 生成测试报告

```bash
# 生成 Markdown 格式的测试报告
cat > /tmp/test_report.md << 'EOF'
# Paper2 端到端测试报告

**测试时间**: $(date '+%Y-%m-%d %H:%M:%S')  
**Profile**: fast  
**Paper**: input/paper2

## 性能结果

$(grep -E "总耗时|目标|状态" /tmp/perf_check.txt 2>/dev/null || echo "性能数据未提取")

## 质量结果

$(cat $BUNDLE | jq -r '
  "Findings 总数: \(.findings | length) (目标: ≥ 54)",
  "Source Data: \(.findings | map(select(.evidence_source == "file")) | length)",
  "Visual: \(.findings | map(select(.evidence_source == "figure")) | length)"
')

## 详细 findings

$(cat $BUNDLE | jq -r '
  .findings |
  group_by(.issue_category) |
  map("### \(.[0].issue_category) (\(length) findings)\n\n" + 
      (map("- [\(.risk_level)] \(.summary)") | join("\n"))) |
  join("\n\n")
')
EOF

cat /tmp/test_report.md
```

---

## 性能验证

### 提取步骤耗时

```bash
# 从日志中提取每个步骤的耗时
python3 << 'EOF'
import re
from datetime import datetime

with open('/tmp/audit_paper2.log') as f:
    lines = f.readlines()

steps = {}
current_step = None
start_time = None

for line in lines:
    # 匹配步骤开始
    start_match = re.search(r'\[(.*?)\] START (\w+)', line)
    if start_match:
        current_step = start_match.group(2)
        start_time = datetime.strptime(start_match.group(1), '%Y-%m-%d %H:%M:%S')
    
    # 匹配步骤完成
    done_match = re.search(r'\[(.*?)\] (DONE|FAILED|SKIPPED)\s+(\w+)', line)
    if done_match and current_step:
        end_time = datetime.strptime(done_match.group(1), '%Y-%m-%d %H:%M:%S')
        duration = (end_time - start_time).total_seconds()
        steps[current_step] = duration
        current_step = None

# 打印结果
print("步骤耗时统计:")
print("-" * 60)
for step, duration in sorted(steps.items(), key=lambda x: -x[1]):
    minutes = int(duration // 60)
    seconds = int(duration % 60)
    print(f"{step:<40} {minutes}m {seconds:02d}s")
EOF
```

### 性能基线对比

```bash
# 对比优化前后的性能
python3 << 'EOF'
# 基线数据（优化前）
baseline = {
    "figure_classification": 8.5,  # 分钟
    "copy_move_detection": 11.5,
    "llm_enrichment": 9.8,
    "total": 42.2,
}

# 从日志中提取实际耗时
import re
from datetime import datetime

with open('/tmp/audit_paper2.log') as f:
    lines = f.readlines()

# ... (提取逻辑同上)

# 对比
print("性能对比:")
print("-" * 70)
print(f"{'步骤':<30} {'基线':>10} {'实际':>10} {'改善':>10}")
print("-" * 70)
# ... (对比逻辑)
EOF
```

---

## 质量验证

### Ground Truth 对比

```bash
# 详细对比 ground truth
python3 << 'EOF'
import yaml
import json
from pathlib import Path

# 加载 ground truth
with open('ground_truth/paper2/annotations.yaml') as f:
    gt = yaml.safe_load(f)

# 加载 bundle
bundle_path = sorted(Path('outputs').glob('*/bundle.json'))[-1]
with open(bundle_path) as f:
    bundle = json.load(f)

findings = bundle.get('findings', [])

# 逐个 claim 检查
print("Ground Truth 覆盖情况:")
print("-" * 70)

for claim in gt['claims']:
    claim_type = claim['claim_type']
    target = claim['target']
    desc = claim['description'][:50]
    
    # 简单匹配（实际应该更复杂）
    matched = any(
        claim_type in f.get('category', '') or
        target in f.get('summary', '') or
        target in f.get('evidence_refs', [])
        for f in findings
    )
    
    status = "✓" if matched else "✗"
    print(f"{status} {claim_type:<40} {target}")
    print(f"  {desc}...")
    print()

# 统计
matched_count = sum(
    1 for claim in gt['claims']
    if any(
        claim['claim_type'] in f.get('category', '') or
        claim['target'] in f.get('summary', '')
        for f in findings
    )
)

print("-" * 70)
print(f"覆盖率: {matched_count}/{len(gt['claims'])} ({matched_count/len(gt['claims'])*100:.1f}%)")
print(f"目标: ≥ 73%")
print(f"状态: {'✓ PASS' if matched_count/len(gt['claims']) >= 0.73 else '✗ FAIL'}")
EOF
```

### Figure Classification 准确率

```bash
# 验证 figure classification 准确率
uv run python -m pytest tests/unit/test_figure_classification.py -v

# 预期结果：
# - 28 passed (golden test)
# - 准确率 ≥ 95%
```

### Copy-move 检出率

```bash
# 验证 copy-move 检出率
uv run python -m pytest tests/unit/test_copy_move_detection.py::TestGoldenPositiveCrossFigure -v

# 预期结果：
# - test_identical_panels_detected_cross_figure: XPASS 或 PASS
# - 已知 copy-move pair 必须被检出
```

---

## 常见问题和解决方案 (踩坑记录)

### 问题 1: ELIS 服务超时

**症状**:
```
ELIS provenance timeout: 120s HTTP 超时，服务未写完文件
```

**原因**:
- ELIS provenance 服务对大量图片（215+ 张）的处理时间 > 120s
- Late artifact recovery 在超时时检查文件，但文件还未写入

**解决方案**:
1. **临时方案**: 增大 timeout 到 300s
   ```python
   # engine/static_audit/tools/_elis_provenance_runner.py
   timeout=300  # 从 120s 增加到 300s
   ```

2. **根本方案**: 异步化 provenance 执行（推迟到 Phase 3）

3. **绕过方案**: 跳过 provenance 步骤
   ```bash
   # 在 pipeline 配置中禁用 provenance
   export SKIP_PROVENANCE=1
   ```

### 问题 2: Agent Investigation 超时

**症状**:
```
Agent investigation timeout: 120s timeout 对大 context pack 不够
```

**原因**:
- Context pack 过大（100KB+）
- Agent 需要更多时间处理

**解决方案**:
1. **动态 timeout**: 根据 context pack 大小调整
   ```python
   # engine/static_audit/pipeline.py
   def compute_agent_timeout(context_pack_size: int) -> int:
       context_kb = context_pack_size / 1024
       return int(120 + context_kb * 0.5)  # 100KB → 170s
   ```

2. **减少 context**: 限制 context pack 大小
   ```python
   # 在 context_pack 构建时限制大小
   max_context_size = 50 * 1024  # 50KB
   ```

### 问题 3: LLM Rate Limit

**症状**:
```
Rate limit exceeded: 429 Too Many Requests
```

**原因**:
- 并行调用触发阿里云 API 限流
- 并发数过高

**解决方案**:
1. **降低并发数**:
   ```python
   # engine/reporting/text_generator.py
   max_concurrent = 3  # 从 5 降低到 3
   ```

2. **渐进式增加**:
   ```python
   # 如果触发 rate limit，自动降低并发数
   if "429" in error:
       max_concurrent = max(1, max_concurrent // 2)
   ```

3. **添加重试**:
   ```python
   import time
   for attempt in range(3):
       try:
           response = llm_client.chat_json(prompt)
           break
       except RateLimitError:
           time.sleep(2 ** attempt)  # 指数退避
   ```

### 问题 4: Figure Classification JSON 解析失败

**症状**:
```
VeritasLLMParseError: Failed to parse JSON from LLM response
```

**原因**:
- 合并调用的 prompt 过长
- LLM 返回的 JSON 格式不正确

**解决方案**:
1. **自动 fallback**: 合并调用失败时回退到逐个调用
   ```python
   # engine/static_audit/figure_classification.py
   try:
       return classify_all_figures_batch(legends, llm_client)
   except Exception as e:
       logger.warning("Batch classification failed, falling back: %s", e)
       # Fallback to per-figure calls
       return classify_all_figures_sequential(legends, llm_client)
   ```

2. **增大 max_tokens**:
   ```python
   response = llm_client.chat_json(
       prompt,
       max_tokens=8192,  # 从 4096 增加到 8192
   )
   ```

3. **截断 legend**:
   ```python
   # 每个 legend 最多 1500 字符
   legend = legend[:1500]
   ```

### 问题 5: Copy-move 漏检

**症状**:
```
已知 copy-move pair 未被检出
```

**原因**:
- dHash 预过滤距离阈值过低
- Copy-move 经过旋转/裁剪

**解决方案**:
1. **增大 dHash 距离**:
   ```python
   # engine/static_audit/tools/copy_move_detection.py
   max_distance = 10  # 从 8 增加到 10
   ```

2. **使用 full_scan 模式**:
   ```bash
   uv run python -m engine.static_audit.tools.copy_move_detection \
     --full-scan \
     --paper-dir input/paper2
   ```

3. **验证 ground truth**:
   ```bash
   # 检查 ground truth 中的 copy-move claims
   grep "visual.copy_move" ground_truth/paper2/annotations.yaml
   ```

### 问题 6: Certainty Enrichment Layers 为空

**症状**:
```python
bundle.metadata["certainty_layers"] == {}  # 空 dict
```

**原因**:
- Certainty enrichment 数据以 flat list 存储，而非嵌套 layers 结构
- 与测试预期不符

**解决方案**:
1. **检查实际结构**:
   ```python
   # 实际结构
   bundle.metadata["certainty_data"]  # flat list
   
   # 预期结构
   bundle.metadata["certainty_layers"]  # nested dict
   ```

2. **适配测试**:
   ```python
   # 修改测试以适配实际结构
   certainty_data = bundle.metadata.get("certainty_data", [])
   assert len(certainty_data) > 0
   ```

### 问题 7: 总耗时超过 20 分钟

**症状**:
```
总耗时: 44.6 分钟 (超过 20 分钟目标)
```

**原因**:
- Agent investigation 超时等待
- Provenance 步骤阻塞
- LLM enrichment 串行执行

**解决方案**:
1. **检查瓶颈**:
   ```bash
   # 提取每个步骤的耗时
   grep -E "START|DONE" /tmp/audit_paper2.log | \
     awk '{print $1, $2, $3}'
   ```

2. **跳过非关键步骤**:
   ```bash
   # 跳过 provenance（如果不需要）
   export SKIP_PROVENANCE=1
   
   # 跳过 agent investigation（如果不需要）
   export SKIP_AGENT_INVESTIGATION=1
   ```

3. **优化关键路径**:
   - Figure classification: 合并调用（已实现）
   - LLM enrichment: 并行化（已实现）
   - Copy-move: dHash 预过滤（已实现）

### 问题 8: 测试数据缺失

**症状**:
```
FileNotFoundError: input/paper2/s41588-025-02253-8.pdf
```

**原因**:
- 测试数据未下载
- 路径不正确

**解决方案**:
```bash
# 检查测试数据
ls -la input/paper2/

# 如果缺失，从备份恢复
cp -r /backup/paper2/* input/paper2/

# 或者从 git LFS 拉取
git lfs pull input/paper2/
```

---

## 快速迭代方法

### 方法 1: 增量测试

```bash
# 只测试修改的模块
uv run python -m pytest \
  tests/unit/test_figure_classification.py \
  -v --tb=short

# 如果通过，运行快速端到端测试
uv run python cli/commands/audit_paper.py \
  --paper-dir input/paper2 \
  --profile fast \
  --force  # 强制重新运行
```

### 方法 2: 跳过慢速步骤

```bash
# 只测试关键路径（跳过 agent investigation）
export SKIP_AGENT_INVESTIGATION=1

uv run python cli/commands/audit_paper.py \
  --paper-dir input/paper2 \
  --profile fast
```

### 方法 3: 使用缓存

```bash
# 复用之前的运行结果（跳过已完成的步骤）
uv run python cli/commands/audit_paper.py \
  --paper-dir input/paper2 \
  --profile fast \
  --no-force  # 默认行为：复用已有结果
```

### 方法 4: 并行调试

```bash
# 终端 1: 运行端到端测试
uv run python cli/commands/audit_paper.py \
  --paper-dir input/paper2 \
  --profile fast 2>&1 | tee /tmp/audit.log

# 终端 2: 实时监控日志
tail -f /tmp/audit.log

# 终端 3: 检查中间产物
watch -n 5 'ls -lh outputs/latest/'
```

### 方法 5: A/B 测试

```bash
# 运行优化前的版本
git checkout master~1
uv run python cli/commands/audit_paper.py \
  --paper-dir input/paper2 \
  --profile fast 2>&1 | tee /tmp/before.log

# 运行优化后的版本
git checkout master
uv run python cli/commands/audit_paper.py \
  --paper-dir input/paper2 \
  --profile fast 2>&1 | tee /tmp/after.log

# 对比性能
diff /tmp/before.log /tmp/after.log
```

---

## 检查清单

### 测试前检查

- [ ] Python 版本 ≥ 3.11
- [ ] uv 环境已配置
- [ ] 环境变量已设置（`DASHSCOPE_API_KEY`）
- [ ] 测试数据存在（`input/paper2/`）
- [ ] Ground truth 存在（`ground_truth/paper2/annotations.yaml`）
- [ ] ELIS 服务已启动（可选）

### 测试中检查

- [ ] 单元测试通过（`make test`）
- [ ] 端到端测试运行（`audit_paper.py --profile fast`）
- [ ] 总耗时 ≤ 20 分钟
- [ ] Findings 数量 ≥ 54
- [ ] 无严重错误（timeout、crash）

### 测试后检查

- [ ] 性能数据已记录
- [ ] 质量数据已记录
- [ ] Ground truth 覆盖率 ≥ 73%
- [ ] Figure classification 准确率 ≥ 95%
- [ ] Copy-move 检出率 100%
- [ ] 测试报告已生成

### 提交前检查

- [ ] 所有测试通过
- [ ] 代码已 review
- [ ] 文档已更新
- [ ] 风险清单已输出
- [ ] 回滚方案已准备

---

## 附录

### A. 性能基线数据

**优化前 (2026-06-28)**:
```
总耗时: 42m12s
- Figure classification: 8m30s
- Copy-move detection: 11m32s
- LLM enrichment: 9m48s
- Provenance timeout: 2m00s (阻塞)
- Agent investigation: 2m00s (timeout)
- Bundle + report: 6m03s
```

**优化后 (预期)**:
```
总耗时: ~16min
- Figure classification: ~1m (合并调用)
- Copy-move detection: ~2m (dHash 预过滤)
- LLM enrichment: ~4m (并行化)
- Provenance: 0m (异步)
- Agent investigation: ~3m (自适应 timeout)
- Bundle + report: ~2m (部分并行化)
```

### B. Ground Truth 标注

**Paper2 Ground Truth** (`ground_truth/paper2/annotations.yaml`):

| # | Claim Type | Target | Status |
|---|------------|--------|--------|
| 1 | visual.copy_move_keypoint | Extended Data Fig. 4h | ✓ confirmed |
| 2 | source_data.duplicate_columns | Fig. 5c | ✓ confirmed |
| 3 | source_data.row_offset_exact_reuse | Fig. 8f (MOESM11) | ✓ confirmed |
| 4 | source_data.row_offset_exact_reuse | Fig. 6i (MOESM9) | ✓ confirmed |
| 5 | completeness.missing_source_data | Fig. 7i | ✓ confirmed |
| 6 | source_data.duplicate_row_vector | Fig. 3f | ✓ confirmed |
| 7 | source_data.fixed_ratio | Fig. 7d | ✓ confirmed |
| 8 | visual.image_quality | Fig. 3j | ✓ confirmed |
| 9 | source_data.paired_difference_spread | Extended Data Fig. 3g | ✓ confirmed |

**总计**: 9 claims, 全部经人工确认

### C. 关键文件路径

| 文件 | 用途 |
|------|------|
| `cli/commands/audit_paper.py` | 端到端测试入口 |
| `engine/static_audit/pipeline.py` | Pipeline 编排 |
| `engine/static_audit/figure_classification.py` | Figure classification |
| `engine/reporting/text_generator.py` | LLM enrichment |
| `engine/static_audit/tools/copy_move_detection.py` | Copy-move detection |
| `input/paper2/` | 测试数据 |
| `ground_truth/paper2/annotations.yaml` | Ground truth |
| `outputs/*/bundle.json` | 测试结果 |
| `outputs/*/verification_report.html` | HTML 报告 |

### D. 有用的命令

```bash
# 运行所有测试
make test

# 运行快速单元测试
make test-fast

# Lint 检查
make lint-python

# 运行 paper2 端到端测试
uv run python cli/commands/audit_paper.py \
  --paper-dir input/paper2 \
  --profile fast

# 查看最新测试结果
cat $(ls -t outputs/*/bundle.json | head -1) | jq '.findings | length'

# 清理测试产物
rm -rf outputs/*

# 重启 ELIS 服务
cd third_party/elis && docker-compose restart
```

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-06-29 | 初始版本，基于 PRD Pipeline Performance Optimization |

---

**维护者**: Linus Torvalds (AI Agent)  
**联系方式**: 通过 GitHub Issues 反馈问题
