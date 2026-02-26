# WS-1 Route Bug Fixes Report

**Date:** 2026-02-26  
**Worker:** WS-1 (L3 Coder)  
**Status:** ✅ Complete

---

## Summary of Changes

### Bug 1 — Marketplace Triple-Prefix (8 decorators fixed)

**File:** `backend/app/routes/marketplace.py`

Stripped `/api/v1/marketplace` from 8 route decorators on a router already registered with that prefix in `main.py`:

| Before | After |
|--------|-------|
| `@router.post("/api/v1/marketplace/publishers")` | `@router.post("/publishers")` |
| `@router.post("/api/v1/marketplace/packages")` | `@router.post("/packages")` |
| `@router.post("/api/v1/marketplace/packages/{package_id}/install")` | `@router.post("/packages/{package_id}/install")` |
| `@router.get("/api/v1/marketplace/packages/search")` | `@router.get("/packages/search")` |
| `@router.post("/api/v1/marketplace/packages/{package_id}/rate")` | `@router.post("/packages/{package_id}/rate")` |
| `@router.get("/api/v1/marketplace/publishers/analytics")` | `@router.get("/publishers/analytics")` |
| `@router.get("/api/v1/marketplace/packages/{package_id}/verify")` | `@router.get("/packages/{package_id}/verify")` |
| `@router.get("/api/v1/marketplace/categories")` | `@router.get("/categories")` |

---

### Bug 2 — Sentinel White Screen (enterprise_router not registered)

**Files:** `backend/app/main.py`

`enterprise_router` was defined in `sentinelscan.py` but never imported or registered in `main.py`.

**Changes made:**
- Added `enterprise_router as sentinelscan_enterprise_router` to the import from `app.routes.sentinelscan`
- Added `application.include_router(sentinelscan_enterprise_router, prefix=settings.API_PREFIX)` in Phase 3 routers block

**Note:** `enterprise_router` already has `prefix="/sentinel"` built in (line 306 of sentinelscan.py). Registering with `prefix=settings.API_PREFIX` produces the correct effective path `/api/v1/sentinel/...`. Registering with `settings.API_PREFIX + "/sentinel"` as originally specified in the task would have caused a double-prefix (`/api/v1/sentinel/sentinel/...`). A blocker was posted to the swarm board documenting this decision.

---

### Bug 3 — Duplicate /posture Endpoint

**File:** `backend/app/routes/sentinelscan.py`

Both `router` (L286) and `scan_router` (L613) defined `GET /posture` under the same prefix `/sentinelscan`, causing a route conflict.

**Change:** Renamed the `router`-based handler from `@router.get("/posture")` to `@router.get("/posture/summary")`.

---

### Bug 4 — Audit Log URL Mismatch

**File:** `backend/app/routes/audit_logs.py` (L20)

Frontend calls `/audit-logs` but backend registered as `/audit/logs`.

**Change:** `APIRouter(prefix="/audit/logs", ...)` → `APIRouter(prefix="/audit-logs", ...)`

---

### Bug 5 — Smoke Test Double Prefix

**File:** `scripts/smoke_test.sh` (L50)

**Change:** `/api/v1/api/v1/dlp/policies` → `/api/v1/dlp/policies`

---

## Verification

### Ruff Lint
```
ruff check backend/app/routes/marketplace.py backend/app/routes/sentinelscan.py backend/app/routes/audit_logs.py backend/app/main.py
```
Result: 9 pre-existing F401 (unused import) warnings — all auto-fixable, none introduced by these changes.

### Test Suite
```
PYTHONPATH=backend python3 -m pytest tests/ --no-header -q
```
Result: **2 failed, 1746 passed** — the 2 failures (`test_verify_signature_valid`, `test_missing_token_returns_401`) are pre-existing and unrelated to these route changes.
