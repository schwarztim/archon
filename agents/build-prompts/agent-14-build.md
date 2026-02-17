# Agent 14 — SentinelScan — Build Prompt

## Context

You are building the **SentinelScan** module for the Archon AI orchestration platform. This module provides shadow AI discovery (finding unauthorized AI service usage), security posture assessment with a weighted scoring model, service inventory management, and remediation workflows.

**Stack:** Backend: Python 3.12, FastAPI, SQLModel, Alembic, AsyncSession. Frontend: React 19, TypeScript strict, shadcn/ui, Tailwind, React Flow. Auth: JWT via Keycloak. Secrets: HashiCorp Vault via `backend/app/secrets/manager.py`.

---

## What Already Exists

| File | Lines | Status |
|------|-------|--------|
| `frontend/src/pages/SentinelScanPage.tsx` | 365 | Posture gauge (shows 100 but 0 services), risk bars all 0, discovery form (Scan Name/Target/Type), empty services table. **EXTEND with real data.** |
| `frontend/src/api/sentinelscan.ts` | 58 | API client. **EXTEND.** |
| `backend/app/routes/sentinelscan.py` | 524 | SentinelScan routes. **EXTEND.** |
| `backend/app/services/sentinelscan_service.py` | 605 | SentinelScan service. **EXTEND.** |
| `backend/app/models/sentinelscan.py` | 240 | SentinelScan models. **KEEP.** |

---

## What to Build

### 1. Discovery Engine Enhancement

The scan must actually discover AI services by checking multiple data sources:

- **IdP/SSO Logs:** Check configured identity provider logs for authentication events to known AI service domains (`openai.com`, `anthropic.com`, `cohere.ai`, `huggingface.co`, `replicate.com`, `stability.ai`, `midjourney.com`, etc.)
- **API Gateway Logs:** Scan API gateway/proxy logs for outbound calls to AI API endpoints (`api.openai.com/v1/*`, `api.anthropic.com/v1/*`, etc.)
- **DNS Records:** Check DNS query logs for known AI service endpoints
- **For demo/dev mode:** Generate realistic sample findings when no real data sources are configured. Findings should vary across scans (randomized but plausible).

Each discovered service produces a `Finding` record with: service_name, service_type, risk_level, users_count, data_exposure, first_seen, last_seen, source (how it was discovered).

### 2. Service Inventory

Populated table with the following columns:

| Column | Description |
|--------|-------------|
| Service Name | e.g., "OpenAI ChatGPT", "Anthropic Claude" |
| Type | LLM / Embedding / Image / Voice / Code |
| Risk Level | Badge: `Critical` (red), `High` (orange), `Medium` (yellow), `Low` (green) |
| Users Count | Number of distinct users accessing this service |
| Data Exposure | `Sensitive` (red) / `Internal` (yellow) / `None` (green) |
| First Seen | Date first detected |
| Last Seen | Date last detected |
| Status | `Approved` (green) / `Unapproved` (yellow) / `Blocked` (red) |

Click row → detail side panel with:
- Full service info
- List of users who accessed it
- Data types potentially exposed
- Recommended remediation actions

### 3. Posture Score

Weighted calculation:

```
penalty = (unauthorized_services × 10) + (critical_risks × 20)
        + (data_exposure_incidents × 15) + (policy_violations × 5)
score = max(0, 100 - penalty)
```

**Color coding:**
- 🟢 Green: 80–100
- 🟡 Yellow: 60–79
- 🔴 Red: 0–59

Gauge component renders as a semi-circular arc with the score number in the center and color fill matching the range.

### 4. Risk Breakdown

Category bars showing real counts (not zeros):

| Category | Example Count | Description |
|----------|--------------|-------------|
| Data Exposure | 3 | Sensitive data sent to AI services |
| Unauthorized Access | 7 | Users accessing unapproved AI services |
| Credential Risk | 2 | API keys or credentials exposed in AI prompts |
| Policy Violation | 4 | Usage violating organizational policies |

