# Archon - Project Roadmap

> Living document tracking all phases, milestones, and deliverables.
> Incorporates all 20 strategic improvements and 10 build-correctness strategies.

---

## Phase Overview

```
Phase 0 --> Phase 1 --> Phase 2 --> Phase 3 --> Phase 4 --> Phase 5 --> Phase 6 --> Phase 7
Vertical    Core        Ops &       Security    Integ &     Deploy &    Advanced    Validation
Slice       Platform    Cost        & Gov       Data        UX          Features    & Polish
(Orch)      (01-06)     (07-09,23)  (10-12,     (13,14,19)  (15-17,22)  (24,25)     (Master
                                     18,20,21)                                       Validator)
```

---

## Phase 0: Foundation & Vertical Slice (Orchestrator - MANDATORY FIRST)

> **Goal**: Prove the entire architecture works end-to-end before any agent scales out.
> Implements Build-Correctness Strategies 1-6, 8-9.

### Milestone 0.1 - Contract-First Artifacts (Strategy 1)
- [ ] Generate `contracts/openapi.yaml` - complete OpenAPI 3.1 spec for all planned endpoints
- [ ] Generate `contracts/events.yaml` - WebSocket event schemas (JSON Schema)
- [ ] Generate `contracts/shared-types.ts` - TypeScript types auto-generated from OpenAPI
- [ ] Lock contracts - agents implement against these, no deviations allowed

### Milestone 0.2 - Architecture Decision Records (Strategy 2)
- [ ] `docs/ADR/001-api-response-format.md`
- [ ] `docs/ADR/002-error-handling-pattern.md`
- [ ] `docs/ADR/003-database-naming.md`
- [ ] `docs/ADR/004-task-queue-pattern.md`
- [ ] `docs/ADR/005-auth-middleware.md`
- [ ] `docs/ADR/006-logging-format.md`
- [ ] `docs/ADR/007-testing-patterns.md`
- [ ] `docs/ADR/008-websocket-protocol.md`
- [ ] `docs/ADR/009-env-config-pattern.md`
- [ ] `docs/ADR/010-import-structure.md`

### Milestone 0.3 - Interface Stubs & Golden Path (Strategies 3, 7)
- [ ] `backend/app/interfaces/` - Abstract base classes for all cross-agent boundaries
- [ ] `backend/app/interfaces/models/` - Shared Pydantic models (Agent, Execution, User, etc.)
- [ ] `docs/golden-path/router-example.py`
- [ ] `docs/golden-path/service-example.py`
- [ ] `docs/golden-path/test-example.py`
- [ ] `docs/golden-path/model-example.py`

### Milestone 0.4 - Integration Test Contracts (Strategy 4)
- [ ] `tests/integration/` - Pre-written failing tests at every agent boundary
- [ ] Backend to Frontend contract tests (API response shapes)
- [ ] Router to LLM Provider contract tests (model interface)
- [ ] Connector to Backend contract tests (data source interface)
- [ ] Agent to Execution Engine contract tests (state machine interface)

### Milestone 0.5 - Build Verification Pipeline (Strategies 5, 8, 10)
- [ ] `Makefile` with `make verify` (syntax, imports, types, lint, tests, contract diff)
- [ ] `make test-slice` - heartbeat test for the vertical slice
- [ ] CI/CD pipeline definition (GitHub Actions) with regression guardian
- [ ] `docs/SELF_VERIFICATION_CHECKLIST.md` - mandatory agent pre-completion gate

### Milestone 0.6 - Vertical Slice (Strategy 9)
- [ ] End-to-end: "Create and Execute a Simple 2-Node Agent"
  - [ ] Frontend: drag 2 nodes, connect, click Run
  - [ ] API: POST /agents, POST /execute
  - [ ] Auth: JWT validation via Keycloak
  - [ ] LangGraph: execute 2-node state machine
  - [ ] WebSocket: stream execution output
  - [ ] Database: persist agent definition + execution result
  - [ ] Audit: log events with correlation IDs
  - [ ] Cost: record token usage
  - [ ] Docker: docker-compose up runs everything
