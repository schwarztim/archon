# Agent 17 — Secrets Vault — Build Prompt

> Hand this file to a coding agent. It contains everything needed to build this component.

## Context
You are building the **Secrets Vault** management UI and enhancements for Archon, an enterprise AI orchestration platform. Secrets are stored in HashiCorp Vault. A VaultSecretsManager class already exists.
Project root: `~/Scripts/Archon/`

## What Already Exists (do NOT rebuild these)
- `frontend/src/pages/SecretsPage.tsx` (449 lines) — Create Secret modal (Name, Path, Type), list view. EXTEND with rotation, access log, type badges, Vault status.
- `backend/app/routes/secrets.py` (306 lines) — Vault-backed CRUD routes. EXTEND with rotation, access log.
- `backend/app/secrets/manager.py` — VaultSecretsManager with get/put/delete/list. Has _StubSecretsManager fallback. EXTEND with rotation and access tracking.
- `backend/app/secrets/config.py` — SecretsConfig with Vault connection settings. KEEP.
- `backend/app/secrets/rotation.py` — Rotation module. EXTEND.
- `backend/app/models/secrets.py` (34 lines) — Minimal secret models. EXTEND.

## What to Build

### 1. Secrets List Enhancement
- Show columns: Name, Path, Type (badge: API Key/OAuth Token/Password/Certificate/Custom), Last Rotated (relative time), Expiry Status (approaching/expired/ok with color), Actions (View/Rotate/Delete)
- Type badges: color-coded by type (blue=API Key, green=OAuth, orange=Password, purple=Certificate)
- "Reveal" button (admin only) → shows masked value with only last 4 chars → click again for full reveal (with confirmation modal + audit log entry)

### 2. Path-Based Access Tree
- Visual tree view showing Vault path structure: `archon/{tenant}/providers/`, `archon/{tenant}/connectors/`, `archon/{tenant}/sso/`, etc.
- Expandable tree nodes showing secrets at each path level
- Breadcrumb navigation

### 3. Rotation Management
- Manual "Rotate" button per secret → generates new value (for auto-generated) or prompts for new value → stores in Vault → logs rotation event
- Auto-rotation policies: configurable per secret — rotation period (30/60/90 days), notification before expiry (7/14/30 days)
- Rotation status dashboard: secrets approaching rotation (yellow), overdue (red), recently rotated (green), never rotated (gray)

### 4. Vault Status Banner
- Show Vault connection status: Connected (green), Stub Mode (yellow warning), Sealed (red), Disconnected (red)
- In Settings page: embed Vault status indicator
- Stub mode: show clear warning banner "Running in stub mode — secrets are NOT persisted. Configure Vault for production use."

### 5. Access Log
- Per-secret access log: who accessed (user), when, what action (read/write/rotate/delete), from which component (provider setup, connector setup, etc.)
- Backend: log every SecretsManager.get() call with actor context

### 6. Universal Vault API
Ensure all components that store secrets (providers from Agent 08, connectors from Agent 09, SSO from Agent 16) use the same Vault API pattern:
- PUT /api/v1/secrets/{path} — store secret
- GET /api/v1/secrets/{path}/metadata — get metadata (never the value directly via API)
- POST /api/v1/secrets/{path}/rotate — rotate

## Patterns to Follow (from OSS)

### Pattern 1: Dify Provider Key Storage (dify/api/core/model_runtime/model_providers/, dify/api/models/provider.py)
Dify stores provider API keys in an encrypted_config column on the Provider model. Keys are encrypted/decrypted with a server-side key. The frontend sends keys, backend encrypts and stores. For display, backend returns masked values (only last 4 chars). Archon adaptation: Instead of encrypted DB column, store in Vault. Backend stores only the Vault path reference. Display pattern is the same (masked with last 4 chars). Add rotation capability that Dify lacks.

### Pattern 2: Original Design — Rotation and Access Logging
No OSS platform has secret rotation management in-app. Designed from enterprise secret management best practices (CyberArk, Thales). Pattern: Each secret has metadata including rotation_policy, last_rotated, expires_at. A scheduled job checks for secrets approaching rotation and emits notifications. Access is logged via middleware that wraps SecretsManager calls.

