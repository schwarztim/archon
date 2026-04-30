# Archon — Production Configuration

**Authority:** [`backend/app/config.py`](../backend/app/config.py), [`backend/app/startup_checks.py`](../backend/app/startup_checks.py), [`env.example`](../env.example).
**Governing ADR:** [ADR-005](adr/orchestration/ADR-005-production-durability-policy.md).

> All Archon backend env vars use the `ARCHON_` prefix and are read by pydantic-settings (`backend/app/config.py`). Non-prefixed names like `DATABASE_URL` and `JWT_SECRET` are accepted as fallback for ops compatibility but `ARCHON_*` always wins.

## 1. Environment classification

The single most important variable. Drives every fail-closed gate.

| `ARCHON_ENV` | Effect |
|--------------|--------|
| `production` | All startup checks active. SQLite rejected. `MemorySaver` rejected. Dev JWT secrets rejected. `AUTH_DEV_MODE=true` rejected. Stub-status node executors return `step.failed`. |
| `staging` | Same as production. |
| `dev` | Most checks no-op. Stub executors run. SQLite allowed. |
| `test` | Same as `dev`. Test fixtures may set `LLM_STUB_MODE=true`. |
| (unset) | Treated as `dev`. |

## 2. Canonical env vars

### 2.1 Database

| Variable | Default | Type | Required in production | Notes |
|----------|---------|------|------------------------|-------|
| `ARCHON_DATABASE_URL` | (none) | URL | **yes** | Must be Postgres in production / staging. SQLite rejected by `_check_database_url`. |
| `POSTGRES_USER` | `archon` | str | yes (compose) | Used by docker-compose's Postgres service. |
| `POSTGRES_PASSWORD` | `archon` | str | yes (compose) | Same. |
| `POSTGRES_DB` | `archon` | str | yes (compose) | Same. |
| `ARCHON_AUTO_MIGRATE` | `false` | bool | optional | If `true`, backend runs `alembic upgrade head` on startup. Off by default; ops should run migrations explicitly. |

### 2.2 Auth & JWT

| Variable | Default | Type | Required in production | Notes |
|----------|---------|------|------------------------|-------|
| `ARCHON_JWT_SECRET` | `change-me-in-production` | str | **yes** | Must be a strong random value. Dev defaults (`changeme`, `change-me`, `dev-secret`, `test-secret`, `secret`, `default`, `insecure`, prefixes `dev-`/`test-`/`change`) are rejected. |
| `ARCHON_AUTH_DEV_MODE` | `false` | bool | **must be false** | If `true` in production / staging, `_check_auth_dev_mode` rejects startup. Allows static `dev-token` to pass JWT validation when dev. |
| `ARCHON_KEYCLOAK_URL` | (none) | URL | optional | OIDC issuer URL. Required for Keycloak-backed auth. |
| `ARCHON_KEYCLOAK_CLIENT_ID` | (none) | str | optional | Same. |
| `ARCHON_AZURE_TENANT_ID` | (none) | str | optional | Required for Azure Entra ID auth. |
| `ARCHON_AZURE_CLIENT_ID` | (none) | str | optional | Same. |

### 2.3 LangGraph durability

| Variable | Default | Type | Required in production | Notes |
|----------|---------|------|------------------------|-------|
| `LANGGRAPH_CHECKPOINTING` | `postgres` | enum | **must be `postgres`** | Allowed: `postgres`, `memory`, `disabled` (and legacy aliases `false`/`0`/`off`/`none` for `disabled`). In production / staging, only `postgres` is permitted. `memory` and `disabled` are rejected by `_check_langgraph_checkpointing`. |
| `ARCHON_DATABASE_URL` | (see above) | URL | yes | Backs the LangGraph Postgres saver. |

When the checkpointer factory cannot construct an `AsyncPostgresSaver` in production, it raises `CheckpointerDurabilityFailed` and `_check_checkpointer_is_postgres` aborts startup. There is no silent `MemorySaver` fallback.

### 2.4 Tenant isolation

