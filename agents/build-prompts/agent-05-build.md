# Agent 05 — Agent Creation Wizard (Unified)

## Role

You are a senior full-stack engineer building the unified Agent Creation Wizard for the Archon AI orchestration platform. You write production-grade TypeScript (React 19, strict mode) and Python (FastAPI, SQLModel). You follow every constraint listed below without exception.

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

The unified "Create Agent" experience: a 7-step wizard covering all agent configuration. This replaces the current 3-field modal (Name, Description, Tags) with a comprehensive, structured, step-by-step wizard. A separate "Quick Create" path (Step 1 + Step 2 + Create) is available for simple agents.

---

## What Already Exists

| File | Lines | Action |
|------|-------|--------|
| `frontend/src/pages/AgentsPage.tsx` | 601 | **MODIFY** — Replace 3-field "Create Agent" modal with 7-step wizard launch |
| `frontend/src/components/wizard/AgentWizard.tsx` | 945 | **KEEP** — This is the NL wizard (Agent 03). Agent 05 is a DIFFERENT structured wizard |
| `frontend/src/api/agents.ts` | 61 | **MODIFY** — Extend to accept full agent specification payload |
| `frontend/src/api/router.ts` | 123 | **KEEP** — Used for model list in Step 2 |
| `frontend/src/api/connectors.ts` | 57 | **KEEP** — Used for connector list in Step 6 |
| `backend/app/routes/agents.py` | 160 | **KEEP** — Agent CRUD. Uses expanded AgentCreate schema from Agent 01 |
| `backend/app/services/agent_service.py` | 367 | **KEEP** — Agent service |
| `backend/app/models/__init__.py` | 279 | **KEEP** — Agent model with: name, description, definition, status, owner_id, tags, steps, tools, llm_config, rag_config, mcp_config, security_policy, input_schema, output_schema, graph_definition, group_id |

---

## What to Build

### 7-Step Wizard

**Step 1 — Identity**
- `name` — required text input with slug preview
- `description` — textarea with character count
- Icon picker — grid of category icons (bot, brain, cog, zap, shield, etc.)
- `tags` — multi-select tag input with autocomplete from existing tags
- `group_id` — dropdown of available groups/teams

**Step 2 — Model Configuration**
- LLM selector — dropdown populated from `GET /api/v1/router/models` with provider badges (OpenAI logo, Anthropic logo, etc.)
- Temperature slider — range 0–2, step 0.1, with labels (Precise ↔ Creative)
- `max_tokens` — numeric input with model-specific max hint
- System prompt — rich text editor (markdown-capable) with template suggestions

