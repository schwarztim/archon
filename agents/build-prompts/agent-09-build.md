# Agent 09 — Connectors Onboarding — Build Prompt

## Context

Rich connector management with type-specific wizards, OAuth flows, and one-click onboarding. Replace the bare JSON config form with a visual connector catalog, per-type setup wizards, OAuth popup flows, connection testing, and health monitoring.

**Tech stack — Backend:** Python 3.12, FastAPI, SQLModel, Alembic, AsyncSession. **Frontend:** React 19, TypeScript strict, shadcn/ui, Tailwind CSS, React Flow. **Auth:** JWT + Keycloak. **Secrets:** HashiCorp Vault via `backend/app/secrets/manager.py`.

---

## What Already Exists

| File | Lines | Action |
|------|-------|--------|
| `frontend/src/pages/ConnectorsPage.tsx` | 186 | **REDESIGN** — Bare form: Name, Type dropdown, raw JSON Config field. |
| `frontend/src/api/connectors.ts` | 57 | **EXTEND** — Basic API client. |
| `backend/app/routes/connectors.py` | 382 | **EXTEND** — Connector CRUD. Add OAuth, test, health endpoints. |
| `backend/app/services/connector_service.py` | 541 | **EXTEND** — Connector service. |
| `backend/app/models/connector.py` | 143 | **KEEP** — Model: id, name, type, config(JSON), status, owner_id. Enhance routes, not model. |

---

## What to Build

### 1. Connector Catalog

Replace the bare form with a visual grid of connector type cards (35+ types).

**Categories:**

| Category | Types |
|----------|-------|
| Databases | PostgreSQL, MySQL, MongoDB, Redis, Elasticsearch, Snowflake, BigQuery |
| SaaS | Salesforce, HubSpot, Zendesk, Jira, Confluence, Notion |
| Communication | Slack, Teams, Discord, Email/SMTP |
| Cloud | AWS S3, Azure Blob, GCP Storage, GitHub, GitLab |
| AI | OpenAI, Anthropic, Ollama, HuggingFace |
| Custom | Webhook, REST API, GraphQL |

Each card displays: icon, name, category badge, "Connect" button.

### 2. Type-Specific Forms

Click a connector card → opens a type-specific setup form (not raw JSON):

- **PostgreSQL:** Host, Port, Database, Username, Password (stored in Vault), SSL mode dropdown.
- **Salesforce:** "Connect with Salesforce" OAuth button → OAuth popup → callback → tokens in Vault.
- **Slack:** "Add to Slack" OAuth button → Bot Token stored in Vault → Channel selector.
- **S3:** Region dropdown, Bucket, Access Key (Vault), Secret Key (Vault).
- **Generic REST:** Base URL, Auth type (None / API Key / Bearer / Basic / OAuth2), credential fields.

### 3. OAuth Flow

Backend endpoints for OAuth connectors:

- `GET /connectors/oauth/{type}/authorize` → returns redirect URL.
- `GET /connectors/oauth/{type}/callback` → exchanges code → stores tokens in Vault.

Supported providers: Salesforce, Slack, GitHub, Google, Microsoft 365.

### 4. Test Connection

"Test" button per connector → `POST /connectors/{id}/test` → validates credentials and connectivity → returns success with details or failure with diagnostic message.

### 5. Health Monitoring

Periodic health checks on connected connectors. Status badges: green = healthy, yellow = degraded, red = error. Show last check time.

---

## Patterns to Follow

### Pattern 1 — Dify Tool Integration

**Source:** `dify/web/app/components/tools/`, `dify/api/core/tools/`

Dify has a tool provider system where each provider has credential requirements, a setup form, and available tools. Tools are registered via YAML manifests with parameter schemas. OAuth tools have authorize/callback endpoints.

**Adaptation:** Same provider-based pattern. Each connector type registers its credential schema (drives form fields) and connection test logic. Store all credentials in Vault instead of Dify's encrypted DB. Return connector type metadata from `GET /connectors/types` including field schemas.

### Pattern 2 — Dify OAuth Flow

**Source:** `dify/api/core/tools/provider/`

Dify handles OAuth by redirecting to provider, receiving callback with code, exchanging for tokens, and storing encrypted.

**Adaptation:** Same OAuth flow but tokens go to Vault at path `archon/connectors/{id}/oauth_tokens`. The frontend opens an OAuth popup (not a redirect) and listens for a postMessage callback.

### Pattern 3 — Flowise Credential Management

Flowise has a credentials page where users add API keys for various services. Each credential type has its own form fields defined in a schema.

**Adaptation:** Connector setup IS credential setup — type-specific forms generated from schemas returned by the backend. No raw JSON on any form.

---

