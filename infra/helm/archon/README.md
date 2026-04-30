# Archon Helm Chart

Helm chart for the Archon AI Orchestration Platform — backend (FastAPI), worker
(scheduled jobs), frontend (React/nginx), and gateway (model proxy).

## TL;DR

```bash
# Dev install (defaults — stub LLM, single replicas, no NetPol/HPA/PDB)
helm upgrade --install archon ./infra/helm/archon \
  --namespace archon-dev --create-namespace \
  --set postgresql.host=postgres.archon-dev.svc.cluster.local \
  --set redis.host=redis.archon-dev.svc.cluster.local \
  --set vault.addr=http://vault.archon-dev.svc.cluster.local:8200 \
  --set secrets.existingAppSecret=archon-app

# Production install
helm upgrade --install archon ./infra/helm/archon \
  --namespace archon-production --create-namespace \
  -f infra/helm/archon/values-production.yaml \
  --set postgresql.host=<rds-host> \
  --set postgresql.existingSecret=archon-postgres \
  --set redis.host=<elasticache-host> \
  --set redis.existingSecret=archon-redis \
  --set vault.addr=https://vault.example.com \
  --set vault.existingSecret=archon-vault-token \
  --set secrets.existingAppSecret=archon-app
```

## Prerequisites

* Kubernetes ≥ 1.27
* Helm ≥ 3.12
* External PostgreSQL (this chart does not provision a database)
* External Redis
* External Vault (or compatible secrets provider)
* App secret bundle in the release namespace (a Kubernetes `Secret`) holding:
  * `ARCHON_JWT_SECRET` — strong random value (≥32 chars)
  * `ARCHON_VAULT_TOKEN` — AppRole-issued token
  * `POSTGRES_PASSWORD` — referenced via `postgresql.existingSecret`
  * `REDIS_PASSWORD` — referenced via `redis.existingSecret`

The chart **never** creates secrets containing live credentials — the operator
must inject them out-of-band (e.g. via External Secrets Operator, sealed
secrets, or vault-injector sidecars).

## Components

| Name | Image | Replicas (dev / prod) | Service Port |
|------|-------|-----------------------|--------------|
| backend | `archon/backend:<appVersion>` | 1 / 3 | 8000 |
| worker | `archon/worker:<appVersion>` | 2 / 5 | n/a (no listener) |
| frontend | `archon/frontend:<appVersion>` | 1 / 2 | 80 |
| gateway | `archon/gateway:<appVersion>` | 1 / 2 | 8080 |

A pre-install/pre-upgrade `Job` runs `alembic upgrade head` against the
backend image to apply database migrations before any pod rolls.

## Values Override Matrix

| Concern | Default | Production override |
|---------|---------|---------------------|
| `global.archonEnv` | `dev` | `production` |
| `stubMode` | `true` | `false` |
| `backend.replicaCount` | 1 | 3 |
| `worker.replicaCount` | 2 | 5 |
| `frontend.replicaCount` | 1 | 2 |
| `gateway.replicaCount` | 1 | 2 |
| `*.autoscaling.enabled` | `false` | `true` |
| `*.podDisruptionBudget.enabled` | `false` | `true` |
| `networkPolicies.enabled` | `false` | `true` (default-deny + allow rules) |
| `ingress.enabled` | `false` | `true` (TLS) |
| `config.enterpriseStrictTenant` | `false` | `true` |
| `config.langgraphCheckpointing` | `memory` | `postgres` |
| Resource limits | dev (1 CPU / 1Gi) | prod (2 CPU / 2Gi) |
| `containerSecurityContext.readOnlyRootFilesystem` | `false` | `true` |

The full set of overrides is captured in `values-production.yaml`.

## Common Operations

### Render manifests without applying

```bash
bash scripts/render-helm.sh
# Output: infra/k8s/manifests/dev.yaml + infra/k8s/manifests/production.yaml
```

