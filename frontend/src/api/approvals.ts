/**
 * Frontend client for the approvals REST surface.
 *
 * Backend routes (``backend/app/routes/approvals.py``):
 *   - GET    /api/v1/approvals?status=pending&tenant_id=...
 *   - GET    /api/v1/approvals/{id}
 *   - POST   /api/v1/approvals/{id}/approve   body: {"reason": "..."}
 *   - POST   /api/v1/approvals/{id}/reject    body: {"reason": "..."}
 *   - POST   /api/v1/executions/{run_id}/resume
 */

import type {
  Approval,
  ApprovalDecisionResponse,
  ApprovalListResponse,
  ApprovalResponse,
  ApprovalStatus,
  ResumeRunResponse,
} from "@/types/approvals";

const API_BASE = "/api/v1";

/** Query params for ``listApprovals``. */
export interface ListApprovalsArgs {
  status?: ApprovalStatus | "all" | "decided";
  tenant_id?: string;
  limit?: number;
}

async function readError(res: Response): Promise<unknown> {
  return res.json().catch(() => ({
    errors: [{ code: "UNKNOWN", message: res.statusText }],
  }));
}

/**
 * List approvals. Default ``status="pending"``. Backend currently only
 * supports ``status=pending`` — other values return an empty list with a
 * meta note. See ``approvals.py::list_approvals``.
 */
export async function listApprovals(
  opts: ListApprovalsArgs = {},
): Promise<Approval[]> {
  const sp = new URLSearchParams();
  if (opts.status !== undefined) sp.set("status", opts.status);
  if (opts.tenant_id) sp.set("tenant_id", opts.tenant_id);
  if (opts.limit !== undefined) sp.set("limit", String(opts.limit));

  const qs = sp.toString();
  const path = `${API_BASE}/approvals${qs ? `?${qs}` : ""}`;

  const res = await fetch(path, {
    method: "GET",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });

  if (!res.ok) throw await readError(res);

  const body = (await res.json()) as ApprovalListResponse;
  return body.data ?? [];
}

/** Fetch a single approval by id. */
export async function getApproval(id: string): Promise<Approval> {
  const res = await fetch(
    `${API_BASE}/approvals/${encodeURIComponent(id)}`,
    {
      method: "GET",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
    },
  );

  if (!res.ok) throw await readError(res);

  const body = (await res.json()) as ApprovalResponse;
  return body.data;
}

/**
 * Approve an approval. Emits ``approval.granted`` + ``run.resumed`` and
 * flips the run from ``paused`` → ``running``.
 */
export async function approveApproval(
  id: string,
  reason?: string,
): Promise<{ approval: Approval; signal_id: string }> {
  const res = await fetch(
    `${API_BASE}/approvals/${encodeURIComponent(id)}/approve`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason ?? null }),
    },
  );

  if (!res.ok) throw await readError(res);

  const body = (await res.json()) as ApprovalDecisionResponse;
  return body.data;
}

/**
 * Reject an approval. Emits ``approval.rejected``. The run remains paused
 * — the dispatcher decides on resume whether to fail or branch.
 */
export async function rejectApproval(
  id: string,
  reason?: string,
): Promise<{ approval: Approval; signal_id: string }> {
  const res = await fetch(
    `${API_BASE}/approvals/${encodeURIComponent(id)}/reject`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason ?? null }),
    },
  );

  if (!res.ok) throw await readError(res);

  const body = (await res.json()) as ApprovalDecisionResponse;
  return body.data;
}

/**
 * Generic resume — re-checks pending signals; the dispatcher does the
 * actual resume. Returns the count of pending signals visible for the run.
 */
export async function resumeRun(
  runId: string,
): Promise<{
  run_id: string;
  status: string;
  pending_signal_count: number;
  pending_signal_types: string[];
}> {
  const res = await fetch(
    `${API_BASE}/executions/${encodeURIComponent(runId)}/resume`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    },
  );

  if (!res.ok) throw await readError(res);

  const body = (await res.json()) as ResumeRunResponse;
  return body.data;
}
