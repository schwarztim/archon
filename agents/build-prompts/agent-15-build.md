# Agent 15 — MCP Apps Engine — Build Prompt

## Context

You are building the **MCP Apps Engine** for the Archon AI orchestration platform. This module enables interactive UI components (tables, charts, forms, approval panels) to be embedded directly in agent chat responses via the MCP (Model Context Protocol). The backend already exists — the frontend has **zero implementation**. Users currently cannot see or interact with MCP apps at all.

**Stack:** Backend: Python 3.12, FastAPI, SQLModel, Alembic, AsyncSession. Frontend: React 19, TypeScript strict, shadcn/ui, Tailwind, React Flow. Auth: JWT via Keycloak. Secrets: HashiCorp Vault via `backend/app/secrets/manager.py`.

---

## What Already Exists

| File | Lines | Status |
|------|-------|--------|
| `backend/app/routes/mcp_interactive.py` | 206 | Component sessions, render, action endpoints. **KEEP backend.** |
| `backend/app/services/mcp_interactive_service.py` | 359 | MCP interactive service. **KEEP.** |
| `backend/app/models/mcp_interactive.py` | 105 | MCP interactive models. **KEEP.** |
| **Frontend** | 0 | **ZERO implementation.** This feature is completely invisible to users. **BUILD from scratch.** |

---

## What to Build

### 1. MCP Chat Interface

A chat page/component where users interact with MCP-enabled agents:

- **Message layout:** Chat bubble layout with user messages on the right, agent responses on the left
- **Text responses:** Rendered as markdown in chat bubbles
- **Component responses:** When an agent response includes MCP component data (a `components` array in the response payload), render each component inline in the chat below the text
- **Input area:** Text input with send button, supports Enter to send, Shift+Enter for newline
- **Session indicator:** Shows active session ID, connection status

### 2. Component Library (7 types)

Build a `ComponentRenderer` that maps component `type` to a React component:

| Type | Component | Description |
|------|-----------|-------------|
| `data_table` | `DataTable` | Sortable, paginated table rendered from agent data. Columns defined by agent. Supports row selection. |
| `chart` | `ChartComponent` | Bar / Line / Pie chart using `recharts`. Chart type, data, and options defined by agent payload. |
| `form` | `DynamicForm` | Agent defines form fields (text, select, checkbox, date, number). User fills in → submits → data sent back to agent. Validation rules from agent. |
| `approval` | `ApprovalPanel` | Approve / Reject buttons with comment textarea. Sends decision as action back to agent. Shows approval status after submission. |
| `code` | `CodeEditor` | Read-only or editable code block with syntax highlighting (use `@monaco-editor/react` or `react-syntax-highlighter`). Language auto-detected or specified by agent. |
| `markdown` | `MarkdownViewer` | Rich markdown rendering with support for tables, code blocks, images, links. |
| `image_gallery` | `ImageGallery` | Grid of images from agent output. Click to expand. Supports captions. |

Each component receives `props` (data/config) and `actions` (available user actions) from the agent response.

### 3. Interactive Actions

When a user interacts with a component (clicks a button, submits a form, selects a table row):

1. Capture the action: `{ action_type: string, component_id: string, payload: any }`
2. Send via `POST /api/v1/mcp/sessions/{id}/action`
3. Agent processes the action and may respond with:
   - New text message
   - Updated components (replacing previous ones)
   - New components (appended to chat)
4. UI updates in real-time to reflect agent response

### 4. Sandboxed Rendering

Components render in a **sandboxed environment** to prevent XSS:

- Use Shadow DOM (`attachShadow({ mode: 'closed' })`) or an iframe sandbox
- Component code cannot access parent page state, cookies, or localStorage
- Styles are scoped to the component container
- Event handlers are mediated through the `ComponentRenderer` — no direct DOM access

### 5. Session State

- Each conversation has a **session** (created via `POST /api/v1/mcp/sessions`)
- Components maintain state within the session (e.g., form partially filled, table sort state)
- Session data stored server-side — refreshing the page restores session state
- Session expires after configurable timeout (default: 30 minutes of inactivity)

### 6. MCP Apps Page

New page accessible from the sidebar navigation:

