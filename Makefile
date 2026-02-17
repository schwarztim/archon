.PHONY: up down logs db migrate test clean dev install vault-up keycloak-up secrets-init dev-enterprise enterprise-status

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
