# Archon — Agent Definitions v2.0 (Production-Ready)

> **Purpose**: Complete, enriched prompt for each of the 22 specialized agents.
> Each agent definition includes exact responsibilities, UI flows, backend logic,
> integration points, acceptance criteria, security/tenancy handling, and
> how it eliminates JSON hell in favor of intuitive UX.
>
> **Status**: DEFINITION ONLY — no implementation until user confirms.

---

## Agent 01 — Core Backend & API Gateway

### Role
Foundation backend: FastAPI application, database models, auth middleware, error handling, API envelope format, health checks, and the standard patterns every other agent depends on.

### Current State & Gaps
- `agents.py` is 140 lines — minimal CRUD, no steps/tools/prompts in `AgentCreate` schema.
- `audit_logs.py` is 71 lines — bare list endpoint, no auth, fails in Docker (DB session issues).
- `executions.py` is 101 lines — read-only stubs, no execution engine.
- Health endpoint at `/health` but Settings page calls `/api/v1/health` → 404.
- No `Agent` model fields for: `steps`, `tools`, `mcp_config`, `rag_config`, `security_policy`, `llm_config`, `input_schema`, `output_schema`.

### Responsibilities
1. **Agent Model Expansion**: Extend `Agent` DB model and `AgentCreate`/`AgentUpdate` schemas to include:
   - `steps: list[AgentStep]` — ordered list with step_name, step_type (llm|tool|condition|human|subagent), config
   - `tools: list[ToolBinding]` — tool name, MCP server ref, parameter overrides
   - `llm_config: LLMConfig` — model_id, temperature, max_tokens, system_prompt, provider_ref
   - `rag_config: RAGConfig | None` — collection_id, chunk_strategy, top_k, rerank
   - `mcp_config: MCPConfig | None` — server_url, tools_enabled, sandbox_mode
   - `security_policy: SecurityPolicy` — dlp_enabled, guardrails, allowed_domains, max_cost_per_run
   - `input_schema: dict | None`, `output_schema: dict | None` — JSON Schema for structured I/O
   - `graph_definition: dict | None` — React Flow serialized graph (nodes + edges) from visual builder
   - `group_id: str | None` — team/group ownership
2. **Execution Engine**: Wire `POST /agents/{id}/execute` to LangGraph runtime:
   - Accept `input` payload, create Execution record, stream events via WebSocket
   - Record token usage, cost, latency per step
   - Emit events: `step.started`, `step.completed`, `step.failed`, `tool.called`, `llm.response`
3. **Health Endpoint Fix**: Add `/api/v1/health` alias that proxies to `/health`.
4. **Audit Log Fix**: Ensure audit_logs route uses proper auth dependency (`require_auth`), handles empty DB gracefully (return `[]` not 500).
5. **API Envelope**: Every response must follow `{"data": ..., "meta": {"request_id", "timestamp", "pagination?"}}`. Error responses: `{"errors": [...], "meta": {...}}`.

### Integration Points
- **Agent 02 (Builder)**: Receives `graph_definition` from React Flow serialization
- **Agent 05 (Wizard)**: Receives structured agent spec from wizard completion
- **Agent 06 (Executions)**: Provides execution engine and WebSocket streaming
- **Agent 07 (Workflows)**: Agents are referenced in workflow steps
- **Agent 08 (Router)**: `llm_config.provider_ref` resolves via router
- **Agent 12 (DLP)**: All execution I/O passes through DLP pipeline
- **Agent 17 (Secrets)**: Credential refs in tools/connectors resolve via Vault

### Acceptance Criteria
- [ ] `AgentCreate` accepts 10+ fields (not just name/description/tags)
- [ ] `POST /agents/{id}/execute` creates execution, returns execution_id, streams via WS
- [ ] `GET /api/v1/health` returns `{"status":"healthy"}` (Settings page works)
- [ ] `GET /audit-logs/` returns `{"data":[], "meta":{...}}` when empty (not 500)
- [ ] All routes use `require_auth` dependency
- [ ] All responses follow envelope format
- [ ] 1092+ tests still pass

---

## Agent 02 — Visual Graph Builder (React Flow)

### Role
The primary agent creation experience: a drag-and-drop visual graph editor using React Flow 12 where users compose agent logic by connecting nodes.

### Current State & Gaps
- `BuilderPage.tsx` exists (56 lines) with React Flow infrastructure
- Components exist: `AgentCanvas`, `TopBar`, `NodePalette`, `PropertyPanel`, 6 node types (Base, Input, Output, LLM, Tool, Condition)
- **Gap**: Canvas appears blank/minimal — no way to save graph to backend, no rich node configuration, no template loading, no NL-to-graph integration
- **Gap**: AgentsPage "Edit" button navigates to `/builder?agentId=` but builder doesn't load agent data
- **Gap**: No preview/test mode, no validation before save

### Responsibilities
1. **Node Type Library (20+ types)** organized in collapsible palette categories:
   - **Input/Output**: UserInput, APIInput, WebhookTrigger, ScheduleTrigger, Output, StreamOutput
   - **LLM**: ChatCompletion, TextGeneration, Embedding, Vision, Structured (JSON mode)
   - **Tools**: MCPTool, FunctionCall, HTTPRequest, DatabaseQuery, FileOperation
   - **Logic**: Condition (if/else), Switch (multi-branch), Loop, Parallel, Merge, Delay
   - **RAG**: VectorSearch, DocumentLoader, Chunker, Reranker
   - **Human**: HumanApproval, HumanInput, Notification
   - **Sub-agents**: SubAgentCall, WorkflowCall
   - **Security**: DLPScan, GuardrailCheck, CostGate
2. **Node Configuration Panel** (right sidebar):
   - When a node is selected, show a rich form (NOT JSON) with fields specific to the node type
   - LLM node: Model dropdown (from router/models), temperature slider, system prompt editor (Monaco), max_tokens
   - Tool node: MCP server picker, tool selector (auto-discovered from MCP), parameter mapping
   - Condition node: Visual condition builder (field, operator, value) — NOT raw JSON
3. **Save/Load Agent Graph**:
   - Save: Serialize React Flow `nodes` + `edges` → `graph_definition` field on Agent model
   - Load: `GET /agents/{id}` → deserialize `graph_definition` → restore React Flow state
   - Auto-save draft every 30s
