import type { ApiResponse } from "@/types";
import type {
  DeploymentRecord,
  HealthCheck,
  DeploymentStage,
  PipelineStageInfo,
  EnvironmentInfo,
  ConfigDiff,
  DeploymentHistoryEntry,
  HealthMetrics,
  ApprovalGate,
} from "@/types/models";
import { apiGet, apiPost, apiPut, type PaginationParams } from "./client";

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

/** Enhanced deploy with strategy */
export async function enhancedDeploy(payload: {
  agent_id: string;
  version_id: string;
  environment: string;
  strategy_type: string;
  replicas?: number;
  canary_percentage?: number;
  blue_green_preview?: boolean;
  rollback_threshold?: number;
  pre_deploy_checks?: boolean;
  config?: Record<string, unknown>;
}): Promise<ApiResponse<Record<string, unknown>>> {
  return apiPost<Record<string, unknown>>("/lifecycle/deploy", payload);
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

/** Promote deployment to next pipeline stage */
export async function promoteToNextStage(
  deploymentId: string,
): Promise<ApiResponse<Record<string, unknown>>> {
  return apiPost<Record<string, unknown>>(`/lifecycle/promote/${deploymentId}`, {});
}

/** Demote deployment to previous pipeline stage */
export async function demoteToPreviousStage(
  deploymentId: string,
): Promise<ApiResponse<Record<string, unknown>>> {
  return apiPost<Record<string, unknown>>(`/lifecycle/demote/${deploymentId}`, {});
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

/** Rollback via v1 endpoint */
export async function rollbackV1(
  deploymentId: string,
  reason?: string,
): Promise<ApiResponse<Record<string, unknown>>> {
  return apiPost<Record<string, unknown>>(`/lifecycle/rollback/${deploymentId}`, {
    reason: reason ?? "manual rollback",
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

/** Get pipeline stages with deployed versions */
export async function getPipeline(): Promise<ApiResponse<PipelineStageInfo[]>> {
  return apiGet<PipelineStageInfo[]>("/lifecycle/pipeline");
}

/** List environments with health info */
export async function listEnvironments(): Promise<ApiResponse<EnvironmentInfo[]>> {
  return apiGet<EnvironmentInfo[]>("/lifecycle/environments");
}

/** Get config diff between environments */
export async function getConfigDiff(
  source: string,
  target: string,
): Promise<ApiResponse<ConfigDiff>> {
  return apiGet<ConfigDiff>("/lifecycle/diff", { source, target });
}

/** Get deployment history for an environment */
export async function getDeploymentHistory(
  environment: string,
): Promise<ApiResponse<DeploymentHistoryEntry[]>> {
  return apiGet<DeploymentHistoryEntry[]>(`/lifecycle/history/${environment}`);
}

/** Configure approval gates */
export async function configureGates(
  gates: Partial<ApprovalGate>[],
): Promise<ApiResponse<ApprovalGate[]>> {
  return apiPut<ApprovalGate[]>("/lifecycle/gates", { gates });
}

/** Get post-deployment health metrics */
export async function getDeploymentHealth(
  deploymentId: string,
): Promise<ApiResponse<HealthMetrics>> {
  return apiGet<HealthMetrics>(`/lifecycle/health/${deploymentId}`);
}
