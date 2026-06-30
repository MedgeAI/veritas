# Veritas local operations Makefile
# Run from the project root.

SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
UV_CACHE_DIR ?= .uv-cache
UV_ENV := UV_CACHE_DIR=$(UV_CACHE_DIR)
PYTHON ?= $(UV_ENV) $(UV) run python
PYTEST ?= $(UV_ENV) $(UV) run pytest
RUFF ?= $(UV_ENV) $(UV) run ruff
PROJECT_PYTHONPATH ?= .
PY_ENV := PYTHONPATH=$(PROJECT_PYTHONPATH)
VERITAS := $(PY_ENV) $(PYTHON) cli/main.py

HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)
export UID := $(HOST_UID)
export GID := $(HOST_GID)

COMPOSE ?= docker compose --env-file $(CURDIR)/.env --env-file $(CURDIR)/deploy/.env -p vdeploy -f deploy/docker-compose.yml
COMPOSE_DEPLOY ?= docker compose --env-file $(CURDIR)/.env --env-file $(CURDIR)/deploy/.env -p vdeploy -f deploy/docker-compose.yml -f deploy/docker-compose.cloudflare.yml
COMPOSE_DB ?= docker compose -p vdev -f deploy/docker-compose.local-db.yml
COMPOSE_FORE ?= docker compose -p vdev -f deploy/docker-compose.forensics.yml

MANIFEST ?= examples/bioinfo_python_case/veritas.json
OUTPUT_DIR ?= outputs/demo
REPORT_JSON ?= $(OUTPUT_DIR)/report.json
OUTPUT_ROOT ?= outputs

PAPER_DIR ?=
CASE_ID ?= local-paper-demo
AGENT_MODE ?= review
AGENT_MODEL ?= dashscope/qwen3.7-plus
AGENT_TIMEOUT_SECONDS ?= 600
AGENT_MAX_RETRIES ?= 1
PROGRESS ?= plain

HOST ?= 127.0.0.1
PORT ?= 8765
WEB_DATA_DIR ?= web_data
FRONTEND_DIR := web/frontend
# Set VERITAS_DEV_DB_URL in your .env or shell, e.g.:
#   export VERITAS_DEV_DB_URL=postgresql://veritas_dev:CHANGEME@127.0.0.1:5433/veritas_dev
LOCAL_DATABASE_URL ?= $(VERITAS_DEV_DB_URL)

.PHONY: help show-config sync install setup \
	up down rebuild restart logs ps shell health docker-health \
	deploy-up deploy-down deploy-rebuild deploy-logs \
	db-up db-down db-init db-migrate db-reset \
	precheck run report demo audit audit-off audit-fresh report-path \
	web-backend web-backend-reload celery-worker web-frontend web-install web-build web-preview dev dev-up dev-down \
	forensics-up forensics-down \
	test test-fast test-unit test-integration test-e2e test-visual test-model \
	lint lint-python lint-web web-test \
	deslop \
	check-prompts lock-prompts \
	clean-demo clean-cache clean-web wipe-local \
	build-elis-provenance check-elis-provenance

help: ## Show available commands
	@echo "Veritas local operations"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Examples:"
	@echo "  make audit PAPER_DIR=input/paper1 CASE_ID=paper1"
	@echo "  make audit-fresh PAPER_DIR=input/paper1 CASE_ID=paper1"
	@echo "  make web-backend"
	@echo "  make web-frontend"

show-config: ## Print effective Makefile variables
	@echo "PYTHON=$(PYTHON)"
	@echo "PYTEST=$(PYTEST)"
	@echo "RUFF=$(RUFF)"
	@echo "UV_CACHE_DIR=$(UV_CACHE_DIR)"
	@echo "PROJECT_PYTHONPATH=$(PROJECT_PYTHONPATH)"
	@echo "MANIFEST=$(MANIFEST)"
	@echo "OUTPUT_DIR=$(OUTPUT_DIR)"
	@echo "OUTPUT_ROOT=$(OUTPUT_ROOT)"
	@echo "PAPER_DIR=$(PAPER_DIR)"
	@echo "CASE_ID=$(CASE_ID)"
	@echo "AGENT_MODE=$(AGENT_MODE)"
	@echo "HOST=$(HOST)"
	@echo "PORT=$(PORT)"
	@echo "WEB_DATA_DIR=$(WEB_DATA_DIR)"
	@echo "LOCAL_DATABASE_URL=$(LOCAL_DATABASE_URL)"

