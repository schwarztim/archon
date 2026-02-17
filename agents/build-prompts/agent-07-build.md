# Agent 07 — Workflows Graph

## Role

You are a senior full-stack engineer building the visual Workflow Graph Editor for the Archon AI orchestration platform. You write production-grade TypeScript (React 19, strict mode) and Python (FastAPI, SQLModel). You follow every constraint listed below without exception.

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

Workflows orchestrate multiple agents into complex pipelines with branching, parallelism, and scheduling. The current implementation uses a JSON config step builder — this must be replaced with a visual React Flow graph editor. Workflows operate at a higher abstraction than agent graphs: nodes represent agent calls, conditions, loops, and parallel execution rather than individual LLM/tool operations.

---

## What Already Exists

| File | Lines | Action |
|------|-------|--------|
| `frontend/src/pages/WorkflowsPage.tsx` | 686 | **MODIFY** — List view + create modal with JSON step builder. Replace creation flow with visual graph editor |
| `frontend/src/api/workflows.ts` | 108 | **MODIFY** — Workflow API client. Extend with execution, schedule, and run history endpoints |
| `backend/app/routes/workflows.py` | 206 | **MODIFY** — In-memory CRUD + execute endpoint. Extend with schedule management, execution streaming |
| `backend/app/models/__init__.py` | 279 | **KEEP** — Reference for model patterns |

---

## What to Build

### Workflow Visual Editor

Replace the JSON config step builder with an embedded React Flow visual editor. Share React Flow infrastructure patterns established in Agent 02.

#### Node Types

Each node type has a distinct visual style and a configuration form panel (NO raw JSON anywhere):

**AgentCall Node**
- Visual: Agent icon + name, status indicator
- Config form:
  - Agent dropdown (searchable, from `GET /api/v1/agents`)
  - Input mapping: visual source field → target field mapper (drag lines or dropdown pairs)
  - Timeout: numeric input with unit selector (seconds/minutes)
  - Retry policy: max retries (0–5), backoff strategy (none/linear/exponential)
  - On-failure action: dropdown (stop workflow | skip step | use fallback agent | continue with error)
  - Fallback agent: dropdown (shown when on-failure = "use fallback agent")

**Condition Node**
- Visual: Diamond shape with condition label
- Config form:
  - IF condition builder: `[variable dropdown] [operator dropdown] [value input]`
  - Variables populated from outputs of upstream nodes
  - Operators: equals, not_equals, contains, greater_than, less_than, is_empty, matches_regex
  - Two output handles: "True" (green) and "False" (red)
  - Support AND/OR grouping for multiple conditions

**Parallel Node**
- Visual: Horizontal fork icon, shows branch count
- Config form:
  - Branch count (auto-calculated from connected edges)
  - Execution mode: All (wait for all) | Any (first to complete) | N of M
  - Timeout for entire parallel block

**Loop Node**
- Visual: Circular arrow icon with iteration count
- Config form:
  - Loop type: For Each (over array variable) | While (condition) | Fixed Count
  - For Each: source array variable dropdown
  - While: condition builder (same as Condition node)
  - Fixed Count: numeric input
  - Max iterations safety limit
  - Item variable name (accessible inside loop body)

**Sub-workflow Node**
- Visual: Nested workflow icon
- Config form:
  - Workflow selector dropdown (from `GET /api/v1/workflows`)
  - Input mapping (same pattern as AgentCall)
  - Async toggle: wait for completion or fire-and-forget

**Merge Node**
- Visual: Converging arrow icon
- Config form:
  - Merge strategy: Wait for All | Wait for Any | Wait for N
  - Timeout for merge
  - Output mapping: how to combine results from incoming branches

**Delay Node**
- Visual: Clock icon with duration label
- Config form:
  - Duration: numeric + unit dropdown (seconds/minutes/hours/days)
  - Or: specific datetime picker ("Wait until")

#### Canvas Features

