# Archon — Orchestrator Context (Enterprise Edition — LEAN)

> This is the ONLY file the orchestrator session needs to read.
> Sub-agents read the full docs. You stay lightweight.
> Updated for Stage 3: Full Validation & Rebranding.

## What Is Archon?
Open-source enterprise AI orchestration platform. 26 agents (00-25) build it across 8 phases.
Location: `~/Scripts/Archon/`

## Phase Map

| Phase | Agents | What Gets Built | Status |
|-------|--------|----------------|--------|
| 0 | Orchestrator + **Agent-00** | API contracts, ADRs, stubs, golden paths, **Secrets Vault + SecretsManager SDK** | ✅ Complete |
| 1 | 01-06 | Backend + **OAuth/SAML/SCIM/MFA/RBAC** + React Flow UI + **SSO Login + RBAC UI** + NL wizard + templates + sandbox + versioning | ✅ Complete |
| 2 | 07-09, 23 | Router (**auth-aware**), lifecycle (**credential rotation**), cost (**identity attribution**), multi-tenant (**per-tenant IdP + SCIM + Vault namespaces + billing**) | ✅ Complete |
| 3 | 10-12, 18, 20, 21 | Red-team (**auth bypass testing**), DLP (**credential scanning**), governance (**identity governance + access reviews**), SentinelScan (**SSO discovery**), MCP security (**OAuth scopes**), proxy (**SAML termination**) | ✅ Complete |
| 4 | 13-14, 19 | Connectors (**full OAuth flows + Vault storage**), DocForge (**encrypted embeddings**), A2A (**federated OAuth + mTLS**) | ✅ Complete |
| 5 | 15-17, 22 | Live components (**session auth**), mobile (**biometric + SAML**), deployment (**Vault operator + cert-manager**), marketplace (**publisher auth + signed packages**) | ✅ Complete |
| 6 | 24-25 | Federated mesh (**federated identity**), edge runtime (**offline auth + local secrets**) | ✅ Complete |
| 7 | MV | Master validation — E2E + **enterprise auth + secrets + tenant isolation verification** | ✅ Complete |

## Agent Dependencies (Critical Path)
```
Phase 0 → Agent-00 (Secrets Vault) → Agent-01 → everything else
Agent-00 → ALL agents (SecretsManager SDK)
Agent-01 → 02, 03, 05, 06, 07, 13, 16
Agent-02 → 04, 12, 15, 22
Agent-07 → 08, 09, 11, 21
Agent-05 → 10
Agent-09 → 23
Agent-12 → 18
Agent-11 + 15 → 20
Agent-13 → 14
Agent-07 + 13 → 19
ALL → 17 → 24, 25 → Master Validator
```

## How To Delegate (Sub-Agent Pattern)

### Context Layering (CRITICAL — prevents context overflow)

Sub-agents have limited context too. Never tell them to read everything.
Use this 3-layer system:

**Layer 1 — Always included (inline in prompt, ~20 lines):**
- What to build (2-3 sentences)
- Which directory to work in
- Key constraints (3-5 bullets)

**Layer 2 — Read from disk (agent reads 1-2 small files, ~150 lines max):**
- `agents/AGENT_RULES.md` (compact standards — ALWAYS include)
- ONE of: the relevant agent prompt OR a specific ADR (not both unless small)

**Layer 3 — Read ONLY if directly needed for this task:**
- `contracts/openapi.yaml` — only if building API endpoints
- `docs/ARCHITECTURE.md` — only if making architectural decisions
- Specific existing source files the agent needs to modify or extend

### Prompt Template

```
You are building part of OpenAiria, an open-source AI orchestration platform.
Project root: ~/Scripts/Archon/

YOUR TASK: [one specific deliverable — 2-3 sentences max]

READ THESE FILES FIRST:
- ~/Scripts/Archon/agents/AGENT_RULES.md (coding standards — mandatory)
- ~/Scripts/Archon/[one other relevant file] (your specific requirements)

CONSTRAINTS:
- [2-3 bullets scoped to THIS task]
- [specific directory to write to]
- [specific patterns to follow]

DO NOT read ROADMAP.md, INSTRUCTIONS.md, BUILD_CORRECTNESS.md, or ARCHITECTURE.md.
Only read the files listed above.

When done, list every file you created or modified.
```

### Task Sizing Guide

Break work so each sub-agent task fits comfortably in context:

