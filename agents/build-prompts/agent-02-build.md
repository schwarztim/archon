# Agent 02 — Visual Graph Builder — Build Prompt

> Hand this file to a coding agent. It contains everything needed to build this component.

## Context

You are building the **Visual Graph Builder** for Archon — a drag-and-drop React Flow 12 canvas where users compose AI agent logic by connecting nodes.
Project root: `~/Scripts/Archon/`

## What Already Exists (do NOT rebuild these)

- `frontend/src/pages/BuilderPage.tsx` (84 lines) — React Flow provider + canvas/palette/properties layout. EXTEND.
- `frontend/src/components/canvas/AgentCanvas.tsx` (154 lines) — React Flow canvas component. EXTEND.
- `frontend/src/components/canvas/TopBar.tsx` (257 lines) — Builder toolbar with save/load/new/theme. KEEP.
- `frontend/src/components/canvas/BaseNode.tsx` (118 lines) — Base node component with handles. EXTEND.
- `frontend/src/components/palette/NodePalette.tsx` (140 lines) — Node palette sidebar. EXTEND with categories.
- `frontend/src/components/properties/PropertyPanel.tsx` (1190 lines) — Property panel for selected node. EXTEND.
- `frontend/src/stores/canvasStore.ts` (173 lines) — Zustand store for canvas state. EXTEND.
- `frontend/src/hooks/useAgents.ts` (70 lines) — Agent API hook. KEEP.
- 28 node type components in `frontend/src/components/canvas/` (23-33 lines each) — Skeleton node types. EXTEND with rich config.

Existing node types (all ~25 lines, skeleton only):
InputNode, OutputNode, LLMNode, ToolNode, ConditionNode, BaseNode, MCPToolNode, FunctionCallNode, HTTPRequestNode, DatabaseQueryNode, VectorSearchNode, DocumentLoaderNode, EmbeddingNode, VisionNode, StructuredOutputNode, HumanApprovalNode, HumanInputNode, SubAgentNode, LoopNode, ParallelNode, MergeNode, SwitchNode, DelayNode, WebhookTriggerNode, ScheduleTriggerNode, StreamOutputNode, CostGateNode, DLPScanNode

## What to Build

### 1. Enhance Node Types with Rich Configuration
Each node type component needs to expose configuration fields (not JSON) that PropertyPanel renders:
- **LLMNode**: model (dropdown from /router/models), temperature (slider 0-2), max_tokens (number), system_prompt (textarea with syntax highlighting)
- **ToolNode/MCPToolNode**: MCP server picker (dropdown), tool selector (auto-populated from selected server), parameter mapping (key-value form)
- **ConditionNode**: Visual condition builder: field (input), operator (dropdown: equals/contains/gt/lt), value (input). Multiple conditions with AND/OR toggle.
- **InputNode**: Input name, description, required toggle, type selector (text/number/file/json)
- **OutputNode**: Output name, format selector (text/json/stream)
- **HTTPRequestNode**: Method (dropdown), URL (input), Headers (key-value), Body (textarea), Auth type (dropdown)
- **DatabaseQueryNode**: Connector selector (dropdown from /connectors), Query (SQL editor), Parameters (key-value)
- **VectorSearchNode**: Collection (dropdown), Query field, Top-K (slider), Similarity threshold (slider)

### 2. Node Palette Categories
Organize NodePalette into collapsible categories:
- **Triggers**: UserInput, WebhookTrigger, ScheduleTrigger
- **AI Models**: ChatCompletion (LLM), Embedding, Vision, StructuredOutput
- **Tools**: MCPTool, FunctionCall, HTTPRequest, DatabaseQuery
- **Logic**: Condition, Switch, Loop, Parallel, Merge, Delay
- **RAG**: VectorSearch, DocumentLoader
- **Human**: HumanApproval, HumanInput
- **Agents**: SubAgent
- **Security**: DLPScan, CostGate
- **Output**: Output, StreamOutput