- Drag nodes from sidebar palette onto canvas
- Connect nodes by dragging from output handle to input handle
- Edge labels for data passing (click edge to configure field mapping)
- Mini-map in corner
- Zoom controls
- Auto-layout button (dagre layout)
- Undo/redo (Ctrl+Z / Ctrl+Shift+Z)
- Copy/paste nodes
- Node validation indicators (red border if misconfigured)
- Canvas saves to `graph_definition` JSON on the workflow model

---

### Schedule Builder

Replace raw cron strings with a visual cron builder component.

**Presets (radio buttons):**
- Every Hour
- Every Day at 9:00 AM
- Every Monday at 9:00 AM
- Every 1st of Month at 9:00 AM
- Custom

**Custom Builder (shown when "Custom" selected):**
- Minute: dropdown (every minute, every 5 min, every 15 min, every 30 min, specific minute 0–59)
- Hour: dropdown (every hour, specific hour 0–23 with AM/PM labels)
- Day of Month: dropdown (every day, specific day 1–31)
- Month: dropdown (every month, specific month Jan–Dec)
- Day of Week: checkbox group (Mon–Sun)

**Preview:**
- Human-readable summary: "Runs every Monday at 9:00 AM UTC"
- Next 5 run times displayed below the builder
- Timezone selector (defaults to user's timezone)

---

### Execution

**`POST /api/v1/workflows/{id}/execute`**
- Creates a workflow execution record
- Runs steps sequentially following graph edges
- Parallel nodes fork execution into concurrent branches
- Condition nodes evaluate and follow true/false path
- Loop nodes iterate as configured
- Records per-step: status, duration, input/output, agent execution ID (for AgentCall nodes)

**WebSocket `/ws/workflows/{workflow_id}/executions/{execution_id}`**
- Stream step status updates in real-time
- Events: `step.started`, `step.completed`, `step.failed`, `workflow.completed`, `workflow.failed`
- Include step_id and step_type in each event

**Step Failure Handling (per-node configurable):**
- **Stop** — Fail entire workflow immediately
- **Skip** — Mark step as skipped, continue to next
- **Retry** — Retry with configured backoff, then fail or skip
- **Fallback** — Run fallback agent, use its output

---

### Run History

**Table of past workflow runs:**
- Columns: Run ID, Status badge, Trigger (manual/scheduled), Duration, Started At
- Row click → expandable detail showing per-step timeline
- Step timeline: same pattern as Agent 06's StepTimeline component
- For AgentCall steps: link to the agent's execution detail page (Agent 06)

**Filters:**
- Status: All | Running | Completed | Failed
- Trigger: All | Manual | Scheduled
- Date range picker

---

## OSS Patterns to Follow

### 1. Dify Workflow Editor (`dify/web/app/components/workflow/nodes/`)
Dify has dedicated workflow node types: LLM, Knowledge Retrieval, Question Classifier, IF/ELSE, Iteration, Variable Aggregator, Code, HTTP Request, Template Transform. Each node type has a panel component with rich forms. Nodes connect via typed handles (string, array, object). **Adaptation**: Archon workflow nodes are higher-level — an AgentCall node encapsulates what Dify would represent as multiple LLM + Tool + Retrieval nodes. Use the same per-node-type panel pattern with rich config forms, but the node types map to agent-level orchestration primitives.

### 2. Flowise Chatflow Canvas
Flowise's entire paradigm is a visual chatflow builder using React Flow. Nodes are dragged from a sidebar, connected on canvas, and configured via side panels. The canvas state serializes to JSON and saves to the database. **Adaptation**: Reuse the same React Flow canvas patterns from Agent 02's agent builder, but with workflow-specific node types. The sidebar palette shows workflow node types (AgentCall, Condition, Parallel, etc.) instead of agent node types (LLM, Tool, etc.).

### 3. Coze Studio Workflow Nodes
Coze separates "bot" nodes (high-level, orchestrate entire bots) from "workflow" nodes (lower-level, individual operations). Workflows in Coze can call bots as steps. **Adaptation**: This is exactly the Archon pattern — Agent 02 builds low-level agent graphs (LLM/tool nodes), and Agent 07 builds high-level workflow graphs (agent call nodes). Maintain this clear separation.

---

## Frontend Deliverables

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/pages/WorkflowsPage.tsx` | **MODIFY** | Replace JSON step builder with visual editor. List view retains current layout |
| `frontend/src/components/workflows/WorkflowCanvas.tsx` | **CREATE** | React Flow canvas for workflow editing: sidebar palette, canvas, node config panel |
| `frontend/src/components/workflows/nodes/AgentCallNode.tsx` | **CREATE** | Agent call node: agent selector, input mapping, timeout, retry, on-failure |
| `frontend/src/components/workflows/nodes/ConditionNode.tsx` | **CREATE** | Condition node: visual if/else builder with variable/operator/value rows |
| `frontend/src/components/workflows/nodes/ParallelNode.tsx` | **CREATE** | Parallel fork node: branch count, execution mode |
| `frontend/src/components/workflows/nodes/LoopNode.tsx` | **CREATE** | Loop node: for-each, while, fixed count |
| `frontend/src/components/workflows/nodes/SubWorkflowNode.tsx` | **CREATE** | Sub-workflow node: workflow selector, input mapping, async toggle |
| `frontend/src/components/workflows/nodes/MergeNode.tsx` | **CREATE** | Merge node: strategy, timeout, output mapping |
| `frontend/src/components/workflows/nodes/DelayNode.tsx` | **CREATE** | Delay node: duration or specific time |
| `frontend/src/components/workflows/CronBuilder.tsx` | **CREATE** | Visual cron picker with presets, custom builder, preview, timezone |
| `frontend/src/components/workflows/WorkflowRunHistory.tsx` | **CREATE** | Run history table with filters and expandable step detail |
| `frontend/src/api/workflows.ts` | **MODIFY** | Add execute, schedule CRUD, run history endpoints |

---

## Backend Deliverables

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /api/v1/workflows/{id}/execute` | POST | Execute a workflow, create run record |
| `GET /api/v1/workflows/{id}/runs` | GET | List workflow run history with filters |
| `GET /api/v1/workflows/{id}/runs/{run_id}` | GET | Get run detail with per-step data |
| `WebSocket /ws/workflows/{id}/executions/{exec_id}` | WS | Stream step events during execution |
| `PUT /api/v1/workflows/{id}/schedule` | PUT | Set or update workflow schedule (cron) |
| `DELETE /api/v1/workflows/{id}/schedule` | DELETE | Remove workflow schedule |
| `GET /api/v1/workflows/{id}/schedule/preview` | GET | Get next N run times for a cron expression |

**Service changes:**
- Add `execute_workflow()` method — graph traversal engine that follows edges, handles branching/parallelism
- Add `WorkflowRun` model or use `steps` JSON field on a workflow execution record
- Cron schedule storage and preview logic

---

## Integration Points

| Agent | Integration |
|-------|------------|
| Agent 01 | Agent model — AgentCall nodes reference agents by ID, need agent name/icon |
| Agent 02 | React Flow patterns — share canvas infrastructure (minimap, controls, layout) |
| Agent 06 | Execution engine — AgentCall steps create agent executions, link to execution detail |
| Agent 08 | Model router — agents within workflow may use routed models |

---

## Acceptance Criteria

1. Workflow creation and editing uses a visual React Flow graph editor, not JSON forms
2. AgentCall node has agent dropdown, visual input mapping form, retry config, and on-failure action
3. Condition node has visual if/else builder with variable/operator/value rows and AND/OR grouping
4. Parallel node correctly forks execution and Merge node combines results
5. Loop node supports for-each, while, and fixed count iteration modes
6. Schedule uses visual cron picker with presets — no raw cron string visible to users
7. Cron builder shows human-readable preview and next 5 run times
8. Workflow execution shows real-time step progress via WebSocket
9. Run history shows per-step detail with expandable timeline
10. AgentCall steps link to the corresponding agent execution detail page
11. Group filter on workflow list page works correctly
12. Zero raw JSON config visible on any workflow creation or editing form
13. Node validation: red border and tooltip on misconfigured nodes, cannot save invalid graph

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
