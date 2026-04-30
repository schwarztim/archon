# WS-8 Cross-Cutting Features — Completion Report

> Date: February 26, 2026  
> Workstream: WS-8 (Cross-Cutting: CI/CD, Docs, Mail, Teams)  
> Status: **COMPLETE**

---

## Summary

WS-8 implemented real SMTP email sending, Microsoft Teams webhook notifications, CI/CD pipeline updates for the MCP Gateway, and documentation updates.

---

## 1. Real SMTP Sending — ✅ COMPLETE

### Changes
- **`backend/requirements.txt`**: Added `aiosmtplib>=3.0.0`
- **`backend/app/config.py`**: Added SMTP config fields:
  ```python
  SMTP_HOST: str = ""
  SMTP_PORT: int = 587
  SMTP_FROM: str = ""
  SMTP_USERNAME: str = ""
  SMTP_PASSWORD: str = ""
  ```
- **`backend/app/routes/settings.py`**: Replaced stub with real implementation:
  - Added `_send_email()` async helper using `aiosmtplib.send()` with STARTTLS
  - Reads SMTP config from tenant's notification settings
  - Raises HTTP 502 with error detail on SMTP failure (never swallows exceptions)
  - Treats `"********"` masked password as absent (consistent with masking in GET response)

### Configuration
Set via environment variables (`ARCHON_SMTP_*`) or via `PUT /api/v1/settings`:
```json
{
  "notifications": {
    "smtp_host": "smtp.sendgrid.net",
    "smtp_port": 587,
    "smtp_from": "archon@yourdomain.com",
    "smtp_username": "apikey",
    "smtp_password": "<key>"
  }
}
```

---

## 2. Microsoft Teams Integration — ✅ COMPLETE

### Changes
- **`backend/app/config.py`**: Added `TEAMS_WEBHOOK_URL: str = ""`
- **`backend/app/routes/settings.py`**:
  - Added `_send_teams_notification()` async helper using `httpx.AsyncClient`
  - Posts MS Teams `MessageCard` format payload to Incoming Webhook URL
  - Wired into `POST /api/v1/settings/notifications/test` for `channel="teams"`
  - Updated `NotificationTestRequest.channel` description to include `"teams"`
  - Added `teams_webhook_url: ""` to default notifications settings seed
- `httpx` was already present in `requirements.txt` (≥0.28.0) — no new dependency needed

### Configuration
```
ARCHON_TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/...
```
Or via Settings UI / API under `notifications.teams_webhook_url`.

### Test
```bash
POST /api/v1/settings/notifications/test
{ "channel": "teams" }
```

---

## 3. Multi-Tenancy Review — ✅ VERIFIED

### Tenant Extraction
**`backend/app/middleware/tenant.py`** (`TenantMiddleware` + `get_tenant_context`):
- Tenant ID is extracted from the authenticated JWT (`user.tenant_id` claim)
- `get_tenant_context()` FastAPI dependency raises HTTP 403 if `tenant_id` is missing
- `TenantFilter` helper provides a reusable SQLAlchemy clause: `model.tenant_id == tenant_id`

### Services — Tenant Isolation Status

| Service | Filter Method | Status |
|---------|--------------|--------|
| `agent_service.py` | JOIN User WHERE `User.tenant_id == tenant_id` | ✅ Isolated |
| `execution_service.py` | JOIN Agent→User WHERE `User.tenant_id == tenant_id` | ✅ Isolated |
| `router_service.py` | In-memory filter on `config["tenant_id"]` + DB WHERE | ✅ Isolated |
| `tenant_service.py` | Direct `Tenant.id` lookup + quota WHERE `tenant_id` | ✅ Isolated |
| `tenancy.py` | `BillingRecord.tenant_id == tenant_id` | ✅ Isolated |
| `secret_access_logger.py` | `SecretAccessLog.tenant_id == UUID(tenant_id)` | ✅ Isolated |
| `settings.py` (route) | `_settings_store[tenant_id]` (in-memory, keyed by tenant) | ✅ Isolated |
| `sandbox_service.py` | Paginated list filtered by `tenant_id` | ✅ Isolated |
| `docforge_service.py` | Permission-filtered by tenant | ✅ Isolated |
| `template_service.py` | Filtered by tenant scope | ✅ Isolated |

