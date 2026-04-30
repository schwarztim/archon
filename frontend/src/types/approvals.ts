/**
 * TypeScript types mirroring the backend ``Approval`` JSON shape.
 *
 * Source of truth: ``backend/app/models/approval.py`` and the REST surface
 * exposed by ``backend/app/routes/approvals.py``. Field names use snake_case
 * to match the wire format verbatim — DO NOT camelCase them.
 *
 * Lifecycle is owned by ``backend/app/services/approval_service.py``:
 *   pending → approved | rejected | expired
 *
 * The terminal-state transitions emit a corresponding ``Signal`` row with
 * ``signal_type`` of ``approval.granted`` / ``approval.rejected`` /
 * ``approval.expired``. See ``types/signals.ts``.
 */

/** Closed set of approval states. Matches ``approval.status`` column. */
export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired";

/**
 * Single approval row mirroring ``Approval`` SQLModel.
 *
 * Tenant scoping rules (see ``approvals.py::_check_tenant_visibility``):
 *   - ``tenant_id`` null → admin-only visibility
 *   - non-null tenant_id → only callers in that tenant or admins
 */
export interface Approval {
  id: string;
  run_id: string;
  step_id: string;
  tenant_id: string | null;
  requester_id: string | null;
  approver_id: string | null;
  status: ApprovalStatus;
  decision_reason: string | null;
  requested_at: string;
  decided_at: string | null;
  expires_at: string | null;
  payload: Record<string, unknown>;
}

/** Standard envelope meta block matching ``approvals.py::_meta``. */
export interface ApprovalMeta {
  request_id: string;
  timestamp: string;
  count?: number;
  note?: string;
}

/** ``GET /api/v1/approvals`` envelope. */
export interface ApprovalListResponse {
  data: Approval[];
  meta: ApprovalMeta;
}

/** ``GET /api/v1/approvals/{id}`` envelope. */
export interface ApprovalResponse {
  data: Approval;
  meta: ApprovalMeta;
}

/** ``POST /api/v1/approvals/{id}/approve|reject`` envelope. */
export interface ApprovalDecisionResponse {
  data: {
    approval: Approval;
    signal_id: string;
  };
  meta: ApprovalMeta;
}

/** ``POST /api/v1/executions/{run_id}/resume`` envelope. */
export interface ResumeRunResponse {
  data: {
    run_id: string;
    status: string;
    pending_signal_count: number;
    pending_signal_types: string[];
  };
  meta: ApprovalMeta;
}
