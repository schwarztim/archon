# C4 Container Diagram — Archon Platform

> Level 2 C4 diagram showing all containers (deployable units) within the Archon platform.

```mermaid
C4Container
    title Archon Platform — Container Diagram

    Person(user, "User", "Admin / Developer / End User")

    Container_Boundary(archon, "Archon Platform") {
        Container(frontend, "Frontend SPA", "React 19, TypeScript, Vite", "27 pages: Agent builder, dashboards, governance, marketplace, DLP, cost, SSO config, etc.")
        Container(backend, "Backend API", "Python, FastAPI, SQLModel", "40 route modules, 47 services, 7 middleware layers, REST + WebSocket API")
        Container(worker, "Background Worker", "Python, asyncio", "Async task processing: scans, deployments, cost reconciliation, DLP scans")
        Container(langgraph_engine, "LangGraph Engine", "LangGraph, LangChain", "Agent execution engine: process → respond graph with state management")
    }

    Container_Boundary(data, "Data Layer") {
        ContainerDb(postgres, "PostgreSQL 16", "Relational DB", "32 SQLModel tables: agents, executions, tenants, audit logs, DLP, governance, etc.")
        ContainerDb(redis, "Redis 7", "In-memory store", "Session cache, pub/sub, rate limiting, worker queues")
    }

    Container_Boundary(security, "Security & Identity") {
        Container(keycloak, "Keycloak 26", "Java, Quarkus", "OAuth 2.0 / OIDC / SAML 2.0 identity provider with MFA")
        Container(vault, "HashiCorp Vault 1.15", "Go", "Secrets management, credential rotation, PKI, transit encryption")
        Container(vault_init, "Vault Init", "Shell script", "Bootstrap: creates KV engines, policies, approle for backend")
    }

    Container_Boundary(observability, "Observability") {
        Container(prometheus, "Prometheus", "Go", "Metrics scraping from backend /metrics endpoint")
        Container(grafana, "Grafana", "Go, React", "Dashboards: request rates, latencies, error rates, cost metrics")
    }

    Rel(user, frontend, "Uses", "HTTPS :3000")
    Rel(frontend, backend, "API calls", "HTTPS :8000 /api/*")
    Rel(backend, postgres, "Reads/writes", "asyncpg :5432")
    Rel(backend, redis, "Cache, pub/sub", "Redis :6379")
    Rel(backend, keycloak, "JWT validation, JWKS", "HTTP :8180")
    Rel(backend, vault, "Secret ops", "HTTP :8200")
    Rel(backend, langgraph_engine, "Executes agents", "In-process")
    Rel(worker, postgres, "Reads/writes", "asyncpg :5432")
    Rel(worker, redis, "Consumes jobs", "Redis :6379")
    Rel(worker, vault, "Fetches secrets", "HTTP :8200")
    Rel(vault_init, vault, "Bootstraps", "HTTP :8200")
    Rel(prometheus, backend, "Scrapes /metrics", "HTTP :8000")
    Rel(grafana, prometheus, "Queries", "PromQL :9090")
```

## Container Details

| Container | Technology | Port | Purpose |
|-----------|-----------|------|---------|
| **Frontend** | React 19, TypeScript, Vite | 3000 | 27-page SPA: agent builder, governance, DLP, cost, marketplace |
| **Backend API** | FastAPI, SQLModel, Python | 8000 | 40 route modules with 7 middleware layers (Auth → Tenant → RBAC → DLP → Audit → Metrics → CORS) |
| **Worker** | Python asyncio | — | Background tasks: SentinelScan, cost reconciliation, DLP scans, deployments |
| **LangGraph Engine** | LangGraph, LangChain | — | In-process agent execution: StateGraph with process → respond pipeline |
| **PostgreSQL** | PostgreSQL 16 | 5432 | 70+ SQLModel tables across 32 model files |
| **Redis** | Redis 7 | 6379 | Session cache, WebSocket pub/sub, rate limiting, task queues |
| **Keycloak** | Keycloak 26 | 8180 | OIDC/SAML provider, user federation, MFA, realm management |
| **Vault** | HashiCorp Vault 1.15 | 8200 | KV secrets, credential rotation, PKI, transit encryption |
| **Vault Init** | Shell script | — | One-shot bootstrap of Vault engines, policies, and approle |
| **Prometheus** | Prometheus | 9090 | Metrics scraping and alerting |
| **Grafana** | Grafana | 3001 | Observability dashboards |

## Middleware Stack (Request Processing Order)

```mermaid
graph TD
    A[Incoming Request] --> B[CORS Middleware]
    B --> C[MetricsMiddleware]
    C --> D[TenantMiddleware]
    D --> E[DLPMiddleware]
    E --> F[AuditMiddleware]
    F --> G[Auth / JWT Validation]
    G --> H[RBAC Permission Check]
    H --> I[Route Handler]
    I --> J[Service Layer]
    J --> K[Model / Database]
```
