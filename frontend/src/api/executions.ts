import type { ApiResponse } from "@/types";
import type { Execution, ExecutionStatus } from "@/types/models";
import { apiGet, apiPost, apiDelete, type PaginationParams } from "./client";

/** List executions */
export async function listExecutions(
  params: PaginationParams & { agent_id?: string; status?: ExecutionStatus } = {},
): Promise<ApiResponse<Execution[]>> {
  return apiGet<Execution[]>("/executions", params);
}

/** Get a single execution (enhanced with agent name and metrics summary) */
export async function getExecution(
  id: string,
): Promise<ApiResponse<Execution & { agent_name?: string; metrics_summary?: { total_steps: number; completed_steps: number; failed_steps: number } }>> {
  return apiGet<Execution & { agent_name?: string; metrics_summary?: { total_steps: number; completed_steps: number; failed_steps: number } }>(`/executions/${id}`);
}

/** Start a new execution */
export async function startExecution(payload: {
  agent_id: string;
  input: Record<string, unknown>;
}): Promise<ApiResponse<Execution>> {
  return apiPost<Execution>("/execute", payload);
}

/** Create and run an agent execution (new enterprise endpoint) */
export async function createExecution(payload: {
  agent_id: string;
  input_data: Record<string, unknown>;
  config_overrides?: Record<string, unknown>;
}): Promise<ApiResponse<Execution>> {
  return apiPost<Execution>("/executions", payload);
}

/** Execute an agent via the convenience endpoint */
export async function executeAgent(
  agentId: string,
  inputData: Record<string, unknown>,
): Promise<ApiResponse<Execution>> {
  return apiPost<Execution>(`/agents/${agentId}/execute`, {
    input_data: inputData,
  });
}

/** Cancel a running execution */
// TODO: No backend route for POST /executions/{id}/cancel exists yet
export async function cancelExecution(
  id: string,
): Promise<ApiResponse<Execution>> {
  return apiPost<Execution>(`/executions/${id}/cancel`, {});
}

/** Replay an execution with same or modified input */
export async function replayExecution(
  id: string,
  payload?: {
    input_override?: Record<string, unknown>;
    config_overrides?: Record<string, unknown>;
  },
): Promise<ApiResponse<Execution>> {
  return apiPost<Execution>(`/executions/${id}/replay`, payload ?? {});
}

/** Delete an execution */
// TODO: No backend route for DELETE /executions/{id} exists yet
export async function deleteExecution(id: string): Promise<void> {
  return apiDelete(`/executions/${id}`);
}

/** WebSocket event types for execution streaming */
export type ExecutionEventType =
  | "llm_stream_token"
  | "tool_call"
  | "tool_result"
  | "agent_start"
  | "agent_complete"
  | "error"
  | "cost_update"
  | "ping"
  | "pong"
  // Legacy HTTP-style event types (used by connectExecutionWebSocket callers)
  | "execution.started"
  | "step.started"
  | "step.completed"
  | "step.failed"
  | "tool.called"
  | "llm.response"
  | "execution.completed"
  | "execution.failed";

/** Canonical execution event shape sent by the backend WebSocket */
export interface ExecutionEvent {
  /** Unique event identifier (UUID) for replay deduplication */
  id: string;
  type: ExecutionEventType;
  timestamp: string;
  /** Type-specific event payload */
  payload: Record<string, unknown>;
  /** Running total cost in USD (present on cost_update events) */
  cost?: number;
  /** LLM stream token text (present on llm_stream_token events) */
  token?: string;
}

/**
 * Connect to WebSocket for real-time execution updates.
 * Returns cleanup function to close the connection.
 */
export function connectExecutionWebSocket(
  executionId: string,
  onEvent: (event: ExecutionEvent) => void,
  onClose?: () => void,
  onError?: (error: Event) => void,
): () => void {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const token = document.cookie
    .split("; ")
    .find((c) => c.startsWith("access_token="))
    ?.split("=")[1];

  const url = `${protocol}//${window.location.host}/ws/executions/${executionId}${token ? `?token=${token}` : ""}`;
  const ws = new WebSocket(url);

  ws.onmessage = (event) => {
    try {
      // Backend sends: { event_id, type, timestamp, data, ... }
      // Normalize to ExecutionEvent shape: { id, type, timestamp, payload, cost?, token? }
      const raw = JSON.parse(event.data) as {
        event_id?: string;
        type: ExecutionEventType;
        timestamp: string;
        data?: Record<string, unknown>;
        cost?: number;
        token?: string;
      };
      const mapped: ExecutionEvent = {
        id: raw.event_id ?? "",
        type: raw.type,
        timestamp: raw.timestamp,
        payload: raw.data ?? {},
        cost: raw.cost ?? (typeof raw.data?.total_cost_usd === "number" ? raw.data.total_cost_usd : undefined),
        token: raw.token ?? (typeof raw.data?.token === "string" ? raw.data.token : undefined),
      };
      onEvent(mapped);
    } catch {
      // Ignore malformed messages
    }
  };

  ws.onclose = () => onClose?.();
  ws.onerror = (err) => onError?.(err);

  return () => {
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
      ws.close();
    }
  };
}
