# Archon — Architecture Document

> Version 1.0 | February 14, 2026

---

## 1. Overview

Archon is an enterprise-grade, open-source AI orchestration and governance platform. It provides a complete lifecycle for building, deploying, monitoring, securing, and governing AI agents at scale.

### Design Principles

| Principle | Description |
|-----------|-------------|
| **Security-First** | Zero-trust architecture, DLP by default, SOC2/HIPAA/GDPR ready |
| **Model-Agnostic** | Swap any LLM without code changes; route dynamically by cost/latency/sensitivity |
| **Observable** | OpenTelemetry throughout; every token, every decision, every dollar tracked |
| **Scalable** | Horizontally scalable to 10k+ concurrent agents on Kubernetes |
| **Extensible** | Plugin architecture for connectors, guardrails, and routing strategies |
| **Open** | Apache 2.0; no vendor lock-in; air-gapped deployment supported |

---

## 2. High-Level System Design

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐    │
│  │ Web UI   │  │ Mobile   │  │ REST API │  │ SDK (Python/TS)  │    │
│  │ (React)  │  │ (Flutter)│  │ (FastAPI)│  │                  │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘    │
│       └──────────────┴─────────────┴─────────────────┘              │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                      API GATEWAY / AUTH LAYER                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ Keycloak     │  │ Rate Limiter │  │ Request Validator        │  │
│  │ (OIDC/OAuth2)│  │              │  │ (OPA Policy Engine)      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                     ORCHESTRATION LAYER                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ Agent Engine    │  │ Intelligent     │  │ Lifecycle Manager  │  │
│  │ (LangGraph)    │  │ Router          │  │ (Canary, A/B, etc.)│  │
│  └─────────────────┘  └─────────────────┘  └────────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ NL → Agent     │  │ Template Engine │  │ Version Control    │  │
│  │ Wizard          │  │                 │  │                    │  │
│  └─────────────────┘  └─────────────────┘  └────────────────────┘  │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                     SECURITY & GOVERNANCE LAYER                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ DLP Engine     │  │ Guardrails      │  │ Red-Team Engine   │  │
│  │ (Multi-layer)  │  │ (NeMo + Custom) │  │ (Garak + Custom)  │  │
│  └─────────────────┘  └─────────────────┘  └────────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ Audit Logger   │  │ Policy Engine   │  │ Compliance        │  │
│  │                 │  │ (OPA)           │  │ Dashboard (Neo4j) │  │
│  └─────────────────┘  └─────────────────┘  └────────────────────┘  │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                     DATA & INTEGRATION LAYER                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ RAG Engine     │  │ Doc Processor   │  │ Connector Hub     │  │
│  │ (LlamaIndex)   │  │ (Unstructured)  │  │ (50+ connectors)  │  │
│  └─────────────────┘  └─────────────────┘  └────────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ Vector Store   │  │ Object Store    │  │ Cache Layer       │  │
│  │ (PGVector)     │  │ (MinIO/S3)      │  │ (Redis/Valkey)    │  │
│  └─────────────────┘  └─────────────────┘  └────────────────────┘  │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                     OPERATIONS & OBSERVABILITY                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ Cost Engine    │  │ Token Ledger    │  │ Metrics           │  │
│  │ (Chargeback)   │  │ (OpenLLMetry)   │  │ (Prometheus)      │  │
│  └─────────────────┘  └─────────────────┘  └────────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ Tracing        │  │ Logging         │  │ Dashboards        │  │
│  │ (OTel + Jaeger)│  │ (OpenSearch)    │  │ (Grafana)         │  │
│  └─────────────────┘  └─────────────────┘  └────────────────────┘  │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                     INFRASTRUCTURE LAYER                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ Kubernetes     │  │ Helm Charts    │  │ Terraform Modules │  │
│  │ (ArgoCD)       │  │ (+ Air-gapped)  │  │ (AWS/Azure/GCP)   │  │
│  └─────────────────┘  └─────────────────┘  └────────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ Cert-Manager   │  │ Kyverno        │  │ Secret Mgmt       │  │
│  │                 │  │ (Policies)      │  │ (Vault)           │  │
│  └─────────────────┘  └─────────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Breakdown