## Backend Deliverables

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/connectors` | Enhanced: store credentials in Vault, save `vault_path` in config JSON. |
| POST | `/api/v1/connectors/{id}/test` | Test connection: validate credentials and connectivity. |
| GET | `/api/v1/connectors/oauth/{type}/authorize` | Return OAuth redirect URL for provider. |
| GET | `/api/v1/connectors/oauth/{type}/callback` | Exchange OAuth code, store tokens in Vault. |
| GET | `/api/v1/connectors/{id}/health` | Health check for a connected connector. |
| GET | `/api/v1/connectors/types` | List available connector types with credential schemas. |

All endpoints:
- JWT-authenticated, scoped to `tenant_id`.
- Return envelope: `{"data": ..., "meta": {"request_id": "...", "timestamp": "..."}}`.
- Mutations produce `AuditLog` entries.
- Credentials read/written via `SecretsManager`, never stored in DB or returned in API responses.

---

## Frontend Deliverables

| File | Action |
|------|--------|
| `pages/ConnectorsPage.tsx` | **MODIFY** — Catalog grid with type-specific forms. |
| `components/connectors/ConnectorCatalog.tsx` | **CREATE** — Grid of connector type cards with category filtering. |
| `components/connectors/ConnectorCard.tsx` | **CREATE** — Type card with icon, name, category badge, "Connect" button. |
| `components/connectors/forms/PostgreSQLForm.tsx` | **CREATE** — Host/Port/Database/Username/Password/SSL fields. |
| `components/connectors/forms/SalesforceForm.tsx` | **CREATE** — OAuth "Connect with Salesforce" button. |
| `components/connectors/forms/SlackForm.tsx` | **CREATE** — OAuth "Add to Slack" button + channel selector. |
| `components/connectors/forms/S3Form.tsx` | **CREATE** — Region/Bucket/Access Key/Secret Key fields. |
| `components/connectors/forms/GenericRESTForm.tsx` | **CREATE** — Base URL, auth type selector, credential fields. |
| `components/connectors/TestConnectionButton.tsx` | **CREATE** — Test button with loading/success/failure states. |
| `components/connectors/HealthBadge.tsx` | **CREATE** — Green/yellow/red status badge with last check time. |
| `api/connectors.ts` | **MODIFY** — Add OAuth, test, health, types API calls. |

All components: dark/light mode via Tailwind `dark:` variants.

---

## Integration Points

- **SecretsManager** (`backend/app/secrets/manager.py`): Store/retrieve all connector credentials. Vault paths: `archon/connectors/{connector_id}/{credential_key}`.
- **AuditLog**: Log connector create, update, delete, OAuth connect, test, health check.
- **Execution Engine**: Connectors used by agents during execution must resolve credentials from Vault at runtime.
- **DLP (Agent 12)**: Connector credentials must never appear in execution logs; DLP should redact if leaked.

---

## Acceptance Criteria

1. Connector page shows visual catalog grid, not bare form.
2. Click connector type → type-specific form (not raw JSON).
3. OAuth connectors have "Connect" button with OAuth popup flow.
4. PostgreSQL form has Host / Port / Database / Username / Password fields.
5. "Test Connection" validates and shows success / failure with diagnostics.
6. Connected connectors show health status badges (green/yellow/red).
7. Credentials stored in Vault, never in DB or API responses.
8. At least 10 connector types have rich forms.

---

## Files to Read

Read these files before writing any code to understand existing patterns:

```
backend/app/routes/connectors.py
backend/app/services/connector_service.py
backend/app/models/connector.py
backend/app/secrets/manager.py
frontend/src/pages/ConnectorsPage.tsx
frontend/src/api/connectors.ts
frontend/src/components/ui/          # shadcn/ui primitives
```

---

## Files to Create / Modify

### Backend

```
backend/app/routes/connectors.py                          # MODIFY — add OAuth, test, health, types endpoints
backend/app/services/connector_service.py                 # MODIFY — add OAuth, test, health logic
backend/app/services/connectors/__init__.py                # CREATE — connector type registry
backend/app/services/connectors/schemas.py                 # CREATE — credential schemas per type
backend/app/services/connectors/oauth.py                   # CREATE — OAuth flow logic
backend/app/services/connectors/testers.py                 # CREATE — connection test implementations
backend/app/services/connectors/health.py                  # CREATE — health check implementations
tests/test_connectors.py                                   # CREATE — endpoint + service tests
tests/test_connectors_oauth.py                             # CREATE — OAuth flow tests
```

### Frontend

```
frontend/src/pages/ConnectorsPage.tsx                      # MODIFY
frontend/src/components/connectors/ConnectorCatalog.tsx    # CREATE
frontend/src/components/connectors/ConnectorCard.tsx       # CREATE
frontend/src/components/connectors/forms/PostgreSQLForm.tsx # CREATE
frontend/src/components/connectors/forms/SalesforceForm.tsx # CREATE
frontend/src/components/connectors/forms/SlackForm.tsx     # CREATE
frontend/src/components/connectors/forms/S3Form.tsx        # CREATE
frontend/src/components/connectors/forms/GenericRESTForm.tsx # CREATE
frontend/src/components/connectors/TestConnectionButton.tsx # CREATE
frontend/src/components/connectors/HealthBadge.tsx         # CREATE
frontend/src/api/connectors.ts                             # MODIFY
```

---

## Testing

```bash
# Backend — run from repo root
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/test_connectors.py tests/test_connectors_oauth.py --no-header -q

# Minimum coverage
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/test_connectors.py --cov=backend/app/routes/connectors --cov=backend/app/services/connector_service --cov-fail-under=80 --no-header -q
```

Test cases must include:
- List connector types returns ≥ 10 types with schemas.
- Create connector stores credentials in Vault (mock SecretsManager).
- Test connection returns success for valid config, failure for invalid.
- OAuth authorize returns redirect URL.
- OAuth callback stores tokens in Vault.
- Health check returns status.
- API responses use envelope format.
- Endpoints reject unauthenticated requests (401).
- Queries scoped to `tenant_id`.

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