4. **Validation**:
   - Every graph must have ≥1 Input and ≥1 Output node
   - All edges must connect compatible ports
   - Show validation errors inline (red badges on invalid nodes)
5. **Preview Mode**: Toggle to see a simplified execution flow visualization
6. **Test Run**: "Test" button sends sample input through the graph, shows step-by-step execution in a side panel
7. **NL Integration**: "Describe with AI" button opens Agent 03 wizard, result populates the canvas

### Integration Points
- **Agent 01 (Backend)**: Save/load via `PUT /agents/{id}` with `graph_definition`
- **Agent 03 (NL Wizard)**: Wizard output becomes React Flow graph
- **Agent 05 (Wizard)**: Wizard step 7 = visual graph preview in this canvas
- **Agent 06 (Executions)**: Test run creates execution via backend
- **Agent 08 (Router)**: LLM node model dropdown fetches from `/router/models`
- **Agent 15 (MCP Apps)**: MCP tool nodes reference MCP server registry

### Acceptance Criteria
- [ ] Canvas renders 20+ node types from palette via drag-drop
- [ ] Selecting a node shows rich property form (no JSON fields for common config)
- [ ] Graph saves to backend and reloads correctly on page revisit
- [ ] Validation prevents saving invalid graphs (missing I/O, disconnected nodes)
- [ ] "Test" button executes sample input and shows step results
- [ ] Edit agent from AgentsPage loads graph in builder
- [ ] Works on 1920x1080 and 1440px screens without overflow

---

## Agent 03 — Natural Language → Agent Wizard

### Role
4-step conversational wizard that converts a plain English description into a fully structured agent with graph definition.

### Current State & Gaps
- `wizard_service.py` exists (719 lines) with NL→LangGraph conversion logic
- `wizard.py` route exists (183 lines) with basic endpoints
- **Gap**: No frontend wizard UI exists — user has zero access to this feature
- **Gap**: Wizard output doesn't integrate with the visual builder

### Responsibilities
1. **Frontend 4-Step Wizard Modal** (`components/wizard/AgentWizard.tsx`):
   - **Step 1 — Describe**: Large textarea "What should this agent do?" + optional context (industry, data sources, tools needed). Auto-suggest completions.
   - **Step 2 — Plan**: AI generates a plan showing proposed steps, tools, model choices. User can accept, modify, or re-generate. Show as editable card list, NOT JSON.
   - **Step 3 — Configure**: AI-generated agent config shown as rich form — user tweaks model selection, temperature, guardrails, cost limits. Each field has explanation tooltip.
   - **Step 4 — Preview & Create**: Show the proposed graph visually (React Flow read-only preview). "Create Agent" button saves to backend and redirects to builder for fine-tuning.
2. **Backend Wizard Endpoints**:
   - `POST /wizard/describe` — accepts description, returns structured plan
   - `POST /wizard/generate` — accepts plan, returns full agent spec including `graph_definition`
   - `POST /wizard/create` — accepts final spec, creates Agent record
3. **Suggestions Engine**: Based on description, suggest relevant templates from marketplace

### Integration Points
- **Agent 01 (Backend)**: Creates Agent via standard CRUD
- **Agent 02 (Builder)**: Step 4 preview uses React Flow components; "Edit in Builder" button
- **Agent 04 (Templates)**: Suggest matching templates during Step 2
- **Agent 08 (Router)**: Model suggestions come from available models in router

### Acceptance Criteria
- [ ] Wizard accessible from AgentsPage "Create Agent" button and Dashboard "Quick Start"
- [ ] All 4 steps render rich UI — zero raw JSON visible to user
- [ ] Generated plan is editable as card/form, not raw text
- [ ] Step 4 shows React Flow graph preview
- [ ] "Create Agent" creates a real agent retrievable via API
- [ ] Round-trip: create via wizard → open in builder → graph matches wizard output

---

## Agent 04 — Templates & Marketplace

### Role
Pre-built agent templates and a marketplace for sharing/installing community agents.

### Current State & Gaps
- `TemplatesPage.tsx` (177 lines) — form with Name, raw JSON Definition, Category, Tags. No preview, no one-click instantiate.
- `MarketplacePage.tsx` (232 lines) — bare publish form. No listings, no search, no install.
- Backend: `templates.py` (367 lines), `marketplace.py` (431 lines), services exist.
- **Gap**: Templates need rich cards with preview, not just a list. Definition field must NOT be raw JSON.
- **Gap**: Marketplace needs a catalog UI with search, categories, ratings.

### Responsibilities
1. **Templates Page Redesign**:
   - **Gallery View**: Grid of template cards with: icon, name, category badge, description preview, "Use Template" button
   - **Template Detail**: Click card → modal with full description, graph preview (React Flow read-only), required connectors, estimated cost, "Instantiate" button
   - **Create Template**: Multi-step form: (1) Name/Description/Category (2) Build graph in embedded mini-builder OR import from existing agent (3) Set default config (4) Preview & Publish
   - **Categories**: Customer Support, Data Analysis, Content Generation, Code Assistant, Research, DevOps, Sales, HR, Finance, Custom
   - Seed 20+ starter templates on first load
2. **Marketplace Page Redesign**:
   - **Browse Catalog**: Search bar + category filters + sort (Popular, Recent, Rating)
   - **Package Cards**: Publisher avatar, name, version, downloads, rating stars, verified badge
   - **Install Flow**: "Install" → confirm permissions → creates agent from template
   - **Publish Flow**: Multi-step: (1) Select agent to publish (2) Add metadata (3) Set license (4) Submit for review
   - **Review Status**: Show pending/approved/rejected for published items
3. **Backend Enhancements**:
   - `GET /templates/` — paginated with category/search filters, return rich metadata
   - `POST /templates/{id}/instantiate` — create agent from template with user overrides
   - `GET /marketplace/catalog` — public listings with search, category, sort
   - `POST /marketplace/{id}/install` — install into user's workspace

### Integration Points
- **Agent 01 (Backend)**: Instantiation creates Agent via standard CRUD
- **Agent 02 (Builder)**: Template graph preview uses React Flow components
- **Agent 03 (Wizard)**: Wizard Step 2 suggests templates
- **Agent 13 (Governance)**: Published marketplace items go through approval workflow

