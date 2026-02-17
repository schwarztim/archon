# Agent 21 — Deployment Infrastructure — Build Prompt

> Hand this file to a coding agent. It contains everything needed to build this component.

## Context
You are building **Deployment Infrastructure** — Docker Compose, Helm charts, CI/CD, and monitoring for Archon.
Project root: `~/Scripts/Archon/`

## What Already Exists (do NOT rebuild these)
- `docker-compose.yml` — Working compose file with 5 services (backend, frontend, postgres, redis, keycloak). EXTEND.
- `infra/helm/archon-platform/` — Helm chart for Archon. UPDATE values.
- `infra/helm/vault/` — Helm chart for Vault. KEEP.

## What to Build

### 1. Docker Compose Enhancement
Add services:
- **vault**: HashiCorp Vault in dev mode for local development. Port 8200. Auto-initialize with dev root token. Health check.
- **prometheus**: Prometheus for metrics collection. Scrape backend /metrics endpoint. Port 9090.
- **grafana**: Grafana for dashboards. Pre-configured datasource (Prometheus). Port 3001.
- **worker**: Background worker for async tasks (scheduled scans, rotation checks, budget alerts). Same image as backend, different entrypoint.

### 2. Backend Metrics Endpoint
Add `/metrics` endpoint (Prometheus format) exposing:
- `archon_requests_total{method,path,status}` — HTTP request count
- `archon_request_duration_seconds{method,path}` — Request latency histogram
- `archon_executions_total{status}` — Execution count
- `archon_active_agents` — Current active agent count
- `archon_vault_status` — Vault connection status gauge

### 3. Grafana Dashboards
Create pre-built dashboards (JSON provisioning):
- **Platform Overview**: Request rate, error rate, latency p50/p95/p99, active agents, executions/hour
- **Cost Dashboard**: Token usage over time, cost by provider, budget utilization
- **Security Dashboard**: DLP scans, blocked requests, audit events

### 4. Helm Chart Updates
Update `infra/helm/archon-platform/values.yaml`:
- Add Vault container settings
- Add monitoring stack settings
- Update environment variables for new features
- Add health check probes
- Add resource limits and requests

### 5. CI/CD Pipeline
Create `.github/workflows/`:
- `ci.yml`: On PR — lint (ruff), test (pytest), build (docker compose build), security scan
- `cd.yml`: On merge to main — build images, push to registry, deploy to staging

### 6. Environment Configuration
Create `env.example` with all required environment variables documented:
- Database, Redis, Keycloak URLs
- Vault address and token
- JWT secret
- Feature flags

## Patterns to Follow (from OSS)

### Pattern 1: Dify Docker Compose (dify/docker/)
Dify has a comprehensive docker-compose with 10+ services including web, API, worker, DB, Redis, Weaviate, Sandbox, SSRF proxy, Nginx. Each service has health checks, restart policies, and volume mounts. Adaptation: Same multi-service pattern but with Archon's service set. Add Vault (which Dify doesn't have) and monitoring stack.

### Pattern 2: Flowise Docker Configuration
Flowise has a simpler Docker setup focused on single-container deployment with optional database. Adaptation: Archon needs the full enterprise stack but can learn from Flowise's simplicity for the "quick start" developer experience.

## Backend Deliverables

| Deliverable | Description |
|---|---|
| `/metrics` endpoint | Prometheus-format metrics |
| `backend/app/middleware/metrics_middleware.py` | Request metrics collection |
| Worker entrypoint | Background task runner |

## Frontend Deliverables
No frontend changes for Agent 21.

## Integration Points
- **Agent 17 (Secrets)**: Vault container configuration
- **Agent 19 (Settings)**: Health endpoint reports all service statuses
- All agents benefit from monitoring and CI/CD

## Acceptance Criteria
1. `docker compose up` starts all services including Vault, Prometheus, Grafana
2. Vault accessible at localhost:8200 with dev token
3. Backend /metrics endpoint returns Prometheus-format data
4. Grafana accessible at localhost:3001 with pre-built dashboards
5. Helm chart deploys to Kubernetes cluster
6. CI pipeline runs lint and tests on PR
7. `env.example` documents all required environment variables
8. All existing services still work after compose changes

## Files to Read Before Starting
- `~/Scripts/Archon/agents/AGENT_RULES.md`
- `~/Scripts/Archon/docker-compose.yml`

## Files to Create/Modify

| Path | Action |
|---|---|
| `docker-compose.yml` | MODIFY |
| `docker-compose.monitoring.yml` | CREATE (optional override) |
| `backend/app/middleware/metrics_middleware.py` | CREATE |
| `infra/helm/archon-platform/values.yaml` | MODIFY |
| `infra/grafana/dashboards/platform-overview.json` | CREATE |
| `infra/grafana/dashboards/cost-dashboard.json` | CREATE |
| `infra/grafana/dashboards/security-dashboard.json` | CREATE |
| `infra/prometheus/prometheus.yml` | CREATE |
| `.github/workflows/ci.yml` | CREATE |
| `.github/workflows/cd.yml` | CREATE |
| `env.example` | CREATE |

## Testing
```bash
cd ~/Scripts/Archon && docker compose up -d
# Wait for services to start
curl http://localhost:8000/metrics
curl http://localhost:8200/v1/sys/health  # Vault
curl http://localhost:9090/api/v1/targets  # Prometheus
curl http://localhost:3001/api/health  # Grafana
```

## Constraints
- Python 3.12, type hints, docstrings. Use `python3` not `python`.
- Always `PYTHONPATH=backend` for pytest.
- API envelope: `{"data": ..., "meta": {"request_id", "timestamp"}}`
- No raw JSON fields on any user-facing form.
- All credentials via SecretsManager, never in DB.
- Never use `password=value` directly — use dict unpacking.
- Do NOT read ROADMAP.md, INSTRUCTIONS.md, ARCHITECTURE.md.
- Tests must pass: `cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q`