### 3.1 Frontend — No-Code Agent Builder

**Tech**: React 19 + Vite + TypeScript + React Flow + shadcn/ui + Tailwind CSS + Monaco Editor

| Component | Description |
|-----------|-------------|
| **Canvas** | React Flow-based drag-and-drop builder with 200+ node types |
| **Node Palette** | Categorized: LLM, Tool, Condition, Human-in-Loop, Input/Output, Custom |
| **Property Panel** | Context-aware configuration for each node |
| **Preview Pane** | Live agent execution preview with streaming output |
| **Version Timeline** | Git-like visual history with diff and rollback |
| **Template Browser** | Searchable catalog with preview and one-click deploy |
| **Pro-Code Editor** | Monaco Editor for Python/TypeScript agent code |
| **Dashboard** | Analytics, cost tracking, active agents, alerts |
| **Admin Console** | User management, RBAC, audit logs, compliance reports |

### 3.2 Backend — Core API & Orchestration

**Tech**: FastAPI + Python 3.12 + SQLModel + Alembic + Celery + Redis

| Service | Endpoints | Description |
|---------|-----------|-------------|
| **Agent Service** | `/api/v1/agents/*` | CRUD, versioning, deployment |
| **Execution Service** | `/api/v1/execute/*` | Run agents, stream results via WebSocket |
| **Router Service** | `/api/v1/route/*` | Model selection, cost/latency scoring |
| **Template Service** | `/api/v1/templates/*` | Browse, fork, publish templates |
| **User Service** | `/api/v1/users/*` | Profile, preferences, API keys |
| **Audit Service** | `/api/v1/audit/*` | Complete audit trail |
| **Cost Service** | `/api/v1/cost/*` | Token tracking, budgets, forecasts |
| **Connector Service** | `/api/v1/connectors/*` | Data source management |
| **Admin Service** | `/api/v1/admin/*` | System config, health, metrics |

**Database Schema** (PostgreSQL + PGVector):
```
agents          — Agent definitions, metadata, ownership
agent_versions  — Immutable version snapshots
executions      — Run history, inputs, outputs, metrics
models          — Registered LLM providers and configurations
connectors      — Data source configs and credentials (encrypted)
users           — User profiles, roles, permissions
audit_logs      — Immutable audit trail
cost_records    — Token usage, costs, departmental allocation
templates       — Agent templates with categories and tags
guardrails      — DLP rules, content policies, sensitivity levels
```

### 3.3 Agent Engine — LangGraph State Machines

**Tech**: LangGraph + LangChain + LiteLLM

Every agent is a LangGraph state machine with:
- **Nodes**: LLM calls, tool invocations, conditionals, human-in-loop
- **State**: Typed state object with full history
- **Checkpointing**: PostgreSQL-backed for durability
- **Streaming**: Token-by-token via WebSocket
- **Interrupts**: Human approval gates at any node

### 3.4 Intelligent Router

**Tech**: Custom Python service + Redis + Prometheus

Routing decision factors:
1. **Cost** — Token pricing per model, budget remaining
2. **Latency** — Real-time latency measurements per provider
3. **Capability** — Model strengths (code, reasoning, creative, etc.)
4. **Sensitivity** — Data classification level → model eligibility
5. **Availability** — Health checks, rate limit headroom
6. **User Preference** — Override rules per team/department

### 3.5 Security Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Authentication** | Keycloak | SSO, OIDC, OAuth2, MFA |
| **Authorization** | OPA + Custom RBAC/ABAC | Fine-grained access control |
| **DLP** | Multi-layer (regex + LLM + semantic) | PII/PHI/secrets detection |
| **Guardrails** | NeMo Guardrails + Guardrails AI | Content safety, hallucination detection |
| **Red-Teaming** | Garak + custom suites | Automated adversarial testing |
| **Secrets** | HashiCorp Vault | Credential management |
| **Network** | mTLS + network policies | Zero-trust networking |
| **Audit** | Immutable append-only log | Complete traceability |

