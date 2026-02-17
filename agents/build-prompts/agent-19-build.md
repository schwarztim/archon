# Agent 19 — Settings Platform — Build Prompt

> Hand this file to a coding agent. It contains everything needed to build this component.

## Context
You are building the **Settings Platform** for Archon — platform configuration including system health, API info, SSO setup, feature flags, and admin controls.
Project root: `~/Scripts/Archon/`

## What Already Exists (do NOT rebuild these)
- `frontend/src/pages/SettingsPage.tsx` (451 lines) — System info card, user info card, quick links. Currently calls /api/v1/health which returns 404. EXTEND with tabs.
- `backend/app/routes/` — Main app exists but health is at /health, not /api/v1/health.

## What to Build

### 1. Fix Health Endpoint
Add `/api/v1/health` route alias that returns:
```json
{"status": "healthy", "version": "1.0.0", "services": {"api": "up", "database": "up", "redis": "up", "vault": "connected|stub|sealed", "keycloak": "up|down"}, "timestamp": "ISO8601"}
```

### 2. Settings Page Redesign with Tabs
Reorganize into tabbed layout (use shadcn Tabs component):

**General Tab**: Platform name (editable), Logo upload, Default language dropdown, Timezone dropdown

**Authentication Tab**:
- SSO Configuration section (embed Agent 16's SSO component or link to SSO page)
- Session timeout (slider: 15min-24h)
- Password policy: min length (slider), require uppercase/number/special (toggles)
- MFA enforcement toggle

**API & Integrations Tab**:
- API keys for external access: list of API keys with create/revoke
- Webhook endpoints: URL + events to send
- Rate limits: requests per minute (number input)

**Notifications Tab**:
- Email SMTP config: Host, Port, Username, Password (Vault), From address, TLS toggle
- Slack webhook URL for alerts
- Notification preferences: checkboxes for which events trigger notifications

**Feature Flags Tab** (admin only):
- Toggle switches for experimental features
- Show feature name, description, status (enabled/disabled), affected scope

**System Health Tab**:
- Service status cards: API (green/red), Database (green/red), Redis (green/red), Vault (green/yellow/red with mode), Keycloak (green/red)
- Version info, uptime, last restart
- Resource usage: memory, CPU (if available)

**Appearance Tab**:
- Theme selector: Light/Dark/System Auto
- Accent color picker
- Compact mode toggle

### 3. Permission Gating
- Feature Flags and System Health tabs only visible to admin users
- Use `usePermission()` hook or check user role

## Patterns to Follow (from OSS)

### Pattern 1: Dify Account Settings (dify/web/app/components/header/account-setting/)
Dify organizes settings into sidebar sections: Account, Members, Integrations, Model Providers, Data Sources, Plugin, API Extensions, Custom. Each section is a separate component rendered in the right panel. Adaptation: Use horizontal tabs instead of sidebar (more compact). Combine related settings.

### Pattern 2: Coze Studio Settings
Coze has workspace-level settings with API key management, model configuration, and team settings. Adaptation: Same pattern — settings organized by concern with clear sections.

## Backend Deliverables

| Endpoint | Method | Description |
|---|---|---|
| `GET /api/v1/health` | GET | Health check with all service statuses |
| `GET /api/v1/settings` | GET | Get platform settings |
| `PUT /api/v1/settings` | PUT | Update platform settings |
| `GET /api/v1/settings/feature-flags` | GET | List feature flags |
| `PUT /api/v1/settings/feature-flags/{flag}` | PUT | Toggle feature flag |
| `POST /api/v1/settings/api-keys` | POST | Create API key |
| `DELETE /api/v1/settings/api-keys/{id}` | DELETE | Revoke API key |
| `POST /api/v1/settings/notifications/test` | POST | Send test notification |

## Frontend Deliverables

| Component | Action | Description |
|---|---|---|
| `pages/SettingsPage.tsx` | MODIFY | Tabbed layout with all sections |
| `components/settings/GeneralTab.tsx` | CREATE | Platform name, logo, timezone |
| `components/settings/AuthTab.tsx` | CREATE | SSO link, session, password, MFA |
| `components/settings/APITab.tsx` | CREATE | API keys, webhooks, rate limits |
| `components/settings/NotificationsTab.tsx` | CREATE | SMTP, Slack, preferences |
| `components/settings/FeatureFlagsTab.tsx` | CREATE | Toggle switches (admin only) |
| `components/settings/SystemHealthTab.tsx` | CREATE | Service status cards |
| `components/settings/AppearanceTab.tsx` | CREATE | Theme, accent, compact |

## Integration Points
- **Agent 01 (Backend)**: Health endpoint fix (may overlap — coordinate)
- **Agent 16 (SSO)**: SSO config component embedded or linked from Auth tab
- **Agent 17 (Secrets)**: Vault status shown in System Health
- **Agent 18 (Audit)**: Settings changes logged to audit trail

## Acceptance Criteria
1. Settings page loads without "Failed to reach API" error (health endpoint works)
2. Settings organized in clear tabs (General, Auth, API, Notifications, Flags, Health, Appearance)
3. System Health shows status of all services (API, DB, Redis, Vault, Keycloak)
4. SSO configuration accessible from Settings → Authentication tab
5. Feature Flags tab only visible to admin users
6. Theme switcher works (light/dark/auto)
7. SMTP password stored in Vault, not in settings DB

## Files to Read Before Starting
- `~/Scripts/Archon/agents/AGENT_RULES.md`
- `~/Scripts/Archon/frontend/src/pages/SettingsPage.tsx`

## Files to Create/Modify

| Path | Action |
|---|---|
| `frontend/src/pages/SettingsPage.tsx` | MODIFY |
| `frontend/src/components/settings/GeneralTab.tsx` | CREATE |
| `frontend/src/components/settings/AuthTab.tsx` | CREATE |
| `frontend/src/components/settings/APITab.tsx` | CREATE |
| `frontend/src/components/settings/NotificationsTab.tsx` | CREATE |
| `frontend/src/components/settings/FeatureFlagsTab.tsx` | CREATE |
| `frontend/src/components/settings/SystemHealthTab.tsx` | CREATE |
| `frontend/src/components/settings/AppearanceTab.tsx` | CREATE |
| `backend/app/routes/settings.py` | CREATE |

## Testing
```bash
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q
curl http://localhost:8000/api/v1/health
# Should return {"status":"healthy","services":{...}}
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
