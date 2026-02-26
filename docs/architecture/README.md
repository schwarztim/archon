# Archon Architecture Documentation

> Comprehensive C4 and data flow diagrams for the Archon Enterprise AI Agent Orchestration Platform.

---

## 📐 Diagrams Index

| # | Diagram | File | Description |
|---|---------|------|-------------|
| 1 | [C4 System Context](c4-system-context.md) | `c4-system-context.md` | Level 1 — Archon platform boundary with all external actors and systems (users, Keycloak, Vault, PostgreSQL, Redis, LLM providers, etc.) |
| 2 | [C4 Container](c4-container.md) | `c4-container.md` | Level 2 — All deployable containers: Frontend, Backend API, Worker, PostgreSQL, Redis, Vault, Keycloak, Prometheus, Grafana + middleware stack |
| 3 | [C4 Component — Backend](c4-component-backend.md) | `c4-component-backend.md` | Level 3 — Backend internals: 40 route modules → 47 services → 70+ SQLModel tables grouped by domain (Core, Security, Governance, Integration, Infrastructure) |
| 4 | [Agent Dependency Graph](agent-dependency-graph.md) | `agent-dependency-graph.md` | All 26 build agents across 7 phases with full dependency graph, phase breakdown, and agent↔backend mapping |
| 5 | [Data Flow Diagrams](data-flow-diagrams.md) | `data-flow-diagrams.md` | Sequence diagrams for: Agent Execution, Model Routing, DLP processing, Authentication & Authorization, Tenant Isolation, Worker background processing |
| 6 | [Integration Map](integration-map.md) | `integration-map.md` | All external connections: protocols, ports, auth methods, Vault secret paths, connector types |
| 7 | [Frontend → API Mapping](frontend-api-mapping.md) | `frontend-api-mapping.md` | 27 React pages mapped to their backend API routes with detailed endpoint table |

---

## Platform Overview

**Archon** is an enterprise AI agent orchestration platform featuring:

- **40 route modules** exposing ~265 API endpoints
- **47 service files** with domain-specific business logic
- **32 model files** defining 70+ SQLModel (PostgreSQL) tables
- **7 middleware layers**: CORS → Metrics → Tenant → DLP → Audit → Auth → RBAC
- **LangGraph engine** for agent execution (StateGraph: process → respond)
- **26 build agents** organized in 7 phases (Foundation → Validate)
- **27 frontend pages** (React 19 + TypeScript)
- **10 Docker Compose services**: postgres, redis, backend, frontend, vault, keycloak, vault-init, prometheus, grafana, worker
- **Infrastructure-as-Code**: Helm charts, Terraform (AWS/Azure/GCP), ArgoCD GitOps, Kubernetes manifests

## Domain Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ARCHON PLATFORM                          │
├─────────────┬─────────────┬─────────────┬─────────────┬─────────┤
│    Core     │  Security   │ Governance  │ Integration │  Infra  │
├─────────────┼─────────────┼─────────────┼─────────────┼─────────┤
│ agents      │ auth        │ governance  │ connectors  │ deploy  │
│ executions  │ saml        │ audit_logs  │ a2a         │ lifecyc │
│ wizard      │ sso         │ sentinelscan│ mcp         │ cost    │
│ templates   │ scim        │             │ mcp_interac │ router  │
│ sandbox     │ secrets     │             │ mesh        │ tenancy │
│ versioning  │ redteam     │             │ edge        │ tenants │
│ workflows   │ dlp         │             │ docforge    │ admin   │
│ models      │ mcp_security│             │ mobile      │ setting │
│             │ sec_proxy   │             │ marketplace │         │
└─────────────┴─────────────┴─────────────┴─────────────┴─────────┘
```

## How to View Diagrams

These diagrams use [Mermaid](https://mermaid.js.org/) syntax. View them:

1. **GitHub** — renders Mermaid in markdown automatically
2. **VS Code** — install the "Mermaid Markdown Syntax Highlighting" extension
3. **Mermaid Live Editor** — paste at [mermaid.live](https://mermaid.live)
4. **CLI** — use `mmdc` (Mermaid CLI) to render to PNG/SVG

---

*Generated from codebase analysis. Last updated based on scan of 40 route modules, 47 services, 32 model files, 7 middleware, 27 frontend pages, and docker-compose.yml.*
