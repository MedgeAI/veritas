我已经完成了所有关键文件的逐行审查。以下是完整的 review 报告。

---

# 静默失败降级 Review 报告

## 【核心判断】

**值得做：这是真问题。** 当前实现中存在系统性的"静默降级"模式 — 错误被吞掉后返回看起来正常的空数据，测试全部通过，但生产环境中用户会看到错误结论。

## 【关键洞察】

- **数据结构**：错误状态被折叠进成功响应（200 + `{items: []}`），调用方无法区分"没有数据"和"系统故障"
- **复杂度**：至少 3 层 fallback（mapped path → legacy path → default）叠加，每一层都可能吞掉真实错误
- **风险点**：DB 断连时，embedding/similarity/review 接口全部返回空成功，用户会以为"没有发现相似 panel"
- **验证边界**：现有测试全部用 `sqlite:///:memory:` + 手动插入数据，从未验证"当基础设施失败时系统是否正确报错"

---

## CRITICAL — 必须修复

### C1. `database.py:47-52` — pgvector 扩展注册失败被完全吞掉

```python
@event.listens_for(engine, "connect")
def _register_vector_extension(dbapi_connection, _connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cursor.close()
    except Exception:
        pass  # pgvector may not be installed (e.g. test without Docker)
```

**问题**：
- 捕获 `Exception`（包括连接超时、权限拒绝、认证失败），全部 `pass`
- 注释说"pgvector 可能没装"，但实际会吞掉任何错误
- 生产环境中 PostgreSQL 没装 pgvector 时，embedding 存储退化为 JSON 列暴力搜索，但系统不会报错
- 用户会以为 HNSW 索引正常工作，实际从未建立

**生产影响**：性能从毫秒级退化到 O(n²) 暴力搜索，1071 panels 可能需要几十秒，但用户不会收到任何警告。

**测试覆盖**：无。测试用 SQLite，根本不触发这个路径。

---

### C2. `routers/embeddings.py:99-100, 122-123, 141-142` — DB 不可用时返回空成功

```python
@router.get("/cases/{case_id}/embeddings/status")
def embedding_status(...):
    if deps._session_factory is None:
        return {"case_id": case_id, "status": "no_database", "indexed_count": 0}

@router.get("/cases/{case_id}/similarity")
def get_similar_panels(...):
    if deps._session_factory is None:
        return {"similar_panels": []}

@router.get("/cases/{case_id}/similarity/pairs")
def get_all_similar_pairs(...):
    if deps._session_factory is None:
        return {"pairs": []}
```

**问题**：
- DB 不可用时，similarity 接口返回 HTTP 200 + `{"similar_panels": []}`
- 用户看到"0 个相似 panel"，会以为"没有发现抄袭"
- 实际上查询根本没跑 — 是基础设施故障，不是阴性结果
- 前端 `VisualForensicsPage.jsx` 无法区分"空结果"和"系统故障"

**生产影响**：**这是最危险的 bug**。PI 会以为学生数据没有问题，实际上整个检测被跳过了。

**应该怎么做**：返回 HTTP 503 + `{"error": "database_unavailable"}`，让前端显示红色告警。

**测试覆盖**：无。测试假设 DB 始终可用。

---

### C3. `investigations.py:180-181` — Investigation record 写入 DB 失败被静默吞掉

```python
def _save_record_to_db(self, case_id, record):
    ...
    except Exception:
        session.rollback()
    finally:
        session.close()
```

**问题**：
- DB 写入失败（约束冲突、连接断开、磁盘满）时，没有任何日志或告警
- JSONL 写入成功但 DB 写入失败 → 数据不一致
- 前端 Investigation Board 从 DB 读取，看不到这条记录 → 用户以为调查没跑
- CLI 从 JSONL 读取能看到 → 两个入口看到不同的数据

**生产影响**：用户通过 Web UI 看不到自己触发的 SILA dense 结果，但 CLI 能看到。同一个事实被两个数据源矛盾维护。