Each bar is **clickable** — clicking a category opens a filtered view showing all findings in that category.

### 5. Remediation

Per finding, provide a remediation workflow:

- **Suggested action dropdown:** Block, Approve, Monitor, Ignore
- **"Apply" button** executes the selected action:
  - `Block` → Marks service as blocked, creates policy rule
  - `Approve` → Marks service as approved, removes from risk count
  - `Monitor` → Adds to watch list, increases scan frequency
  - `Ignore` → Dismisses finding with reason
- **Bulk remediation:** Select multiple findings → apply same action to all
- All remediation actions produce `AuditLog` entries

### 6. Scan History

Table of past scans:

| Column | Description |
|--------|-------------|
| Date | Scan execution timestamp |
| Scan Name | User-provided name |
| Target | What was scanned |
| Findings Count | Number of findings |
| New Findings | Findings not seen in previous scan |
| Status | Completed / Failed / Running |
| Actions | Re-run / View Results |

---

## Patterns to Follow

### Pattern 1: Original Design — Multi-Source Discovery

No OSS reference for shadow AI discovery. Designed from enterprise security assessment principles.

**Pattern:** Discovery agents scan multiple data sources (SSO logs, DNS, API gateway) and correlate findings into a unified risk model. Each finding has:

```python
class Finding:
    service_name: str
    service_type: ServiceType  # LLM, Embedding, Image, Voice, Code
    risk_level: RiskLevel      # Critical, High, Medium, Low
    risk_score: int            # 0-100
    category: RiskCategory     # DataExposure, UnauthorizedAccess, CredentialRisk, PolicyViolation
    remediation_options: list[RemediationAction]
    source: DiscoverySource    # SSO, DNS, APIGateway, Manual
```

Findings are deduplicated by `(service_name, tenant_id)`. New findings on subsequent scans are flagged as `is_new=True`.

### Pattern 2: Idun Agent Platform Guardrails

Idun provides guardrail patterns for AI service control.

**Adaptation:** Combine discovery (find unauthorized AI usage) with guardrails (enforce policies on discovered services). When a service is marked `Blocked`, generate a guardrail rule that can be enforced at the network/proxy level. The remediation action produces both a status change and a policy artifact.

---

## Backend Deliverables

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/sentinelscan/scan` | Run discovery scan (accepts scan_name, target, scan_type) |
| `GET` | `/api/v1/sentinelscan/scan/{scan_id}` | Get scan status and results |
| `GET` | `/api/v1/sentinelscan/services` | Discovered services list (paginated, filterable) |
| `GET` | `/api/v1/sentinelscan/services/{id}` | Service detail with users and exposure data |
| `GET` | `/api/v1/sentinelscan/posture` | Posture score with component breakdown |
| `GET` | `/api/v1/sentinelscan/risks` | Risk category breakdown with counts |
| `GET` | `/api/v1/sentinelscan/risks/{category}` | Findings in a specific risk category |
| `POST` | `/api/v1/sentinelscan/remediate/{finding_id}` | Apply remediation action (Block/Approve/Monitor/Ignore) |
| `POST` | `/api/v1/sentinelscan/remediate/bulk` | Bulk remediation for multiple findings |
| `GET` | `/api/v1/sentinelscan/history` | Scan history (paginated) |

All endpoints return envelope format: `{"data": ..., "meta": {"request_id": "...", "timestamp": "..."}}`.

All endpoints require JWT auth. All queries scoped to `tenant_id`. All mutations produce `AuditLog` entries.

---

## Frontend Deliverables

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/pages/SentinelScanPage.tsx` | **MODIFY** | Wire to real data, fix posture gauge, add remediation UI |
| `frontend/src/components/sentinelscan/PostureGauge.tsx` | **CREATE** | Semi-circular gauge with color coding (green/yellow/red) |
| `frontend/src/components/sentinelscan/RiskBars.tsx` | **CREATE** | Clickable category bars with real counts |
| `frontend/src/components/sentinelscan/ServiceTable.tsx` | **CREATE** | Rich service inventory table with row click → detail |
| `frontend/src/components/sentinelscan/ServiceDetail.tsx` | **CREATE** | Side panel with full service info and users |
| `frontend/src/components/sentinelscan/RemediationPanel.tsx` | **CREATE** | Action dropdown + apply button per finding |
| `frontend/src/components/sentinelscan/BulkRemediation.tsx` | **CREATE** | Multi-select + bulk action toolbar |
| `frontend/src/components/sentinelscan/ScanHistory.tsx` | **CREATE** | Past scans table with re-run capability |
| `frontend/src/api/sentinelscan.ts` | **MODIFY** | Add posture, risks, remediate, history endpoints |

