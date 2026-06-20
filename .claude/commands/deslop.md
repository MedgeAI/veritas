# /deslop — Veritas Entropy Control Skill

You are running the Veritas code entropy control pipeline. Your goal: use deterministic tools to find and fix low-risk code slop left by LLM-generated edits. You do NOT rely on your own judgment to decide what is "slop" — you trust tool output.

## Invocation

```
/deslop           → quick mode: only changed files (default)
/deslop full      → full mode: entire codebase
/deslop python    → Python-only (Ruff + Vulture + import-linter)
/deslop frontend  → Frontend-only (Biome + Knip + dependency-cruiser)
```

## Execution Rules

1. **Never auto-delete without presenting findings first.** Show what tools found, then ask user to confirm deletions.
2. **Never modify `engine/static_audit/upstream/` or `third_party/`.** These are read-only.
3. **Never delete Pydantic model fields, TypedDict fields, or dataclass fields.** Vulture false positives.
4. **Never delete `__init__.py` re-exports.** These are API contracts.
5. **After every fix, run `make test` (or targeted pytest) to verify no regressions.**
6. **Output a risk list at the end** (per AGENTS.md format).

---

## Quick Mode (default) — Changed Files Only

### Step 1: Identify changed files

```bash
git diff --name-only HEAD -- '*.py' '*.jsx' '*.js' '*.ts' '*.tsx'
```

If no changed files, tell the user and stop.

### Step 2: Python changed files — Ruff fix + format

For each changed `.py` file (excluding `engine/static_audit/upstream/` and `third_party/`):

```bash
uv run ruff check --fix <file>
uv run ruff format <file>
```

Show what was fixed (diff).

### Step 3: import-linter (fast — always full codebase, but fast)

```bash
uv run lint-imports
```

If any contract is BROKEN, report it as `[blocked]` — these are architectural violations that must be fixed.

### Step 4: Vulture (only if Python files changed in scope)

```bash
uv run vulture <changed-files> --min-confidence 80 --sort-by-size
```

Present findings. Do NOT auto-delete. Ask user to confirm.

### Step 5: Frontend changed files (if any `.jsx`/`.js`/`.ts`/`.tsx` changed)

```bash
cd web/frontend && npx depcruise --validate .dependency-cruiser.cjs src/
```

If violations found, report as `[blocked]`.

### Step 6: Verify

```bash
uv run python -m pytest tests/ -q --tb=line -x
```

If tests fail, report failures and stop. Do NOT attempt to fix test failures by modifying tests.

### Step 7: Report

Present a summary table:

| Category | Count | Action |
|---|---|---|
| Auto-fixed (Ruff) | N | Already applied |
| Dead code (Vulture) | N | Awaiting user confirm |
| Architecture violations | N | Must fix |
| Tests | pass/fail | Status |

Then output the standard risk list.

---

## Full Mode — Entire Codebase

Run `make deslop` and process the output:

```bash
make deslop
```

Then follow the same present-findings → ask-confirm → verify → report flow as quick mode.

---

## Python-Only Mode

Skip frontend tools. Run:
1. `uv run ruff check --fix cli/ engine/ runtime/ protocols/ web/backend/ tests/ scripts/`
2. `uv run ruff format cli/ engine/ runtime/ protocols/ web/backend/ tests/ scripts/`
3. `uv run vulture cli/ engine/ runtime/ protocols/ web/backend/ scripts/ --exclude engine/static_audit/upstream/ --min-confidence 80 --sort-by-size`
4. `uv run lint-imports`
5. Verify tests.

---

## Frontend-Only Mode

Skip Python tools. Run:
1. `cd web/frontend && npx biome check --write .` (if available)
2. `cd web/frontend && npx knip`
3. `cd web/frontend && npx depcruise --validate .dependency-cruiser.cjs src/`
4. `cd web/frontend && npm test`

---

## Prohibited Actions

- Do NOT modify files in `engine/static_audit/upstream/` or `third_party/`
- Do NOT delete `__init__.py` imports (they are API re-exports)
- Do NOT delete Pydantic BaseModel fields, TypedDict fields, or dataclass fields
- Do NOT delete Vulture findings below 80% confidence
- Do NOT modify test expectations to make tests pass
- Do NOT "improve" adjacent code that isn't part of the cleanup scope
- Do NOT swallow exceptions or add `# noqa` to silence warnings without understanding why
