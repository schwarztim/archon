# Infrastructure Changes

## Overview

This document records all infrastructure gaps fixed in the BUILD phase
by workstream ws-14 (Infrastructure Fixes).

---

## Dependencies Added

| Package | Version | Purpose |
|---|---|---|
| `presidio-analyzer` | `>=2.2.0` | PII detection engine (NER-based entity recognition) |
| `presidio-anonymizer` | `>=2.2.0` | PII redaction / anonymisation engine |

**Note:** `hvac` (Vault client) was already present in `requirements.txt` at `>=2.3.0`.
The previous recon finding was incorrect — Vault client dependency was not missing.

**Important:** Presidio models download approximately 500 MB of spaCy language models on
first run. Run the following after install in production:

```bash
python -m spacy download en_core_web_lg
```

---

## Configuration Changes

### `backend/app/config.py`

| Setting | Before | After | Reason |
|---|---|---|---|
| `AUTH_DEV_MODE` | `default=True` | `default=False` | Production safety — prevents accidental auth bypass |
| `VAULT_ADDR` | *(missing)* | `"http://localhost:8200"` | Vault address configurable via `ARCHON_VAULT_ADDR` env var |
| `VAULT_TOKEN` | *(missing)* | `"dev-token"` | Vault token configurable via `ARCHON_VAULT_TOKEN` env var |

**Production note:** Always set `ARCHON_VAULT_TOKEN` to a non-default value. The
`"dev-token"` default is for local development only.

---

## New Files Created

### `backend/app/core/__init__.py`
- Created for import compatibility with code that uses `from app.core import ...`
- The flat layout (`app/config.py`, `app/database.py`) is preserved for backward compat
- No code currently imports from `app.core` — this is a forward-compatibility shim

### `backend/app/models/common.py`
- Defines `StandardResponse[T]` — generic Pydantic model wrapping all API responses
- Also defines `PaginatedResponse[T]`, `ErrorResponse`, and `ErrorDetail`
- All models include `meta` dict with `request_id` and `timestamp`

### `backend/app/cache.py`
- Application-wide Redis client singleton (distinct from WebSocket's `redis_client.py`)
- Provides `get_redis()` and `close_redis()` coroutines
- Strict mode: raises `RuntimeError` on connection failure (callers must handle it)
- The WebSocket subsystem has its own lenient client in `app/websocket/redis_client.py`

---

## Modified Files

### `backend/app/middleware/tenant.py`
- Added `get_tenant_id(request: Request) -> str` FastAPI dependency
- Extracts `tenant_id` from `request.state` (set by `TenantMiddleware`)
- Falls back to `"default-tenant"` for unauthenticated/anonymous routes
- Import of `Request` from FastAPI added

---

## Security Fixes

| Fix | Impact |
|---|---|
| `AUTH_DEV_MODE=False` default | Prevents auth bypass in production deployments where env is not explicitly set |
| `VAULT_ADDR` / `VAULT_TOKEN` now in config | Vault client uses proper config instead of hardcoded fallbacks in `secrets/manager.py` |

---

## What Was Already Present

The following items were confirmed present before this workstream ran:

- `hvac>=2.3.0` — already in `requirements.txt`
- `REDIS_URL` setting — already in `config.py`
- `get_current_user()` in `auth.py` — full implementation with Keycloak JWKS + dev-mode fallback
- Redis client in `app/websocket/redis_client.py` — exists, lenient/graceful-degradation style

---

## Next Steps

1. **Presidio models:** Run `python -m spacy download en_core_web_lg` after `pip install`
2. **Vault token:** Set `ARCHON_VAULT_TOKEN` to a real token before production deployment
3. **AUTH_DEV_MODE:** Set `ARCHON_AUTH_DEV_MODE=true` in local `.env` file for dev environments
4. **Redis persistence:** Configure Redis `save` options if session/cache durability is needed
5. **StandardResponse adoption:** Migrate existing route handlers to use `StandardResponse[T]`
   as the `response_model` for consistent API contracts