**测试覆盖**：无。测试只验证 happy path（`test_web_investigation_runs_dense_on_selected_panels` 用 monkeypatch 替换了 `detect_sila_dense`，完全不涉及 DB 写入失败路径）。

---

## HIGH — 应该修复

### H1. `embeddings.py:74-78` — 图片加载失败被静默跳过

```python
for p in batch_paths:
    try:
        img = Image.open(p).convert("RGB")
        tensors.append(preprocess(img))
    except Exception:
        continue  # Skip unreadable images
```

**问题**：
- 捕获 `Exception`（包括路径错误、权限错误、文件损坏），全部 `continue`
- 如果所有 1071 张图片全部加载失败，返回空列表
- 调用方 `index_panels` 检查 `len(embeddings) != len(image_paths)`，返回 `status: "partial"`
- 但 `routers/embeddings.py:73` 将 "partial" 直接作为 job status 写入 → job 显示为 "partial"，indexed_count=0
- 用户看到"partial"但不知道是 1/1071 还是 0/1071

**生产影响**：如果 `panel_evidence.json` 中的 `crop_path` 全部指向不存在的路径（路径迁移/重命名后），索引结果为 0 但状态不是 "failed"。

---

### H2. `embeddings.py:176-181` — 索引数为 0 但状态是 "partial" 不是 "failed"

```python
if len(embeddings) != len(image_paths):
    return {
        "status": "partial",
        "indexed_count": len(embeddings),
        ...
    }
```

当 `indexed_count=0` 时，状态应该是 `"failed"`，不是 `"partial"`。"partial" 暗示"部分成功"，0 是完全失败。

---

### H3. `sila_dense.py:192-195` — mask coverage 计算失败时 fallback 到 0.5

```python
try:
    mask_img = np.array(Image.open(mask_path).convert("L"))
    coverage = float(np.count_nonzero(mask_img)) / max(mask_img.size, 1)
    score = min(1.0, coverage * 5)
except Exception:
    score = 0.5  # Default score if coverage calculation fails
```

**问题**：
- mask 覆盖度计算失败时，给一个固定的 0.5 分数
- 如果 `min_score=0.05`（默认值），0.5 远超阈值 → 这个 panel 会被报告为"检测到 copy-move"
- 但这个分数是基于"计算失败"，不是基于真实检测
- **伪造了一个虚假阳性结果**

**应该怎么做**：`score = 0.0` 或直接 `continue`（跳过这个 panel），并在 `errors` 中记录失败原因。

---

### H4. `embeddings.py` 后台任务异常处理不完整

```python
# routers/embeddings.py:65-81
def _run_index() -> None:
    session = deps._session_factory()
    try:
        ...
    except Exception as exc:
        update_index_job(session, case_id, "failed", detail=str(exc))
    finally:
        session.close()
```

**问题**：如果 `_run_index` 本身抛出异常（例如 session factory 返回 None），`update_index_job` 也会失败，session 不会 close。但更严重的是：如果 `update_index_job(session, "running")` 成功但后续 `index_panels` 抛出异常，且 `update_index_job(session, "failed")` 也失败（DB 断连），job 会永远卡在 "running" 状态。

---

### H5. `routers/review.py:24-25` — workdir 不存在时返回空列表

```python
@router.get("/cases/{case_id}/review-items")
def list_review_items(...):
    workdir = deps.artifacts.latest_workdir(case_id)
    if not workdir:
        return {"items": []}
```

audit 没跑完时，review queue 显示"0 项待审核"，看起来像"一切正常"，实际是"没有数据可审核"。

---

## MEDIUM — 可以后续处理

### M1. `models.py:69-76` — 无效 status 静默规范化

```python
def normalize_case_status(status: str) -> str:
    if status not in CASE_STATUSES:
        return "Draft"
    return status
```

任何非法 status 都被静默替换为 "Draft"。如果上游 bug 写了 "completed_typo"，会被默默变成 "Draft"，case 会回到初始状态。

### M2. `embeddings.py:141-142` — panel evidence 不存在返回 "no_panels"

```python
if not panel_doc:
    return {"status": "no_panels", "indexed_count": 0, "elapsed_seconds": 0}
```