### 3. Save/Load Integration
- Save: Serialize React Flow nodes + edges → PUT /api/v1/agents/{id} with graph_definition field
- Load: GET /api/v1/agents/{id} → deserialize graph_definition → restore React Flow state
- The BuilderPage already has agentId from URL params and loads agent data — enhance to fully restore graph
- Auto-save draft every 30 seconds

### 4. Validation
- Require at least 1 trigger/input node and 1 output node
- All edges must connect compatible ports (validate port types)
- Show validation errors as red badges on invalid nodes
- Validate before save — block save if invalid, show error list

### 5. Test Run Panel
- "Test" button in TopBar → opens side panel
- User enters sample input
- Sends POST /api/v1/agents/{id}/execute with test input
- Shows step-by-step execution results in the panel (streaming via WebSocket when available)

### 6. NL Integration
- "Describe with AI" button in TopBar
- Opens Agent 03's wizard modal
- Wizard output populates the canvas with nodes and edges

## Patterns to Follow (from OSS)

### Pattern 1: Dify Workflow Editor (from dify/web/app/components/workflow/)
Dify uses React Flow with custom node types registered via `nodeTypes` map. Each node type has a `data` object containing all configuration. Nodes are organized into categories in a panel. The editor supports zoom, minimap, and undo/redo. Key pattern: nodes define their own `getDefaultData()` factory and `validate()` method. Archon adaptation: Each node component exports a `defaultConfig` and `configSchema` (Zod) that PropertyPanel uses to render the correct form.

### Pattern 2: Flowise Node Palette (from flowise/packages/ui/)
Flowise organizes nodes into categories with search. Each node has an icon, label, description, and category. Drag from palette → drop on canvas creates node with default config. The palette is filterable by text search and category tabs. Archon adaptation: NodePalette should have a search bar at top, collapsible category sections, and each node item shows icon + name + one-line description.

### Pattern 3: Dify Node Configuration Panels (from dify/web/app/components/workflow/nodes/)
Each Dify node type has its own configuration component (e.g., `llm/panel.tsx`, `tool/panel.tsx`). When selected, the right panel renders the node-specific form. This avoids a monolithic property panel. Archon adaptation: PropertyPanel already exists at 1190 lines — it likely already switches on node type. Extend it to render richer forms per node type using the node's configSchema.

### Pattern 4: Coze Studio Workflow Nodes (from coze-studio)
Coze defines node types with a declarative schema that includes: inputs (typed ports), outputs (typed ports), parameters (form fields with types), and validation rules. This schema-driven approach means new node types just need a schema file. Archon adaptation: Consider a `NodeTypeRegistry` that maps node type → {icon, label, category, defaultConfig, configSchema, validate}.

## Backend Deliverables

No new backend endpoints needed — uses existing:
- `PUT /api/v1/agents/{id}` — saves graph_definition field
- `GET /api/v1/agents/{id}` — loads graph_definition
- `POST /api/v1/agents/{id}/execute` — test run (from Agent 01)
- `GET /api/v1/router/models` — model list for LLM node dropdown
- `GET /api/v1/connectors` — connector list for DB node dropdown

## Frontend Deliverables

| Component | Action | Description |
|---|---|---|
| `components/canvas/AgentCanvas.tsx` | MODIFY | Register all node types, add validation overlay |
| `components/palette/NodePalette.tsx` | MODIFY | Add categories, search, node descriptions |
| `components/properties/PropertyPanel.tsx` | MODIFY | Add rich forms per node type |
| `stores/canvasStore.ts` | MODIFY | Add auto-save, validation state, dirty tracking |
| `components/canvas/LLMNode.tsx` | MODIFY | Add config fields (model, temp, etc.) |
| `components/canvas/ConditionNode.tsx` | MODIFY | Add visual condition builder |
| `components/canvas/MCPToolNode.tsx` | MODIFY | Add MCP server/tool pickers |
| `components/canvas/HTTPRequestNode.tsx` | MODIFY | Add method/url/headers/body form |
| `components/canvas/DatabaseQueryNode.tsx` | MODIFY | Add connector picker, SQL editor |
| `components/canvas/VectorSearchNode.tsx` | MODIFY | Add collection/topK/threshold |
| All other node components | MODIFY | Add relevant config fields |
| `components/builder/TestRunPanel.tsx` | CREATE | Test execution side panel |
| `components/builder/ValidationOverlay.tsx` | CREATE | Validation error badges |
| `types/nodeTypes.ts` | CREATE | NodeTypeRegistry with schemas |

