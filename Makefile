.PHONY: up down logs db migrate migrate-up migrate-down db-reset test clean dev install vault-up keycloak-up secrets-init dev-enterprise enterprise-status worker worker-bg verify verify-unit verify-integration verify-frontend verify-contracts verify-slice verify-fast known-failures test-slice test-worker-canary slice-up slice-down lint typecheck test-fast chaos load load-ci helm-lint helm-render helm-smoke security-scan backup-test sso-test test-metrics-real

up: ## Start all services in background
	docker compose up -d

down: ## Stop all services
	docker compose down

logs: ## Follow logs for all services
	docker compose logs -f

db: ## Open psql shell in postgres container
	docker compose exec postgres psql -U archon

migrate: ## Run Alembic migrations in backend container
	docker compose exec backend alembic upgrade head

test: ## Run pytest in backend container
	docker compose exec backend python -m pytest

clean: ## Stop services and remove volumes
	docker compose down -v --remove-orphans

dev: ## Start only postgres + redis (for local backend dev)
	docker compose up -d postgres redis

install: ## Install backend Python dependencies locally
	pip install -r backend/requirements.txt

vault-up: ## Start Vault container in dev mode
	docker compose up -d vault

keycloak-up: ## Start Keycloak container in dev mode
	docker compose up -d keycloak

secrets-init: ## Bootstrap Vault with initial secrets and policies
	docker compose run --rm vault-init

dev-enterprise: ## Start all services including Vault and Keycloak
	docker compose up -d postgres redis vault keycloak
	docker compose run --rm vault-init
	docker compose up -d backend frontend

enterprise-status: ## Check health of Vault and Keycloak
	@echo "=== Vault ===" && docker compose exec vault vault status 2>/dev/null || echo "Vault: not running"
	@echo "=== Keycloak ===" && docker compose exec keycloak curl -sf http://localhost:8080/auth/health 2>/dev/null || echo "Keycloak: not running"

migrate-up: ## Run Alembic migrations to latest head (safe — never drops data)
	docker compose exec backend alembic upgrade head

migrate-down: ## Roll back the last Alembic migration
	docker compose exec backend alembic downgrade -1

db-reset: ## DESTRUCTIVE: drop and recreate the database. Refuses in production.
	@if [ "$${ARCHON_ENV}" = "production" ]; then \
		echo ""; \
		echo "╔══════════════════════════════════════════════════════╗"; \
		echo "║  ERROR: db-reset is DISABLED in production.          ║"; \
		echo "║  Unset ARCHON_ENV=production to use this target.     ║"; \
		echo "╚══════════════════════════════════════════════════════╝"; \
		echo ""; \
		exit 1; \
	fi
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║  ⚠  WARNING: db-reset will DESTROY ALL DATA  ⚠          ║"
	@echo "║                                                          ║"
	@echo "║  This drops every table and recreates the schema.       ║"
	@echo "║  All workflows, agents, executions, and audit logs      ║"
	@echo "║  will be permanently deleted.                           ║"
	@echo "║                                                          ║"
	@echo "║  Press Ctrl+C NOW to abort.                             ║"
	@echo "╚══════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "Waiting 5 seconds before proceeding..."
	@sleep 5
	docker compose exec backend python3 -c "\
		import asyncio; \
		from app.database import drop_and_recreate_db; \
		asyncio.run(drop_and_recreate_db()); \
		print('Schema reset complete. All data has been wiped.')"
	@echo "Running alembic stamp to mark schema as current..."
	docker compose exec backend alembic stamp head
	@echo ""
	@echo "db-reset complete. Run 'make dev-enterprise' to reseed defaults."

worker: ## Run the background worker (foreground, Ctrl-C to stop)
	cd backend && PYTHONPATH=. python3 -m app.worker