### 3.6 Data & RAG Pipeline

```
Document Ingestion:
  Upload → Unstructured.io Parser → Chunking → Embedding → PGVector

Query Pipeline:
  User Query → Embedding → Vector Search → Reranking → Context Assembly → LLM
```

Supported formats: PDF, DOCX, PPTX, XLSX, HTML, Markdown, Plain Text, Images (OCR), Audio (Whisper), Video (keyframes)

### 3.7 Connector Hub

**Initial 50+ Connectors:**

| Category | Connectors |
|----------|-----------|
| **Productivity** | Microsoft 365 (SharePoint, Teams, Outlook, OneDrive), Google Workspace, Notion, Confluence, Slack |
| **CRM** | Salesforce, HubSpot, Dynamics 365 |
| **Dev Tools** | GitHub, GitLab, Jira, Linear, Azure DevOps |
| **Databases** | PostgreSQL, MySQL, MongoDB, Snowflake, BigQuery, Databricks |
| **Cloud Storage** | S3, Azure Blob, GCS, MinIO |
| **Communication** | Email (IMAP/SMTP), SMS (Twilio), WhatsApp |
| **ITSM** | ServiceNow, PagerDuty, Zendesk |
| **ERP** | SAP, Oracle, NetSuite |
| **Identity** | Active Directory, Okta, Azure AD |
| **Custom** | REST API, GraphQL, gRPC, WebSocket, MCP Protocol |

## 3.8 MCP Host Gateway

**Tech**: FastAPI + Python 3.12 + Plugin Registry

The MCP (Model Context Protocol) Host Gateway is a lightweight, independently deployable service that bridges external MCP-compatible tools and the Archon platform. It exposes a plugin-based architecture where each plugin maps to a set of tool definitions callable by AI agents.

**Location:** `gateway/` (standalone FastAPI service, port 8080)

### Components

| Component | File(s) | Description |
|-----------|---------|-------------|
| **FastAPI App** | `gateway/app/main.py` | Application factory; lifespan hook loads plugins and starts the hot-reload watcher |
| **Plugin Registry** | `gateway/app/plugins/loader.py` | Discovers YAML-defined plugins from `gateway/plugins/`; supports hot-reload via `watchfiles` |
| **Plugin Loader** | `gateway/app/plugins/loader.py` | Validates plugin schemas, resolves tool configurations at startup |
| **Capabilities API** | `gateway/app/routes/capabilities.py` | `GET /api/v1/capabilities` — returns all tool manifests from loaded plugins |
| **Invoke API** | `gateway/app/routes/invoke.py` | `POST /api/v1/invoke/{tool}` — routes a tool call to the correct plugin |
| **Plugins API** | `gateway/app/routes/plugins.py` | `GET /api/v1/plugins` — list all loaded plugins and their metadata |
| **Health Probe** | `gateway/app/routes/health.py` | `GET /health` — liveness check, reports loaded plugin count |
| **JWKS Cache** | `gateway/app/auth/middleware.py` | Resolves OIDC discovery → `jwks_uri`, caches keyset for 1 hour (TTL-based, async-safe lock) |
| **Docs** | (FastAPI default) | `GET /docs` — Swagger UI, `GET /redoc` — ReDoc |

### JWKS Caching

The gateway verifies incoming JWTs using Entra ID (Azure AD). The JWKS endpoint is resolved lazily on the first authenticated request:

1. Fetch OIDC discovery document from `ARCHON_OIDC_DISCOVERY_URL`
2. Extract `jwks_uri` from the response
3. Fetch the JSON Web Key Set (JWKS) and cache it in-process for **1 hour** (`_JWKS_TTL_SECONDS = 3600`)
4. All subsequent requests within the TTL window use the cached keyset — no network round-trips
5. Cache refresh is protected by an `asyncio.Lock` to prevent thundering herd on expiry

### Plugin Schema (`gateway/plugins/_example.yaml`)