## Integration Points

- **Agent 01 (Backend)**: Save/load via PUT/GET /agents/{id} with graph_definition
- **Agent 03 (NL Wizard)**: "Describe with AI" opens wizard, result populates canvas
- **Agent 05 (Wizard)**: Step 7 embeds a read-only React Flow preview of the agent graph
- **Agent 06 (Executions)**: Test Run sends POST /agents/{id}/execute
- **Agent 08 (Router)**: LLM node model dropdown fetches GET /router/models
- **Agent 09 (Connectors)**: DB node connector dropdown fetches GET /connectors

## Acceptance Criteria

1. Canvas renders 28+ node types organized in categorized palette with search
2. Selecting any node shows a rich property form (zero JSON fields for common config)
3. LLM node has model dropdown, temperature slider, system prompt editor
4. Condition node has visual condition builder (field/operator/value rows)
5. Graph saves to backend via graph_definition and reloads on page revisit
6. "Edit" from AgentsPage loads correct graph in builder
7. Validation prevents saving graphs without Input+Output nodes
8. Test Run panel sends execution and shows results
9. Auto-save drafts every 30 seconds
10. Works on 1920x1080 and 1440px screens without overflow

## Files to Read Before Starting

- `~/Scripts/Archon/agents/AGENT_RULES.md` (mandatory coding standards)
- `~/Scripts/Archon/frontend/src/components/properties/PropertyPanel.tsx` (existing 1190-line panel)
- `~/Scripts/Archon/frontend/src/components/palette/NodePalette.tsx` (existing palette)

## Files to Create/Modify

| Path | Action |
|---|---|
| `frontend/src/components/canvas/AgentCanvas.tsx` | MODIFY |
| `frontend/src/components/palette/NodePalette.tsx` | MODIFY |
| `frontend/src/components/properties/PropertyPanel.tsx` | MODIFY |
| `frontend/src/stores/canvasStore.ts` | MODIFY |
| `frontend/src/components/canvas/LLMNode.tsx` | MODIFY |
| `frontend/src/components/canvas/ConditionNode.tsx` | MODIFY |
| `frontend/src/components/canvas/MCPToolNode.tsx` | MODIFY |
| `frontend/src/components/canvas/HTTPRequestNode.tsx` | MODIFY |
| `frontend/src/components/canvas/DatabaseQueryNode.tsx` | MODIFY |
| `frontend/src/components/canvas/VectorSearchNode.tsx` | MODIFY |
| `frontend/src/components/builder/TestRunPanel.tsx` | CREATE |
| `frontend/src/components/builder/ValidationOverlay.tsx` | CREATE |
| `frontend/src/types/nodeTypes.ts` | CREATE |

## Testing

```bash
cd ~/Scripts/Archon && docker compose build frontend
# Open browser to http://localhost:3000/builder
# 1. Drag LLM node from palette → canvas
# 2. Click node → verify property panel shows model dropdown, temp slider, system prompt
# 3. Connect Input → LLM → Output
# 4. Click Save → verify no errors
# 5. Refresh page → verify graph reloads
# 6. From AgentsPage, click Edit on an agent → verify builder loads its graph
# 7. Try saving without Output node → verify validation error shown
```

## Constraints

- Python 3.12, type hints, docstrings. Use `python3` not `python`.
- Always `PYTHONPATH=backend` for pytest.
- API envelope: `{"data": ..., "meta": {"request_id", "timestamp"}}`
- No raw JSON fields on any user-facing form.
- All credentials via SecretsManager, never in DB.
- Never use `password=value` directly — use dict unpacking.
- Do NOT read ROADMAP.md, INSTRUCTIONS.md, ARCHITECTURE.md.
- Tests must pass: `cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q`
