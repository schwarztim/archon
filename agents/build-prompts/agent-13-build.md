# Agent 13 — Governance & Registry — Build Prompt

## Context

You are building the **Governance & Registry** module for the Archon AI orchestration platform. This module provides an agent registry with compliance status tracking, policy-based compliance scanning, approval workflows for agent promotion to production, and a working audit trail.

**Stack:** Backend: Python 3.12, FastAPI, SQLModel, Alembic, AsyncSession. Frontend: React 19, TypeScript strict, shadcn/ui, Tailwind, React Flow. Auth: JWT via Keycloak. Secrets: HashiCorp Vault via `backend/app/secrets/manager.py`.

---

## What Already Exists

| File | Lines | Status |
|------|-------|--------|
| `frontend/src/pages/GovernancePage.tsx` | 308 | Agent Registry form, Compliance Policies form, Audit Trail tab (fails to load). **REDESIGN.** |
| `frontend/src/api/governance.ts` | 81 | Governance API client. **EXTEND.** |
| `backend/app/routes/governance.py` | 547 | Governance CRUD. **EXTEND.** |
| `backend/app/services/governance_service.py` | 698 | Governance service. **EXTEND.** |
| `backend/app/models/governance.py` | 259 | Governance models. **KEEP.** |

---

## What to Build

### 1. Agent Registry Dashboard

Visual grid/table of **all** registered agents with the following columns:

- **Name** — agent display name
- **Version** — semantic version string
- **Owner** — user or team that owns the agent
- **Compliance Status** — badge: `Compliant` (green), `At Risk` (yellow), `Non-Compliant` (red)
- **Risk Score** — numeric 0–100, color-coded
- **Last Scan Date** — relative timestamp
- **Actions** — View / Scan / Archive buttons

Clicking an agent opens a **detail view** with:
- Full agent metadata
- Compliance history timeline (list of past scan results)
- Active policy violations

**Bulk actions** toolbar: Request Review, Archive, Flag for selected agents.

### 2. Compliance Policies

**Policy Template Gallery** with pre-built templates:

| Template | Example Requirements |
|----------|---------------------|
| SOC2 | Data encrypted at rest, Audit logging enabled, Access controls defined, Change management documented |
| GDPR | Data retention policy, Right to erasure, Consent management, Data processing agreement |
| HIPAA | PHI access logging, Minimum necessary access, Encryption in transit, BAA in place |
| PCI-DSS | Cardholder data protection, Network segmentation, Vulnerability management |
| ISO 27001 | Risk assessment, Information security policy, Asset management |
| Custom | User-defined requirements |

Each policy has **checkable requirements**. When a policy is applied to an agent, each requirement can be checked (pass/fail) either manually or via automated scan.

**Auto-scan:** Agents are periodically checked against all active policies. Results stored as `ComplianceScanResult` records.

**Compliance Score:** 0–100 per agent, calculated as `(passed_requirements / total_requirements) * 100`.

### 3. Approval Workflows

When an agent moves to production (via Agent 10 Lifecycle), trigger an approval flow:

- **Configure approval:** Assign reviewers (dropdown from users list), set approval rules (`Any 1`, `All`, `Majority`).
- **Reviewer dashboard:** Pending approvals list with:
  - Agent summary (name, version, compliance score)
  - Approve / Reject buttons
  - Comments textarea (required on reject, optional on approve)
- **Status tracking:** Pending → Approved / Rejected. Notification to agent owner on decision.

### 4. Audit Trail Fix

Wire the Audit Trail tab to `GET /api/v1/audit-logs/` endpoint correctly. Display:
- Timeline of governance events (scans, approvals, policy changes, agent status changes)
- Filterable by event type, date range, user
- Each entry: timestamp, actor, action, target, details

---

## Patterns to Follow

### Pattern 1: Original Design — Policy-as-Code Compliance

No direct OSS reference for agent governance. Designed from first principles based on enterprise compliance frameworks (SOC2, GDPR).

**Pattern:** Policy-as-code where each compliance requirement maps to an automated check function. Agents are scanned against policies on create/update and periodically. Results stored as `ComplianceScanResult` records.

```
PolicyTemplate → [Requirement] → CheckFunction(agent) → ScanResult(pass/fail)
Agent.compliance_score = sum(passed) / total * 100
```

### Pattern 2: Dify Workspace Management

**Source:** `dify/api/services/workspace_service.py`

Dify has workspace-level settings and member roles (Owner, Admin, Editor, Viewer).

**Adaptation:** Extend the role concept to include a `Compliance Reviewer` role and permission gates for approval workflows. Reviewers can only see agents assigned to them for review. Approval actions gated behind `governance:approve` permission.

---

