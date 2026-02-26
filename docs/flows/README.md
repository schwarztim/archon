# Archon Platform — Flow Documentation

Comprehensive end-to-end documentation of all major flows in the Archon enterprise AI agent platform, traced from actual source code.

## Flows Index

| # | Flow | File | Key Components |
|---|------|------|----------------|
| 01 | [Agent Execution](./01-agent-execution.md) | Execution pipeline | `ExecutionService`, `LangGraphEngine`, WebSocket streaming |
| 02 | [Model Routing](./02-model-routing.md) | Intelligent model selection | `ModelRouterService`, `_CircuitBreaker`, `RoutingDecision` |
| 03 | [DLP](./03-dlp.md) | Data Loss Prevention | `DLPMiddleware`, `DLPService` (4-layer), 200+ secret patterns |
| 04 | [Auth & Authorization](./04-auth.md) | Authentication & RBAC | JWT (HS256/RS256), Keycloak OIDC, SAML, `TenantMiddleware` |
| 05 | [Lifecycle & Deployment](./05-lifecycle-deployment.md) | Agent lifecycle + infra | `LifecycleService`, `DeploymentService`, state machine |
| 06 | [Cost Engine](./06-cost-engine.md) | Token economics | `CostService`, token ledger, budgets, chargeback |
| 07 | [Connector Hub](./07-connector-hub.md) | External integrations | `ConnectorService`, OAuth flows, Vault credentials |
| 08 | [A2A Protocol](./08-a2a-protocol.md) | Agent-to-Agent federation | `A2AService`, partner trust, federated OAuth, DLP |
| 09 | [Agent Mesh](./09-agent-mesh.md) | Cross-org mesh network | `MeshService`, topology, federation agreements |
| 10 | [Edge Runtime](./10-edge-runtime.md) | Edge device management | `EdgeService`, offline auth, sync, OTA updates |
| 11 | [Security Proxy](./11-security-proxy.md) | AI provider proxy | `SecurityProxyService`, SAML, credential injection |
| 12 | [MCP Security](./12-mcp-security.md) | MCP tool security | `MCPSecurityService`, OAuth scopes, sandbox, DLP |

## Architecture Layers

```
┌─────────────────────────────────────────────────────┐
│                    API Routes                        │
│  agents · executions · router · cost · mesh · edge   │
├─────────────────────────────────────────────────────┤
│                   Middleware                          │
│  TenantMiddleware → DLPMiddleware → Auth → RBAC     │
├─────────────────────────────────────────────────────┤
│                   Services                           │
│  ExecutionService · ModelRouterService · DLPService  │
│  CostService · MeshService · EdgeService · A2AService│
├─────────────────────────────────────────────────────┤
│                   LangGraph Engine                   │
│  StateGraph → process_node → respond_node → END     │
├─────────────────────────────────────────────────────┤
│                Infrastructure                        │
│  PostgreSQL · Vault · Keycloak · Redis              │
└─────────────────────────────────────────────────────┘
```

## Cross-Cutting Concerns

| Concern | Implementation |
|---------|---------------|
| **Tenant Isolation** | `TenantMiddleware` stamps `request.state.tenant_id`; all queries scoped |
| **RBAC** | `check_permission(user, resource, action)` in `middleware/rbac.py` |
| **Audit Logging** | `AuditLogService.create()` on every state change |
| **DLP** | Middleware + service layers; 200+ secret + 15 PII patterns |
| **Secrets** | `VaultSecretsManager` — credentials never in request bodies |
| **Circuit Breaker** | `_CircuitBreaker` in router — 3 failures → open → 60s reset |

## Generated
Auto-generated from source code analysis. Last updated: $(date -u +%Y-%m-%dT%H:%M:%SZ)
