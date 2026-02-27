# Archon Platform — Fixup Swarm Plan

**Project:** /Users/timothy.schwarz/archon/
**Baseline commit:** 899188e (all swarm WS-0 through WS-8 work committed)
**Current test results:** Backend 1724/1782 (58 failures), Frontend 48/48, Gateway 31/31

Fix the 5 remaining issues in the Archon platform. Each issue is a separate workstream.
Run the full test suite after each workstream to verify no regressions.

---

## Workstream 1: Fix 25 SCIM Test Failures (UUID parsing)

**Priority:** HIGH — 25 of 58 failures
**Estimated scope:** 2 files, ~10 line changes

### Root Cause
Tests use plain string tenant IDs (`"tenant-aaa"`, `"tenant-bbb"`) but the DB model
column is `UUID` type and `scim_service.py` calls `UUID(tenant_id)` which raises
`ValueError: badly formed hexadecimal UUID string`.

### Files
- `tests/test_agent01/test_scim_service.py` — lines 25-26 define `_TENANT_A` and `_TENANT_B`
- `backend/app/models/scim_db.py` — line 25 defines `tenant_id: UUID = Field(index=True)`
- `backend/app/services/scim_service.py` — 8 occurrences of `UUID(tenant_id)` at lines 101, 149, 193, 248, 295, 340, 393, 435

### Fix
Change the test fixtures to use valid UUID strings. Keep the UUID column type and UUID() casts:

```python
# tests/test_agent01/test_scim_service.py lines 25-26
# BEFORE:
_TENANT_A = "tenant-aaa"
_TENANT_B = "tenant-bbb"

# AFTER:
_TENANT_A = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
_TENANT_B = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"
```

Search the entire test file for any other hardcoded non-UUID tenant strings and fix them too.

### Verification
```bash
PYTHONPATH=backend python3 -m pytest tests/test_agent01/test_scim_service.py -v --tb=short
```
Expected: 28/28 passed (was 3/28).

---

## Workstream 2: Fix Gateway Azure OpenAI Payload (Responses API)

**Priority:** HIGH — gateway calls fail against live Azure endpoint
**Estimated scope:** 1 file, ~15 line changes

### Root Cause
`gateway/app/tools/builtin_ai.py` constructs payloads using Chat Completions API format
(`"messages"`, `"max_tokens"`, `/chat/completions` endpoint) but the deployed model
`gpt-5.2-codex` only supports the Responses API format.

### Current Code (builtin_ai.py)
```python
url = (
    f"{endpoint}/openai/deployments/{deployment}"
    "/chat/completions?api-version=2025-04-01-preview"
)
payload = {
    "messages": [
        {"role": "system", "content": f"You are executing tool '{tool_id}'. ..."},
        {"role": "user", "content": str(body)},
    ],
    "max_tokens": 1024,
}
```

### Fix
Change to Responses API format:

```python
url = f"{endpoint}/openai/responses?api-version=2025-04-01-preview"

payload = {
    "model": deployment,
    "input": [
        {"role": "system", "content": f"You are executing tool '{tool_id}'. Respond with valid JSON only."},
        {"role": "user", "content": str(body)},
    ],
    "max_output_tokens": 1024,
}
```

Also update the response parsing — the Responses API returns a different response shape:
- Chat Completions: `data["choices"][0]["message"]["content"]`
- Responses API: `data["output"][0]["content"][0]["text"]` (or check `data.get("output_text")`)

Read the existing response parsing code in `builtin_ai.py` and update it to handle the
Responses API response format. Look at how `test_azure_openai_smoke.py` parses responses
for reference (it already uses the Responses API format).

### Gateway Tests
After making changes, run:
```bash
cd gateway && python3 -m pytest tests/ -v --tb=short
```
The gateway tests mock HTTP calls, so they need their mocked responses updated to match
the new Responses API format. Check `tests/test_dispatch.py` and any test that mocks
`call_builtin_ai` — update the mock response shape.

Expected: 31/31 passed (no regressions).

### Verification (live endpoint — optional, may skip if no API key)
```bash
curl -s -X POST "https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview" \
  -H "Content-Type: application/json" \
  -H "api-key: b664331212b54911969792845dee8ba9" \
  -d '{"model":"gpt-5.2-codex","input":[{"role":"user","content":"ping"}],"max_output_tokens":16}'
```

