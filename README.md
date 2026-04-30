<div align="center">

# ⬡ Archon

### Enterprise-Grade AI Orchestration Platform

Build, deploy, and govern AI agents at scale — with a visual canvas, intelligent model routing, enterprise security, and data connectors.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg?logo=react&logoColor=white)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7+-3178C6.svg?logo=typescript&logoColor=white)](https://typescriptlang.org)

<br/>

<img src="docs/screenshots/dashboard.png" alt="Archon Dashboard" width="100%" />

</div>

---

## Status (2026-04-29)

Pre-1.0. **Substantial canonical orchestration substrate** with the official REST durable heartbeat passing through `bash scripts/verify-slice.sh` and `bash scripts/test-slice.sh` (inline-dispatch contract: `ARCHON_DISPATCH_INLINE=1`).

This is **not yet** a Temporal-class production-proven platform. Production fire-and-forget worker dispatch end-to-end, mandatory Postgres RLS in CI, Keycloak/OIDC end-to-end, live observability scrape, scale/chaos under load, and the security-scan severity threshold remain open. `RunHistoryPage`, `ApprovalsPage`, and `ArtifactsPage` exist with tests but are not yet registered in `frontend/src/App.tsx`.

See [`CURRENT_STATE.md`](CURRENT_STATE.md) for the canonical truth-table — what is proven vs script-green only vs implemented-but-unproven vs missing vs deferred. The phrase "production ready" does not appear in this repo by deliberate policy.

### Acceptance commands

```bash
python3 scripts/check-feature-matrix.py             # feature matrix valid (206 entries; 84 warnings)
python3 scripts/check-frontend-backend-parity.py    # 28 nodes both sides, 0 DRIFT
bash scripts/verify-slice.sh                        # REST canary (inline)
bash scripts/test-slice.sh                          # REST canary (inline, direct)
# bash scripts/test-worker-canary.sh                # non-inline worker proof — added when plan §P0 lands
```

Authoritative reports: [`REMEDIATION_REPORT.md`](REMEDIATION_REPORT.md) (2026-04-29 corrective action), [`PHASE_0_9_EXECUTION_REPORT.md`](PHASE_0_9_EXECUTION_REPORT.md) (historical narrative with reconciliation note prepended), [`ROADMAP.md`](ROADMAP.md) (phase ledger). Older completion reports are archived in [`docs/_archive/`](docs/_archive/) — they overclaimed prior cycles' state and are not authoritative.

---

## Overview

Archon is a self-hosted AI orchestration and governance platform for teams that need full control over their AI infrastructure. It replaces fragmented tooling with a single platform for building agent workflows, managing model providers, enforcing data loss prevention policies, and monitoring costs — all behind your firewall.

### Why Archon?

- **No vendor lock-in** — Model-agnostic via [LiteLLM](backend/app/langgraph/llm.py); OpenAI, Anthropic, Azure OpenAI proven via tests; other providers configured via the model registry.
- **Visual-first** — Drag-and-drop agent builder with **28 registered node executors** (see [`docs/feature-matrix.yaml`](docs/feature-matrix.yaml) for status — 14 production / beta, 12 honestly blocked in production via `_stub_block.py`, 2 infrastructure helpers).
- **Enterprise security** — Real `hvac` Vault integration (KV-v2 + PKI + Transit + AppRole), 3-tier JWT auth (HS256 / Keycloak / Azure Entra), Presidio-backed DLP, multi-tenancy with strict-mode startup gate, SHA-256 hash-chained audit + run event log.
- **Durable orchestration** — Postgres LangGraph checkpointer (fail-closed in production per [ADR-005](docs/adr/orchestration/ADR-005-production-durability-policy.md)); worker leasing with reclaim; durable timers; idempotency contract per [ADR-004](docs/adr/orchestration/ADR-004-idempotency-contract.md).
- **Self-hosted** — Docker Compose (8 services), Helm umbrella chart, AWS Terraform (VPC + EKS + RDS PG16 multi-AZ + ElastiCache + S3-KMS).
- **Honest observability** — Every emitted metric has a Grafana panel; every panel queries an emitted metric; CI gate `scripts/check-grafana-metric-parity.py` enforces. See [`docs/metrics-catalog.md`](docs/metrics-catalog.md).

---

## Features

### 🎨 Visual Agent Builder

Build AI workflows by dragging and connecting nodes on a canvas. 28 node executors registered. The activity layer enforces honesty: 12 stub executors are blocked in production (the dispatcher emits `step.failed` with `error_code="stub_blocked_in_production"`). See [`docs/feature-matrix.yaml`](docs/feature-matrix.yaml) for per-node status.

<img src="docs/screenshots/builder.png" alt="Agent Builder — Drag-and-drop canvas with 28 registered node executors" width="100%" />

<br/>

### 🔌 Data Connectors

5 reference connectors today (PostgreSQL, S3, Slack, REST, Google Drive); operator-extensible connector framework.

<img src="docs/screenshots/connectors.png" alt="Connectors — Databases, SaaS, communication, cloud, and custom integrations" width="100%" />

<br/>

### 🧭 Intelligent Model Router

Register multiple LLM providers, define routing rules based on capability, cost, latency, or tenant tier, and configure automatic fallback chains. Monitor provider health with real-time latency and error tracking.

<img src="docs/screenshots/model-router.png" alt="Model Router — Provider management, routing rules, and health monitoring" width="100%" />

<br/>

### 🛡️ Data Loss Prevention & Security

Scan agent inputs and outputs for PII, credentials, and sensitive data in real time. Define policies with configurable actions (redact, mask, block, alert) and sensitivity levels. Full audit trail for compliance.

<img src="docs/screenshots/dlp.png" alt="DLP — Real-time scanning, policy management, and detection metrics" width="100%" />

<br/>

### 📊 Operations Dashboard

Monitor active agents, execution throughput, model usage, and costs from a single pane. System health indicators for API, database, cache, vault, and identity services. Agent leaderboard and activity feed.

<img src="docs/screenshots/dashboard.png" alt="Dashboard — Metrics, health monitoring, cost tracking, and activity feed" width="100%" />

---

## Architecture

For the full bounded-context decomposition, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

```
archon/
├── frontend/          React 19 · TypeScript · @xyflow/react · Tailwind + hand-rolled UI
├── backend/           FastAPI · Python 3.12 · SQLModel · Alembic · LangGraph
│   └── app/services/node_executors/  ← 28 node types (status registry + stub-block gate)
├── security/          DLP engine · Red-team harness
├── integrations/      5 reference connectors (Postgres · S3 · Slack · REST · Google Drive)
├── ops/               (placeholder; cost engine lives in backend/app/services/cost_service.py)
├── infra/             Helm umbrella · AWS Terraform · Vault Helm · Grafana dashboards
├── gateway/           MCP gateway (rate limit · input validation · audit)
├── mobile/            Flutter — 3-screen stub (NOT a 1.0 surface)
└── tests/             Unit · Integration · Vertical slice · Load · Chaos
```

## Tech Stack (proven by `import` statements)

| Layer | Technology |
|:------|:-----------|
| **Frontend** | React 19 · TypeScript · @xyflow/react · Tailwind CSS · hand-rolled UI components |
| **Backend** | FastAPI 0.115+ · SQLModel · Alembic · Python 3.12 · `asyncio` worker (no Celery) |
| **Orchestration** | LangGraph + Postgres `AsyncPostgresSaver` (fail-closed in production) |
| **LLM** | LiteLLM (`litellm.acompletion`) · `LLM_STUB_MODE=true` for tests |
| **Security** | HashiCorp Vault (`hvac`) · Presidio DLP · `python-jose` JWT |
| **Monitoring** | Prometheus (custom `archon_*` metric set) · Grafana dashboards |
| **Deployment** | Docker Compose (8 services) · Helm umbrella · AWS Terraform |
| **Auth** | Keycloak (OIDC + JWKS) · Azure Entra ID (OIDC discovery) · HS256 dev mode |
| **Cost Tracking** | Real LiteLLM token usage + rate-card lookup → `cost_records` table → `archon_cost_total` metric |

---

## Quick Start

### Prerequisites

- Docker 24+ & Docker Compose 2+
- Node.js 20+ and Python 3.12+
- Git
- Optional: `make` (all the convenience targets are documented; the underlying commands work without it).

### One-shot startup

```bash
# Clone
git clone <repo-url>
cd archon

# Configure (dev defaults are safe for localhost; NOT for prod)
cp env.example .env

# Bring up the 8-service stack
make up
# = docker compose up -d
# Services: postgres, redis, backend, worker, frontend, keycloak, vault, vault-init

# Apply migrations
make migrate

# Run the vertical-slice REST canary (the heartbeat)
make test-slice
# This issues POST /api/v1/agents → POST /api/v1/executions and
# asserts a durable WorkflowRun reaches a terminal status. When it
# passes, the kernel works.

# Run the 5-gate verify pipeline
make verify
# = unit + integration + frontend + contracts + slice
```

Then open:
- Frontend: http://localhost:3000 (auth dev mode; static `dev-token`)
- Backend API: http://localhost:8000/docs
- Keycloak: http://localhost:8180 (`admin` / `admin`)
- Vault: http://localhost:8200 (root token: `dev-root-token`)

For staging / production deploys, see [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md). Production startup gates fail closed on dev defaults (`ARCHON_AUTH_DEV_MODE=true`, dev JWT secret, SQLite `DATABASE_URL`, `MemorySaver` checkpointer, `ARCHON_ENTERPRISE_STRICT_TENANT=false`) — see [`docs/PRODUCTION_CONFIG.md`](docs/PRODUCTION_CONFIG.md).

### Local backend dev (no Docker)

```bash
make dev                     # postgres + redis only
pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --reload --port 8000

# In another terminal:
cd frontend && npm install && npm run dev
```

---

## Project Structure

| Directory | Description |
|:----------|:------------|
| `frontend/` | React SPA — agent builder, dashboards, admin UI |
| `backend/` | FastAPI REST API + LangGraph + 28 node executors + worker |
| `gateway/` | MCP gateway — rate limiter (Redis sorted set), input validation, audit |
| `security/` | DLP engine + Red-team harness (13 OWASP-aligned attacks) |
| `integrations/` | 5 reference connectors (Postgres, S3, Slack, REST, Google Drive) |
| `contracts/` | OpenAPI 3.1 spec (`openapi.yaml`) — used by `verify-contracts` gate |
| `infra/` | Helm umbrella · AWS Terraform · Vault Helm · Grafana dashboards · Prometheus alert rules |
| `mobile/` | Flutter — 3-screen stub (NOT a 1.0 surface) |
| `scripts/` | Verify gates, migration helpers, backup/restore, load + chaos test runners |
| `tests/` | Integration tests including the vertical-slice REST canary |
| `docs/` | Architecture, ADRs, runbooks, feature matrix, gap analysis |

---

## Documentation

| Document | What's in it |
|:---------|:-------------|
| [`ROADMAP.md`](ROADMAP.md) | Phase-based ledger A–I; what's done with verifier sign-off, what's next. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | The seven bounded contexts (control plane, kernel, worker, activity layer, AI policy, visibility, enterprise ops). |
| [`docs/STATE_MACHINE.md`](docs/STATE_MACHINE.md) | `WorkflowRun` lifecycle: pending → claimed → running → (completed \| failed \| cancelled \| paused → resumed). |
| [`docs/PRODUCTION_CONFIG.md`](docs/PRODUCTION_CONFIG.md) | Every `ARCHON_*` env var, plus the seven startup gates that fail closed on misconfiguration in production. |
| [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md) | Local (compose) → staging (Helm) → production (Helm + Terraform + External Secrets). |
| [`docs/FEATURE_MAPPING.md`](docs/FEATURE_MAPPING.md) | Feature → code → tests → docs map. Linked from [`docs/feature-matrix.yaml`](docs/feature-matrix.yaml) (canonical 206-entry inventory). |
| [`docs/GAP_ANALYSIS.md`](docs/GAP_ANALYSIS.md) | Residual ledger: P0/P1/P2/P3 gaps with priority, effort, dependencies. |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Branch strategy, PR template, definition of done, test discipline. |
| [`docs/metrics-catalog.md`](docs/metrics-catalog.md) | Canonical metric set; the contract between emitters and dashboards / alerts. |
| [`docs/runbooks/observability.md`](docs/runbooks/observability.md) | Grafana / Prometheus operational guide. |
| [`docs/load-test-profiles.md`](docs/load-test-profiles.md) | Phase F load test profiles. |
| [`docs/adr/orchestration/`](docs/adr/orchestration/) | The seven binding orchestration ADRs (run model, event ownership, branching, idempotency, durability, migration, deletion). |
| [`docs/adr/`](docs/adr/) | Cross-cutting ADRs (auth, secrets, audit, tenant). |

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](docs/CONTRIBUTING.md) before submitting a pull request.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'feat: add your feature'`)
4. Push to your branch (`git push origin feature/your-feature`)
5. Open a Pull Request

---

## License

Licensed under the [Apache License 2.0](LICENSE).

---

<div align="center">
<sub>Built with ⬡ by the Archon team</sub>
</div>