# -- Setup ---------------------------------------------------------------

sync: ## Sync Python dependencies with uv (includes all optional extras)
	$(UV_ENV) $(UV) sync --dev --all-extras

install: sync ## Install/sync the Python environment with uv

setup: sync web-install ## Sync Python and frontend dependencies

# -- Docker lifecycle ----------------------------------------------------

DOCKER_BUILD_ARGS := --build-arg USER_UID=$$(id -u) --build-arg USER_GID=$$(id -g) --build-arg USERNAME=veritas --build-arg BUILD_VERSION=$(shell git rev-parse --short HEAD 2>/dev/null || echo "dev")

docker-build: ## Build Docker image with host user UID/GID (for bind mount compatibility)
	docker build $(DOCKER_BUILD_ARGS) -t veritas:latest .

up: ## Start the Docker web service
	$(COMPOSE) up -d

down: ## Stop Docker services while keeping local volumes
	$(COMPOSE) down

rebuild: ## Rebuild the Docker image and start the web service
	$(COMPOSE) up --build -d

restart: ## Restart the Docker web service
	$(COMPOSE) restart veritas

logs: ## Show Docker web service logs
	$(COMPOSE) logs --tail=100 -f veritas

ps: ## Show Docker service status
	$(COMPOSE) ps

shell: ## Enter the Docker web service shell
	$(COMPOSE) exec veritas sh

docker-health: ## Check Docker web service health via container exec
	@$(COMPOSE) exec -T veritas curl -sf http://localhost:8765/api/health | $(PYTHON) -m json.tool || echo "Docker web service unavailable"

# -- Cloudflare Tunnel Deploy --------------------------------------------

deploy-up: ## Start all services with Cloudflare Tunnel
	$(COMPOSE_DEPLOY) up --build -d

deploy-down: ## Stop all services including Cloudflare Tunnel
	$(COMPOSE_DEPLOY) down

deploy-rebuild: ## Rebuild and restart all services with Cloudflare Tunnel
	$(COMPOSE_DEPLOY) up --build -d --force-recreate
	@echo ""
	@echo "Waiting for services to be healthy..."
	@for i in $$(seq 1 30); do \
		status=$$($(COMPOSE_DEPLOY) ps --format json 2>/dev/null | $(PYTHON) -c "import sys,json; lines=[json.loads(l) for l in sys.stdin if l.strip()]; print('ok' if all(l.get('Health','')=='' or l.get('Health','').startswith('healthy') or l.get('Health','').startswith('running') for l in lines) else 'waiting')" 2>/dev/null || echo "waiting"); \
		if [ "$$status" = "ok" ]; then echo "All services healthy."; break; fi; \
		echo "  [$${i}/30] waiting..."; sleep 2; \
	done
	@echo ""
	@echo "Running post-deploy smoke tests..."
	@$(COMPOSE_DEPLOY) exec -T veritas curl -sf http://localhost:8765/api/health | $(PYTHON) -m json.tool || echo "⚠ /api/health failed"
	@$(COMPOSE_DEPLOY) exec -T veritas curl -sf http://localhost:8765/api/health/deep | $(PYTHON) -m json.tool || echo "⚠ /api/health/deep failed"
	@$(COMPOSE_DEPLOY) exec -T veritas curl -sf http://localhost:8765/api/cases | $(PYTHON) -c "import sys,json; d=json.load(sys.stdin); print(f'✓ /api/cases OK ({len(d.get(\"cases\",[]))} cases)')" || echo "⚠ /api/cases failed"
	@echo ""
	@echo "Deploy complete. Check cloudflared logs: make deploy-logs"

deploy-logs: ## Show cloudflared container logs
	$(COMPOSE_DEPLOY) logs --tail=100 -f cloudflared

