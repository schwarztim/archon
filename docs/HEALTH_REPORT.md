# Archon Platform — Health Report

**Generated:** Thu Feb 26 2026  
**Executor:** L3 Worker (ws-0), swarm session swarm-1772144420849-1  
**Scope:** Baseline diagnostics — no code modifications made

> _Previous report dated Thu Feb 26 14:10:53 EST 2026 is superseded by this run._

---

## Summary Dashboard

| Check | Status | Details |
|-------|--------|---------|
| Pytest Suite | ⚠️ PARTIAL | 1727 passed, 55 failed (infrastructure gaps only) |
| Ruff Linting | ✅ PASS | 0 violations |
| Frontend Build | ✅ PASS | Built in 4.27s, 2614 modules |
| TypeScript Check | ✅ PASS | 0 errors |
| Azure OpenAI Connectivity | ⚠️ REACHABLE | HTTP 400 — API param mismatch (`messages` → `input`) |
| OIDC Discovery | ✅ PASS | Valid JSON, `authorization_endpoint` present |

---

## 1. Pytest Suite

**Command:** `PYTHONPATH=backend python3 -m pytest tests/ --no-header -q`  
**Duration:** 20.20s  
**Result:** `55 failed, 1727 passed, 10 warnings`

### Pass Rate
- **Total tests:** 1,782
- **Passed:** 1,727 (96.9%)
- **Failed:** 55 (3.1%)
- **Warnings:** 10 (`PytestDeprecationWarning` — `asyncio_default_fixture_loop_scope` unset)

### Failure Root Cause Analysis

All 55 failures trace to **two missing infrastructure dependencies** — no application logic bugs were found.

#### Category 1: Backend Server Not Running — 30 failures
All integration tests connect to `localhost:8000` and fail with:
```
httpx.ConnectError: [Errno 61] Connection refused
```

Affected test files:

| File | Failures |
|------|----------|
| `tests/integration/test_workflows.py` | 3 |
| `tests/integration/test_sentinel.py` | 3 |
| `tests/integration/test_templates.py` | 2 |
| `tests/integration/test_settings.py` | 2 |
| `tests/integration/test_secrets.py` | 2 |
| `tests/integration/test_rbac.py` | 2 |
| `tests/integration/test_rate_limit.py` | 2 |
| `tests/integration/test_model_router.py` | 2 |
| `tests/integration/test_marketplace.py` | 2 |
| `tests/integration/test_health.py` | 2 |
| `tests/integration/test_dlp.py` | 2 |
| `tests/integration/test_audit_logs.py` | 2 |
| `tests/integration/test_api_keys.py` | 2 |
| `tests/integration/test_embeddings.py` | 1 |
| `tests/integration/test_azure_openai.py` | 1 |

**Sample stack trace:**
```python
tests/integration/test_api_keys.py:29: in test_list_api_keys
    resp = client.get(f"{api_prefix}/settings/api-keys")
httpx._transports.default:118: ConnectError
    httpx.ConnectError: [Errno 61] Connection refused
```

#### Category 2: PostgreSQL Not Running — 25 failures
All `tests/test_agent01/test_scim_service.py` tests fail with:
```
OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5432, 0, 0),
         [Errno 61] Connect call failed ('127.0.0.1', 5432)
```
PostgreSQL not running on `localhost:5432`. 3 of 28 SCIM tests pass (non-DB code paths).

**Failing SCIM test classes:**
- `TestCreateUser` — user creation/retrieval
- `TestUpdateUser` — replace display name, active flag, last_modified
- `TestDeleteUser` — deactivation, delete nonexistent, last_modified update
- `TestGroups` — list/create/filter/meta
- `TestTenantIsolation` — cross-tenant isolation for users and groups
- `TestSCIMErrorHandling` — 404 handling for users and groups

### Deprecation Warnings
```
PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.
Future versions of pytest-asyncio will default the loop scope for asynchronous fixtures to function scope.
```
**Fix:** Add to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

---

## 2. Linting Status (Ruff)

**Command:** `ruff check backend/`  
**Result:** `All checks passed!`

- **Violations:** 0
- **Status:** ✅ Fully clean — zero linting issues

> _Note: A prior health report (14:10 EST) reported 184 violations. Those have since been resolved._

---

## 3. Frontend Build

**Command:** `cd frontend && npm install && npm run build`  
**Result:** ✅ Build successful

```
> archon-frontend@0.1.0 build
> tsc -b && vite build

vite v6.4.1 building for production...
✓ 2614 modules transformed.

dist/index.html                     0.54 kB │ gzip:   0.36 kB
dist/assets/index-Cdkx47TW.css     75.82 kB │ gzip:  12.69 kB
dist/assets/index-U68zRER_.js   1,584.19 kB │ gzip: 413.53 kB

✓ built in 4.27s
```

