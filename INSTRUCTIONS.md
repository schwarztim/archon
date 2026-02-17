# OpenAiria Build Instructions (Enterprise Edition)

> **Single source of truth for the entire agent swarm — Stage 2: Enterprise Hardening.**

---

## Vision

Build a complete, production-ready, enterprise-grade open-source AI orchestration and governance platform that matches or exceeds every capability of Airia (airia.com) and leading commercial platforms. This is a flagship benchmark demonstrating the full power of agentic AI systems.

## Non-Negotiables

1. **Every feature must be implemented or surpassed** — nothing half-baked, every tool functional
2. **Enterprise-ready from day one** — security-first, observable, compliant, scalable, auditable
3. **100% open-source** — Apache 2.0 license, no proprietary dependencies
4. **Model-agnostic** — support every major LLM provider + local inference
5. **Zero data leakage by design** — all data stays within the deployment boundary
6. **Enterprise Identity** — OAuth 2.0, SAML 2.0, OIDC, SCIM 2.0, MFA — all functional, not stubbed
7. **Secrets Management** — HashiCorp Vault for all credentials, keys, certificates — zero plaintext anywhere
8. **User Management** — RBAC + ABAC, SCIM provisioning, directory sync, access reviews, audit trails
9. **Every Connector Works** — Full OAuth flows, real API integration, credential storage in Vault, health monitoring

## Enterprise Cross-Cutting Concerns

> **EVERY agent must implement or integrate with these. They are not optional.**

### Authentication & SSO (Agent-01)
- All API endpoints require authentication (except /health, /docs, /.well-known)
- Supported auth methods: JWT (via Keycloak OIDC), SAML 2.0, API Keys
- Token validation: JWKS-based, cached, <5ms per request
- SAML flows: SP-initiated (redirect binding), IdP-initiated (POST binding)
- MFA: TOTP, WebAuthn/FIDO2, SMS (configurable per tenant)
- Session management: Redis-backed, idle timeout, absolute timeout, concurrent limits

### Secrets Management (Agent-00)
- ALL credentials stored in HashiCorp Vault — never in database, env vars, or config files
- SDK: `from backend.app.secrets.manager import SecretsManager` — all services use this
- Credential injection: at request time from Vault, cached with TTL
- Rotation: automatic on schedule, with webhook notification to dependents
- Transit encryption: for data-at-rest encryption without exposing keys
- PKI: internal mTLS certificates issued by Vault

### User & Access Management (Agent-01)
- RBAC: 7 predefined roles (platform_admin → viewer), custom roles per tenant
- ABAC: OPA sidecar for complex access decisions
- SCIM 2.0: bi-directional user/group sync with enterprise IdPs
- User lifecycle: invite → activate → suspend → deactivate → delete
- Access reviews: quarterly reviews, just-in-time elevation, separation of duties

### Tenant Isolation (Agent-23)
- Row-Level Security (RLS) on every database table
- Vault namespace per tenant (or path-prefix isolation)
- Kubernetes namespace isolation (Enterprise tier)
- Per-tenant IdP, SCIM, branding, feature flags

---

## Agent Swarm Rules

Every agent MUST output:
1. **Code** — in the correct directory, following project conventions
2. **Tests** — pytest for backend, Playwright for frontend, integration tests
3. **Documentation** — Markdown + OpenAPI specs where applicable
4. **PR Description** — structured summary of changes, rationale, and test results

### Enterprise Mandates (NEW — Stage 2)

Every agent MUST also:
1. **Use SecretsManager** — All credentials accessed via `backend.app.secrets.manager.SecretsManager`. Never raw Vault calls, never env vars, never hardcoded.
2. **Respect Auth Context** — Every API endpoint receives `request.state.user` (AuthenticatedUser) and `request.state.tenant_id`. Use them for authorization and RLS.
3. **Log to Audit Trail** — All state-changing operations (create, update, delete, execute, approve, rotate) produce an AuditLog entry with actor, action, resource, result.
4. **Enforce RBAC** — Every endpoint checks permissions via `check_permission(user, action, resource)`. No endpoint is publicly accessible except health probes.
5. **Isolate by Tenant** — All queries include `tenant_id` filter (or rely on RLS). Cross-tenant data access is a Critical security bug.
6. **Encrypt Sensitive Data** — Use Vault Transit engine for encrypting sensitive fields at rest (PII, credentials metadata, document content).
7. **Validate Inputs** — All user inputs validated via Pydantic models. No raw string interpolation in queries or LLM prompts.

### Communication Protocol

- All agents communicate via shared `/workspace` directory
- Central state file: `swarm-state.json` tracks progress, blockers, dependencies
- Conflict resolution escalates to the Orchestrator Agent
- Every agent reads `INSTRUCTIONS.md` and `ARCHITECTURE.md` before starting work

### Quality Gates

