/**
 * TypeScript types mirroring the backend ``workflow_run_events`` shape.
 *
 * Source of truth: ``backend/app/services/event_service.py::EVENT_TYPES``
 * and ``backend/app/routes/events.py::_serialise_event``.
 *
 * The 15 ``event_type`` values are bound by the
 * ``ck_run_events_event_type`` CHECK constraint on ``workflow_run_events``
 * (see ``backend/app/models/workflow.py``). Adding a new entry requires an
 * ADR-002 amendment AND the matching CHECK constraint update.
 */

/** Run-level event types — 9 entries, lifecycle of a WorkflowRun. */
export type RunEventType =
  | "run.created"
  | "run.queued"
  | "run.claimed"
  | "run.started"
  | "run.completed"
  | "run.failed"
  | "run.cancelled"
  | "run.paused"
  | "run.resumed";

/** Step-level event types — 6 entries, lifecycle of a WorkflowRunStep. */
export type StepEventType =
  | "step.started"
  | "step.completed"
  | "step.failed"
  | "step.skipped"
  | "step.retry"
  | "step.paused";

/** Closed enumeration of every valid event_type. */
export type EventType = RunEventType | StepEventType;

/**
 * Frozen array of every EventType. Use this when you need to iterate at
 * runtime — for instance, in API filter validation or in tests.
 *
 * Order: run-level first (chronological lifecycle), then step-level.
 */
export const ALL_EVENT_TYPES: readonly EventType[] = [
  "run.created",
  "run.queued",
  "run.claimed",
  "run.started",
  "run.completed",
  "run.failed",
  "run.cancelled",
  "run.paused",
  "run.resumed",
  "step.started",
  "step.completed",
  "step.failed",
  "step.skipped",
  "step.retry",
  "step.paused",
] as const;

/**
 * One row of the hash-chained ``workflow_run_events`` log.
 *
 * Field names mirror the backend serialiser exactly. ``current_hash`` is
 * a 64-char hex sha256 digest of the canonical envelope (see ADR-002 for
 * the envelope shape and the serialisation rules).
 */
export interface WorkflowRunEvent {
  id: string;
  run_id: string;
  sequence: number;
  event_type: EventType;
  payload: Record<string, unknown>;
  tenant_id: string | null;
  correlation_id: string | null;
  span_id: string | null;
  step_id: string | null;
  prev_hash: string | null; // NULL only for sequence=0
  current_hash: string;
  created_at: string;
}

/** Standard envelope meta block — same shape as the run meta. */
export interface EventMeta {
  request_id: string;
  timestamp: string;
}

/**
 * Response shape for ``GET /api/v1/workflow-runs/{run_id}/events``.
 *
 * - ``next_after_sequence`` is ``null`` when the requested page is the
 *   tail of the chain. Otherwise it is the largest sequence number on
 *   this page — pass it as ``after_sequence`` to fetch the next page.
 * - ``chain_verified`` is computed over the *unfiltered* page even if
 *   the caller filtered by ``event_types``. This prevents a filter from
 *   masking tampering.
 */
export interface EventsResponse {
  run_id: string;
  events: WorkflowRunEvent[];
  next_after_sequence: number | null;
  chain_verified: boolean;
  meta?: EventMeta;
}

/**
 * Response shape for
 * ``GET /api/v1/workflow-runs/{run_id}/events/verify``.
 */
export interface ChainVerifyResponse {
  run_id: string;
  chain_verified: boolean;
  first_corruption_at_sequence: number | null;
  event_count: number;
  meta?: EventMeta;
}

/** WebSocket / channel envelope used to push a single event in real time. */
export interface RunEventStreamMessage {
  /** When events arrive over WS, the backend wraps them under ``type``. */
  type: "event";
  data: WorkflowRunEvent;
}
