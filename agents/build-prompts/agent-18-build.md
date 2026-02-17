# Agent 18 — Audit Log — Build Prompt

> Hand this file to a coding agent. It contains everything needed to build this component.

## Context
You are building the **Audit Log** system for Archon — immutable, queryable audit trail of all platform actions.
Project root: `~/Scripts/Archon/`

## What Already Exists (do NOT rebuild these)
- `frontend/src/pages/AuditPage.tsx` (151 lines) — List with filters, expand details. EXTEND.
- `backend/app/routes/audit_logs.py` (134 lines) — Basic list endpoint. FIX: add auth, handle empty DB, add filters.
- `backend/app/services/audit_log_service.py` (98 lines) — Audit service. EXTEND with middleware, export.
- `backend/app/models/audit.py` (48 lines) — AuditLog model (id, actor_id, action, resource_type, resource_id, details, created_at). KEEP.
- There is also `frontend/src/pages/admin/AuditLogPage.tsx` (309 lines) — Admin audit page. KEEP.

## What to Build

### 1. Fix Audit Loading
- Handle empty DB: return `{"data": [], "meta": {"pagination": {"total": 0}}}` not 500 error
- Add `Depends(get_current_user)` to all audit routes
- Fix Governance page's Audit Trail tab to call correct endpoint

### 2. Comprehensive Event Logging Middleware
Create FastAPI middleware that auto-logs on every state-changing request (POST/PUT/PATCH/DELETE):
- Captures: actor (from JWT), action (HTTP method + path → human readable e.g., "agent.created"), resource_type (from URL path), resource_id (from response), timestamp, IP address, tenant_id, outcome (success/failure), request_id
- Event types: agent.created, agent.updated, agent.deleted, agent.executed, user.invited, user.updated, user.removed, secret.created, secret.rotated, secret.accessed, policy.created, policy.updated, deployment.created, deployment.promoted, login.success, login.failure, sso.configured, budget.created, connector.created, connector.tested, template.instantiated, workflow.created, workflow.executed, approval.submitted, approval.approved, approval.rejected

### 3. Audit Dashboard Enhancement
- Timeline view: vertical timeline with event cards, infinite scroll
- Each card: icon (based on action type), actor name, action description, resource link, timestamp (relative)
- Filters: Date range picker, Actor dropdown (from users), Action type multi-select, Resource type multi-select, Outcome (success/failure)
- Search: Full-text search across event details
- Export: "Export" button → CSV or JSON download for selected date range

### 4. Immutability Enforcement
- No PUT or DELETE endpoints on audit_logs
- Database: if using RLS, add policy preventing UPDATE/DELETE on audit_logs table
- API: explicitly return 405 Method Not Allowed for PUT/DELETE on /audit-logs/

## Patterns to Follow (from OSS)

### Pattern 1: Dify Operation Logs (dify/api/services/operation_log_service.py if exists)
Dify logs significant operations with actor, action, and resource info. Operations are displayed in an admin panel. Adaptation: Archon logs ALL mutations automatically via middleware (not manual log calls). This ensures comprehensive coverage without developers forgetting to add audit calls.

### Pattern 2: Original Design — Auto-Logging Middleware
No OSS platform auto-logs all mutations via middleware. Designed from enterprise audit requirements (SOC2 CC7.2, GDPR Article 30). Pattern: Middleware inspects request method and path. For state-changing methods, it captures pre-request context, then post-response captures outcome. Audit entry created asynchronously (non-blocking) via background task.

## Backend Deliverables

| Endpoint | Method | Description |
|---|---|---|
| `GET /api/v1/audit-logs/` | GET | Fixed: auth, empty handling, filters, pagination |
| `GET /api/v1/audit-logs/export` | GET | Export as CSV/JSON |
| `PUT /api/v1/audit-logs/*` | - | Return 405 (immutable) |
| `DELETE /api/v1/audit-logs/*` | - | Return 405 (immutable) |

New/modified files:
- `backend/app/routes/audit_logs.py` — MODIFY — Fix auth, add filters, export, block mutations
- `backend/app/middleware/audit_middleware.py` — CREATE — Auto-logging middleware
- `backend/app/services/audit_log_service.py` — MODIFY — Add filter/export logic

## Frontend Deliverables

| Component | Action | Description |
|---|---|---|
| `pages/AuditPage.tsx` | MODIFY | Timeline view, enhanced filters, export |
| `components/audit/AuditTimeline.tsx` | CREATE | Vertical timeline with event cards |
| `components/audit/AuditFilters.tsx` | CREATE | Date/actor/action/resource filters |
| `components/audit/ExportButton.tsx` | CREATE | CSV/JSON export |
| `components/audit/AuditEventCard.tsx` | CREATE | Single event card with icon/details |

## Integration Points
- **All agents**: Every mutation logs to audit trail via middleware
- **Agent 13 (Governance)**: Audit data feeds compliance reporting, Governance Audit Trail tab
- **Agent 16 (Tenants)**: Audit entries scoped to tenant

## Acceptance Criteria
1. Audit page loads without errors when DB is empty (shows empty state, not error)
2. Every mutation API call (POST/PUT/PATCH/DELETE) creates an audit entry automatically
3. Filters work: date range, actor, action type, resource type
4. Full-text search across audit event details
5. Export button produces valid CSV with audit data
6. No PUT/DELETE endpoints exist for audit logs (returns 405)
7. Auth required on all audit endpoints
8. Governance page Audit Trail tab loads correctly

## Files to Read Before Starting
- `~/Scripts/Archon/agents/AGENT_RULES.md`
- `~/Scripts/Archon/backend/app/routes/audit_logs.py`
- `~/Scripts/Archon/backend/app/models/audit.py`

## Files to Create/Modify

| Path | Action |
|---|---|
| `backend/app/routes/audit_logs.py` | MODIFY |
| `backend/app/middleware/audit_middleware.py` | CREATE |
| `backend/app/services/audit_log_service.py` | MODIFY |
| `frontend/src/pages/AuditPage.tsx` | MODIFY |
| `frontend/src/components/audit/AuditTimeline.tsx` | CREATE |
| `frontend/src/components/audit/AuditFilters.tsx` | CREATE |
| `frontend/src/components/audit/ExportButton.tsx` | CREATE |
| `frontend/src/components/audit/AuditEventCard.tsx` | CREATE |

## Testing
```bash
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q
curl http://localhost:8000/api/v1/audit-logs/ -H "Authorization: Bearer $TOKEN"
# Create an agent, then check audit log has the event
curl -X POST http://localhost:8000/api/v1/agents -H "Authorization: Bearer $TOKEN" -d '{"name":"test"}'
curl "http://localhost:8000/api/v1/audit-logs/?action=agent.created" -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/v1/audit-logs/export?format=csv -H "Authorization: Bearer $TOKEN" -o audit.csv
# Verify immutability
curl -X DELETE http://localhost:8000/api/v1/audit-logs/some-id -H "Authorization: Bearer $TOKEN"
# Should return 405
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
