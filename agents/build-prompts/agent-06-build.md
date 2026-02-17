# Agent 06 — Executions & Tracing

## Role

You are a senior full-stack engineer building the Execution Engine, real-time tracing, and execution history UI for the Archon AI orchestration platform. You write production-grade TypeScript (React 19, strict mode) and Python (FastAPI, SQLModel). You follow every constraint listed below without exception.

---

## Platform Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLModel, Alembic, AsyncSession |
| Frontend | React 19, TypeScript strict, shadcn/ui, Tailwind CSS, React Flow (@xyflow/react) |
| Auth | JWT via Keycloak |
| Secrets | HashiCorp Vault via `backend/app/secrets/manager.py` |

---

## Context

The execution engine is responsible for running agents, recording per-step traces, streaming real-time progress via WebSocket, and presenting execution history with full traceability. This is the runtime heart of the platform — every agent invocation flows through this system.

---

## What Already Exists

| File | Lines | Action |
|------|-------|--------|
| `frontend/src/pages/ExecutionsPage.tsx` | 150 | **MODIFY** — Currently an empty state with play icon and basic table structure. Extend to rich list with filters and "Run Agent" button |
| `frontend/src/api/executions.ts` | 42 | **MODIFY** — Basic API client. Extend with create, WebSocket, replay |
| `backend/app/routes/executions.py` | 164 | **MODIFY** — Read-only list/get endpoints. Add execution creation, WebSocket streaming, replay |
| `backend/app/services/execution_service.py` | 326 | **MODIFY** — Execution service. Extend with creation logic, step recording, and streaming |
| `backend/app/models/__init__.py` | 279 | **KEEP** — Execution model exists with: agent_id, status, input_data, output_data, error, steps, metrics |

---

## What to Build

### Backend

#### `POST /api/v1/executions`

Create and run an agent execution.

**Request:**
```json
{
  "agent_id": "uuid",
  "input": { "message": "..." },
  "config_overrides": {
    "temperature": 0.5,
    "max_tokens": 2000
  }
}
```

**Behavior:**
1. Validate agent exists and belongs to tenant
2. Create Execution record with status `pending`
3. Transition to `running`
4. Execute agent graph (stub the actual LLM/tool calls initially — produce realistic mock step data)
5. Record per-step data in `steps` JSON field:
   - `step_name` — human-readable label
   - `step_type` — `llm_call` | `tool_call` | `condition` | `transform` | `retrieval`
   - `status` — `pending` | `running` | `completed` | `failed`
   - `started_at`, `completed_at`, `duration_ms`
   - `token_usage` — `{ prompt_tokens, completion_tokens, total_tokens }`
   - `cost` — float in USD
   - `input` — step input data
   - `output` — step output data
   - `error` — error message if failed
6. Record overall metrics: `total_duration_ms`, `total_tokens`, `total_cost`
7. Set final status: `completed` or `failed`

**Response:**
```json
{
  "data": {
    "id": "uuid",
    "agent_id": "uuid",
    "status": "running",
    "created_at": "ISO8601"
  },
  "meta": { "request_id": "...", "timestamp": "..." }
}
```

#### `WebSocket /ws/executions/{execution_id}`

Real-time step event streaming. Authenticate via query param `?token=JWT`.

**Event types:**
```json
{ "event": "execution.started", "data": { "execution_id": "...", "agent_id": "..." } }
{ "event": "step.started", "data": { "step_index": 0, "step_name": "...", "step_type": "llm_call" } }
{ "event": "step.completed", "data": { "step_index": 0, "duration_ms": 1200, "tokens": 450, "cost": 0.003 } }
{ "event": "step.failed", "data": { "step_index": 1, "error": "Timeout after 30s" } }
{ "event": "tool.called", "data": { "step_index": 2, "tool_name": "web_search", "input": {...} } }
{ "event": "llm.response", "data": { "step_index": 0, "chunk": "partial response text..." } }
{ "event": "execution.completed", "data": { "total_duration_ms": 5400, "total_cost": 0.012 } }
{ "event": "execution.failed", "data": { "error": "Step 3 failed: API timeout" } }
```

#### `GET /api/v1/executions/{id}` (Enhanced)

Return full execution with expanded step detail, agent name, and metrics summary.

#### `POST /api/v1/executions/{id}/replay`

Re-run an execution with same or modified input.

