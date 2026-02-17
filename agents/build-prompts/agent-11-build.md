# Agent 11 — Cost Engine — Build Prompt

## Context

Token usage tracking, budget management, cost attribution, and forecasting. Build a complete cost management system: an immutable token ledger, a real-data dashboard, configurable budget enforcement (soft alerts + hard blocks), and chargeback export.

**Tech stack — Backend:** Python 3.12, FastAPI, SQLModel, Alembic, AsyncSession. **Frontend:** React 19, TypeScript strict, shadcn/ui, Tailwind CSS, React Flow. **Auth:** JWT + Keycloak. **Secrets:** HashiCorp Vault via `backend/app/secrets/manager.py`.

---

## What Already Exists

| File | Lines | Action |
|------|-------|--------|
| `frontend/src/pages/CostPage.tsx` | 334 | **EXTEND** — Usage chart (empty), budget form (Name/Scope/Limit/Period/Enforcement), alerts (empty). |
| `frontend/src/api/cost.ts` | 85 | **EXTEND** — Cost API client. |
| `backend/app/routes/cost.py` | 568 | **EXTEND** — Cost routes. |
| `backend/app/services/cost_service.py` | 797 | **EXTEND** — Cost service. |
| `backend/app/services/cost.py` | 650 | **KEEP** — Additional cost logic. |
| `backend/app/models/cost.py` | 403 | **KEEP** — Cost models including TokenLedger, Budget. |

---

## What to Build

### 1. Token Ledger

Immutable append-only table recording every LLM call:

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `execution_id` | UUID | FK to execution |
| `agent_id` | UUID | FK to agent |
| `model_id` | str | Model identifier (e.g., `gpt-4o`, `claude-3.5-sonnet`) |
| `provider` | str | Provider name (e.g., `openai`, `anthropic`) |
| `input_tokens` | int | Input token count |
| `output_tokens` | int | Output token count |
| `cost_usd` | Decimal | Calculated cost in USD |
| `timestamp` | datetime | When the call occurred |
| `tenant_id` | UUID | Tenant scope |
| `user_id` | UUID | User who triggered |
| `group_id` | UUID | Team/group for chargeback |

Insert on every execution step that calls an LLM. Table is append-only — no UPDATE or DELETE.

### 2. Cost Dashboard Redesign

- **Summary Cards:**
  - Total Spend (current period)
  - Spend vs Budget (progress bar with color)
  - Projected Spend (linear trend with up/down arrow)
  - Top Model by Cost (name + amount)

- **Usage Chart:** Stacked area chart by provider/model over time. Toggle: daily / weekly / monthly. Use `recharts` `<AreaChart>` with stacked areas.

- **Breakdown Table:** Switchable views — by Agent, by Model, by User, by Team. Each row: name, call count, total tokens, cost USD, % of total. Sortable columns.

- **Top Consumers:** Ranked horizontal bar chart of agents/users by cost.

### 3. Budget Enhancement

- **Budget Wizard:** Step-by-step form:
  1. Scope selector: Tenant / Team / Agent / User (searchable dropdown).
  2. Limit: Dollar amount input.
  3. Period: Daily / Weekly / Monthly.
  4. Enforcement: Soft alert (notify only) / Hard block (reject executions).

- **Utilization Bar:** Bar graph showing current spend vs limit per budget. Color: green < 75%, yellow 75–90%, red > 90%.

- **Alert Rules:** Notifications at 50%, 75%, 90%, 100% thresholds. Alerts stored in DB, shown in notification center.

- **Hard Block:** When budget exceeded and enforcement = hard, reject execution with HTTP 429 and explanation: `{"error": "Budget exceeded", "budget_id": "...", "limit": 100.00, "current_spend": 105.23}`.

### 4. Chargeback Reports

Export button → CSV or PDF with cost breakdown per team/department for a billing period. Columns: Team, Agent, Model, Calls, Tokens, Cost USD.

---

## Patterns to Follow

