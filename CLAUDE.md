@AGENTS.md

# Claude Entry Point

Read and follow `AGENTS.md`. It is the single source of truth for this repository.

Do not duplicate project rules in `CLAUDE.md`; duplicated rules will drift. If Claude cannot expand `@AGENTS.md`, open `AGENTS.md` directly before making changes.

Current local operations are documented in `README.md` and the root `Makefile`. Python dependencies are managed by `uv`; the usual checks are `make sync`, `make test`, and `make lint-python`.

**⚠️ 环境约束**：本项目使用 `uv` 管理 Python 环境和依赖。所有 Python 命令（`python`、`pytest`、`ruff` 等）必须通过 `uv run` 执行，或先激活 uv 虚拟环境。**禁止使用系统 Python**（`/usr/bin/python`），因为系统环境缺少项目依赖且 Python 版本不兼容（系统为 3.8，项目要求 ≥3.11）。常用命令：
- `uv run python -m pytest tests/` — 运行测试
- `uv run ruff check .` — lint 检查
- `make sync` — 同步依赖到 uv 环境

For current module/data-flow orientation, read `CodeMAP.md` and `Dataflow.md` before making cross-module changes. Visual forensics is currently a first-party beta with ELIS adapters planned, not a fully replaced ELIS pipeline.
