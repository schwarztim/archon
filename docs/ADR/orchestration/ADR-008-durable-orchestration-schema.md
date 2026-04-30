# ADR-008: Durable Orchestration Schema Freeze

- **Status:** ACCEPTED
- **Namespace:** orchestration
- **Date:** 2026-04-30
- **Supersedes:** none
- **Superseded by:** none
- **Depends on:** ADR-001 (unified run model), ADR-002 (event ownership + hash chain), ADR-003 (hint envelope), ADR-004 (idempotency contract), ADR-005 (production durability policy), ADR-006 (execution migration), ADR-007 (workflow deletion semantics)

## Context

ADRs 001–007 froze the unified run model, the hash-chained event log, the
hint envelope, the idempotency contract, the durability policy, the
migration cutover, and the deletion semantics. They are sufficient to
ship the inline-dispatch slice and the non-inline worker canary, both of
which are green per `CURRENT_STATE.md` and `REMEDIATION_REPORT_R2.md`.

They are not sufficient to ship the next wave of capabilities the master
plan requires: named task queues with rate limits and concurrency caps;
worker registries with capability sets and lease leasing; first-class
activity executions with attempts, heartbeats, and idempotency keys;
inbound/outbound CI/CD pipeline correlation with provider-event idempotency
and signed callbacks; workflow definition versioning with worker
compatibility sets; continue-as-new run chains; visibility/search indexes;
schedules with overlap policy and catchup; and large-payload references
that keep the event history compact.

The master plan (Wave 1 onwards) splits this work across W1, W2, W1.5,
W7, W8, W11, W12, W13, and W16. Each of those workers must agree on
table names, column names, foreign keys, indexes, and partial-unique
constraints **before they start** so they can implement in parallel
without contract renegotiation. Without that freeze, two workers will
write incompatible columns and one will lose a week unwinding the merge.

This ADR is that freeze. It does not implement anything — W1 owns the
migrations, W2 owns the worker registry behaviour, etc. It only fixes
the names, types, FKs, and indexes that downstream workers commit to.

## Decision

The following nine schema units are accepted, named, and locked. Any
change to a column name, type, FK, or index in this ADR after acceptance
requires a new ADR superseding 008.

All datetimes are stored as `TIMESTAMP WITHOUT TIME ZONE` and treated as
UTC at the application layer (consistent with `_utcnow()` in
`models/workflow.py` line 15). All primary keys are `UUID` produced by
`uuid4`. All `tenant_id` columns are `UUID | None` matching
`WorkflowRun.tenant_id` (`models/workflow.py` line 125).

Migration ordering is fixed:

1. `WorkflowDefinitionVersion`
2. `TaskQueue`
3. `Task`
4. `ActivityExecution`
5. `PipelineCorrelation`
6. `RunChain`
7. `VisibilityIndex`
8. `Schedule` (extension of existing `WorkflowSchedule` plus a new
   `Schedule` table for non-cron / multi-action schedules, see §9)

`PayloadBlob`-style storage is **not** introduced as a new table; large
payloads are stored as artifacts via the existing `Artifact` model with
two new flag columns (see §8 for justification).

## §1 — `TaskQueue`

Named queue used to route work to workers with matching capabilities.
Owned by W1.

```text
TaskQueue
- id                    UUID, PK, default uuid4
- tenant_id             UUID | None, indexed
- name                  str, NOT NULL
- queue_type            str, NOT NULL, default "activity"
                        (one of: "activity", "workflow", "system")
- description           Text, NOT NULL, default ""
- max_dispatch_rate     int | None     -- per-second token-bucket cap
- concurrency_limit     int | None     -- max in-flight tasks
- retention_days        int, NOT NULL, default 30
- paused                bool, NOT NULL, default false
- created_at            datetime, NOT NULL, default _utcnow
- updated_at            datetime, NOT NULL, default _utcnow

Constraints:
- UniqueConstraint("tenant_id", "name", name="uq_task_queues_tenant_name")
  -- a queue name is unique within a tenant; the same name may exist in
     another tenant. NULL tenant_id is the platform-default queue scope.

Indexes:
- ix_task_queues_tenant_id_paused (tenant_id, paused)
  -- the dispatcher polls for non-paused queues per tenant
```

Rationale: `(tenant_id, name)` matches the `Workflow.name` per-tenant
uniqueness convention (`models/workflow.py` line 41) and lets the
dispatcher index polls by tenant first.

## §2 — `Task`

A single unit of dispatchable work in a queue. Owned by W1, polled by
the dispatcher (W1.5), claimed by workers (W2). Every node activation
that reaches a worker is a `Task` row; the existing `WorkflowRunStep` is
the result of executing one or more attempts of a `Task`.

