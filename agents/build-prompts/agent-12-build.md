# Agent 12 — DLP & Guardrails — Build Prompt

## Context

Data Loss Prevention pipeline: scan all execution inputs/outputs for PII and secrets, enforce guardrail policies with configurable actions (redact, block, log, alert). Build the DLP middleware, a visual detector library, a policy test feature, and a real metrics dashboard.

**Tech stack — Backend:** Python 3.12, FastAPI, SQLModel, Alembic, AsyncSession. **Frontend:** React 19, TypeScript strict, shadcn/ui, Tailwind CSS, React Flow. **Auth:** JWT + Keycloak. **Secrets:** HashiCorp Vault via `backend/app/secrets/manager.py`.

---

## What Already Exists

| File | Lines | Action |
|------|-------|--------|
| `frontend/src/pages/DLPPage.tsx` | 386 | **EXTEND** — Live scanner textarea, policy form (Name/Action/Detectors/Sensitivity), metrics all 0. |
| `frontend/src/components/dlp/DetectorPicker.tsx` | 188 | **MODIFY** — Enhance from tag-based input to visual card grid. |
| `frontend/src/api/dlp.ts` | 70 | **EXTEND** — DLP API client. |
| `backend/app/routes/dlp.py` | 365 | **EXTEND** — DLP routes. |
| `backend/app/services/dlp_service.py` | 936 | **EXTEND** — Substantial DLP implementation. Add middleware integration. |
| `backend/app/models/dlp.py` | 234 | **KEEP** — DLP models. |

---

## What to Build

### 1. DLP Middleware

FastAPI middleware that intercepts ALL execution I/O:

- **Before LLM call:** Scan input text for PII and secrets.
- **After LLM response:** Scan output text for PII and secrets.
- **Policy actions** (based on matching policy):
  - **Redact:** Mask sensitive data (e.g., `SSN: ***-**-1234`, `API Key: sk-****...ab3f`).
  - **Block:** Reject with HTTP 403 + structured explanation of what was detected.
  - **Log:** Record detection in `dlp_detections` table but allow the request.
  - **Alert:** Allow request but send notification to admin.

The middleware should be registered in the FastAPI app and apply to execution endpoints. It must not scan non-execution endpoints (e.g., auth, settings).

### 2. Detector Library (10+ Built-in)

Each detector has: name, description, regex pattern(s), sensitivity level, icon.

| Detector | Pattern Description |
|----------|-------------------|
| SSN | `\d{3}-\d{2}-\d{4}` |
| Credit Card | Luhn-valid 13–19 digit sequences |
| Email Address | RFC 5322 simplified pattern |
| Phone Number | US/international formats |
| Street Address | Number + street name patterns |
| Passport Number | Country-specific formats |
| Driver's License | State-specific formats |
| API Key | `sk-`, `api_`, `key-` prefixed strings |
| Password | `password=`, `passwd=`, `pwd=` patterns in text |
| JWT Token | `eyJ` base64 header pattern |
| AWS Key | `AKIA` prefix, 20-char alphanumeric |
| Private Key | `-----BEGIN.*PRIVATE KEY-----` blocks |
| Custom Regex | User-defined pattern |

### 3. Detector Picker Redesign

Replace the tag-based input in `DetectorPicker.tsx` with a visual grid of detector cards:

- Each card: icon, name, short description, sensitivity level indicator (Low / Medium / High / Critical color dot).
- Toggle on/off per detector.
- "Custom Regex" card opens an inline form: regex input + test string field + match preview.
- Search / filter detectors by name or category.

### 4. Policy Test Feature

"Test Policy" section on the DLP page:

- Textarea: paste sample text.
- Select active policy (or all policies).
- Click "Scan" → send to `POST /api/v1/dlp/scan`.
- Results: detected items highlighted inline with type labels (e.g., `[SSN]`, `[Credit Card]`) and the action that would apply.
- Show count of detections by type.

### 5. DLP Metrics Dashboard (Real Data)

Replace the all-zeros metrics with real data from scan records:

- **Summary Cards:** Scans Today, Detections Today, Blocked Today, Redacted Today.
- **Detection Type Breakdown:** Pie/donut chart showing distribution by detector type.
- **Trend Chart:** Line chart of detections over time (daily, 30-day window).
- **Recent Detections Table:** Columns: Time, Detector Type, Action Taken, Source (agent name / execution ID), Snippet (redacted preview).

