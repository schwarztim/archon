import type { ApiResponse } from "@/types";
import type { Execution, ExecutionStatus } from "@/types/models";
import { apiGet, apiPost, type PaginationParams } from "./client";

/** List executions */
export async function listExecutions(
  params: PaginationParams & { agent_id?: string; status?: ExecutionStatus } = {},
): Promise<ApiResponse<Execution[]>> {
  return apiGet<Execution[]>("/executions", params);
}

/** Get a single execution */
export async function getExecution(
  id: string,
): Promise<ApiResponse<Execution>> {
  return apiGet<Execution>(`/executions/${id}`);
}

/** Start a new execution */
export async function startExecution(payload: {
  agent_id: string;
  input: Record<string, unknown>;
}): Promise<ApiResponse<Execution>> {
  return apiPost<Execution>("/execute", payload);
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
export async function cancelExecution(
  id: string,
): Promise<ApiResponse<Execution>> {
  return apiPost<Execution>(`/executions/${id}/cancel`, {});
}