- [ ] Vertical slice stays green at ALL times - `make test-slice` is the heartbeat

---

## Phase 1: Core Platform (Agents 01-06)

> **Goal**: Functional backend + UI builder + NL wizard + templates + sandbox + versioning

### Milestone 1.1 - Core Backend (Agent-01)
- [ ] FastAPI project structure with modular routers
- [ ] SQLModel schemas for all core entities (agents, versions, executions, users)
- [ ] Alembic migration setup with initial schema
- [ ] LangGraph integration - agent state machine execution engine
- [ ] WebSocket server for real-time builder updates and streaming
- [ ] OpenTelemetry instrumentation (traces, metrics, logs)
- [ ] Docker Compose for local development (API + Postgres + Redis + MinIO)
- [ ] Health check, readiness, and liveness endpoints
- [ ] API key management (creation, rotation, revocation)
- [ ] Basic RBAC middleware
- [ ] **[Improvement 7]** Data retention & lifecycle policy engine
- [ ] **[Improvement 7]** Right-to-erasure workflows (GDPR)
- [ ] **[Improvement 7]** Data lineage tracking

### Milestone 1.2 - No-Code Builder UI (Agent-02)
- [ ] React 19 + Vite + TypeScript project setup
- [ ] React Flow canvas with custom node types
- [ ] Node palette (200+ nodes organized by category)
- [ ] Property panel with context-aware configuration
- [ ] Live preview pane with streaming agent output
- [ ] Version timeline component with diff view
- [ ] Export to JSON and Python
- [ ] Responsive layout with dark/light mode
- [ ] Keyboard shortcuts and accessibility
- [ ] Integration with backend WebSocket API
- [ ] **[Improvement 18]** Visual Agent Debugger - breakpoints, step-through, state inspect
- [ ] **[Improvement 18]** Time-travel debugging (go backwards through execution)
- [ ] **[Improvement 18]** State modification mid-execution and resume

### Milestone 1.3 - Natural Language to Agent Wizard (Agent-03)
- [ ] Multi-step LangGraph workflow: Describe > Plan > Build > Validate
- [ ] Planner LLM generates agent specification and flow diagram
- [ ] Coder LLM generates LangGraph JSON + Python from spec
- [ ] Validator LLM checks generated agent for security issues
- [ ] User feedback loop with iterative refinement
- [ ] Auto-deploy to sandbox after validation passes
- [ ] Natural language to node suggestion (inline in canvas)

### Milestone 1.4 - Template Library (Agent-04)
- [ ] Template data model (metadata, categories, tags, popularity)
- [ ] Template CRUD API endpoints
- [ ] Template browser UI with search, filter, preview
- [ ] One-click deploy from template
- [ ] Fork and customize templates
- [ ] Community contribution workflow (submit, review, publish)
- [ ] GitHub sync for template repository
- [ ] 50 initial templates across categories

### Milestone 1.5 - Sandbox & Testing (Agent-05)
- [ ] Isolated Docker execution environment per test run
- [ ] Kubernetes namespace isolation for sandbox workloads
- [ ] Arena Mode - parallel agent execution with metrics comparison
- [ ] Test suite generation from agent definition
- [ ] Automated regression testing on version changes
- [ ] Resource limits and timeout enforcement
- [ ] Test results dashboard with comparison charts
- [ ] **[Improvement 17]** Standardized agent benchmarking suite
- [ ] **[Improvement 17]** Public leaderboard for community agents
- [ ] **[Improvement 17]** Enterprise private benchmarks

### Milestone 1.6 - Version Control (Agent-06)
- [ ] Git-like versioning for agent definitions
- [ ] Immutable version snapshots (code, config, dependencies)
- [ ] Visual diff between versions
- [ ] One-click rollback to any previous version
- [ ] Branch and merge support for agent development
- [ ] Deployment promotion (dev > staging > production)
- [ ] Audit trail for all version changes

