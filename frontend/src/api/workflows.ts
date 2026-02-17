import type { ApiResponse } from "@/types";
import { apiGet, apiPost, apiPut, apiDelete, type PaginationParams } from "./client";

// ─── Types ───────────────────────────────────────────────────────────

export interface WorkflowStep {
  step_id: string;
  name: string;
  agent_id: string;
  config: Record<string, unknown>;
  depends_on: string[];
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  group_id: string;
  group_name: string;
  steps: WorkflowStep[];
  schedule: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  status: "pending" | "running" | "completed" | "failed";
  started_at: string;
  completed_at: string | null;
  triggered_by: string;
}

export interface WorkflowCreatePayload {
  name: string;
  description: string;
  group_id: string;
  group_name: string;
  steps: {
    name: string;
    agent_id: string;
    config: Record<string, unknown>;
    depends_on: string[];
  }[];
  schedule: string | null;
  is_active: boolean;
  created_by: string;
}

export interface WorkflowUpdatePayload {
  name?: string;
  description?: string;
  group_id?: string;
  group_name?: string;
  steps?: {
    name: string;
    agent_id: string;
    config: Record<string, unknown>;
    depends_on: string[];
  }[];
  schedule?: string | null;
  is_active?: boolean;
}

// ─── API calls ───────────────────────────────────────────────────────

export async function listWorkflows(
  params: PaginationParams & { group_id?: string; search?: string; is_active?: boolean } = {},
): Promise<ApiResponse<Workflow[]>> {
  return apiGet<Workflow[]>("/workflows/", params);
}

export async function getWorkflow(id: string): Promise<ApiResponse<Workflow>> {
  return apiGet<Workflow>(`/workflows/${id}`);
}

export async function createWorkflow(
  payload: WorkflowCreatePayload,
): Promise<ApiResponse<Workflow>> {
  return apiPost<Workflow>("/workflows/", payload);
}

export async function updateWorkflow(
  id: string,
  payload: WorkflowUpdatePayload,
): Promise<ApiResponse<Workflow>> {
  return apiPut<Workflow>(`/workflows/${id}`, payload);
}

export async function deleteWorkflow(id: string): Promise<void> {
  return apiDelete(`/workflows/${id}`);
}

export async function executeWorkflow(
  id: string,
): Promise<ApiResponse<WorkflowRun>> {
  return apiPost<WorkflowRun>(`/workflows/${id}/execute`, {});
}

export async function listWorkflowRuns(
  id: string,
  params: PaginationParams = {},
): Promise<ApiResponse<WorkflowRun[]>> {
  return apiGet<WorkflowRun[]>(`/workflows/${id}/runs`, params);
}