### 6. Inline DLP Indicators

- **Agent Cards** in AgentsPage: Show a shield icon / DLP badge if DLP policy is enabled for that agent.
- **Execution Detail:** Show redacted items in the step trace (e.g., "2 items redacted in step 3").

---

## Patterns to Follow

### Pattern 1 — Dify Content Moderation

**Source:** `dify/api/core/moderation/`

Dify has a moderation module that hooks into the app generation pipeline. It checks inputs and outputs against moderation providers (OpenAI moderation API, keyword lists, custom APIs). Moderation runs as a pre/post hook — before the LLM call and after the response. If moderation fails, a preset fallback response is returned.

**Adaptation:** Same before/after hook pattern but with regex-based PII detection instead of external moderation APIs. Run as FastAPI middleware (applied to execution routes) rather than per-app hooks. Return structured error responses with detection details instead of a preset fallback message. Detection results include the detector type, matched text (redacted), position, and the action taken.

### Pattern 2 — Dify Sensitive Word Filter

**Source:** `dify/api/core/app/apps/`

Dify's advanced_chat and similar app types check for sensitive words before processing user input. The sensitive word check runs synchronously — if blocked content is detected, the app returns a preset safe response. The detection is binary (blocked or allowed).

**Adaptation:** Archon's DLP system is more granular: four action levels (redact/block/log/alert) instead of binary block/allow. Multiple detectors can fire on the same text. The middleware returns structured JSON errors with all detections listed, not a preset response. Policies are configurable per tenant/agent with different detector sets and actions.

---

## Backend Deliverables

| Method | Endpoint | Description |
|--------|----------|-------------|
| — | DLP Middleware | FastAPI middleware class: intercept execution I/O, scan, apply policy actions. |
| POST | `/api/v1/dlp/scan` | Manual scan endpoint for the policy test feature. Input: text + policy_id (optional). Output: detections list. |
| GET | `/api/v1/dlp/metrics` | Real metrics: scans today, detections today, blocked, redacted. |
| GET | `/api/v1/dlp/detections` | Recent detections list. Query: `?limit=50&offset=0`. |
| GET | `/api/v1/dlp/detectors` | List available detector types with name, description, sensitivity, icon. |
| PUT | `/api/v1/dlp/policies/{id}` | Enhanced: accepts detector card schema (list of detector objects with enabled flag). |
| POST | `/api/v1/dlp/policies` | Create policy with detector configuration. |
| GET | `/api/v1/dlp/policies/{id}/stats` | Detection stats for a specific policy. |

All endpoints:
- JWT-authenticated, scoped to `tenant_id`.
- Return envelope: `{"data": ..., "meta": {"request_id": "...", "timestamp": "..."}}`.
- Mutations produce `AuditLog` entries.

---

## Frontend Deliverables

| File | Action |
|------|--------|
| `pages/DLPPage.tsx` | **MODIFY** — Real metrics, test feature, enhanced detector picker. |
| `components/dlp/DetectorPicker.tsx` | **MODIFY** — Visual card grid instead of tags. Toggle on/off per detector. |
| `components/dlp/DetectorCard.tsx` | **CREATE** — Single detector card: icon, name, description, sensitivity dot, toggle. |
| `components/dlp/PolicyTestPanel.tsx` | **CREATE** — Textarea + policy selector + "Scan" button + highlighted results. |
| `components/dlp/MetricsDashboard.tsx` | **CREATE** — Summary cards + pie chart + trend chart. |
| `components/dlp/DetectionsList.tsx` | **CREATE** — Recent detections table with time, type, action, source, snippet. |
| `components/dlp/CustomRegexForm.tsx` | **CREATE** — Regex input + test string + match preview. |
| `components/dlp/DLPBadge.tsx` | **CREATE** — Shield icon badge for agent cards. |
| `api/dlp.ts` | **MODIFY** — Add scan, metrics, detections, detectors API calls. |

All components: dark/light mode via Tailwind `dark:` variants.

---

## Integration Points