- **Apps listing:** Grid of available MCP apps (agents with MCP capabilities) showing: app name, description, icon, category
- **Click to open:** Opens the chat interface with that specific MCP app
- **Recent sessions:** List of recent/active sessions the user can resume
- **Search/filter:** Filter apps by category or name

---

## Patterns to Follow

### Pattern 1: Original Design — Adaptive Cards Pattern

MCP Apps is a novel concept not found in Dify, Flowise, or Coze. Designed from first principles based on Microsoft Copilot's adaptive cards and Slack's Block Kit.

**Pattern:** Agent responses include a `components` array alongside text. Each component has a `type`, `props`, and optional `actions`. A `ComponentRenderer` maps `type` → React component.

```typescript
interface MCPResponse {
  text: string;
  components?: MCPComponent[];
}

interface MCPComponent {
  id: string;
  type: 'data_table' | 'chart' | 'form' | 'approval' | 'code' | 'markdown' | 'image_gallery';
  props: Record<string, unknown>;
  actions?: MCPAction[];
}

interface MCPAction {
  action_type: string;
  label: string;
  payload?: Record<string, unknown>;
}
```

`ComponentRenderer` is a simple switch/map:

```typescript
const COMPONENT_MAP: Record<string, React.ComponentType<MCPComponentProps>> = {
  data_table: DataTable,
  chart: ChartComponent,
  form: DynamicForm,
  approval: ApprovalPanel,
  code: CodeEditor,
  markdown: MarkdownViewer,
  image_gallery: ImageGallery,
};
```

### Pattern 2: Coze Studio Plugin UI

**Source:** Coze plugins return structured data that renders as cards in the chat.

**Adaptation:** Extend the card concept to full interactive components (tables, charts, forms) — not just static cards. Key difference: Coze cards are read-only; MCP components support bidirectional interaction via the action system.

---

## Backend Deliverables

Backend mostly exists — verify endpoints work and extend as needed:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/mcp/sessions` | Create a new MCP session for a specific app |
| `GET` | `/api/v1/mcp/sessions/{id}` | Get session state and history |
| `POST` | `/api/v1/mcp/sessions/{id}/message` | Send message, receive response with text + components |
| `POST` | `/api/v1/mcp/sessions/{id}/action` | Send component action (form submit, button click, etc.) |
| `GET` | `/api/v1/mcp/apps` | List available MCP apps |
| `GET` | `/api/v1/mcp/apps/{id}` | Get MCP app details |

All endpoints return envelope format: `{"data": ..., "meta": {"request_id": "...", "timestamp": "..."}}`.

All endpoints require JWT auth. All queries scoped to `tenant_id`.

---

## Frontend Deliverables

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/pages/MCPAppsPage.tsx` | **CREATE** | MCP Apps listing page + embedded chat interface |
| `frontend/src/components/mcp/ChatInterface.tsx` | **CREATE** | Chat bubble layout with message input |
| `frontend/src/components/mcp/MessageBubble.tsx` | **CREATE** | Individual message bubble (user vs. agent styling) |
| `frontend/src/components/mcp/ComponentRenderer.tsx` | **CREATE** | Maps component type → React component, handles sandboxing |
| `frontend/src/components/mcp/ComponentSandbox.tsx` | **CREATE** | Shadow DOM / iframe sandbox wrapper |
| `frontend/src/components/mcp/components/DataTable.tsx` | **CREATE** | Sortable, paginated table from agent data |
| `frontend/src/components/mcp/components/ChartComponent.tsx` | **CREATE** | Bar/Line/Pie chart via recharts |
| `frontend/src/components/mcp/components/DynamicForm.tsx` | **CREATE** | Agent-defined form with validation |
| `frontend/src/components/mcp/components/ApprovalPanel.tsx` | **CREATE** | Approve/Reject with comments |
| `frontend/src/components/mcp/components/CodeEditor.tsx` | **CREATE** | Syntax-highlighted code block |
| `frontend/src/components/mcp/components/MarkdownViewer.tsx` | **CREATE** | Rich markdown rendering |
| `frontend/src/components/mcp/components/ImageGallery.tsx` | **CREATE** | Image grid with lightbox expand |
| `frontend/src/api/mcp.ts` | **CREATE** | MCP API client (sessions, messages, actions, apps) |

