# Audit Output Layout

`outputs/<case_id>/research-integrity-audit/` 的产物目录结构。

每个条目标注：作用、生产者（函数 + step_key）、执行阶段。

## 数据流总览

```
输入材料 (PDF + Source Data + Code)
  │
  ▼
┌─ mandatory_bootstrap ──────────────────────────────┐
│  discover → material_inventory → agent_material_plan│
│  mineru → evidence_ledger                           │
│  numeric_forensics → paperfraud_rule_match          │
│  source_data (profile/findings/pair/cross_sheet)    │
│  exact_image_duplicates                             │
│  agent_plan                                         │
└─────────────────────────────────────────────────────┘
  │
  ▼
┌─ mandatory_visual ─────────────────────────────────┐
│  visual_panel_extraction (YOLOv5 → panels/)         │
│  visual_finding_pipeline (copy-move + exact dup)    │
│  visual_tru_for (GPU, 伪造区域热力图)               │
│  visual_provenance_graph                            │
│  visual_copy_move_dense (SILA dense, GPU)           │
└─────────────────────────────────────────────────────┘
  │
  ▼
┌─ investigation_rounds ─────────────────────────────┐
│  agent_investigation_plan (≤3 轮)                   │
│  每轮选择 tool_id → 执行 → 写入 investigation/      │
│  可选工具: copy_move, image_similarity, sila_dense  │
└─────────────────────────────────────────────────────┘
  │
  ▼
┌─ role_layer ───────────────────────────────────────┐
│  claim_extractor → source_data_auditor → judge      │
│  + reserved roles: defense, digit_pattern,          │
│    domain_sanity, math_consistency                │
└─────────────────────────────────────────────────────┘
  │
  ▼
┌─ terminal ─────────────────────────────────────────┐
│  static_audit_bundle → report (md) → html_report    │
│  audit_run_manifest                                 │
└─────────────────────────────────────────────────────┘
```

## 目录详解

### `materials/` — 材料清单与 Agent 材料计划

| 文件 | 生产者 | step_key | 阶段 |
|------|--------|----------|------|
| `material_inventory.json` | `build_material_inventory()` → `write_material_inventory()` (materials.py) | `material_inventory` | mandatory_bootstrap |
| `agent_material_plan.json` | `run_agent_material_plan()` (orchestrator.py) | `agent_material_plan` | mandatory_bootstrap |

### `mineru/` — MinerU PDF 解析产物 (~56MB)

| 文件 | 生产者 | step_key | 阶段 |
|------|--------|----------|------|
| `full.md` | `mineru_convert.py` → MinerU API | `mineru` | mandatory_bootstrap |
| `evidence_ledger.json` | `build_evidence_ledger.py` | `evidence_ledger` | mandatory_bootstrap |
| `layout.json` | MinerU API 原始输出 | `mineru` | mandatory_bootstrap |
| `mineru_manifest.json` | `mineru_convert.py:write_manifest()` | `mineru` | mandatory_bootstrap |
| `*_middle.json` | MinerU API 中间文件 | `mineru` | mandatory_bootstrap |

### `visual/` — 视觉取证产物

| 文件/子目录 | 生产者 | step_key | 阶段 |
|------------|--------|----------|------|
| `images/` | MinerU → `_relocate_mineru_outputs()` 移入 | `mineru` | mandatory_bootstrap |
| `evidence.json` | `run_visual_panel_extraction()` (orchestrator.py) | `visual_panel_extraction` | mandatory_visual |
| `panel_evidence.json` | 同上 | `visual_panel_extraction` | mandatory_visual |
| `exact_duplicates.json` | `exact_image_duplicates.py` | `exact_image_duplicates` | mandatory_visual |
| `findings.json` | `run_visual_finding_pipeline()` | `visual_finding_pipeline` | mandatory_visual |
| `relationships.json` | 同上 | `visual_finding_pipeline` | mandatory_visual |
| `forged_region_evidence.json` | `run_tru_for_detection()` | `visual_tru_for` | mandatory_visual |
| `provenance_graph.json` | `run_provenance_graph()` | `visual_provenance_graph` | mandatory_visual |
| `copy_move_dense.json` | `run_sila_dense_detection()` | `visual_copy_move_dense` | mandatory_visual |
| `copy_move.json` | `run_investigation_tool_action()` | `investigation_*_copy_move` | investigation_rounds |
| `similarity_candidates.json` | `run_investigation_tool_action()` | `investigation_*_img_sim` | investigation_rounds |