## Backend Deliverables

| Endpoint | Method | Description |
|---|---|---|
| `GET /api/v1/secrets/` | GET | Enhanced: return type badges, rotation status, expiry |
| `POST /api/v1/secrets/{path}/rotate` | POST | Rotate secret (generate new or accept new value) |
| `GET /api/v1/secrets/{path}/access-log` | GET | Access history for a secret |
| `GET /api/v1/secrets/status` | GET | Vault connection status |
| `PUT /api/v1/secrets/{path}/rotation-policy` | PUT | Set auto-rotation policy |
| `GET /api/v1/secrets/rotation-dashboard` | GET | Secrets grouped by rotation status |

New/modified files:
- `backend/app/routes/secrets.py` — MODIFY — Add rotation, access log, status endpoints
- `backend/app/services/secret_access_logger.py` — CREATE — Decorator/middleware for logging secret access
- `backend/app/models/secrets.py` — MODIFY — Add rotation_policy, last_rotated, expires_at, access_log models

## Frontend Deliverables

| Component | Action | Description |
|---|---|---|
| `pages/SecretsPage.tsx` | MODIFY | Type badges, rotation status, access log tab |
| `components/secrets/SecretsList.tsx` | CREATE | Enhanced list with type/rotation columns |
| `components/secrets/PathTree.tsx` | CREATE | Vault path tree navigation |
| `components/secrets/RotationDashboard.tsx` | CREATE | Grouped rotation status view |
| `components/secrets/AccessLog.tsx` | CREATE | Per-secret access history |
| `components/secrets/VaultStatusBanner.tsx` | CREATE | Connection status banner |
| `components/secrets/RotationPolicyForm.tsx` | CREATE | Auto-rotation config form |

## Integration Points
- **Agent 08 (Router)**: Provider API keys stored at `archon/{tenant}/providers/{id}/api_key`
- **Agent 09 (Connectors)**: Connector credentials at `archon/{tenant}/connectors/{id}/`
- **Agent 16 (SSO)**: SSO secrets at `archon/{tenant}/sso/{idp_id}/`
- **Agent 19 (Settings)**: Vault status banner embedded in Settings System Health tab

## Acceptance Criteria
1. Secrets list shows type badges (colored by type) and rotation status
2. "Rotate" button rotates a secret and logs the rotation event
3. Auto-rotation policy configurable per secret (30/60/90 day periods)
4. Vault status visible (Connected/Stub/Sealed) with appropriate warnings
5. Stub mode shows clear warning banner
6. Access log shows who accessed which secret and when
7. Path tree navigation shows Vault structure
8. "Reveal" button requires admin role and creates audit log entry

## Files to Read Before Starting
- `~/Scripts/Archon/agents/AGENT_RULES.md` (mandatory coding standards)
- `~/Scripts/Archon/backend/app/secrets/manager.py` (existing Vault manager)
- `~/Scripts/Archon/frontend/src/pages/SecretsPage.tsx` (existing UI)

## Files to Create/Modify

| Path | Action |
|---|---|
| `backend/app/routes/secrets.py` | MODIFY |
| `backend/app/models/secrets.py` | MODIFY |
| `backend/app/services/secret_access_logger.py` | CREATE |
| `frontend/src/pages/SecretsPage.tsx` | MODIFY |
| `frontend/src/components/secrets/SecretsList.tsx` | CREATE |
| `frontend/src/components/secrets/PathTree.tsx` | CREATE |
| `frontend/src/components/secrets/RotationDashboard.tsx` | CREATE |
| `frontend/src/components/secrets/AccessLog.tsx` | CREATE |
| `frontend/src/components/secrets/VaultStatusBanner.tsx` | CREATE |
| `frontend/src/components/secrets/RotationPolicyForm.tsx` | CREATE |

## Testing
```bash
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q
curl http://localhost:8000/api/v1/secrets/status -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/api/v1/secrets/test-secret/rotate -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/v1/secrets/test-secret/access-log -H "Authorization: Bearer $TOKEN"
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
