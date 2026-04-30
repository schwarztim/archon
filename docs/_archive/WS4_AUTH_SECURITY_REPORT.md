# WS-4: Auth, Rate Limiting, Group Management & Security — Implementation Report

**Workstream:** WS-4  
**Date:** 2026-02-26  
**Status:** ✅ Complete

---

## Summary

WS-4 implements the security hardening layer for Archon: Azure Entra ID OIDC authentication (third JWT tier), Redis-backed rate limiting middleware, real TOTP MFA endpoints, and PII/secret redaction in the audit trail.

---

## Changes Made

### 1. `backend/app/config.py`

Added six new configuration fields, all read from `ARCHON_` env vars:

| Field | Default | Purpose |
|---|---|---|
| `OIDC_DISCOVERY_URL` | `""` | Entra OIDC discovery document URL |
| `OIDC_CLIENT_ID` | `""` | Entra application client ID (audience) |
| `OIDC_CLIENT_SECRET` | `""` | Optional — for confidential clients |
| `OIDC_TENANT_ID` | `""` | Entra directory (tenant) ID |
| `RATE_LIMIT_RPM` | `1000` | Global per-tenant requests per minute |
| `RATE_LIMIT_ENABLED` | `True` | Kill-switch for rate limiting |

### 2. `backend/app/middleware/auth.py`

Extended the JWT validation pipeline from 2 tiers to **3 tiers**:

```
Tier 1: HS256 dev-mode (JWT_SECRET)       — unchanged, fastest path
Tier 2: RS256 Keycloak JWKS               — unchanged, Keycloak tokens
Tier 3: RS256 Azure Entra ID OIDC (new)   — Entra tokens when OIDC_DISCOVERY_URL set
```

**Tier 3 implementation details:**

- `_fetch_entra_jwks()` — resolves `jwks_uri` from the OIDC discovery document, fetches the JWKS, caches for **1 hour** (separate lock/timestamp from Keycloak cache)
- `_map_entra_groups_to_roles()` — queries `GroupRoleMapping` table to convert Entra group OIDs to Archon roles; fails open (returns `[]`) if DB is unavailable
- **Claim extraction:** `oid` (stable identifier), `preferred_username`/`upn` (email fallback), `groups` (mapped via `GroupRoleMapping`), `tid` (tenant), `amr` (MFA methods reference)
- **MFA detection:** checks `mfa_verified` claim (Keycloak) **or** `amr` values (`mfa`, `ngcmfa`, `rsa`, `hwk`, `face`, `fido`) for Entra ID
- Backward-compatible: when `OIDC_DISCOVERY_URL` is empty, tier 3 is silently skipped

### 3. `backend/app/middleware/rate_limit.py` (new file)

Redis INCR + EXPIRE fixed-window rate limiter with two enforcement tiers:

**Tier 1 — Global per-tenant (1000 RPM default):**
- Redis key: `rl:tenant:<tenant_id>:<minute_bucket>`
- Falls back to client IP when no tenant is in request state

**Tier 2 — Per-API-key:**
- Redis key: `rl:apikey:<api_key_id>:<minute_bucket>`
- Only enforced when `request.state.api_key_id` and `request.state.api_key_rate_limit` are set by upstream middleware
- Reads the per-key limit from `APIKey.rate_limit` via request state

**On limit exceeded:** returns HTTP 429 with `Retry-After` header set to remaining window TTL.

**Fail-open policy:** if Redis is unreachable, requests pass through without blocking.

**Exempt paths:** `/healthz`, `/readyz`, `/livez`, `/docs`, `/redoc`, `/openapi.json`, `/metrics`

Registered in `main.py` after DLP middleware.

### 4. `backend/app/routes/auth_routes.py`

Implemented real TOTP MFA using `pyotp`:

**`POST /api/v1/auth/totp/setup`** (also mounted at `/mfa/totp/setup` for backward compat):
- Generates 32-char base-32 secret (160 bits entropy) via `pyotp.random_base32()`
- Returns `otpauth://` provisioning URI for QR code display
- Generates 8 backup codes (`secrets.token_hex(8)` each = 64 bits)
- Requires authentication (`require_auth` dependency)

**`POST /api/v1/auth/totp/verify`** (also mounted at `/mfa/totp/verify`):
- Validates 6-digit code via `pyotp.TOTP.verify()` with `valid_window=1` (±30s drift)
- Returns HTTP 422 when user hasn't completed TOTP setup
- Returns HTTP 401 on invalid/expired code
- Returns HTTP 400 on malformed code (not 6 digits)

`_get_totp_secret()` helper performs DB lookup with graceful fallback.

### 5. `backend/app/middleware/audit_middleware.py`

Added PII/secret redaction before any value reaches the database:

| Pattern | Before | After |
|---|---|---|
| Archon API keys | `ak_live_abc123xyz` | `ak_live_***` |
| Bearer tokens | `Bearer eyJhbGci...` | `Bearer ***` |
| Emails in URL paths | `/users/alice@example.com` | `/users/***@***.***` |

**Bodies never stored:** The dispatch loop only records `status_code`, `outcome`, `ip_address`, `request_id`, and the auth scheme (not value). No request/response body is captured.

### 6. `backend/requirements.txt`

Added:
```
msal>=1.28.0
pyotp>=2.9.0
```

---

## Acceptance Criteria Status

| Criterion | Status |
|---|---|
| OIDC auth works with Entra discovery URL | ✅ Tier 3 validates RS256 Entra tokens |
| Gracefully handles missing client secret | ✅ Public client mode (no secret needed for validation) |
| TOTP setup endpoint works | ✅ Returns real secret + QR URI + 8 backup codes |
| TOTP verify endpoint works | ✅ pyotp TOTP.verify() with ±30s window |
| Rate limiting enforced globally | ✅ Per-tenant Redis counter, 429 + Retry-After |
| Rate limiting enforced per-API-key | ✅ Per-key Redis counter from request.state |
| AD groups auto-map to Archon roles | ✅ GroupRoleMapping table lookup |
| Audit logs redact secrets and PII | ✅ API keys, Bearer tokens, emails masked |
| Bodies never in audit logs | ✅ Only action metadata stored |
| Backward compatible with HS256/Keycloak | ✅ Tiers 1 & 2 unchanged |

---

## Ruff Lint Results

```
backend/app/middleware/   — 0 errors (our files)
backend/app/config.py     — 0 errors
```

One pre-existing F401 in `dlp_middleware.py` (not in WS-4 scope).

---

## Test Results

```
1723 passed, 25 failed (all pre-existing failures confirmed by git stash test)
```

Pre-existing failures:
- `tests/test_auth/test_jwt_validation.py::test_missing_token_returns_401` — pre-existing dev-mode bypass test gap
- `tests/test_agent19/test_settings.py` (22 tests) — pre-existing module import issue
- `tests/test_agent06/test_versioning_service.py::test_verify_signature_valid` — pre-existing

No regressions introduced by WS-4.

---

## Security Notes

1. **Never hardcode secrets:** All OIDC/auth secrets read from `ARCHON_` env vars only
2. **JWKS caching:** Entra JWKS cached 1 hour to prevent SSRF amplification; Keycloak 5 minutes
3. **MFA amr validation:** Entra `amr` claim checked against known strong MFA methods only
4. **Rate limit fail-open:** By design — availability > strict enforcement when Redis is down
5. **`oid` claim for user ID:** Entra's `oid` is stable across token refreshes; `sub` changes per-app