**Cosmetic Warning (non-blocking):**
> Some chunks are larger than 500 kB after minification.  
> Main JS bundle: 1,584 kB (413 kB gzipped). Consider dynamic imports or `build.rollupOptions.output.manualChunks`.

**npm audit:** Packages with known vulnerabilities; run `npm audit` for full details.

---

## 4. TypeScript Check

**Command:** `cd frontend && npx tsc --noEmit`  
**Result:** No output — **zero TypeScript errors**

- **Error count:** 0
- **Status:** ✅ Clean

---

## 5. Azure OpenAI Connectivity

**Endpoint:** `https://YOUR_AZURE_ENDPOINT.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview`  
**Model:** `gpt-5.2-codex`  
**HTTP Status:** `400 Bad Request`

**Status: ⚠️ REACHABLE — API parameter mismatch**

The endpoint responds (not 401/403/502/504). The 400 error is a request format issue:

```json
{
  "error": {
    "message": "Unsupported parameter: 'messages'. In the Responses API, this parameter has moved to 'input'.",
    "type": "invalid_request_error",
    "param": null,
    "code": "unsupported_parameter"
  }
}
```

**Root cause:** The test curl command uses `"messages"` (Chat Completions API format) against the newer Responses API which requires `"input"`.

**Fix:** Update request body:
```json
{
  "input": [{"role": "user", "content": "ping"}],
  "max_completion_tokens": 5,
  "model": "gpt-5.2-codex"
}
```

The Azure OpenAI service is **up and responding**; connectivity is confirmed.

---

## 6. OIDC Discovery

**URL:** `https://login.microsoftonline.com/REDACTED_OIDC_TENANT_ID/v2.0/.well-known/openid-configuration`  
**Result:** ✅ Valid JSON — all required OIDC keys present

| Key | Value |
|-----|-------|
| `authorization_endpoint` | `https://login.microsoftonline.com/REDACTED_OIDC_TENANT_ID/oauth2/v2.0/authorize` |
| `token_endpoint` | `https://login.microsoftonline.com/REDACTED_OIDC_TENANT_ID/oauth2/v2.0/token` |
| `jwks_uri` | `https://login.microsoftonline.com/REDACTED_OIDC_TENANT_ID/discovery/v2.0/keys` |
| `issuer` | `https://login.microsoftonline.com/REDACTED_OIDC_TENANT_ID/v2.0` |

OIDC discovery is fully operational for tenant `REDACTED_OIDC_TENANT_ID`.

---

## Confirmed Bugs from Prior Runs (carried forward)

### 1. Audit Log URL Mismatch
- **File:** `frontend/src/api/governance.ts`
- **Issue:** `getAuditTrail()` calls `/governance/audit` but backend router is at `/audit-logs/`
- **Impact:** Audit log feature non-functional

### 2. System Health Endpoint Mismatch
- **Files:** `frontend/src/components/settings/SystemHealthTab.tsx`, `frontend/src/pages/DashboardPage.tsx`
- **Issue:** Frontend calls `/health` but backend is at `/api/v1/health`; response format mismatch (string vs boolean fields)
- **Impact:** Health monitoring non-functional

---

## Recommendations

### Priority 1 — Start Infrastructure (blocks 55 tests)
1. **PostgreSQL on :5432** — required for all SCIM service tests.
2. **Backend server on :8000** — required for all integration tests. Alternative: refactor integration tests to use FastAPI `TestClient` (in-process, no server required).

### Priority 2 — API Compatibility
3. **Azure OpenAI Responses API**: Update all backend code using `/openai/responses` endpoint to use `"input"` instead of `"messages"`.

### Priority 3 — Non-blocking Improvements
4. **pytest-asyncio deprecation**: Set `asyncio_default_fixture_loop_scope = "function"` in `pyproject.toml`.
5. **Frontend bundle size**: Route-based code splitting recommended (1.58 MB main bundle).
6. **npm audit**: Review and remediate package vulnerabilities.

---

## Conclusion

The Archon codebase is in **good shape**. Backend linting is fully clean (0 ruff violations), the frontend builds with zero TypeScript errors, and OIDC authentication infrastructure is healthy. The 55 test failures are 100% attributable to missing runtime infrastructure (no live backend server, no PostgreSQL) — not code defects. Azure OpenAI connectivity is confirmed reachable; only the request format needs updating for the newer Responses API.

**No code modifications were made during this diagnostic run.**
