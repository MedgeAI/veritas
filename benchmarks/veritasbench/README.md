# VeritasBench

This directory is the paper-evaluation boundary for the 50-paper benchmark.
The repository currently contains the schema and experiment contract, not the
paper cases. A paper result is invalid until the manifest, suite, case files,
annotations, and observation artifacts are present and hashed.

## Required layout

```text
manifest.json
suites/veritasbench_50.json
cases/<case_id>/case.json
cases/<case_id>/artifacts/...
```

`case.json` is validated by `case.schema.json`. Every claim relation must have
an annotation and every verifier input must come from `observations`, never
from the annotation verdict. Observation records require an artifact hash and
source span so a result can be replayed and audited.

## Anti-leakage rules

- `claims[].verdict` is ground truth only; it must never be read to construct a
  verifier input or a predicted verdict.
- `observations` contain the values available to the verifier and must be
  derived from paper/source artifacts before annotation labels are applied.
- Clean claims are declared with `is_clean_claim: true` and are used only for
  FAR calculation.
- Mock cases and `_process_case_mock` are regression fixtures only. They are
  not a valid paper benchmark run.
- The 50 cases are split by paper. No claim from one paper may appear in more
  than one split.

## Run contract

The source of truth for the planned matrix is
`configs/experiments/veritasbench_b1_b5.yaml`:

- 50 cases x 5 tiers = 250 primary runs.
- 3 repeats per run = 750 repeat runs for consistency measurement.
- B4 and B5 use the same upstream pipeline and differ only in aggregation
  policy (`flat` versus `graph_aware`).

Results must include the input/config/tool/model identity and a canonical
digest over verdicts and evidence spans. Runtime timestamps and durations are
not part of that digest.

Before execution, prepare the frozen experiment ledger:

```bash
uv run python -m cli.main reproduce experiment-plan \
  --config configs/experiments/veritasbench_b1_b5.yaml \
  --base-path benchmarks/veritasbench \
  --output-dir outputs/experiments/veritasbench
```

This command fails closed unless all 50 cases pass preflight. It writes the
preflight report, experiment manifest, and the deterministic 750-run plan.
The plan is an execution contract, not a prediction result. A tier backend
must write one JSON record per run under `runs/<identity_digest>.json` and
must preserve the canonical result digest for repeat-consistency analysis.