---

## Workstream 3: Fix 3 Remaining Test Failures

**Priority:** HIGH — brings failures from 58 → 30 (integration-only)
**Estimated scope:** 3 files, ~20 line changes

### 3A: test_verify_signature_valid (versioning_service.py)

**File:** `tests/test_agent06/test_versioning_service.py` — test at lines 536-551
**Service:** `backend/app/services/versioning_service.py` — `verify_signature()` at lines 506-540

**Root cause:** The test's mock `version_db.definition` is `{"nodes": {"a": {"type": "llm"}}}`
which lacks a `"_signature"` key. In production, `create_version()` (line 211) injects
`definition["_signature"] = signature` before persisting. But the test constructs a raw mock
that bypasses `create_version()`.

In `verify_signature()`:
1. `stored_signature = db_ver.definition.get("_signature", "")` → empty string
2. `if stored_signature` evaluates to `False`
3. `valid = False` unconditionally

**Fix:** In the test, compute the correct signature and inject it into the mock definition:

```python
async def test_verify_signature_valid() -> None:
    version_db = _make_agent_version_db()
    session = _mock_session()
    secrets = _mock_secrets()  # returns {"key": "test-signing-key"}

    # Compute and inject the correct signature
    from app.services.versioning_service import _canonical_json, _compute_hash, _sign
    canonical = _canonical_json(version_db.definition)
    content_hash = _compute_hash(canonical)
    signing_key = "test-signing-key"  # matches _mock_secrets()
    version_db.definition["_signature"] = _sign(content_hash, signing_key)

    session.get = AsyncMock(return_value=version_db)
    result = await VersioningService.verify_signature(
        version_id=version_db.id, session=session, secrets=secrets, tenant_id="tenant-1",
    )
    assert result.valid is True
    assert result.content_hash_matches is True
```

NOTE: Check if `_canonical_json`, `_compute_hash`, and `_sign` are importable (they may be
private functions). If they're module-level functions starting with `_`, they're still
importable. Read `versioning_service.py` to find the exact function names and signatures.

If `_get_signing_key` is async and extracts the key differently, trace the exact path
to ensure the test uses the same key value.

### 3B: test_missing_token_returns_401 (JWT validation)

**File:** `tests/test_auth/test_jwt_validation.py` — test at lines 91-98
**Middleware:** `backend/app/middleware/auth_middleware.py` (or `backend/app/middleware/auth.py`)
  — `get_current_user()` function

**Root cause:** `settings.AUTH_DEV_MODE` defaults to `True` (defined in `backend/app/config.py`
line 34). When no token is provided, the middleware hits the dev-mode bypass and returns a
synthetic admin user instead of raising `HTTPException(401)`.

**Fix:** Patch `AUTH_DEV_MODE` to `False` in the test:

```python
async def test_missing_token_returns_401(mock_keycloak_jwks) -> None:
    with _patch_jwks(mock_keycloak_jwks):
        with patch("app.middleware.auth.settings") as mock_settings:
            mock_settings.AUTH_DEV_MODE = False
            mock_settings.KEYCLOAK_REALM_URL = settings.KEYCLOAK_REALM_URL  # preserve other attrs
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(request=_mock_request(), token="")
    assert exc_info.value.status_code == 401
```

Alternatively, use `monkeypatch` or a simpler approach — read the test file to see what
patching patterns are already used.

NOTE: First determine the correct module path. The middleware file may be at
`backend/app/middleware/auth.py` or `backend/app/middleware/auth_middleware.py`. Read
the imports at the top of the test file to determine the exact import path. The patch
target must match where `settings` is imported FROM in the middleware module.

### 3C: test_chat_completion (Azure smoke test)

**File:** `tests/integration/test_azure_openai_smoke.py` — test at lines 21-47

**Root cause:** This is a live integration test. It already uses the correct Responses API
format (`"input"`, not `"messages"`). The failure is `max_output_tokens: 10` which may be
below the API minimum of 16.