### Acceptance Criteria
- [ ] Templates page shows gallery of cards, not a bare form
- [ ] Each template has a visual graph preview
- [ ] "Use Template" creates a working agent in one click
- [ ] Marketplace has search, categories, install flow
- [ ] Template creation uses a wizard, not raw JSON
- [ ] 20+ seed templates available on fresh install

---

## Agent 05 — Agent Creation Wizard (Unified)

### Role
The unified "Create Agent" experience: a 7-step wizard that covers all agent configuration without requiring the visual builder for simple agents.

### Current State & Gaps
- AgentsPage has a "Create Agent" modal with only Name, Description, Tags — **3 fields total**
- No steps, tools, LLM config, security, connectors, testing
- **Gap**: Must become a comprehensive 7-step wizard that produces a fully configured agent

### Responsibilities
1. **7-Step Create Agent Wizard** (full-screen modal or dedicated page):
   - **Step 1 — Identity**: Name, description, icon picker, tags, group/team assignment
   - **Step 2 — Model**: Select LLM (dropdown from router/models with provider badges), temperature slider (0-2), max tokens, system prompt (rich editor with syntax highlighting). "Suggest Model" button based on use case.
   - **Step 3 — Tools & MCP**: Browse available MCP tools in a searchable grid. Toggle tools on/off. Configure tool parameters via form. Add custom HTTP tools.
   - **Step 4 — Knowledge (RAG)**: Connect to document collections (DocForge). Select embedding model, chunk strategy, top_k. Upload files directly or link connectors.
   - **Step 5 — Security & Guardrails**: DLP on/off, select guardrail policies, set cost limit per execution, allowed input/output domains, PII handling mode (redact/block/allow).
   - **Step 6 — Connectors**: Select from registered connectors (Salesforce, Slack, DB, etc.) with visual cards. OAuth connectors show "Connect" button.
   - **Step 7 — Review & Test**: Summary of all config in readable cards. "Test Agent" button sends sample prompt. Visual graph preview. "Create" button saves.
2. **Quick Create**: For simple agents, offer "Quick Create" (just Step 1 + Step 2 + Create).
3. **Edit Agent**: Same wizard but pre-populated from existing agent data.

### Integration Points
- **Agent 01 (Backend)**: Saves via expanded `AgentCreate` schema
- **Agent 02 (Builder)**: "Open in Builder" button after creation for visual editing
- **Agent 03 (NL Wizard)**: "Describe with AI" alternative entry point
- **Agent 08 (Router)**: Step 2 model dropdown from `/router/models`
- **Agent 09 (Connectors)**: Step 6 connector selection from `/connectors`
- **Agent 12 (DLP)**: Step 5 guardrail policy selection from `/dlp/policies`
- **Agent 17 (Secrets)**: Tool/connector credentials stored in Vault

### Acceptance Criteria
- [ ] "Create Agent" opens 7-step wizard, not a 3-field modal
- [ ] Each step has rich form controls — zero JSON fields
- [ ] Model selector shows available models with provider/cost info
- [ ] Tool selector shows MCP tools in searchable grid with descriptions
- [ ] Step 7 shows visual graph preview of the agent's flow
- [ ] Test button in Step 7 executes a sample run
- [ ] Created agent appears in AgentsPage and is runnable

---

## Agent 06 — Executions & Tracing

### Role
Execution engine, real-time traces, and execution history.

### Current State & Gaps
- `ExecutionsPage.tsx` (150 lines) — empty state with play icon, basic table structure
- `executions.py` (101 lines) — read-only list/get, no execution creation
- **Gap**: No execution engine. No traces. No real-time streaming. No step-level detail.

### Responsibilities
1. **Execution Engine** (backend):
   - `POST /executions` — accepts `agent_id`, `input`, optional `config_overrides`
   - Creates Execution record with status `pending` → `running` → `completed`/`failed`
   - Runs agent graph via LangGraph, emitting events to Redis pub/sub
   - Records per-step: name, type, duration_ms, token_usage, cost, input/output
   - Records overall: total_duration, total_tokens, total_cost, final_output
2. **Real-Time Streaming**:
   - WebSocket at `/ws/executions/{execution_id}` streams step events
   - Frontend shows live execution progress: steps lighting up as they complete
3. **Execution Detail Page**:
   - Header: agent name, status badge, duration, total cost
   - **Timeline**: Vertical timeline of steps with expand/collapse
   - Each step shows: input → processing → output, duration, tokens used
   - Tool calls show request/response
   - LLM calls show prompt/completion with token counts
   - **Graph View**: React Flow graph with steps colored by status (green=done, blue=running, red=failed)
4. **Execution List Page**:
   - Table: Execution ID, Agent Name, Status, Duration, Cost, Created At
   - Filters: Status, Agent, Date Range
   - "Run Agent" button → select agent → provide input → start execution
5. **Replay**: Re-run a past execution with same or modified input

### Integration Points
- **Agent 01 (Backend)**: Agent graph definition loaded for execution
- **Agent 02 (Builder)**: "Test" button creates execution
- **Agent 07 (Workflows)**: Workflow execution creates child executions per step
- **Agent 08 (Router)**: LLM calls route through model router
- **Agent 11 (Cost)**: Token usage → cost ledger
- **Agent 12 (DLP)**: All I/O scanned during execution
- **Agent 18 (Audit)**: Execution events logged to audit trail

### Acceptance Criteria
- [ ] `POST /executions` creates and runs an execution
- [ ] WebSocket streams step events in real-time
- [ ] Execution detail page shows step-by-step timeline
- [ ] Execution list page shows history with filters
- [ ] "Run Agent" button from ExecutionsPage works
- [ ] Each step shows tokens, cost, duration
- [ ] Failed steps show error details

---

## Agent 07 — Workflows Graph

### Role
Multi-step workflow orchestration with visual graph editor for composing agent sequences.

### Current State & Gaps
- `WorkflowsPage.tsx` (686 lines) — has list + create modal with basic step builder
- `workflows.py` (206 lines) — in-memory CRUD + execute endpoint
- **Gap**: Create modal uses simple form with raw JSON config per step — needs visual graph like old React Flow experience
- **Gap**: No execution visualization, no scheduling UI, no group management

### Responsibilities
1. **Workflow Visual Editor** (embedded React Flow):
   - Drag-drop workflow steps as nodes on a canvas
   - Each node = one agent call, with config form (not JSON)
   - Edges define execution order and data passing
   - Support parallel branches (Parallel node), conditions (Condition node), loops
   - "Sub-workflow" node for composition