**Request:**
```json
{
  "input_override": { "message": "modified input" }
}
```

If `input_override` is omitted, reuse original input. Creates a new Execution linked to the same agent.

#### Execution Status Flow

```
pending → running → completed
                  → failed
```

---

### Frontend

#### Execution List Page (`/executions`)

**Table columns:**
- ID (truncated UUID, click to copy full)
- Agent Name (linked to agent detail)
- Status badge: `pending` (gray), `running` (blue pulse), `completed` (green), `failed` (red)
- Duration (formatted: "1.2s", "45s", "2m 30s")
- Cost (formatted: "$0.003")
- Created At (relative: "2 min ago", hover for full timestamp)

**Filters:**
- Status dropdown: All | Pending | Running | Completed | Failed
- Agent dropdown: populated from user's agents
- Date range picker: start date → end date

**Actions:**
- "Run Agent" button → opens RunAgentDialog
- Row click → navigates to ExecutionDetailPage
- Bulk actions: delete selected

**Polling:**
- Auto-refresh list every 10 seconds when any execution is `running`

#### Execution Detail Page (`/executions/{id}`)

**Header:**
- Agent name (linked) + agent icon
- Status badge (large)
- Duration, total tokens, total cost
- "Re-run" button → opens RunAgentDialog pre-filled
- "Delete" button with confirmation

**Tab 1 — Timeline View:**
- Vertical step timeline (top to bottom)
- Each step: status icon, name, type badge, duration, token count, cost
- Click step to expand: shows input data (syntax-highlighted JSON), output data, error (if any)
- Running steps show spinner animation
- Failed steps show red border with error message and stack trace

**Tab 2 — Graph View:**
- React Flow canvas rendering the agent's graph
- Nodes colored by execution status:
  - Green: completed
  - Blue (pulsing): running
  - Red: failed
  - Gray: pending / not yet reached
- Click node → shows step detail panel (same data as timeline expand)
- Edge animations for active paths

**Tab 3 — Raw Data:**
- Full JSON view of execution record (collapsible sections)
- Copy button for full JSON

**WebSocket Integration:**
- On page load, if execution is `running`, connect to WebSocket
- Update timeline steps in real-time as events arrive
- Update graph node colors in real-time
- Auto-disconnect when execution completes/fails

#### Run Agent Dialog

- Agent selector dropdown (searchable, shows agent icon + name)
- Input form: JSON editor with syntax highlighting and validation
- Config overrides section (collapsible): temperature slider, max_tokens input
- "Run" button → calls POST /executions → navigates to detail page
- Pre-fill support: when launched from "Re-run", populate agent and input

---

## OSS Patterns to Follow

