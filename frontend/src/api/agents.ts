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

/** Full agent specification for create/update */
export interface AgentSpec {
  name: string;
  description?: string;
  tags?: string[];
  group_id?: string | null;
  definition?: Record<string, unknown>;
  llm_config?: {
    provider: string;
    model_id: string;
    temperature?: number;
    max_tokens?: number;
    system_prompt?: string;
  } | null;
  tools?: Array<{ name: string; type?: string; config?: Record<string, unknown> }> | null;
  rag_config?: {
    enabled: boolean;
    collection?: string;
    embedding_model?: string;
    chunk_strategy?: string;
    chunk_size?: number;
    chunk_overlap?: number;
    top_k?: number;
  } | null;
  mcp_config?: {
    enabled: boolean;
    tools?: string[];
  } | null;
  security_policy?: {
    dlp_enabled?: boolean;
    guardrail_policies?: string[];
    max_cost_per_run?: number;
    allowed_domains?: string[];
    pii_handling?: string;
  } | null;
  connectors?: string[];
  nodes?: AppNode[];
  edges?: AppEdge[];
}

/** Create a new agent definition */
export async function createAgent(
  payload: AgentSpec,
): Promise<ApiResponse<AgentDefinition>> {
  return apiPost<AgentDefinition>("/agents/", payload);
}

/** Update an existing agent definition */
export async function updateAgent(
  id: string,
  payload: Partial<AgentSpec>,
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
