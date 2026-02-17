# Archon — Autonomous Build Reference

> Re-read this file at the START of each phase to stay on track.
> This is your playbook. Follow it exactly.

## Operating Rules

1. You are a **manager, not a coder**. Delegate everything to sub-agents.
2. Spawn sub-agents via `task` tool, type `general-purpose`.
3. Each sub-agent reads **at most 3 files**: AGENT_RULES.md + .sdd/learnings/*.md + 1 task-specific file.
4. Every sub-agent prompt **MUST** end with a `VERIFY:` line (shell command, exits 0 on success).
5. After each sub-agent completes, **run its VERIFY command** — don't just spot-check.
6. If a sub-agent fails, retry once with a refined prompt. If it fails again:
   ```
   node ~/Projects/copilot-sdd/dist/cli.js learn --type pitfall --summary "what happened"
   ```
   Then move on — do NOT get stuck.
7. Between phases, run the **phase gate**:
   ```
   node ~/Projects/copilot-sdd/dist/cli.js check
   ```
   All weight-5 goals must PASS before moving to the next phase.
8. Update `ORCHESTRATOR_CONTEXT.md` phase status table after each phase completes.
9. **Do NOT stop. Do NOT ask the user. Keep building until Phase 7 is complete.**

## Sub-Agent Prompt Template

```
You are building part of Archon, an open-source AI orchestration platform.
Project root: ~/Scripts/Archon/

YOUR TASK: [one specific deliverable]

READ THESE FILES FIRST:
- ~/Scripts/Archon/agents/AGENT_RULES.md
- ~/Scripts/Archon/.sdd/learnings/*.md
- ~/Scripts/Archon/agents/prompts/agent-XX-name.md

CONSTRAINTS:
- [2-3 bullets scoped to THIS task]
- [specific directory to write to]

VERIFY: [shell command that exits 0 when done]

DO NOT read ROADMAP.md, INSTRUCTIONS.md, BUILD_CORRECTNESS.md, or ARCHITECTURE.md.
When done, list files created/modified and note any pitfalls.
```

## Phase Execution Plan

### Phase 2: Operations & Cost (Agents 07-09, 23)

**Dependency order:** Agent-07 FIRST → PARALLEL: Agent-08, Agent-09 → LAST: Agent-23

| Task | Agent | Deliverable | Read | Verify |
|------|-------|-------------|------|--------|
| 7a | 07 | Routing decision engine + model registry | agent-07-router.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.router import RoutingEngine; print('OK')"` |
| 7b | 07 | Routing strategies + A/B testing | agent-07-router.md | `cd ~/Scripts/Archon/backend && python3 -m pytest tests/test_router/ --tb=short -q` |
| 8a | 08 | Lifecycle manager + deployment records | agent-08-lifecycle.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.lifecycle import LifecycleManager; print('OK')"` |
| 8b | 08 | Health monitoring + anomaly detection | agent-08-lifecycle.md | `cd ~/Scripts/Archon/backend && python3 -m pytest tests/test_lifecycle/ --tb=short -q` |
| 9a | 09 | Token ledger + cost tracking | agent-09-cost-engine.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.cost import CostEngine; print('OK')"` |
| 9b | 09 | Dashboards + budgets + forecasting | agent-09-cost-engine.md | `cd ~/Scripts/Archon/backend && python3 -m pytest tests/test_cost/ --tb=short -q` |
| 23a | 23 | Tenant isolation + self-service signup | agent-23-multi-tenant.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.tenancy import TenantManager; print('OK')"` |
| 23b | 23 | Metering + Stripe billing + quotas | agent-23-multi-tenant.md | `cd ~/Scripts/Archon/backend && python3 -m pytest tests/test_multi_tenant/ --tb=short -q` |

**Phase gate:** `node ~/Projects/copilot-sdd/dist/cli.js check`

---

### Phase 3: Security & Governance (Agents 10-12, 18, 20, 21)

**Dependency order:** PARALLEL: Agent-10, Agent-11, Agent-12 → PARALLEL: Agent-18 (after 12), Agent-21 (after 11) → LAST: Agent-20 (after 11)

| Task | Agent | Deliverable | Read | Verify |
|------|-------|-------------|------|--------|
| 10a | 10 | Red-team engine + attack library | agent-10-redteam.md | `cd ~/Scripts/Archon && python3 -c "from security.red_team.engine import RedTeamEngine; print('OK')"` |
| 10b | 10 | Scoring + CI/CD integration | agent-10-redteam.md | `cd ~/Scripts/Archon && python3 -m pytest tests/test_redteam/ --tb=short -q` |
| 11a | 11 | DLP engine + NER + semantic classification | agent-11-dlp-guardrails.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.dlp import DLPEngine; print('OK')"` |
| 11b | 11 | OPA policies + content guardrails | agent-11-dlp-guardrails.md | `cd ~/Scripts/Archon/backend && python3 -m pytest tests/test_dlp/ --tb=short -q` |
| 12a | 12 | Agent registry + compliance dashboard | agent-12-governance.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.governance import GovernanceEngine; print('OK')"` |
| 12b | 12 | Neo4j lineage + OPA policies + audit logs | agent-12-governance.md | `cd ~/Scripts/Archon/backend && python3 -m pytest tests/test_governance/ --tb=short -q` |
| 18a | 18 | Shadow AI discovery modules | agent-18-sentinelscan.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.sentinelscan import SentinelScanner; print('OK')"` |
| 18b | 18 | Risk classification + posture dashboard | agent-18-sentinelscan.md | `cd ~/Scripts/Archon && python3 -m pytest tests/test_sentinelscan/ --tb=short -q` |
| 21a | 21 | Reverse proxy + DLP pipeline | agent-21-security-proxy.md | `cd ~/Scripts/Archon && python3 -c "from security.proxy import SecurityProxy; print('OK')"` |
| 21b | 21 | OPA policy engine + standalone Docker mode | agent-21-security-proxy.md | `cd ~/Scripts/Archon && python3 -m pytest tests/test_security_proxy/ --tb=short -q` |
| 20a | 20 | Ephemeral sandbox + tool authorization | agent-20-mcp-security.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.mcp_security import MCPSecurityGuardian; print('OK')"` |
| 20b | 20 | Change detection + response validation | agent-20-mcp-security.md | `cd ~/Scripts/Archon && python3 -m pytest tests/test_mcp_security/ --tb=short -q` |

**Phase gate:** `node ~/Projects/copilot-sdd/dist/cli.js check`

---

### Phase 4: Integrations & Data (Agents 13-14, 19)

**Dependency order:** Agent-13 FIRST → PARALLEL: Agent-14, Agent-19

| Task | Agent | Deliverable | Read | Verify |
|------|-------|-------------|------|--------|
| 13a | 13 | Connector framework + SDK | agent-13-connectors.md | `cd ~/Scripts/Archon && python3 -c "from integrations.connectors.framework import ConnectorBase; print('OK')"` |
| 13b | 13 | Core connectors + health monitoring | agent-13-connectors.md | `cd ~/Scripts/Archon && python3 -m pytest tests/test_connectors/ --tb=short -q` |
| 14a | 14 | Multi-format parsers + chunking + embeddings | agent-14-docforge.md | `cd ~/Scripts/Archon && python3 -c "from integrations.docforge.pipeline import DocForgePipeline; print('OK')"` |
| 14b | 14 | Celery workers + search integration | agent-14-docforge.md | `cd ~/Scripts/Archon && python3 -m pytest tests/test_docforge/ --tb=short -q` |
| 19a | 19 | Agent Card discovery + A2A client | agent-19-a2a-protocol.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.a2a import A2AClient, A2APublisher; print('OK')"` |
| 19b | 19 | Publishing + security (mTLS/OAuth2) | agent-19-a2a-protocol.md | `cd ~/Scripts/Archon && python3 -m pytest tests/test_a2a/ --tb=short -q` |

**Phase gate:** `node ~/Projects/copilot-sdd/dist/cli.js check`

---

### Phase 5: Deployment & UX (Agents 15-17, 22)

**Dependency order:** PARALLEL: Agent-15, Agent-16, Agent-22 → LAST: Agent-17

| Task | Agent | Deliverable | Read | Verify |
|------|-------|-------------|------|--------|
| 15a | 15 | WebSocket components + form/chart/table library | agent-15-mcp-interactive.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.mcp import MCPService; print('OK')"` |
| 15b | 15 | Component SDK + sandboxing | agent-15-mcp-interactive.md | `cd ~/Scripts/Archon && python3 -m pytest tests/test_mcp/ --tb=short -q` |
| 16a | 16 | Flutter SDK + core app screens | agent-16-mobile.md | `cd ~/Scripts/Archon/mobile && flutter pub get` |
| 16b | 16 | Offline mode + push notifications | agent-16-mobile.md | `cd ~/Scripts/Archon/mobile && flutter analyze --no-fatal-infos` |
| 22a | 22 | Marketplace CRUD + search + review pipeline | agent-22-marketplace.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.marketplace import MarketplaceService; print('OK')"` |
| 22b | 22 | Creator program + one-click install | agent-22-marketplace.md | `cd ~/Scripts/Archon/backend && python3 -m pytest tests/test_marketplace/ --tb=short -q` |
| 17a | 17 | Helm charts + Terraform (AWS/Azure/GCP) | agent-17-deployment.md | `cd ~/Scripts/Archon/infra/helm/archon && helm lint .` |
| 17b | 17 | Air-gap bundle + ArgoCD + monitoring | agent-17-deployment.md | `cd ~/Scripts/Archon/infra/terraform/aws && terraform validate` |
| 17c | 17 | Deployment docs | agent-17-deployment.md | `test -f ~/Scripts/Archon/infra/docs/deployment-guide.md` |

**Phase gate:** `node ~/Projects/copilot-sdd/dist/cli.js check`

---

### Phase 6: Advanced Features (Agents 24-25)

**Dependency order:** PARALLEL: Agent-24, Agent-25

| Task | Agent | Deliverable | Read | Verify |
|------|-------|-------------|------|--------|
| 24a | 24 | Mesh gateway + trust establishment | agent-24-agent-mesh.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.mesh import MeshGateway; print('OK')"` |
| 24b | 24 | Cross-org communication + data isolation | agent-24-agent-mesh.md | `cd ~/Scripts/Archon && python3 -m pytest tests/test_mesh/ --tb=short -q` |
| 25a | 25 | Edge runtime + local inference | agent-25-edge-runtime.md | `cd ~/Scripts/Archon/backend && python3 -c "from app.services.edge import EdgeRuntime; print('OK')"` |
| 25b | 25 | Bi-directional sync + fleet management | agent-25-edge-runtime.md | `cd ~/Scripts/Archon && python3 -m pytest tests/test_edge/ --tb=short -q` |

**Phase gate:** `node ~/Projects/copilot-sdd/dist/cli.js check`

---

### Phase 7: Master Validation

Run full E2E validation across 50 enterprise scenarios:

1. Agent CRUD (create, update, delete, list)
2. Agent execution (single node, multi-node, parallel, human-in-loop)
3. Multi-model routing under simulated load
4. Security boundary enforcement (DLP, red-team, guardrails)
5. Data connector reliability (connect, read, write, error handling)
6. Cost tracking accuracy (token counting, budget enforcement)
7. Deployment automation (Helm install, Terraform apply)
8. Mobile SDK functionality (connect, stream, offline)
9. Compliance audit trail completeness
10. Rollback and disaster recovery

**Final verify:** `node ~/Projects/copilot-sdd/dist/cli.js check` — must be 95%+ on all weight-5 goals.
