/**
 * Frontend client for the operator signal-injection endpoint.
 *
 * Backend route: ``POST /api/v1/executions/{run_id}/signals`` — admin-only
 * per ``backend/app/routes/approvals.py::inject_signal``. Used by support
 * to deliver ``input.provided`` for a paused ``humanInputNode`` or to
 * ``cancel`` a paused run out-of-band.
 */

import type { Signal, SignalInjectArgs, SignalInjectResponse } from "@/types/signals";

const API_BASE = "/api/v1";

async function readError(res: Response): Promise<unknown> {
  return res.json().catch(() => ({
    errors: [{ code: "UNKNOWN", message: res.statusText }],
  }));
}

/**
 * Inject a signal targeting a run. Returns the persisted Signal-shaped
 * payload (id + run_id + signal_type — full Signal includes more fields
 * but the API surface returns the slimmer shape).
 *
 * Admins only — the backend returns 403 to non-admin callers.
 */
export async function sendSignal(
  runId: string,
  args: SignalInjectArgs,
): Promise<Pick<Signal, "id" | "run_id" | "signal_type">> {
  const res = await fetch(
    `${API_BASE}/executions/${encodeURIComponent(runId)}/signals`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        signal_type: args.signal_type,
        payload: args.payload ?? {},
        step_id: args.step_id ?? null,
      }),
    },
  );

  if (!res.ok) throw await readError(res);

  const body = (await res.json()) as SignalInjectResponse;
  return {
    id: body.data.signal_id,
    run_id: body.data.run_id,
    signal_type: body.data.signal_type,
  };
}
