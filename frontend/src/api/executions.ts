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
  | "execution.started"
  | "step.started"
  | "step.completed"
  | "step.failed"
  | "tool.called"
  | "llm.response"
  | "execution.completed"
  | "execution.failed";

export interface ExecutionEvent {
  type: ExecutionEventType;
  data: Record<string, unknown>;
  timestamp: string;
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
      const parsed = JSON.parse(event.data) as ExecutionEvent;
      onEvent(parsed);
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
