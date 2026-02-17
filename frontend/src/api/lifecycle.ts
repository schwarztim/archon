import type { ApiResponse } from "@/types";
import type {
  DeploymentRecord,
  HealthCheck,
  DeploymentStage,
} from "@/types/models";
import { apiGet, apiPost, type PaginationParams } from "./client";

/** List deployments */
export async function listDeployments(
  params: PaginationParams & { agent_id?: string; stage?: DeploymentStage } = {},
): Promise<ApiResponse<DeploymentRecord[]>> {
  return apiGet<DeploymentRecord[]>("/lifecycle/deployments", params);
}

/** Deploy an agent version */
export async function deploy(payload: {
  agent_id: string;
  version: number;
  stage: DeploymentStage;
  replicas?: number;
  metadata?: Record<string, unknown>;
}): Promise<ApiResponse<DeploymentRecord>> {
  return apiPost<DeploymentRecord>("/lifecycle/deployments", payload);
}

/** Promote a deployment to the next stage */
export async function promote(
  deploymentId: string,
  targetStage: DeploymentStage,
): Promise<ApiResponse<DeploymentRecord>> {
  return apiPost<DeploymentRecord>(`/lifecycle/deployments/${deploymentId}/promote`, {
    target_stage: targetStage,
  });
}

/** Scale a deployment */
export async function scale(
  deploymentId: string,
  replicas: number,
): Promise<ApiResponse<DeploymentRecord>> {
  return apiPost<DeploymentRecord>(`/lifecycle/deployments/${deploymentId}/scale`, {
    replicas,
  });
}

/** Rollback a deployment */
export async function rollback(
  deploymentId: string,
  targetVersion?: number,
): Promise<ApiResponse<DeploymentRecord>> {
  return apiPost<DeploymentRecord>(`/lifecycle/deployments/${deploymentId}/rollback`, {
    target_version: targetVersion,
  });
}

/** Retire a deployment */
export async function retire(
  deploymentId: string,
): Promise<ApiResponse<DeploymentRecord>> {
  return apiPost<DeploymentRecord>(`/lifecycle/deployments/${deploymentId}/retire`, {});
}

/** Record a health check */
export async function recordHealthCheck(payload: {
  deployment_id: string;
  status: HealthCheck["status"];
  latency_ms: number;
  details?: Record<string, unknown>;
}): Promise<ApiResponse<HealthCheck>> {
  return apiPost<HealthCheck>(`/lifecycle/deployments/${payload.deployment_id}/health`, payload);
}

/** Get deployment by ID */
export async function getDeployment(
  id: string,
): Promise<ApiResponse<DeploymentRecord>> {
  return apiGet<DeploymentRecord>(`/lifecycle/deployments/${id}`);
}

/** List lifecycle events */
export async function listEvents(
  params: PaginationParams & { deployment_id?: string; agent_id?: string; event_type?: string } = {},
): Promise<ApiResponse<unknown[]>> {
  return apiGet<unknown[]>("/lifecycle/events", params);
}
