# Archon Implementation Orchestration Plan

**Date:** 2026-04-28
**Authority:** Derived from `RE_EVALUATION_REPORT.md` (read it first)
**Model assignment:** All implementation agents on Sonnet 4.6 (cost-effective for focused implementation; Opus reserved for synthesis/judgment).

## Purpose

Land the enterprise workflow orchestration capability in one cycle. Not 50 connectors. Not 200 node types. **Real workflows that execute, persist, recover, and report — proven by `make test-slice`**.

## Operating principles (mandatory for all implementation agents)

1. **No overclaim.** "Done" means tests pass + the behavior observable end-to-end. Documentation that says complete without test evidence will be rejected by the verification swarm.
2. **Minimal coherent change.** Do not refactor adjacent code unless your scope requires it.
3. **Preserve existing tests.** If your change breaks tests outside your scope, stop and report.
4. **Add tests for new behavior.** Every new code path needs a real test, not a mock-paste.
5. **Stay in your lane.** File ownership is exclusive. If a file is needed by two missions, the upstream mission produces an interface; the downstream mission consumes it.
6. **Report blockers, don't bypass them.** If your scope requires a downstream change that's another agent's lane, document the dependency and stop. Do not patch around it.
7. **No new framework installs.** No `.sdd`, no `.claude-flow`, no `.swarm`. Code only.

## Definition of done (entire cycle)

Verifiable by re-running this skill:

- `make verify` runs and passes (lint + typecheck + tests).
- `make test-slice` runs and passes — POST /agents (with a real OpenAI/Anthropic key in env), POST /executions, observe a real LLM completion in the response.
- `pytest tests/ backend/tests/ gateway/tests/` — green except known QRG-hardcoded tests in `test_azure_wiring/` (skip those with marker; track in a known-failures registry).
- `database.py` no longer wipes data on restart; Alembic migrations are the source of truth.
- A FastAPI restart mid-execution does NOT lose the workflow run (PostgresSaver checkpoint test passes).
- Scheduled runs created by the worker are picked up and executed within 60s.
- The visual builder's drawn nodes (Loop, Condition, Parallel-mode, HumanApproval, DLPScan, CostGate) execute with backend semantics matching what the canvas displays.
- Cost dashboard shows real token usage from a live execution.
- Prometheus alerts use metric names the backend actually emits.
- README claims match reality (connector count, node count, framework list).
- Misleading completion docs are archived to `docs/_archive/`.

---

## Agent missions

### WAVE 1 — Foundation (parallel; no inter-dependencies)

#### A1: DB Durability + Alembic Truth

**Owner files (exclusive write):**
- `backend/app/database.py`
- `backend/app/main.py` (only the startup hook section)
- `backend/alembic/env.py`
- `backend/alembic/versions/` (new migration files)
- `Makefile` (only adding `db-reset`, `migrate-up`, `migrate-down` targets)

**Mission:**
1. Remove `SQLModel.metadata.drop_all` and `create_all` from startup. The startup hook becomes a no-op for schema (or runs `alembic upgrade head` if `ARCHON_AUTO_MIGRATE=true`, default off).
2. Fix `alembic/env.py` to import every SQLModel from `backend/app/models/` so autogenerate sees the real schema.
3. Generate one consolidated migration that brings a fresh DB to the current model schema (squash drift; do not delete prior migrations — chain after them).
4. Add `make db-reset` target — explicit destructive reset (drop + create). Loud warning. Refuses to run if `ARCHON_ENV=production`.
5. Add `make migrate-up` and `make migrate-down`.

**Acceptance:**
- `python -c "from backend.app.database import init_db; import asyncio; asyncio.run(init_db())"` runs WITHOUT dropping tables (verify via inspecting that data inserted before init_db survives a second init_db call — write a test).
- `alembic check` (or equivalent) shows no schema drift between models and migration head.
- `make db-reset` works and prints a destructive-action warning.
- `tests/test_db_durability.py` (new) — insert a row, call `init_db()` again, assert row still exists.

---

#### A2: Real LLM Nodes via LiteLLM

**Owner files (exclusive write):**
- `backend/app/langgraph/nodes.py`
- `backend/app/langgraph/llm.py` (new — LiteLLM wrapper)
- `backend/app/langgraph/__init__.py` (exports only)
- `backend/tests/test_llm_node.py` (new)