2. **Workflow Create/Edit Redesign**:
   - Replace JSON config field with visual node editor
   - Each step node's config: Select Agent (dropdown), Input Mapping (visual mapper: source field → target field), Timeout, Retry Policy, On-Failure action
   - Group assignment: Select team/group that owns the workflow
   - Schedule: Visual cron builder (not raw cron string) — hourly/daily/weekly/monthly presets + custom
3. **Workflow Execution**:
   - `POST /workflows/{id}/execute` → creates execution, runs steps in order/parallel
   - Real-time progress: WebSocket streams step status
   - Step failures: configurable action (stop, skip, retry, fallback agent)
4. **Run History**: Table of past workflow runs with status, duration, step details
5. **Group Management**: Filter workflows by group, assign group permissions

### Integration Points
- **Agent 01 (Backend)**: Each workflow step references an Agent
- **Agent 02 (Builder)**: Shares React Flow infrastructure and node patterns
- **Agent 06 (Executions)**: Each workflow step creates a child execution
- **Agent 11 (Cost)**: Workflow-level cost aggregation
- **Agent 16 (Tenants)**: Workflows scoped to tenant + group

### Acceptance Criteria
- [ ] Workflow creation uses visual graph editor, not JSON forms
- [ ] Nodes are draggable with connection handles
- [ ] Step config is a form (agent dropdown, input mapping, retry), not JSON
- [ ] Schedule uses visual cron picker with presets
- [ ] Workflow execution shows real-time step progress
- [ ] Run history shows step-level detail
- [ ] Group filter on workflow list works

---

## Agent 08 — Model Router + Vault Secrets

### Role
Intelligent model routing with provider management, cost/latency scoring, and Vault-stored API keys.

### Current State & Gaps
- `ModelRouterPage.tsx` (548 lines) — has Providers, Models, Rules sections (recently added)
- Backend: `router.py` (276 lines), `models.py` (262 lines) with provider CRUD
- **Gap**: Provider registration has no API key/secret field — critical! Users can't store provider credentials
- **Gap**: Routing rules use raw JSON conditions — needs visual rule builder
- **Gap**: No cost/latency scoring visualization, no fallback chain UI
- **Gap**: "Cost/1K" and "Avg Latency" fields on provider form are cosmetic — not used in routing decisions

### Responsibilities
1. **Provider Management with Vault Secrets**:
   - Provider form: Name, Type (OpenAI/Anthropic/Azure/Ollama/etc.), API Base URL, **API Key** (stored in Vault, never in DB), Supported Models
   - API Key handling: Frontend sends key → backend stores at `archon/providers/{id}/api_key` in Vault → stores only Vault path in provider record
   - "Test Connection" button: validates API key + base URL by making a test call
   - Health dashboard: Show latency, error rate, circuit breaker status per provider
2. **Model Registry Enhancement**:
   - Model form: Provider (dropdown from registered providers), Model ID, Display Name, Capabilities (multi-select chips: chat, code, vision, embedding, structured), Context Window, Pricing (auto-fetched if known provider)
   - Cost/performance matrix: Table showing models ranked by cost, speed, capability
3. **Routing Rules — Visual Builder**:
   - Replace JSON conditions with visual rule builder:
   - Condition rows: `IF [field] [operator] [value] THEN route to [model]`
   - Fields: `capability`, `max_cost`, `min_context`, `sensitivity_level`, `tenant_tier`, `time_of_day`
   - Operators: equals, contains, greater_than, less_than, in
   - Priority ordering via drag-drop
   - Fallback chain: If primary model fails → try next → try next
4. **Routing Decision Explainability**: API returns which rule matched and why

### Integration Points
- **Agent 01 (Backend)**: Models referenced in Agent LLM config
- **Agent 02 (Builder)**: LLM node model dropdown fetches from router
- **Agent 06 (Executions)**: Execution LLM calls route through router
- **Agent 11 (Cost)**: Per-model cost rates used for cost tracking
- **Agent 17 (Secrets)**: Provider API keys stored in Vault

### Acceptance Criteria
- [ ] Provider form has "API Key" field that stores securely in Vault
- [ ] "Test Connection" validates provider credentials
- [ ] Health dashboard shows live provider status
- [ ] Routing rules use visual builder, not JSON
- [ ] Fallback chain configurable via UI
- [ ] Routing decision includes explanation of rule match
- [ ] No API keys visible in API responses or DB records

---

## Agent 09 — Connectors Onboarding

### Role
Rich connector management with type-specific wizards, OAuth flows, and one-click onboarding.

### Current State & Gaps
- `ConnectorsPage.tsx` (186 lines) — bare form: Name, Type dropdown, raw JSON Config field
- Backend: `connectors.py` (382 lines), `connector_service.py` (541 lines)
- **Gap**: "Config" is a raw JSON textarea — must be a type-specific form
- **Gap**: No OAuth flow, no connection testing, no visual status

### Responsibilities
1. **Connector Type Registry** (35+ types):
   - **Databases**: PostgreSQL, MySQL, MongoDB, Redis, Elasticsearch, Snowflake, BigQuery
   - **SaaS**: Salesforce, HubSpot, Zendesk, Jira, Confluence, Notion, Airtable
   - **Communication**: Slack, Teams, Discord, Email (SMTP/IMAP), Twilio
   - **Cloud**: AWS S3, Azure Blob, GCP Storage, GitHub, GitLab
   - **AI**: OpenAI, Anthropic, Ollama, HuggingFace
   - **Custom**: Webhook, REST API, GraphQL, gRPC
2. **Type-Specific Configuration Forms**:
   - Each connector type has its own form schema:
     - PostgreSQL: Host, Port, Database, Username, Password (Vault), SSL mode
     - Salesforce: "Connect with Salesforce" OAuth button → redirect → callback → store tokens in Vault
     - Slack: Workspace picker, Bot Token (Vault), Channels
     - S3: Region, Bucket, Access Key (Vault), Secret Key (Vault)
   - NO raw JSON config for any standard connector type
   - "Custom" type allows JSON for advanced users
3. **OAuth Flow**:
   - For OAuth connectors: "Connect" button → opens OAuth popup → captures tokens → stores in Vault
   - Backend: `GET /connectors/oauth/{type}/authorize` → redirect URL
   - Backend: `GET /connectors/oauth/{type}/callback` → exchange code → store tokens