### 1. Dify Workflow Run Tracing (`dify/web/app/components/workflow/run/`)
Dify shows a step-by-step trace with expandable nodes. Each node displays input, output, token usage, and duration. A miniature graph view highlights the currently executing step. **Adaptation**: Implement the same timeline + graph dual-view pattern. Add cost tracking per step (Dify doesn't track cost). Use the `steps` JSON field on the Execution model to store per-step trace data rather than a separate table.

### 2. Dify Execution Recording (`dify/api/core/workflow/`)
Dify records execution events in a `workflow_node_executions` table with status, inputs, outputs, and metadata per node. Events are emitted via a callback system during execution. **Adaptation**: Use the existing Execution model's `steps` JSON field to store per-step data. Emit WebSocket events as each step transitions. The execution service acts as the callback handler.

### 3. Coze Studio Debug/Test (`coze-studio`)
Coze provides a test panel where users input test messages and see real-time responses with trace information. The trace shows which tools were called, what the LLM generated, and performance metrics. **Adaptation**: The "Run Agent" dialog serves a similar purpose — accessible from the executions page, it lets users test any agent with custom input and immediately see traced results.

---

## Backend Deliverables

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/executions` | POST | Create and run an execution |
| `/ws/executions/{id}` | WebSocket | Stream step events in real-time |
| `/api/v1/executions/{id}` | GET | Enhanced with full step detail and metrics |
| `/api/v1/executions/{id}/replay` | POST | Re-run with same or modified input |

**Service changes:**
- `execution_service.py` — Add `create_execution()`, `run_execution()`, `replay_execution()`, `stream_events()` methods
- Step recording logic: capture per-step timing, tokens, cost, input/output
- WebSocket manager: maintain active connections, broadcast events per execution

---

## Frontend Deliverables

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/pages/ExecutionsPage.tsx` | **MODIFY** | Rich execution list with status/agent/date filters, "Run Agent" button, auto-refresh |
| `frontend/src/pages/ExecutionDetailPage.tsx` | **CREATE** | Timeline view + graph view + raw data tabs, WebSocket real-time updates |
| `frontend/src/components/executions/StepTimeline.tsx` | **CREATE** | Vertical step timeline with expand/collapse, status icons, metrics per step |
| `frontend/src/components/executions/ExecutionGraph.tsx` | **CREATE** | React Flow graph with nodes colored by execution status, real-time updates |
| `frontend/src/components/executions/RunAgentDialog.tsx` | **CREATE** | Agent selector, JSON input editor, config overrides, run button |
| `frontend/src/api/executions.ts` | **MODIFY** | Add `createExecution()`, `replayExecution()`, `connectWebSocket()` |

**Routing:**
- Add `/executions/:id` route to the app router pointing to `ExecutionDetailPage`

---

## Integration Points

| Agent | Integration |
|-------|------------|
| Agent 01 | Agent model — execution references agent_id, needs agent name/icon for display |
| Agent 02 | Graph definition — ExecutionGraph reuses React Flow rendering with status overlays |
| Agent 05 | Agent list — RunAgentDialog uses agent dropdown |
| Agent 08 | Model router — execution may log which model was selected by the router |
| Agent 12 | Security — DLP checks may run as execution steps |

---

## Acceptance Criteria

1. `POST /api/v1/executions` creates and runs an execution, recording per-step data
2. WebSocket streams step events (`step.started`, `step.completed`, `step.failed`, `tool.called`, `llm.response`) in real-time
3. Execution detail page shows step-by-step timeline with expand/collapse per step
4. Each step displays tokens, cost, duration, input data, and output data
5. Graph view shows agent nodes colored by execution status (green/blue/red/gray)
6. Execution list page has working status, agent, and date range filters
7. "Run Agent" button from ExecutionsPage opens dialog, creates execution, and navigates to detail
8. Failed steps show error details including error message and stack trace
9. "Re-run" button creates a new execution with pre-filled input from the original
10. WebSocket auto-connects for running executions and disconnects on completion
11. Execution list auto-refreshes when any execution is in `running` state
12. All monetary values formatted consistently (USD with appropriate precision)

---

## Constraints

1. **Response Envelope** — Every API response uses the standard envelope: `{ "data": T, "meta": { "request_id", "timestamp" } }`. Errors: `{ "error": { "code", "message", "details" } }`.
2. **JWT Auth** — Every endpoint requires a valid JWT Bearer token. Use `get_current_user` dependency. No anonymous access. WebSocket authenticates via `?token=JWT` query parameter.
3. **Vault Secrets** — All credentials (API keys, OAuth tokens) are stored and retrieved via `SecretsManager` (`backend/app/secrets/manager.py`). Never store secrets in the database or environment variables at runtime.
4. **Tenant Scoping** — All database queries must be scoped to `tenant_id` from the JWT. Users must never see or modify another tenant's data.
5. **Audit Logging** — All create, update, and delete operations must produce an `AuditLog` entry with: actor, action, resource_type, resource_id, before/after diff, timestamp.
6. **Test Coverage** — Minimum 80% line coverage for all new code. Write unit tests for services, integration tests for API routes, and component tests for React components.
7. **Dark/Light Mode** — All UI components must render correctly in both dark and light themes. Use Tailwind's `dark:` variants. Never hardcode colors.
8. **Accessibility** — All interactive elements must have ARIA labels. All forms must be keyboard-navigable. Color is never the sole indicator of state.
9. **TypeScript Strict** — `strict: true` in tsconfig. No `any` types. No `@ts-ignore`. All props interfaces explicitly defined.
10. **SQLModel + Alembic** — All schema changes require an Alembic migration. Use `AsyncSession` for all database operations. No raw SQL unless absolutely necessary.
11. **Error Handling** — Backend: raise `HTTPException` with appropriate status codes. Frontend: try/catch with toast notifications for user-facing errors. Never swallow errors silently.
12. **No Placeholder Code** — Every function must be fully implemented. No `TODO`, `FIXME`, `pass`, or `...` in delivered code. Stub integrations with realistic mock data if the dependency doesn't exist yet.