worker-bg: ## Run the background worker in the background (logs to /tmp/archon-worker.log)
	cd backend && PYTHONPATH=. nohup python3 -m app.worker > /tmp/archon-worker.log 2>&1 &
	@echo "Worker started, PID=$$!"

verify: ## Run all 5 verification gates in order (unit, integration, frontend, contracts, slice)
	bash scripts/verify.sh

verify-unit: ## Gate 1: backend + gateway unit tests (no live infra required)
	bash scripts/verify-unit.sh

verify-integration: ## Gate 2: tests/integration/ suite (excluding slice; needs postgres + redis)
	bash scripts/verify-integration.sh

verify-frontend: ## Gate 3: frontend typecheck + Vitest unit tests
	bash scripts/verify-frontend.sh

verify-contracts: ## Gate 4: feature matrix + OpenAPI diff + API type parity (skips missing pieces with warnings)
	bash scripts/verify-contracts.sh

verify-slice: ## Gate 5: vertical-slice REST heartbeat (set ARCHON_TRANSITION=1 for one-cycle degraded mode)
	bash scripts/verify-slice.sh

verify-fast: verify-unit verify-frontend ## Quick local iteration: unit + frontend only

known-failures: ## Print the curated list of explicitly excluded tests with reasons
	@cat scripts/known-failures.txt

# NOTE: verify-contracts depends on scripts/check-feature-matrix.py which is being created
# by another agent in this wave. Until that lands, the gate skips that check with a warning.

test-slice: ## Run the vertical-slice end-to-end integration test (LLM_STUB_MODE=true)
	bash scripts/test-slice.sh

test-worker-canary: ## Run the non-inline worker dispatch canary (ARCHON_DISPATCH_INLINE=0)
	bash scripts/test-worker-canary.sh

slice-up: ## Start only postgres + redis (for slice testing with live infra)
	docker compose up -d postgres redis
	@echo "Wait 5s for services..." && sleep 5

slice-down: ## Stop all slice infra
	docker compose down

lint: ## Lint Python source (ruff)
	ruff check backend/ gateway/

typecheck: ## Typecheck Python source (pyright if installed)
	@command -v pyright &> /dev/null && pyright backend gateway || echo "pyright not installed; skipping"

test-fast: ## Run backend tests quickly (LLM_STUB_MODE=true, stop on first failure)
	LLM_STUB_MODE=true PYTHONPATH=backend python3 -m pytest backend/tests/ -x -q --ignore=backend/tests/test_azure_wiring

chaos: ## Run Phase 6 chaos test suite (worker crash, transient db, 429 storm, redis down)
	bash scripts/run-chaos-tests.sh

load: ## Run Phase 6 load test suite (5 profiles: simple, fanout, llm, approval, retry — local N=50)
	bash scripts/run-load-tests.sh

load-ci: ## Run Phase 6 load test suite in CI mode (N=10, ~2 min budget)
	bash scripts/run-load-tests.sh --ci

helm-lint: ## Lint the Archon Helm chart with default + production values
	bash scripts/lint-helm.sh

helm-render: ## Render Helm chart to infra/k8s/manifests/{dev,production}.yaml
	bash scripts/render-helm.sh

helm-smoke: ## Render Helm chart + dry-run validate (requires helm CLI; mirrors helm-smoke.yml)
	bash scripts/helm-smoke.sh

security-scan: ## Run dependency security scan with severity threshold (high) — see docs/runbooks/ci-gates.md
	bash scripts/security-scan.sh --threshold high

backup-test: ## Round-trip the Postgres + Vault backup scripts (skips without docker/pg/vault)
	bash scripts/backup-restore-test.sh

sso-test: ## Run Keycloak SSO integration tests (skips without KEYCLOAK_TEST_URL)
	PYTHONPATH=backend python3 -m pytest backend/tests/test_sso_keycloak.py -v

test-metrics-real: ## P3 live observability proof — drive a real run, scrape /metrics, assert canonical metrics emitted
	bash scripts/test-metrics-real.sh