All components must support dark/light mode via Tailwind classes.

---

## Integration Points

- **Audit Logs:** All scan executions, remediation actions, and status changes write to the shared `AuditLog` table.
- **Governance (Agent 13):** Discovered services that are AI agents managed by Archon link back to the Agent Registry.
- **DLP (if exists):** Data exposure findings may reference DLP scan results.
- **Auth:** Remediation actions gated behind `sentinelscan:remediate` permission from JWT claims.
- **Secrets:** Any configured data source credentials (API gateway tokens, SSO log access keys) stored in Vault via SecretsManager.

---

## Acceptance Criteria

1. **PASS/FAIL:** Discovery scan returns results that populate the services table with at least 3 discovered services.
2. **PASS/FAIL:** Posture score reflects actual risk data — not hardcoded to 100 when no services exist.
3. **PASS/FAIL:** Risk category bars show real counts (non-zero when findings exist), not all zeros.
4. **PASS/FAIL:** Clicking a risk bar filters and shows findings in that specific category.
5. **PASS/FAIL:** Remediation actions available per finding: Block, Approve, Monitor, Ignore — each changes finding status.
6. **PASS/FAIL:** Scan history table shows past scans with re-run capability.
7. **PASS/FAIL:** Posture gauge is color-coded: green (80–100), yellow (60–79), red (0–59).

---

## Files to Read Before Starting

- `backend/app/models/sentinelscan.py` — Understand existing models before extending
- `backend/app/routes/sentinelscan.py` — Existing route structure
- `backend/app/services/sentinelscan_service.py` — Existing business logic
- `frontend/src/pages/SentinelScanPage.tsx` — Current UI to extend
- `frontend/src/api/sentinelscan.ts` — Current API client
- `backend/app/models/audit.py` — AuditLog model for integration
- `backend/app/secrets/manager.py` — SecretsManager interface

---

## Files to Create / Modify

| File | Action | Notes |
|------|--------|-------|
| `backend/app/routes/sentinelscan.py` | MODIFY | Add posture, risks, remediate, history endpoints |
| `backend/app/services/sentinelscan_service.py` | MODIFY | Add discovery logic, posture calculation, remediation |
| `frontend/src/pages/SentinelScanPage.tsx` | MODIFY | Wire to real data, integrate new components |
| `frontend/src/api/sentinelscan.ts` | MODIFY | Add new API methods |
| `frontend/src/components/sentinelscan/PostureGauge.tsx` | CREATE | Color-coded gauge component |
| `frontend/src/components/sentinelscan/RiskBars.tsx` | CREATE | Clickable risk category bars |
| `frontend/src/components/sentinelscan/ServiceTable.tsx` | CREATE | Service inventory table |
| `frontend/src/components/sentinelscan/ServiceDetail.tsx` | CREATE | Service detail side panel |
| `frontend/src/components/sentinelscan/RemediationPanel.tsx` | CREATE | Remediation action UI |
| `frontend/src/components/sentinelscan/BulkRemediation.tsx` | CREATE | Bulk action toolbar |
| `frontend/src/components/sentinelscan/ScanHistory.tsx` | CREATE | Scan history table |

---

## Testing

```bash
# Run all tests
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q

# Run sentinelscan-specific tests
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ -k sentinelscan --no-header -q

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