# -- ELIS Provenance Container -------------------------------------------

build-elis-provenance: ## Build veritas-elis-provenance Docker image from ELIS submodule
	@./scripts/build-elis-provenance.sh

check-elis-provenance: ## Check if veritas-elis-provenance image exists
	@if docker images | grep -q "veritas-elis-provenance.*latest"; then \
		echo "✓ veritas-elis-provenance:latest exists"; \
		docker images | grep "veritas-elis-provenance"; \
	else \
		echo "✗ veritas-elis-provenance:latest not found"; \
		echo "  Run: make build-elis-provenance"; \
		exit 1; \
	fi

# -- Database lifecycle --------------------------------------------------

db-up: ## Start PostgreSQL + Redis for local development
	$(COMPOSE_DB) up -d postgres redis
	@echo "Waiting for PostgreSQL..."
	@for i in $$(seq 1 15); do \
		if $(COMPOSE_DB) exec -T postgres pg_isready -U veritas_dev -d veritas_dev >/dev/null 2>&1; then \
			echo "PostgreSQL ready."; break; \
		fi; \
		sleep 1; \
	done
	@echo "Waiting for Redis..."
	@for i in $$(seq 1 15); do \
		if $(COMPOSE_DB) exec -T redis redis-cli ping >/dev/null 2>&1; then \
			echo "Redis ready."; break; \
		fi; \
		sleep 1; \
	done

db-down: ## Stop PostgreSQL and Redis containers
	$(COMPOSE_DB) stop postgres redis

db-init: db-up ## Initialise database tables (development only)
	VERITAS_DATABASE_URL="$(LOCAL_DATABASE_URL)" $(PY_ENV) $(PYTHON) -c "from web.backend.veritas_web.database import init_db; init_db()"

db-migrate: ## Migrate web_data/ JSON files to PostgreSQL
	VERITAS_DATABASE_URL="$(LOCAL_DATABASE_URL)" $(PY_ENV) $(PYTHON) scripts/migrate_web_data_to_postgres.py

db-reset: ## Reset database: drop all tables and recreate (DEVELOPMENT ONLY)
	@echo "⚠️  WARNING: This will DELETE all data in the database!"
	@read -p "Continue? [y/N] " confirm && [ $$confirm = "y" ] || exit 1
	VERITAS_DATABASE_URL="$(LOCAL_DATABASE_URL)" $(PY_ENV) $(PYTHON) -c "from web.backend.veritas_web.database import create_db_engine, Base; \
		engine = create_db_engine(); \
		Base.metadata.drop_all(bind=engine); \
		Base.metadata.create_all(bind=engine); \
		print('✓ Database reset: all tables dropped and recreated')"

migrate-decision-type: ## Add decision_type column to review_decisions table (PRD §8.4)
	PGPASSWORD=veritas_dev psql -h localhost -p 5433 -U veritas_dev veritas -c "ALTER TABLE review_decisions ADD COLUMN IF NOT EXISTS decision_type VARCHAR(64);"

# -- CLI audit flow ------------------------------------------------------

precheck: ## Run deterministic precheck against MANIFEST
	$(VERITAS) precheck "$(MANIFEST)"

run: ## Run the lightweight manifest demo into OUTPUT_DIR
	$(VERITAS) run "$(MANIFEST)" --output-dir "$(OUTPUT_DIR)"

report: ## Render markdown/html from REPORT_JSON into OUTPUT_DIR
	$(VERITAS) report "$(REPORT_JSON)" --output-dir "$(OUTPUT_DIR)"

demo: ## Run precheck, run, and report for the lightweight demo manifest
	$(MAKE) precheck
	$(MAKE) run
	$(MAKE) report
	$(MAKE) report-path