**Fix:** Change `max_output_tokens` from 10 to 16:
```python
payload = {
    "model": "gpt-5.2-codex",
    "input": "Say OK",
    "max_output_tokens": 16,  # was 10
}
```

NOTE: This test requires a live Azure endpoint and API key. If the test still fails after
the fix (e.g., 404 DeploymentNotFound), that's an infrastructure issue — mark the test
with `@pytest.mark.skip(reason="requires live Azure deployment")` or leave it.

### Verification
```bash
PYTHONPATH=backend python3 -m pytest tests/test_agent06/test_versioning_service.py::test_verify_signature_valid tests/test_auth/test_jwt_validation.py::test_missing_token_returns_401 -v --tb=short
```
Expected: 2/2 passed.

---

## Workstream 4: Complete Lifecycle Service DB Migration

**Priority:** MEDIUM — functional improvement, prevents data loss on restart
**Estimated scope:** 2 files, ~600 lines changed

### Current State
8 in-memory dicts in `backend/app/services/lifecycle_service.py` (lines 53-60):

| Dict | Type | Used By (functions) |
|------|------|---------------------|
| `_scheduled_jobs` | `dict[str, list[ScheduledJob]]` | `schedule_execution` (R+W), `list_scheduled_jobs` (R) |
| `_metrics_store` | `dict[str, list[dict[str, float]]]` | `compute_health_score` (R), `detect_anomalies` (R) |
| `_approval_gates` | `dict[str, list[ApprovalGate]]` | `get_pipeline` (R), `configure_gates` (W) |
| `_environments` | `dict[str, list[EnvironmentInfo]]` | `list_environments` (R) |
| `_agent_states` | `dict[str, str]` | `transition` (R+W) |
| `_deployments` | `dict[str, Deployment]` | `deploy` (W), `rollback_deployment` (R+W), `get_pipeline` (R), `promote_to_next_stage` (R+W), `demote_to_previous_stage` (R+W), `list_environments` (R), `get_config_diff` (R), `get_deployment_history` (R), `get_deployment_health` (R) |
| `_deployment_history` | `dict[str, list[DeploymentHistoryEntry]]` | **NEVER USED — dead code** |
| `_health_metrics` | `dict[str, HealthMetrics]` | `get_deployment_health` (R) |

### Existing DB Models (backend/app/models/lifecycle.py)
3 SQLModel table classes already exist but are NOT wired:
- `DeploymentRecord` (line 22) — maps to `_deployments`
- `HealthCheck` (line 61) — maps to `_health_metrics`
- `LifecycleEvent` (line 84) — maps to `_agent_states` (derive current state from latest event)

### Step 1: Add 4 New SQLModel Table Classes

Add to `backend/app/models/lifecycle.py`:

```python
class ScheduledJobRecord(SQLModel, table=True):
    __tablename__ = "scheduled_jobs"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    cron_expression: str
    next_run_at: datetime | None = None
    enabled: bool = Field(default=True)
    parameters: dict = Field(default_factory=dict, sa_type=JSON)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MetricDataPoint(SQLModel, table=True):
    __tablename__ = "metric_data_points"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    metric_name: str = Field(index=True)
    value: float
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApprovalGateRecord(SQLModel, table=True):
    __tablename__ = "approval_gates"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    pipeline_id: str = Field(index=True)
    stage: str
    approver_role: str
    status: str = Field(default="pending")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EnvironmentRecord(SQLModel, table=True):
    __tablename__ = "environments"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    name: str = Field(index=True)
    config: dict = Field(default_factory=dict, sa_type=JSON)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### Step 2: Wire 15 Functions to Use DB

In `backend/app/services/lifecycle_service.py`:

1. Import `async_session_factory` from `app.database`
2. Import the new + existing DB models from `app.models.lifecycle`
3. For each function, replace dict reads/writes with async DB queries using
   `async with async_session_factory() as session:`

**Pattern for dict reads:**
```python
# BEFORE:
key = f"{tenant_id}:{agent_id}"
jobs = _scheduled_jobs.get(key, [])

# AFTER:
async with async_session_factory() as session:
    stmt = select(ScheduledJobRecord).where(
        ScheduledJobRecord.tenant_id == tenant_id,
        ScheduledJobRecord.agent_id == agent_id,
    )
    result = await session.exec(stmt)
    jobs = result.all()
