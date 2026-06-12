@AGENTS.md

# Claude Entry Point

Read and follow `AGENTS.md`. It is the single source of truth for this repository.

Do not duplicate project rules in `CLAUDE.md`; duplicated rules will drift. If Claude cannot expand `@AGENTS.md`, open `AGENTS.md` directly before making changes.

Current local operations are documented in `README.md` and the root `Makefile`. Python dependencies are managed by `uv`; the usual checks are `make sync`, `make test`, and `make lint-python`.