```text
Task
- id                    UUID, PK, default uuid4
- tenant_id             UUID | None, indexed
- run_id                UUID, FK("workflow_runs.id", ondelete="CASCADE"), indexed, NOT NULL
- step_id               str | None        -- node identifier within the workflow
- queue_name            str, NOT NULL
- task_type             str, NOT NULL     -- "activity" | "workflow_step" | "timer_fire" | "schedule_fire"
- payload_ref           str | None        -- artifact_id (UUID as str) when payload was extracted
                                             via the payload codec; NULL means inline payload below
- payload_inline        JSON | None       -- small payloads (≤ codec threshold) stored inline
- status                str, NOT NULL, default "pending"
                        (one of: "pending", "visible", "claimed", "completed", "failed", "cancelled")
- visible_at            datetime, NOT NULL, default _utcnow
                        -- earliest moment a worker may claim; supports timer/delay
- attempts              int, NOT NULL, default 0
- max_attempts          int, NOT NULL, default 3
- lease_owner           str | None        -- worker_id holding the claim
- lease_expiration      datetime | None   -- claim expiry; reclaimed by janitor after this
- priority              int, NOT NULL, default 0     -- higher = sooner (signed for future deboost)
- idempotency_key       str | None        -- per-tenant deduplication key
- correlation_id        str | None, indexed
- created_at            datetime, NOT NULL, default _utcnow
- updated_at            datetime, NOT NULL, default _utcnow

Constraints:
- Index(
      "uq_tasks_tenant_idem",
      "tenant_id", "idempotency_key",
      unique=True,
      sqlite_where=text("idempotency_key IS NOT NULL"),
      postgresql_where=text("idempotency_key IS NOT NULL"),
  )
  -- partial unique index, identical pattern to ADR-004's
     uq_workflow_runs_tenant_idem on WorkflowRun. Portable across
     SQLite ≥ 3.8 and Postgres ≥ 9.0.
- CheckConstraint("status IN ('pending','visible','claimed','completed','failed','cancelled')",
                  name="ck_tasks_status")
- CheckConstraint("attempts >= 0", name="ck_tasks_attempts_nonneg")

Indexes:
- ix_tasks_dispatch_poll
      (tenant_id, queue_name, status, visible_at, priority)
  -- the canonical polling index; the dispatcher's
     select_pending_tasks(tenant_id, queue_names, limit)
     query (W1.5 task) hits this exactly.
- ix_tasks_run_id (run_id)
  -- joins back to workflow_runs / workflow_run_steps
- ix_tasks_lease_owner_expiration (lease_owner, lease_expiration)
  -- janitor scan for expired leases
- ix_tasks_correlation_id (correlation_id)
```

`payload_ref` matches the existing `_artifact_ref` pattern used by the
artifact extraction path (`models/artifact.py` notes lines 5–8). When
`payload_ref` is non-NULL, `payload_inline` MUST be NULL; when
`payload_inline` is set, `payload_ref` MUST be NULL. This invariant is
enforced at the application layer rather than by a CHECK constraint
because SQLite's CHECK does not see JSON contents portably.