状态是 "no_panels" 不是 "failed"。如果 `panel_evidence.json` 因为 audit 失败不存在，用户看到"no panels"而不是"audit artifacts missing"。

### M3. 前端 `api.js` 无降级感知

前端代码中所有 API 调用都是 `request(...)` → 成功就渲染数据。没有任何逻辑区分：
- `{"items": []}` = "没有 review 项"（正常）
- `{"items": []}` = "系统故障返回空"（异常）

前端应该检查 response 中是否有 `error`、`status` 字段表示降级状态。

---

## 【测试审计】

### 测试覆盖的致命盲区

| 测试文件                     | 测试了什么                                   | 没测试什么                                               |
| ---------------------------- | -------------------------------------------- | -------------------------------------------------------- |
| `test_web_embeddings.py`     | cosine 数学正确性、手动插入 embedding 后查询 | 真实 SSCD 编码、图片加载失败、DB 断连、embedding 全为 0  |
| `test_web_investigations.py` | monkeypatch 后的调查流程                     | DB 写入失败、artifact 路径不存在、JSONL/DB 不一致        |
| `test_web_app.py`            | fake_audit_func 的 happy path                | 真实 audit 失败、runner 异常、stale run 恢复后数据完整性 |

### 核心问题

1. **所有测试都假设基础设施正常工作。** 没有任何测试验证"DB 断了"、"文件丢了"、"model 加载失败"时系统是否正确报错。
2. **测试只验证"不崩"，不验证"报对错"。** 例如 `test_no_panel_evidence_returns_no_panels` 验证返回 `status: "no_panels"` — 但这个 status 本身就是错误的降级。
3. **没有负例测试。** 没有测试"当 1071 张图中 1070 张加载失败时，系统是否正确告警"。
4. **没有端到端降级测试。** 没有测试"DB 断连时，similarity 接口是否返回 503 而不是 200+空列表"。

---

## 【风险清单】

| 可能破坏的旧行为                               | 修复方向                                    |
| ---------------------------------------------- | ------------------------------------------- |
| DB 断连时 API 返回空成功 → 改为 503            | 前端需要处理 503 并显示告警 UI              |
| `normalize_case_status` 宽松行为 → 改为 strict | 调用方需要处理 ValueError                   |
| `_save_record_to_db` 静默失败 → 改为日志+告警  | 需要确定 DB 写入失败是否应该让 API 返回 500 |
| `score = 0.5` fallback → 改为 0.0 或 skip      | 会减少 copy-move 检测的 false positive 数量 |

| 未覆盖的路径                     | 优先级 |
| -------------------------------- | ------ |
| DB 断连时所有 API 端点的行为     | P0     |
| SSCD 编码所有图片都失败          | P0     |
| Investigation record DB 写入失败 | P1     |
| 前端对 503/降级状态的展示        | P1     |
| Mask coverage 计算失败           | P1     |

---

## 【执行方案建议】

**P0 修复（应该在合入前完成）**：

1. `routers/embeddings.py` — DB 不可用时返回 503，不返回空成功
2. `investigations.py:180-181` — `_save_record_to_db` 失败时至少 `logger.error()`
3. `sila_dense.py:195` — `score = 0.5` 改为 `continue` + 记录到 errors
4. `database.py:47-52` — 至少 log warning，不要 bare `pass`

**P1 修复（下一阶段）**：

5. 补负例测试：DB 断连、图片全失败、artifact 缺失
6. `embeddings.py:176-181` — `indexed_count=0` 时 status 改为 "failed"
7. 前端增加降级感知：检查 response 中的 error/status 字段
8. `routers/review.py:24-25` — workdir 缺失时返回 404 或带 status 的响应

**不改（风险低）**：

9. `normalize_case_status` — 当前只有内部代码调用，不直接暴露给外部输入
10. `_read_json` 的 legacy fallback — 路径兼容是真实需求，只要最终返回 None 时调用方正确处理就行

---

以上是纯 review 意见，等你决策哪些需要修、哪些可以接受。