All components must support dark/light mode via Tailwind classes.

---

## Integration Points

- **Sidebar Navigation:** Add "MCP Apps" entry to the sidebar. Icon: `LayoutGrid` or `AppWindow` from lucide-react.
- **Router:** Add route `/mcp-apps` and `/mcp-apps/:appId` to the React Router configuration.
- **Agent Chat (if exists):** MCP components could also render in existing agent chat interfaces if they return MCP component data.
- **Auth:** All API calls include JWT token. Session creation validates user has access to the requested MCP app.
- **Recharts:** Add `recharts` as a frontend dependency for chart rendering.
- **Syntax Highlighting:** Add `react-syntax-highlighter` or `@monaco-editor/react` for code blocks.

---

## Acceptance Criteria

1. **PASS/FAIL:** MCP Apps page is accessible from sidebar navigation and shows available apps.
2. **PASS/FAIL:** Chat interface renders messages in a bubble layout (user right, agent left).
3. **PASS/FAIL:** At least 5 component types render inline in chat when agent response includes `components` data.
4. **PASS/FAIL:** `DataTable` component supports column sorting and pagination.
5. **PASS/FAIL:** `DynamicForm` component submits form data back to the agent via the action endpoint.
6. **PASS/FAIL:** `ApprovalPanel` sends approve/reject action to agent and shows updated status.
7. **PASS/FAIL:** Components render in a sandboxed environment (Shadow DOM or iframe) — no access to parent page state.
8. **PASS/FAIL:** Session state persists across messages within the same conversation.

---

## Files to Read Before Starting

- `backend/app/routes/mcp_interactive.py` — Existing backend endpoints
- `backend/app/services/mcp_interactive_service.py` — Existing service logic
- `backend/app/models/mcp_interactive.py` — Existing data models
- `frontend/src/App.tsx` or `frontend/src/router.tsx` — Router configuration for adding new route
- `frontend/src/components/layout/Sidebar.tsx` — Sidebar navigation for adding MCP Apps link
- `frontend/src/api/` — Existing API client patterns to follow
- `backend/app/secrets/manager.py` — SecretsManager interface

---

## Files to Create / Modify

| File | Action | Notes |
|------|--------|-------|
| `frontend/src/pages/MCPAppsPage.tsx` | CREATE | Main page with app grid + chat |
| `frontend/src/components/mcp/ChatInterface.tsx` | CREATE | Chat layout component |
| `frontend/src/components/mcp/MessageBubble.tsx` | CREATE | Message bubble styling |
| `frontend/src/components/mcp/ComponentRenderer.tsx` | CREATE | Type → component mapper |
| `frontend/src/components/mcp/ComponentSandbox.tsx` | CREATE | Sandbox wrapper |
| `frontend/src/components/mcp/components/DataTable.tsx` | CREATE | Table component |
| `frontend/src/components/mcp/components/ChartComponent.tsx` | CREATE | Chart component |
| `frontend/src/components/mcp/components/DynamicForm.tsx` | CREATE | Form component |
| `frontend/src/components/mcp/components/ApprovalPanel.tsx` | CREATE | Approval component |
| `frontend/src/components/mcp/components/CodeEditor.tsx` | CREATE | Code block component |
| `frontend/src/components/mcp/components/MarkdownViewer.tsx` | CREATE | Markdown component |
| `frontend/src/components/mcp/components/ImageGallery.tsx` | CREATE | Image grid component |
| `frontend/src/api/mcp.ts` | CREATE | API client |
| `frontend/src/App.tsx` or router config | MODIFY | Add MCP Apps route |
| `frontend/src/components/layout/Sidebar.tsx` | MODIFY | Add MCP Apps nav link |
| `frontend/package.json` | MODIFY | Add recharts, syntax highlighter deps |

---

## Testing

```bash
# Run all tests
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q

# Run MCP-specific tests
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ -k mcp --no-header -q

# Frontend type check
cd ~/Scripts/Archon/frontend && npx tsc --noEmit
```

Target: ≥80% test coverage for new code.

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