| Variable | Default | Type | Required in production | Notes |
|----------|---------|------|------------------------|-------|
| `ARCHON_ENTERPRISE_STRICT_TENANT` | (unset → strict in production) | bool | **must not be `false`** | Explicit `false` / `0` / `no` / `off` is rejected. Enables the tenant-context middleware that rejects requests without a resolved `tenant_id`. |

### 2.5 Vault

| Variable | Default | Type | Required in production | Notes |
|----------|---------|------|------------------------|-------|
| `VAULT_ADDR` | `http://vault:8200` | URL | yes | Vault HTTP address. |
| `VAULT_TOKEN` | `dev-root-token` | str | yes | Bootstrap token. In production should be obtained via AppRole; dev token is rejected by Vault hardening (operator concern, not gated by Archon startup). |
| `ARCHON_VAULT_NAMESPACE` | (none) | str | optional | Vault Enterprise namespace for tenant isolation. |

### 2.6 Redis

| Variable | Default | Type | Required in production | Notes |
|----------|---------|------|------------------------|-------|
| `ARCHON_REDIS_URL` | `redis://redis:6379/0` | URL | yes | Used by rate limiter (sorted set), WebSocket replay manager, idempotency cache. |

### 2.7 Worker

| Variable | Default | Type | Notes |
|----------|---------|------|-------|
| `ARCHON_WORKER_CONCURRENCY` | `4` | int | Maximum concurrent steps per worker process. |
| `ARCHON_WORKER_SCAN_INTERVAL` | `300` | int (seconds) | Cadence of the slow loop (cron, budget, audit). |

### 2.8 LLM stub mode

| Variable | Default | Type | Notes |
|----------|---------|------|-------|
| `LLM_STUB_MODE` | `false` | bool | When `true`, `app.langgraph.llm.call_llm` returns deterministic 30-token stub responses instead of calling LiteLLM. Used by tests and local development without API keys. **Must be `false` in production** (no startup gate; behaviour gate — stub mode would yield meaningless completions). |
| `OPENAI_API_KEY` | (none) | str | Provider key. Resolved via `secrets_manager.get_secret("openai")` first; env fallback only in dev. |
| `ANTHROPIC_API_KEY` | (none) | str | Same. |
| `AZURE_OPENAI_API_KEY` | (none) | str | Same. |

### 2.9 Feature flags

| Variable | Default | Type | Notes |
|----------|---------|------|-------|
| `ARCHON_FEATURE_DLP_ENABLED` | `true` | bool | Toggles DLP scan on `dlpScanNode` and middleware. |
| `ARCHON_FEATURE_COST_TRACKING` | `true` | bool | Toggles cost-service writes per step. |
| `ARCHON_FEATURE_MCP_SECURITY` | `true` | bool | Toggles MCP security routes. |
| `ARCHON_FEATURE_A2A_ENABLED` | `true` | bool | Toggles Agent-to-Agent endpoints. |

### 2.10 Logging / debug

| Variable | Default | Type | Notes |
|----------|---------|------|-------|
| `ARCHON_DEBUG` | `false` | bool | If `true`, structured logs include extra debug fields. **Must be `false` in production** (operator concern). |
| `ARCHON_LOG_LEVEL` | `INFO` | enum | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

### 2.11 Notifications

| Variable | Default | Type | Notes |
|----------|---------|------|-------|
| `ARCHON_SMTP_HOST` | (none) | str | SMTP relay host. |
| `ARCHON_SMTP_PORT` | `587` | int | SMTP port. |
| `ARCHON_SMTP_FROM` | (none) | str | Default sender. |
| `ARCHON_SMTP_USERNAME` | (none) | str | SMTP user. |
| `ARCHON_SMTP_PASSWORD` | (none) | str | SMTP password / API key (resolve via Vault when possible). |
| `ARCHON_TEAMS_WEBHOOK_URL` | (none) | URL | Microsoft Teams incoming webhook. |

## 3. Startup gates (`run_startup_checks`)

Run by the FastAPI lifespan and the worker's `main()` **before** the listener binds. Each check runs in any environment but only **fails** in `production` / `staging`. Failure aggregates into a `StartupCheckFailed` exception which the caller converts to `SystemExit(1)`.