4. **Connection Testing**:
   - "Test Connection" button on every connector → validates credentials and connectivity
   - Shows success/failure with diagnostic details
5. **Connector Browser**:
   - Replace bare form with visual catalog: grid of connector cards with logos
   - Click card → opens type-specific setup wizard (2-3 steps)
   - Connected connectors show status badge (green=healthy, red=error)
6. **Health Monitoring**: Periodic health checks on all connectors, alerts on failures

### Integration Points
- **Agent 01 (Backend)**: Connectors referenced in Agent tool config
- **Agent 05 (Wizard)**: Step 6 selects connectors
- **Agent 14 (DocForge)**: Document connectors feed RAG pipeline
- **Agent 17 (Secrets)**: All credentials stored in Vault

### Acceptance Criteria
- [ ] Connector creation uses type-specific forms, not JSON
- [ ] OAuth connectors (Salesforce, Slack, GitHub) have "Connect" button with OAuth flow
- [ ] "Test Connection" works for all connector types
- [ ] Connector catalog shows visual cards with logos/icons
- [ ] Credentials never visible in API responses
- [ ] Connected connectors show health status
- [ ] At least 10 connector types have rich forms

---

## Agent 10 — Lifecycle & Deployment

### Role
Agent lifecycle management: draft → staging → production with deployment strategies.

### Current State & Gaps
- `LifecyclePage.tsx` (207 lines) — deployment form with Agent ID, Version ID, Environment, Rolling Count
- Backend: `lifecycle.py` (530 lines), service exists
- **Gap**: Form is too technical — requires raw Agent ID input
- **Gap**: No visual pipeline, no environment comparison, no health monitoring

### Responsibilities
1. **Lifecycle Pipeline View**:
   - Visual horizontal pipeline: Draft → Review → Staging → Production
   - Each stage shows agent versions currently in that stage
   - Drag agent version between stages (or use promote/demote buttons)
   - Approval gates between stages (configurable per tenant)
2. **Deployment Form Redesign**:
   - Replace raw ID fields with: Agent selector (dropdown with search), Version selector, Environment selector
   - Deployment strategy: Rolling (with replica count slider), Blue-Green, Canary (with traffic % slider)
   - Pre-deploy checks: auto-run DLP scan, guardrail validation, cost estimate
3. **Environment Management**:
   - Show environments: Development, Staging, Production (+ custom)
   - Per-environment: deployed version, health status, instance count, last deploy time
   - Diff view: compare agent config between environments
4. **Health Monitoring**:
   - After deployment: show live health (response time, error rate, throughput)
   - Auto-rollback trigger on error rate > threshold

### Integration Points
- **Agent 01 (Backend)**: Agent versions and deployment records
- **Agent 06 (Executions)**: Execution metrics feed health monitoring
- **Agent 11 (Cost)**: Deployment cost estimates
- **Agent 13 (Governance)**: Approval workflows for production promotion

### Acceptance Criteria
- [ ] Visual pipeline shows lifecycle stages
- [ ] Agent/version selectors use dropdowns, not raw IDs
- [ ] Deployment strategy selector with visual config
- [ ] Environment comparison view
- [ ] Health monitoring after deployment
- [ ] Approval gates configurable

---

## Agent 11 — Cost Engine

### Role
Token usage tracking, budget management, cost attribution, and forecasting.

### Current State & Gaps
- `CostPage.tsx` (334 lines) — usage chart (empty), budget form (Name, Scope, Limit, Period, Enforcement), alerts (empty)
- Backend: `cost.py` (568 lines), `cost_service.py` (797 lines)
- **Gap**: No actual cost data flowing — executions don't record token costs
- **Gap**: Budget form works but no enforcement mechanism
- **Gap**: No per-team/per-agent cost breakdown, no chargeback

### Responsibilities
1. **Token Ledger**: Immutable append-only ledger recording every LLM call:
   - execution_id, agent_id, model_id, provider, input_tokens, output_tokens, cost_usd, timestamp, tenant_id, user_id, group_id
2. **Cost Dashboard Redesign**:
   - **Summary Cards**: Total spend (period), spend vs budget, projected spend, top model by cost
   - **Usage Chart**: Stacked area chart by provider/model over time (daily/weekly/monthly)
   - **Breakdown Table**: Cost by agent, by model, by user, by team — switchable views
   - **Top Consumers**: Ranked list of agents/users by cost
3. **Budget Management Enhancement**:
   - Budget wizard: Select scope (tenant/team/agent/user), set limit, period, enforcement (soft alert / hard block)
   - Budget utilization bar graph showing spend vs limit
   - Alert rules: email/slack notification at 50%, 75%, 90%, 100%
4. **Forecasting**: ML-based projection of next period's cost based on trends
5. **Chargeback Reports**: Exportable PDF/CSV cost reports per team/department

### Integration Points
- **Agent 06 (Executions)**: Execution engine records token usage
- **Agent 08 (Router)**: Per-model cost rates
- **Agent 16 (Tenants)**: Tenant-level budget enforcement

### Acceptance Criteria
- [ ] Every execution records token cost in ledger
- [ ] Dashboard shows real cost data from ledger
- [ ] Cost breakdown by agent/model/user/team
- [ ] Budgets enforce limits (soft and hard)
- [ ] Alert notifications trigger at thresholds
- [ ] Usage chart renders with real data

---

## Agent 12 — DLP & Guardrails

### Role
Data Loss Prevention pipeline: scan all inputs/outputs for PII/secrets, enforce guardrail policies.

### Current State & Gaps
- `DLPPage.tsx` (386 lines) — live scanner textarea, policy CRUD form (Name, Action, Detectors, Sensitivity), metrics all 0
- Backend: `dlp.py` (338 lines), `dlp_service.py` (936 lines) — substantial implementation
- **Gap**: Metrics are 0 because no executions feed data through DLP
- **Gap**: Policy detectors are tag inputs — should be visual picker with descriptions
- **Gap**: No live scanning indicator on other pages (agent builder, executions)

### Responsibilities
1. **DLP Pipeline Integration**:
   - Middleware: ALL execution I/O passes through DLP before/after LLM calls
   - Scan types: PII (SSN, credit card, email, phone, address), secrets (API keys, passwords, tokens), custom patterns
   - Actions: Redact (mask sensitive data), Block (reject request), Log (record but allow), Alert