```

**Pattern for dict writes:**
```python
# BEFORE:
key = f"{tenant_id}:{agent_id}"
_scheduled_jobs.setdefault(key, []).append(job)

# AFTER:
async with async_session_factory() as session:
    record = ScheduledJobRecord(tenant_id=tenant_id, agent_id=agent_id, ...)
    session.add(record)
    await session.commit()
```

**For `_agent_states`:** Query the latest `LifecycleEvent` per agent to derive current state:
```python
stmt = select(LifecycleEvent).where(
    LifecycleEvent.agent_id == agent_id
).order_by(LifecycleEvent.created_at.desc()).limit(1)
```

**For `_deployments`:** Use existing `DeploymentRecord` model. Map between the Pydantic
`Deployment` model and `DeploymentRecord` SQLModel. The `DeploymentRecord` has more fields
(replicas, traffic_percentage, etc.) — preserve defaults for unmapped fields.

**For `_health_metrics`:** Use existing `HealthCheck` model. The `HealthMetrics` Pydantic
model has `response_time_p50/p95/p99`, `throughput_rps`, `uptime_pct` — store these in the
`HealthCheck.details` JSON column.

### Step 3: Delete Dead Code
Remove `_deployment_history` dict (line 59) — it's declared but never read or written.

### Step 4: Add Hybrid Fallback (Optional)
Follow the pattern from `settings.py` — if DB is unavailable, fall back to in-memory.
This ensures tests that don't have a DB connection still pass:

```python
try:
    async with async_session_factory() as session:
        # DB query
except Exception:
    # fall back to in-memory dict
```

### Step 5: Create Alembic Migration
```bash
cd backend && alembic revision --autogenerate -m "0003_lifecycle_db_migration"
```
This should pick up the 4 new tables + the 3 existing tables that were never migrated.

### Verification
```bash
PYTHONPATH=backend python3 -m pytest tests/ --no-header -q --tb=no
```
Expected: No new failures introduced. Lifecycle tests (if any exist in test_agent* dirs)
should continue passing.

---

## Workstream 5: Auto-fix Ruff Lint Violations

**Priority:** LOW — code quality
**Estimated scope:** ~138 auto-fixes across many files

### Step 1: Auto-fix
```bash
cd /Users/timothy.schwarz/archon && ruff check backend/ --fix
```
This fixes 138 of 184 violations (mostly F401 unused imports, F841 unused variables).

### Step 2: Review Remaining 46 Violations
```bash
ruff check backend/ --statistics
```

The remaining ~46 violations are:
- **E402** (30): module-level import not at top of file — often intentional (conditional imports,
  circular import avoidance). Review each and either:
  - Move the import to the top if safe
  - Add `# noqa: E402` if intentional
- **E741** (3): ambiguous variable name (e.g., `l`, `O`, `I`) — rename to descriptive names
- **F811** (1): redefined-while-unused — remove the first definition or merge

### Step 3: Verify No Breakage
```bash
PYTHONPATH=backend python3 -m pytest tests/ --no-header -q --tb=no
cd frontend && npx vitest run
cd gateway && python3 -m pytest tests/ -v
```

---

## Execution Order

1. **WS-1: SCIM tests** (quick win, -25 failures)
2. **WS-3: Other 3 test failures** (quick win, -3 failures)
3. **WS-2: Gateway Azure payload** (functionality fix)
4. **WS-5: Ruff lint** (code quality, fast)
5. **WS-4: Lifecycle DB migration** (largest change, do last)

## Success Criteria

| Metric | Before | Target |
|--------|--------|--------|
| Backend test failures | 58 | ≤ 30 (integration-only) |
| Frontend tests | 48/48 | 48/48 |
| Gateway tests | 31/31 | 31/31 |
| Ruff violations | 184 | ≤ 46 |
| In-memory dicts (lifecycle) | 8 | 0 |

## Constraints

- DO NOT delete existing working code — only extend and fix
- DO NOT modify swarm infrastructure files (.swarm/, .claude/, SWARM_PLAN.md)
- Run full test suite after each workstream
- Commit each workstream separately with descriptive messages
- Use `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` trailer
