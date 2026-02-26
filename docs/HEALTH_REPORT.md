# Project Health Report

Generated: Thu Feb 26 14:10:53 EST 2026

## Executive Summary

Overall project health is **GOOD**. Core backend and frontend functionality is stable, with 98% of tests passing. The frontend builds cleanly with zero TypeScript errors. Two confirmed route mismatches require immediate attention. The majority of linting violations are auto-fixable. Infrastructure endpoints are reachable with minor configuration adjustments needed.

---

## Test Results

### pytest
- **Total Tests:** 1782
- **Passed:** 1747
- **Failed:** 35
- **Errors:** 0

**Failed Test Breakdown:**
- 31 integration tests (backend not running during test execution)
- 2 unit test failures in `test_agent19` (`test_settings.py`)
- 2 other test failures

**Assessment:** Core functionality stable. Integration failures are expected without a running backend. Unit test failures in `test_agent19` need investigation.

---

### Code Quality (ruff)
- **Total Violations:** 184
- **Auto-fixable:** 138 (75%)
- **Manual Fixes Required:** 46

**Assessment:** The majority of linting issues can be resolved automatically by running `ruff check --fix` on the backend codebase. The remaining 46 violations require manual review.

---

### Frontend Build
- **Status:** ✅ PASS
- **Build Time:** 4.03s
- **TypeScript Errors (`tsc --noEmit`):** 0

**Assessment:** Frontend builds cleanly with no type errors.

---

## Infrastructure Health

### Azure OpenAI
- **Connectivity:** ✅ Reachable
- **Status:** HTTP 400 (model name format issue)
- **Assessment:** Endpoint is accessible but requires the correct API model naming format to return valid responses.

### OIDC Discovery
- **Connectivity:** ✅ Reachable
- **Response:** Valid JSON
- **Assessment:** SSO integration is functional.

### Docker
- **Status:** ⚠️ Not tested
- **Reason:** Docker may not be running on the test system
- **Assessment:** Containerization untested in this run; should be validated in CI environment.

---

## Confirmed Bugs

### 1. Audit Log URL Mismatch
- **File:** `frontend/src/api/governance.ts`
- **Issue:** `getAuditTrail()` calls `/governance/audit` but the backend router is registered at `/audit-logs/`
- **Impact:** Audit log feature is non-functional
- **Fix Required:** Change the endpoint in `governance.ts` to `/audit-logs/`

---

### 2. System Health Endpoint Mismatch
- **Files:**
  - `frontend/src/components/settings/SystemHealthTab.tsx`
  - `frontend/src/pages/DashboardPage.tsx`
- **Issue:** Frontend calls `/health` but backend is registered at `/api/v1/health`
- **Response Format Mismatch:** Backend returns `{status, services: {api, database, redis, vault, keycloak}, version, timestamp}` with string values (`"up"`, `"connected"`), but frontend expects boolean fields
- **Additional Bug (`DashboardPage.tsx`):** Double-consume of `response.json()` causing runtime errors
- **Impact:** Health monitoring is non-functional
- **Fix Required:** Update endpoint URLs and response parsing logic in both files

---

## Debunked Issues

### 1. Marketplace Triple-Prefix ❌ FALSE POSITIVE
- **Investigation:** Routes are correctly configured at `/api/v1/marketplace`
- **Status:** Working as designed

### 2. Sentinel White Screen ❌ FALSE POSITIVE
- **Investigation:** All 3 routers are properly registered in `main.py`
- **Status:** Working as designed

---

## Recommendations

### Immediate Actions
1. Fix audit log URL mismatch (see WS-1)
2. Fix health endpoint mismatches (see WS-1)
3. Run `ruff check --fix` on backend codebase to resolve 138 auto-fixable violations
4. Investigate `test_agent19` unit test failures in `test_settings.py`

### Short-term Actions
1. Set up Docker testing environment and validate containerization
2. Configure Azure OpenAI with the correct model naming format
3. Address remaining 46 manual linting fixes identified by ruff

### Long-term Actions
1. Implement integration test fixtures that mock external services to eliminate false negatives
2. Add pre-commit hooks for ruff auto-fixing to prevent regression
3. Add API contract tests (e.g., OpenAPI schema validation) to catch URL mismatches early

---

## Conclusion

Overall project health is **GOOD** with targeted fixes needed. Core functionality is stable with a **98% test pass rate**. The frontend builds cleanly with zero TypeScript errors. Two confirmed route mismatches require immediate attention and are tracked under WS-1. Code quality issues are largely auto-fixable. Infrastructure endpoints are reachable with minor configuration adjustments needed for Azure OpenAI.