audit: ## Run audit-paper; requires PAPER_DIR, optional CASE_ID
	@if [ -z "$(PAPER_DIR)" ]; then \
		echo "PAPER_DIR is required. Example: make audit PAPER_DIR=input/paper1 CASE_ID=paper1"; \
		exit 2; \
	fi
	$(VERITAS) audit-paper "$(PAPER_DIR)" \
		--case-id "$(CASE_ID)" \
		--output-root "$(OUTPUT_ROOT)" \
		--agent-mode "$(AGENT_MODE)" \
		--agent-model "$(AGENT_MODEL)" \
		--agent-timeout-seconds "$(AGENT_TIMEOUT_SECONDS)" \
		--agent-max-retries "$(AGENT_MAX_RETRIES)" \
		--progress "$(PROGRESS)"

audit-off: ## Run deterministic audit-paper without opencode Agent; requires PAPER_DIR
	@if [ -z "$(PAPER_DIR)" ]; then \
		echo "PAPER_DIR is required. Example: make audit-off PAPER_DIR=input/paper1 CASE_ID=paper1"; \
		exit 2; \
	fi
	$(VERITAS) audit-paper "$(PAPER_DIR)" \
		--case-id "$(CASE_ID)" \
		--output-root "$(OUTPUT_ROOT)" \
		--agent-mode off \
		--progress "$(PROGRESS)"

audit-fresh: ## Force a clean audit-paper rerun; requires PAPER_DIR
	@if [ -z "$(PAPER_DIR)" ]; then \
		echo "PAPER_DIR is required. Example: make audit-fresh PAPER_DIR=input/paper1 CASE_ID=paper1"; \
		exit 2; \
	fi
	$(VERITAS) audit-paper "$(PAPER_DIR)" \
		--case-id "$(CASE_ID)" \
		--output-root "$(OUTPUT_ROOT)" \
		--fresh \
		--force \
		--agent-mode "$(AGENT_MODE)" \
		--agent-model "$(AGENT_MODEL)" \
		--agent-timeout-seconds "$(AGENT_TIMEOUT_SECONDS)" \
		--agent-max-retries "$(AGENT_MAX_RETRIES)" \
		--progress "$(PROGRESS)"

report-path: ## Print the expected final audit-paper HTML report path
	@echo "$(OUTPUT_ROOT)/$(CASE_ID)/research-integrity-audit/final_audit_report.html"

# -- Web P1 --------------------------------------------------------------

web-backend: ## Start local web backend in foreground (requires `make db-up` first)
	VERITAS_DEV=1 VERITAS_LOG_DIR=logs $(PY_ENV) $(PYTHON) -c "from web.backend.veritas_web.app import serve; serve(host='$(HOST)', port=$(PORT), data_root='$(WEB_DATA_DIR)', output_root='$(OUTPUT_ROOT)')"

web-backend-reload: ## Start web backend in foreground with auto-reload on code changes
	@mkdir -p logs/app
	VERITAS_DEV=1 VERITAS_LOG_DIR=logs $(PY_ENV) $(PYTHON) -c "\
from web.backend.veritas_web.app import create_app; \
import uvicorn; \
app = create_app(data_root='$(WEB_DATA_DIR)', output_root='$(OUTPUT_ROOT)'); \
uvicorn.run(app, host='$(HOST)', port=$(PORT), reload=True, reload_dirs=['engine', 'web/backend'])"

celery-worker: ## Start Celery worker in foreground for async audit tasks
	@mkdir -p logs/worker
	VERITAS_DEV=1 VERITAS_LOG_DIR=logs $(PY_ENV) celery -A engine.tasks.celery_app worker --loglevel=debug

web-frontend: ## Start Vite frontend dev server (HMR + API proxy to backend:$(PORT))
	cd $(FRONTEND_DIR) && npm run dev

dev: ## Start full local dev environment in background (delegates to dev-up)
	@$(MAKE) --no-print-directory dev-up

dev-up: ## One-command start: DB (postgres + redis) + backend + frontend + celery + forensics
	@$(COMPOSE_DB) up -d postgres redis
	@for i in $$(seq 1 10); do \
		if $(COMPOSE_DB) exec -T postgres pg_isready -U veritas_dev -d veritas_dev >/dev/null 2>&1; then \
			echo "PostgreSQL ready."; break; \
		fi; \
		sleep 1; \
	done
	@bash scripts/dev-start.sh