### Notes
- Settings, feature flags, and API key data use in-memory stores keyed by `tenant_id` — correct for the current implementation but **not durable across restarts**. Production upgrade path: migrate to a `PlatformSettings` database table with `tenant_id` column.
- `sentinelscan_service.py` has TODO comments noting production implementations should filter by `tenant_id` — currently returns stub data, tenant isolation is documented as pending.
- The `AuditLog` model does not have a `tenant_id` column directly; audit entries are scoped by `actor_id` → `user.tenant_id`. This is functionally correct but makes cross-tenant audit queries slower. Recommend adding `tenant_id` to `AuditLog` in a future migration.

---

## 4. CI Pipeline Updates — ✅ COMPLETE

### `.github/workflows/ci.yml`
Added:
- **`lint` job**: Now runs `ruff check gateway/` in addition to `ruff check backend/`
- **`test-gateway` job** (new): Installs gateway deps, runs `tests/gateway/` if it exists (graceful skip otherwise)
- **`build` job**: Now builds `archon-gateway:ci` Docker image in addition to backend and frontend
- **`security-scan` job**: Now scans `gateway/requirements.txt` in addition to backend

### `.github/workflows/cd.yml`
Added:
- **gateway image build+push** step: Builds `./gateway` context and pushes `ghcr.io/<repo>/gateway:latest` and `gateway:<sha>`

---

## 5. Documentation Updates — ✅ COMPLETE

### `docs/ARCHITECTURE.md`
Added **Section 3.8: MCP Host Gateway** documenting:
- Technology stack (FastAPI + Python 3.12 + Plugin Registry)
- Component table (Plugin Registry, Loader, Plugins API, Health Probe, Docs)
- Plugin YAML schema example
- Deployment notes

### `docs/DEPLOYMENT_GUIDE.md` (new)
Created comprehensive deployment guide covering:
- Local development (Docker Compose)
- Kubernetes (Helm + Vault)
- Azure Container Apps (recommended cloud path)
- CI/CD secrets and workflows
- SMTP and Teams configuration
- Health endpoints
- Troubleshooting

---

## 6. OpenAPI Docs Verification — ✅ VERIFIED

**`backend/app/main.py`** analysis:
- `FastAPI(...)` is instantiated without `docs_url=None` or `openapi_url=None`, so Swagger UI is available at **`GET /docs`** and OpenAPI JSON at **`GET /openapi.json`** by default.
- **39 routers** are registered, covering all phases (1–6), DocForge, SSO/SCIM, auth, settings, metrics.
- The settings router (`prefix="/api/v1"` + router `prefix="/settings"`) contributes to OpenAPI at `/api/v1/settings/*` — all 8 routes including the new Teams notification test.
- The gateway (`gateway/app/main.py`) also has `docs_url="/docs"` explicitly set, exposing its own Swagger UI.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/requirements.txt` | Added `aiosmtplib>=3.0.0` |
| `backend/app/config.py` | Added SMTP_HOST/PORT/FROM/USERNAME/PASSWORD + TEAMS_WEBHOOK_URL |
| `backend/app/routes/settings.py` | Real SMTP + Slack + Teams implementation; updated schemas |
| `.github/workflows/ci.yml` | Gateway lint, gateway test, gateway Docker build |
| `.github/workflows/cd.yml` | Gateway Docker image build+push |
| `docs/ARCHITECTURE.md` | Added Section 3.8: MCP Host Gateway |
| `docs/DEPLOYMENT_GUIDE.md` | New — full deployment guide |
| `docs/WS8_CROSSCUTTING_REPORT.md` | This file |
