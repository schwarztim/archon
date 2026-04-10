<div align="center">

# Archon

**Enterprise AI orchestration — visual agent builder, intelligent model routing, and enterprise-grade governance at scale.**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg?logo=react&logoColor=white)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7+-3178C6.svg?logo=typescript&logoColor=white)](https://typescriptlang.org)

</div>

---

## Overview

Archon is a self-hosted platform for building, deploying, and governing AI agents in production environments. It provides a visual workflow canvas, a model-agnostic routing layer across six LLM providers, real-time data loss prevention, fine-grained access control, and 50+ data connectors — all deployable behind your firewall.

The platform targets teams that need the capability of managed AI services without the tradeoffs: no data leaving your perimeter, no vendor lock-in, and full audit visibility.

**Key properties:**

- **Model-agnostic** — Routes across Claude, GPT-4o, Gemini, Llama, Mistral, and Cohere with configurable fallback chains
- **Visual-first** — Drag-and-drop agent builder with 27+ node types; no code required for most workflows
- **Enterprise security** — Real-time DLP scanning, RBAC/ABAC, Keycloak SSO, multi-tenancy, and OPA policy enforcement
- **Self-hosted** — First-class support for on-prem, air-gapped, and private cloud deployments via Kubernetes and Helm
- **Observable** — OpenTelemetry instrumentation, Prometheus metrics, token-level cost tracking, and Grafana dashboards

---

## Features

### Visual Agent Builder

A canvas-based workflow editor for composing AI agents without writing orchestration code. Nodes cover the full spectrum of production agent needs: LLM inference, tool execution, branching logic, parallel fan-out/fan-in, RAG retrieval, DLP scanning checkpoints, and human-in-the-loop approval gates.

27+ built-in node types. Workflows are serialized as versioned DAGs and executable via REST or event trigger.

### Intelligent Model Router

A routing layer that abstracts provider selection from agent logic. Rules can target capability requirements, cost ceilings, latency SLOs, or tenant tier. Automatic fallback chains handle provider outages without surfacing errors to callers. Provider health is tracked in real time with per-model latency and error rate metrics.

Supported providers: OpenAI, Anthropic, Google (Gemini), Mistral, Cohere, Meta (Llama via Ollama/vLLM). LiteLLM proxy integration available for extended provider support.

### Data Loss Prevention

All agent inputs and outputs pass through a configurable DLP engine before leaving the platform boundary. Detectors cover PII categories (names, addresses, SSNs, card numbers), credentials, API keys, and custom regex patterns. Policy actions: redact, mask, block, or alert with full audit trail. Designed for HIPAA, PCI-DSS, and SOC 2 contexts.

### Access Control

Attribute-based and role-based access control enforced at the API layer via OPA. Keycloak provides OIDC/OAuth 2.0 SSO integration with support for existing enterprise identity providers (SAML, LDAP, AD). Tenant isolation enforced at the data layer.

### 50+ Data Connectors

Pre-built connectors for:

- **Databases** — PostgreSQL, MySQL, MongoDB, Snowflake, BigQuery, Redis
- **SaaS** — Salesforce, Jira, Confluence, HubSpot, Zendesk, ServiceNow
- **Communication** — Slack, Microsoft Teams
- **Storage** — Amazon S3, Azure Blob, Google Cloud Storage
- **Custom** — REST and GraphQL connector SDK for arbitrary integrations

### 17 Specialized AI Agents

Purpose-built agents deployed as LangGraph state machines: code review, document analysis, data pipeline orchestration, incident triage, compliance auditing, and more. Each agent is independently configurable and composable within the visual builder.

### Operations Dashboard

Unified view of agent execution throughput, model usage by provider, token spend, and system health. Health indicators cover the full dependency stack: API, Postgres, Redis, Vault, and identity services. Agent execution leaderboard and live activity feed.

---

## Architecture

```
archon/
├── frontend/          React 19 · TypeScript · React Flow · shadcn/ui · Monaco Editor
├── backend/           FastAPI · SQLModel · Alembic · Celery · Python 3.12
├── agents/            LangGraph state machines · 17 specialized agents
├── security/          DLP engine · Guardrails AI · NeMo Guardrails · OPA policies
├── integrations/      50+ connectors · REST/GraphQL SDK
├── ops/               Model router · Cost tracker · OpenTelemetry instrumentation
├── data/              RAG pipeline · PGVector · LlamaIndex · Unstructured.io
├── infra/             Terraform · Helm charts · Kubernetes manifests · Kyverno
├── mobile/            Flutter SDK · iOS/Android
└── tests/             Unit · Integration · E2E
```

**Request path (agent execution):**

1. Client calls REST API or triggers via event source
2. Auth middleware validates JWT, enforces RBAC/ABAC via OPA
3. DLP engine scans input payload against active policies
4. Model router selects provider based on routing rules and real-time health
5. LangGraph state machine executes the agent DAG, invoking tools and connectors as needed
6. DLP engine scans output before returning to caller
7. OpenTelemetry spans and token usage written to observability pipeline

**Storage:**

- Postgres (primary) + PGVector (embeddings) — agent definitions, executions, audit logs, user data
- Redis — execution state cache, Celery task queue
- HashiCorp Vault — provider API keys, connector credentials

---

## Tech Stack

| Layer | Technology |
|:------|:-----------|
| Frontend | React 19, TypeScript, React Flow, shadcn/ui, Tailwind CSS, Monaco Editor |
| Backend | FastAPI, SQLModel, Alembic, Celery, Python 3.12 |
| Orchestration | LangGraph, LangChain |
| Vector / RAG | PGVector, LlamaIndex, Unstructured.io |
| Security | OPA, Guardrails AI, NeMo Guardrails, HashiCorp Vault |
| Auth | Keycloak, OAuth 2.0, OIDC, RBAC/ABAC |
| Observability | OpenTelemetry, Prometheus, Grafana, OpenSearch |
| Deployment | Kubernetes, Helm, ArgoCD, Terraform, Cert-Manager, Kyverno |
| Cost Tracking | OpenLLMetry, custom token accounting engine |

---

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Node.js 20+, Python 3.12+

### Local Development

```bash
git clone https://github.com/schwarztim/archon.git
cd archon

# Copy environment template
cp env.example .env

# Start Postgres and Redis
make dev

# Backend
pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

### Full Stack via Docker

```bash
make up       # start all services
make migrate  # run database migrations
make logs     # tail logs
```

### Enterprise Mode (Vault + Keycloak)

```bash
make dev-enterprise   # start with full enterprise services
make secrets-init     # initialize HashiCorp Vault secrets
```

---

## Project Structure

| Directory | Purpose |
|:----------|:--------|
| `frontend/` | React SPA — agent builder, dashboards, admin UI |
| `backend/` | FastAPI REST API — agents, models, executions, auth |
| `agents/` | Agent definitions and LangGraph state machines |
| `security/` | DLP engine, guardrails, red-team tooling |
| `integrations/` | Data connectors and connector SDK |
| `ops/` | Model router, cost engine, monitoring |
| `data/` | RAG pipeline and document processing |
| `infra/` | Terraform modules, Helm charts, Kubernetes manifests |
| `docs/` | Architecture docs and API reference |

---

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — System design, component interactions, data flow
- [Roadmap](ROADMAP.md) — Feature roadmap and release milestones
- [Contributing](docs/CONTRIBUTING.md) — Development setup, code style, PR process

---

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](docs/CONTRIBUTING.md) before submitting a pull request.

```bash
git checkout -b feature/your-feature
# make changes
git commit -m 'feat: description'
git push origin feature/your-feature
# open a pull request
```

---

## License

Licensed under the [Apache License 2.0](LICENSE).