`task_type` is open-enum at the schema level; the dispatcher rejects
unknown types. `timer_fire` and `schedule_fire` task types are produced
by `timer_service` and `schedule_service` respectively (see §9 and
ADR-005's pause/resume hooks).

## §3 — `ActivityExecution`

One row per attempt of an activity. The dispatcher inserts the row when
a worker claims a Task; updates it through the lifecycle; and persists
the final outcome before writing the corresponding `WorkflowRunStep` row.
Owned by W3 (activity runtime).

**Decision: heartbeat details are inline JSONB on `ActivityExecution`,
not a separate `ActivityHeartbeat` table.**

Rationale:

1. The plan §P0-D listed `ActivityHeartbeat` as a candidate but the
   master plan §"Worker W3" only specifies "Persist heartbeat details
   for long-running activities" and "Restore heartbeat details on
   retry/resume." Both behaviours are satisfied by overwriting a single
   JSONB column on the live attempt row.
2. A separate table would require either (a) a row per heartbeat (write
   amplification — heartbeats fire every few seconds) or (b) a single
   row per attempt (which is just §3 with an extra join). Neither is
   superior to inlining.
3. The dedicated `heartbeat_at` timestamp column gives us an indexable
   "last seen" without requiring JSON path extraction in the janitor's
   "stale activity" sweep.
4. Audit trail of heartbeat history is intentionally not in scope —
   ADR-002's event log captures `step.started`, `step.completed`,
   `step.failed`, `step.retry`, `step.paused`, `step.skipped` which is
   the durable record. Heartbeats are progress hints, not history.

```text
ActivityExecution
- id                    UUID, PK, default uuid4
- tenant_id             UUID | None, indexed
- task_id               UUID, FK("tasks.id", ondelete="CASCADE"), indexed, NOT NULL
- run_id                UUID, FK("workflow_runs.id", ondelete="CASCADE"), indexed, NOT NULL
- step_id               str, NOT NULL              -- node identifier within the workflow
- attempt_number        int, NOT NULL              -- 1-based; matches Task.attempts at claim time
- worker_id             str, NOT NULL              -- identity of the worker that claimed it
- queue_name            str, NOT NULL
- activity_type         str, NOT NULL              -- e.g. "httpRequestNode", "llmNode"
- idempotency_key       str | None                 -- copied from Task at claim time

- status                str, NOT NULL, default "running"
                        (one of: "running", "completed", "failed", "paused", "cancelled", "retry_scheduled")
- started_at            datetime, NOT NULL, default _utcnow
- completed_at          datetime | None
- duration_ms           int | None

- output_ref            str | None                 -- artifact_id when extracted
- output_inline         JSON | None                -- inline output dict
- error_code            str | None
- error_message         Text | None
- non_retryable         bool, NOT NULL, default false
- retry_after_seconds   int | None                 -- explicit backoff hint when status='retry_scheduled'

- heartbeat_at          datetime | None, indexed   -- last heartbeat timestamp
- heartbeat_details     JSON | None                -- last heartbeat payload (overwritten on each beat)

- created_at            datetime, NOT NULL, default _utcnow

Constraints:
- UniqueConstraint("task_id", "attempt_number",
                   name="uq_activity_executions_task_attempt")
  -- one row per attempt; the (task_id, attempt_number) tuple is the
     natural key from the dispatcher's perspective.
- CheckConstraint("status IN ('running','completed','failed','paused','cancelled','retry_scheduled')",
                  name="ck_activity_executions_status")
- CheckConstraint("attempt_number >= 1", name="ck_activity_executions_attempt_pos")

Indexes:
- ix_activity_executions_run_step (run_id, step_id)
  -- joins back to workflow_run_steps
- ix_activity_executions_heartbeat_stale (status, heartbeat_at)
  -- janitor sweep: status='running' AND heartbeat_at < now - threshold
- ix_activity_executions_worker (worker_id, status)
- ix_activity_executions_tenant_started (tenant_id, started_at)
```

`output_ref` / `output_inline` follow the same XOR rule as
`Task.payload_ref` / `Task.payload_inline`: at most one is set; the
codec extracts to artifact above the threshold, otherwise stores inline.

The relationship to `WorkflowRunStep`: `ActivityExecution` is per
attempt; `WorkflowRunStep` is per logical step (current snapshot).
`WorkflowRunStep.attempt` (line 187 of `models/workflow.py`) tracks the
latest attempt number, which equals the most recent
`ActivityExecution.attempt_number` for that `(run_id, step_id)`.
`WorkflowRunStep` is updated only after `ActivityExecution` is finalised.

## §4 — `PipelineCorrelation`

Separate table linking `WorkflowRun` to external CI/CD pipeline events.
Owned by W8.

**Hard rule: this is a separate table. Pipeline/provider identity is
NOT added to `WorkflowRun`.** This preserves ADR-001's workflow-vs-agent
XOR contract — a `WorkflowRun` row stays focused on execution state and
either a workflow or an agent, never on external system identity.

```text
PipelineCorrelation
- id                          UUID, PK, default uuid4
- tenant_id                   UUID | None, indexed, NOT NULL at app layer
                              -- nullable in schema for migration only; W8 enforces non-null
- workflow_run_id             UUID, FK("workflow_runs.id", ondelete="CASCADE"), indexed, NOT NULL
- provider                    str, NOT NULL
                              -- one of: "github_actions", "azure_devops", "jenkins", "gitlab", "generic_webhook"
- external_event_id           str, NOT NULL    -- provider-specific event identifier
- external_run_id             str | None        -- provider-side run/build/job ID
- external_pipeline_id        str | None        -- provider-side pipeline definition ID
- external_commit_sha         str | None
- external_branch             str | None
- external_actor              str | None        -- e.g. github username, AD account
- environment                 str | None        -- "dev"|"staging"|"production" or provider env name
- callback_url                str | None        -- where to post status callbacks
- callback_url_secret_ref     str | None        -- vault path for callback signing/auth secret
- idempotency_key             str, NOT NULL     -- application-computed:
                                                   sha256(provider || external_event_id)
                                                   used to dedupe duplicate webhook deliveries

- created_at                  datetime, NOT NULL, default _utcnow
- updated_at                  datetime, NOT NULL, default _utcnow

Constraints:
- UniqueConstraint("provider", "external_event_id",
                   name="uq_pipeline_corr_provider_event")
  -- absolute dedupe at the schema layer: one provider event yields at most
     one PipelineCorrelation row regardless of webhook redelivery.
- Index(
      "uq_pipeline_corr_idem",
      "tenant_id", "idempotency_key",
      unique=True,
      sqlite_where=text("idempotency_key IS NOT NULL"),
      postgresql_where=text("idempotency_key IS NOT NULL"),
  )
  -- redundant safety net for app-computed idempotency_key, partial-unique
     to mirror ADR-004's pattern.
- CheckConstraint(
      "provider IN ('github_actions','azure_devops','jenkins','gitlab','generic_webhook')",
      name="ck_pipeline_corr_provider"
  )

Indexes:
- ix_pipeline_corr_run (workflow_run_id)
- ix_pipeline_corr_external (provider, external_run_id)
- ix_pipeline_corr_tenant_created (tenant_id, created_at)
```

`callback_url_secret_ref` resolves through the existing Vault service
(see master plan §"Existing Archon toolsets" — Vault/secrets manager).
The raw secret is never stored; only the vault path.

ADR-001 contract preservation: `WorkflowRun` keeps `workflow_id XOR
agent_id`. Pipeline correlation is an *attachment* to a run, not a third
target. Visibility queries that need pipeline metadata join through
`workflow_run_id`.

## §5 — `WorkflowDefinitionVersion`

Versioned snapshot of a workflow definition. Used by W11 (definition
versioning) and W12 (continue-as-new — child runs reference the parent's
version snapshot).

```text
WorkflowDefinitionVersion
- id                    UUID, PK, default uuid4
- workflow_id           UUID, FK("workflows.id", ondelete="CASCADE"), indexed, NOT NULL
- tenant_id             UUID | None, indexed
- version_number        int, NOT NULL              -- monotonic per workflow_id, starts at 1
- schema_snapshot       JSON, NOT NULL             -- the full graph_definition + steps frozen at version cut
- compatibility_set     JSON, NOT NULL, default [] -- list of worker version tags allowed to run this version
- changelog             Text, NOT NULL, default ""
- created_by            str, NOT NULL, default ""
- created_at            datetime, NOT NULL, default _utcnow
- deprecated_at         datetime | None            -- soft-deprecation marker; runs continue, new starts blocked

Constraints:
- UniqueConstraint("workflow_id", "version_number",
                   name="uq_workflow_def_version_number")
  -- monotonic version number per workflow

Indexes:
- ix_workflow_def_version_active (workflow_id, deprecated_at)
- ix_workflow_def_version_tenant (tenant_id, created_at)
```

Relationship to existing fields:

- `WorkflowRun.definition_snapshot` (line 119 of `models/workflow.py`)
  remains the **per-run frozen copy** owned by ADR-001. It does not
  change.
- `WorkflowRun.definition_version` (line 122) is upgraded from a free-form
  string to the FK target of `WorkflowDefinitionVersion.id`. The column
  type stays compatible during the transition; W11 adds the FK in a
  later migration after backfill.
- `compatibility_set` is consumed by W11's worker version routing —
  workers advertise a version tag at registration and the dispatcher
  filters tasks for that version.

## §6 — `RunChain`

Captures the chain of runs created by continue-as-new. Used by W12.

```text
RunChain
- id                    UUID, PK, default uuid4
- chain_id              UUID, NOT NULL, indexed
                        -- shared identifier across every run in the chain;
                           operators search by chain_id to see continuity
- root_run_id           UUID, FK("workflow_runs.id", ondelete="CASCADE"), indexed, NOT NULL
                        -- the originating run that started the chain
- parent_run_id         UUID, FK("workflow_runs.id", ondelete="CASCADE"), indexed, NOT NULL
                        -- the run that issued continue-as-new for this entry
- run_id                UUID, FK("workflow_runs.id", ondelete="CASCADE"), indexed, NOT NULL
                        -- the new child run created by continue-as-new
- generation_number     int, NOT NULL
                        -- 0 for root, 1 for first child, etc; monotonic along the chain
- compacted_state       JSON | None
                        -- carry-forward state passed from parent to child
- continue_reason       str, NOT NULL
                        -- e.g. "history_size_threshold", "scheduled_cutover", "operator_request"
- created_at            datetime, NOT NULL, default _utcnow

Constraints:
- UniqueConstraint("chain_id", "generation_number",
                   name="uq_run_chain_chain_generation")
  -- one row per chain + generation; replays land deterministically.
- UniqueConstraint("run_id",
                   name="uq_run_chain_run_id")
  -- a child run belongs to exactly one chain entry; root run also has
     a row with parent_run_id == run_id and generation_number = 0.

Indexes:
- ix_run_chain_chain (chain_id, generation_number)
- ix_run_chain_root (root_run_id)
- ix_run_chain_parent (parent_run_id)
```

`WorkflowRun` itself does NOT gain `chain_id` / `parent_run_id` columns.
That preserves the XOR contract and keeps `WorkflowRun` focused on
execution state. Visibility queries that want chain context join through
`RunChain.run_id`.

## §7 — `VisibilityIndex`

Denormalised search row maintained per `WorkflowRun`. Used by W13.

The denormalisation is necessary because the canonical query —
"show me all runs in tenant T with status S, queue Q, that touched
external_run X, with cost ≥ N, sorted by duration" — joins
`WorkflowRun` × `Task` × `ActivityExecution` × `PipelineCorrelation` ×
`WorkflowRunStep` and is too expensive to run on the live tables once
per page load.

```text
VisibilityIndex
- id                    UUID, PK, default uuid4
- workflow_run_id       UUID, FK("workflow_runs.id", ondelete="CASCADE"),
                        unique=True, indexed, NOT NULL
                        -- 1:1 with WorkflowRun
- tenant_id             UUID | None, indexed

- status                str, NOT NULL                 -- mirrored from WorkflowRun.status
- workflow_id           UUID | None, indexed          -- mirrored
- agent_id              UUID | None, indexed          -- mirrored
- chain_id              UUID | None, indexed          -- from RunChain
- queue_name            str | None, indexed
- worker_id             str | None, indexed
- definition_version_id UUID | None, indexed

- tags_json             JSON, NOT NULL, default {}    -- arbitrary operator tags
- cost_total_usd        float, NOT NULL, default 0.0  -- sum across steps
- duration_ms           int | None
- step_count            int, NOT NULL, default 0
- failure_code          str | None, indexed

- external_provider     str | None, indexed           -- mirrored from PipelineCorrelation
- external_run_id       str | None, indexed
- external_branch       str | None, indexed
- external_environment  str | None, indexed

- started_at            datetime | None, indexed
- completed_at          datetime | None
- updated_at            datetime, NOT NULL, default _utcnow

Indexes:
- ix_visibility_tenant_status_started
      (tenant_id, status, started_at DESC)
- ix_visibility_tenant_queue_started
      (tenant_id, queue_name, started_at DESC)
- ix_visibility_tenant_worker
      (tenant_id, worker_id)
- ix_visibility_external_run
      (external_provider, external_run_id)
- ix_visibility_failure_code
      (tenant_id, failure_code)
- ix_visibility_cost
      (tenant_id, cost_total_usd)
```

**Update mechanism — decision: function call from the dispatcher, not
a database trigger.** Rationale:

1. SQLite has limited trigger support and no portable JSON triggers,
   so a trigger would be Postgres-only — splitting our test substrate.
2. The dispatcher already runs in the same transaction as event emission
   (ADR-002). Calling a small `update_visibility_index(run_id, session)`
   helper from `dispatch_runtime` after every terminal transition keeps
   the visibility row in the same atomic boundary as the event log.
3. Triggers obscure causality during debugging; an explicit call is
   greppable and traceable.

W13 owns the `update_visibility_index` helper. It is called from
`run_dispatcher` on `run.created`, `run.claimed`, `run.completed`,
`run.failed`, `run.cancelled`; from `pipeline_service` after
`PipelineCorrelation` insert; and from `versioning_service` after
`WorkflowDefinitionVersion` resolution.

## §8 — Payload storage — extension of existing `Artifact`

**Decision: extend the existing `Artifact` model with two flag columns;
do NOT add a new `PayloadBlob` table.**

Rationale:

1. The artifact storage layer (`backend/app/services/artifact_service.py`,
   `models/artifact.py`) already does exactly what payload codec needs:
   stores bytes via a backend (`storage_backend`, `storage_uri`),
   tracks size and content hash, scopes by tenant, supports retention,
   and is referenced from step `output_data` via the `_artifact_ref`
   pattern (see `models/artifact.py` notes lines 5–8).
2. Adding `PayloadBlob` would duplicate every column: storage backend,
   URI, hash, size, retention, tenant scoping. Two storage layers means
   two retention janitors, two integrity checks, two backup paths.
3. The only thing missing is a way to mark "this artifact is a payload
   reference, not a user-visible output." Two boolean flags suffice.

Schema changes to `Artifact`:

```text
Add columns:
- is_payload            bool, NOT NULL, default false
                        -- true when produced by the payload codec for
                           Task.payload_ref or ActivityExecution.output_ref
- payload_role          str | None, indexed
                        -- one of: "task_payload", "activity_output",
                           "step_input", "step_output", or NULL when
                           is_payload=false

Add index:
- ix_artifacts_payload (is_payload, expires_at)
  -- payload janitor uses this; user-visible artifacts have a different
     retention curve.
```

Impact on `Artifact` is purely additive — no existing column is renamed
or retyped. The W16 payload codec (`backend/app/services/payload_codec.py`)
inserts `Artifact` rows with `is_payload=true` and updates `Task.payload_ref`
or `ActivityExecution.output_ref` to the resulting `Artifact.id`.

Existing `_artifact_ref` consumers continue to work unchanged for
user-visible artifacts (step outputs already extracted above the
threshold). Payload references use the same indirection but are filtered
out of the operator UI's "Artifacts" view.

## §9 — `Schedule` (model + state fields)

A first-class schedule table independent of the existing
`WorkflowSchedule` (which is a per-workflow cron). The new table covers
workflow OR agent schedules with overlap policy, jitter, and catchup —
the master plan §"Worker W7" requirements.

```text
Schedule
- id                          UUID, PK, default uuid4
- tenant_id                   UUID | None, indexed
- name                        str, NOT NULL
- description                 Text, NOT NULL, default ""

# ── Action target — same XOR contract as WorkflowRun ──────────────
- workflow_id                 UUID | None, FK("workflows.id", ondelete="SET NULL"), indexed
- agent_id                    UUID | None, FK("agents.id", ondelete="SET NULL"), indexed
- definition_version_id       UUID | None, FK("workflow_definition_versions.id", ondelete="SET NULL")
                              -- pin to a specific version; NULL means "latest active"

# ── Schedule spec ─────────────────────────────────────────────────
- calendar_spec               str, NOT NULL
                              -- cron expression, RRULE, or "interval:N{s|m|h|d}"
- spec_kind                   str, NOT NULL
                              -- one of: "cron", "rrule", "interval"
- timezone                    str, NOT NULL, default "UTC"
- jitter_seconds              int, NOT NULL, default 0       -- random ±jitter applied to fire time
- start_bound                 datetime | None                -- earliest fire time
- end_bound                   datetime | None                -- latest fire time

# ── Behaviour policy ──────────────────────────────────────────────
- overlap_policy              str, NOT NULL, default "skip"
                              -- one of: "skip", "buffer_one", "buffer_all",
                                 "cancel_running", "terminate_running", "allow_all"
- catchup_window_seconds      int, NOT NULL, default 0
                              -- 0 = no catchup; >0 = catch up missed fires within this window
- pause_on_failure            bool, NOT NULL, default false
- input_template              JSON, NOT NULL, default {}     -- fed into ExecutionFacade.start_run

# ── State ─────────────────────────────────────────────────────────
- paused                      bool, NOT NULL, default false
- last_evaluated_at           datetime | None                -- last schedule loop pass
- last_fire_attempted_at      datetime | None                -- last attempted fire (regardless of overlap result)
- last_fire_succeeded_at      datetime | None                -- last successful fire
- last_successful_run_id      UUID | None,
                              FK("workflow_runs.id", ondelete="SET NULL")
- next_fire_at                datetime | None, indexed
- consecutive_failures        int, NOT NULL, default 0
- notes                       Text, NOT NULL, default ""

- created_by                  str, NOT NULL, default ""
- created_at                  datetime, NOT NULL, default _utcnow
- updated_at                  datetime, NOT NULL, default _utcnow

Constraints:
- CheckConstraint(
      "(workflow_id IS NULL) <> (agent_id IS NULL)",
      name="ck_schedules_workflow_xor_agent"
  )
  -- mirrors WorkflowRun's XOR; preserves ADR-001 invariant at the
     schedule layer.
- CheckConstraint(
      "spec_kind IN ('cron','rrule','interval')",
      name="ck_schedules_spec_kind"
  )
- CheckConstraint(
      "overlap_policy IN ('skip','buffer_one','buffer_all','cancel_running','terminate_running','allow_all')",
      name="ck_schedules_overlap_policy"
  )

Indexes:
- ix_schedules_tenant_paused (tenant_id, paused)
- ix_schedules_next_fire (next_fire_at, paused)
  -- the schedule loop's primary scan
- ix_schedules_workflow_id (workflow_id)
- ix_schedules_agent_id (agent_id)
```

Relationship to existing `WorkflowSchedule`:

- `WorkflowSchedule` (line 259 of `models/workflow.py`) is retained
  unchanged for backward compatibility. Existing cron rows continue
  to fire via the worker's existing tick.
- W7 implements the `schedule_service` against the new `Schedule`
  table. New schedules are written to `Schedule`; W7 may later migrate
  `WorkflowSchedule` rows by emitting equivalent `Schedule` rows in a
  one-shot data migration. That migration is W7's responsibility, not
  this ADR's.

## Workflow-vs-agent XOR contract — preserved

Every new table that points at a "thing being executed" preserves the
XOR contract from ADR-001:

| Table                | Targets                                  | XOR enforced? |
|----------------------|------------------------------------------|---------------|
| `Task`               | references `run_id` (XOR is on the run)  | inherits      |
| `ActivityExecution`  | references `run_id`                      | inherits      |
| `PipelineCorrelation`| references `workflow_run_id`             | inherits      |
| `RunChain`           | references `run_id`/`parent_run_id`/`root_run_id` | inherits |
| `VisibilityIndex`    | mirrors `workflow_id` and `agent_id`     | inherits      |
| `Schedule`           | `workflow_id` XOR `agent_id`             | enforced via CHECK |
| `WorkflowDefinitionVersion` | `workflow_id` only                | N/A — workflows only |

No table directly columns pipeline/provider identity onto `WorkflowRun`.
`PipelineCorrelation` stands separately as the master plan §"Worker W8"
requires.

## Migration ordering (locked)

```
1. WorkflowDefinitionVersion       (no FK dependencies on new tables)
2. TaskQueue                       (independent)
3. Task                            (FK to workflow_runs only)
4. ActivityExecution               (FK to tasks, workflow_runs)
5. PipelineCorrelation             (FK to workflow_runs)
6. RunChain                        (FK to workflow_runs)
7. VisibilityIndex                 (FK to workflow_runs)
8. Schedule                        (FK to workflows, agents, workflow_definition_versions)
9. Artifact additive columns       (ALTER TABLE artifacts ADD ...)
```

W1 owns migrations 2 and 3. W3 owns 4. W8 owns 5. W11 owns 1. W12 owns
6. W13 owns 7. W7 owns 8. W16 owns 9. Each migration includes its own
SQLite + Postgres compatibility verification. Migrations 1 through 8
are pure additions — no existing column is altered. Migration 9 is
purely additive on `artifacts`.

## Consequences

### Positive

- W1, W2, W3, W7, W8, W11, W12, W13, W16 can implement in parallel
  without renegotiating column names. Each worker's PR touches a
  different migration file and a different model file.
- The XOR contract (ADR-001) is preserved across every new table — no
  schema ambiguity creeps in via pipeline or chain identity.
- The polling index `ix_tasks_dispatch_poll` is the precise tuple
  `(tenant_id, queue_name, status, visible_at, priority)` that the
  master plan §"Worker W1" requires.
- Idempotency partial-unique indexes (`uq_tasks_tenant_idem`,
  `uq_pipeline_corr_idem`) follow ADR-004's portable
  `sqlite_where`/`postgresql_where` pattern.
- `ActivityExecution` heartbeat is a single column overwrite, not a
  per-beat row insert — write amplification is bounded.
- Payload extraction reuses the existing `Artifact` infrastructure,
  avoiding a parallel storage subsystem.

### Negative

- The denormalised `VisibilityIndex` requires the dispatcher to call an
  update helper at every terminal transition. Forgetting one call site
  causes silent staleness. Mitigation: a stop-gate test asserts that
  `VisibilityIndex.updated_at >= WorkflowRun.completed_at` for every
  terminal run.
- `WorkflowRun.definition_version` changes meaning (free-form string ->
  FK target). W11 must execute a backfill before adding the FK
  constraint; the column stays nullable to permit pre-existing runs
  without a versioned definition row.
- Migration ordering is strict — out-of-order application breaks FKs.
  Mitigation: the migration ordering is encoded in the alembic
  `down_revision` chain, not just in this document.

### Neutral

- `WorkflowSchedule` continues to exist alongside the new `Schedule`
  table during the W7 transition. The two will be reconciled in a
  W7-owned data migration; this ADR does not delete `WorkflowSchedule`.
- Fully-qualified table names in the ORM remain in `snake_case` plural
  (`task_queues`, `tasks`, `activity_executions`, `pipeline_correlations`,
  `workflow_definition_versions`, `run_chains`, `visibility_indexes`,
  `schedules`).

## Implementation notes

### SQLite vs Postgres parity

All partial-unique indexes use the portable
`sqlite_where=text("...")` + `postgresql_where=text("...")` pattern
inherited from ADR-004. JSON columns use `Column(JSON, nullable=...)`
which renders as `JSON` on SQLite and `JSONB` on Postgres via the
existing dialect-aware path.

### Type usage

- `UUID` primary keys use `Field(default_factory=uuid4, primary_key=True)`
  matching existing models.
- FK references use the canonical
  `Column(SAUuid, ForeignKey("table.id", ondelete=...), nullable=...)`
  shape (see `WorkflowRun.workflow_id` lines 94–102).
- All `tenant_id` columns are `UUID | None` matching
  `WorkflowRun.tenant_id` (line 125).
- All datetimes are naive UTC via `_utcnow()` (matching the existing
  `models/workflow.py` line 15 / `models/__init__.py` line 15
  convention noted in the ADR-005 context).

### What this ADR does NOT freeze

- The Python `ActivityContext` / `ActivityResult` dataclass shapes —
  those are owned by ADR-003 (hint envelope) and the W3 contract block
  in the master plan §"Worker W3". They are interface contracts, not
  schema.
- The REST surface for queues, schedules, pipelines — owned by
  the corresponding worker's `routes/` files.
- The exact event-history payload shapes for new event types
  (`task.created`, `task.claimed`, `task.heartbeat`, `task.released`,
  `task.completed`, `task.failed`) — those will require a future ADR
  amending ADR-002's enumerated event types. This ADR only freezes the
  durable rows that produce those events.

## Locked

The following names cannot change without a new ADR superseding 008:

**Tables:**
`task_queues`, `tasks`, `activity_executions`, `pipeline_correlations`,
`workflow_definition_versions`, `run_chains`, `visibility_indexes`,
`schedules`.

**Locked column names (all tables):**

- `task_queues`: `id`, `tenant_id`, `name`, `queue_type`, `description`,
  `max_dispatch_rate`, `concurrency_limit`, `retention_days`, `paused`,
  `created_at`, `updated_at`.
- `tasks`: `id`, `tenant_id`, `run_id`, `step_id`, `queue_name`,
  `task_type`, `payload_ref`, `payload_inline`, `status`, `visible_at`,
  `attempts`, `max_attempts`, `lease_owner`, `lease_expiration`,
  `priority`, `idempotency_key`, `correlation_id`, `created_at`,
  `updated_at`.
- `activity_executions`: `id`, `tenant_id`, `task_id`, `run_id`,
  `step_id`, `attempt_number`, `worker_id`, `queue_name`,
  `activity_type`, `idempotency_key`, `status`, `started_at`,
  `completed_at`, `duration_ms`, `output_ref`, `output_inline`,
  `error_code`, `error_message`, `non_retryable`, `retry_after_seconds`,
  `heartbeat_at`, `heartbeat_details`, `created_at`.
- `pipeline_correlations`: `id`, `tenant_id`, `workflow_run_id`,
  `provider`, `external_event_id`, `external_run_id`,
  `external_pipeline_id`, `external_commit_sha`, `external_branch`,
  `external_actor`, `environment`, `callback_url`,
  `callback_url_secret_ref`, `idempotency_key`, `created_at`,
  `updated_at`.
- `workflow_definition_versions`: `id`, `workflow_id`, `tenant_id`,
  `version_number`, `schema_snapshot`, `compatibility_set`, `changelog`,
  `created_by`, `created_at`, `deprecated_at`.
- `run_chains`: `id`, `chain_id`, `root_run_id`, `parent_run_id`,
  `run_id`, `generation_number`, `compacted_state`, `continue_reason`,
  `created_at`.
- `visibility_indexes`: `id`, `workflow_run_id`, `tenant_id`, `status`,
  `workflow_id`, `agent_id`, `chain_id`, `queue_name`, `worker_id`,
  `definition_version_id`, `tags_json`, `cost_total_usd`, `duration_ms`,
  `step_count`, `failure_code`, `external_provider`, `external_run_id`,
  `external_branch`, `external_environment`, `started_at`,
  `completed_at`, `updated_at`.
- `schedules`: `id`, `tenant_id`, `name`, `description`, `workflow_id`,
  `agent_id`, `definition_version_id`, `calendar_spec`, `spec_kind`,
  `timezone`, `jitter_seconds`, `start_bound`, `end_bound`,
  `overlap_policy`, `catchup_window_seconds`, `pause_on_failure`,
  `input_template`, `paused`, `last_evaluated_at`,
  `last_fire_attempted_at`, `last_fire_succeeded_at`,
  `last_successful_run_id`, `next_fire_at`, `consecutive_failures`,
  `notes`, `created_by`, `created_at`, `updated_at`.
- `artifacts` additive columns: `is_payload`, `payload_role`.

**Locked indexes:**
`uq_task_queues_tenant_name`, `ix_task_queues_tenant_id_paused`,
`uq_tasks_tenant_idem`, `ix_tasks_dispatch_poll`, `ix_tasks_run_id`,
`ix_tasks_lease_owner_expiration`, `ix_tasks_correlation_id`,
`uq_activity_executions_task_attempt`, `ix_activity_executions_run_step`,
`ix_activity_executions_heartbeat_stale`,
`ix_activity_executions_worker`, `ix_activity_executions_tenant_started`,
`uq_pipeline_corr_provider_event`, `uq_pipeline_corr_idem`,
`ix_pipeline_corr_run`, `ix_pipeline_corr_external`,
`ix_pipeline_corr_tenant_created`, `uq_workflow_def_version_number`,
`ix_workflow_def_version_active`, `ix_workflow_def_version_tenant`,
`uq_run_chain_chain_generation`, `uq_run_chain_run_id`,
`ix_run_chain_chain`, `ix_run_chain_root`, `ix_run_chain_parent`,
`ix_visibility_tenant_status_started`,
`ix_visibility_tenant_queue_started`, `ix_visibility_tenant_worker`,
`ix_visibility_external_run`, `ix_visibility_failure_code`,
`ix_visibility_cost`, `ix_schedules_tenant_paused`,
`ix_schedules_next_fire`, `ix_schedules_workflow_id`,
`ix_schedules_agent_id`, `ix_artifacts_payload`.

**Locked CHECK constraints:**
`ck_tasks_status`, `ck_tasks_attempts_nonneg`,
`ck_activity_executions_status`, `ck_activity_executions_attempt_pos`,
`ck_pipeline_corr_provider`, `ck_schedules_workflow_xor_agent`,
`ck_schedules_spec_kind`, `ck_schedules_overlap_policy`.

## See also

- ADR-001 — unified run model; XOR contract is preserved by every new
  table that targets a run.
- ADR-002 — event log; new task/activity events extend the enumerated
  set in a future ADR amendment.
- ADR-003 — hint envelope; activity executors continue to emit hints,
  the engine consumes them; this ADR adds the durable row that holds
  attempts and heartbeats around each hint emission.
- ADR-004 — idempotency contract; `Task.idempotency_key` and
  `PipelineCorrelation.idempotency_key` reuse the partial-unique-index
  pattern.
- ADR-005 — durability policy; `Task` and `ActivityExecution` rows are
  the durable substrate that survives the worker crashes ADR-005's
  fail-closed checkpointer protects against.
- ADR-006 — execution migration; legacy `Execution` rows do not produce
  `Task`/`ActivityExecution`/`VisibilityIndex` rows. Only WorkflowRun
  rows do.
- ADR-007 — workflow deletion semantics; `WorkflowDefinitionVersion`
  uses `ondelete="CASCADE"` because a deleted workflow's versions are
  meaningless. Run-side FKs remain `SET NULL` per ADR-007.