dev-down: ## One-command stop: kill backend + frontend + forensics + DB
	@bash scripts/dev-stop.sh

forensics-up: ## Build and start visual forensics services (SILA dense :8770, ELIS provenance :8771)
	@$(COMPOSE_FORE) up -d --build

forensics-down: ## Stop visual forensics services
	@$(COMPOSE_FORE) down

forensics-logs: ## Tail forensics service logs
	@$(COMPOSE_FORE) logs -f

web-install: ## Install frontend dependencies
	cd $(FRONTEND_DIR) && npm install

web-build: ## Build frontend static assets for backend serving
	cd $(FRONTEND_DIR) && npm run build

web-preview: ## Preview the built frontend with Vite
	cd $(FRONTEND_DIR) && npm run preview

health: ## Check local web backend health
	@curl -sf http://$(HOST):$(PORT)/api/health | $(PYTHON) -m json.tool || echo "Local web backend unavailable"

# -- Tests and lint ------------------------------------------------------

test: ## Run all Python tests
	$(PY_ENV) $(PYTEST) -q

test-fast: ## Fast tests: unit tests only, no models, no heavy visual, target <30s
	$(PY_ENV) $(PYTEST) tests/unit/ -x --tb=short -q -k "not test_copy_move and not test_overlap_reuse and not test_visual_finding and not test_visual_fixtures and not test_tru_for and not test_sila and not test_paperconan and not test_web_app"

test-unit: ## Run unit tests
	$(PY_ENV) $(PYTEST) -q tests/unit

test-integration: ## Integration tests: e2e + web + CLI smoke
	$(PY_ENV) $(PYTEST) tests/e2e/ tests/integration/ -x --tb=short -q

test-e2e: ## Run end-to-end tests
	$(PY_ENV) $(PYTEST) -q tests/e2e

test-visual: ## Visual tests: OpenCV/fixture-heavy
	$(PY_ENV) $(PYTEST) tests/unit/test_copy_move_detection.py tests/unit/test_overlap_reuse.py tests/unit/test_visual_finding_pipeline.py tests/unit/test_visual_fixtures.py tests/unit/test_visual_report.py tests/unit/test_visual_orchestrator.py -x --tb=short -q

test-model: ## Model tests: TruFor/SSCD/SILA/Docker/GPU (not in CI fast gate)
	$(PY_ENV) $(PYTEST) tests/ -x --tb=short -q -k "tru_for or sila or sscd or embedding"

lint: lint-python lint-web ## Run Python and frontend lint checks

lint-python: ## Run ruff checks
	$(PY_ENV) $(RUFF) check cli engine runtime protocols web/backend tests scripts

lint-web: ## Run frontend eslint
	cd $(FRONTEND_DIR) && npm run lint