### `panels/` — Panel 裁剪图 (~772 files, ~27MB)

由 ELIS YOLOv5 panel-extractor 从 composite figure 中裁出。

| 路径 | 生产者 | step_key | 阶段 |
|------|--------|----------|------|
| `panels/<figure_id>/<label>.png` | `extract_panels_batch()` → `_convert_csv_rows_to_panels()` (panel_extraction.py) | `visual_panel_extraction` | mandatory_visual |
| `panels/<figure_id>/a.png` (fallback) | `whole_figure_panel()` — YOLOv5 检测零 panel 时的兜底 | 同上 | mandatory_visual |

### `yolov5_batch/` — YOLOv5 原始输出

| 文件 | 生产者 | step_key | 阶段 |
|------|--------|----------|------|
| `PANELS.csv` | ELIS `extract.py` subprocess 输出 | `visual_panel_extraction` | mandatory_visual |

### `provenance/` — 图像溯源可视化 (~2490 files, ~347MB)

| 路径 | 生产者 | step_key | 阶段 |
|------|--------|----------|------|
| `provenance/` | `build_provenance_graph()` (provenance_graph.py) | `visual_provenance_graph` | mandatory_visual |
| `provenance/provenance_cross/` | ELIS copy-move runner subprocess 可视化输出 | 同上 | mandatory_visual |

### `tru_for/` — TruFor 伪造检测热力图

| 路径 | 生产者 | step_key | 阶段 |
|------|--------|----------|------|
| `tru_for/<figure_id>/` | `run_tru_for()` (tru_for.py) — ELIS TruFor runner subprocess | `visual_tru_for` | mandatory_visual |

### `numeric/` — 数值取证

| 文件 | 生产者 | step_key | 阶段 |
|------|--------|----------|------|
| `forensics.json` | `numeric_forensics.py` (third_party/research-integrity-auditor) | `numeric_forensics` | mandatory_bootstrap |
| `paperfraud_rules.json` | `run_paperfraud_rule_match()` (paperfraud_rules.py) | `paperfraud_rule_match` | mandatory_bootstrap |

### `source_data/` — Source Data 审查

| 文件 | 生产者 | step_key | 阶段 |
|------|--------|----------|------|
| `profile.json` | `source_data_profile.py` | `source_data_profile` | mandatory_bootstrap |
| `findings.json` | `source_data_findings.py` | `source_data_findings` | mandatory_bootstrap |
| `pair_forensics.json` | `source_data_pair_forensics.py` | `source_data_pair_forensics` | mandatory_bootstrap |
| `cross_sheet.json` | `source_data_cross_sheet.py` | `source_data_cross_sheet` | mandatory_bootstrap |

### `investigation/` — Agent 调查轮次记录

| 路径 | 生产者 | step_key | 阶段 |
|------|--------|----------|------|
| `investigation_rounds.jsonl` | `append_investigation_record()` (investigation.py) | 多个 round step_keys | investigation_rounds |
| `round_XX/<action_id>/` | `run_investigation_tool_action()` 的工具输出 | `investigation_{round}_{action}` | investigation_rounds |

### `agents/` — Agent 结构化输出