2. **Policy Management Redesign**:
   - Detector picker: Visual grid of detector types with icons and descriptions (not just tag input)
   - Sensitivity slider: Low (log only) → Medium (redact) → High (block)
   - Scope: Apply per-tenant, per-agent, or globally
   - Test policy: Paste sample text → see what gets detected and how action applies
3. **Metrics Dashboard**:
   - Scans today / Detections today / Blocked today / Redacted today
   - Detection type breakdown (pie chart)
   - Trend chart over time
   - Recent detections table with details
4. **Inline DLP Indicators**:
   - Agent Builder: DLP badge on agent card showing if DLP is enabled
   - Execution detail: Show redacted/blocked items in step trace
   - Chat: Real-time redaction in MCP App responses

### Integration Points
- **Agent 01 (Backend)**: Agent `security_policy.dlp_enabled` flag
- **Agent 06 (Executions)**: All execution I/O scanned
- **Agent 13 (Governance)**: DLP policy compliance tracked
- **Agent 15 (MCP Apps)**: MCP responses scanned before display

### Acceptance Criteria
- [ ] All execution I/O passes through DLP middleware
- [ ] Detector picker shows visual cards, not raw tag input
- [ ] Policy test feature works (paste text → see results)
- [ ] Metrics dashboard shows real scan data
- [ ] Redacted content shows masked values in execution trace
- [ ] At least 10 built-in detector types

---

## Agent 13 — Governance & Registry

### Role
Agent registry, compliance policies, approval workflows, and audit trail integration.

### Current State & Gaps
- `GovernancePage.tsx` (308 lines) — Agent Registry form, Compliance Policies form, Audit Trail tab (fails to load)
- Backend: `governance.py` (547 lines), `governance_service.py` (698 lines)
- **Gap**: Audit Trail tab fails with error — likely calling wrong endpoint
- **Gap**: Registry is just a form — should be a visual dashboard of all agents with compliance status
- **Gap**: No approval workflow UI

### Responsibilities
1. **Agent Registry Dashboard**:
   - Visual grid/table of ALL registered agents with: name, version, owner, compliance status (badge), risk score, last scan date
   - Click agent → detail view with full compliance history
   - Bulk actions: request review, archive, flag for review
2. **Compliance Policies**:
   - Policy templates: SOC2, GDPR, HIPAA, PCI-DSS, ISO 27001, Custom
   - Each policy has checkable requirements (automated where possible)
   - Auto-scan: agents periodically checked against active policies
   - Compliance score: 0-100 per agent, aggregated per policy
3. **Approval Workflows**:
   - When agent moves to production: trigger approval flow
   - Assign reviewers (from Users), set approval rules (any 1, all, majority)
   - Reviewer dashboard: pending approvals with agent details, approve/reject with comments
4. **Audit Trail Fix**:
   - Wire to `/audit-logs/` endpoint correctly
   - Show timeline of all governance events: approvals, policy changes, compliance scans

### Integration Points
- **Agent 01 (Backend)**: Agent metadata for registry
- **Agent 10 (Lifecycle)**: Production promotion triggers approval
- **Agent 12 (DLP)**: DLP scan results feed compliance checks
- **Agent 18 (Audit)**: All governance actions logged

### Acceptance Criteria
- [ ] Registry shows all agents with compliance badges
- [ ] Compliance scan runs automatically on agent updates
- [ ] Approval workflow UI: assign reviewers, approve/reject
- [ ] Audit trail tab loads without errors
- [ ] At least 3 policy templates (SOC2, GDPR, Custom)
- [ ] Risk score visible per agent

---

## Agent 14 — SentinelScan

### Role
Shadow AI discovery, security posture assessment, and service inventory.

### Current State & Gaps
- `SentinelScanPage.tsx` (365 lines) — posture gauge (100 but 0 services), risk bars 0, discovery form, empty services table
- Backend: `sentinelscan.py` (524 lines), service exists
- **Gap**: Posture score is cosmetic (always 100 when no services) — needs real calculation
- **Gap**: Discovery form (Scan Name, Target, Type) is functional but results don't populate
- **Gap**: No remediation actions

### Responsibilities
1. **Discovery Engine**: Scan SSO logs, network traffic, API gateway logs for unauthorized AI service usage
2. **Service Inventory**: Discovered services with: name, type, risk level, users, data exposure, last seen
3. **Posture Score**: Weighted calculation based on: unauthorized services, data exposure, credential risks, policy violations
4. **Risk Breakdown**: Category bars (Data Exposure, Unauthorized Access, Credential Risk, Policy Violation) with actual counts
5. **Remediation**: For each discovered risk → suggested action (block, approve, monitor) with one-click apply
6. **Scan Scheduling**: Recurring scans with configurable targets

### Integration Points
- **Agent 12 (DLP)**: DLP findings feed into posture score
- **Agent 13 (Governance)**: Posture score contributes to overall compliance
- **Agent 16 (Tenants)**: Scan scope per tenant

### Acceptance Criteria
- [ ] Discovery scan returns results that populate the services table
- [ ] Posture score reflects actual risk data
- [ ] Risk category bars show real counts
- [ ] Remediation actions available per finding
- [ ] Scan history with status

---

## Agent 15 — MCP Apps Engine

### Role
Interactive UI components embedded in agent chat responses via MCP protocol.

### Current State & Gaps
- `mcp_interactive.py` (206 lines) — component sessions, render, action endpoints
- **Gap**: No frontend for MCP Apps — zero user-facing implementation
- **Gap**: No component library, no chat interface that renders MCP components

### Responsibilities
1. **MCP Component Library**:
   - Pre-built components: DataTable, Chart (bar/line/pie), Form, ApprovalPanel, CodeEditor, FileUploader, MarkdownViewer, ImageGallery
   - Components render inside agent chat responses
   - Sandboxed rendering (iframe or shadow DOM) for security
2. **Chat Interface**:
   - Agent execution results can include MCP components
   - WebSocket streams component data alongside text responses
   - Interactive: user clicks button in component → sends action back to agent → agent responds
3. **Component Builder**: Admin can create custom MCP components using React + a visual editor
4. **Session Management**: Component state persisted per conversation session

