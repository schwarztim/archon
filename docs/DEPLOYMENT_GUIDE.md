# Archon — Deployment Guide

**Status:** Pre-1.0. The deploy paths described here all run; the production path adds startup gates that fail closed on misconfiguration.
**Authority:** [`docker-compose.yml`](../docker-compose.yml), [`infra/helm/archon-platform/`](../infra/helm/archon-platform/), [`infra/terraform/aws/main.tf`](../infra/terraform/aws/main.tf), [`backend/app/startup_checks.py`](../backend/app/startup_checks.py).

## 1. Prerequisites

| Tool | Minimum version | Purpose |
|------|-----------------|---------|
| Docker | 24.x | Container runtime. |
| Docker Compose | 2.x | Local development. |
| Kubernetes | 1.29+ | Production deployment. |
| Helm | 3.14+ | Chart management. |
| kubectl | 1.29+ | Cluster interaction. |
| Terraform | 1.7+ | Cloud infrastructure (AWS module ships; Azure / GCP are scaffolds). |

## 2. Local development (Docker Compose)

### 2.1 Clone and configure

```bash
git clone <repo-url>
cd archon
cp env.example .env
# Edit .env: at minimum, leave defaults for dev. The .env defaults are
# safe for local dev (ARCHON_AUTH_DEV_MODE=true, dev JWT secret); they
# are NOT safe for staging / production.
```

### 2.2 Start the eight-service stack

```bash
make up
# Equivalent to: docker compose up -d
```

This brings up:

| Service | Port (host) | Role |
|---------|-------------|------|
| `postgres` | 5432 | Primary datastore. |
| `redis` | 6379 | Rate limiter, WebSocket replay, idempotency cache. |
| `backend` | 8000 | FastAPI control plane. Depends on `vault-init` completion. |
| `worker` | (none) | Background worker — drain, reclaim, timer-fire. |
| `frontend` | 3000 | React SPA. |
| `keycloak` | 8180 | OIDC provider (dev profile). |
| `vault` | 8200 | Secrets backend (dev mode). |
| `vault-init` | (one-shot) | Idempotent KV-v2 / Transit / PKI / AppRole bootstrap. |

The backend's `depends_on` on `vault-init: { condition: service_completed_successfully }` ensures Vault is initialized before the API binds.

### 2.3 Run migrations + verify

```bash
make migrate     # alembic upgrade head — safe, never drops data
make verify      # 5-gate pipeline (unit + integration + frontend + contracts + slice)
make test-slice  # vertical-slice REST canary
```

`make test-slice` issues `POST /api/v1/agents` → `POST /api/v1/executions` and asserts a durable `WorkflowRun` reaches a terminal status. It's the heartbeat — when this passes, the kernel works.

### 2.4 Default credentials (dev only)

| Surface | URL | Credentials |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | static `dev-token` (auth dev mode) |
| Backend API | http://localhost:8000/docs | static `dev-token` |
| Keycloak | http://localhost:8180 | `admin` / `admin` |
| Vault | http://localhost:8200 | root token: `dev-root-token` |

These credentials are dev-mode only. They will be rejected in production by the startup gates documented in [`docs/PRODUCTION_CONFIG.md`](PRODUCTION_CONFIG.md).

### 2.5 Tear down

```bash
make down            # stop services, keep volumes
make clean           # stop + remove volumes (DESTRUCTIVE)
```

## 3. Staging (Helm)

Staging mirrors production except secrets come from a real Vault instance and `ARCHON_ENV=staging` activates the same fail-closed startup gates.

### 3.1 Install

```bash
helm repo add archon <repo-url>      # if published
# or use the local chart:
cd infra/helm/archon-platform
helm dependency update

kubectl create namespace archon-staging

helm upgrade --install archon . \
  --namespace archon-staging \
  -f values.yaml \
  -f values-staging.yaml \           # operator overlay (machine-local)
  --set backend.env.ARCHON_ENV=staging \
  --set worker.env.ARCHON_ENV=staging
```

### 3.2 Required values

| Override | Source |
|----------|--------|
| `ARCHON_DATABASE_URL` | Postgres connection string (NOT SQLite — startup will reject) |
| `ARCHON_REDIS_URL` | Redis connection string |
| `ARCHON_JWT_SECRET` | 32+ byte random value (NOT a dev default) |
| `ARCHON_AUTH_DEV_MODE` | `false` |
| `LANGGRAPH_CHECKPOINTING` | `postgres` |
| `ARCHON_ENTERPRISE_STRICT_TENANT` | `true` (or unset; default is strict) |
| `ARCHON_KEYCLOAK_URL` | OIDC issuer URL |