- **License compliance**: Only open-source, permissive licenses (Apache 2.0, MIT, BSD)
- **Security scan**: Every PR must pass automated DLP and vulnerability scan
- **Performance**: < 200ms p95 latency for routing decisions
- **Test coverage**: Minimum 80% for all new code
- **Documentation**: Every public API must have OpenAPI spec + usage examples

---

## Build-Correctness Enforcement (MANDATORY)

> See `docs/BUILD_CORRECTNESS.md` for full details. These are non-negotiable.

Before ANY agent writes code, the Orchestrator MUST complete:
1. **Contract-First**: Generate `contracts/openapi.yaml` — locked API spec, immutable to agents
2. **Binding ADRs**: Write `docs/ADR/*.md` — canonical patterns for error handling, auth, logging, pagination, config
3. **Interface Stubs**: Create `backend/app/interfaces/` — abstract base classes + shared Pydantic models
4. **Integration Test Contracts**: Write `tests/integration/` — failing boundary tests that define cross-agent contracts
5. **Golden Path Examples**: Create `docs/golden-path/` — one complete reference implementation of every pattern
6. **Self-Verification Checklist**: Create `docs/SELF_VERIFICATION_CHECKLIST.md` — mandatory pre-completion gate

During build, after EVERY agent output:
7. **Build Verification Pipeline**: Run the agent's verify command + `node ~/Projects/copilot-sdd/dist/cli.js check` — all weight-5 goals must pass
8. **Dependency-Ordered Execution**: No agent starts until dependencies are completed AND output-locked
9. **Regression Guardian**: Full test suite re-run — if Agent X breaks Agent Y's tests, Agent X is blocked
10. **Capture Learnings**: After any failure or unexpected fix, run `node ~/Projects/copilot-sdd/dist/cli.js learn --type pitfall --summary "description"` to persist the knowledge for future sessions

### Phase 0: Vertical Slice (NEW — before Phase 1)
> Prove the entire architecture works end-to-end with ONE feature

Agent-01 builds a single complete vertical slice: "Create and Execute a Simple 2-Node Agent"
- Frontend: drag 2 nodes, connect, click Run
- API: POST /agents, POST /execute
- Auth: JWT validation
- LangGraph: execute 2-node state machine
- WebSocket: stream output
- Database: persist agent + execution
- Audit: log events
- Cost: record tokens
- Docker: `docker-compose up` runs everything

This slice MUST stay green at all times. `make test-slice` is the project heartbeat.

---

## Build Phases

Agents execute in parallel where possible. Dependencies are explicit.

### Phase 0: Foundation (Orchestrator + Agent-00)
> Contracts, ADRs, interface stubs, golden paths, vertical slice, AND secrets vault

| Agent | Responsibility | Dependencies |
|-------|---------------|--------------|
| Orchestrator | API contracts, ADRs, stubs, golden paths | None |
| Agent-00 | Secrets Management & Credential Vault | None |

> **Agent-00 is NEW in Stage 2.** It runs alongside the Orchestrator in Phase 0 because every subsequent agent depends on the SecretsManager SDK and Vault integration.

### Phase 1: Core Platform (Agents 01–06)
> Foundation — must complete before anything else depends on it

| Agent | Responsibility | Dependencies |
|-------|---------------|--------------|
| Agent-01 | Core Backend + Enterprise Identity (OAuth/SAML/SCIM/MFA) | Agent-00 |
| Agent-02 | No-Code Builder UI + SSO Login + RBAC-Gated UI | Agent-01, Agent-00 |
| Agent-03 | Natural Language to Agent Wizard (Auth-Aware) | Agent-01, Agent-00 |
| Agent-04 | Template Library + Marketplace Auth | Agent-01, Agent-02 |
| Agent-05 | Sandbox + Arena Mode + Secrets Injection | Agent-01, Agent-00 |
| Agent-06 | Version Control + Signed Versions + Secrets Tracking | Agent-01, Agent-00 |

### Phase 2: Operations & Cost (Agents 07–09, 23)
> Intelligence layer — routing, lifecycle, cost tracking, multi-tenancy, billing

| Agent | Responsibility | Dependencies |
|-------|---------------|--------------|
| Agent-07 | Intelligent Router + Auth-Aware Routing + Vault Credentials | Agent-01, Agent-00 |
| Agent-08 | Lifecycle Manager + Deployment Credential Rotation | Agent-01, Agent-07, Agent-00 |
| Agent-09 | Cost Engine + Identity-Based Attribution + Financial Governance | Agent-01, Agent-07, Agent-00 |
| Agent-23 | Multi-Tenant + Per-Tenant IdP + SCIM + Vault Namespaces + Billing | Agent-01, Agent-09, Agent-00 |

### Phase 3: Security & Governance (Agents 10–12, 18, 20, 21)
> Trust layer — adversarial testing, DLP, compliance, shadow AI, MCP security