**Step 3 — Tools & MCP**
- Searchable grid of available MCP tools from `GET /api/v1/tools`
- Each tool card: icon, name, description, toggle on/off
- When toggled on, expand to show parameter config form (rendered dynamically from tool's parameter schema)
- Selected tool count badge in step indicator

**Step 4 — Knowledge / RAG**
- Connect document collections from `GET /api/v1/knowledge/collections`
- Embedding model selector (dropdown)
- Chunk strategy: Fixed Size | Sentence | Paragraph | Semantic (radio group)
- `chunk_size` and `chunk_overlap` — numeric inputs (shown for Fixed Size)
- `top_k` — slider 1–20
- Retrieval preview: "Test query" input → shows sample retrieved chunks

**Step 5 — Security & Guardrails**
- DLP toggle (on/off) with explanation tooltip
- Guardrail policies — multi-select from available policies via `GET /api/v1/security/policies`
- Cost limit per execution — currency input with "No limit" toggle
- Allowed domains — tag input for URL patterns
- PII handling mode — radio: Block | Redact | Allow with Warning

**Step 6 — Connectors**
- Visual cards of registered connectors from `GET /api/v1/connectors`
- Each card: logo, name, status badge (Connected / Not Connected)
- "Connect" button triggers OAuth flow for unconnected connectors
- "Disconnect" button for connected connectors
- Filter by category (Communication, Storage, CRM, etc.)

**Step 7 — Review & Test**
- Summary cards for each step — compact read-only view of all configured values
- "Edit" button on each card → jumps back to that step
- Visual graph preview of the agent's flow (React Flow read-only canvas)
- "Test Agent" button → opens test dialog with sample input → shows output
- "Create" / "Save" button → submits full agent spec

### Quick Create

- Toggle at top of wizard: "Quick Create" / "Full Setup"
- Quick Create shows only Step 1 (Identity) + Step 2 (Model) + Create button
- All other fields use sensible defaults
- After creation, user can edit to fill remaining steps

### Edit Mode

- Opening wizard for existing agent pre-populates all steps with current values
- URL: `/agents/{id}/edit`
- Same 7 steps, "Save Changes" instead of "Create"

---

## OSS Patterns to Follow

### 1. Dify App Configuration (`dify/web/app/components/app/configuration/`)
Dify uses separate panels for model config, tools, RAG, and moderation. Each panel has its own rich form with validation and preview. **Adaptation**: Combine into wizard steps but replicate the per-panel form richness — each step should feel like a standalone configuration panel with its own validation state.

### 2. Coze Studio Bot Creation
Coze organizes bot creation into logical sections (prompt, model, plugins, knowledge). Each section is independently configurable and collapsible. **Adaptation**: Same section-based approach but presented as wizard steps with a progress bar. Each step is independently valid — users can skip optional steps.

### 3. Flowise Node Parameters
Flowise renders dynamic forms for each node based on parameter schemas. Input types are inferred from the schema (string → text, number → numeric, enum → dropdown, boolean → toggle). **Adaptation**: The Tools step (Step 3) should dynamically render parameter forms based on each MCP tool's parameter schema using the same schema-driven approach.

---

## Frontend Deliverables

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/components/agents/CreateAgentWizard.tsx` | **CREATE** | 7-step wizard shell: progress bar, step navigation, state management, Quick Create toggle |
| `frontend/src/components/agents/steps/IdentityStep.tsx` | **CREATE** | Name, description, icon picker, tags, group selector |
| `frontend/src/components/agents/steps/ModelStep.tsx` | **CREATE** | Model dropdown from `/router/models`, temperature slider, max_tokens, system prompt editor |
| `frontend/src/components/agents/steps/ToolsStep.tsx` | **CREATE** | Searchable MCP tool grid with toggle and per-tool parameter config |
| `frontend/src/components/agents/steps/KnowledgeStep.tsx` | **CREATE** | RAG config: collections, embedding model, chunk strategy, top_k |
| `frontend/src/components/agents/steps/SecurityStep.tsx` | **CREATE** | DLP toggle, guardrail selector, cost limit, allowed domains, PII mode |
| `frontend/src/components/agents/steps/ConnectorsStep.tsx` | **CREATE** | Connector cards with OAuth connect/disconnect |
| `frontend/src/components/agents/steps/ReviewStep.tsx` | **CREATE** | Summary cards, graph preview, test button, create button |
| `frontend/src/pages/AgentsPage.tsx` | **MODIFY** | Replace 3-field modal with wizard. "Create Agent" button opens `CreateAgentWizard` |
| `frontend/src/api/agents.ts` | **MODIFY** | Extend `createAgent()` to accept full agent specification matching all 7 steps |

---

## Integration Points

| Agent | Integration |
|-------|------------|
| Agent 01 | Backend CRUD — AgentCreate schema already supports full spec from Agent 01 |
| Agent 02 | Graph preview in Step 7 — reuse `AgentGraphCanvas` read-only mode |
| Agent 08 | Model list — `GET /api/v1/router/models` for Step 2 model dropdown |
| Agent 09 | Connector list — `GET /api/v1/connectors` for Step 6 |
| Agent 12 | DLP policies — `GET /api/v1/security/policies` for Step 5 |
| Agent 17 | Secrets — Tool credentials stored/retrieved via SecretsManager |

---

## Acceptance Criteria

1. "Create Agent" opens the 7-step wizard, not the 3-field modal
2. Each step has rich form controls — zero raw JSON input fields anywhere
3. Model selector shows available models with provider badges and cost info
4. Tool selector shows MCP tools in a searchable grid with descriptions and parameter config
5. Security step has DLP toggle, guardrail selector, and cost limit input
6. Step 7 shows visual summary cards + graph preview + test button
7. "Quick Create" is available for simple agents (Step 1 + Step 2 + Create)
8. Created agent appears in AgentsPage list and is runnable
9. Editing an agent re-opens the wizard pre-populated with existing data
10. All form validation is per-step — user cannot advance past invalid step
11. Wizard state persists across step navigation (no data loss on back/forward)
12. Dark mode and light mode render correctly on all steps

---

## Constraints

1. **Response Envelope** — Every API response uses the standard envelope: `{ "data": T, "meta": { "request_id", "timestamp" } }`. Errors: `{ "error": { "code", "message", "details" } }`.
2. **JWT Auth** — Every endpoint requires a valid JWT Bearer token. Use `get_current_user` dependency. No anonymous access.
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
