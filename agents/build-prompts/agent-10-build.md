# Agent 10 — Lifecycle & Deployment — Build Prompt

## Context

Agent lifecycle management: draft → staging → production with deployment strategies. Replace the raw-ID deployment form with a visual pipeline, searchable selectors, deployment strategy pickers, environment management, and post-deployment health monitoring.

**Tech stack — Backend:** Python 3.12, FastAPI, SQLModel, Alembic, AsyncSession. **Frontend:** React 19, TypeScript strict, shadcn/ui, Tailwind CSS, React Flow. **Auth:** JWT + Keycloak. **Secrets:** HashiCorp Vault via `backend/app/secrets/manager.py`.

---

## What Already Exists

| File | Lines | Action |
|------|-------|--------|
| `frontend/src/pages/LifecyclePage.tsx` | 207 | **REDESIGN** — Deployment form with raw Agent ID, Version ID, Environment, Rolling Count. |
| `frontend/src/api/lifecycle.ts` | 86 | **EXTEND** — Lifecycle API client. |
| `backend/app/routes/lifecycle.py` | 530 | **EXTEND** — Lifecycle routes. |
| `backend/app/services/lifecycle_service.py` | 468 | **EXTEND** — Lifecycle service. |
| `backend/app/models/lifecycle.py` | 215 | **KEEP** — Lifecycle models. |

---

## What to Build

### 1. Visual Lifecycle Pipeline

Horizontal pipeline visualization showing four stages: **Draft → Review → Staging → Production**.

- Each stage shows agent versions currently in that stage (cards with agent name, version, deploy time).
- Promote / demote buttons between stages.
- Approval gates between Review → Staging and Staging → Production (configurable per tenant).
- Use React Flow or a custom horizontal lane component for the pipeline.

### 2. Deployment Form Redesign

Replace raw ID fields with rich selectors:

- **Agent selector:** Searchable dropdown showing agent name + current status badge.
- **Version selector:** Dropdown showing version number + changelog preview (first 80 chars).
- **Environment selector:** Development, Staging, Production, + custom environments.
- **Deployment strategy:**
  - **Rolling:** Replica count slider (1–10).
  - **Blue-Green:** Preview toggle — deploy to inactive, switch on confirmation.
  - **Canary:** Traffic percentage slider (1–100%).
- **Pre-deploy checks:** Auto-run DLP scan, guardrail validation, cost estimate before deploy.

### 3. Environment Management

- Environment cards showing: deployed version, health status, instance count, last deploy time.
- **Diff view:** Compare agent config between any two environments side-by-side (JSON diff with highlighting).
- Create / archive custom environments.

### 4. Health Monitoring

- After deployment, show live health: response time (p50/p95/p99), error rate, throughput (req/min).
- Auto-rollback trigger configurable: rollback if error rate > threshold within window.
- Deployment history timeline per environment.

---

## Patterns to Follow

### Pattern 1 — Dify App Publishing

**Source:** `dify/api/services/app_service.py`

Dify has a simple publish/unpublish model for apps. When published, the app becomes accessible via its API. No multi-environment pipeline exists.

**Adaptation:** Archon extends this with a full 4-stage pipeline (Draft → Review → Staging → Production). Each stage transition is an explicit action with optional approval gates. Deployment strategies (Rolling, Blue-Green, Canary) are added on top. Design from first principles using Kubernetes deployment pattern concepts — the pipeline is a state machine where each promotion is a transition that can require approval.

### Pattern 2 — Coze Studio Bot Deployment

Coze has draft/published states for bots with version management. Publishing creates a snapshot of the bot configuration.

**Adaptation:** Extend the 2-state model to 4+ stages with approval gates between critical transitions. Add deployment strategy selection (Rolling/Blue-Green/Canary) at the promotion step. Each promotion creates an immutable deployment record with the full agent config snapshot, enabling rollback to any previous state.

---