| Check | Function | Failure condition |
|-------|----------|-------------------|
| Database URL is set | `_check_database_url` | `ARCHON_DATABASE_URL` empty (any env) |
| Database URL is not SQLite | `_check_database_url` | URL starts with `sqlite` (production / staging) |
| JWT secret is non-trivial | `_check_jwt_secret` | Empty or matches a known dev default (production / staging) |
| Auth dev mode is off | `_check_auth_dev_mode` | `ARCHON_AUTH_DEV_MODE=true` (production / staging) |
| LangGraph checkpointing is enabled | `_check_langgraph_checkpointing` | `LANGGRAPH_CHECKPOINTING in {memory, disabled}` (production / staging) |
| Tenant strict mode is on | `_check_tenant_context_active` | `ARCHON_ENTERPRISE_STRICT_TENANT in {false, 0, no, off}` (production / staging) |
| Checkpointer is Postgres | `_check_checkpointer_is_postgres` | `get_checkpointer()` raises, returns `None`, or returns a non-Postgres saver (production / staging) |

When any check fails, the process logs `startup_checks_failed` at CRITICAL and exits non-zero. The HTTP listener never binds. There is no silent fallback.

## 4. Recommended `values-production.yaml`

```yaml
backend:
  env:
    ARCHON_ENV: production
    ARCHON_DATABASE_URL: postgresql+asyncpg://archon:${POSTGRES_PASSWORD}@archon-postgres:5432/archon
    ARCHON_REDIS_URL: redis://archon-redis:6379/0
    ARCHON_JWT_SECRET: ${JWT_SECRET}        # 32+ bytes, from a Vault KV secret
    ARCHON_AUTH_DEV_MODE: "false"
    ARCHON_DEBUG: "false"
    ARCHON_LOG_LEVEL: INFO
    LANGGRAPH_CHECKPOINTING: postgres
    ARCHON_ENTERPRISE_STRICT_TENANT: "true"
    ARCHON_WORKER_CONCURRENCY: "8"
    ARCHON_KEYCLOAK_URL: https://auth.example.com/realms/archon
    ARCHON_KEYCLOAK_CLIENT_ID: archon-app
    ARCHON_FEATURE_DLP_ENABLED: "true"
    ARCHON_FEATURE_COST_TRACKING: "true"
    LLM_STUB_MODE: "false"

worker:
  replicas: 2
  env:
    ARCHON_ENV: production
    # Same vars as backend (DB, Redis, JWT_SECRET, etc.)
```

A complete production `values-production.yaml` lives at `infra/helm/archon-platform/values-production.yaml` (operator overlay; ship-time secrets via External Secrets Operator).

## 5. Verifying production readiness

Before promoting an image to production, run:

```bash
# 1. The five-gate verify pipeline
make verify

# 2. The vertical-slice heartbeat against a Postgres-backed test instance
make test-slice

# 3. A startup-gate dry run (point ARCHON_ENV=production at a TEST cluster)
ARCHON_ENV=production \
  ARCHON_DATABASE_URL="postgresql+asyncpg://..." \
  ARCHON_JWT_SECRET="$(openssl rand -hex 32)" \
  ARCHON_AUTH_DEV_MODE=false \
  LANGGRAPH_CHECKPOINTING=postgres \
  ARCHON_ENTERPRISE_STRICT_TENANT=true \
  python -m app.main &  # Should bind. Any startup_checks_failed in logs = fix before deploy.
```

Negative test:

```bash
ARCHON_ENV=production \
  ARCHON_DATABASE_URL="sqlite:///tmp/x" \
  python -m app.main
# Expected: CRITICAL startup_checks_failed; exit code 1; HTTP listener never binds.
```

## 6. Cross-references

- [`backend/app/startup_checks.py`](../backend/app/startup_checks.py) — implementation.
- [`backend/app/config.py`](../backend/app/config.py) — pydantic-settings schema.
- [`env.example`](../env.example) — dev defaults (do not deploy as-is).
- [`docs/adr/orchestration/ADR-005-production-durability-policy.md`](adr/orchestration/ADR-005-production-durability-policy.md) — durability policy.
- [`docs/DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) — Helm + Terraform deploy.
- [`docs/STATE_MACHINE.md`](STATE_MACHINE.md) — the run lifecycle that depends on these gates.
