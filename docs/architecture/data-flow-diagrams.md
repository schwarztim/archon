# Data Flow Diagrams — Archon Platform

> Sequence and flow diagrams for major subsystems.

---

## 1. Agent Execution Flow

```mermaid
sequenceDiagram
    participant U as User / Frontend
    participant GW as API Gateway<br/>(Middleware Stack)
    participant EX as ExecutionService
    participant LG as LangGraph Engine
    participant LLM as LLM Provider<br/>(via Router)
    participant DB as PostgreSQL
    participant R as Redis
    participant V as Vault

    U->>GW: POST /api/executions {agent_id, input}
    GW->>GW: Auth (JWT → Keycloak JWKS)
    GW->>GW: TenantMiddleware (extract tenant)
    GW->>GW: DLPMiddleware (scan input)
    GW->>GW: AuditMiddleware (log request)
    GW->>GW: RBAC (check execute permission)

    GW->>EX: create_execution(agent_id, input, tenant_id)
    EX->>DB: Load Agent definition
    DB-->>EX: Agent{definition, model, tools}
    EX->>DB: INSERT Execution (status=running)

    EX->>V: Fetch agent secrets (Vault KV)
    V-->>EX: Credentials bundle

    EX->>LG: execute_agent(definition, input, secrets)
    LG->>LG: create_graph(definition)
    LG->>LG: StateGraph: START → process

    LG->>LLM: process_node → LLM inference
    Note over LG,LLM: RoutingEngine selects<br/>optimal model+provider
    LLM-->>LG: LLM response

    LG->>LG: conditional_edge → respond
    LG->>LG: respond_node → format output

    LG-->>EX: AgentState{messages, output}
    EX->>DB: UPDATE Execution (status=completed, output)
    EX->>R: PUBLISH execution.completed event

    EX-->>GW: ExecutionResponse
    GW->>GW: DLPMiddleware (scan response)
    GW->>GW: AuditMiddleware (log response)
    GW-->>U: 201 {execution_id, output, status}
```

## 2. Model Routing Flow

```mermaid
sequenceDiagram
    participant Caller as Service / Agent
    participant RE as RoutingEngine
    participant RR as RoutingRuleService
    participant MR as ModelRegistry
    participant DB as PostgreSQL
    participant V as Vault
    participant P1 as Provider A<br/>(Azure OpenAI)
    participant P2 as Provider B<br/>(Fallback)

    Caller->>RE: route(prompt, context)
    RE->>RR: evaluate_rules(context)
    RR->>DB: Load RoutingRules (priority ordered)
    DB-->>RR: Rules[cost_limit, latency, model_pref...]
    RR-->>RE: Matching rule + target model

    RE->>MR: get_model(model_id)
    MR->>DB: Load ModelRegistryEntry
    DB-->>MR: Model{provider, endpoint, capabilities}
    MR-->>RE: Provider config

    RE->>V: Fetch provider API key
    V-->>RE: api_key

    RE->>P1: POST /chat/completions
    alt Provider A succeeds
        P1-->>RE: 200 {response}
    else Provider A fails
        P1-->>RE: 500 Error
        RE->>RE: Check fallback config
        RE->>P2: POST /chat/completions (fallback)
        P2-->>RE: 200 {response}
    end

    RE->>DB: INSERT TokenLedger (usage, cost)
    RE-->>Caller: RoutingResult{response, model, tokens, cost}
```

## 3. DLP (Data Loss Prevention) Flow

```mermaid
sequenceDiagram
    participant Req as Incoming Request
    participant DM as DLPMiddleware
    participant DE as DLPEngine
    participant DS as DLPService
    participant DB as PostgreSQL
    participant V as Vault

    Req->>DM: HTTP Request (body)
    DM->>DE: scan_content(body, tenant_id)

    DE->>DB: Load DLPPolicy (tenant_id, enabled)
    DB-->>DE: Policies[PII, credentials, PHI, custom...]

    loop Each active policy
        DE->>DE: Apply detector patterns
        DE->>DE: Regex + NER + custom rules
    end

    alt Findings detected
        DE->>DB: INSERT DLPScanResult
        DE->>DB: INSERT DLPDetectedEntity (per finding)

        alt Policy action = BLOCK
            DE-->>DM: BLOCKED (policy violation)
            DM-->>Req: 403 Forbidden + violation details
        else Policy action = REDACT
            DE->>DE: Redact sensitive content
            DE->>V: Store original in Vault (audit)
            DE-->>DM: Redacted content
            DM->>DM: Replace request body
            DM-->>Req: Continue with redacted body
        else Policy action = LOG
            DE-->>DM: ALLOWED (logged only)
            DM-->>Req: Continue unchanged
        end
    else No findings
        DE-->>DM: CLEAN
        DM-->>Req: Continue unchanged
    end
```