### Integration Points
- **Agent 02 (Builder)**: MCP App node type in agent graph
- **Agent 06 (Executions)**: Execution streaming includes MCP component data
- **Agent 12 (DLP)**: Component data scanned before rendering

### Acceptance Criteria
- [ ] At least 5 MCP component types renderable in chat
- [ ] Components are interactive (buttons, forms submit data back)
- [ ] Components render in sandboxed environment
- [ ] Chat interface exists and shows MCP components inline

---

## Agent 16 — SSO + Tenants + Users

### Role
Multi-tenant management, SSO configuration, user administration, and RBAC.

### Current State & Gaps
- `TenantsPage.tsx` (231 lines) — New Tenant form (Name, Slug, Owner, Type)
- `UsersPage.tsx` (572 lines) — user table + invite modal (works with admin.py)
- **Gap**: No SSO configuration pane anywhere — users cannot configure OIDC/SAML IdP
- **Gap**: Tenant form too simple — no IdP config, no usage limits, no billing

### Responsibilities
1. **SSO Configuration Page** (in Settings or dedicated section):
   - **OIDC Configuration**: Discovery URL, Client ID, Client Secret (Vault), Scopes, Claim Mappings (email, name, roles, tenant)
   - **SAML Configuration**: Metadata URL or upload XML, Entity ID, ACS URL, Certificate, Attribute Mappings
   - **Test SSO**: "Test Connection" button → validates IdP configuration
   - **Active Directory / LDAP**: Host, Port, Base DN, Bind DN, Password (Vault), User/Group filters
   - Multiple IdPs per tenant supported
2. **Tenant Management Enhancement**:
   - Tenant detail page: General info, IdP config, Usage quotas (max agents, max executions/day, max storage), Billing info, Member list
   - Usage dashboard per tenant: agents, executions, storage, cost
   - Tenant isolation verification status
3. **User Management Enhancement**:
   - Current user table works — enhance with:
   - Role detail: expandable role definition (what each role can access)
   - Activity log per user
   - "Impersonate" button for admins (with audit trail)
   - Password policy configuration
4. **RBAC Matrix**: Visual matrix of roles × resources × actions

### Integration Points
- **Agent 01 (Backend)**: Auth middleware reads tenant/role from JWT
- **Agent 07 (Workflows)**: Group-scoped workflows
- **Agent 11 (Cost)**: Per-tenant budget enforcement
- **Agent 17 (Secrets)**: IdP credentials stored in Vault
- **Agent 18 (Audit)**: All auth events logged

### Acceptance Criteria
- [ ] SSO configuration page exists with OIDC/SAML/LDAP forms
- [ ] "Test Connection" validates IdP config
- [ ] Tenant detail page shows usage, members, IdP config
- [ ] No raw JSON for SSO configuration
- [ ] Claim/attribute mapping uses visual mapper
- [ ] At least one SSO flow (Keycloak OIDC) works end-to-end

---

## Agent 17 — Secrets Vault

### Role
HashiCorp Vault integration for secure credential storage with tenant isolation.

### Current State & Gaps
- `SecretsPage.tsx` (449 lines) — Create Secret modal (Name, Path, Type), list view
- Backend: `secrets.py` (306 lines), `manager.py` (with stub fallback)
- **Gap**: In Docker, falls back to in-memory stub — needs graceful UX indication
- **Gap**: No path-based access control visualization
- **Gap**: Secret rotation not surfaced in UI

### Responsibilities
1. **Secrets UI Enhancement**:
   - Secret list: show name, path, type badge, last rotated, expiry status (approaching/expired/ok)
   - Secret detail: show metadata (never the value), rotation history, access log (who read it)
   - "Reveal" button (with confirmation + audit log) for authorized admins
2. **Path-Based Access**: Visual tree showing Vault path structure: `archon/{tenant}/providers/`, `archon/{tenant}/connectors/`, etc.
3. **Rotation Management**:
   - Manual rotate button per secret
   - Auto-rotation policies: configurable per secret (30/60/90 days)
   - Rotation status dashboard: secrets approaching rotation, overdue, recently rotated
4. **Vault Status Banner**: Show Vault connection status (connected/stub mode/sealed) in Settings
5. **Integration**: All components that store secrets (providers, connectors, IdPs) use `PUT /secrets` → Vault

### Integration Points
- **Agent 08 (Router)**: Provider API keys in Vault
- **Agent 09 (Connectors)**: Connector credentials in Vault
- **Agent 16 (SSO)**: IdP secrets in Vault

### Acceptance Criteria
- [ ] Secrets page shows list with type badges and rotation status
- [ ] Rotation can be triggered from UI
- [ ] Vault status visible in Settings
- [ ] In-memory stub mode shows clear warning banner
- [ ] Access log shows who accessed which secret

---

## Agent 18 — Audit Log

### Role
Immutable, queryable audit trail of all platform actions.

### Current State & Gaps
- `AuditPage.tsx` (131 lines) — list with filters, expand details
- `admin/AuditLogPage.tsx` (309 lines) — separate admin audit page
- Backend: `audit_logs.py` (71 lines) — basic list endpoint
- **Gap**: "Failed to load audit log" error in Governance tab and possibly main Audit page
- **Gap**: audit_logs.py has no auth dependency — anyone can read
- **Gap**: Very few events actually logged — most actions don't create audit entries

### Responsibilities
1. **Fix Audit Loading**:
   - Ensure `GET /audit-logs/` works when DB is empty (return `[]` not error)
   - Add auth dependency to audit routes
   - Fix Governance page audit tab to call correct endpoint
2. **Comprehensive Event Logging**:
   - Middleware: auto-log on every mutation (POST/PUT/PATCH/DELETE) with: actor, action, resource, timestamp, IP, tenant, outcome
   - Events: agent.created, agent.updated, agent.deleted, agent.executed, user.invited, user.updated, secret.created, secret.rotated, secret.accessed, policy.changed, deployment.created, login.success, login.failure, etc.
3. **Audit Dashboard**:
   - Timeline view with infinite scroll
   - Filters: date range, actor, action type, resource type, outcome (success/failure)
   - Search: full-text search across event details
   - Export: CSV/JSON export for compliance
4. **Immutability**: Audit entries are append-only — no update/delete API endpoints

### Integration Points
- All agents log events to audit trail
- **Agent 13 (Governance)**: Audit data feeds compliance reporting
- **Agent 16 (Tenants)**: Audit entries scoped to tenant

