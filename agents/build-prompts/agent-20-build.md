# Agent 20 — Dashboard — Build Prompt

> Hand this file to a coding agent. It contains everything needed to build this component.

## Context
You are building the **Dashboard** — the landing page with executive summary of platform state and actionable quick-start actions.
Project root: `~/Scripts/Archon/`

## What Already Exists (do NOT rebuild these)
- `frontend/src/pages/DashboardPage.tsx` (381 lines) — Stat cards (agents/executions/models/policies all showing 0), "No agents yet", "No executions yet". EXTEND to show real data and add actions.

## What to Build

### 1. Summary Stats (real data from APIs)
Four stat cards, each with: number, label, trend arrow (vs yesterday), click → navigate to detail page
- Active Agents: fetch from GET /api/v1/agents/ (count where status=active)
- Executions Today: fetch from GET /api/v1/executions/?created_after=today
- Models Configured: fetch from GET /api/v1/router/models (count)
- Total Cost (This Month): fetch from GET /api/v1/cost/summary?period=monthly

### 2. Quick Actions Bar
Horizontal bar with icon buttons:
- "Create Agent" → opens Agent 05 wizard
- "Run Agent" → opens execution dialog (select agent dropdown + input textarea + "Run" button)
- "Browse Templates" → navigates to /templates
- "Import Agent" → file upload dialog (JSON/YAML)

### 3. Recent Activity Feed
Card showing last 10 audit events from GET /api/v1/audit-logs/?limit=10
Each event: icon (based on action type), actor avatar/initials, action description, relative timestamp
"View All" link → navigates to /audit

### 4. System Health Mini-Status
Horizontal row of small status indicators: API ●, DB ●, Redis ●, Vault ●, Keycloak ●
Green = up, Red = down, Yellow = degraded
Data from GET /api/v1/health

### 5. Agent Leaderboard
Top 5 agents by execution count (this month). Small bar chart or ranked list.
Data from GET /api/v1/agents/ sorted by execution count.

### 6. Cost Summary Widget
Mini area chart showing daily spend over last 7 days.
Current week total and comparison to last week.
Data from GET /api/v1/cost/chart?period=daily&range=7d

## Patterns to Follow (from OSS)

### Pattern 1: Dify App Overview (dify/web/app/components/app/overview/)
Dify's app overview shows usage stats (total messages, active users, average session time), a usage chart, and recent messages. Each stat is a card with the number and a trend indicator. Adaptation: Same card+chart pattern but with Archon-specific metrics (agents, executions, cost, models).

### Pattern 2: Flowise Dashboard
Flowise has a simple dashboard showing chatflow count and recent chatflows. Adaptation: More comprehensive — add cost, health, activity feed, and quick actions that Flowise lacks.

## Backend Deliverables
No new backend endpoints needed. Dashboard aggregates data from existing APIs:
- GET /api/v1/agents/ (count)
- GET /api/v1/executions/ (today's count)
- GET /api/v1/router/models (count)
- GET /api/v1/cost/summary (monthly total)
- GET /api/v1/audit-logs/ (last 10)
- GET /api/v1/health (service status)

If any of these don't support the needed query params, add them:
- `GET /api/v1/agents/?status=active` — filter by status
- `GET /api/v1/executions/?created_after=YYYY-MM-DD` — filter by date

## Frontend Deliverables

| Component | Action | Description |
|---|---|---|
| `pages/DashboardPage.tsx` | MODIFY | Real data, quick actions, activity feed |
| `components/dashboard/StatCard.tsx` | CREATE | Stat card with number, trend, click action |
| `components/dashboard/QuickActions.tsx` | CREATE | Action buttons bar |
| `components/dashboard/ActivityFeed.tsx` | CREATE | Recent audit events |
| `components/dashboard/HealthIndicators.tsx` | CREATE | Service status dots |
| `components/dashboard/AgentLeaderboard.tsx` | CREATE | Top agents chart |
| `components/dashboard/CostWidget.tsx` | CREATE | Mini cost chart |
| `components/dashboard/RunAgentDialog.tsx` | CREATE | Quick run dialog |

## Integration Points
- **Agent 01 (Backend)**: Agent count
- **Agent 05 (Wizard)**: "Create Agent" opens wizard
- **Agent 06 (Executions)**: Execution count, Run Agent dialog
- **Agent 08 (Router)**: Model count
- **Agent 11 (Cost)**: Cost summary and chart data
- **Agent 18 (Audit)**: Recent activity feed
- **Agent 19 (Settings)**: Health status from /api/v1/health

## Acceptance Criteria
1. All stat cards show real data from APIs (not hardcoded 0)
2. Stat cards show trend arrows (up/down vs yesterday/last week)
3. Click stat card → navigates to respective detail page
4. Quick action buttons work: Create Agent opens wizard, Run Agent opens dialog
5. Recent activity feed shows last 10 audit events with icons and timestamps
6. System health indicators show actual service status (green/red/yellow)
7. Agent leaderboard shows top 5 agents by execution count
8. Cost widget shows 7-day spend chart
9. Dashboard loads in <2 seconds
10. Empty states show helpful guidance (not just "0")

## Files to Read Before Starting
- `~/Scripts/Archon/agents/AGENT_RULES.md`
- `~/Scripts/Archon/frontend/src/pages/DashboardPage.tsx`

## Files to Create/Modify

| Path | Action |
|---|---|
| `frontend/src/pages/DashboardPage.tsx` | MODIFY |
| `frontend/src/components/dashboard/StatCard.tsx` | CREATE |
| `frontend/src/components/dashboard/QuickActions.tsx` | CREATE |
| `frontend/src/components/dashboard/ActivityFeed.tsx` | CREATE |
| `frontend/src/components/dashboard/HealthIndicators.tsx` | CREATE |
| `frontend/src/components/dashboard/AgentLeaderboard.tsx` | CREATE |
| `frontend/src/components/dashboard/CostWidget.tsx` | CREATE |
| `frontend/src/components/dashboard/RunAgentDialog.tsx` | CREATE |

## Testing
```bash
cd ~/Scripts/Archon && docker compose build frontend
# Open http://localhost:3000/ (dashboard)
# 1. Verify stat cards show real numbers (or helpful empty states)
# 2. Click "Create Agent" → verify wizard opens
# 3. Click "Run Agent" → verify dialog with agent selector opens
# 4. Verify health indicators show colored dots
# 5. Verify activity feed shows recent events
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