---

## Phase 2: Operations & Cost (Agents 07, 08, 09, 23)

> **Goal**: Intelligent routing, lifecycle management, cost tracking, multi-tenancy

### Milestone 2.1 - Intelligent Router (Agent-07)
- [ ] Dynamic model selection engine (cost x latency x capability x sensitivity)
- [ ] Real-time latency and availability monitoring per provider
- [ ] Fallback chains with automatic failover
- [ ] Per-department and per-user routing rules
- [ ] A/B testing support for routing strategies
- [ ] Router configuration UI
- [ ] < 200ms p95 routing decision latency
- [ ] LiteLLM integration for unified model access
- [ ] **[Improvement 13]** Explainable routing - human-readable decision with every route
- [ ] **[Improvement 13]** Decision audit trail and replay/simulation
- [ ] **[Improvement 13]** "Why was this model chosen?" UI

### Milestone 2.2 - Lifecycle Manager (Agent-08)
- [ ] Model registry with approval workflows
- [ ] Canary deployments for agent updates
- [ ] Blue-green deployment support
- [ ] Automated rollback on error rate thresholds
- [ ] Agent health monitoring and auto-restart
- [ ] Scheduled agent execution (cron-like)
- [ ] Agent dependency graph visualization
- [ ] **[Improvement 14]** Real-time streaming ops dashboard
- [ ] **[Improvement 14]** ML-based anomaly detection
- [ ] **[Improvement 14]** Predictive observability (budget forecasting, error trending)
- [ ] **[Improvement 14]** Auto-mitigation (throttle, failover, pause on anomaly)

### Milestone 2.3 - Cost Engine (Agent-09)
- [ ] Universal token ledger tracking all LLM usage
- [ ] Real-time cost dashboard per agent, user, department
- [ ] Departmental budgets with alerts and hard limits
- [ ] Cost forecasting based on historical trends
- [ ] Chargeback reports (PDF + API)
- [ ] Cost optimization recommendations
- [ ] OpenLLMetry integration for standardized tracking
- [ ] Multi-currency support

### Milestone 2.4 - Multi-Tenant Platform & Billing (Agent-23) NEW
- [ ] **[Improvement 12]** Tenant isolation (database RLS, compute namespaces, network policies)
- [ ] **[Improvement 12]** Self-service onboarding: signup > verify > choose tier > provision
- [ ] **[Improvement 12]** Tier definitions: Free > Individual > Team > Enterprise
- [ ] **[Improvement 12]** Usage metering (executions, tokens, storage, API calls)
- [ ] **[Improvement 12]** Stripe billing integration (subscriptions + usage-based)
- [ ] **[Improvement 12]** Internal chargeback mode (no external billing dependency)
- [ ] **[Improvement 12]** Quota enforcement with configurable hard/soft limits
- [ ] **[Improvement 12]** Tenant admin console

---

## Phase 3: Security & Governance (Agents 10, 11, 12, 18, 20, 21)

> **Goal**: Adversarial testing, DLP, compliance, shadow AI discovery, MCP security, proxy

### Milestone 3.1 - Red-Teaming Engine (Agent-10)
- [ ] Garak integration for automated adversarial testing
- [ ] Custom attack vector library (prompt injection, jailbreak, data exfil)
- [ ] Scheduled red-team runs per agent
- [ ] Vulnerability scoring and trending
- [ ] Remediation recommendations
- [ ] Integration with CI/CD pipeline
- [ ] Report generation (executive + technical)