### Acceptance Criteria
- [ ] Audit page loads without errors (empty state = empty table, not error)
- [ ] Every mutation API call creates audit entry
- [ ] Filters work: date range, actor, action, resource
- [ ] Export button produces CSV
- [ ] No update/delete endpoints for audit entries
- [ ] Auth required on all audit endpoints

---

## Agent 19 — Settings Platform

### Role
Platform configuration: system health, API info, SSO setup, feature flags, and admin controls.

### Current State & Gaps
- `SettingsPage.tsx` (113 lines) — system info card, user info card, quick links
- **Gap**: Calls `/api/v1/health` but health endpoint is at `/health` → 404 → "Failed to reach API: Not Found"
- **Gap**: No SSO configuration section (critical gap)
- **Gap**: No feature flags, no email config, no appearance settings

### Responsibilities
1. **Fix Health Endpoint**: Either add `/api/v1/health` alias or fix frontend to call `/health`
2. **Settings Sections** (tabs or sidebar navigation):
   - **General**: Platform name, logo upload, default language, timezone
   - **Authentication**: SSO configuration (delegate to Agent 16 SSO component), session timeout, password policy, MFA enforcement
   - **API & Integrations**: API keys for external access, webhook endpoints, rate limits
   - **Notifications**: Email SMTP config (Vault for credentials), Slack webhook, notification preferences
   - **Feature Flags**: Toggle experimental features on/off per tenant
   - **System Health**: Combined health of all services (API, DB, Redis, Vault, Keycloak), version info, uptime
   - **Appearance**: Theme (dark/light/auto), accent color, custom CSS
3. **Admin-Only Sections**: Feature flags, system health details, Vault status

### Integration Points
- **Agent 16 (SSO)**: SSO config component embedded in Auth tab
- **Agent 17 (Secrets)**: Vault status shown in System Health

### Acceptance Criteria
- [ ] Settings page loads without errors (health endpoint works)
- [ ] SSO configuration accessible from Settings → Authentication
- [ ] System Health shows status of all services
- [ ] Settings organized in clear tabs/sections
- [ ] Non-admin users see limited settings

---

## Agent 20 — Dashboard

### Role
The landing page: executive summary of platform state with actionable quick-start actions.

### Current State & Gaps
- `DashboardPage.tsx` (222 lines) — stat cards (agents/executions/models/policies all 0), "No agents yet", "No executions yet"
- **Gap**: Stats are 0 because data is empty — but also because some API calls may be wrong
- **Gap**: No quick-start actions, no recent activity feed, no system health overview

### Responsibilities
1. **Summary Stats** (real data from APIs):
   - Active Agents (from `/agents/`), Executions Today (from `/executions/`), Models Configured (from `/router/models`), Total Cost (from cost engine)
   - Each card: number, trend arrow (vs yesterday), click → navigate to detail page
2. **Quick Actions Bar**:
   - "Create Agent" → opens wizard (Agent 05)
   - "Run Agent" → opens execution dialog
   - "Browse Templates" → navigates to templates
   - "Import Agent" → file upload
3. **Recent Activity Feed**: Last 10 audit events with actor, action, time
4. **System Health**: Mini status indicators for API, DB, Redis, Vault, Keycloak
5. **Agent Leaderboard**: Top 5 agents by execution count or success rate
6. **Cost Summary**: Spend this week/month with mini chart

### Integration Points
- **Agent 01 (Backend)**: Agent count
- **Agent 06 (Executions)**: Execution count/stats
- **Agent 08 (Router)**: Model count
- **Agent 11 (Cost)**: Cost summary
- **Agent 18 (Audit)**: Recent activity feed

### Acceptance Criteria
- [ ] All stat cards show real data (not hardcoded 0)
- [ ] Quick action buttons navigate to correct pages/modals
- [ ] Recent activity feed shows last 10 events
- [ ] System health indicators reflect actual service status
- [ ] Dashboard loads in <2 seconds

---

## Agent 21 — Deployment Infrastructure

### Role
Docker Compose, Helm charts, Kubernetes manifests, and CI/CD configuration.

### Current State & Gaps
- `docker-compose.yml` exists and works (5 services running)
- Helm charts exist at `infra/helm/archon-platform/` and `infra/helm/vault/`
- **Gap**: No CI/CD pipeline definitions
- **Gap**: Helm values need updating for new services/features
- **Gap**: No monitoring stack (Prometheus, Grafana)

### Responsibilities
1. **Docker Compose Enhancement**: Add Vault container, monitoring stack (Prometheus + Grafana), worker containers
2. **Helm Chart Updates**: Update values for new endpoints, env vars, replicas
3. **CI/CD**: GitHub Actions workflows for test, build, deploy
4. **Monitoring**: Prometheus metrics endpoint on backend, Grafana dashboards

### Acceptance Criteria
- [ ] `docker compose up` starts all services cleanly
- [ ] Helm chart deploys to K8s
- [ ] CI pipeline runs tests on PR

---

## Agent 22 — Master Validator

### Role
End-to-end validation: runs full test suite, SDD check, branding verification, live smoke tests, and UX audit.

### Current State & Gaps
- 1092 tests passing, SDD 10/10, branding clean
- **Gap**: No automated UX audit — manual verification only
- **Gap**: No integration tests between frontend and backend

### Responsibilities
1. **Test Suite**: Run `pytest` — 1092+ tests, 0 failures
2. **SDD Check**: Run SDD scorer — 10/10
3. **Branding**: Verify zero "openairia" references
4. **Smoke Tests**: Automated curl tests for all API endpoints
5. **Frontend Build**: `docker compose build frontend` — no errors
6. **UX Audit Checklist**:
   - Every page loads without errors
   - No raw JSON fields visible on standard forms
   - All buttons have functional click handlers
   - All forms submit to correct API endpoints
   - Navigation works (all sidebar items lead to real pages)
   - Error states show friendly messages
   - Empty states show helpful guidance (not just "no data")
7. **Cross-Agent Integration**: Verify data flows between agents (e.g., create agent → execute → see in audit log)

### Acceptance Criteria
- [ ] 1092+ tests pass
- [ ] SDD 10/10
- [ ] All pages load without error
- [ ] No JSON fields on standard forms
- [ ] Create → Execute → Trace → Audit flow works end-to-end
- [ ] All sidebar items navigate to functional pages