deslop: ## Full entropy control: Ruff fix/format + Vulture + import-linter + Biome + Knip
	@echo "╔══════════════════════════════════════════════════════╗"
	@echo "║  Veritas Deslop — Deterministic Entropy Control     ║"
	@echo "╚══════════════════════════════════════════════════════╝"
	@echo ""
	@echo "━━━ Layer 2: Python surface entropy ━━━"
	@echo ""
	@echo "▸ Ruff: auto-fix unused imports + lint"
	-$(PY_ENV) $(RUFF) check --fix cli engine runtime protocols web/backend tests scripts
	@echo ""
	@echo "▸ Ruff: format"
	-$(PY_ENV) $(RUFF) format cli engine runtime protocols web/backend tests scripts
	@echo ""
	@echo "▸ Vulture: dead code scan (80%+ confidence)"
	-uv run vulture cli/ engine/ runtime/ protocols/ web/backend/ scripts/ \
		--exclude engine/static_audit/upstream/ \
		--min-confidence 80 --sort-by-size
	@echo ""
	@echo "━━━ Layer 2: JS/TS surface entropy ━━━"
	@echo ""
	@echo "▸ Biome: format + lint (if available)"
	-@if [ -f $(FRONTEND_DIR)/node_modules/.bin/biome ]; then \
		cd $(FRONTEND_DIR) && npx biome check --write . ; \
	else \
		echo "  [skip] biome not installed — run 'cd $(FRONTEND_DIR) && npm install' first" ; \
	fi
	@echo ""
	@echo "▸ Knip: unused exports/deps (if available)"
	-@if [ -f $(FRONTEND_DIR)/node_modules/.bin/knip ]; then \
		cd $(FRONTEND_DIR) && npx knip ; \
	else \
		echo "  [skip] knip not installed — run 'cd $(FRONTEND_DIR) && npm install --save-dev knip' first" ; \
	fi
	@echo ""
	@echo "━━━ Layer 3: Structural entropy (dependency direction) ━━━"
	@echo ""
	@echo "▸ import-linter: Python layered architecture"
	-uv run lint-imports
	@echo ""
	@echo "▸ dependency-cruiser: JS/TS dependency direction (if available)"
	-@if [ -f $(FRONTEND_DIR)/node_modules/.bin/depcruise ]; then \
		cd $(FRONTEND_DIR) && npx depcruise --validate .dependency-cruiser.cjs src/ ; \
	else \
		echo "  [skip] dependency-cruiser not installed — run 'cd $(FRONTEND_DIR) && npm install --save-dev dependency-cruiser' first" ; \
	fi
	@echo ""
	@echo "━━━ Verification ━━━"
	@echo ""
	@echo "▸ Pyright: type check (errors only)"
	-uv run pyright cli/ engine/ runtime/ protocols/ web/backend/ 2>&1 | grep -E '(error|Error)' | head -20 || true
	@echo ""
	@echo "╔══════════════════════════════════════════════════════╗"
	@echo "║  Deslop complete. Review [needs-human] items above. ║"
	@echo "╚══════════════════════════════════════════════════════╝"

check-prompts: ## Verify prompt files match locked hashes
	$(PYTHON) scripts/lock_prompts.py --check

lock-prompts: ## Regenerate prompts.lock from current prompt files
	$(PYTHON) scripts/lock_prompts.py

web-test: ## Run frontend tests
	cd $(FRONTEND_DIR) && npm run test

# -- Model weights -------------------------------------------------------

download-models: ## Download model weights (YOLOv5 panel extraction + TruFor)
	./scripts/download_panel_extraction_models.sh
	@echo ""
	@echo "Checking TruFor weights..."
	@if [ ! -f models/trufor/weights/trufor.pth.tar ]; then \
		echo "TruFor weights not found at models/trufor/weights/trufor.pth.tar"; \
		echo "Download from https://github.com/danielgatis/trufor/releases and place in models/trufor/weights/trufor.pth.tar"; \
		mkdir -p models/trufor/weights; \
		echo "You can also run: gdown <TRUFOR_GDRIVE_ID> -O models/trufor/weights/trufor.pth.tar"; \
	else \
		echo "TruFor weights found."; \
	fi

# -- Cleanup -------------------------------------------------------------

clean-demo: ## Remove the lightweight demo output directory
	rm -rf "$(OUTPUT_DIR)"

clean-cache: ## Remove Python and pytest cache artifacts
	rm -rf runtime/__pycache__ runtime/executors/__pycache__ tests/e2e/__pycache__ tests/unit/__pycache__ cli/commands/__pycache__ cli/__pycache__ engine/static_audit/__pycache__ engine/static_audit/tools/__pycache__ engine/__pycache__ engine/workflows/__pycache__ engine/claims/__pycache__ engine/reporting/__pycache__ engine/investigation/__pycache__ engine/ingest/__pycache__ engine/tools/__pycache__ .pytest_cache

clean-web: ## Remove frontend build output
	rm -rf "$(FRONTEND_DIR)/dist"

wipe-local: ## Remove outputs and web_data; requires CONFIRM=1
	@if [ "$(CONFIRM)" != "1" ]; then \
		echo "This removes $(OUTPUT_ROOT) and $(WEB_DATA_DIR). Re-run with CONFIRM=1."; \
		exit 2; \
	fi
	rm -rf "$(OUTPUT_ROOT)" "$(WEB_DATA_DIR)"