| 文件 | 生产者 | step_key | 阶段 |
|------|--------|----------|------|
| `audit_plan.json` | `run_agent_plan()` → `_run_with_context_pack(role="plan")` | `agent_plan` | mandatory_bootstrap |
| `review.json` | `run_agent_review()` → `_run_with_context_pack(role="review")` | `agent_review` | agent_selectable |
| `claim_extractor.json` | `run_agent_role(role_id="claim_extractor")` | `agent_role_claim_extractor` | role_layer |
| `source_data_auditor.json` | `run_agent_role(role_id="source_data_auditor")` | `agent_role_source_data_auditor` | role_layer |
| `judge.json` | `run_agent_role(role_id="judge")` | `agent_role_judge` | role_layer |
| `investigation_plan_round_01.json` | `run_agent_investigation_plan()` | `agent_investigation_plan_round_01` | investigation_rounds |
| `traces/<role>.json` | `write_role_trace()` — opencode 原始调用 trace | 对应 role step_key | role_layer |

### `logs/` — Agent 调用日志

| 路径 | 生产者 | 阶段 |
|------|--------|------|
| `logs/<role>_<timestamp>.log` | `AgentStepRunner._write_log_artifact()` (agent_step_runner.py) | role_layer |
| `logs/<step_key>_<timestamp>.log` | `_write_long_text_to_log()` (orchestrator.py) | 全 pipeline |

### `reports/` — 最终报告

| 文件 | 生产者 | step_key | 阶段 |
|------|--------|----------|------|
| `static_audit_bundle.json` | `build_static_audit_bundle()` | `static_audit_bundle` | terminal |
| `final_audit_report.md` | `generate_report()` | `report` | terminal |
| `final_audit_report.html` | `write_static_audit_html()` (html_report/_core.py) | `html_report` | terminal |
| `audit_run_manifest.json` | manifest 序列化 (orchestrator.py:3726-3733) | (terminal) | terminal |

### `inputs/` — 空目录

由 `ensure_output_subdirs()` 创建，无代码向此目录写入。PDF 路径仅记录在 manifest 中。

## 根目录散文件（遗留问题）

以下文件应由 `ARTIFACT_PATH_MAP` 归入子目录，但因 legacy flat path 仍写在根目录：

### `agent_*.json` (9 files)

Role 层 agent 的结构化输出。应归入 `agents/`。

| 文件 | 对应 role | real_in_v1 |
|------|-----------|-----------|
| `agent_claim_extractor.json` | claim_extractor | ✅ |
| `agent_source_data_auditor.json` | source_data_auditor | ✅ |
| `agent_judge.json` | judge | ✅ |
| `agent_defense.json` | defense | ❌ reserved |
| `agent_digit_pattern.json` | digit_pattern | ❌ reserved |
| `agent_domain_sanity.json` | domain_sanity | ❌ reserved |
| `agent_math_consistency.json` | math_consistency | ❌ reserved |
| `agent_visual_triage.json` | visual_triage | removed (PRD3-T6) |
| `agent_investigation_plan_round_01.json` | investigation_plan | ✅ |

### `context_pack_*.json` (7 files)

Agent 调用的 bounded context 快照。应归入 `agents/` 或 `logs/`。

由 `_run_with_context_pack()` (_shared.py:100-101) 写入 `workdir / f"context_pack_{role}.json"`。

### `<hash>_*` (MinerU 原始产物)

| 文件 | 说明 |
|------|------|
| `<hash>_content_list.json` | MinerU content_list 中间文件 |
| `<hash>_content_list_v2.json` | MinerU content_list v2 |
| `<hash>_model.json` | MinerU 模型输出 |
| `<hash>_origin.pdf` | MinerU 接收的原始 PDF 副本 |

`_relocate_mineru_outputs()` 未覆盖这些以 paper hash 为前缀的文件，导致它们留在根目录。

## 已知问题

1. **根目录文件散落**：`ARTIFACT_PATH_MAP` 定义了目标子目录，但 `write_reserved_role_output()` 和 `_run_with_context_pack()` 仍写入 `workdir / filename` (legacy flat path)。需要统一迁移逻辑。
2. **MinerU 原始产物未完全迁移**：`_relocate_mineru_outputs()` 遗漏了 `*_content_list.json`、`*_model.json`、`*_origin.pdf`。
3. **`inputs/` 空目录**：`OUTPUT_DIRS` 定义了它但无写入者。应移除或让 discover 步骤实际复制输入文件到此目录。