These are the same gates documented in [`docs/PRODUCTION_CONFIG.md §3`](PRODUCTION_CONFIG.md#3-startup-gates-run_startup_checks). If the chart is misconfigured, the backend pod CrashLoopBackOff with `startup_checks_failed` in the logs.

### 3.3 Verify the deploy

```bash
kubectl -n archon-staging get pods                    # all Running
kubectl -n archon-staging logs deploy/archon-backend  # look for "startup_checks: passed (env=staging)"
kubectl -n archon-staging port-forward svc/archon-backend 8000:8000
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/health
```

Then run `make test-slice` against the staging API:

```bash
ARCHON_BASE_URL=http://localhost:8000 make test-slice
```

## 4. Production

Production = staging with two additions:

1. `ARCHON_ENV=production` (same gates, slightly stricter wording in error messages).
2. Multi-zone Postgres + ElastiCache + multi-AZ EKS via the AWS Terraform module.

### 4.1 Provision infrastructure (AWS)

```bash
cd infra/terraform/aws
terraform init
terraform workspace select prod   # or terraform workspace new prod
terraform plan -var-file=production.tfvars
terraform apply -var-file=production.tfvars
```

The AWS module ships with VPC + EKS + RDS PG16 multi-AZ + ElastiCache + S3 with KMS. Output values feed Helm.

### 4.2 Create namespace + secrets

```bash
kubectl create namespace archon

# Secrets are managed via External Secrets Operator pulling from Vault.
# Apply the ESO ClusterSecretStore + ExternalSecret manifests:
kubectl apply -f infra/k8s/external-secrets/
```

### 4.3 Bootstrap Vault (first deploy only)

```bash
helm upgrade --install vault infra/helm/vault \
  --namespace vault \
  --create-namespace \
  -f infra/helm/vault/values.yaml

# Initialize + unseal (operator-only, do NOT script the unseal keys):
kubectl exec -it -n vault vault-0 -- vault operator init
# Distribute unseal keys per your operator policy.
kubectl exec -it -n vault vault-0 -- vault operator unseal

# Bootstrap KV-v2 + Transit + PKI + AppRole (idempotent):
bash infra/helm/vault/vault-init.sh
```

### 4.4 Install the platform

```bash
cd infra/helm/archon-platform
helm dependency update

helm upgrade --install archon . \
  --namespace archon \
  -f values.yaml \
  -f values-production.yaml \    # operator overlay
  --set backend.env.ARCHON_ENV=production \
  --set worker.env.ARCHON_ENV=production
```

### 4.5 Production startup gates

On startup the backend and worker run [`run_startup_checks`](../backend/app/startup_checks.py) and abort if any of the following fail:

- `ARCHON_DATABASE_URL` is empty or `sqlite://...`
- `ARCHON_JWT_SECRET` is a known dev default (`changeme`, `dev-secret`, etc.)
- `ARCHON_AUTH_DEV_MODE=true`
- `LANGGRAPH_CHECKPOINTING in {memory, disabled}`
- `ARCHON_ENTERPRISE_STRICT_TENANT in {false, 0, no, off}`
- The LangGraph Postgres saver fails to construct (any reason)

A failed gate logs `startup_checks_failed` at CRITICAL and exits non-zero. The HTTP listener never binds. There is no silent fallback.

See [`docs/PRODUCTION_CONFIG.md`](PRODUCTION_CONFIG.md) for the full env-var contract.

## 5. Migrations

### 5.1 Apply

```bash
# In any environment:
kubectl exec deploy/archon-backend -- alembic upgrade head
```

Or locally:

```bash
make migrate-up
```

Migrations are idempotent (`0007_canonical_run_substrate.py` and later use inspector helpers `_table_exists`, `_column_exists`, `_index_exists` that no-op on existing schema elements). They apply cleanly to a fresh database AND to one already partway through the chain.

### 5.2 Roll back

```bash
make migrate-down       # rolls back one revision
# or:
kubectl exec deploy/archon-backend -- alembic downgrade -1
```

The full chain (0001 → 0010) round-trips on SQLite (test) and Postgres (production). Verify with:

```bash
alembic upgrade head
alembic downgrade base
alembic upgrade head      # should succeed again
```

### 5.3 Generate a new migration

```bash
# Inside the backend container (so app.config + models import cleanly):
docker compose exec backend alembic revision --autogenerate -m "<description>"
```

Review the generated file. If it includes Postgres-specific DDL (RLS, partial indexes), guard it with:

```python
if op.get_bind().dialect.name == "postgresql":
    op.execute(...)
```

Module-level `from app.models import *` imports are required (Python 3.12 syntax error if placed inside a function).

## 6. Backup & restore

### 6.1 Manual backup

```bash
bash scripts/backup-postgres.sh > /tmp/archon-$(date +%Y%m%d-%H%M).sql.gz
```

The script uses `pg_dump` against `ARCHON_DATABASE_URL` and writes a compressed plain-format dump.

### 6.2 Restore

```bash
gunzip -c /tmp/archon-20260429-1500.sql.gz | bash scripts/restore-postgres.sh
```

`scripts/restore-postgres.sh` refuses to run against a database whose name starts with `archon_prod` unless `ARCHON_RESTORE_FORCE=true` is set — a guardrail against accidental restore over production.

### 6.3 PITR (production)

The AWS Terraform module enables RDS automated backups with 35-day retention. PITR is performed via the AWS console / `aws rds restore-db-instance-to-point-in-time`, not via this script. See your operator runbook.

## 7. Monitoring & alerts

### 7.1 Grafana

Dashboards live in `infra/grafana/dashboards/archon-*.json`. Loaded by the Grafana sidecar via the `grafana_dashboard` ConfigMap label.

```bash
kubectl -n archon-monitoring port-forward svc/archon-monitoring-grafana 3000:80
open http://localhost:3000
```

### 7.2 Prometheus alerts

Alert rules in `infra/monitoring/alerts/archon-orchestration.yaml` and `infra/monitoring/prometheus-values.yaml`. Loaded by `kube-prometheus-stack` via `additionalPrometheusRulesMap`.

Every alert references a metric in [`docs/metrics-catalog.md`](metrics-catalog.md). The CI gate `scripts/check-grafana-metric-parity.py` rejects PRs that introduce metric drift.

See [`docs/runbooks/observability.md`](runbooks/observability.md) for the operational walkthrough.

## 8. Health & readiness

| Endpoint | Type | When ready |
|----------|------|-----------|
| `GET /health` | Liveness | Process is up. |
| `GET /ready` | Readiness | Database connected, migrations at head, Vault reachable, checkpointer initialized. |
| `GET /api/v1/health` | Equivalent to `/health`. | — |
| `GET /metrics` | Prometheus scrape. | Always available. |

A backend pod that fails its startup gates **never** becomes Ready (it crashes before `Ready` can be true). A worker that fails the same gates exits with a non-zero code and Kubernetes restarts it; the backoff is the operator's signal that gates are misconfigured.

## 9. Troubleshooting

### 9.1 `startup_checks_failed` in logs

Read the failure list. Each line names the env var to fix. See [`docs/PRODUCTION_CONFIG.md §3`](PRODUCTION_CONFIG.md#3-startup-gates-run_startup_checks).

### 9.2 Worker not draining pending runs

```bash
kubectl logs deploy/archon-worker -n archon | grep "drain_loop"
# Look for: "claimed run <uuid>" lines
# If none: check ARCHON_DATABASE_URL is correct and worker has DB connectivity.
# If lease errors: another worker may hold the run; check worker_registry table.
```

### 9.3 Postgres checkpointer fails to initialize

```bash
kubectl exec -it deploy/archon-backend -- python -c "
from app.langgraph.checkpointer import get_checkpointer
import asyncio
asyncio.run(get_checkpointer())
"
# In production this MUST succeed and return an AsyncPostgresSaver.
# Common causes:
#   - DATABASE_URL not Postgres
#   - langgraph-checkpoint-postgres package not installed in the image
#   - Postgres instance unreachable
```

### 9.4 Vertical slice fails

```bash
make test-slice  # exits non-zero
```

Read the pytest output. The slice asserts on:
1. `POST /api/v1/agents` returns 201.
2. `POST /api/v1/executions` returns 200/201 with a run_id.
3. The run reaches a terminal status (`completed`).
4. `workflow_run_steps` rows exist.
5. `workflow_run_events` chain verifies.

Whichever assertion fails localizes the regression.

### 9.5 Frontend not connecting to WebSocket

Check `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` in `frontend/.env` (or the Helm value `frontend.env.VITE_API_BASE_URL`). The WebSocket client uses `wss://` if served over HTTPS.

## 10. Cross-references

- [`docs/PRODUCTION_CONFIG.md`](PRODUCTION_CONFIG.md) — env var + startup gate map.
- [`docs/STATE_MACHINE.md`](STATE_MACHINE.md) — what "terminal" means.
- [`docs/runbooks/observability.md`](runbooks/observability.md) — Grafana / Prometheus operational guide.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — bounded contexts the deploy maps onto.
- [`docs/adr/orchestration/ADR-005-production-durability-policy.md`](adr/orchestration/ADR-005-production-durability-policy.md) — fail-closed durability.