**Read-only (for context):**
- `backend/app/services/router_service.py` (use the scoring engine if available; otherwise a default model)
- `backend/app/secrets/manager.py` (resolve API keys via `get_secret(provider)`)

**Mission:**
1. Add `backend/app/langgraph/llm.py` with `async def call_llm(prompt: str, model: str, **opts) -> LLMResponse`. Use `litellm.acompletion`. `LLMResponse` has `content`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd`, `model_used`, `latency_ms`.
2. `LLMResponse.cost_usd` MUST be calculated using LiteLLM's `completion_cost(response)` helper if available, otherwise return `None` (caller will look up rate card).
3. Replace `process_node` in `nodes.py` with a real LLM call. Read `state["agent_definition"]["system_prompt"]` and `state["input"]` (or messages). Call `call_llm`.
4. `respond_node` packages the LLM response + token usage into the workflow output state.
5. Resolve API keys via the secrets manager. Fall back to env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) if Vault unreachable.
6. Add timeout (default 60s, configurable per agent definition) and retry (default 2 retries, exponential backoff).
7. **Stub mode:** if `LLM_STUB_MODE=true` in env, `call_llm` returns a deterministic fake response (`"[STUB] echoed: {prompt[:100]}"`) so unit tests don't need API keys. Default false.

**Acceptance:**
- `LLM_STUB_MODE=true python -m pytest backend/tests/test_llm_node.py` passes (no API keys needed).
- With `OPENAI_API_KEY` set: `python -c "import asyncio; from backend.app.langgraph.llm import call_llm; r = asyncio.run(call_llm('Say hi', 'gpt-3.5-turbo')); print(r.content, r.total_tokens, r.cost_usd)"` produces a real completion.
- `process_node` no longer returns `f"Processed: {content}"` — verified by reading the code post-change.

---

#### A3: LangGraph PostgresSaver Checkpointing

**Owner files (exclusive write):**
- `backend/app/langgraph/engine.py`
- `backend/app/langgraph/checkpointer.py` (new)
- `backend/tests/test_checkpoint_recovery.py` (new)

**Read-only:**
- `backend/app/database.py` (already-existing engine for connection)

**Mission:**
1. Add `checkpointer.py` with `get_checkpointer()` returning a configured `langgraph.checkpoint.postgres.PostgresSaver` connected to the same DSN as the main app. Run its `setup()` migration on first call (idempotent).
2. Update `create_graph()` in `engine.py` to call `compile(checkpointer=get_checkpointer())`.
3. Each `execute_agent` invocation passes a `thread_id` (from the `WorkflowRunStep` UUID) so checkpoints are addressable.
4. Add `resume_agent(thread_id)` that re-invokes the graph with the existing checkpoint — used by the pending-run consumer (Wave 2) for restart recovery.
5. Document the upgrade path: existing executions without checkpoints continue to work (legacy compile if `LANGGRAPH_CHECKPOINTING=false`).

**Acceptance:**
- New test: kick off a long-running graph (sleep 5s in a node), kill the executor task mid-run, call `resume_agent(thread_id)`, assert the run completes from checkpoint not from scratch.
- Existing `test_langgraph.py` still passes (regression).

---

#### A4: Documentation Truth + README Reality

**Owner files (exclusive write):**
- `README.md`
- `docs/_archive/` (new directory; many files moved here)
- `COMPLETION_SUMMARY.txt`, `FINAL_REPORT.md`, `FIXES_SUMMARY.txt`, `CRITICAL_STUBS_FIXED.md`, `WIZARD_TEMPLATES_EXAMPLES.md`, `VERIFICATION_CHECKLIST.md`, `DOCUMENTATION_INDEX.md`, `docs/FINAL_SUMMARY.md`, `docs/HEALTH_REPORT.md`, `docs/INTEGRATION_TEST_REPORT.md` (move to archive)

**Mission:**
1. `mkdir -p docs/_archive`. Move the listed misleading completion docs there. Add `docs/_archive/README.md` explaining: "Historical agent self-reports superseded by `/RE_EVALUATION_REPORT.md` (2026-04-28). Retained for git history only — do NOT treat as authoritative."
2. Update root `README.md`:
   - "27+ node types" → "27 node types in the visual builder (full backend semantic coverage in progress; see ROADMAP)"
   - "50+ data connectors" → "5 production connectors today (PostgreSQL, S3, Slack, REST, Google Drive); connector framework supports operator-authored extensions"
   - "shadcn/ui" → "Tailwind + custom UI components (shadcn-compatible API)"
   - Remove "OpenLLMetry" reference
   - Remove "NeMo Guardrails" until integrated
   - "LangGraph state machines · 17 specialized agents" → "LangGraph state-machine engine; agent definitions are user-authored via the visual builder"
   - "LiteLLM" → keep, but only after Wave 1.A2 lands (verify by checking `import litellm` exists in the codebase)
   - Add a "Status" section: "Pre-1.0 — orchestration core complete, advertised connector catalog is operator-extensible (5 reference impls)"
3. **Do not** update `ROADMAP.md` checkboxes. Verification swarm checks ROADMAP separately.
4. **Do not** delete files; only move.

**Acceptance:**
- `git log --diff-filter=R --name-only` shows the archive moves.
- README claims spot-check: `grep -E "50\+|27\+|shadcn|OpenLLMetry|NeMo" README.md` returns nothing.
- `docs/_archive/README.md` exists and is clear.

---

#### A5: Production Bug Fixes (Surgical)

**Owner files (exclusive write):** Only the specific files containing the named bugs:
- `backend/app/routes/sentinelscan.py` (`NameError: timezone`)
- `backend/app/services/mcp_service.py` (`test_mcp_service.py:514` datetime naive vs aware)
- Any other file producing the 4 datetime errors documented by Agent #6 (research)

**Mission:**
1. Reproduce each failure with `pytest <file>::<test>` first. Document the root cause inline in commit message.
2. Fix the timezone-naive vs aware comparisons by ensuring all `datetime.utcnow()` are replaced with `datetime.now(timezone.utc)`. Add `from datetime import timezone` where needed.
3. Fix the `NameError: timezone` in sentinelscan route by adding the import.
4. Re-run the previously-failing tests; assert green.

**Acceptance:**
- `pytest tests/test_mcp_service.py::TestUpdateComponent::test_update_component_sets_updated_at` passes.
- `pytest tests/test_sentinelscan` (or wherever the NameError fires) passes.
- No new test additions required for this mission (these were caught by existing tests).

---

### WAVE 2 — Wiring (depends on Wave 1; agents in this wave are mostly parallel among themselves)

#### A6: REST → Real Executor Wiring

**Depends on:** A2 (LLM nodes), A3 (checkpointer)
**Owner files (exclusive write):**
- `backend/app/routes/executions.py`
- `backend/app/services/workflow_engine.py` (extend; do not rewrite — A7 also touches this; coordinate via A7's interface)
- `backend/tests/test_executions_real.py` (new)

**Read-only:**
- `backend/app/services/execution_service.py` (call its persistence methods, don't modify)
- `backend/app/models/workflow.py`
- `backend/app/models/execution.py`

**Mission:**
1. Delete `_simulate_execution` from `routes/executions.py` (and any callers).
2. `POST /api/v1/executions` and `POST /api/v1/agents/{id}/execute` must:
   - Validate the agent_id / workflow_id exists and tenant_id matches the JWT.
   - Create an `Execution` row at `status="running"`.
   - For agent-only execution: call `execute_agent(agent_id, definition, input, thread_id=execution_id)` (uses A2's real LLM via A3's checkpointer).
   - For workflow execution: call `execute_workflow_dag(workflow_id, definition, input, run_id=execution_id)`.
   - Stream WebSocket events to `/ws/executions/{execution_id}` channel as steps complete.
3. The endpoint returns immediately with `{"execution_id": "..."}` for long-running. The actual execution is in the background via `asyncio.create_task` OR a queue write that the worker picks up (Wave 2.A8 builds the consumer; for now, `asyncio.create_task` is acceptable — A8 will replace it).
4. Cancellation endpoint `POST /api/v1/executions/{id}/cancel` writes a `WorkflowRun.cancel_requested = true` flag; the executor checks this between steps and exits cleanly.
5. **Do NOT** modify `_simulate_failure` random in `execution_service.py`; that's A9's job.

**Acceptance:**
- `make test-slice` (defined by A12) calls `POST /executions` and gets a real LLM completion back.
- New test `test_executions_real.py::test_real_execution` posts an agent definition with a real LLM stub (uses `LLM_STUB_MODE=true`) and asserts the response includes the stub completion plus token counts.
- `grep -r "_simulate_execution" backend/app/` returns nothing.
- `grep -r "random.random() < 0.1" backend/app/services/` returns nothing (delete that line in execution_service if A6 owns the cleanup; otherwise A9 does).

---

#### A7: Node-Type Interpreter (the big one)

**Depends on:** A2 (LLM call), A3 (checkpointer)
**Owner files (exclusive write):**
- `backend/app/services/workflow_engine.py` (dispatch logic — coordinate with A6 via interface)
- `backend/app/services/node_executors/` (new directory)
- `backend/app/services/node_executors/__init__.py` (registry)
- `backend/app/services/node_executors/llm.py`
- `backend/app/services/node_executors/condition.py`
- `backend/app/services/node_executors/switch.py`
- `backend/app/services/node_executors/parallel.py` (handles `executionMode: all|any|n_of_m`)
- `backend/app/services/node_executors/loop.py`
- `backend/app/services/node_executors/human_approval.py` (creates pending-approval row, pauses run via checkpoint)
- `backend/app/services/node_executors/dlp_scan.py` (calls `dlp_service.scan_content`)
- `backend/app/services/node_executors/cost_gate.py` (checks tenant budget, fails run if over)
- `backend/app/services/node_executors/sub_workflow.py` (recursive call to `execute_workflow_dag`)
- `backend/app/services/node_executors/sub_agent.py` (call another agent_id by reference)
- `backend/app/services/node_executors/http_request.py`
- `backend/app/services/node_executors/database_query.py` (uses connector framework)
- `backend/app/services/node_executors/delay.py`
- `backend/app/services/node_executors/merge.py`
- `backend/app/services/node_executors/webhook_trigger.py`, `schedule_trigger.py` (trigger nodes — no-op at execution time; metadata-only at registration time)
- `backend/app/services/node_executors/input.py`, `output.py`, `function_call.py`, `tool.py`, `mcp_tool.py`, `embedding.py`, `vision.py`, `structured_output.py`, `vector_search.py`, `document_loader.py`, `human_input.py`, `stream_output.py`
- `backend/tests/test_node_executors/` (new — one test file per node executor)

**Read-only:**
- `frontend/src/types/nodeTypes.ts` (the canonical 27 types — match these names)
- `frontend/src/components/canvas/nodes/*.tsx` (read for shape of `data` per node type)

**Mission:**
1. Build a registry: `NODE_EXECUTORS: dict[str, NodeExecutor] = {...}`. Each executor has `async def execute(self, ctx: NodeContext) -> NodeResult` where `NodeContext` carries: `step_id`, `node_data` (from JSON), `inputs` (from upstream nodes), `tenant_id`, `secrets`, `db_session`, `cancel_check`.
2. For each of the 27 node types, implement the executor. Many are thin (input/output/delay/merge); a few are substantive (loop, parallel, human_approval, sub_workflow).
3. **Critical semantics:**
   - `parallel` with `executionMode=all` → wait for all branches; `any` → first wins; `n_of_m` → wait for N of M.
   - `loop` → re-execute body until condition met or `maxIterations` hit.
   - `condition` / `switch` → evaluate Python expression on inputs (use a sandboxed evaluator — `simpleeval` or `asteval`), branch.
   - `human_approval` → write pending-approval row to DB, suspend the LangGraph thread (return special `PAUSED` result; the run resumes when approval endpoint is called).
   - `dlp_scan` → call `dlp_service.scan_content` on inputs; if any high-severity match and `actionOnViolation=block`, abort the run.
   - `cost_gate` → query `cost_records` for tenant's running total; if over `maxUsd`, abort.
   - `retryPolicy` (a property on every node) → wrap the executor in `tenacity.retry` with the per-node policy.
4. `workflow_engine.py` reads each step's `node_type` (or `type`) and dispatches to `NODE_EXECUTORS[type]`. Falls back to legacy `execute_agent` only when type is missing (backward compat).
5. Each executor MUST: persist its own `WorkflowRunStep` row with status, input, output, duration. Emit a WebSocket event.

**Acceptance:**
- One unit test per executor in `backend/tests/test_node_executors/`. Each test runs the executor in isolation with a mocked context and asserts behavior.
- One integration test: a workflow with `parallel` (mode=all) + `condition` + `dlp_scan` + `human_approval` runs end-to-end (the human_approval step pauses; a subsequent approve endpoint call resumes; the workflow completes).
- `grep -r "execute_agent(" backend/app/services/workflow_engine.py` shows the legacy path is fenced behind a backward-compat check, not the default.
- 27 executor files exist in `backend/app/services/node_executors/`.

---

#### A8: Pending Run Consumer

**Depends on:** A6 (executor entry point)
**Owner files (exclusive write):**
- `backend/app/worker.py` (extend)
- `backend/app/services/run_dispatcher.py` (new)
- `backend/tests/test_run_dispatcher.py` (new)

**Mission:**
1. Add a new task to the worker loop: `_drain_pending_runs()`. Every 5 seconds:
   - `SELECT * FROM workflow_runs WHERE status='pending' ORDER BY created_at LIMIT 10` (configurable).
   - For each row: lock optimistically (`UPDATE ... SET status='running' WHERE id=? AND status='pending'`); if rowcount=1, dispatch.
   - Dispatch via `asyncio.create_task(execute_workflow_dag(...))`. Track active tasks; cap concurrency at 50 per worker (configurable via `ARCHON_MAX_CONCURRENT_RUNS`).
2. Extract a small `run_dispatcher.py` module with `dispatch_run(run_id)` so both the REST endpoint (A6) and the worker can use the same path.
3. Add `make worker` target that runs the worker as a foreground process for dev; `make worker-bg` for daemon.
4. Schedule trigger and webhook trigger continue creating `pending` rows; the consumer drains them.
5. Distributed lock (optional but encouraged): use `redis.set("dispatcher_lock", ttl=60, nx=True)` so only one worker picks up runs at a time when scaled.

**Acceptance:**
- Test: insert a `WorkflowRun(status="pending")` directly into DB, run `_drain_pending_runs()` once, assert the run transitions to `completed` (with the LLM stub) and the row is updated.
- Test: schedule a workflow with `cron_expression="* * * * *"`, advance time (or set `next_run_at` to past), run worker tick, assert the run executed.
- Webhook test: `POST /workflows/{id}/webhook` creates pending; consumer picks it up; run completes.

---

### WAVE 3 — Observability & Cost (depends on Wave 2; mostly parallel)

#### A9: Real Cost Tracking

**Depends on:** A2 (LiteLLM token data)
**Owner files (exclusive write):**
- `backend/app/services/cost_service.py`
- `backend/app/services/execution_service.py` (only the cost section; coordinate with A6)
- `backend/app/models/cost.py` (extend if needed)
- `backend/tests/test_cost_real.py` (new)

**Mission:**
1. Replace `_generate_mock_steps()` in `execution_service.py`. Cost rows are created by the LLM node executor (A2) emitting `LLMResponse.cost_usd` and `total_tokens`.
2. `cost_service.record_usage(tenant_id, execution_id, step_id, model, prompt_tokens, completion_tokens, cost_usd)` writes a `CostRecord`.
3. `cost_service.tenant_running_total(tenant_id, since: datetime) -> Decimal` — used by `cost_gate` node executor (A7).
4. `GET /api/v1/cost/summary` returns: per-tenant total today/week/month, top 5 agents by cost, top 5 models by cost. No mock data.
5. Rate card lookup: when LiteLLM doesn't return `cost_usd`, look up in `model_rate_cards` table (seed with current OpenAI/Anthropic/Azure rates from `azure_models_seed.json`).
6. Delete `random.random() < 0.1` simulation in `execution_service.py:256`.

**Acceptance:**
- New test runs a real LLM stub execution, asserts `cost_records` row created with non-zero `cost_usd`.
- `GET /api/v1/cost/summary` returns data from real `cost_records`, not mocks.
- `grep -r "random.randint" backend/app/services/execution_service.py` returns nothing.

---

#### A10: Metric Name Alignment

**Owner files (exclusive write):**
- `backend/app/middleware/metrics_middleware.py`
- `infra/grafana/dashboards/cost-dashboard.json`
- `infra/grafana/dashboards/platform-overview.json`
- `infra/grafana/dashboards/security-dashboard.json`
- `infra/monitoring/prometheus-values.yaml`

**Mission:**
1. Decide canonical naming: prefix all backend-emitted metrics with `archon_`. Update Grafana dashboards and Prometheus alerts to use these names.
2. Add metric emission for: `archon_token_usage_total{tenant_id, model, kind="prompt|completion"}`, `archon_cost_total{tenant_id, model}`, `archon_workflow_runs_total{status}`, `archon_workflow_run_duration_seconds`. Emit these from the cost service (A9) and workflow engine (A7).
3. Update `prometheus-values.yaml` alerts: `http_requests_total` → `archon_requests_total`, `http_request_duration_seconds_bucket` → `archon_request_duration_seconds_bucket`.
4. Update Grafana JSON: cost dashboard panels query the new metric names; platform overview queries `archon_requests_total`; security dashboard queries `archon_dlp_findings_total` (add this metric to DLP service).

**Acceptance:**
- `grep -r "http_requests_total" infra/` returns nothing.
- `grep -r "archon_token_usage_total" backend/app/middleware/metrics_middleware.py` returns the metric definition.
- `curl localhost:8000/metrics` (mock test if possible) shows `archon_token_usage_total`, `archon_cost_total`, `archon_workflow_runs_total`.
- Grafana JSON validated by `jq` (no syntax errors).

---

#### A11: In-Memory State → Persistent State

**Owner files (exclusive write):**
- `gateway/app/guardrails/middleware.py` (rate limiter)
- `backend/app/routes/sso.py` (SSO config)
- `backend/app/routes/router.py` (only the `_visual_rules_store` lines)
- `backend/app/models/sso_config.py` (new model)
- `backend/app/models/visual_rule.py` (new model)
- `backend/alembic/versions/` (new migration — coordinate with A1)

**Mission:**
1. Rate limiter: replace `dict[str, list[float]]` with Redis sorted set per user. Use `ZADD` for window entries; `ZREMRANGEBYSCORE` to expire; `ZCOUNT` to check current window. Connect via existing Redis client.
2. SSO config: replace `_sso_config = SSOConfigData()` with a `sso_configs` table (one row per tenant). CRUD endpoints persist to DB.
3. Visual rules: replace `_visual_rules_store: list[dict]` with a `visual_rules` table. CRUD endpoints persist.
4. Tenant cache (`middleware/tenant.py`): keep the in-memory dict but add Redis as L2 with 5-minute TTL.
5. Each migration squash with A1's; ensure idempotent.

**Acceptance:**
- Restart the FastAPI process; SSO config and visual rules persist.
- Two horizontally-scaled FastAPI replicas share rate-limit state (manual test with `httpie` against two ports if dev compose is running; otherwise unit test against in-memory Redis fake).

---

### WAVE 4 — Verification + UX (parallel; depends on Wave 2)

#### A12: `make verify` + `make test-slice`

**Owner files (exclusive write):**
- `Makefile` (only the `verify`, `test-slice`, `slice-up` targets)
- `scripts/verify.sh` (new)
- `scripts/test-slice.sh` (new)
- `tests/integration/test_vertical_slice.py` (new)

**Mission:**
1. `make verify`: runs `ruff check`, `pyright backend gateway` (or `mypy --strict`), `pytest backend/tests/ tests/integration/ gateway/tests/ -x -q`, `cd frontend && npm run typecheck && npm run lint`. Fails on any non-zero exit.
2. `make test-slice`: assumes `make dev-up` (postgres+redis+backend up) ran. Runs `pytest tests/integration/test_vertical_slice.py -v`.
3. The vertical slice test:
   - Authenticate (dev mode JWT).
   - `POST /api/v1/agents/` with a 2-node agent (input → llm → output).
   - `POST /api/v1/agents/{id}/execute` with `LLM_STUB_MODE=true` so no real API key needed.
   - Poll `GET /api/v1/executions/{id}` until status terminal.
   - Assert: status=completed, response contains the stub completion content, `cost_records` row exists, audit log row exists.
4. `make verify` exits 0 on success; the verification swarm runs this as the gate.

**Acceptance:**
- `make verify` runs without error in a fresh container with `LLM_STUB_MODE=true`.
- `make test-slice` runs and the `tests/integration/test_vertical_slice.py` test passes.
- ROADMAP Phase 0 Milestone 0.5 references `make verify` — coordinate with A4 to update README to reference these.

---

#### A13: Builder Live Stream (Frontend)

**Owner files (exclusive write):**
- `frontend/src/components/canvas/TestRunPanel.tsx` (or wherever the Run button lives)
- `frontend/src/api/executions.ts` (only the WebSocket connection helper)
- `frontend/src/tests/TestRunPanel.test.tsx` (new)

**Mission:**
1. After `runAgent` returns the `runId`, immediately call `connectExecutionWebSocket(runId, callbacks)`.
2. Render incoming `step.started`, `step.completed`, `step.failed`, `execution.completed` events in the panel as a timeline. Show partial output as it streams.
3. Display total tokens and cost when the execution completes.
4. Cancel button calls `POST /api/v1/executions/{id}/cancel`.

**Acceptance:**
- New Vitest unit test mocks the WebSocket and verifies events render in order.
- Manual test: drag a 2-node agent (input → llm → output), Test Run, observe live timeline updating.
- `npm run typecheck` clean.

---

#### A14: Register Orphaned Routers + Module Duplicate Decision

**Owner files (exclusive write):**
- `backend/app/main.py` (only the router registration block)
- `backend/app/services/router.py`, `backend/app/services/edge.py`, `backend/app/services/governance.py`, `backend/app/services/lifecycle.py`, `backend/app/services/marketplace.py`, `backend/app/services/mesh.py` (delete these v1 files; keep `_service.py` versions)
- Any router that was importing the v1 versions (update import to `_service`)

**Mission:**
1. For each duplicated v1/v2 service pair, confirm `*_service.py` is the active version (per the Agent #2 finding). Delete the v1 file. Update any importers.
2. Register all currently-orphaned routers in `main.py`: SentinelScan, connector test/health, model router provider management. If the underlying functionality isn't ready, the route should return `503 Service Unavailable` with a clear message — but it must NOT 404.
3. List all orphaned routers in a comment block at the top of `main.py` for visibility.

**Acceptance:**
- `grep -E "router_service|router\.py" backend/app/services/` shows only the `*_service.py` files remain (for each duplicated pair).
- `curl localhost:8000/api/v1/sentinelscan/services` (against running dev) returns 200 OK or 503 (not 404).
- `make verify` passes after the cleanup.

---

## Wave dependencies graph

```
Wave 1 (parallel):
  A1 (DB) ──┐
  A2 (LLM) ─┤
  A3 (Ckpt)─┤   (A3 reads A1's DB; can start once A1 has merged migration plan)
  A4 (Docs) ─┤
  A5 (Bugs) ─┘

Wave 2 (parallel):
  A6 (REST→Exec) ── needs A2, A3
  A7 (Node Interp) ── needs A2, A3
  A8 (Consumer) ── needs A6 (run_dispatcher import)

Wave 3 (parallel after Wave 2):
  A9 (Cost) ── needs A2 LLMResponse, A6 to call cost_service
  A10 (Metrics) ── needs A9 to emit metrics
  A11 (Persistent State) ── needs A1 migration

Wave 4 (parallel after Wave 2):
  A12 (Verify) ── needs A6 for slice test
  A13 (Builder Stream) ── needs A6 WebSocket events
  A14 (Routers + Dupes) ── independent
```

## Execution policy

- Each agent works in isolation on its declared file ownership. Touching another agent's owned file is a violation; report blocker instead.
- After each wave completes, run `make verify` (once A12 lands; before that, run the relevant pytest subset).
- After ALL waves complete, re-run `/re-evaluation-plan` (Phase D). The verification swarm checks every claim in this plan against actual code/tests.

---

## Reporting format (every implementation agent must return this)

```markdown
## Mission: {agent-id}

### Files written
- path:lines (created|modified|deleted) — purpose

### Behavior added
- description (with file:line where the new behavior lives)

### Tests added/modified
- test path: assertions made

### Tests run
- command: result (pass/fail with counts)

### Acceptance criteria check
- [✓|✗] criterion 1 — evidence
- [✓|✗] criterion 2 — evidence
...

### Remaining gaps
- description (what wasn't done; reason)

### Blockers encountered
- description + which agent's lane / what's needed to unblock
```

---

*Plan author: Opus 4.7 (synthesis)*
*Implementation agents: Sonnet 4.6 (focused, narrow scope, file-owned)*
*Verification: re-run /re-evaluation-plan post-implementation*