```yaml
name: my-tool
version: "1.0"
description: "Example MCP tool plugin"
tools:
  - name: do_something
    description: "Performs an action"
    parameters: {}
```

**Deployment:** The gateway runs as a separate container (`archon-gateway`) and is built/pushed independently in the CD pipeline. It communicates with the Archon backend via internal service networking.

---



### 4.1 Agent Execution Flow

```
User → Web UI → API Gateway → Auth Check → Agent Service
  → Load Agent Definition
  → Initialize LangGraph State Machine
  → Router selects optimal model(s)
  → Execute nodes sequentially/parallel
    → Each node: DLP scan input → LLM call → Guardrail check output
    → Log: tokens, cost, latency, content hash
  → Stream results via WebSocket
  → Persist execution record + audit log
  → Update cost ledger
```

### 4.2 Agent Creation Flow (No-Code)

```
User → Drag nodes onto canvas → Configure properties
  → Save → Validate graph (cycles, missing configs)
  → Generate LangGraph JSON + Python
  → Deploy to sandbox → Run test suite
  → Preview results → Iterate
  → Publish (version bump) → Available for production
```

### 4.3 Natural Language → Agent Flow

```
User describes intent → Planner LLM creates spec + diagram
  → User reviews/edits plan
  → Coder LLM generates LangGraph JSON + Python
  → Validator LLM checks for security/logic issues
  → Auto-deploy to sandbox
  → User tests → Feedback loop → Finalize
```

---

## 5. Security Model

### 5.1 Zero-Trust Architecture

- **Network**: All internal communication over mTLS
- **Identity**: Every request authenticated via JWT (Keycloak)
- **Authorization**: OPA evaluates every API call against policies
- **Data**: Encrypted at rest (AES-256) and in transit (TLS 1.3)
- **Secrets**: Never stored in code; HashiCorp Vault for all credentials
- **Isolation**: Agent sandboxes run in isolated K8s namespaces with resource limits

### 5.2 DLP Pipeline

```
Input → Regex patterns (SSN, CC, etc.)
     → NER model (spaCy/Presidio)
     → Semantic classifier (sensitivity level)
     → Policy engine (block/mask/allow)
     → Audit log entry

Output → Same pipeline in reverse
      → Hallucination detector
      → Toxicity/bias scorer
      → Policy enforcement
      → Audit log entry
```

### 5.3 Compliance Readiness

| Standard | Implementation |
|----------|---------------|
| **SOC2 Type II** | Audit logging, access controls, change management, monitoring |
| **GDPR** | Data residency controls, right to erasure, consent management, DPO tools |
| **HIPAA** | PHI detection/masking, BAA support, encryption, access logging |
| **ISO 27001** | Information security management via OPA policies |
| **FedRAMP** | Air-gapped deployment, FIPS 140-2 encryption options |

---

## 6. Scalability Strategy

### 6.1 Horizontal Scaling

| Component | Scaling Strategy |
|-----------|-----------------|
| API Gateway | Kubernetes HPA based on request rate |
| Agent Engine | Worker pool with Celery; scale workers independently |
| Router | Stateless; scale via replicas |
| Vector DB | PGVector with read replicas; consider Qdrant for >1B vectors |
| Cache | Redis Cluster with sentinel |
| WebSocket | Sticky sessions via Kubernetes ingress |

### 6.2 Performance Targets

| Metric | Target |
|--------|--------|
| API Response (p95) | < 100ms (non-LLM calls) |
| Routing Decision (p95) | < 200ms |
| Agent Start (cold) | < 2 seconds |
| Agent Start (warm) | < 200ms |
| Concurrent Agents | 10,000+ |
| Document Ingestion | 1000 pages/minute |
| WebSocket Latency | < 50ms |

### 6.3 Multi-Tenancy

- **Namespace isolation**: Each tenant gets a dedicated K8s namespace
- **Database isolation**: Schema-per-tenant or row-level security (configurable)
- **Resource quotas**: CPU/memory/storage limits per tenant
- **Network policies**: Tenant traffic isolation
- **Cost attribution**: Full token/compute tracking per tenant

