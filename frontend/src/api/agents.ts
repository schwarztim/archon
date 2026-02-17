import type {
  AgentDefinition,
  ApiResponse,
  AppNode,
  AppEdge,
} from "@/types";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

/** Fetch all agent definitions (paginated) */
export async function listAgents(
  limit = 20,
  offset = 0,
): Promise<ApiResponse<AgentDefinition[]>> {
  return apiGet<AgentDefinition[]>("/agents/", { limit, offset });
}

/** Fetch a single agent definition */
export async function getAgent(
  id: string,
): Promise<ApiResponse<AgentDefinition>> {
  return apiGet<AgentDefinition>(`/agents/${id}`);
}

/** Create a new agent definition */
export async function createAgent(payload: {
  name: string;
  description?: string;
  nodes: AppNode[];
  edges: AppEdge[];
}): Promise<ApiResponse<AgentDefinition>> {
  return apiPost<AgentDefinition>("/agents/", payload);
}

/** Update an existing agent definition */
export async function updateAgent(
  id: string,
  payload: {
    name?: string;
    description?: string;
    nodes?: AppNode[];
    edges?: AppEdge[];
  },
): Promise<ApiResponse<AgentDefinition>> {
  return apiPut<AgentDefinition>(`/agents/${id}`, payload);
}

/** Delete an agent definition */
export async function deleteAgent(id: string): Promise<void> {
  return apiDelete(`/agents/${id}`);
}

/** Execute an agent (trigger a run) */
export async function runAgent(
  agentId: string,
  input?: Record<string, unknown>,
): Promise<ApiResponse<{ runId: string }>> {
  return apiPost<{ runId: string }>("/execute", {
    agent_id: agentId,
    input: input ?? {},
  });
}