| Task Size | Example | Reads | Writes |
|-----------|---------|-------|--------|
| **Small** (ideal) | "Create the Agent SQLModel + Alembic migration" | AGENT_RULES + 1 file | 2-3 files |
| **Medium** (ok) | "Build CRUD routes for agents with tests" | AGENT_RULES + contract + 1 existing model | 4-6 files |
| **Too big** (split it) | "Build the entire cost engine" | Would need prompt + contract + architecture + ADRs | 10+ files |

Rule of thumb: if a sub-agent needs to read more than 3 files, the task is too big — split it.

## Rules For The Orchestrator (You)

1. **Never read full docs into your own context** — delegate to sub-agents
2. **One task = one deliverable** — don't ask a sub-agent to build an entire phase
3. **Keep sub-agent file reads ≤ 3** — AGENT_RULES.md + 1-2 task-specific files
4. **Verify before moving on** — after a sub-agent completes, run its verify command (not just spot-check)
5. **Phase gates** — run `node ~/Projects/copilot-sdd/dist/cli.js check` between phases. Do NOT start the next phase if any weight-5 goal fails.
6. **Track progress** — update this file's Phase Status table after each milestone
7. **Fail fast** — if a sub-agent fails twice, adjust the prompt scope (smaller) and retry
8. **Chunk Phase 0** into ~5 sub-tasks (contracts, ADRs, stubs, golden paths, vertical slice)
9. **Chunk each agent** into 2-4 sub-tasks (models → services → routes → tests)
10. **Chain results** — when task B depends on task A's output, tell task B which specific files to read from task A (not "read everything agent-01 built")
11. **Capture learnings** — after each failed sub-agent or surprising fix, run: `node ~/Projects/copilot-sdd/dist/cli.js learn --type pitfall --summary "<what happened>"`
12. **Inject learnings** — include `READ .sdd/learnings/*.md` in sub-agent prompts when relevant learnings exist

## SDD Pipeline Integration

This project uses copilot-sdd for spec-driven development. Key integration points:

### Phase Gates
Run between every phase transition:
```bash
node ~/Projects/copilot-sdd/dist/cli.js check
```
All weight-5 goals must PASS before proceeding to the next phase.

### Verify Commands
Every sub-agent task MUST include a `VERIFY:` line — a shell command that exits 0 on success.

### Learnings
After failures or discoveries, capture them:
```bash
node ~/Projects/copilot-sdd/dist/cli.js learn --type pitfall --summary "description"
```
Learnings persist in `.sdd/learnings/` and should be referenced by future sub-agents.

### Updated Prompt Template
```
You are building part of OpenAiria, an open-source AI orchestration platform.
Project root: ~/Scripts/Archon/

YOUR TASK: [one specific deliverable — 2-3 sentences max]

READ THESE FILES FIRST:
- ~/Scripts/Archon/agents/AGENT_RULES.md (coding standards + verify protocol — mandatory)
- ~/Scripts/Archon/.sdd/learnings/*.md (known pitfalls — read if any exist)
- ~/Scripts/Archon/[one other relevant file] (your specific requirements)

CONSTRAINTS:
- [2-3 bullets scoped to THIS task]
- [specific directory to write to]
- [specific patterns to follow]

VERIFY: [shell command that exits 0 when task is correctly done]
Example: cd backend && python -m pytest tests/test_agents.py -q 2>&1 | tail -1 | grep -qv 'FAILED'

DO NOT read ROADMAP.md, INSTRUCTIONS.md, BUILD_CORRECTNESS.md, or ARCHITECTURE.md.
Only read the files listed above.

When done, list every file you created or modified, and note any pitfalls discovered.
```

## Key Files Reference (for sub-agent prompts)

| Purpose | File |
|---------|------|
| Agent requirements | `agents/prompts/agent-XX-name.md` |
| API contract | `contracts/openapi-stub.yaml` |
| Response format | `docs/ADR/001-api-response-format.md` |
| Architecture | `docs/ARCHITECTURE.md` |
| Build correctness | `docs/BUILD_CORRECTNESS.md` |
| Self-check | `docs/SELF_VERIFICATION_CHECKLIST.md` |
| Feature matrix | `docs/FEATURE_MAPPING.md` |
| Full roadmap | `ROADMAP.md` |
| Swarm state | `agents/swarm/swarm-state.json` |
| **SDD goals** | `.sdd/goals.yaml` |
| **Known pitfalls** | `.sdd/learnings/*.md` |
| **SDD agents** | `.sdd/agents/*.md` |

