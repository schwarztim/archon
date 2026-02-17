# Agent 03 — NL-to-Agent Wizard — Build Prompt

> Hand this file to a coding agent. It contains everything needed to build this component.

## Context

You are building the **Natural Language to Agent Wizard** for Archon — a 4-step conversational wizard that converts a plain English description into a fully structured agent with graph definition.
Project root: `~/Scripts/Archon/`

## What Already Exists (do NOT rebuild these)

- `backend/app/services/wizard_service.py` (719 lines) — NL→LangGraph conversion logic. KEEP — wire frontend to this.
- `backend/app/routes/wizard.py` (183 lines) — Wizard API endpoints (POST /wizard/describe, /wizard/generate, /wizard/create). KEEP.
- `backend/app/models/wizard.py` (166 lines) — Wizard data models. KEEP.
- `frontend/src/components/wizard/AgentWizard.tsx` (945 lines) — Wizard component EXISTS. EXTEND/FIX to wire to backend.
- `frontend/src/pages/AgentsPage.tsx` (601 lines) — Needs "Create with AI" button to open wizard. MODIFY.
- `frontend/src/pages/DashboardPage.tsx` (381 lines) — Needs "Quick Start" button to open wizard. MODIFY.

## What to Build

### 1. Wire AgentWizard to Backend
The 945-line AgentWizard.tsx exists but may not be fully wired to the backend wizard endpoints. Ensure:

- **Step 1 — Describe**: Large textarea. On "Next", calls `POST /api/v1/wizard/describe` with the description text. Shows loading spinner during AI processing.
- **Step 2 — Plan**: Backend returns a structured plan (proposed steps, tools, model choices). Display as editable card list (NOT raw JSON/text). Each card: step name, type badge, description, edit pencil icon. User can reorder, remove, add cards. "Regenerate" button re-calls describe with modifications.
- **Step 3 — Configure**: AI-generated agent config shown as rich form sections:
  - Model Selection: Dropdown from /router/models with provider badges
  - Temperature: Slider with labels (Creative/Balanced/Precise)
  - Guardrails: Toggle switches for DLP, cost limit input, allowed domains
  - Each field has info tooltip explaining what it does
- **Step 4 — Preview & Create**: 
  - Read-only React Flow graph preview showing the proposed agent flow
  - Summary cards for all config
  - "Create Agent" button → POST /api/v1/wizard/create → saves to backend → redirect to builder
  - "Edit in Builder" button → opens builder with the generated graph

### 2. Entry Points
- AgentsPage: Add "Create with AI ✨" button next to existing "Create Agent" button
- DashboardPage: Add "Quick Start" card that opens the wizard
- Both open the AgentWizard modal

### 3. Template Suggestions
During Step 2, show a "Similar Templates" sidebar section that queries `/api/v1/templates?search={keywords}` and displays matching templates as small cards. Clicking a template pre-fills the plan.

## Patterns to Follow (from OSS)

### Pattern 1: Dify Create App Dialog (from dify/web/app/components/app/create-app-dialog/)
Dify's app creation offers multiple paths: "Create from Blank", "Create from Template", and uses a step-by-step flow. The dialog is a full-screen modal with clear step indicators. Archon adaptation: Use a similar full-screen modal with step progress bar at top. Offer both "From Scratch" (regular wizard) and "Describe with AI" (NL wizard) paths.

### Pattern 2: Coze Studio Bot Creation (from coze-studio)
Coze's bot creation has a description-first flow where users type what they want, then the platform suggests configuration. The suggestion is shown as an editable structured form, not raw text. Archon adaptation: Step 2's plan output should be structured cards, each representing a step in the agent's flow, editable inline.

## Backend Deliverables

No new backend endpoints needed — existing wizard.py endpoints are sufficient:
- `POST /api/v1/wizard/describe` — accepts description, returns structured plan
- `POST /api/v1/wizard/generate` — accepts plan modifications, returns full agent spec
- `POST /api/v1/wizard/create` — accepts final spec, creates Agent record

Verify these endpoints work and return the expected shapes. If response shapes don't match frontend needs, add adapter logic in the frontend API client.

## Frontend Deliverables

| Component | Action | Description |
|---|---|---|
| `components/wizard/AgentWizard.tsx` | MODIFY | Wire all 4 steps to backend endpoints |
| `pages/AgentsPage.tsx` | MODIFY | Add "Create with AI" button |
| `pages/DashboardPage.tsx` | MODIFY | Add Quick Start wizard trigger |
| `api/wizard.ts` | CREATE | API client for wizard endpoints |
| `components/wizard/PlanCard.tsx` | CREATE | Editable plan step card component |
| `components/wizard/ConfigForm.tsx` | CREATE | Step 3 configuration form |
| `components/wizard/GraphPreview.tsx` | CREATE | Step 4 React Flow read-only preview |
| `components/wizard/TemplateSuggestions.tsx` | CREATE | Template suggestion sidebar |

## Integration Points

- **Agent 01 (Backend)**: Wizard creates Agent via standard CRUD (POST /agents)
- **Agent 02 (Builder)**: Step 4 "Edit in Builder" navigates to /builder?agentId={id}
- **Agent 04 (Templates)**: Template suggestions query /templates endpoint
- **Agent 08 (Router)**: Step 3 model dropdown fetches /router/models

## Acceptance Criteria

1. Wizard accessible from AgentsPage "Create with AI" button
2. Wizard accessible from DashboardPage Quick Start
3. Step 1: Description textarea submits to backend and shows loading state
4. Step 2: AI plan shown as editable cards, not raw JSON/text
5. Step 3: Config shown as form with dropdowns/sliders/toggles
6. Step 4: React Flow graph preview renders the proposed agent
7. "Create Agent" creates a real agent retrievable via GET /agents/{id}
8. "Edit in Builder" opens builder with the wizard-generated graph
9. Zero raw JSON visible to user at any step

## Files to Read Before Starting

- `~/Scripts/Archon/agents/AGENT_RULES.md` (mandatory coding standards)
- `~/Scripts/Archon/frontend/src/components/wizard/AgentWizard.tsx` (existing 945-line wizard)
- `~/Scripts/Archon/backend/app/routes/wizard.py` (existing wizard endpoints)

## Files to Create/Modify

| Path | Action |
|---|---|
| `frontend/src/components/wizard/AgentWizard.tsx` | MODIFY |
| `frontend/src/pages/AgentsPage.tsx` | MODIFY |
| `frontend/src/pages/DashboardPage.tsx` | MODIFY |
| `frontend/src/api/wizard.ts` | CREATE |
| `frontend/src/components/wizard/PlanCard.tsx` | CREATE |
| `frontend/src/components/wizard/ConfigForm.tsx` | CREATE |
| `frontend/src/components/wizard/GraphPreview.tsx` | CREATE |
| `frontend/src/components/wizard/TemplateSuggestions.tsx` | CREATE |

## Testing

```bash
cd ~/Scripts/Archon && docker compose build frontend
# Open browser to http://localhost:3000/agents
# 1. Click "Create with AI" → wizard modal opens
# 2. Type "Build a customer support bot that uses Slack and Salesforce" → Next
# 3. Verify plan shows as editable cards
# 4. Modify a card → Next
# 5. Verify config form (not JSON)
# 6. Next → verify graph preview renders
# 7. Click "Create Agent" → verify agent created
# 8. Navigate to /agents → verify new agent in list
curl -X POST http://localhost:8000/api/v1/wizard/describe -H "Authorization: Bearer $TOKEN" -d '{"description":"customer support bot"}'
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