| Agent | Responsibility | Dependencies |
|-------|---------------|--------------|
| Agent-10 | Red-Teaming + Auth Bypass Testing + Credential Leak Detection | Agent-01, Agent-05, Agent-00 |
| Agent-11 | DLP + Credential Scanning + Vault-Aware Redaction + NL Policy Engine | Agent-01, Agent-07, Agent-00 |
| Agent-12 | Governance + Identity Governance + Access Reviews + Compliance | Agent-01, Agent-02, Agent-00 |
| Agent-18 | SentinelScan + SSO Discovery + Credential Exposure Scanning | Agent-01, Agent-12, Agent-00 |
| Agent-20 | MCP Security + Tool-Level OAuth Scopes + Vault Integration | Agent-01, Agent-11, Agent-15, Agent-00 |
| Agent-21 | Security Proxy + SAML Termination + Credential Injection | Agent-01, Agent-07, Agent-00 |

### Phase 4: Integrations & Data (Agents 13–14, 19)
> Connectivity — external data, document processing, agent interop

| Agent | Responsibility | Dependencies |
|-------|---------------|--------------|
| Agent-13 | Connector Hub + Full OAuth Flows + Vault Credential Storage | Agent-01, Agent-00 |
| Agent-14 | DocForge + Auth-Gated Documents + Encrypted Embeddings | Agent-01, Agent-13, Agent-00 |
| Agent-19 | A2A Protocol + Federated OAuth + mTLS Credential Exchange | Agent-01, Agent-07, Agent-13, Agent-00 |

### Phase 5: Deployment & UX (Agents 15–17, 22)
> Delivery — interactive UIs, mobile, marketplace, production deployment

| Agent | Responsibility | Dependencies |
|-------|---------------|--------------|
| Agent-15 | Live Components + Session-Bound Auth + Component-Level RBAC | Agent-01, Agent-02, Agent-00 |
| Agent-16 | Mobile SDK + Biometric + SAML Auth + Secure Enclave Secrets | Agent-01, Agent-00 |
| Agent-17 | K8s/Terraform + Vault Operator + Cert-Manager + SAML IdP Config | Agent-01, all others, Agent-00 |
| Agent-22 | Marketplace + Publisher Auth + Signed Packages + License Enforcement | Agent-01, Agent-02, Agent-00 |

### Phase 6: Advanced Features (Agents 24–25)
> Differentiators — features no competitor offers

| Agent | Responsibility | Dependencies |
|-------|---------------|--------------|
| Agent-24 | Federated Agent Mesh + Federated Identity + Cross-Org Vault | Agent-01, Agent-17, Agent-19, Agent-00 |
| Agent-25 | Edge Runtime + Offline Auth Tokens + Local Secret Store | Agent-01, Agent-17, Agent-00 |

### Phase 7: Validation & Polish (Master Validator)
> Final gate — E2E testing across 50 enterprise scenarios

---

## Success Criteria

- [ ] Production deployment in < 4 hours on any cloud or on-prem
- [ ] Handles 10k+ concurrent agents
- [ ] Zero data leakage verified by automated testing
- [ ] Beats commercial platforms on cost (open models + routing) and transparency
- [ ] Complete documentation site with getting started, API reference, and tutorials
- [ ] 95%+ feature parity with leading commercial AI orchestration platforms
- [ ] **OAuth 2.0 / OIDC SSO works end-to-end with Okta, Azure AD, and Google**
- [ ] **SAML 2.0 SSO works with at least 2 enterprise IdPs**
- [ ] **SCIM 2.0 provisioning syncs users/groups from IdP to platform**
- [ ] **MFA (TOTP + WebAuthn) enforced for admin roles**
- [ ] **All credentials stored in Vault — zero plaintext secrets in codebase, logs, or env vars**
- [ ] **Automatic credential rotation works with webhook notification**
- [ ] **RBAC enforces correct access at every endpoint (verified by red-team Agent-10)**
- [ ] **Tenant isolation verified: tenant A cannot access tenant B's data (RLS + Vault)**
- [ ] **Audit trail is tamper-evident (hash chain) and captures every state change**
- [ ] **All 60+ connectors authenticate via OAuth/API-key with credentials in Vault**

---

## Master Validator Agent Prompt

> Run last, after all other agents have completed their work.

```
You are the final gatekeeper. Run full E2E tests across 50 enterprise scenarios.
If any feature is <95% match to the target feature set, reject and send back
to the responsible agent with exact gaps documented.

Test categories:
1. Agent creation (no-code, low-code, pro-code)
2. Multi-model routing under load
3. Security boundary enforcement
4. Data connector reliability
5. Cost tracking accuracy
6. Deployment automation
7. Mobile SDK functionality
8. Performance under 10k concurrent agents
9. Compliance audit trail completeness
10. Disaster recovery and rollback
```
