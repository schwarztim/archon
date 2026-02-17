import type { ApiResponse } from "@/types";
import type {
  CompliancePolicy,
  ComplianceRecord,
  AuditEntry,
  Agent,
} from "@/types/models";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

/** List governance policies */
export async function listPolicies(
  params: PaginationParams = {},
): Promise<ApiResponse<CompliancePolicy[]>> {
  return apiGet<CompliancePolicy[]>("/governance/policies", params);
}

/** Create a governance policy */
export async function createPolicy(
  payload: Omit<CompliancePolicy, "id" | "created_at" | "updated_at">,
): Promise<ApiResponse<CompliancePolicy>> {
  return apiPost<CompliancePolicy>("/governance/policies", payload);
}

/** Get a governance policy */
export async function getPolicy(
  id: string,
): Promise<ApiResponse<CompliancePolicy>> {
  return apiGet<CompliancePolicy>(`/governance/policies/${id}`);
}

/** Update a governance policy */
export async function updatePolicy(
  id: string,
  payload: Partial<Omit<CompliancePolicy, "id" | "created_at" | "updated_at">>,
): Promise<ApiResponse<CompliancePolicy>> {
  return apiPut<CompliancePolicy>(`/governance/policies/${id}`, payload);
}

/** Delete a governance policy */
export async function deletePolicy(id: string): Promise<void> {
  return apiDelete(`/governance/policies/${id}`);
}

/** Check compliance for an agent */
export async function checkCompliance(
  agentId: string,
  policyIds?: string[],
): Promise<ApiResponse<ComplianceRecord>> {
  return apiPost<ComplianceRecord>("/governance/compliance/check", {
    agent_id: agentId,
    policy_ids: policyIds,
  });
}

/** Get audit trail */
export async function getAuditTrail(
  params: PaginationParams & {
    actor?: string;
    resource_type?: string;
    resource_id?: string;
  } = {},
): Promise<ApiResponse<AuditEntry[]>> {
  return apiGet<AuditEntry[]>("/governance/audit", params);
}

/** Register an agent with governance */
export async function registerAgent(payload: {
  agent_id: string;
  name: string;
  owner: string;
  classification?: string;
}): Promise<ApiResponse<Agent>> {
  return apiPost<Agent>("/governance/agents", payload);
}

/** List registered agents */
export async function listRegisteredAgents(
  params: PaginationParams = {},
): Promise<ApiResponse<Agent[]>> {
  return apiGet<Agent[]>("/governance/agents", params);
}