### Pattern 1 — Dify Token Tracking

**Source:** `dify/api/core/model_runtime/`

Dify tracks token usage per app call via callbacks in the model runtime. The LLM callback handler receives token counts after each call and stores usage in message records. Usage data is aggregated for the analytics dashboard.

**Adaptation:** Archon records usage in a dedicated `TokenLedger` table (not embedded in execution records) for immutability and query performance. Insert via execution engine hooks — after every LLM call completes, write a ledger entry. Cost is calculated using a model pricing table (`provider + model → price_per_1k_input, price_per_1k_output`).

### Pattern 2 — Dify Billing / Quota

**Source:** `dify/api/models/`

Dify has subscription-based quotas with usage tracking. When quota is exceeded, API calls are blocked and return a quota-exceeded error. Usage is checked before each model call.

**Adaptation:** Archon uses configurable budgets per scope (tenant / team / agent / user) with two enforcement modes: soft alerts (notifications at thresholds) and hard blocks (HTTP 429 rejection). Budget check runs as FastAPI middleware before execution, not at the model-call level. This prevents wasted compute on executions that will be blocked partway through.

---

## Backend Deliverables

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/cost/record` | Internal: record token usage from execution engine. Not user-facing. |
| GET | `/api/v1/cost/summary` | Summary stats. Query: `?period=monthly`. Returns total spend, budget utilization, projected spend, top model. |
| GET | `/api/v1/cost/breakdown` | Cost breakdown. Query: `?group_by=agent\|model\|user\|team`. Returns rows with name, calls, tokens, cost, percentage. |
| GET | `/api/v1/cost/chart` | Chart data. Query: `?period=daily&range=30d`. Returns time-series data grouped by provider/model. |
| POST | `/api/v1/cost/budgets` | Create budget with scope, limit, period, enforcement. |
| GET | `/api/v1/cost/budgets` | List budgets with current utilization. |
| GET | `/api/v1/cost/budgets/{id}/utilization` | Current spend vs limit for a budget. |
| PUT | `/api/v1/cost/budgets/{id}` | Update budget. |
| GET | `/api/v1/cost/export` | Export report. Query: `?format=csv&period=2024-01`. Returns file download. |
| — | Middleware | Budget enforcement middleware: check before execution, reject with 429 if hard limit exceeded. |

All endpoints:
- JWT-authenticated, scoped to `tenant_id`.
- Return envelope: `{"data": ..., "meta": {"request_id": "...", "timestamp": "..."}}`.
- Mutations produce `AuditLog` entries.

---

## Frontend Deliverables

| File | Action |
|------|--------|
| `pages/CostPage.tsx` | **MODIFY** — Wire up real data, add summary cards, chart, breakdown, budget UI. |
| `components/cost/SummaryCards.tsx` | **CREATE** — Four stat cards: total spend, spend vs budget, projected, top model. |
| `components/cost/UsageChart.tsx` | **CREATE** — Stacked area chart using `recharts`. Daily/weekly/monthly toggle. |
| `components/cost/BreakdownTable.tsx` | **CREATE** — Switchable group-by table (agent/model/user/team) with sortable columns. |
| `components/cost/TopConsumers.tsx` | **CREATE** — Ranked horizontal bar chart. |
| `components/cost/BudgetWizard.tsx` | **CREATE** — Step-by-step budget creation wizard. |
| `components/cost/BudgetBar.tsx` | **CREATE** — Utilization bar with color thresholds. |
| `components/cost/BudgetList.tsx` | **CREATE** — List of budgets with utilization bars. |
| `components/cost/ExportButton.tsx` | **CREATE** — Export to CSV/PDF with period selector. |
| `api/cost.ts` | **MODIFY** — Add summary, breakdown, chart, budget, export API calls. |

All components: dark/light mode via Tailwind `dark:` variants.

---

## Integration Points

- **Execution Engine**: After every LLM call, the execution engine must call `POST /api/v1/cost/record` (or invoke the cost service directly) to insert a ledger entry.
- **Budget Middleware**: Runs before execution start. If the user/team/agent has a hard-limit budget that is exceeded, the execution is rejected with 429.
- **Model Pricing Table**: Maintain a pricing config (JSON or DB table) mapping `(provider, model) → (input_price_per_1k, output_price_per_1k)`. Used by the record endpoint to calculate `cost_usd`.
- **AuditLog**: Log budget create/update/delete, export actions.
- **Notifications**: Budget threshold alerts feed into the notification system.

---

## Acceptance Criteria

1. Every LLM call during execution records token usage in the ledger (append-only).
2. Dashboard shows real cost data (not zeros or placeholders).
3. Usage chart renders with actual data, stacked by provider/model, with period toggle.
4. Breakdown table is switchable between agent / model / user / team views.
5. Budget enforcement works: soft alerts at 50/75/90/100% thresholds, hard block returns 429 when exceeded.
6. Export produces a valid CSV with cost data for the selected period.
7. Summary cards show: total spend, spend vs budget (progress bar), projected spend (trend), top model.
8. Budget wizard uses searchable scope selector, not raw text input.

---

## Files to Read

Read these files before writing any code to understand existing patterns:

```
backend/app/routes/cost.py
backend/app/services/cost_service.py
backend/app/services/cost.py
backend/app/models/cost.py
frontend/src/pages/CostPage.tsx
frontend/src/api/cost.ts
frontend/src/components/ui/               # shadcn/ui primitives
backend/app/services/execution_service.py  # where to hook ledger inserts
```

---

## Files to Create / Modify

### Backend

```
backend/app/routes/cost.py                                 # MODIFY — add summary, breakdown, chart, export, utilization endpoints
backend/app/services/cost_service.py                       # MODIFY — add summary, breakdown, chart, export logic
backend/app/services/cost/ledger.py                        # CREATE — token ledger insert + query logic
backend/app/services/cost/budget_enforcement.py            # CREATE — budget check middleware
backend/app/services/cost/pricing.py                       # CREATE — model pricing table + cost calculation
backend/app/services/cost/export.py                        # CREATE — CSV/PDF export logic
backend/app/middleware/budget.py                           # CREATE — FastAPI middleware for budget enforcement
tests/test_cost.py                                         # CREATE — endpoint + service tests
tests/test_cost_budget.py                                  # CREATE — budget enforcement tests
```

### Frontend

```
frontend/src/pages/CostPage.tsx                            # MODIFY
frontend/src/components/cost/SummaryCards.tsx               # CREATE
frontend/src/components/cost/UsageChart.tsx                 # CREATE
frontend/src/components/cost/BreakdownTable.tsx             # CREATE
frontend/src/components/cost/TopConsumers.tsx               # CREATE
frontend/src/components/cost/BudgetWizard.tsx               # CREATE
frontend/src/components/cost/BudgetBar.tsx                  # CREATE
frontend/src/components/cost/BudgetList.tsx                 # CREATE
frontend/src/components/cost/ExportButton.tsx               # CREATE
frontend/src/api/cost.ts                                   # MODIFY
```

---

## Testing

```bash
# Backend — run from repo root
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/test_cost.py tests/test_cost_budget.py --no-header -q

# Minimum coverage
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/test_cost.py --cov=backend/app/routes/cost --cov=backend/app/services/cost_service --cov-fail-under=80 --no-header -q
```

Test cases must include:
- Record token usage creates ledger entry with correct cost calculation.
- Ledger entries are immutable (no update/delete endpoints).
- Summary endpoint returns correct totals for period.
- Breakdown endpoint groups correctly by agent/model/user/team.
- Chart endpoint returns time-series data with correct grouping.
- Budget creation validates scope, limit, period, enforcement.
- Budget enforcement middleware returns 429 when hard limit exceeded.
- Budget enforcement middleware allows request when under limit.
- Soft alert budget logs alert but does not block.
- Export endpoint returns valid CSV.
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
