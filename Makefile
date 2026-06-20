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

COMPOSE ?= docker compose -f docker-compose.yml

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

.PHONY: help show-config sync install setup \
	up down rebuild restart logs ps shell health docker-health \
	db-up db-down db-init db-migrate db-reset \
	precheck run report demo audit audit-off audit-fresh report-path \
	web-backend web-frontend web-install web-build web-preview \
	test test-fast test-unit test-integration test-e2e test-visual test-model \
	lint lint-python lint-web web-test \
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

# -- Setup ---------------------------------------------------------------

sync: ## Sync Python dependencies with uv (includes all optional extras)
	$(UV_ENV) $(UV) sync --dev --all-extras

install: sync ## Install/sync the Python environment with uv

setup: sync web-install ## Sync Python and frontend dependencies

# -- Docker lifecycle ----------------------------------------------------

DOCKER_BUILD_ARGS := --build-arg USER_UID=$$(id -u) --build-arg USER_GID=$$(id -g) --build-arg USERNAME=veritas

docker-build: ## Build Docker image with host user UID/GID (for bind mount compatibility)
	docker build $(DOCKER_BUILD_ARGS) -t veritas:latest .

docker-build-dev: ## Build development Docker image (runs as root)
	docker build -f Dockerfile.dev -t veritas:dev .

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

docker-health: ## Check Docker web service health through port 80
	@curl -sf http://127.0.0.1/api/health | $(PYTHON) -m json.tool || echo "Docker web service unavailable"

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

# -- Tool Availability Check ----------------------------------------------

check-tools: ## Check all tool availability (Docker images, model weights, dependencies, GPU)
	@./scripts/dev.sh check-tools

# -- Database lifecycle --------------------------------------------------

db-up: ## Start PostgreSQL with pgvector via Docker Compose
	$(COMPOSE) up -d postgres
	@echo "Waiting for PostgreSQL..."
	@for i in $$(seq 1 15); do \
		if docker compose exec -T postgres pg_isready -U veritas >/dev/null 2>&1; then \
			echo "PostgreSQL ready."; break; \
		fi; \
		sleep 1; \
	done

db-down: ## Stop PostgreSQL container
	$(COMPOSE) stop postgres

db-init: db-up ## Initialise database tables (development only)
	$(PY_ENV) $(PYTHON) -c "from web.backend.veritas_web.database import init_db; init_db()"

db-migrate: ## Migrate web_data/ JSON files to PostgreSQL
	$(PY_ENV) $(PYTHON) scripts/migrate_web_data_to_postgres.py

db-reset: ## Reset database: drop all tables and recreate (DEVELOPMENT ONLY)
	@echo "⚠️  WARNING: This will DELETE all data in the database!"
	@read -p "Continue? [y/N] " confirm && [ $$confirm = "y" ] || exit 1
	$(PY_ENV) $(PYTHON) -c "from web.backend.veritas_web.database import create_db_engine, Base; \
		engine = create_db_engine(); \
		Base.metadata.drop_all(bind=engine); \
		Base.metadata.create_all(bind=engine); \
		print('✓ Database reset: all tables dropped and recreated')"

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

web-backend: ## Start local stdlib Python web backend
	$(PY_ENV) $(PYTHON) -c "from web.backend.veritas_web.app import serve; serve(host='$(HOST)', port=$(PORT), data_root='$(WEB_DATA_DIR)', output_root='$(OUTPUT_ROOT)')"

web-frontend: ## Start Vite frontend dev server
	cd $(FRONTEND_DIR) && npm run dev

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
