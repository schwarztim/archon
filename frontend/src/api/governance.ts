import type { ApiResponse } from "@/types";
import type {
  CompliancePolicy,
  ComplianceRecord,
  AuditEntry,
  Agent,
} from "@/types/models";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

// ── Types ──────────────────────────────────────────────────────────────

export interface RegistryAgent {
  id: string;
  agent_id: string;
  owner: string;
  department: string;
  approval_status: string;
  models_used: string[];
  data_accessed: string[];
  risk_level: string;
  registered_at: string;
  updated_at: string;
  compliance_status: string;
  compliance_score: number;
  risk_score: number;
  total_scans: number;
}

export interface AgentDetail {
  registry: RegistryAgent;
  compliance_history: ComplianceRecord[];
  compliance_score: number;
  compliance_status: string;
  risk_score: number;
  total_scans: number;
  passed_scans: number;
}

export interface ScanResult {
  agent_id: string;
  records: ComplianceRecord[];
  compliance_score: number;
  total_policies: number;
  passed: number;
  failed: number;
  scanned_at: string;
}

export interface ApprovalRequest {
  id: string;
  agent_id: string;
  requester_id: string | null;
  requester_name: string;
  agent_name: string;
  action: string;
  status: string;
  approval_rule: string;
  reviewers: string[];
  decisions: Array<{
    reviewer: string;
    decision: string;
    comment: string;
    decided_at: string;
  }>;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

// ── Policy CRUD ────────────────────────────────────────────────────────

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

// ── Compliance ─────────────────────────────────────────────────────────

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

// ── Audit Trail ────────────────────────────────────────────────────────

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

// ── Agent Registry (legacy) ────────────────────────────────────────────

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

// ── Registry Dashboard ─────────────────────────────────────────────────

/** List agents with compliance status for registry dashboard */
export async function listRegistry(
  params: PaginationParams = {},
): Promise<ApiResponse<RegistryAgent[]>> {
  return apiGet<RegistryAgent[]>("/governance/registry", params);
}

/** Get agent detail with compliance history */
export async function getRegistryDetail(
  agentId: string,
): Promise<ApiResponse<AgentDetail>> {
  return apiGet<AgentDetail>(`/governance/registry/${agentId}`);
}

/** Run compliance scan for an agent */
export async function scanAgent(
  agentId: string,
): Promise<ApiResponse<ScanResult>> {
  return apiPost<ScanResult>(`/governance/scan/${agentId}`, {});
}

// ── Approvals ──────────────────────────────────────────────────────────

/** List approval requests */
export async function listApprovals(
  params: PaginationParams & { status?: string } = {},
): Promise<ApiResponse<ApprovalRequest[]>> {
  return apiGet<ApprovalRequest[]>("/governance/approvals", params);
}

/** Create an approval request */
export async function createApproval(payload: {
  agent_id: string;
  agent_name?: string;
  action?: string;
  approval_rule?: string;
  reviewers?: string[];
  comment?: string;
}): Promise<ApiResponse<ApprovalRequest>> {
  return apiPost<ApprovalRequest>("/governance/approvals", payload);
}

/** Approve an approval request */
export async function approveRequest(
  id: string,
  comment: string = "",
): Promise<ApiResponse<ApprovalRequest>> {
  return apiPost<ApprovalRequest>(`/governance/approvals/${id}/approve`, { comment });
}

/** Reject an approval request */
export async function rejectRequest(
  id: string,
  comment: string = "",
): Promise<ApiResponse<ApprovalRequest>> {
  return apiPost<ApprovalRequest>(`/governance/approvals/${id}/reject`, { comment });
}

/** Get audit logs (from audit-logs endpoint) */
export async function getAuditLogs(
  params: PaginationParams & {
    action?: string;
    resource_type?: string;
    search?: string;
    date_from?: string;
    date_to?: string;
  } = {},
): Promise<ApiResponse<AuditEntry[]>> {
  return apiGet<AuditEntry[]>("/audit-logs/", params);
}