### Milestone 3.2 - DLP & Guardrails (Agent-11)
- [ ] Multi-layer DLP pipeline (regex > NER > semantic > policy)
- [ ] Presidio integration for PII/PHI detection
- [ ] Custom entity recognizers (API keys, internal IDs, etc.)
- [ ] NeMo Guardrails for content safety
- [ ] Guardrails AI for structural output validation
- [ ] Configurable policies per agent/department
- [ ] Real-time DLP dashboard with alerts
- [ ] Hallucination detection (cross-reference + confidence scoring)
- [ ] Toxicity and bias scoring
- [ ] **[Improvement 19]** Natural Language Policy Engine - define policies in plain English
- [ ] **[Improvement 19]** Auto-generate OPA + DLP rules from NL description
- [ ] **[Improvement 19]** Policy impact simulation

### Milestone 3.3 - Governance Dashboard (Agent-12)
- [ ] Neo4j graph for agent/model/data lineage
- [ ] Compliance dashboard (SOC2, GDPR, HIPAA status)
- [ ] Agent registry with ownership and approval status
- [ ] Data flow visualization
- [ ] Policy management UI (OPA policies)
- [ ] Audit log viewer with advanced search and filters
- [ ] Export compliance reports (PDF, CSV)
- [ ] Role-based access to governance features
- [ ] **[Improvement 5]** Auto-generate reports for EU AI Act, NIST AI RMF, ISO 42001
- [ ] **[Improvement 5]** Pluggable regulation templates (community-contributed)
- [ ] **[Improvement 8]** AI Inventory Management with custom risk tiers
- [ ] **[Improvement 8]** Dynamic risk scoring based on usage patterns
- [ ] **[Improvement 9]** Governance committees with approval workflows
- [ ] **[Improvement 9]** Time-bounded approvals with auto-escalation
- [ ] **[Improvement 15]** Agent dependency graph with blast radius analysis
- [ ] **[Improvement 15]** Change impact simulation

### Milestone 3.4 - SentinelScan Engine (Agent-18) NEW
- [ ] **[Improvement 1]** Shadow AI discovery across the organization
- [ ] **[Improvement 1]** SSO audit log scanner, network traffic analyzer, API gateway inspector
- [ ] **[Improvement 1]** Unified AI asset inventory (cross-platform, not just Archon agents)
- [ ] **[Improvement 1]** Risk classification with configurable tiers
- [ ] **[Improvement 1]** Real-time posture score (0-100) with trend tracking
- [ ] **[Improvement 1]** Executive summary export (PDF)
- [ ] **[Improvement 1]** Pluggable discovery module SDK

### Milestone 3.5 - MCP Security & Governance (Agent-20) NEW
- [ ] **[Improvement 3]** Ephemeral sandboxed containers per MCP request (zero data retention)
- [ ] **[Improvement 3]** Tool-level authorization and access control
- [ ] **[Improvement 3]** Tool definition change detection with side-by-side diff
- [ ] **[Improvement 3]** Response validation + indirect prompt injection detection
- [ ] **[Improvement 3]** Community-driven MCP vulnerability database
- [ ] **[Improvement 3]** Version pinning and rollback for MCP tools

### Milestone 3.6 - Security Proxy Gateway (Agent-21) NEW
- [ ] **[Improvement 4]** Standalone reverse-proxy for ANY AI endpoint
- [ ] **[Improvement 4]** DLP pipeline: PII detection/redaction on requests and responses
- [ ] **[Improvement 4]** Content classification and policy enforcement (OPA)
- [ ] **[Improvement 4]** Token counting and cost attribution across all proxied services
- [ ] **[Improvement 4]** Full audit logging with SIEM export
- [ ] **[Improvement 4]** Streaming SSE passthrough for chat completions
- [ ] **[Improvement 4]** Standalone Docker deployment with YAML config
- [ ] **[Improvement 4]** < 50ms added latency (p95)

---

## Phase 4: Integrations & Data (Agents 13, 14, 19)

> **Goal**: 50+ connectors, document processing, A2A protocol, RAG pipeline

