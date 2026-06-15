# Output Directory Structure

This directory contains the complete output of a Veritas audit run. Files are organized by responsibility to make them easy to navigate for both humans and agents.

## Directory Layout

```
.
├── README.md                      # This file
├── inputs/                        # Original input files (PDF)
│   └── paper.pdf
├── mineru/                        # MinerU PDF parsing intermediate artifacts
│   ├── full.md                    # Full markdown conversion
│   ├── evidence_ledger.json       # Evidence ledger with claim references
│   ├── mineru_manifest.json       # MinerU output manifest
│   └── layout.json                # PDF layout information
├── materials/                     # Material inventory and plans
│   ├── material_inventory.json    # Scanned materials list
│   └── agent_material_plan.json   # Agent-selected evidence lanes
├── source_data/                   # Source Data tool outputs
│   ├── profile.json               # Workbook/sheet profiles
│   ├── findings.json              # Duplicate columns, fixed relationships
│   ├── pair_forensics.json        # Row-offset, paired-ratio patterns
│   └── cross_sheet.json           # Cross-sheet duplicate detection
├── visual/                        # Visual forensics tool outputs
│   ├── images/                    # Extracted PDF images
│   ├── panels/                    # Extracted panel crops
│   ├── yolov5_batch/              # YOLOv5 batch processing results
│   ├── evidence.json              # Figure-level evidence
│   ├── panel_evidence.json        # Panel-level evidence
│   ├── findings.json              # Visual findings clusters
│   ├── relationships.json         # Image relationships
│   ├── copy_move.json             # Copy-move detection results
│   ├── exact_duplicates.json      # Byte-identical image duplicates
│   └── similarity_candidates.json # Near-duplicate candidates
├── numeric/                       # Numeric forensics tool outputs
│   ├── forensics.json             # PDF numeric forensics
│   ├── paperfraud_rules.json      # PaperFraud rule matches
│   └── paperconan_scan.json       # Paperconan scan results
├── agents/                        # Agent outputs, traces, context packs, logs
│   ├── plan.json                  # Agent audit plan
│   ├── review.json                # Agent review output
│   ├── claim_extractor.json       # Claim extractor role output
│   ├── source_data_auditor.json   # Source Data auditor role output
│   ├── judge.json                 # Judge role output
│   ├── traces/                    # Raw agent traces
│   ├── context_pack_*.json        # Bounded context packs for each role
│   └── logs/                      # Agent logs (long text overflow)
├── investigation/                 # Investigation rounds (Agent-selectable tools)
│   ├── investigation_rounds.jsonl # Round-by-round investigation log
│   └── round_XX/                  # Per-round tool outputs
└── reports/                       # Final deliverables
    ├── final_audit_report.html    # Interactive HTML report
    ├── final_audit_report.md      # Markdown report
    ├── static_audit_bundle.json   # Consolidated audit bundle
    └── audit_run_manifest.json    # Run manifest with provenance
```

## Key Files

| File | Location | Purpose |
|------|----------|---------|
| `final_audit_report.html` | `reports/` | Primary human-readable report |
| `static_audit_bundle.json` | `reports/` | Consolidated evidence for downstream tools |
| `audit_run_manifest.json` | `reports/` | Complete run manifest with tool outputs and timing |
| `material_inventory.json` | `materials/` | What was submitted |
| `agent_material_plan.json` | `materials/` | What the Agent chose to analyze |

## For Agents

Use `resolve_artifact_path(workdir, "legacy_name")` to resolve legacy filenames to their new locations. For example:

```python
from engine.static_audit.orchestrator import resolve_artifact_path

# Resolve "full.md" to "mineru/full.md"
path = resolve_artifact_path(workdir, "full.md")
# Returns: workdir / "mineru/full.md"
```

## For Humans

Start with `reports/final_audit_report.html` for the complete audit results. The directory structure groups related artifacts together, so you can drill into specific categories (e.g., `visual/` for all image forensics, `source_data/` for all source data analysis).

## Version

This layout was introduced in Veritas v0.8 to replace the previous flat directory structure where all artifacts were placed at the root level.
