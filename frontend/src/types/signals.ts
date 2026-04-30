/**
 * TypeScript types mirroring the backend ``Signal`` JSON shape.
 *
 * Source of truth: ``backend/app/models/approval.py::Signal`` and the REST
 * surface exposed by ``backend/app/routes/approvals.py`` (signal injection
 * endpoint). Field names use snake_case to match the wire format verbatim.
 *
 * Signals are the durable mechanism by which the dispatcher resumes paused
 * runs. ``approval.granted`` / ``approval.rejected`` are emitted by the
 * approval service; ``cancel`` / ``input.provided`` may be operator-injected
 * via ``POST /api/v1/executions/{run_id}/signals``.
 */

/**
 * Closed set of signal types known to the dispatcher.
 *
 * Note: backend keeps the signal_type column as a free-form string, but
 * these are the operator-meaningful types. ``custom`` is the escape hatch
 * for forward compatibility — if a new well-known type appears server-side
 * we add it here in the same patch.
 */
export type SignalType =
  | "approval.granted"
  | "approval.rejected"
  | "approval.expired"
  | "input.requested"
  | "input.provided"
  | "cancel"
  | "custom";

/** Single signal row. */
export interface Signal {
  id: string;
  run_id: string;
  step_id: string | null;
  signal_type: SignalType | string;
  payload: Record<string, unknown>;
  consumed_at: string | null;
  created_at: string;
}

/** ``POST /api/v1/executions/{run_id}/signals`` body. */
export interface SignalInjectArgs {
  signal_type: SignalType | string;
  payload?: Record<string, unknown>;
  step_id?: string;
}

/** ``POST /api/v1/executions/{run_id}/signals`` envelope. */
export interface SignalInjectResponse {
  data: {
    signal_id: string;
    run_id: string;
    signal_type: string;
  };
  meta: {
    request_id: string;
    timestamp: string;
  };
}