- **Execution Engine**: DLP middleware wraps execution endpoints. Scans happen before LLM calls (input) and after (output).
- **Agent Cards (AgentsPage)**: Show `<DLPBadge />` on agents that have an active DLP policy.
- **Execution Detail**: Show redaction summary in step trace.
- **Connectors (Agent 09)**: DLP should catch connector credentials if they leak into execution text.
- **AuditLog**: Log all block actions, policy changes.
- **Notifications**: Alert actions trigger notification to admin users.

---

## Acceptance Criteria

1. DLP middleware scans all execution I/O (input before LLM, output after LLM).
2. Detector picker shows visual cards with descriptions and sensitivity indicators, not tags.
3. 10+ built-in detector types available via `GET /detectors`.
4. Policy test: paste text → click Scan → see highlighted detections with type labels.
5. Metrics dashboard shows real scan data (not zeros).
6. Recent detections table shows actual scanned items with time, type, action, source.
7. DLP badge (shield icon) visible on agent cards when DLP is enabled for that agent.
8. Redacted content shows masked values (e.g., `SSN: ***-**-1234`, `API Key: sk-****...ab3f`).
9. Block action returns HTTP 403 with structured detection details.
10. Custom regex detector allows user-defined patterns with test preview.

---

## Files to Read

Read these files before writing any code to understand existing patterns:

```
backend/app/routes/dlp.py
backend/app/services/dlp_service.py
backend/app/models/dlp.py
frontend/src/pages/DLPPage.tsx
frontend/src/components/dlp/DetectorPicker.tsx
frontend/src/api/dlp.ts
frontend/src/components/ui/               # shadcn/ui primitives
backend/app/services/execution_service.py  # where middleware hooks in
```

---

## Files to Create / Modify

### Backend

```
backend/app/routes/dlp.py                                  # MODIFY — add scan, metrics, detections, detectors endpoints
backend/app/services/dlp_service.py                        # MODIFY — add scan, metrics, detections logic
backend/app/middleware/dlp.py                              # CREATE — FastAPI DLP middleware class
backend/app/services/dlp/detectors.py                      # CREATE — built-in detector registry with regex patterns
backend/app/services/dlp/scanner.py                        # CREATE — text scanning engine (runs detectors, returns matches)
backend/app/services/dlp/actions.py                        # CREATE — action handlers (redact, block, log, alert)
backend/app/models/dlp.py                                  # MODIFY — add DLPDetection model for scan results (if not exists)
tests/test_dlp.py                                          # CREATE — endpoint + service tests
tests/test_dlp_middleware.py                                # CREATE — middleware integration tests
tests/test_dlp_detectors.py                                # CREATE — detector regex accuracy tests
```

### Frontend

```
frontend/src/pages/DLPPage.tsx                             # MODIFY
frontend/src/components/dlp/DetectorPicker.tsx             # MODIFY
frontend/src/components/dlp/DetectorCard.tsx               # CREATE
frontend/src/components/dlp/PolicyTestPanel.tsx            # CREATE
frontend/src/components/dlp/MetricsDashboard.tsx           # CREATE
frontend/src/components/dlp/DetectionsList.tsx             # CREATE
frontend/src/components/dlp/CustomRegexForm.tsx            # CREATE
frontend/src/components/dlp/DLPBadge.tsx                   # CREATE
frontend/src/api/dlp.ts                                    # MODIFY
```

---

## Testing

```bash
# Backend — run from repo root
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/test_dlp.py tests/test_dlp_middleware.py tests/test_dlp_detectors.py --no-header -q

# Minimum coverage
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/test_dlp.py --cov=backend/app/routes/dlp --cov=backend/app/services/dlp_service --cov-fail-under=80 --no-header -q
```

Test cases must include:
- SSN detector matches `123-45-6789`.
- Credit card detector matches valid Luhn numbers.
- Email detector matches `user@example.com`.
- API key detector matches `sk-abc123...`.
- JWT detector matches `eyJhbGciOiJIUzI1NiIs...`.
- AWS key detector matches `AKIAIOSFODNN7EXAMPLE`.
- Scan endpoint returns detections with type, position, action.
- Redact action masks correctly: `SSN: ***-**-1234`.
- Block action returns 403 with detection details.
- Log action records detection but allows request (200).
- Metrics endpoint returns non-zero counts after scans.
- Detections endpoint returns recent items.
- Custom regex detector works with user-provided pattern.
- Middleware applies to execution routes only.
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