## 4. Authentication & Authorization Flow

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend SPA
    participant BE as Backend API
    participant KC as Keycloak
    participant SAML as External IdP<br/>(SAML)
    participant V as Vault
    participant DB as PostgreSQL

    Note over U,DB: === Standard OIDC Login ===
    U->>FE: Navigate to /login
    FE->>KC: Redirect to /auth/realms/archon/protocol/openid-connect/auth
    KC->>U: Login page (username/password + MFA)
    U->>KC: Credentials + MFA token
    KC->>KC: Validate credentials
    KC-->>FE: Authorization code (redirect)
    FE->>KC: Exchange code for tokens
    KC-->>FE: {access_token, refresh_token, id_token}

    Note over U,DB: === SAML Federated Login ===
    U->>FE: Navigate to /login (SSO tenant)
    FE->>BE: POST /api/v1/saml/login {tenant_id}
    BE->>DB: Load SAMLProvider config
    BE-->>FE: Redirect URL to external IdP
    FE->>SAML: SAML AuthnRequest
    SAML->>U: IdP login page
    U->>SAML: Credentials
    SAML-->>BE: POST /api/v1/saml/acs (SAML Response)
    BE->>BE: Validate SAML assertion + signature
    BE->>KC: Create/update Keycloak user
    BE-->>FE: {access_token, refresh_token}

    Note over U,DB: === API Request Auth ===
    FE->>BE: GET /api/agents (Authorization: Bearer <token>)
    BE->>BE: Auth middleware: extract JWT
    BE->>KC: Fetch JWKS (cached 5 min)
    BE->>BE: Validate JWT signature + expiry
    BE->>BE: Extract claims: sub, roles, tenant_id
    BE->>BE: TenantMiddleware: set tenant context
    BE->>BE: RBAC: check_permission(user, action, resource)

    alt Authorized
        BE->>DB: Query with tenant isolation
        BE-->>FE: 200 {data}
    else Unauthorized
        BE-->>FE: 403 Forbidden
    end

    Note over U,DB: === SCIM Provisioning ===
    SAML->>BE: POST /api/v1/scim/v2/Users {user}
    BE->>BE: Validate SCIM bearer token
    BE->>DB: Create/update UserIdentity
    BE->>KC: Sync user to Keycloak realm
    BE-->>SAML: 201 {scim_user}
```

## 5. Tenant Isolation Flow

```mermaid
graph TD
    A[Request arrives] --> B{TenantMiddleware}
    B -->|Extract tenant_id from JWT| C{Tenant exists?}
    C -->|No| D[403 Forbidden]
    C -->|Yes| E[Set tenant context]
    E --> F{Quota check}
    F -->|Exceeded| G[429 Rate Limited]
    F -->|OK| H[Route handler]
    H --> I[Service layer]
    I --> J["DB Query with WHERE tenant_id = ?"]
    J --> K[PostgreSQL RLS / app-level filter]
    K --> L[Response]
    L --> M[DLPMiddleware scans output]
    M --> N[AuditMiddleware logs]

    style B fill:#ff9800,color:#fff
    style J fill:#f44336,color:#fff
    style K fill:#f44336,color:#fff
```

## 6. Worker Background Processing

```mermaid
graph LR
    subgraph "Triggers"
        T1[Schedule: SentinelScan]
        T2[Event: Cost Reconciliation]
        T3[Event: DLP Scan Queue]
        T4[Event: Deployment Pipeline]
        T5[Event: Credential Rotation]
    end

    subgraph "Worker Process"
        W[Worker Main Loop]
        W1[SentinelScan Task]
        W2[Cost Reconcile Task]
        W3[DLP Batch Scan Task]
        W4[Deploy Task]
        W5[Secret Rotate Task]
    end

    subgraph "External"
        DB[(PostgreSQL)]
        R[(Redis)]
        V[Vault]
    end

    T1 --> R
    T2 --> R
    T3 --> R
    T4 --> R
    T5 --> R

    R --> W
    W --> W1
    W --> W2
    W --> W3
    W --> W4
    W --> W5

    W1 --> DB
    W2 --> DB
    W3 --> DB
    W4 --> V
    W5 --> V
```
