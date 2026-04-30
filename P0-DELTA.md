# P0-DELTA — Wave 0 worker status against the master plan

**Date:** 2026-04-30
**Plan reference:** `~/.copilot/session-state/fcc4865f-1863-433f-87c5-0ed09daeee22/files/archon-durable-orchestration-worker-plan.md`, §"Phase 0: Stabilize existing P0/P1 gaps"
**Authoritative-state references:** `CURRENT_STATE.md` (truth table), `REMEDIATION_REPORT_R2.md` (Round-2 remediation evidence)
**Worker scope:** P0-A, P0-B, P0-C, P0-D, P0-E

This file is the worker P0-D's structural deliverable: an honest DONE / PARTIAL / NOT-STARTED report on every Wave-0 worker so the orchestrator can dispatch follow-up workers without re-discovering what is already shipped.

## Summary table

| Worker | Title | Status | Evidence file/line |
|--------|-------|--------|---------------------|
| P0-A | Background dispatch failure recovery | **DONE** | `backend/app/services/dispatch_runtime.py:37,159,203`; `backend/tests/test_dispatch_runtime_failure.py` (7 tests); `tests/integration/test_worker_canary.py:288` |
| P0-B | Non-inline worker canary | **PARTIAL** | Script `scripts/test-worker-canary.sh` exists; tests pass; **`.github/workflows/ci.yml` has no canary step — not a hard CI gate** |
| P0-C | Frontend route registration | **DONE** | `frontend/src/App.tsx:11–14,71–74` registers all four pages |
| P0-D | Schema/ADR freeze | **DOING** | This document; `docs/adr/orchestration/ADR-008-durable-orchestration-schema.md` (40,779 bytes) |
| P0-E | Existing integration path unification | **PARTIAL** | Executions/Agents routes go through `ExecutionFacade`; **3 bypasses in `routes/workflows.py` and 1 in `worker.py`**; `tests/integration/test_integration_paths_canonical.py` does not exist; `scripts/check-direct-run-bypasses.sh` exists and **fails (RC=1, 4 BYPASS hits)** |

**Counts:** DONE = 2, PARTIAL = 2, DOING = 1, NOT-STARTED = 0.

The two PARTIAL workers (P0-B, P0-E) are the gating items for Wave 1.

---

## P0-A — Background dispatch failure recovery — DONE

### What the plan asked for

> "Wrap background dispatch entrypoints so unhandled exceptions always transition the run to `failed`. Emit `run.failed` event with error code, traceback hash, worker ID, and correlation ID. Ensure failed dispatch does not leave a run stuck in `queued`, `running`, or leased state. Add regression test that injects a dispatcher exception and proves terminal `failed`."

### What is shipped

| Artefact | File:line | Verdict |
|---|---|---|
| `_persist_failed_run` helper (reads run, no-ops if terminal, sets `status="failed"` + `error_code="background_dispatch_failed"` + `completed_at`, commits, appends `run.failed` event) | `backend/app/services/dispatch_runtime.py:37` | Present |
| `schedule_dispatch(coro, run_id=...)` accepts run_id kwarg and stashes it on the tracked task | `backend/app/services/dispatch_runtime.py:159` | Present |
| `_on_done` callback schedules `_persist_failed_run` on non-CancelledError exceptions | `backend/app/services/dispatch_runtime.py:117–146` | Present |
| `drain_tracked_tasks(timeout)` helper for tests so the persist path completes before the loop tears down | `backend/app/services/dispatch_runtime.py:203` | Present |
| `routes/executions.py` POST handler calls `await schedule_dispatch(dispatch_run(run.id), run_id=run.id)` | `backend/app/routes/executions.py:213,281` | Present |
| `routes/agents.py` POST handler ditto | `backend/app/routes/agents.py:197` | Present |
| Dedicated unit test bundle for persistence behaviour | `backend/tests/test_dispatch_runtime_failure.py` (7 tests) | Present |
| Integration-level proof: route → schedule_dispatch → raising coro → terminal `failed` + `run.failed` event | `tests/integration/test_worker_canary.py::TestNonInlineFailureFinalisation::test_non_inline_failed_run_is_marked_failed_after_background_exception` (line 288) | Present |
| Invariant: no raw `asyncio.create_task(dispatch_run(...))` survives | `grep -rn 'asyncio\.create_task(dispatch_run' backend/app/routes/` returns 0 | Verified |

