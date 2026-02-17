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
  graph_definition?: {
    nodes: { id: string; type: string; position: { x: number; y: number }; data: Record<string, unknown> }[];
    edges: { id: string; source: string; target: string; label?: string }[];
  } | null;
  schedule: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface WorkflowRunStep {
  id: string;
  run_id: string;
  step_id: string;
  name: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  started_at: string;
  completed_at: string | null;
  duration_ms: number;
  input_data: Record<string, unknown>;
  output_data: Record<string, unknown> | null;
  agent_execution_id: string | null;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  status: "pending" | "running" | "completed" | "failed";
  trigger_type: "manual" | "schedule" | "webhook";
  started_at: string;
  completed_at: string | null;
  triggered_by: string;
  duration_ms: number | null;
  steps?: WorkflowRunStep[];
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
  graph_definition?: {
    nodes: { id: string; type: string; position: { x: number; y: number }; data: Record<string, unknown> }[];
    edges: { id: string; source: string; target: string; label?: string }[];
  } | null;
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
  graph_definition?: {
    nodes: { id: string; type: string; position: { x: number; y: number }; data: Record<string, unknown> }[];
    edges: { id: string; source: string; target: string; label?: string }[];
  } | null;
  schedule?: string | null;
  is_active?: boolean;
}

export interface SchedulePayload {
  cron: string;
  timezone: string;
}

export interface SchedulePreview {
  next_runs: string[];
  cron: string | null;
  timezone: string;
}

export interface ScheduleRecord {
  workflow_id: string;
  cron: string;
  timezone: string;
  created_at: string;
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
  params: PaginationParams & { status?: string; trigger_type?: string } = {},
): Promise<ApiResponse<WorkflowRun[]>> {
  return apiGet<WorkflowRun[]>(`/workflows/${id}/runs`, params);
}

export async function getWorkflowRun(
  workflowId: string,
  runId: string,
): Promise<ApiResponse<WorkflowRun>> {
  return apiGet<WorkflowRun>(`/workflows/${workflowId}/runs/${runId}`);
}

export async function setWorkflowSchedule(
  id: string,
  payload: SchedulePayload,
): Promise<ApiResponse<ScheduleRecord>> {
  return apiPut<ScheduleRecord>(`/workflows/${id}/schedule`, payload);
}

export async function removeWorkflowSchedule(id: string): Promise<void> {
  return apiDelete(`/workflows/${id}/schedule`);
}

export async function previewSchedule(
  id: string,
  count: number = 5,
): Promise<ApiResponse<SchedulePreview>> {
  return apiGet<SchedulePreview>(`/workflows/${id}/schedule/preview`, { count });
}

/** Create a WebSocket connection for execution streaming. */
export function createExecutionWebSocket(
  workflowId: string,
  execId: string,
): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${window.location.host}/api/v1/workflows/${workflowId}/executions/${execId}`;
  return new WebSocket(url);
}