### Milestone 4.1 - Connector Hub (Agent-13)
- [ ] Connector framework with plugin architecture
- [ ] OAuth2 credential management for connectors
- [ ] **[Improvement 10]** Three-tier integration architecture:
  - [ ] Data Source Connectors (read-only: SharePoint, Confluence, Drive, etc.)
  - [ ] MCP Servers (bidirectional tool access)
  - [ ] Tool Integrations (action-oriented: Jira actions, email sending, etc.)
  - [ ] Event Sources (webhooks, Kafka, DB change streams - 4th category)
- [ ] Initial connectors: M365, Google Workspace, Salesforce, Slack, Jira/Confluence, GitHub/GitLab, databases, cloud storage, ServiceNow, generic REST/GraphQL/gRPC
- [ ] **[Improvement 6]** Permissions-aware data access (inherit source app permissions)
- [ ] **[Improvement 6]** Transparent permissions cache with real-time sync
- [ ] **[Improvement 6]** Audit logging of every permission check
- [ ] Connector health monitoring, rate limiting, retry logic
- [ ] Custom connector SDK (Python)
- [ ] Connector marketplace UI

### Milestone 4.2 - DocForge Processor (Agent-14)
- [ ] Unstructured.io integration for multi-format parsing
- [ ] Parallel processing pipeline (chunks > embeddings > store)
- [ ] Automatic document tagging and classification
- [ ] OCR for images and scanned documents
- [ ] Table extraction and structured data output
- [ ] Document change detection and re-indexing
- [ ] Processing status dashboard
- [ ] Support for: PDF, DOCX, PPTX, XLSX, HTML, MD, TXT, Images

### Milestone 4.3 - A2A Protocol Support (Agent-19) NEW
- [ ] **[Improvement 2]** Agent Card discovery from well-known URIs
- [ ] **[Improvement 2]** Import external A2A agents as drag-and-drop canvas nodes
- [ ] **[Improvement 2]** Publish Archon agents as A2A-compatible services
- [ ] **[Improvement 2]** Bi-directional task delegation with streaming
- [ ] **[Improvement 2]** mTLS + OAuth2 authentication for cross-platform calls
- [ ] **[Improvement 2]** Full audit trail of all A2A interactions

---

## Phase 5: Deployment & UX (Agents 15, 16, 17, 22)

> **Goal**: Mobile SDK, interactive components, marketplace, production deployment

### Milestone 5.1 - Live Components (Agent-15)
- [ ] WebSocket protocol for embedded React components in chat
- [ ] Component library (forms, charts, tables, buttons, cards)
- [ ] Dynamic component rendering based on agent output
- [ ] State management between chat and embedded components
- [ ] Component SDK for custom interactive elements
- [ ] Theme support (inherits from host application)

### Milestone 5.2 - Mobile SDK (Agent-16)
- [ ] Flutter SDK package for agent interaction
- [ ] iOS native chat application
- [ ] Android native chat application
- [ ] Push notifications for agent updates
- [ ] Offline mode with sync
- [ ] Biometric authentication
- [ ] Voice input/output support
- [ ] Responsive agent cards and rich media

### Milestone 5.3 - Production Deployment (Agent-17)
- [ ] Helm chart with configurable values for all services
- [ ] Terraform modules for AWS, Azure, GCP
- [ ] Air-gapped deployment bundle (all images + charts)
- [ ] ArgoCD application definitions
- [ ] Kyverno policies for security enforcement
- [ ] Cert-Manager configuration for automatic TLS
- [ ] Monitoring stack (Prometheus + Grafana + AlertManager)
- [ ] Logging stack (OpenSearch + Fluent Bit)
- [ ] Backup and restore procedures
- [ ] Disaster recovery runbook
- [ ] Performance tuning guide
- [ ] Security hardening checklist

### Milestone 5.4 - Open Marketplace & Creator Program (Agent-22) NEW
- [ ] **[Improvement 11]** Listing system: agents, templates, connectors, guardrail policies
- [ ] **[Improvement 11]** Search with full-text + faceted filtering
- [ ] **[Improvement 11]** Creator registration, profiles, verified badges
- [ ] **[Improvement 11]** Submission > automated review > manual review > publish pipeline
- [ ] **[Improvement 11]** One-click install from marketplace to workspace
- [ ] **[Improvement 11]** Stars, reviews, forks, usage analytics
- [ ] **[Improvement 11]** Self-hostable private marketplace for enterprises
- [ ] **[Improvement 11]** Optional Stripe Connect for premium listings

