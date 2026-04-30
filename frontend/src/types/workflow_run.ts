/**
 * TypeScript types mirroring the backend ``WorkflowRun`` JSON shape.
 *
 * Source of truth: ``backend/app/models/workflow.py`` and the canonical
 * payload returned by ``GET /api/v1/executions/{id}?canonical=true`` /
 * ``GET /api/v1/workflow-runs/{id}``. Field names use snake_case to match
 * the wire format verbatim — DO NOT camelCase them.
 *
 * Bound by:
 *   - ADR-001 — unified run model (workflow OR agent)
 *   - ADR-002 — run event ownership
 *   - ADR-004 — idempotency contract
 *   - ADR-007 — workflow_id is nullable (ondelete=SET NULL)
 */

/**
 * Run lifecycle status. Mirrors the closed set of values the dispatcher /
 * facade may write to ``workflow_runs.status``.
 *
 * Note: ``queued`` is a real intermediate state (worker leasing); some
 * legacy paths skip it and go straight pending → running.
 */
export type RunStatus =
  | "pending"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "paused";

/** A WorkflowRun describes either a workflow execution or an agent run. */
export type RunKind = "workflow" | "agent";

/**
 * Optional metrics block populated by the dispatcher / facade as the run
 * progresses. ``tokens`` and ``cost_usd`` are first-class; arbitrary
 * additional keys are permitted for forward compatibility.
 */
export interface RunMetrics {
  tokens?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cost_usd?: number;
  [k: string]: unknown;
}

/**
 * Canonical WorkflowRun shape returned by ``GET /api/v1/workflow-runs/{id}``
 * or ``GET /api/v1/executions/{id}?canonical=true``.
 *
 * Field names match the backend SQLModel column names verbatim.
 */
export interface WorkflowRun {
  id: string;
  workflow_id: string | null;
  agent_id: string | null;
  kind: RunKind;
  tenant_id: string | null;
  status: RunStatus;
  trigger_type: string;
  input_data: Record<string, unknown> | null;
  triggered_by: string;
  attempt: number;

  // ── Idempotency (ADR-004) ────────────────────────────────────────
  idempotency_key: string | null;
  input_hash: string | null;

  // ── Snapshot of the workflow/agent definition at run time ────────
  definition_snapshot: Record<string, unknown>;
  definition_version?: string | null;

  // ── Outputs / observability ───────────────────────────────────────
  output_data: Record<string, unknown> | null;
  metrics: RunMetrics | null;
  error: string | null;
  error_code: string | null;

  // ── Timeline ──────────────────────────────────────────────────────
  queued_at: string | null;
  claimed_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  paused_at: string | null;
  resumed_at: string | null;
  cancel_requested_at: string | null;
  duration_ms: number | null;
  created_at: string;

  // ── Worker leasing (optional — present when worker has claimed) ──
  lease_owner?: string | null;
  lease_expires_at?: string | null;
}

/**
 * Compact run shape returned by the run history list endpoint
 * (``GET /api/v1/workflow-runs``).
 *
 * Shape derived from ``backend/app/routes/events.py::_serialise_run``.
 * Excludes heavy fields (``definition_snapshot``, ``input_data``,
 * ``output_data``) to keep list pages cheap.
 */
export interface WorkflowRunSummary {
  id: string;
  kind: RunKind;
  workflow_id: string | null;
  agent_id: string | null;
  tenant_id: string | null;
  status: RunStatus;
  trigger_type: string;
  triggered_by: string;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error_code: string | null;
  created_at: string;
}

/**
 * Step status — mirrors ``workflow_run_steps.status``. Closed set lives
 * in the backend alongside the ``WorkflowRunStep`` SQLModel.
 */
export type StepStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped"
  | "paused";

/**
 * Step shape mirroring ``backend/app/models/workflow.py::WorkflowRunStep``.
 * Field names use snake_case to match the wire format.
 */
export interface WorkflowRunStep {
  id: string;
  run_id: string;
  step_id: string;
  name: string;
  status: StepStatus;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number;
  input_data: Record<string, unknown>;
  output_data: Record<string, unknown> | null;
  error: string | null;
  agent_execution_id: string | null;

  // ── Retries / idempotency ─────────────────────────────────────────
  attempt: number;
  retry_count: number;
  idempotency_key: string | null;

  // ── LangGraph checkpointer linkage (ADR-005) ─────────────────────
  checkpoint_thread_id: string | null;

  // ── Hash-chain alignment + artifact pointer ──────────────────────
  input_hash: string | null;
  output_artifact_id: string | null;

  // ── Cost + worker observability ───────────────────────────────────
  token_usage: Record<string, number>;
  cost_usd: number | null;
  worker_id: string | null;
  error_code: string | null;

  created_at: string;
}

/** Standard envelope meta block — same shape as ApiResponse meta. */
export interface RunMeta {
  request_id: string;
  timestamp: string;
  pagination?: {
    total?: number;
    limit?: number;
    offset?: number;
    returned?: number;
  };
  source?: "workflow_runs" | "executions";
  cancel_intent?: boolean;
}

/** Page of runs returned by the run history endpoint. */
export interface WorkflowRunListResponse {
  items: WorkflowRunSummary[];
  next_cursor: string | null;
  meta?: RunMeta;
}

/** Run-create response (``POST /api/v1/executions``). */
export interface StartRunResponse {
  data: WorkflowRun;
  meta?: RunMeta;
  // 409 idempotency conflict envelope (ADR-004 §Behaviour) — mutually exclusive with ``data``.
  error?: {
    code: "idempotency_conflict";
    message: string;
    key: string;
    existing_run_id: string;
  };
}

/** Cancel response — 202 Accepted with the canonical run shape. */
export interface CancelRunResponse {
  data: WorkflowRun | Record<string, unknown>;
  meta?: RunMeta;
  status: "accepted";
}