## Backend Deliverables

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/lifecycle/deploy` | Enhanced: accepts strategy (rolling/blue-green/canary), environment, pre-deploy checks. |
| POST | `/api/v1/lifecycle/promote/{deployment_id}` | Move deployment to next stage. Enforce approval gates. |
| POST | `/api/v1/lifecycle/demote/{deployment_id}` | Move deployment to previous stage. |
| POST | `/api/v1/lifecycle/rollback/{deployment_id}` | Rollback to previous version in environment. |
| GET | `/api/v1/lifecycle/pipeline` | Return all stages with current agent versions in each. |
| GET | `/api/v1/lifecycle/environments` | List environments with health, deployed version, instance count. |
| GET | `/api/v1/lifecycle/diff` | Compare config between environments. Query: `?env1=staging&env2=production`. |
| GET | `/api/v1/lifecycle/history/{environment}` | Deployment history for an environment. |
| PUT | `/api/v1/lifecycle/gates` | Configure approval gates between stages. |
| GET | `/api/v1/lifecycle/health/{deployment_id}` | Post-deployment health metrics. |

All endpoints:
- JWT-authenticated, scoped to `tenant_id`.
- Return envelope: `{"data": ..., "meta": {"request_id": "...", "timestamp": "..."}}`.
- Mutations produce `AuditLog` entries.

---

## Frontend Deliverables

| File | Action |
|------|--------|
| `pages/LifecyclePage.tsx` | **MODIFY** — Visual pipeline + enhanced deploy form. |
| `components/lifecycle/PipelineView.tsx` | **CREATE** — Horizontal stage pipeline with version cards. |
| `components/lifecycle/StageColumn.tsx` | **CREATE** — Single stage column showing versions. |
| `components/lifecycle/DeployForm.tsx` | **CREATE** — Enhanced form with searchable dropdowns + strategy selector. |
| `components/lifecycle/EnvironmentCard.tsx` | **CREATE** — Environment status card with health, version, instances. |
| `components/lifecycle/StrategySelector.tsx` | **CREATE** — Rolling/Blue-Green/Canary picker with visual config (sliders, toggles). |
| `components/lifecycle/DiffView.tsx` | **CREATE** — Side-by-side config comparison between environments. |
| `components/lifecycle/DeploymentHistory.tsx` | **CREATE** — Timeline of deployments per environment. |
| `components/lifecycle/ApprovalGateConfig.tsx` | **CREATE** — Configure approval gates between stages. |
| `api/lifecycle.ts` | **MODIFY** — Add pipeline, diff, environments, promote, rollback calls. |

All components: dark/light mode via Tailwind `dark:` variants.

---

## Integration Points

- **Agents API**: Agent selector fetches from `/api/v1/agents` with search. Version selector fetches from `/api/v1/agents/{id}/versions`.
- **DLP (Agent 12)**: Pre-deploy DLP scan runs before promotion to Staging/Production.
- **Cost Engine (Agent 11)**: Pre-deploy cost estimate shown in deploy form.
- **AuditLog**: Log every deploy, promote, demote, rollback, gate config change.
- **Execution Engine**: Deployed agents in Production are the ones that serve execution requests.

---

## Acceptance Criteria

1. Visual pipeline shows lifecycle stages (Draft → Review → Staging → Production) with agent versions in each.
2. Agent / version selectors use searchable dropdowns, not raw ID text inputs.
3. Deployment strategy selector shows visual config (sliders for replica count and traffic %, toggles for blue-green).
4. Environment comparison (diff) view shows side-by-side config differences with highlighting.
5. Health monitoring shows post-deployment metrics (response time, error rate, throughput).
6. Approval gates are configurable between stages.
7. Zero raw ID inputs on any form.
8. Promote / demote / rollback actions work with audit trail.

---

## Files to Read

Read these files before writing any code to understand existing patterns:

```
backend/app/routes/lifecycle.py
backend/app/services/lifecycle_service.py
backend/app/models/lifecycle.py
backend/app/routes/agents.py              # for agent/version listing
frontend/src/pages/LifecyclePage.tsx
frontend/src/api/lifecycle.ts
frontend/src/components/ui/               # shadcn/ui primitives
```

---

## Files to Create / Modify

### Backend

```
backend/app/routes/lifecycle.py                            # MODIFY — add pipeline, diff, environments, promote, demote, health endpoints
backend/app/services/lifecycle_service.py                  # MODIFY — add pipeline, diff, environment, strategy logic
backend/app/services/lifecycle/strategies.py               # CREATE — Rolling, Blue-Green, Canary strategy implementations
backend/app/services/lifecycle/gates.py                    # CREATE — Approval gate logic
backend/app/services/lifecycle/health.py                   # CREATE — Post-deployment health monitoring
tests/test_lifecycle.py                                    # CREATE — endpoint + service tests
tests/test_lifecycle_strategies.py                         # CREATE — strategy-specific tests
```

### Frontend

```
frontend/src/pages/LifecyclePage.tsx                       # MODIFY
frontend/src/components/lifecycle/PipelineView.tsx         # CREATE
frontend/src/components/lifecycle/StageColumn.tsx          # CREATE
frontend/src/components/lifecycle/DeployForm.tsx           # CREATE
frontend/src/components/lifecycle/EnvironmentCard.tsx      # CREATE
frontend/src/components/lifecycle/StrategySelector.tsx     # CREATE
frontend/src/components/lifecycle/DiffView.tsx             # CREATE
frontend/src/components/lifecycle/DeploymentHistory.tsx    # CREATE
frontend/src/components/lifecycle/ApprovalGateConfig.tsx   # CREATE
frontend/src/api/lifecycle.ts                              # MODIFY
```

---

## Testing

```bash
# Backend — run from repo root
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/test_lifecycle.py tests/test_lifecycle_strategies.py --no-header -q

# Minimum coverage
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/test_lifecycle.py --cov=backend/app/routes/lifecycle --cov=backend/app/services/lifecycle_service --cov-fail-under=80 --no-header -q
```

Test cases must include:
- Pipeline endpoint returns all 4 stages with versions.
- Deploy with Rolling strategy creates correct deployment record.
- Deploy with Canary strategy records traffic percentage.
- Promote moves deployment to next stage.
- Promote to Staging with approval gate required returns 403 without approval.
- Rollback restores previous version.
- Diff endpoint returns differences between environments.
- Environment listing returns health status.
- API responses use envelope format.
- Endpoints reject unauthenticated requests (401).
- Queries scoped to `tenant_id`.

---

## Constraints

- Python 3.12, type hints, docstrings. Use `python3` not `python`.
- Always `PYTHONPATH=backend` for pytest.
- API envelope: `{"data": ..., "meta": {"request_id", "timestamp"}}`
- No raw JSON fields on any user-facing form.
- All credentials via SecretsManager, never in DB.
- Never use `password=value` directly — use dict unpacking.
- Do NOT read ROADMAP.md, INSTRUCTIONS.md, ARCHITECTURE.md.
- Tests must pass: `cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q`
