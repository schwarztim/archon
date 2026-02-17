# Agent 22 — Master Validator — Build Prompt

> Hand this file to a coding agent. It contains everything needed to build this component.

## Context
You are building the **Master Validator** — the final quality gate that validates the entire Archon platform works correctly end-to-end.
Project root: `~/Scripts/Archon/`

## What Already Exists (do NOT rebuild these)
- `tests/` directory — 1092+ existing tests. DO NOT modify existing tests. ADD new validation tests.
- All 21 other agents' code (after they've been built). This agent runs LAST.

## What to Build

### 1. Backend Test Suite Validation
```bash
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q
```
Must pass with 0 failures. Document total test count.

### 2. SDD Check
Run SDD scoring tool if it exists. Must score 10/10.

### 3. Branding Verification
```bash
grep -ri "openairia" ~/Scripts/Archon/backend/ ~/Scripts/Archon/frontend/src/ --include="*.py" --include="*.tsx" --include="*.ts" | grep -v node_modules | grep -v __pycache__
```
Must return zero results.

### 4. Smoke Tests (API)
Write a comprehensive smoke test script that curls every major API endpoint:
```bash
# Health
curl -f http://localhost:8000/api/v1/health
# Agents CRUD
curl -f -X POST http://localhost:8000/api/v1/agents -H "Authorization: Bearer $TOKEN" -d '{"name":"test"}'
# List agents
curl -f http://localhost:8000/api/v1/agents/ -H "Authorization: Bearer $TOKEN"
# Execute agent
curl -f -X POST http://localhost:8000/api/v1/agents/{id}/execute -H "Authorization: Bearer $TOKEN" -d '{"input":{"msg":"test"}}'
# Router models
curl -f http://localhost:8000/api/v1/router/models -H "Authorization: Bearer $TOKEN"
# Templates
curl -f http://localhost:8000/api/v1/templates/ -H "Authorization: Bearer $TOKEN"
# Connectors
curl -f http://localhost:8000/api/v1/connectors/ -H "Authorization: Bearer $TOKEN"
# DLP policies
curl -f http://localhost:8000/api/v1/dlp/policies -H "Authorization: Bearer $TOKEN"
# Audit logs
curl -f http://localhost:8000/api/v1/audit-logs/ -H "Authorization: Bearer $TOKEN"
# Secrets status
curl -f http://localhost:8000/api/v1/secrets/status -H "Authorization: Bearer $TOKEN"
# Cost summary
curl -f http://localhost:8000/api/v1/cost/summary -H "Authorization: Bearer $TOKEN"
# Governance
curl -f http://localhost:8000/api/v1/governance/registry -H "Authorization: Bearer $TOKEN"
# Workflows
curl -f http://localhost:8000/api/v1/workflows/ -H "Authorization: Bearer $TOKEN"
```

### 5. Frontend Build Verification
```bash
cd ~/Scripts/Archon && docker compose build frontend
```
Must complete with zero errors.

### 6. UX Audit Checklist
Create a Playwright test file that navigates to every page and verifies:
- Page loads without errors (no console errors)
- No raw JSON fields visible on standard forms (check for `<textarea>` with JSON content)
- All buttons have click handlers (not disabled without reason)
- All forms submit to correct API endpoints (network tab verification)
- Navigation works (all sidebar items lead to real pages)
- Error states show friendly messages
- Empty states show helpful guidance
- Dark mode renders correctly (no invisible text, correct contrast)

Pages to check:
- / (Dashboard)
- /agents
- /builder
- /executions
- /workflows
- /templates
- /marketplace
- /model-router
- /connectors
- /cost
- /dlp
- /governance
- /sentinel-scan
- /lifecycle
- /tenants
- /secrets
- /audit
- /settings

### 7. Cross-Agent Integration Tests
Write integration tests verifying end-to-end flows:
1. Create Agent (Agent 05) → Execute (Agent 06) → View in Audit (Agent 18) → See cost (Agent 11)
2. Configure Provider with API key (Agent 08) → Create Agent with model (Agent 05) → Execute (Agent 06)
3. Create Template (Agent 04) → Instantiate (Agent 04) → Edit in Builder (Agent 02)
4. Create DLP Policy (Agent 12) → Execute Agent (Agent 06) → Verify DLP scan occurred
5. Configure SSO (Agent 16) → Verify login flow

### 8. Validation Report
Output a markdown report summarizing:
- Total tests: X passed, Y failed
- SDD Score: X/10
- Branding: clean/violations found
- API Smoke Tests: X/Y passed
- Frontend Build: pass/fail
- UX Audit: X/Y pages passed
- Integration: X/Y flows passed
- Overall: PASS/FAIL

## Patterns to Follow (from OSS)

### Pattern 1: Dify Quality Checks
Dify has comprehensive CI with unit tests, integration tests, linting, and type checking. Adaptation: Archon adds UX audit (no JSON on forms) and cross-agent integration testing that Dify doesn't have.

### Pattern 2: Original Design — Platform Validation Suite
No single OSS project has a master validator agent. Designed from enterprise QA practices. Pattern: Layered validation (unit → integration → smoke → UX → E2E) with a final report.

## Backend Deliverables
- `scripts/smoke_test.sh` — CREATE — API smoke test script
- `tests/integration/test_e2e_flows.py` — CREATE — Cross-agent integration tests

## Frontend Deliverables
- `tests/e2e/ux_audit.spec.ts` — CREATE — Playwright UX audit tests

## Integration Points
- ALL other agents — This agent validates the combined output of all 21 agents

## Acceptance Criteria
1. 1092+ backend tests pass with 0 failures
2. SDD score is 10/10
3. Zero "openairia" branding references found
4. All API smoke test endpoints return 2xx
5. Frontend builds without errors
6. All pages load without console errors
7. No raw JSON fields on standard forms (verified by UX audit)
8. Create → Execute → Trace → Audit flow works end-to-end
9. All sidebar navigation items lead to functional pages
10. Validation report generated with all results

## Files to Read Before Starting
- `~/Scripts/Archon/agents/AGENT_RULES.md`
- All other agents' build prompts (to understand what was built)

## Files to Create/Modify

| Path | Action |
|---|---|
| `scripts/smoke_test.sh` | CREATE |
| `scripts/validate_platform.sh` | CREATE |
| `tests/integration/test_e2e_flows.py` | CREATE |
| `tests/e2e/ux_audit.spec.ts` | CREATE |
| `VALIDATION_REPORT.md` | CREATE (output) |

## Testing
```bash
cd ~/Scripts/Archon && bash scripts/validate_platform.sh
# Should output comprehensive validation report
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
