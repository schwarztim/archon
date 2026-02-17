# OpenAiria Agent Swarm Overview (Enterprise Edition)

> Coordinated multi-agent system for building the OpenAiria platform.
> 26 specialized agents + 1 Master Validator = 27 total.
> Stage 2: Enterprise Hardening — OAuth, SAML, SCIM, Vault, RBAC, Tenant Isolation.

---

## Swarm Architecture

```
                    +-------------------------+
                    |   Orchestrator Agent     |
                    |   (MAIN_PROMPT.md)       |
                    |                          |
                    |   Phase 0: Foundation    |
                    |   Contracts, ADRs,       |
                    |   Stubs, Golden Path,    |
                    |   Agent-00 (Vault)       |
                    +-----------+-------------+
                                |
         +----------------------+----------------------+
         |                      |                      |
    +----v----+            +----v----+            +----v----+
    | Phase 1 |            | Phase 2 |            | Phase 3 |
    | Core    +----------->+ Ops     +----------->+Security |
    | 01-06   |            | 07-09,23|            |10-12,18 |
    +---------+            +---------+            |  20,21  |
                                                  +----+----+
         +----------------------+----------------------+
         |                      |                      |
    +----v----+            +----v----+            +----v----+
    | Phase 4 |            | Phase 5 |            | Phase 6 |
    | Data    +----------->+ Deploy  +----------->+Advanced |
    | 13,14,19|            | 15-17,22|            | 24, 25  |
    +---------+            +---------+            +----+----+
                                                       |
                                                  +----v----+
                                                  | Phase 7 |
                                                  |Validate |
                                                  | Master  |
                                                  +---------+
```

## Agent Registry

| ID | Name | Phase | Role | Prompt File |
|----|------|-------|------|-------------|
| **00** | **Secrets Management & Credential Vault** | **0** | **Vault integration, SecretsManager SDK, rotation, PKI** | `agent-00-secrets-vault.md` |
| 01 | Core Backend & Enterprise Identity | 1 | FastAPI + OAuth/SAML/SCIM/MFA/RBAC + LangGraph | `agent-01-core-backend.md` |
| 02 | UI Builder + Enterprise Frontend | 1 | React Flow canvas + SSO login + RBAC-gated UI | `agent-02-ui-builder.md` |
| 03 | NL Wizard (Auth-Aware) | 1 | Natural language to agent (secrets-aware) | `agent-03-nl-wizard.md` |
| 04 | Template Curator + Marketplace Auth | 1 | Template library with credential manifests | `agent-04-templates.md` |
| 05 | Sandbox + Arena + Secrets Injection | 1 | Isolated testing with dynamic Vault secrets | `agent-05-sandbox.md` |
| 06 | Version Control + Signed Versions | 1 | Git-like versioning with secrets tracking | `agent-06-versioning.md` |
| 07 | Intelligent Router + Auth-Aware Routing | 2 | Dynamic model routing with Vault credentials | `agent-07-router.md` |
| 08 | Lifecycle Manager + Credential Rotation | 2 | Deployment strategies with Vault integration | `agent-08-lifecycle.md` |
| 09 | Cost Engine + Identity Attribution | 2 | Token ledger with per-user/tenant attribution | `agent-09-cost-engine.md` |
| 10 | Red-Team + Auth Bypass Testing | 3 | Adversarial testing including auth attacks | `agent-10-redteam.md` |
| 11 | DLP + Credential Scanning + NL Policy | 3 | DLP with Vault-aware redaction | `agent-11-dlp-guardrails.md` |
| 12 | Governance + Identity Governance | 3 | Compliance + access reviews + risk | `agent-12-governance.md` |
| 13 | Connector Hub + Full OAuth Flows | 4 | 60+ connectors with Vault credential storage | `agent-13-connectors.md` |
| 14 | DocForge + Encrypted Embeddings | 4 | Document processing with auth-gated access | `agent-14-docforge.md` |
| 15 | Live Components + Session-Bound Auth | 5 | Embedded UIs with component-level RBAC | `agent-15-mcp-interactive.md` |
| 16 | Mobile SDK + Biometric/SAML Auth | 5 | Flutter SDK with secure enclave secrets | `agent-16-mobile.md` |
| 17 | Deployment + Vault Operator + Cert-Manager | 5 | K8s + Terraform + full Vault/Keycloak deploy | `agent-17-deployment.md` |
| 18 | SentinelScan + SSO Discovery | 3 | Shadow AI discovery via SSO log analysis | `agent-18-sentinelscan.md` |
| 19 | A2A Protocol + Federated OAuth | 4 | Agent-to-Agent with mTLS + OAuth federation | `agent-19-a2a-protocol.md` |
| 20 | MCP Security + Tool-Level OAuth | 3 | MCP governance with Vault integration | `agent-20-mcp-security.md` |
| 21 | Security Proxy + SAML Termination | 3 | AI security proxy with credential injection | `agent-21-security-proxy.md` |
| 22 | Marketplace + Publisher Auth + Signed Pkgs | 5 | Open marketplace with license enforcement | `agent-22-marketplace.md` |
| 23 | Multi-Tenant + Per-Tenant IdP + Billing | 2 | Tenant isolation + SCIM + Vault namespaces | `agent-23-multi-tenant.md` |
| 24 | Federated Agent Mesh + Federated Identity | 6 | Cross-org collaboration with Vault isolation | `agent-24-agent-mesh.md` |
| 25 | Edge Runtime + Offline Auth + Local Secrets | 6 | Offline-first with device-bound auth | `agent-25-edge-runtime.md` |
| MV | Master Validator | 7 | E2E testing + enterprise auth verification | See INSTRUCTIONS.md |

