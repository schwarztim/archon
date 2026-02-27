# WS-7 Integration Testing Infrastructure Report

**Workstream:** WS-7 — Integration Testing Infrastructure  
**Status:** ✅ Complete  
**Date:** 2026-02-26

---

## Overview

This workstream created and validated the full integration testing infrastructure for the Archon
Enterprise AI Orchestration & Governance Platform. Tests cover the live Docker-based stack
(PostgreSQL + Redis + backend + frontend) using pytest/httpx for API tests and Playwright for
browser E2E tests.

---

## 1. Docker Test Stack — `docker-compose.test.yml`

Location: `/docker-compose.test.yml`

The test compose file brings up a minimal, isolated stack:

| Service    | Image              | Port   | Health Check           |
|------------|--------------------|--------|------------------------|
| `postgres`  | `postgres:16`      | 5432   | `pg_isready -U archon` |
| `redis`     | `redis:7-alpine`   | 6379   | `redis-cli ping`       |
| `backend`   | build `./backend`  | 8000   | `curl /health`         |
| `frontend`  | build `./frontend` | 3000   | depends_on backend     |

Key environment variables for the backend:
- `ARCHON_DATABASE_URL=postgresql+asyncpg://archon:archon@postgres:5432/archon_test`
- `ARCHON_AUTH_DEV_MODE=true` — disables real authentication for test isolation
- `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_ENDPOINT` — passed from host env

---

## 2. Test Runner — `scripts/run_integration_tests.sh`

Location: `scripts/run_integration_tests.sh` (executable, `-rwxr-xr-x`)

```bash
bash scripts/run_integration_tests.sh
```

The runner:
1. Checks Docker is running
2. Spins up the test stack with `docker compose -f docker-compose.test.yml up -d --build --wait`
3. Waits (up to 120s) for backend health at `http://localhost:8000/health`
4. Waits (up to 120s) for frontend at `http://localhost:3000`
5. Runs `pytest tests/integration/ -v --tb=short`
6. Runs `npx playwright test` in `frontend/`
7. Tears down the stack with `docker compose ... down -v`
8. Exits with the backend pytest exit code

Test results are written to `test-results/` (backend JUnit XML) and
`frontend/playwright-report/` (HTML report).

---

## 3. Backend Integration Tests — `tests/integration/`

10 test files covering all major API surface areas:

| File                      | Endpoint(s) Tested                              |
|---------------------------|-------------------------------------------------|
| `conftest.py`             | Shared fixtures: `client` (httpx), `api_prefix` |
| `test_health.py`          | `GET /health` — 200, DB/Redis status in body    |
| `test_audit_logs.py`      | `GET /api/v1/audit-logs/` — 200, pagination     |
| `test_workflows.py`       | `GET/POST /api/v1/workflows` — list & create    |
| `test_rbac.py`            | `GET/POST /api/v1/sso/config/roles` — CRUD      |
| `test_api_keys.py`        | `GET/POST /api/v1/settings/api-keys` — list & create |
| `test_marketplace.py`     | `GET /api/v1/marketplace/categories` — 200      |
| `test_rate_limit.py`      | Rapid requests to `/health` — verify no 429     |
| `test_settings.py`        | `GET /api/v1/settings` — settings object        |
| `test_azure_openai.py`    | Router chat + direct Azure OpenAI call (async)  |

Additional test files (bonus coverage):
- `test_dlp.py` — DLP policy endpoints
- `test_sentinel.py` — Sentinel scan endpoints
- `test_secrets.py` — Secrets vault endpoints
- `test_embeddings.py` — Embeddings endpoint
- `test_model_router.py` — Model router
- `test_templates.py` — Template CRUD
- `test_e2e_flows.py` — End-to-end user journeys
- `test_azure_openai_smoke.py` — Direct Azure OpenAI smoke tests

All tests use `httpx.Client` against `http://localhost:8000` with `AUTH_DEV_MODE` enabled
(no real auth headers required). Async tests use `@pytest.mark.asyncio`.

---

## 4. Frontend E2E Tests — `frontend/tests/e2e/`

Playwright configuration: `frontend/playwright.config.ts`
- `baseURL`: `http://localhost:3000`
- `testDir`: `./tests/e2e`
- `headless`: `true`
- `projects`: chromium only

6 required E2E test specs:

| File                  | What It Tests                                        |
|-----------------------|------------------------------------------------------|
| `dashboard.spec.ts`   | Navigate to `/`, body renders, nav visible           |
| `theme.spec.ts`       | Theme toggle present, click changes html class       |
| `audit.spec.ts`       | Navigate to `/audit`, table/list renders             |
| `health.spec.ts`      | API health proxy responds 200, SPA routes don't 404  |
| `workflows.spec.ts`   | Navigate to `/workflows`, content renders            |
| `marketplace.spec.ts` | Navigate to `/marketplace`, categories render        |

Additional E2E specs (bonus coverage):
- `rbac.spec.ts` — RBAC management page
- `settings.spec.ts` — Settings page
- `secrets.spec.ts` — Secrets vault page
- `sentinel.spec.ts` — Sentinel scan page
- `model_router.spec.ts` — Model router page
- `templates.spec.ts` — Templates page

---

## 5. How to Run

### Full integration test suite (requires Docker):
```bash
bash scripts/run_integration_tests.sh
```

### Backend integration tests only (requires running stack):
```bash
docker compose -f docker-compose.test.yml up -d --build --wait
PYTHONPATH=backend python3 -m pytest tests/integration/ -v --tb=short
docker compose -f docker-compose.test.yml down -v
```

### Frontend E2E tests only (requires running frontend):
```bash
cd frontend
npx playwright install --with-deps chromium  # first time only
npx playwright test
```

### Install Playwright browsers:
```bash
cd frontend && npx playwright install --with-deps chromium
```

---

## 6. Baseline Status

Prior to this workstream:
- Backend unit tests: **665 passing**
- Frontend unit tests: **65 passing**
- TypeScript: **0 errors**
- Ruff lint: **0 violations**

The integration test suite is additive — it does not modify existing unit tests.
