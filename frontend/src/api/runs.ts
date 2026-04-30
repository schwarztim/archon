/**
 * Frontend client for the canonical run API.
 *
 * Backend routes:
 *   - POST   /api/v1/executions           — start a workflow OR agent run
 *   - GET    /api/v1/executions/{id}      — get a run (legacy shape)
 *   - GET    /api/v1/executions/{id}?canonical=true  — get a run (WorkflowRun shape)
 *   - GET    /api/v1/workflow-runs/{id}   — alias for canonical=true (preferred)
 *   - POST   /api/v1/executions/{id}/cancel — record cancel intent
 *   - GET    /api/v1/workflow-runs        — paginated run history
 *
 * Per ADR-004 the idempotency contract is enforced via the
 * ``X-Idempotency-Key`` header — passing the key in the body is also
 * supported but the header wins on conflict.
 */

import type {
  CancelRunResponse,
  RunKind,
  RunStatus,
  StartRunResponse,
  WorkflowRun,
  WorkflowRunListResponse,
} from "@/types/workflow_run";

const API_BASE = "/api/v1";

/** Body shape for ``POST /api/v1/executions``. */
export interface StartRunArgs {
  /** Provide exactly one of workflow_id or agent_id. */
  workflow_id?: string;
  agent_id?: string;
  input_data: Record<string, unknown>;
  /** Optional — when omitted the run is non-idempotent. */
  idempotency_key?: string;
  /** Defaults to ``"manual"`` server-side. */
  trigger_type?: string;
  /** Defaults to the authenticated user's email server-side. */
  triggered_by?: string;
}

/**
 * Start a new run (workflow- or agent-driven). Honours the ADR-004
 * idempotency contract — when ``idempotency_key`` is supplied it is sent
 * both in the body AND in the ``X-Idempotency-Key`` header.
 *
 * Returns the canonical run on success (201) or the existing run on an
 * idempotency hit (200). On idempotency *conflict* (409) the server
 * returns an error envelope, which is thrown.
 */
export async function startRun(args: StartRunArgs): Promise<{
  run_id: string;
  status: RunStatus;
  run: WorkflowRun;
  is_new: boolean;
}> {
  if (!args.workflow_id && !args.agent_id) {
    throw new Error("startRun: exactly one of workflow_id or agent_id is required.");
  }
  if (args.workflow_id && args.agent_id) {
    throw new Error("startRun: workflow_id and agent_id are mutually exclusive.");
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (args.idempotency_key) {
    headers["X-Idempotency-Key"] = args.idempotency_key;
  }

  const res = await fetch(`${API_BASE}/executions`, {
    method: "POST",
    credentials: "include",
    headers,
    body: JSON.stringify(args),
  });

  const json = (await res.json()) as StartRunResponse & {
    is_new?: boolean;
    data?: WorkflowRun;
  };

  if (res.status === 409) {
    // Idempotency conflict — surface the structured error.
    throw json.error ?? {
      code: "idempotency_conflict",
      message: "Idempotency key already used with different input.",
    };
  }

  if (!res.ok) {
    throw json;
  }

  const run = json.data as WorkflowRun;
  return {
    run_id: run.id,
    status: run.status,
    run,
    is_new: res.status === 201,
  };
}

/** Get a run by id. Pass ``canonical=true`` for the WorkflowRun shape. */
export async function getRun(
  id: string,
  opts?: { canonical?: boolean },
): Promise<WorkflowRun> {
  const canonical = opts?.canonical ?? true;
  const path = canonical
    ? `${API_BASE}/workflow-runs/${encodeURIComponent(id)}`
    : `${API_BASE}/executions/${encodeURIComponent(id)}?canonical=true`;

  const res = await fetch(path, {
    method: "GET",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({
      errors: [{ code: "UNKNOWN", message: res.statusText }],
    }));
    throw err;
  }

  const body = (await res.json()) as { data?: WorkflowRun } | WorkflowRun;
  // Tolerate both envelope and raw shape — the canonical alias returns
  // ``data: {...}`` while ``executions/{id}?canonical=true`` returns the
  // model_dump dict directly inside ``data``.
  if (body && typeof body === "object" && "data" in body && body.data) {
    return body.data;
  }
  return body as WorkflowRun;
}

/** Cancel a run — server records intent and emits ``run.cancelled``. */
export async function cancelRun(id: string): Promise<{
  status: "accepted";
  run: WorkflowRun | Record<string, unknown>;
}> {
  const res = await fetch(
    `${API_BASE}/executions/${encodeURIComponent(id)}/cancel`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    },
  );

  if (!res.ok && res.status !== 202) {
    const err = await res.json().catch(() => ({
      errors: [{ code: "UNKNOWN", message: res.statusText }],
    }));
    throw err;
  }

  const body = (await res.json()) as CancelRunResponse;
  return { status: "accepted", run: body.data };
}

/** Query params for ``listRuns``. */
export interface ListRunsParams {
  status?: RunStatus;
  kind?: RunKind | string;
  agent_id?: string;
  workflow_id?: string;
  tenant_id?: string;
  since?: string; // ISO-8601
  cursor?: string;
  limit?: number;
}

/** List runs (paginated). */
export async function listRuns(
  opts: ListRunsParams = {},
): Promise<WorkflowRunListResponse> {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(opts)) {
    if (v !== undefined && v !== null) {
      sp.set(k, String(v));
    }
  }
  const qs = sp.toString();
  const path = `${API_BASE}/workflow-runs${qs ? `?${qs}` : ""}`;

  const res = await fetch(path, {
    method: "GET",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({
      errors: [{ code: "UNKNOWN", message: res.statusText }],
    }));
    throw err;
  }

  return (await res.json()) as WorkflowRunListResponse;
}