---

## 7. Deployment Options

### 7.1 Docker Compose (Development)

```yaml
# Single-node development setup
services:
  api, worker, ui, postgres, redis, keycloak, minio
```

### 7.2 Kubernetes (Production)

```
Helm chart with:
- Configurable replicas per service
- PodDisruptionBudgets
- HPA for auto-scaling
- Network policies
- Cert-Manager for TLS
- ArgoCD for GitOps
- Kyverno for policy enforcement
```

### 7.3 Air-Gapped / On-Premises

```
- Offline Helm chart bundle with all images
- Local model inference via vLLM/Ollama
- No external dependencies
- FIPS-compliant TLS options
- Manual certificate management
```

### 7.4 Cloud-Managed

```
Terraform modules for:
- AWS (EKS + RDS + ElastiCache + S3)
- Azure (AKS + Azure Database + Redis + Blob)
- GCP (GKE + Cloud SQL + Memorystore + GCS)
```

---

## 8. Tech Stack Summary

| Layer | Primary | Alternatives |
|-------|---------|-------------|
| **Frontend** | React 19 + Vite + TypeScript | — |
| **UI Components** | shadcn/ui + Tailwind CSS | — |
| **Canvas** | React Flow | — |
| **Code Editor** | Monaco Editor | CodeMirror 6 |
| **Backend** | FastAPI (Python 3.12) | — |
| **ORM** | SQLModel + Alembic | SQLAlchemy |
| **Task Queue** | Celery + Redis | RQ, Dramatiq |
| **Database** | PostgreSQL 16 + PGVector | — |
| **Cache** | Redis 7 / Valkey | — |
| **Object Storage** | MinIO (self-hosted) / S3 | — |
| **Search** | OpenSearch | Elasticsearch |
| **Graph DB** | Neo4j (governance) | — |
| **Auth** | Keycloak 24 | — |
| **Policy** | OPA (Open Policy Agent) | — |
| **Secrets** | HashiCorp Vault | — |
| **LLM Orchestration** | LangGraph + LangChain | — |
| **LLM Gateway** | LiteLLM | — |
| **RAG** | LlamaIndex + Unstructured | Haystack |
| **Embeddings** | sentence-transformers | — |
| **Vector Search** | PGVector | Qdrant, Weaviate |
| **Guardrails** | NeMo Guardrails + Guardrails AI | — |
| **Red-Teaming** | Garak | — |
| **DLP** | Presidio + Custom | — |
| **Observability** | OpenTelemetry + Prometheus + Grafana | — |
| **Logging** | OpenSearch + Fluent Bit | — |
| **Tracing** | Jaeger | Tempo |
| **Cost Tracking** | OpenLLMetry + Custom Ledger | — |
| **Container Runtime** | Kubernetes (1.29+) | — |
| **GitOps** | ArgoCD | Flux |
| **Policy Enforcement** | Kyverno | — |
| **TLS** | Cert-Manager | — |
| **IaC** | Terraform + Helm | Pulumi |
| **Mobile** | Flutter 3 | — |
| **CI/CD** | GitHub Actions | GitLab CI |

---

## 9. API Versioning Strategy

- Base path: `/api/v1/`
- Semantic versioning for breaking changes
- Deprecation notices 2 versions ahead
- OpenAPI 3.1 spec auto-generated from code
- SDK auto-generation for Python, TypeScript, Go

---

## 10. Disaster Recovery

| Scenario | Strategy |
|----------|----------|
| Database failure | Streaming replication + automated failover |
| Service crash | Kubernetes auto-restart + PodDisruptionBudget |
| Region failure | Multi-region active-passive (Terraform managed) |
| Data corruption | Point-in-time recovery (PostgreSQL WAL) |
| Security breach | Automated credential rotation + namespace isolation |
| Agent rollback | One-click version rollback with full state restoration |

---

*This document is maintained by the Archon Orchestrator Agent and updated as the platform evolves.*
