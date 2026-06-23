# Tool Contract (Auto-Generated)

> DO NOT EDIT — generated from `engine/tools/registry.py` by `scripts/build_tool_contract.py`

## Summary

| Metric | Value |
|---|---|
| Total tools | 30 |
| Mandatory Baseline | 10 |
| Conditional Baseline | 5 |
| Agent Selectable | 11 |
| Report Only | 4 |

## Mandatory Baseline

| tool_id | deterministic | agent_selectable | input_artifacts | output_artifacts |
|---|---|---|---|---|
| `mineru.parse_pdf` | yes | no | `paper.pdf` | `mineru/full.md, mineru/mineru_manifest.json, visual/images/` |
| `paper.evidence_ledger` | yes | no | `mineru/full.md, mineru/mineru_manifest.json` | `mineru/evidence_ledger.json` |
| `paper.numeric_forensics` | yes | no | `mineru/full.md` | `numeric/forensics.json` |
| `paperfraud.rule_match` | yes | no | `mineru/full.md` | `numeric/paperfraud_rules.json` |
| `material.inventory` | yes | no | `-` | `materials/material_inventory.json` |
| `image.exact_duplicates` | yes | no | `visual/images/` | `visual/exact_duplicates.json` |
| `visual.panel_extraction` | yes | no | `visual/images/` | `visual/evidence.json, visual/panel_evidence.json` |
| `visual.tru_for` | yes | no | `visual/evidence.json` | `visual/forged_region_evidence.json` |
| `visual.provenance_graph` | yes | no | `visual/evidence.json` | `visual/provenance_graph.json` |
| `visual.image_quality` | yes | no | `visual/evidence.json` | `visual/image_quality.json` |

## Conditional Baseline

| tool_id | deterministic | agent_selectable | input_artifacts | output_artifacts |
|---|---|---|---|---|
| `source_data.profile` | yes | no | `materials/agent_material_plan.json` | `source_data/profile.json` |
| `source_data.findings` | yes | no | `source_data/profile.json, mineru/full.md` | `source_data/findings.json` |
| `source_data.pair_forensics` | yes | no | `source_data/profile.json` | `source_data/pair_forensics.json` |
| `source_data.cross_sheet` | yes | no | `source_data_dir` | `source_data/cross_sheet.json` |
| `source_data.verdict` | **no** | no | `source_data/findings.json, source_data/pair_forensics.json, source_data/profile.json` | `source_data/findings_verdict.json` |

## Agent Selectable

| tool_id | deterministic | agent_selectable | input_artifacts | output_artifacts |
|---|---|---|---|---|
| `agent.material_plan` | **no** | yes | `materials/material_inventory.json` | `materials/agent_material_plan.json` |
| `paperconan.numeric_forensics` | yes | yes | `source_data_dir` | `numeric/paperconan_scan.json` |
| `image.similarity_candidates` | yes | yes | `visual/images/` | `visual/similarity_candidates.json` |
| `visual.copy_move` | yes | yes | `visual/panel_evidence.json, visual/evidence.json` | `visual/copy_move.json` |
| `visual.copy_move_dense` | yes | yes | `visual/panel_evidence.json, visual/evidence.json` | `visual/copy_move_dense.json` |
| `visual.overlap_reuse` | yes | yes | `visual/panel_evidence.json, visual/evidence.json` | `visual/overlap_reuse.json` |
| `visual.cbir_search` | yes | yes | `visual/panel_evidence.json, visual/evidence.json` | `visual/cbir_search.json` |
| `agent.review` | **no** | yes | `-` | `agents/review.json` |
| `agent.role.claim_extractor` | **no** | yes | `-` | `agents/claim_extractor.json, agent_traces/claim_extractor.json` |
| `agent.role.source_data_auditor` | **no** | yes | `-` | `agents/source_data_auditor.json, agent_traces/source_data_auditor.json` |
| `agent.role.judge` | **no** | yes | `-` | `agents/judge.json, agent_traces/judge.json` |

### Selection Rules

Agent investigation rounds may only select tools from this phase. Constraints enforced by `validate_investigation_tool_action()`:

- Tool must have `execution_phase = agent_selectable`
- Tool must be `deterministic = true` (non-deterministic agents are invoked via role layer, not investigation)
- Params are validated against `param_schema` ranges in registry
- Max 3 investigation rounds per audit run
- Each action requires `hypothesis`, `depends_on_artifacts`, and `expected_evidence_type`

## Report Only

| tool_id | deterministic | agent_selectable | input_artifacts | output_artifacts |
|---|---|---|---|---|
| `visual.finding_pipeline` | yes | no | `visual/panel_evidence.json, visual/copy_move.json, visual/exact_duplicates.json` | `visual/relationships.json, visual/findings.json` |
| `static_audit.bundle` | yes | no | `-` | `reports/static_audit_bundle.json` |
| `report.render_markdown` | yes | no | `reports/static_audit_bundle.json` | `reports/final_audit_report.md, reports/audit_run_manifest.json` |
| `report.render_static_html` | yes | no | `reports/audit_run_manifest.json, reports/static_audit_bundle.json` | `reports/final_audit_report.html` |
