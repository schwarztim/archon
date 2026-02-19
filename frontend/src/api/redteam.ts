import type { ApiResponse } from "@/types";
import type { RedTeamCampaign, RedTeamResult } from "@/types/models";
import { apiGet, apiPost } from "./client";

/** POST /security/scan — start a security scan */
export async function startScan(payload: {
  agent_id: string;
  attack_types: string[];
  name?: string;
}): Promise<ApiResponse<RedTeamCampaign>> {
  return apiPost<RedTeamCampaign>("/security/scan", payload);
}

/** GET /security/scan/{id} — get scan result */
export async function getScanResult(
  scanId: string,
): Promise<ApiResponse<RedTeamResult>> {
  return apiGet<RedTeamResult>(`/security/scan/${scanId}`);
}

/** GET /security/scan/{id}/sarif — get SARIF report */
export async function getScanSarif(
  scanId: string,
): Promise<ApiResponse<unknown>> {
  return apiGet<unknown>(`/security/scan/${scanId}/sarif`);
}

/** GET /agents/{agent_id}/security/history — agent security history */
export async function getAgentSecurityHistory(
  agentId: string,
): Promise<ApiResponse<RedTeamCampaign[]>> {
  return apiGet<RedTeamCampaign[]>(`/agents/${agentId}/security/history`);
}