## Backend Deliverables

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/governance/registry` | All agents with compliance status, risk score, last scan |
| `GET` | `/api/v1/governance/registry/{agent_id}` | Agent detail with compliance history |
| `POST` | `/api/v1/governance/scan/{agent_id}` | Run compliance scan against active policies |
| `GET` | `/api/v1/governance/policies` | List policy templates |
| `POST` | `/api/v1/governance/policies` | Create policy from template or custom |
| `PUT` | `/api/v1/governance/policies/{id}` | Update policy requirements |
| `DELETE` | `/api/v1/governance/policies/{id}` | Soft-delete policy |
| `GET` | `/api/v1/governance/approvals` | Pending approvals for current user |
| `POST` | `/api/v1/governance/approvals/{id}/approve` | Approve with optional comment |
| `POST` | `/api/v1/governance/approvals/{id}/reject` | Reject with required comment |
| `GET` | `/api/v1/audit-logs/` | Audit log entries (paginated, filterable) |

All endpoints return envelope format: `{"data": ..., "meta": {"request_id": "...", "timestamp": "..."}}`.

All endpoints require JWT auth. All queries scoped to `tenant_id`. All mutations produce `AuditLog` entries.

---

## Frontend Deliverables

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/pages/GovernancePage.tsx` | **MODIFY** | Redesign with Registry dashboard, Policy gallery, Approval queue tabs |
| `frontend/src/components/governance/RegistryDashboard.tsx` | **CREATE** | Agent grid/table with compliance badges, risk scores, bulk actions |
| `frontend/src/components/governance/AgentDetail.tsx` | **CREATE** | Agent detail view with compliance history timeline |
| `frontend/src/components/governance/PolicyGallery.tsx` | **CREATE** | Policy template cards (SOC2, GDPR, HIPAA, etc.) |
| `frontend/src/components/governance/PolicyDetail.tsx` | **CREATE** | Checkable requirements list per policy |
| `frontend/src/components/governance/ApprovalQueue.tsx` | **CREATE** | Pending approvals list for current reviewer |
| `frontend/src/components/governance/ApprovalCard.tsx` | **CREATE** | Approve/reject card with comments textarea |
| `frontend/src/api/governance.ts` | **MODIFY** | Add registry, scan, policies, approvals endpoints |

All components must support dark/light mode via Tailwind classes.

---

## Integration Points

- **Agent 10 (Lifecycle):** When agent status changes to `production`, create an `ApprovalRequest` record if approval workflow is configured.
- **Audit Logs:** All governance mutations (scan, approve, reject, policy change) write to the shared `AuditLog` table.
- **Auth:** Approval actions gated behind `governance:approve` permission from JWT claims.
- **Secrets:** No secrets stored by this agent directly, but compliance scans may reference SecretsManager to verify agent configurations.

---

## Acceptance Criteria

1. **PASS/FAIL:** Registry dashboard shows all agents with compliance status badges (`Compliant`/`At Risk`/`Non-Compliant`) and numeric risk scores (0–100).
2. **PASS/FAIL:** `POST /api/v1/governance/scan/{agent_id}` runs a compliance scan and returns scan results with per-requirement pass/fail.
3. **PASS/FAIL:** At least 3 policy templates are available: SOC2, GDPR, and Custom.
4. **PASS/FAIL:** Approval workflow: assign reviewers, approve/reject with comments, status updates.
5. **PASS/FAIL:** Audit Trail tab on GovernancePage loads without errors and displays governance events.
6. **PASS/FAIL:** Risk score (0–100) is visible per agent in the registry dashboard.
7. **PASS/FAIL:** Compliance score updates after a scan completes.

---

## Files to Read Before Starting

- `backend/app/models/governance.py` — Understand existing models before extending
- `backend/app/routes/governance.py` — Existing route structure
- `backend/app/services/governance_service.py` — Existing business logic
- `frontend/src/pages/GovernancePage.tsx` — Current UI to redesign
- `frontend/src/api/governance.ts` — Current API client
- `backend/app/models/audit.py` — AuditLog model for integration
- `backend/app/secrets/manager.py` — SecretsManager interface

---

## Files to Create / Modify

| File | Action | Notes |
|------|--------|-------|
| `backend/app/routes/governance.py` | MODIFY | Add registry, scan, policies, approvals endpoints |
| `backend/app/services/governance_service.py` | MODIFY | Add scan logic, approval workflow, policy templates |
| `frontend/src/pages/GovernancePage.tsx` | MODIFY | Redesign with tabbed layout |
| `frontend/src/api/governance.ts` | MODIFY | Add new API methods |
| `frontend/src/components/governance/RegistryDashboard.tsx` | CREATE | Agent grid with compliance data |
| `frontend/src/components/governance/AgentDetail.tsx` | CREATE | Detail view with history |
| `frontend/src/components/governance/PolicyGallery.tsx` | CREATE | Template cards |
| `frontend/src/components/governance/PolicyDetail.tsx` | CREATE | Checkable requirements |
| `frontend/src/components/governance/ApprovalQueue.tsx` | CREATE | Pending approvals list |
| `frontend/src/components/governance/ApprovalCard.tsx` | CREATE | Approve/reject UI |

---

## Testing

```bash
# Run all tests
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q

# Run governance-specific tests
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ -k governance --no-header -q

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