---

## Phase 6: Advanced Features (Agents 24, 25)

> **Goal**: Cross-org collaboration and edge/offline deployment

### Milestone 6.1 - Federated Agent Mesh (Agent-24) NEW
- [ ] **[Improvement 16]** Cross-org agent communication with mutual TLS
- [ ] **[Improvement 16]** Mesh discovery and trust establishment
- [ ] **[Improvement 16]** Data isolation with policy-gated sharing
- [ ] **[Improvement 16]** End-to-end encryption for all mesh messages
- [ ] **[Improvement 16]** Audit trails on both sides of cross-org interactions
- [ ] **[Improvement 16]** Kill switch for immediate trust revocation
- [ ] **[Improvement 16]** Federation agreement management

### Milestone 6.2 - Edge Runtime (Agent-25) NEW
- [ ] **[Improvement 20]** Lightweight runtime (< 500MB) for edge devices
- [ ] **[Improvement 20]** Local model inference (Ollama, vLLM, ONNX Runtime)
- [ ] **[Improvement 20]** Local vector store for offline RAG
- [ ] **[Improvement 20]** Bi-directional sync with conflict resolution
- [ ] **[Improvement 20]** Embedded OPA + local DLP scanning
- [ ] **[Improvement 20]** Device authentication and tamper detection
- [ ] **[Improvement 20]** Fleet management console on central platform
- [ ] **[Improvement 20]** Remote wipe capability

---

## Phase 7: Validation & Polish (Master Validator)

> **Goal**: 95%+ feature coverage, E2E testing, documentation, launch readiness

### Milestone 7.1 - E2E Testing (Master Validator)
- [ ] 50 enterprise scenario test suite
- [ ] Performance benchmarking under load (10k concurrent agents)
- [ ] Security penetration testing
- [ ] Compliance audit simulation
- [ ] Cross-browser testing (Chrome, Firefox, Safari, Edge)
- [ ] Mobile app testing (iOS + Android)
- [ ] API contract testing
- [ ] Chaos engineering tests (pod failures, network partitions)

### Milestone 7.2 - Documentation
- [ ] Getting Started guide
- [ ] API Reference (auto-generated from OpenAPI)
- [ ] Architecture overview
- [ ] Security whitepaper
- [ ] Deployment guides (Docker, K8s, Air-gapped, Cloud, Edge)
- [ ] Connector development guide
- [ ] Agent development tutorials
- [ ] Video walkthroughs
- [ ] FAQ and troubleshooting

### Milestone 7.3 - Launch Readiness
- [ ] Open-source community setup (CONTRIBUTING.md, CODE_OF_CONDUCT.md)
- [ ] GitHub repository configuration (issues, discussions, CI/CD)
- [ ] Demo environment (publicly accessible)
- [ ] Marketing site / landing page
- [ ] Blog post / announcement
- [ ] ProductHunt launch plan

---

## Build-Correctness Strategy Traceability

> Every strategy from `docs/BUILD_CORRECTNESS.md` is mapped to milestones above.

| Strategy | Milestone | Status |
|----------|-----------|--------|
| 1. Contract-First API Specs | Phase 0, M0.1 | Planned |
| 2. Binding ADRs | Phase 0, M0.2 | Planned |
| 3. Interface Stubs | Phase 0, M0.3 | Planned |
| 4. Integration Test Contracts | Phase 0, M0.4 | Planned |
| 5. Build Verification Pipeline | Phase 0, M0.5 | Planned |
| 6. Dependency-Ordered Execution | Enforced by Orchestrator (MAIN_PROMPT.md) | Planned |
| 7. Golden Path Examples | Phase 0, M0.3 | Planned |
| 8. Self-Verification Checklist | Phase 0, M0.5 | Planned |
| 9. Vertical Slice First | Phase 0, M0.6 | Planned |
| 10. Regression Guardian | Phase 0, M0.5 (CI/CD definition) | Planned |

