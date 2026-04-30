/**
 * Frontend client for the run-events API.
 *
 * Backend routes:
 *   - GET /api/v1/workflow-runs/{run_id}/events            — paginated event list
 *   - GET /api/v1/executions/{run_id}/events               — alias of the above
 *   - GET /api/v1/workflow-runs/{run_id}/events/verify     — chain integrity check
 *   - WS  /ws/runs/{run_id}/events                         — real-time event stream
 *     (implemented per ADR-002; clients should treat the HTTP poll loop
 *     as the canonical fallback when WS is unavailable)
 */

import type {
  ChainVerifyResponse,
  EventsResponse,
  EventType,
  WorkflowRunEvent,
} from "@/types/events";

const API_BASE = "/api/v1";

/** Query params for ``listRunEvents``. */
export interface ListRunEventsParams {
  /** Server defaults to -1 (i.e. start of chain). */
  after_sequence?: number;
  /** Server clamps to [1, 500]; default 100. */
  limit?: number;
  /**
   * Optional CSV filter — when set the server returns only events whose
   * ``event_type`` is in this list. The hash chain is still verified
   * over the *unfiltered* page (per backend behaviour).
   */
  event_types?: EventType[];
}

/** Page of events for ``run_id``. */
export async function listRunEvents(
  runId: string,
  opts: ListRunEventsParams = {},
): Promise<EventsResponse> {
  const sp = new URLSearchParams();
  if (opts.after_sequence !== undefined) {
    sp.set("after_sequence", String(opts.after_sequence));
  }
  if (opts.limit !== undefined) {
    sp.set("limit", String(opts.limit));
  }
  if (opts.event_types && opts.event_types.length > 0) {
    sp.set("event_types", opts.event_types.join(","));
  }
  const qs = sp.toString();
  const path = `${API_BASE}/workflow-runs/${encodeURIComponent(runId)}/events${
    qs ? `?${qs}` : ""
  }`;

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

  return (await res.json()) as EventsResponse;
}

/** Verify the hash-chain for an entire run. */
export async function verifyEventChain(
  runId: string,
): Promise<ChainVerifyResponse> {
  const path = `${API_BASE}/workflow-runs/${encodeURIComponent(
    runId,
  )}/events/verify`;

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

  return (await res.json()) as ChainVerifyResponse;
}

/**
 * Subscribe to a run's event stream over WebSocket.
 *
 * Returns an ``unsubscribe`` callback the caller invokes to close the
 * socket. The WS path follows the same convention as
 * ``connectExecutionWebSocket`` in ``api/executions.ts``.
 */
export function subscribeRunEvents(
  runId: string,
  onEvent: (e: WorkflowRunEvent) => void,
  onClose?: () => void,
  onError?: (error: Event) => void,
): { unsubscribe: () => void } {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const token = (typeof document !== "undefined" ? document.cookie : "")
    .split("; ")
    .find((c) => c.startsWith("access_token="))
    ?.split("=")[1];

  const url = `${protocol}//${window.location.host}/ws/runs/${encodeURIComponent(
    runId,
  )}/events${token ? `?token=${token}` : ""}`;

  const ws = new WebSocket(url);

  ws.onmessage = (msg) => {
    try {
      const raw = JSON.parse(msg.data) as
        | { type?: string; data?: WorkflowRunEvent }
        | WorkflowRunEvent;
      // Accept both wrapped (``{type:"event", data:{...}}``) and raw shapes.
      const candidate =
        raw && typeof raw === "object" && "data" in raw && raw.data
          ? raw.data
          : (raw as WorkflowRunEvent);
      if (candidate && typeof candidate === "object" && "event_type" in candidate) {
        onEvent(candidate);
      }
    } catch {
      // Ignore malformed messages — same behaviour as the executions WS.
    }
  };

  ws.onclose = () => onClose?.();
  ws.onerror = (err) => onError?.(err);

  return {
    unsubscribe: () => {
      if (
        ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING
      ) {
        ws.close();
      }
    },
  };
}