### Lint the chart

```bash
bash scripts/lint-helm.sh
```

Or via the Makefile:

```bash
make helm-lint
make helm-render
```

### Upgrade

```bash
helm upgrade archon ./infra/helm/archon \
  --namespace archon-production \
  -f infra/helm/archon/values-production.yaml
```

The pre-upgrade migration `Job` runs `alembic upgrade head` *before* new pods
roll. If the migration fails, the upgrade aborts and the previous pods stay
running.

### Rollback

```bash
# List revisions
helm history archon -n archon-production

# Rollback to a previous revision
helm rollback archon <revision> -n archon-production
```

Rollback re-runs the pre-upgrade migration `Job` against the rollback chart
version. Make sure the target revision is migration-compatible (Alembic
downgrade is **not** automated by this chart — coordinate with the DBA before
rolling back across migration boundaries).

### Uninstall

```bash
helm uninstall archon -n archon-production
```

The migration `Job` is deleted automatically (`helm.sh/hook-delete-policy:
hook-succeeded`). Persistent data (postgres/redis volumes) is *not* affected
because this chart does not own those resources.

## Probes

| Component | Liveness | Readiness | Startup |
|-----------|----------|-----------|---------|
| backend | `GET /health` | `GET /ready` | `GET /health` (failureThreshold=30, period=5s) |
| worker | `pgrep -f app.worker` | n/a | n/a |
| frontend | `GET /` | `GET /` | n/a |
| gateway | `GET /health` | `GET /health` | n/a |

## Network Policies (production)

When `networkPolicies.enabled=true`, the chart applies:

* `archon-default-deny` — denies all ingress + egress in the namespace.
* `archon-allow-dns` — permits DNS to `kube-system/kube-dns`.
* `archon-backend` — accepts HTTP/8000 from frontend, gateway, and the
  configured ingress namespaces (default `ingress-nginx`).
* `archon-worker` — egress only.
* `archon-frontend` — accepts HTTP from ingress; egress only to backend.
* `archon-gateway` — accepts from backend; egress to the CIDRs in
  `networkPolicies.gatewayEgressCIDRs` (default `0.0.0.0/0`).

Tighten `networkPolicies.gatewayEgressCIDRs` to your LLM provider IP ranges
in real production deployments.

## Production Gates Honoured

The chart wires the env-vars enforced by `backend/app/startup_checks.py`:

* `ARCHON_ENV=production` (rejects dev defaults)
* `LANGGRAPH_CHECKPOINTING=postgres` (rejects memory checkpointer)
* `ARCHON_ENTERPRISE_STRICT_TENANT=true` (rejects lax tenant mode)
* `ARCHON_AUTH_DEV_MODE` not set (rejects dev auth)
* `ARCHON_JWT_SECRET` sourced from the existing app secret (chart never
  embeds the value)

Pods will refuse to start if any of these gates fail — the chart is
deliberately strict in `values-production.yaml` to avoid producing a release
that boots but is unsafe.

## Files

```
infra/helm/archon/
├── Chart.yaml
├── values.yaml                    # defaults (dev)
├── values-production.yaml         # production overrides
├── README.md
├── .helmignore
└── templates/
    ├── _helpers.tpl
    ├── configmap.yaml
    ├── serviceaccount.yaml
    ├── backend-deployment.yaml
    ├── backend-service.yaml
    ├── worker-deployment.yaml
    ├── frontend-deployment.yaml
    ├── frontend-service.yaml
    ├── gateway-deployment.yaml
    ├── gateway-service.yaml
    ├── ingress.yaml
    ├── hpa.yaml                   # autoscaling.enabled gated, per-component
    ├── pdb.yaml                   # podDisruptionBudget.enabled gated, per-component
    ├── networkpolicy.yaml         # networkPolicies.enabled gated
    └── migration-job.yaml         # pre-install/pre-upgrade Helm hook
```