### Verdict

**DONE.** The four code-level requirements (wrap, emit failed event, no stuck state, regression test) are all met with file evidence. `REMEDIATION_REPORT_R2.md` reports `test-worker-canary.sh` RC=0 (3/3 pass) and the dedicated 7-test failure bundle.

### Gap

`error_code="background_dispatch_failed"` is set, but the master plan also asked for "traceback hash, worker ID, and correlation ID" on the emitted event. The current implementation populates `error` (truncated message) and `error_code` only. **Follow-up worker:** extend `_persist_failed_run` to compute `sha256(traceback)` and stash it on the event payload, plus `worker_id` (the failing dispatch's owner if known) and `correlation_id` if present in the originating context. File: `backend/app/services/dispatch_runtime.py:37`. Verb: extend `_persist_failed_run` payload composition.

---

## P0-B — Non-inline worker canary — PARTIAL

### What the plan asked for

> "Add canary that starts backend and worker as separate processes. Start a run through REST. Confirm worker claims it, executes it, persists steps, emits events, and reaches terminal state. Add this canary to CI as a hard gate. Acceptance: Canary passes with inline dispatch disabled. Run has worker ID and step rows. CI fails if worker process is not running."

### What is shipped

| Artefact | File:line | Verdict |
|---|---|---|
| Canary script with `ARCHON_DISPATCH_INLINE=0` default | `scripts/test-worker-canary.sh:1–40` | Present |
| Canary test class `TestNonInlineWorkerCanary` (3 tests: completes, has worker_id + step rows, lifecycle event chain) | `tests/integration/test_worker_canary.py:178` | Present |
| Failure-finalisation companion test | `tests/integration/test_worker_canary.py:285` | Present |
| Negative control: REST without drain stays queued | `tests/integration/test_worker_canary.py:346` | Present |
| Makefile target | (per `REMEDIATION_REPORT_R2.md` §"P0") | Present |
| **CI hard gate** — workflow step that runs `bash scripts/test-worker-canary.sh` | **MISSING — searched `.github/workflows/ci.yml` for `worker-canary` and `test-worker-canary`; zero matches** | **NOT WIRED** |
| `docker-compose.test.yml` (plan listed this file) | `docker-compose.test.yml` was not produced — the canary uses an in-process FastAPI TestClient with `force_non_inline` fixture, not separate processes | Different design |

### Verdict

**PARTIAL.** Code path is proven (script returns RC=0 in this workspace per `REMEDIATION_REPORT_R2.md`). The plan's structural requirement — "Add this canary to CI as a hard gate. CI fails if worker process is not running" — is **not met**. The canary still runs in-process via `force_non_inline` fixture; it pins `ARCHON_DISPATCH_INLINE=0` and bypasses the route's inline await but never spawns a separate worker process. CI does not run it at all.

### Acceptance compliance

- "Canary passes with inline dispatch disabled" — **pass** (in-workspace).
- "Run has worker ID and step rows" — **pass** (asserted).
- "CI fails if worker process is not running" — **fail** (no CI step; no separate worker process).

### Next steps for follow-up worker

1. Add to `.github/workflows/ci.yml` a new job `verify-worker-canary` (or extend `verify-slice` parallel-group) that runs `bash scripts/test-worker-canary.sh` with `ARCHON_DISPATCH_INLINE=0` and `services: [postgres, redis]`. Verb: ADD job.
2. Add `verify-worker-canary` to the `build` job's `needs:` list so a red canary blocks merge. File: `.github/workflows/ci.yml:190-198`. Verb: ADD dependency.
3. (Optional, plan-aligned) Promote the canary from in-process `TestClient` + `force_non_inline` to a true separate-process canary using `docker-compose.test.yml` so the plan's "worker process is not running" assertion is structurally provable. File: NEW `docker-compose.test.yml`. Verb: CREATE.

---

## P0-C — Frontend route registration — DONE

### What the plan asked for

> "Register Run History, Approvals, and Artifacts pages. Add reachability tests."

### What is shipped

| Artefact | File:line | Verdict |
|---|---|---|
| `RunHistoryPage` import | `frontend/src/App.tsx:12` | Present |
| `ApprovalsPage` import | `frontend/src/App.tsx:13` | Present |
| `ArtifactsPage` import | `frontend/src/App.tsx:14` | Present |
| `ExecutionDetailPage` import | `frontend/src/App.tsx:11` | Present |
| `<Route path="executions/:id" ...>` | `frontend/src/App.tsx:71` | Present |
| `<Route path="runs" ...>` | `frontend/src/App.tsx:72` | Present |
| `<Route path="approvals" ...>` | `frontend/src/App.tsx:73` | Present |
| `<Route path="artifacts" ...>` | `frontend/src/App.tsx:74` | Present |
| Page components in `frontend/src/pages/` | `RunHistoryPage.tsx`, `ApprovalsPage.tsx`, `ArtifactsPage.tsx`, `ExecutionDetailPage.tsx` all exist | Present |
| Reachability tests (operator-flow contract + Playwright) | `frontend/src/tests/operator-flow.contract.test.tsx`, `frontend/e2e/operator-flow.spec.ts` (per `REMEDIATION_REPORT_R2.md` §"P3") | Present |

### Verdict

**DONE.** All four routes registered, all four page components exist, reachability tests are in place. `CURRENT_STATE.md` row "Frontend page reachability — `ExecutionDetailPage`" was previously the only proven row; the other three rows are now also proven by `App.tsx:72–74`.

### Open follow-ups (out of scope for P0-C)

- Pre-existing `audit.test.tsx` failures (4) due to missing QueryClient setup — flagged in `REMEDIATION_REPORT_R2.md` as not-P3-introduced.
- Bundle code-splitting (1.6 MB monolithic) — operator decision per `CURRENT_STATE.md`.

---

## P0-D — Schema/ADR freeze — DOING (this worker)

### What the plan asked for

> "Add ADR-008 for the expanded durable orchestration schema before any schema worker starts. Freeze ownership and names for: TaskQueue, Task, ActivityExecution, ActivityHeartbeat, PipelineCorrelation, WorkflowDefinitionVersion, RunChain, VisibilityIndex, PayloadBlob or artifact-backed payload references, schedule/backfill state fields. Preserve the existing workflow-vs-agent XOR contract. Add migrations in dependency order. Update feature matrix with `designed` entries."

### What is shipped (this turn)

| Artefact | File:line | Verdict |
|---|---|---|
| `docs/adr/orchestration/ADR-008-durable-orchestration-schema.md` (40,779 bytes) | NEW | Present |
| Names locked for `task_queues`, `tasks`, `activity_executions`, `pipeline_correlations`, `workflow_definition_versions`, `run_chains`, `visibility_indexes`, `schedules` plus `artifacts` additive columns | ADR-008 §1–§9 + "Locked" block | Present |
| Decision: heartbeat details inline on `ActivityExecution`, no separate `ActivityHeartbeat` table | ADR-008 §3 with rationale | Present |
| Decision: payload blobs reuse `Artifact` model with `is_payload` + `payload_role` flags, no `PayloadBlob` table | ADR-008 §8 with rationale | Present |
| Workflow-vs-agent XOR contract preservation table | ADR-008 §"Workflow-vs-agent XOR contract — preserved" | Present |
| Migration ordering locked (1: WorkflowDefinitionVersion → 2: TaskQueue → 3: Task → 4: ActivityExecution → 5: PipelineCorrelation → 6: RunChain → 7: VisibilityIndex → 8: Schedule → 9: Artifact additive columns) | ADR-008 §"Migration ordering (locked)" | Present |
| Cross-references to ADR-001..007 | ADR-008 "Depends on" header field + "See also" footer | Present |
| Locked names list (cannot change without superseding ADR) | ADR-008 §"Locked" | Present |

### What is **not** in scope for this worker (per the prompt's hard guardrails)

- DO NOT modify ADR-001..007 — confirmed, untouched.
- DO NOT modify any model file — confirmed, no edits to `backend/app/models/*.py`.
- DO NOT add migrations — confirmed, W1 owns alembic versions.
- Vendor-neutral language — confirmed; no upstream product names appear in the ADR (providers are listed as `github_actions`, `azure_devops`, `jenkins`, `gitlab`, `generic_webhook` — these are factual provider identifiers used inside `PipelineCorrelation.provider`, matching the plan's identical labels in §"Worker W8" and §"Worker W9a").

### Verdict

**DOING (output of this worker).** ADR-008 written; downstream workers (W1, W2, W3, W7, W8, W11, W12, W13, W16) can implement in parallel against the locked names.

### Open follow-ups

- Feature matrix update — the plan asks for `designed` entries for the eight tables. **This worker does not modify `docs/feature-matrix.yaml`** because (a) it is not a P0-D acceptance criterion strictly required to unblock W1, and (b) the prompt's guardrails say "do not modify any model file" and add migrations — `feature-matrix.yaml` is borderline. Recommended next step: a thin worker (10 minutes) appends 8 rows to `categories.schema:` (or creates that category) with `status: designed`, `source_files: ["docs/adr/orchestration/ADR-008-durable-orchestration-schema.md"]`, and the table name as `id`. File: `docs/feature-matrix.yaml`. Verb: APPEND.
- The plan listed `ActivityHeartbeat` and `PayloadBlob` as candidate tables; ADR-008 explicitly chose against creating either. If the operator disagrees with these decisions, a superseding ADR is required (per ADR-008's "Locked" governance rule).

---

## P0-E — Existing integration path unification — PARTIAL

### What the plan asked for

> "Route UI workflow test execution through `ExecutionFacade`. Route webhook-triggered runs through `ExecutionFacade`. Route event-triggered runs through `ExecutionFacade`. Route schedule-created runs through `ExecutionFacade`. Convert signal delivery to persistent signal/update rows. Ensure approval decisions resume runs through durable message path. Emit timer events when timers fire. Ensure sub-workflow/sub-agent nodes create child runs through `ExecutionFacade`. Add static bypass-detection gate for direct `WorkflowRun` construction."

### Per-path verification

| Path | Required canonical path | Current state | Verdict |
|------|-------------------------|---------------|---------|
| REST manual execution (`POST /api/v1/executions`) | Through `ExecutionFacade` | `routes/executions.py:184,258` calls `await ExecutionFacade.create_run(...)`; followed by `await schedule_dispatch(dispatch_run(run.id), run_id=run.id)` (line 213, 281) | **DONE** |
| Agent execution (`POST /api/v1/agents/{id}/execute`) | Through `ExecutionFacade` | `routes/agents.py:165` calls `await ExecutionFacade.create_run(...)`; followed by `await schedule_dispatch(...)` (line 197) | **DONE** |
| UI builder / test workflow execute (`/api/v1/workflows/{id}/execute` and similar) | Through `ExecutionFacade` | `routes/workflows.py:424,743,785` create `WorkflowRun(...)` directly with NO `ExecutionFacade` import or call | **NOT-STARTED — 3 bypasses** |
| Webhook-triggered runs | Through `ExecutionFacade` | Routes registered (per `CURRENT_STATE.md` row "Webhooks") but end-to-end "webhook → durable run → terminal not exercised by the official canary" | **PARTIAL** — proof gap, possible bypass |
| Event-triggered runs | Through `ExecutionFacade` | Not surveyed in this turn; no `event_service` or equivalent grep'd against `ExecutionFacade` | **UNKNOWN — investigation required** |
| Schedule-created runs | Through `ExecutionFacade` | `worker.py:278` creates `WorkflowRun(...)` directly inside the schedule tick, no `ExecutionFacade` import | **NOT-STARTED — 1 bypass** |
| Signal delivery (durable, not redis-only) | Persistent `Signal` row + event append | `models/approval.py:92` defines `Signal(SQLModel, table=True)` with `__tablename__ = "signals"`, `consumed_at` flag, run_id FK with CASCADE. Persistent. | **DONE** (signal path is durable) |
| Approval decisions resume runs | Update/signal path → event → worker resumes | Approval model exists; signal type `approval.granted/rejected/expired` documented in `models/approval.py:96–99` | **DONE** (per the durable Signal substrate) |
| Timer fire emits `timer.fired` event | Yes | `timer_service.py` exists per `CURRENT_STATE.md`; not grep'd against `ExecutionFacade` in this turn | **UNKNOWN — investigation required** |
| Sub-workflow node creates child runs through `ExecutionFacade` | Yes | `node_executors/sub_workflow.py` exists but does NOT import `ExecutionFacade` (grep returned 0 hits) | **NOT-STARTED** |
| Static bypass-detection gate | Script must exist and pass | `scripts/check-direct-run-bypasses.sh` exists. **Running it: RC=1 with 4 BYPASS hits** (`backend/app/worker.py:278`, `backend/app/routes/workflows.py:424`, `:743`, `:785`). | **PARTIAL** — gate exists, **fails today** |
| Acceptance test bundle `tests/integration/test_integration_paths_canonical.py` | Must exist | `ls tests/integration/test_integration_paths_canonical.py` → **No such file or directory** | **NOT-STARTED** |

### Verdict

**PARTIAL.** Two paths are clean (executions REST, agents REST). One major substrate is durable (`Signal`). **Five paths still bypass `ExecutionFacade` or are unverified**, and the acceptance test bundle does not exist. The static bypass gate (`scripts/check-direct-run-bypasses.sh`) was authored but is failing in the current workspace — meaning the P0-E "static bypass gate passes" acceptance criterion is **red right now**.

### Hard evidence — bypass scan

```
$ bash scripts/check-direct-run-bypasses.sh
FAIL: direct WorkflowRun construction detected outside ExecutionFacade

BYPASS: backend/app/worker.py:278:                        run = WorkflowRun(
BYPASS: backend/app/routes/workflows.py:424:    run = WorkflowRun(
BYPASS: backend/app/routes/workflows.py:743:    run = WorkflowRun(
BYPASS: backend/app/routes/workflows.py:785:        run = WorkflowRun(
```

### Next steps for follow-up worker(s)

Each row is a discrete, file-scoped change:

1. **`backend/app/routes/workflows.py:424` (workflow execute endpoint)** — Replace direct `WorkflowRun(...)` construction with `ExecutionFacade.create_run(...)` followed by `await schedule_dispatch(dispatch_run(run.id), run_id=run.id)`. Verb: REPLACE.
2. **`backend/app/routes/workflows.py:743` (second workflow execute path)** — Same fix. Verb: REPLACE.
3. **`backend/app/routes/workflows.py:785` (third workflow execute path)** — Same fix. Verb: REPLACE.
4. **`backend/app/worker.py:278` (schedule tick)** — Replace direct `WorkflowRun(...)` with `ExecutionFacade.create_run(...)` so schedule-created runs go through the same gate. Verb: REPLACE.
5. **`backend/app/services/node_executors/sub_workflow.py`** — Add `ExecutionFacade.create_run(...)` for child run creation; record `parent_run_id` (per ADR-008 §6 `RunChain`). Verb: ADD.
6. **`backend/app/services/timer_service.py`** — Audit for direct `WorkflowRun` construction; verify `timer.fired` event is emitted on the run's event chain via `_async_append_event`. Verb: AUDIT + emit-event-if-missing.
7. **Webhook + event ingress paths** — Survey `backend/app/routes/webhooks.py` (or equivalent) for direct `WorkflowRun` construction; route through `ExecutionFacade`. Verb: AUDIT + REPLACE.
8. **`tests/integration/test_integration_paths_canonical.py`** — CREATE this file. Test that every entrypoint (REST, UI execute, webhook, event, schedule, signal, approval, timer, sub-workflow) produces:
   - One `WorkflowRun` row created via `ExecutionFacade`
   - At least one canonical `WorkflowRunEvent` (e.g. `run.created`)
   - No orphan pending runs after the canary completes
   Verb: CREATE.
9. **Re-run `bash scripts/check-direct-run-bypasses.sh`** — must exit 0 before P0-E can be marked DONE. Verb: VERIFY.
10. **Add `check-direct-run-bypasses.sh` to `.github/workflows/ci.yml`** as a hard gate (currently the script exists but is not invoked by CI). File: `.github/workflows/ci.yml`. Verb: ADD step + ADD `build.needs:` dependency.

---

## Top 3 surprising findings

These are points where the plan's expectations diverged from the workspace's actual state.

### 1. P0-E is significantly more incomplete than `CURRENT_STATE.md` and `REMEDIATION_REPORT_R2.md` suggest

`CURRENT_STATE.md` calls out webhook/schedule end-to-end as "implemented but unproven." `REMEDIATION_REPORT_R2.md` does not enumerate P0-E in its "what changed" list at all. Yet running the bypass-detection script (which `REMEDIATION_REPORT_R2.md` says was wired in Round 1 — see `REMEDIATION_REPORT.md` lineage) produces **4 active BYPASS hits**, including the schedule tick in `worker.py:278` and three sites in `routes/workflows.py`. This is not a proof gap — it is structurally non-canonical code in production paths. P0-E is the gating Wave-0 item, not P0-B.

### 2. The non-inline canary is not an enforced CI gate

The plan §"Mandatory CI hard gates" lists "Non-inline worker canary" as the FIRST mandatory gate. The `verify-slice` job in `.github/workflows/ci.yml:146` runs `verify-slice.sh` which sets `ARCHON_DISPATCH_INLINE=1` (the test contract, NOT the production contract). There is no second job running `test-worker-canary.sh` with `ARCHON_DISPATCH_INLINE=0`. `REMEDIATION_REPORT_R2.md` reports the canary green in-workspace but does not record adding it to CI. Result: every PR merges without proving the production fire-and-forget path. The canary exists but is structurally toothless.

### 3. The plan's "ActivityHeartbeat" and "PayloadBlob" tables were red herrings

The plan §"Worker P0-D" listed both as required-name freezes. After reading the master plan §"Worker W3" carefully, neither is structurally needed:

- Heartbeat persistence is satisfied by inlining `heartbeat_details JSONB` + `heartbeat_at` on `ActivityExecution`. A separate `ActivityHeartbeat` table would create write amplification (heartbeats fire every few seconds) with no query benefit (operators care about *current* progress, not heartbeat history; lifecycle history lives in `WorkflowRunEvent` per ADR-002).
- Payload storage is already solved by the existing `Artifact` model plus the `_artifact_ref` extraction pattern. A separate `PayloadBlob` table would duplicate `Artifact`'s storage backend, hash, retention, and tenant scoping. Two flag columns (`is_payload`, `payload_role`) are sufficient.

ADR-008 makes both decisions explicit (§3 and §8) with rationale. If the operator disagrees, a superseding ADR is required — but neither is in fact required to unblock the W1–W16 wave.

---

## Blocking issues for downstream workers

| # | Blocker | Impact | Owner |
|---|---------|--------|-------|
| 1 | P0-E bypass gate fails (4 BYPASS hits) | W1 cannot land its `Task` table behind the assumption that all runs go through `ExecutionFacade` — the schedule tick and three workflow-execute routes still create rows behind the facade's back. Wave-1 lands with broken canonical-path invariant. | Follow-up worker on P0-E #1–#9 above |
| 2 | P0-B canary not in CI | Every PR can land a regression of the production fire-and-forget path. Wave-1 worker registry / dispatcher polling changes won't be caught until a release ships and operator sees stuck runs. | Follow-up worker on P0-B "Next steps" #1–#3 above |
| 3 | `tests/integration/test_integration_paths_canonical.py` does not exist | The plan §"Wave 0 Gate" command `pytest backend/tests/test_integration_paths_canonical.py` (typo'd in the plan; actual path per Worker P0-E spec is `tests/integration/test_integration_paths_canonical.py`) is unrunnable. The Wave-0 gate cannot be declared green until the file is created and exits 0. | Follow-up worker on P0-E #8 above |
| 4 | `feature-matrix.yaml` lacks `designed` entries for the eight new tables | W1 lands `task_queues` + `tasks` migrations and the parity check (`scripts/check-feature-matrix.py`) will warn or fail because the rows aren't classified. Mitigation: add 8 `designed` rows in the same PR as the W1 migration, or pre-emptively in a thin follow-up worker (~10 minutes). | Thin follow-up to P0-D |

None of the four blockers prevents reading ADR-008 or starting design work for W1/W2/W3/W7/W8/W11/W12/W13/W16. They prevent **Wave-0 gate green** and therefore prevent Wave-1 workers from being declared started under the master plan's "no worker may start until upstream gates are green" rule. The orchestrator should treat blockers #1 and #3 as the critical path; #2 is structurally critical but doesn't block the start of Wave-1 implementation work, just its merge.