## Tech Stack (Quick Ref)
- **Backend**: FastAPI, Python 3.12, SQLModel, Alembic, Celery, Redis
- **Frontend**: Next.js 15, React 19, TypeScript, React Flow 12, shadcn/ui, Tailwind
- **Orchestration**: LangGraph, LangChain, LiteLLM
- **DB**: PostgreSQL 16 + PGVector + RLS, Neo4j (governance)
- **Auth**: Keycloak 26 (OIDC/OAuth2/SAML), OPA (ABAC), SCIM 2.0
- **Secrets**: HashiCorp Vault (KV-v2, PKI, Transit, Database, AWS/Azure/GCP dynamic)
- **Identity**: SCIM 2.0 provisioning, MFA (TOTP/WebAuthn), API Keys
- **Monitoring**: OpenTelemetry, Prometheus, Grafana
- **Deploy**: Kubernetes 1.30, Helm 3, ArgoCD, Terraform, Istio, cert-manager, External Secrets Operator
- **Security**: Presidio (NER), NeMo Guardrails, Garak (red-team), OPA (policies), Vault (secrets)

## Stage 3: Full Validation & Rebranding — COMPLETE

| Objective | Status | Details |
|-----------|--------|---------|
| 1. Rebrand OpenAiria → Archon | ✅ Complete | All .py/.tsx/.ts/.yaml/.yml/.hcl/.sh/.md files updated. Directory renamed infra/helm/openairia → infra/helm/archon-platform. Zero grep hits for "openairia". |
| 2. Fix Frontend Pages | ✅ Complete | 16 API files fixed (endpoint paths, HTTP methods, response unwrapping). All pages wired to correct backend endpoints. Navigation/routing updated. |
| 3. Keycloak OIDC | ✅ Complete | Archon realm provisioned. Backend auth_routes.py supports Keycloak token grant with dev-mode fallback (AUTH_DEV_MODE=true). JWKS validation works. |
| 4. End-to-End Validation | ✅ Complete | 1092 tests passing. SDD 10/10. Branding clean. All smoke tests pass. Containers rebuilt. |

## Stage 4: Enterprise UX Rebuild — COMPLETE

All 22 agents executed across 5 phases. Every critical gap addressed.

| Gap | Agent | Resolution |
|-----|-------|------------|
| Agent Create = 3-field modal | 05 | 7-step wizard (Identity → Model → Tools → RAG → Security → Connectors → Review) |
| No execution engine | 06 | POST /execute creates & runs execution with mock steps, metrics, cost |
| Settings 404 | 01+19 | /api/v1/health alias added; Settings has 5-tab layout with System Health |
| Audit fails to load | 01+18 | list_all() for unfiltered queries; audit middleware auto-logs mutations |
| No SSO config UI | 16 | SSOConfigPage with OIDC/SAML forms, claim mapping, Test Connection |
| No API key storage | 08 | Provider API key → Vault, Test Connection, visual rule builder |
| Raw JSON connectors | 09 | 12 type-specific forms (PostgreSQL, Slack, S3, etc.) with catalog grid |
| No MCP Apps frontend | 15 | MCPAppsPage with component library, chat interface, interactive preview |
| No NL Wizard frontend | 03 | NLAgentWizard 4-step modal wired to wizard_service.py backend |
| Dashboard all zeros | 20 | Real API data, quick actions, activity feed, health indicators |
| Templates raw JSON | 04 | Gallery with 21 seed templates, one-click instantiate, wizard creation |
| Workflows raw JSON | 07 | Embedded React Flow editor, schedule picker, step config forms |
| DLP tag-only detectors | 12 | Visual detector picker grid (15 types), policy test, metrics |
| Lifecycle raw IDs | 10 | Visual pipeline, agent dropdowns, deployment strategies |
| Cost all zeros | 11 | Summary endpoint, breakdown tabs, budget utilization bars |
| Governance empty | 13 | Registry dashboard, compliance templates, approval workflow |
| SentinelScan fake 100 | 14 | Mock discovery results, risk bars, remediation actions |
| Router raw JSON rules | 08 FE | Visual condition builder, fallback chain, provider health dashboard |

### Validation Results
- **Tests**: 1092 passed, 0 failures ✅
- **SDD**: 10/10 (100%) ✅
- **Branding**: Zero "openairia" references ✅
- **New files**: 30 canvas nodes, MCPAppsPage, SSOConfigPage, NLAgentWizard, CI/CD pipeline, metrics endpoint
- **Modified**: 20 files, +3443 / -764 lines