## Dependency Graph (Detailed — Enterprise Edition)

```
Phase 0 (Orchestrator + Agent-00) ---- MUST COMPLETE FIRST
  |
  +---> Agent-00 (Secrets Vault) ---- ALL agents depend on this
  |       |
  v       v
Agent-01 (Core Backend + Enterprise Identity) -------------------------+
  |                                                                     |
  +---> Agent-02 (UI + SSO + RBAC) -------> Agent-04 (Templates)       |
  |        |                                                            |
  |        +------------> Agent-12 (Governance + Identity Gov)          |
  |        |                                                            |
  |        +------------> Agent-15 (Live Components + Session Auth)     |
  |        |                                                            |
  |        +------------> Agent-22 (Marketplace + Publisher Auth)       |
  |                                                                     |
  +---> Agent-03 (NL Wizard + Auth-Aware Codegen)                      |
  |                                                                     |
  +---> Agent-05 (Sandbox + Secrets Injection) --> Agent-10 (Red-Team)  |
  |                                                                     |
  +---> Agent-06 (Versioning + Signed Versions)                        |
  |                                                                     |
  +---> Agent-07 (Router + Auth-Aware + Vault Creds)                   |
  |        +----> Agent-08 (Lifecycle + Credential Rotation)           |
  |        +----> Agent-09 (Cost + Identity Attribution)               |
  |        +----> Agent-11 (DLP + Credential Scanning)                 |
  |        +----> Agent-21 (Security Proxy + SAML Termination)         |
  |                                                                     |
  +---> Agent-13 (Connectors + OAuth Flows + Vault Storage)            |
  |        +----> Agent-14 (DocForge + Encrypted Embeddings)           |
  |                                                                     |
  +---> Agent-16 (Mobile + Biometric/SAML Auth)                        |
  |                                                                     |
  +---> Agent-18 (SentinelScan + SSO Discovery) <--- Agent-12          |
  |                                                                     |
  +---> Agent-19 (A2A + Federated OAuth) <--- Agent-07, Agent-13       |
  |                                                                     |
  +---> Agent-20 (MCP Security + OAuth Scopes) <--- Agent-15, Agent-11 |
  |                                                                     |
  +---> Agent-23 (Multi-Tenant + Per-Tenant IdP + SCIM) <--- Agent-09  |
  |                                                                     |
  +---> Agent-17 (Deployment + Vault Operator + Cert-Manager)          |
                     |         <--- ALL AGENTS -------------------------+
           +---------+---------+
           |                   |
     Agent-24             Agent-25
     (Federated Mesh      (Edge Runtime +
      + Federated ID)      Offline Auth)
           |                   |
           +---------+---------+
                     |
              Master Validator
              (+ Enterprise Auth
               Verification)
```

## Communication Protocol

### State File: `swarm-state.json`
- Updated by each agent on status change
- Read by Orchestrator for dependency resolution
- Conflict detection via optimistic locking (version field)

### Status Updates
```
[AGENT-XX] [STATUS] [TIMESTAMP]
Summary: <one-line summary>
Files Changed: <list>
Tests: <pass/fail count>
Blockers: <list or "none">
Next: <what the agent will do next>
```

### Conflict Resolution
1. API contract disputes -> contracts/openapi.yaml is the single source of truth
2. Pattern disputes -> docs/ADR/*.md is binding
3. Shared resources -> Orchestrator assigns ownership
4. Tech stack disagreements -> defer to ARCHITECTURE.md
5. Test failures -> responsible agent fixes within 2 iterations

### Build-Correctness Enforcement
- Every agent MUST read contracts/openapi.yaml before writing any endpoint
- Every agent MUST follow patterns in docs/ADR/*.md
- Every agent MUST implement interfaces from backend/app/interfaces/
- Every agent MUST pass `make verify` before marking work complete
- Every agent MUST complete docs/SELF_VERIFICATION_CHECKLIST.md
- Regression guardian blocks agent if their output breaks another agent's tests

## Quality Standards

- **Test Coverage**: >= 80% for all new code
- **Performance**: < 200ms p95 for routing decisions
- **Security**: Every PR passes DLP + vulnerability scan
- **Documentation**: Every public API has OpenAPI spec + examples
- **Licensing**: Only Apache 2.0 / MIT / BSD compatible dependencies
- **Contract Compliance**: 0 deviations from contracts/openapi.yaml
- **Regression**: 0 test regressions after any agent output

### Enterprise Quality Standards (NEW — Stage 2)
- **Authentication**: Every endpoint requires auth (except health probes)
- **Authorization**: Every mutation checks RBAC permissions
- **Tenant Isolation**: Zero cross-tenant data access (verified by integration tests)
- **Secrets Management**: Zero plaintext secrets in code, logs, configs, or database
- **Audit Trail**: Every state change logged with actor, action, resource, result
- **Credential Storage**: All credentials in Vault (never env vars or config files)
- **SSO Functional**: OAuth/OIDC + SAML flows work end-to-end
- **SCIM Functional**: User/group provisioning from IdP works
- **MFA Enforced**: Admin roles require MFA (configurable per tenant)