## Improvement Traceability

> Every improvement from `docs/GAP_ANALYSIS.md` is mapped to milestones above.

| # | Improvement | Phase | Milestone |
|---|-------------|-------|-----------|
| 1 | SentinelScan (Shadow AI Discovery) | 3 | M3.4 |
| 2 | A2A Protocol Support | 4 | M4.3 |
| 3 | MCP Security & Governance | 3 | M3.5 |
| 4 | Security Proxy Gateway | 3 | M3.6 |
| 5 | Compliance Report Generator | 3 | M3.3 |
| 6 | Permissions-Aware Data Pipeline | 4 | M4.1 |
| 7 | Data Retention & Lifecycle | 1 | M1.1 |
| 8 | AI Inventory + Risk Classification | 3 | M3.3 |
| 9 | Governance Committees | 3 | M3.3 |
| 10 | Three-Tier Integration Architecture | 4 | M4.1 |
| 11 | Open Marketplace & Creator Program | 5 | M5.4 |
| 12 | Multi-Tenant & Billing | 2 | M2.4 |
| 13 | Explainable Routing | 2 | M2.1 |
| 14 | Observability & Anomaly Detection | 2 | M2.2 |
| 15 | Dependency Blast Radius | 3 | M3.3 |
| 16 | Federated Agent Mesh | 6 | M6.1 |
| 17 | Agent Benchmarking Suite | 1 | M1.5 |
| 18 | Visual Agent Debugger | 1 | M1.2 |
| 19 | Natural Language Policy Engine | 3 | M3.2 |
| 20 | Edge/Offline Runtime | 6 | M6.2 |

---

## Dependencies Graph (25-Agent Roster)

```
                    Phase 0: Orchestrator
                    Contracts, ADRs, Stubs,
                    Golden Path, Vertical Slice
                              |
  ============================|============================
  |                           |                           |
Agent-01 (Core Backend) ------+---------------------------+
  |                                                       |
  +--- Agent-02 (UI + Debugger)                           |
  |      +--- Agent-04 (Templates)                        |
  |      +--- Agent-12 (Governance)                       |
  |      +--- Agent-15 (Live Components)                  |
  |      +--- Agent-22 (Marketplace)                      |
  |                                                       |
  +--- Agent-03 (NL Wizard)                               |
  |                                                       |
  +--- Agent-05 (Sandbox + Arena)                         |
  |      +--- Agent-10 (Red-Team)                         |
  |                                                       |
  +--- Agent-06 (Versioning)                              |
  |                                                       |
  +--- Agent-07 (Router + XAI)                            |
  |      +--- Agent-08 (Lifecycle + Anomaly)              |
  |      +--- Agent-09 (Cost Engine)                      |
  |      +--- Agent-11 (DLP + NL Policy)                  |
  |      +--- Agent-21 (Security Proxy)                   |
  |                                                       |
  +--- Agent-13 (Connectors 3-Tier) --- Agent-14 (DocForge)
  |                                                       |
  +--- Agent-16 (Mobile SDK)                              |
  |                                                       |
  +--- Agent-18 (SentinelScan)                            |
  +--- Agent-19 (A2A Protocol)                            |
  +--- Agent-20 (MCP Security)                            |
  +--- Agent-23 (Multi-Tenant)                            |
  |                                                       |
  +--- Agent-17 (Deployment) <-- ALL AGENTS --------------+
              |
    +---------+---------+
    |                   |
  Agent-24            Agent-25
  (Agent Mesh)        (Edge Runtime)
    |                   |
    +---------+---------+
              |
       Master Validator
```

---

*Maintained by the Archon Orchestrator. Updated as phases complete.*
