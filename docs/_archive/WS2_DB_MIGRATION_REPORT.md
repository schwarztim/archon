# WS-2 DB Migration Report

## Summary

Migrated in-memory stores to SQLModel/AsyncSession for workflows, custom RBAC roles, API keys, and secret registrations. Added a single Alembic migration (`0002_ws2_db_migration.py`) covering all new tables plus schema additions.

---

## Files Changed

### New Files

| File | Purpose |
|------|---------|
| `backend/app/models/workflow.py` | `Workflow`, `WorkflowRun`, `WorkflowRunStep`, `WorkflowSchedule` SQLModel tables |
| `backend/app/models/rbac.py` | `CustomRole` SQLModel table |
| `backend/alembic/versions/0002_ws2_db_migration.py` | Alembic migration — creates all new tables, adds `rate_limit` column |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/models/settings.py` | Added `rate_limit: int | None` field to `SettingsAPIKey` |
| `backend/app/models/__init__.py` | Added imports and `__all__` entries for all new models |
| `backend/alembic/env.py` | Added model imports so metadata is populated for Alembic autogenerate |
| `backend/app/routes/workflows.py` | Fully rewritten — replaced 4 in-memory dicts with `AsyncSession` DB calls |
| `backend/app/routes/settings.py` | API key CRUD rewritten to use `SettingsAPIKey` SQLModel; settings/flags left in-memory |
| `backend/app/routes/sso_config.py` | Custom role CRUD (GET matrix, POST/PUT/DELETE roles) rewritten to use `CustomRole` SQLModel |
| `backend/app/routes/secrets.py` | Registration helpers rewritten as async DB functions using `SecretRegistration` model; all routes updated to inject `session` |

---

## What Each Change Does

### `workflow.py` — New tables
- **`workflows`** — Stores workflow definitions (name, description, group_id, steps/graph as JSON, schedule, active flag, creator, tenant).
- **`workflow_runs`** — Tracks each execution: FK→workflows, status, trigger type/user, timing, error.
- **`workflow_run_steps`** — Individual step results: FK→workflow_runs, step metadata, input/output JSON, agent_execution_id.
- **`workflow_schedules`** — One-to-one with workflows: cron expression, timezone, enabled flag, last/next run timestamps.

### `rbac.py` — New table
- **`custom_roles`** — Tenant-scoped named roles with a `permissions` JSON column (resource → list of actions), `is_builtin` flag.

### `0002_ws2_db_migration.py` — Migration
- Creates `workflows`, `workflow_runs`, `workflow_run_steps`, `workflow_schedules` with all indexes.
- Creates `custom_roles` with indexes.
- `ALTER TABLE settings_api_keys ADD COLUMN rate_limit INTEGER` (nullable).
- Creates `secret_registrations` and `secret_access_logs` tables (FK constraints to `tenants`/`user_identities` omitted to avoid ordering issues in test environments).
- Full `downgrade()` reverting all changes.

### `settings.py` (routes) — API key CRUD
- `POST /api-keys` — inserts `SettingsAPIKey` row, returns plain-text key.
- `GET /api-keys` — queries `SettingsAPIKey` filtered by `tenant_id`.
- `DELETE /api-keys/{key_id}` — deletes by PK after tenant ownership check.
- Settings/feature-flag routes remain in-memory (intentionally minimal scope).

### `sso_config.py` — Custom roles CRUD
- `GET /rbac/matrix` — merges built-in roles with `CustomRole` rows from DB.
- `POST /rbac/roles` — inserts `CustomRole`, checks for name collision in DB.
- `PUT /rbac/roles/{role_id}` — updates `CustomRole` fields via `session.get`.
- `DELETE /rbac/roles/{role_id}` — deletes `CustomRole` via `session.delete` after tenant ownership check.
- SSO config routes still use `_sso_configs` in-memory dict (out of scope).

### `secrets.py` — Secret registrations → DB
Replaced 3 sync in-memory helpers with 4 async DB helpers:
- `_get_registration(session, tenant_id, path)` — SELECT by tenant+path.
- `_set_registration(session, tenant_id, path, data)` — upsert (insert or update).
- `_delete_registration(session, tenant_id, path)` — DELETE if exists.
- `_reg_to_dict(reg)` — converts `SecretRegistration` ORM to dict for route logic compatibility.

Routes updated: `create_secret`, `list_secrets`, `get_rotation_dashboard`, `update_secret`, `delete_secret`, `rotate_secret`, `set_rotation_policy` — all now inject `session: AsyncSession = Depends(get_session)`.

---

## Migration Summary

```
Revision: 0002_ws2_db_migration
Parent:   0001 (or base)
Creates:
  - workflows
  - workflow_runs
  - workflow_run_steps
  - workflow_schedules
  - custom_roles
  - secret_registrations
  - secret_access_logs
Alters:
  - settings_api_keys: ADD COLUMN rate_limit INTEGER
```

---

## Ruff Check Output

```
All checks passed!
```
(11 auto-fixable issues were corrected: unused imports, redundant f-strings, local re-imports shadowing top-level imports)

---

## Pytest Output

```
200 passed, 1 pre-existing failure (test_health_envelope_format), 2 warnings in ~1.03s
```

The 1 failure (`test_health_envelope_format`) is pre-existing and unrelated to this workstream — it tests that `/health` wraps its response in a `{"data": ..., "meta": ...}` envelope, which was already failing before these changes.

---

## Technical Decisions

- **No FK to `tenants`/`user_identities` in migration** — avoids ordering/dependency issues in SQLite test environments; model-level FKs in `secrets.py` are preserved for production Postgres.
- **`_utcnow()` pattern** — all new models use `datetime.utcnow()` (naive UTC) matching the existing codebase convention.
- **`_DEFAULT_TENANT` UUID** — workflow routes have no auth dependency (matching original); a zero-UUID default tenant is used.
- **Settings/flags left in-memory** — `_settings_store` and `_flags_store` in `settings.py` were intentionally not migrated to stay within scope.
- **`_sso_configs` in-memory dict** — SSO config routes still use this; only RBAC custom roles within `sso_config.py` were migrated.
